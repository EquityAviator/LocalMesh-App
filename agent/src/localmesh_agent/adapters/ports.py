"""Ports the core depends on (§10.1, §10.2) — signatures normative.

Layer position: bottom of the §10.1 dependency rule (`api → core → ports`;
QUESTION-101 interpretation: core MAY import `adapters.ports`, no other
`adapters.*`). Because this module sits below `core`, the shared data types
referenced by the port signatures are DEFINED here and re-exported by
`core/entities.py` (§10.1 "entities.py # Device, BackendModel, ModelEntry,
ChatRequest, ChatChunk, Stats…").

The §10.2 Protocol classes are copied verbatim from the spec; supporting data
types carry evidence tags from §6/§10.3/§13.5. Implementations arrive with
their WPs (§22.1): backends WP-05, hardware WP-15, discovery WP-11,
tailscale WP-14, store WP-04 (concrete `store/sqlite.py`).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import (
    TYPE_CHECKING,
    Any,
    Literal,
    NamedTuple,
    Protocol,
    TypedDict,
    runtime_checkable,
)

if TYPE_CHECKING:  # pragma: no cover - imports for type checking only
    from localmesh_agent.config import ModelOverrideConfig

# ---------------------------------------------------------------------------
# §10.2 BackendCaps (verbatim shape; closed vocabulary)
# ---------------------------------------------------------------------------


class BackendCaps(TypedDict):
    list_models: bool
    stream_chat: bool
    load_unload: bool
    keep_warm: bool
    embeddings: bool
    vision: bool
    audio_in: bool


# ---------------------------------------------------------------------------
# Shared data types (bottom layer — importable by core, api and adapters)
# ---------------------------------------------------------------------------

# §13.5 state vocabulary.
ModelState = Literal["loaded", "unloaded", "loading", "unknown"]
# §13.5 provenance vocabulary.
ValueSource = Literal["backend", "user", "unknown"]

# §10.3 rule 4 — timeouts [DESIGN defaults; configurable via Appendix E limits].
CONNECT_TIMEOUT_S = 3.0
DEFAULT_FIRST_TOKEN_TIMEOUT_S = 120.0
IDLE_CHUNK_TIMEOUT_S = 60.0
DEFAULT_TOTAL_STREAM_CAP_S = 900.0  # §13.8 max stream duration


@dataclass(frozen=True)
class TypedValue:
    """A nullable backend-reported value with provenance (§13.5)."""

    value: Any  # int | str | None at runtime; typed per usage
    source: ValueSource = "unknown"

    @staticmethod
    def unknown() -> TypedValue:
        return TypedValue(value=None, source="unknown")

    @staticmethod
    def backend(value: Any) -> TypedValue:
        return TypedValue(value=value, source="backend")


@dataclass(frozen=True)
class ChatMessage:
    """One chat message — string content in v1 (§13.6)."""

    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True)
class ChatRequest:
    """Normalized chat request (§13.6 allow-list; §13.2 API-CHAT-01)."""

    model: str  # mesh_model_id ("<backend_id>::<backend_model_id>", §14.3)
    backend_model_id: str  # resolved by the Router before the adapter is called
    messages: tuple[ChatMessage, ...]
    stream: bool = True
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    stop: tuple[str, ...] | None = None
    presence_penalty: float | None = None
    frequency_penalty: float | None = None
    seed: int | None = None
    client_request_id: str | None = None  # x_mesh.client_request_id (§13.6)


@dataclass(frozen=True)
class ChatChunk:
    """One streamed chunk from a Backend (OpenAI delta semantics)."""

    delta_content: str | None = None  # None when the chunk carries no text
    role: str | None = None  # e.g. "assistant" on the first delta
    finish_reason: str | None = None  # backend-reported finish reason
    usage_prompt_tokens: int | None = None  # Backend-reported usage if any (§13.7)
    usage_completion_tokens: int | None = None


@dataclass(frozen=True)
class BackendStatus:
    """Probe result (§10.2): up/down, version if known."""

    backend_id: str
    status: Literal["up", "down", "unknown"]
    version: str | None = None


@dataclass(frozen=True)
class BackendModel:
    """Normalized per-Backend model as the adapter reports it (§10.2, §13.5).

    Every field the Backend did not report stays None → the registry marks it
    `source:"unknown"`. Adapters MUST NOT guess from model names (§13.5, §16.3).
    """

    backend_model_id: str
    display_name: str | None = None
    state: ModelState = "unknown"
    modalities_input: tuple[str, ...] | None = None
    modalities_output: tuple[str, ...] | None = None
    capabilities: tuple[str, ...] | None = None
    context_length: int | None = None
    quantization: str | None = None
    parameter_size: str | None = None
    size_bytes: int | None = None
    vram_estimate_bytes: int | None = None
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class ServiceAd:
    """mDNS advertisement payload (§16.2; consumed by WP-11)."""

    agent_id: str
    display_name: str
    port: int
    txt: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class TailnetInfo:
    """Tailscale probe result (§6.3 `[ASSUMPTION]` fields; consumed by WP-14)."""

    state: str
    dns_name: str | None = None
    ips: tuple[str, ...] = ()


@dataclass(frozen=True)
class GpuInfo:
    """One GPU snapshot (all fields nullable; API-DEV-01 shape, WP-15)."""

    name: str | None = None
    vram_total_bytes: int | None = None
    vram_used_bytes: int | None = None
    utilization_pct: float | None = None
    temperature_c: float | None = None


@dataclass(frozen=True)
class HardwareInfo:
    """Best-effort hardware snapshot — unavailable fields stay None (§10.2)."""

    os_family: str | None = None
    os_version: str | None = None
    cpu_model: str | None = None
    logical_cores: int | None = None
    ram_total_bytes: int | None = None
    ram_available_bytes: int | None = None
    gpus: tuple[GpuInfo, ...] = ()


class CancelToken:
    """Cooperative cancellation for one generation (§10.4 Scheduler, §13.7).

    The API layer cancels on client disconnect or API-REQ-01; adapters poll
    `cancelled` between chunks and abort the upstream request ≤ 1 s (§13.7).
    """

    def __init__(self) -> None:
        self._event = asyncio.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    async def wait(self) -> None:
        await self._event.wait()


class SSEEvent(NamedTuple):
    """One parsed SSE event (data lines joined with '\n'; comments dropped)."""

    data: str


# ---------------------------------------------------------------------------
# §10.2 Protocols (verbatim signatures)
# ---------------------------------------------------------------------------


@runtime_checkable
class InferenceBackend(Protocol):
    """A local inference engine behind the Agent (§10.2)."""

    id: str  # stable: "lmstudio" | "ollama" | "openai:<name>"
    kind: str  # "lmstudio" | "ollama" | "openai_compat"
    caps: BackendCaps

    async def probe(self) -> BackendStatus:  # up/down, version if known
        ...

    async def list_models(self) -> list[BackendModel]:  # normalized, nullable fields
        ...

    def stream_chat(self, req: ChatRequest, cancel: CancelToken) -> AsyncIterator[ChatChunk]:
        """Stream chunks (async in §10.2; implemented as an async generator,
        PEP 525 — callers `async for` directly over the returned iterator)."""
        ...

    async def load_model(self, backend_model_id: str) -> None:  # raise UnsupportedCapability
        ...

    async def unload_model(self, backend_model_id: str) -> None: ...
    async def keep_warm(self, backend_model_id: str) -> None: ...


@runtime_checkable
class HardwareProbe(Protocol):
    async def snapshot(self) -> HardwareInfo:  # all fields Optional (§10.2)
        ...


@runtime_checkable
class DiscoveryAdvertiser(Protocol):
    async def start(self, ad: ServiceAd) -> None: ...
    async def stop(self) -> None: ...


@runtime_checkable
class TailnetProbe(Protocol):
    async def status(self) -> TailnetInfo | None:  # None if tailscale absent (§10.2)
        ...


@runtime_checkable
class Store(Protocol):
    """§10.2 sketch ("devices, token_hashes, audit, settings, model_cache"),
    refined with the methods `core` and `security` consume today. WP-08 note
    (§10.1 dependency rule): "`security/` may use `store` through a repository
    port" — the security services below type against THIS port, never against
    `store/sqlite.py`; the concrete surface remains `store/sqlite.py` (WP-04,
    §14.1 schema verbatim).
    """

    # -- model cache (§16.3, consumed by core.registry) -----------------------
    def replace_model_cache(self, entries: list[tuple[str, str]], refreshed_at: int) -> None: ...
    def get_model_cache(self) -> dict[str, dict[str, Any]]: ...

    # -- devices (§14.1, consumed by security.devices / pairing) ---------------
    def upsert_device(
        self,
        device_id: str,
        name: str,
        platform: str,
        public_key_spki: bytes,
        scopes: str,
        created_at: int,
    ) -> None: ...
    def get_device(self, device_id: str) -> dict[str, Any] | None: ...
    def list_devices(self) -> list[dict[str, Any]]: ...
    def revoke_device(self, device_id: str, revoked_at: int) -> bool: ...
    def touch_device_last_seen(self, device_id: str, ts: int) -> None: ...
    def update_device(
        self,
        device_id: str,
        name: str | None = None,
        scopes: str | None = None,
    ) -> bool:
        """Partial operator update (§13.1 `PATCH /admin/devices/{id}`).

        Only the provided fields are written; the row is never created here.
        Returns False when the device_id is unknown.
        """
        ...

    # -- tokens (§14.1: SHA-256 hash only; consumed by security.tokens) --------
    def put_token(
        self, token_hash: bytes, device_id: str, issued_at: int, expires_at: int
    ) -> None: ...
    def get_token(self, token_hash: bytes) -> dict[str, Any] | None: ...
    def delete_device_tokens(self, device_id: str) -> int: ...

    # -- audit (§14.1/§20.2: Metadata only, closed vocabulary) -----------------
    def append_audit(
        self,
        event: str,
        device_id: str | None = None,
        meta: dict[str, Any] | None = None,
        ts: int | None = None,
    ) -> None: ...


@runtime_checkable
class Clock(Protocol):
    """Injectable time source (§10.2: 'monotonic + wall, injectable for tests')."""

    def now_monotonic(self) -> float: ...
    def now_wall(self) -> int: ...  # unix seconds


class SystemClock:
    """Default Clock (§10.2 intent: injectable for tests)."""

    def now_monotonic(self) -> float:
        return time.monotonic()

    def now_wall(self) -> int:
        return int(time.time())


def overrides_from_config(overrides: list[ModelOverrideConfig]) -> dict[str, ModelOverrideConfig]:
    """Index user overrides by mesh_model_id (Appendix E; §16.3 step 3)."""
    return {o.mesh_model_id: o for o in overrides}
