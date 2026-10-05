"""WP-04 unit tests — TOML config (FR-AGT-03, Appendix E)."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from localmesh_agent.config import (
    CONFIG_ENV_VAR,
    Settings,
    default_data_dir,
    load_settings,
    resolve_config_path,
)

APPENDIX_E_TOML = """\
[agent]
display_name = "My PC"
data_dir = ""

[listen]
host = "0.0.0.0"
port = 8443
admin_port = 8444

[tls]
rotate_on_start = false

[pairing]
ttl_seconds = 300
require_confirmation = true

[limits]
max_body_bytes = 2097152
per_device_active = 2
max_queued = 8
max_stream_seconds = 900
first_token_timeout_seconds = 120

[mdns]
enabled = true
interfaces = []

[[backends]]
id = "lmstudio"
kind = "lmstudio"
base_url = "http://127.0.0.1:1234"
enabled = true
auth_ref = ""
concurrency = 1

[[backends]]
id = "ollama"
kind = "ollama"
base_url = "http://127.0.0.1:11434"
enabled = true
concurrency = 1

[[models.overrides]]
mesh_model_id = "ollama::example"
capabilities = ["chat", "vision"]
quality_rank = 4
keep_warm = false

[logging]
level = "info"

[control_plane]
enabled = false
"""


def test_defaults_without_config_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No config file anywhere -> documented defaults (§Appendix E values)."""
    monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    settings = load_settings(tmp_path / "does-not-exist.toml")
    assert settings.listen.port == 8443
    assert settings.listen.admin_port == 8444
    assert settings.agent.display_name == "LocalMesh Agent"
    assert settings.limits.max_body_bytes == 2_097_152  # §13.8
    assert settings.limits.max_queued == 8
    assert settings.pairing.ttl_seconds == 300  # FR-PAIR-02 default
    assert settings.tls.rotate_on_start is False  # "never true by default"
    # Appendix E default backends (also the FR-MOD-01 autodetect targets).
    assert [b.id for b in settings.backends] == ["lmstudio", "ollama"]
    assert [b.base_url for b in settings.backends] == [
        "http://127.0.0.1:1234",
        "http://127.0.0.1:11434",
    ]
    assert settings.backends[0].concurrency == 1  # §16.4 default


def test_appendix_e_example_parses(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(APPENDIX_E_TOML, encoding="utf-8")
    settings = load_settings(path)
    assert settings.agent.display_name == "My PC"
    assert settings.backends[0].auth_ref == ""
    override = settings.models.overrides[0]
    assert override.mesh_model_id == "ollama::example"
    assert override.capabilities == ["chat", "vision"]
    assert override.quality_rank == 4
    assert override.keep_warm is False


def test_unknown_key_rejected(tmp_path: Path) -> None:
    """Unknown config keys are typos, not extensions — reject (Appendix E contract)."""
    path = tmp_path / "config.toml"
    path.write_text("[agent]\ndisplayname = 'typo'\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        load_settings(path)


def test_non_loopback_backend_rejected(tmp_path: Path) -> None:
    """NFR-SEC-03 / SEC-N2 / §10.3: Backends are loopback-only."""
    path = tmp_path / "config.toml"
    path.write_text(
        '[[backends]]\nid = "bad"\nkind = "openai_compat"\nbase_url = "http://192.168.1.50:8080"\n',
        encoding="utf-8",
    )
    with pytest.raises(ValidationError):
        load_settings(path)


def test_unknown_backend_kind_rejected(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        '[[backends]]\nid = "bad"\nkind = "vllm"\nbase_url = "http://127.0.0.1:8000"\n',
        encoding="utf-8",
    )
    with pytest.raises(ValidationError):
        load_settings(path)


def test_backend_id_must_not_contain_separator(tmp_path: Path) -> None:
    """mesh_model_id splits on the first '::' (§14.3) — ids must not contain it."""
    path = tmp_path / "config.toml"
    path.write_text(
        '[[backends]]\nid = "my::backend"\nkind = "openai_compat"\n'
        'base_url = "http://127.0.0.1:8000"\n',
        encoding="utf-8",
    )
    with pytest.raises(ValidationError):
        load_settings(path)


def test_override_capability_closed_vocabulary(tmp_path: Path) -> None:
    """§13.5: capability values are a closed set; no invented values."""
    path = tmp_path / "config.toml"
    path.write_text(
        '[[models.overrides]]\nmesh_model_id = "ollama::x"\ncapabilities = ["telepathy"]\n',
        encoding="utf-8",
    )
    with pytest.raises(ValidationError):
        load_settings(path)


def test_same_public_and_admin_port_rejected(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[listen]\nport = 8444\nadmin_port = 8444\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        load_settings(path)


def test_pairing_ttl_upper_bound(tmp_path: Path) -> None:
    """FR-PAIR-02: TTL configurable ≤ 600 s."""
    path = tmp_path / "config.toml"
    path.write_text("[pairing]\nttl_seconds = 601\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        load_settings(path)


def test_env_var_selects_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "custom.toml"
    path.write_text('[agent]\ndisplay_name = "Env PC"\n', encoding="utf-8")
    monkeypatch.setenv(CONFIG_ENV_VAR, str(path))
    assert resolve_config_path() == path
    settings = load_settings()
    assert settings.agent.display_name == "Env PC"


def test_default_data_dir_owner_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """§14.1: data dir permissions owner-only (POSIX)."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    import os
    import sys

    if sys.platform == "win32":
        pytest.skip("POSIX permission check")
    directory = default_data_dir()  # not created yet

    settings = Settings(agent={"data_dir": str(directory)})
    created = settings.ensure_data_dir()
    assert created == directory
    mode = os.stat(created).st_mode & 0o777
    assert mode & 0o077 == 0, f"data dir must be owner-only, got {oct(mode)}"


def test_settings_reject_unknown_toplevel_section(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[mystery]\nkey = 1\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        load_settings(path)
