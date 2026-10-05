"""pydantic-settings, TOML (Appendix E) (§10.1).

Implements FR-AGT-03: a TOML config file whose keys are exactly the documented
Appendix E reference. Unknown keys are rejected (fail fast on typos) — the
Appendix E table is the contract; adding keys requires a spec change (§1.5).

Resolution order for the config file path:
  1. explicit argument to `load_settings()`
  2. `LOCALMESH_CONFIG` environment variable
  3. `<data_dir>/config.toml` if it exists
  4. otherwise: documented defaults (the file is optional)

`data_dir` default is a [DESIGN] per-OS convention (Appendix E: "default
per-OS"); the directory is created owner-only (§14.1 file-permission rule).
"""

from __future__ import annotations

import os
import stat
import sys
import tomllib
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

CONFIG_ENV_VAR = "LOCALMESH_CONFIG"

# §10.3 — the only Backend kinds v1 knows. M7 (FR-MM-02) adds the
# Whisper-class STT service as a dedicated `whisper` kind [DESIGN per
# FR-MM-02/S-13: "a separate Whisper-service adapter"].
BACKEND_KINDS: tuple[str, ...] = ("lmstudio", "ollama", "openai_compat", "whisper")

# §13.9 — the only Task types v1 knows (shape fixed at M0 stub, delivered M7).
TASK_TYPES: tuple[str, ...] = ("chat", "vision", "transcribe", "doc_qa")

# §13.5 — closed capability vocabulary; a value appears only if the Backend
# reports it or a user override sets it. No heuristic inference (§13.5).
CAPABILITY_VALUES: tuple[str, ...] = (
    "chat",
    "vision",
    "embedding",
    "speech_to_text",
    "tool_calling",
    "reasoning",
    "code",
)

# NFR-SEC-03 / SEC-N2 / §10.3: Backends are reachable on loopback only.
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}


class _StrictModel(BaseModel):
    """Base for config sections: unknown keys are typos, not extensions."""

    model_config = ConfigDict(extra="forbid")


class AgentConfig(_StrictModel):
    display_name: str = "LocalMesh Agent"
    data_dir: str = ""  # default per-OS (see default_data_dir)


class ListenConfig(_StrictModel):
    host: str = "0.0.0.0"  # public Mesh API; restrict to interfaces if desired
    port: int = Field(default=8443, ge=1, le=65535)
    admin_port: int = Field(default=8444, ge=1, le=65535)  # always bound to 127.0.0.1

    @model_validator(mode="after")
    def _ports_must_differ(self) -> ListenConfig:
        if self.port == self.admin_port:
            raise ValueError("listen.port and listen.admin_port must differ")
        return self


class TlsConfig(_StrictModel):
    rotate_on_start: bool = False  # Appendix E: never true by default


class PairingConfig(_StrictModel):
    ttl_seconds: int = Field(default=300, ge=1, le=600)  # FR-PAIR-02: ≤ 600 s
    require_confirmation: bool = True  # SAS approval on PC (FR-PAIR-04)


class LimitsConfig(_StrictModel):
    max_body_bytes: int = Field(default=2_097_152, gt=0)  # §13.8: 2 MiB
    per_device_active: int = Field(default=2, ge=1)  # §13.8
    max_queued: int = Field(default=8, ge=0)  # §13.8
    max_stream_seconds: int = Field(default=900, gt=0)  # §13.8: 15 min
    first_token_timeout_seconds: int = Field(default=120, gt=0)  # §10.3 rule 4


class MdnsConfig(_StrictModel):
    enabled: bool = True
    interfaces: list[str] = Field(default_factory=list)  # empty = default-route only


class BackendConfig(_StrictModel):
    """One `[[backends]]` entry (Appendix E; §10.3)."""

    id: str
    kind: str
    base_url: str
    enabled: bool = True
    auth_ref: str = ""  # keyring entry name, NOT the secret (§17.6)
    concurrency: int = Field(default=1, ge=1)  # §16.4 default 1

    @field_validator("kind")
    @classmethod
    def _known_kind(cls, value: str) -> str:
        if value not in BACKEND_KINDS:
            raise ValueError(f"backend kind must be one of {BACKEND_KINDS}, got {value!r}")
        return value

    @field_validator("base_url")
    @classmethod
    def _loopback_only(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError(f"backend base_url must be an http(s) URL, got {value!r}")
        if parsed.hostname not in _LOOPBACK_HOSTS:
            # NFR-SEC-03 / SEC-N2: Backends are reached via loopback only.
            raise ValueError(f"backend base_url must be loopback (§10.3), got {value!r}")
        return value

    @field_validator("id")
    @classmethod
    def _id_shape(cls, value: str) -> str:
        if not value or "::" in value:
            # mesh_model_id splits on "::"; a backend id must not contain it (§14.3).
            raise ValueError("backend id must be non-empty and must not contain '::'")
        return value


class ModelOverrideConfig(_StrictModel):
    """One `[[models.overrides]]` entry — the ONLY way to set metadata the
    Backend does not report (Appendix E; §13.5 source='user')."""

    mesh_model_id: str
    capabilities: list[str] = Field(default_factory=list)
    quality_rank: int | None = Field(default=None, ge=0, le=5)
    keep_warm: bool | None = None

    @field_validator("capabilities")
    @classmethod
    def _closed_vocabulary(cls, values: list[str]) -> list[str]:
        for value in values:
            if value not in CAPABILITY_VALUES:
                raise ValueError(
                    f"capability {value!r} not in §13.5 closed set {CAPABILITY_VALUES}"
                )
        return values


class ModelsConfig(_StrictModel):
    overrides: list[ModelOverrideConfig] = Field(default_factory=list)


class LoggingConfig(_StrictModel):
    level: str = "info"  # allow-list formatter always on (§17.10)


class TasksConfig(_StrictModel):
    """M7 durable Tasks (§13.9, FR-MM-04): attachment size caps, §13.9's
    ≤ 1 h result retention, per-task concurrency bound."""

    max_attachment_bytes: int = Field(default=10_485_760, gt=0)  # 10 MiB [DESIGN]
    result_retention_s: int = Field(default=3600, ge=30, le=3600)  # §13.9 ≤ 1 h
    max_concurrent: int = Field(default=2, ge=1)  # §13.8 spirit (per-device 2)


class RoutingConfig(_StrictModel):
    """M8 auto-routing (FR-RTE-01..03; §16.6 `[DESIGN — tunable]`).

    `model: "auto"` resolves via the §16.6 score. The four weights are the
    §16.6 defaults; they live here ("Weights live in config", §16.6). The
    classifier (FR-RTE-03) is EXPERIMENTAL and OFF by default (S-21: the
    classifier model is behind a flag); it can only REFINE the rule engine's
    required-set, never bypass it.
    """

    weight_quality: float = Field(default=0.40, ge=0, le=1)  # §16.6 verbatim
    weight_warmth: float = Field(default=0.25, ge=0, le=1)
    weight_speed: float = Field(default=0.20, ge=0, le=1)
    weight_queue: float = Field(default=0.15, ge=0, le=1)
    classifier_enabled: bool = False  # FR-RTE-03: off by default
    classifier_model: str = ""  # mesh_model_id of the classifier model

    @model_validator(mode="after")
    def _weights_sum_to_one(self) -> RoutingConfig:
        total = self.weight_quality + self.weight_warmth + self.weight_speed + self.weight_queue
        if abs(total - 1.0) > 1e-6:
            raise ValueError("routing weights must sum to 1.0 (§16.6)")
        return self


class AgentRuntimeConfig(_StrictModel):
    """M8 agent runtime / tool calling (FR-AGENT-RT; ADR-020).

    DISABLED by default (ADR-020 default-deny): `tools` on chat → 422 until
    the operator enables it. Tool execution is bounded (iterations, output
    bytes) and restricted to the built-in allow-listed, no-I/O tools.
    """

    enabled: bool = False  # ADR-020: default-deny
    max_iterations: int = Field(default=5, ge=1, le=10)  # ADR-020 bound
    max_tool_output_bytes: int = Field(default=4096, ge=256)  # ADR-020 bound


class ControlPlaneConfig(_StrictModel):
    """Optional M6 Control Plane (§12, FR-CP-01..04; §22.1 "optional").

    Off by default. When `enabled`, `url` (https) and `auth_ref` (the keyring
    entry holding the CP key, §17.6 — never the key itself) are REQUIRED so a
    half-configured agent fails fast at config load instead of syncing to a
    wrong place. The Agent remains authoritative (§12.1); the CP is never in
    the content path (ADR-001).
    """

    enabled: bool = False
    url: str = ""  # e.g. https://<project>.supabase.co [UNVERIFIED deployment]
    auth_ref: str = ""  # keyring entry name for the CP key (§17.6)
    heartbeat_interval_s: int = Field(default=60, ge=10, le=3600)  # §12.3: "default 60 s"

    @model_validator(mode="after")
    def _enabled_requires_target(self) -> ControlPlaneConfig:
        if self.enabled:
            parsed = urlparse(self.url)
            if parsed.scheme != "https" or not parsed.hostname:
                raise ValueError("control_plane.url must be an https URL when enabled")
            if not self.auth_ref:
                raise ValueError("control_plane.auth_ref is required when enabled (§17.6)")
        return self


class Settings(BaseSettings):
    """Agent settings — Appendix E layout."""

    model_config = SettingsConfigDict(
        env_prefix="LOCALMESH_", env_nested_delimiter="__", extra="forbid"
    )

    agent: AgentConfig = Field(default_factory=AgentConfig)
    listen: ListenConfig = Field(default_factory=ListenConfig)
    tls: TlsConfig = Field(default_factory=TlsConfig)
    pairing: PairingConfig = Field(default_factory=PairingConfig)
    limits: LimitsConfig = Field(default_factory=LimitsConfig)
    mdns: MdnsConfig = Field(default_factory=MdnsConfig)
    backends: list[BackendConfig] = Field(
        default_factory=lambda: [
            # Appendix E defaults (also FR-MOD-01 autodetect targets).
            BackendConfig(id="lmstudio", kind="lmstudio", base_url="http://127.0.0.1:1234"),
            BackendConfig(id="ollama", kind="ollama", base_url="http://127.0.0.1:11434"),
        ]
    )
    models: ModelsConfig = Field(default_factory=ModelsConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    tasks: TasksConfig = Field(default_factory=TasksConfig)  # §13.9 (M7)
    routing: RoutingConfig = Field(default_factory=RoutingConfig)  # §16.6 (M8)
    agent_runtime: AgentRuntimeConfig = Field(default_factory=AgentRuntimeConfig)  # ADR-020 (M8)
    control_plane: ControlPlaneConfig = Field(default_factory=ControlPlaneConfig)

    # -- data dir ----------------------------------------------------------

    def resolved_data_dir(self) -> Path:
        """`agent.data_dir` if set, else the per-OS default [DESIGN]."""
        if self.agent.data_dir:
            return Path(self.agent.data_dir)
        return default_data_dir()

    def ensure_data_dir(self) -> Path:
        """Create the data dir owner-only (§14.1: permissions owner-only).

        POSIX: mode 0o700. Windows: best-effort here — the ACL restriction to
        the service/user is completed by the installer (M9, §21.6); noted as a
        platform gap in the milestone report.
        """
        path = self.resolved_data_dir()
        path.mkdir(parents=True, exist_ok=True)
        if sys.platform != "win32":
            current = stat.S_IMODE(path.stat().st_mode)
            if current & 0o077:  # tighten only if group/other have any access
                os.chmod(path, current & ~0o077 | stat.S_IRWXU)
        return path


def default_data_dir() -> Path:
    """Per-OS default data dir [DESIGN — Appendix E leaves this to the platform].

    - Windows: %LOCALAPPDATA%\\LocalMesh\\agent
    - macOS:   ~/Library/Application Support/LocalMesh/agent
    - Linux:   $XDG_DATA_HOME/localmesh/agent  (default ~/.local/share/localmesh/agent)
    """
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "LocalMesh" / "agent"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "LocalMesh" / "agent"
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / "localmesh" / "agent"


def resolve_config_path(explicit: str | Path | None = None) -> Path:
    """Config file resolution order (module docstring)."""
    if explicit is not None:
        return Path(explicit)
    env = os.environ.get(CONFIG_ENV_VAR)
    if env:
        return Path(env)
    return default_data_dir() / "config.toml"


def read_toml(path: Path) -> dict[str, Any]:
    """Parse a TOML file into a dict (empty when the file does not exist)."""
    if not path.is_file():
        return {}
    return tomllib.loads(path.read_text(encoding="utf-8"))


def load_settings(config_path: str | Path | None = None) -> Settings:
    """Load settings from the resolved TOML file (defaults when absent)."""
    return Settings(**read_toml(resolve_config_path(config_path)))
