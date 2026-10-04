"""WP-15 part 2 integration tests — API-MODEL-02/03 `POST /models/load|unload`
(§13.2, FR-MOD-04) against the REAL app wired to the WP-03 fake Backends.

Covers: 202 `{"state":"loading"}` verbatim body, fake-server state flip
(load/unload observable in `GET /models` via the registry), 404
`MODEL_NOT_FOUND`, 501 `UNSUPPORTED_CAPABILITY` (Ollama has no explicit
load/unload per §10.3), 422 `INVALID_REQUEST` envelope, auth (Bearer +
`models:manage`), §13.3 wire headers, and the §16.5 keep-warm loop pinging
the fake Ollama through app wiring (warm set from `models.overrides`).
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Any

import httpx
import pytest

TOOLS_FAKE = Path(__file__).resolve().parents[3] / "tools" / "fake-backends"
if str(TOOLS_FAKE) not in sys.path:
    sys.path.insert(0, str(TOOLS_FAKE))  # test asset import (§21.5 shared fixture)

from fake_lmstudio import DEFAULT_MODEL as LMS_MODEL  # noqa: E402
from fake_lmstudio import FakeLMStudio  # noqa: E402
from fake_ollama import DEFAULT_MODEL as OLLAMA_MODEL  # noqa: E402
from fake_ollama import DEFAULT_ON_DISK as OLLAMA_ON_DISK  # noqa: E402
from fake_ollama import FakeOllama  # noqa: E402

from localmesh_agent.app import create_app  # noqa: E402
from localmesh_agent.config import BackendConfig, ModelOverrideConfig, Settings  # noqa: E402
from localmesh_agent.core.entities import new_uuid7  # noqa: E402

LMS_ID = "lmstudio"
OLLAMA_ID = "ollama"


class _FakeServerHandle:
    def __init__(self, server: Any) -> None:
        self.server = server
        self.thread = threading.Thread(target=server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture()
def fakes() -> tuple[_FakeServerHandle, _FakeServerHandle]:
    lms = _FakeServerHandle(FakeLMStudio(("127.0.0.1", 0), cold_load_ms=0))
    ollama = _FakeServerHandle(FakeOllama(("127.0.0.1", 0)))
    yield lms, ollama
    lms.stop()
    ollama.stop()


def make_settings(data_dir: Path, lms_url: str, ollama_url: str) -> Settings:
    return Settings(
        agent={"data_dir": str(data_dir)},
        backends=[
            BackendConfig(id=LMS_ID, kind="lmstudio", base_url=lms_url),
            BackendConfig(id=OLLAMA_ID, kind="ollama", base_url=ollama_url),
        ],
        models={
            "overrides": [
                ModelOverrideConfig(mesh_model_id=f"{OLLAMA_ID}::{OLLAMA_MODEL}", keep_warm=True)
            ]
        },
    )


def make_client(app: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")


@pytest.fixture()
async def app_env(tmp_path: Path, fakes: tuple[_FakeServerHandle, _FakeServerHandle]) -> Any:
    """Token-mode app with the §10.6 lifespan run in the test's loop
    (registry refresh, keep-warm loop start; mDNS disabled for hermeticity)."""
    lms, ollama = fakes
    app = create_app(make_settings(tmp_path, lms.url, ollama.url), dev_insecure=False)
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        yield app, lms, ollama


@pytest.fixture()
async def manage_header(app_env: Any) -> dict[str, str]:
    """A paired Device whose scopes include `models:manage` (§13.2 API table).

    upsert_device is INSERT-OR-IGNORE (scopes come from the FIRST insert —
    see test_device_endpoint.py), so the manage-scoped row is inserted
    directly instead of mutating a DeviceService.create row.
    """
    app, _lms, _ollama = app_env
    device_id = "dv_" + new_uuid7()
    app.state.store.upsert_device(
        device_id,
        "Pixel 8",
        "android",
        b"\x04spki-bytes",
        "models:read models:manage chat",
        int(app.state.clock.now_wall()),
    )
    issued = app.state.tokens.issue(device_id)
    return {"Authorization": f"Bearer {issued.token}"}


# -- API-MODEL-02: load --------------------------------------------------------


@pytest.mark.anyio
async def test_load_returns_202_loading_and_flips_fake_state(
    app_env: Any, manage_header: dict[str, str]
) -> None:
    app, lms, _ollama = app_env
    assert LMS_MODEL not in lms.server.loaded_models  # fake starts cold

    async with make_client(app) as client:
        resp = await client.post(
            "/mesh/v1/models/load",
            json={"mesh_model_id": f"{LMS_ID}::{LMS_MODEL}"},
            headers=manage_header,
        )
    assert resp.status_code == 202
    assert resp.json() == {"state": "loading"}  # §13.2 verbatim
    assert LMS_MODEL in lms.server.loaded_models  # fake LM Studio state flipped
    # §13.3 wire headers on the 202 too.
    assert resp.headers["X-Mesh-Api-Version"] == "1"
    assert resp.headers["X-Mesh-Request-Id"].startswith("rq_")
    assert resp.headers["Cache-Control"] == "no-store"


@pytest.mark.anyio
async def test_load_keeps_registry_state_unknown_until_fixtures(
    app_env: Any, manage_header: dict[str, str]
) -> None:
    """§6.1 Unknown: the native `/api/v1/models` loaded-flags are [UNVERIFIED],
    so the registry extracts only the verified `id` and NEVER guesses state
    (§13.5 "MUST NOT fill unknowns with defaults") — even after a successful
    load the LM Studio entry stays `unknown` until real fixtures land
    (docs/fixtures/CAPTURE.md). The fake server state flip itself is asserted
    by test_load_returns_202_loading_and_flips_fake_state."""
    app, _lms, _ollama = app_env
    async with make_client(app) as client:
        load = await client.post(
            "/mesh/v1/models/load",
            json={"mesh_model_id": f"{LMS_ID}::{LMS_MODEL}"},
            headers=manage_header,
        )
        assert load.status_code == 202
        await app.state.registry.refresh()
        listing = await client.get("/mesh/v1/models", headers=manage_header)
    states = {m["mesh_model_id"]: m["state"] for m in listing.json()["models"]}
    assert states[f"{LMS_ID}::{LMS_MODEL}"] == "unknown"


@pytest.mark.anyio
async def test_load_unknown_model_404_envelope(app_env: Any, manage_header: dict[str, str]) -> None:
    app, _lms, _ollama = app_env
    async with make_client(app) as client:
        resp = await client.post(
            "/mesh/v1/models/load",
            json={"mesh_model_id": "lmstudio::nope"},
            headers=manage_header,
        )
    assert resp.status_code == 404
    error = resp.json()["error"]
    assert error["code"] == "MODEL_NOT_FOUND"
    assert error["retryable"] is False
    assert error["request_id"].startswith("rq_")


@pytest.mark.anyio
async def test_load_on_backend_without_capability_501(
    app_env: Any, manage_header: dict[str, str]
) -> None:
    app, _lms, _ollama = app_env
    async with make_client(app) as client:
        resp = await client.post(
            "/mesh/v1/models/load",
            json={"mesh_model_id": f"{OLLAMA_ID}::{OLLAMA_MODEL}"},
            headers=manage_header,
        )
    # Ollama has no explicit load (§10.3): the adapter raises
    # UNSUPPORTED_CAPABILITY → 501 (§13.2, Appendix D).
    assert resp.status_code == 501
    assert resp.json()["error"]["code"] == "UNSUPPORTED_CAPABILITY"


@pytest.mark.anyio
async def test_load_malformed_body_422_envelope(
    app_env: Any, manage_header: dict[str, str]
) -> None:
    app, _lms, _ollama = app_env
    async with make_client(app) as client:
        missing = await client.post("/mesh/v1/models/load", json={}, headers=manage_header)
        extra = await client.post(
            "/mesh/v1/models/load",
            json={"mesh_model_id": f"{LMS_ID}::{LMS_MODEL}", "force": True},
            headers=manage_header,
        )
        not_json = await client.post(
            "/mesh/v1/models/load",
            content=b"not json",
            headers={**manage_header, "Content-Type": "application/json"},
        )
    for resp in (missing, extra, not_json):
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "INVALID_REQUEST"


# -- API-MODEL-03: unload ------------------------------------------------------


@pytest.mark.anyio
async def test_unload_returns_202_and_flips_fake_state(
    app_env: Any, manage_header: dict[str, str]
) -> None:
    app, lms, _ollama = app_env
    lms.server.loaded_models.add(LMS_MODEL)  # start loaded
    async with make_client(app) as client:
        resp = await client.post(
            "/mesh/v1/models/unload",
            json={"mesh_model_id": f"{LMS_ID}::{LMS_MODEL}"},
            headers=manage_header,
        )
    assert resp.status_code == 202
    assert resp.json() == {"state": "unloaded"}  # QUESTION-106 mirrored vocabulary
    assert LMS_MODEL not in lms.server.loaded_models


@pytest.mark.anyio
async def test_unload_on_backend_without_capability_501(
    app_env: Any, manage_header: dict[str, str]
) -> None:
    app, _lms, _ollama = app_env
    async with make_client(app) as client:
        resp = await client.post(
            "/mesh/v1/models/unload",
            json={"mesh_model_id": f"{OLLAMA_ID}::{OLLAMA_MODEL}"},
            headers=manage_header,
        )
    assert resp.status_code == 501
    assert resp.json()["error"]["code"] == "UNSUPPORTED_CAPABILITY"


# -- auth / scopes -------------------------------------------------------------


@pytest.mark.anyio
async def test_load_requires_token(app_env: Any) -> None:
    app, _lms, _ollama = app_env
    async with make_client(app) as client:
        resp = await client.post(
            "/mesh/v1/models/load",
            json={"mesh_model_id": f"{LMS_ID}::{LMS_MODEL}"},
        )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] in {"AUTH_REQUIRED", "AUTH_FAILED"}


@pytest.mark.anyio
async def test_load_rejects_narrow_scope_403(tmp_path: Path, fakes: tuple[Any, Any]) -> None:
    lms, ollama = fakes
    app = create_app(make_settings(tmp_path, lms.url, ollama.url), dev_insecure=False)
    device_id = app.state.devices.create(
        name="Old Phone", platform="android", public_key_spki=b"\x04spki"
    )
    issued = app.state.tokens.issue(device_id)  # DEFAULT_DEVICE_SCOPES: no manage
    async with make_client(app) as client:
        resp = await client.post(
            "/mesh/v1/models/load",
            json={"mesh_model_id": f"{LMS_ID}::{LMS_MODEL}"},
            headers={"Authorization": f"Bearer {issued.token}"},
        )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN_SCOPE"


# -- §16.5 keep-warm through the real app wiring -------------------------------


@pytest.mark.anyio
async def test_keep_warm_tick_pings_warmed_ollama_model_via_app(
    app_env: Any, manage_header: dict[str, str]
) -> None:
    app, _lms, ollama = app_env
    # The override in make_settings warms `ollama::<OLLAMA_MODEL>`; the fake
    # starts with that model in memory — exercise a warmable model that is
    # NOT currently in memory to prove the ping (re)loads it (§6.2 mechanic).
    target = OLLAMA_ON_DISK[1]  # llama-fake:8b (on disk, not in memory)
    app.state.keep_warm._keep_warm_ids = frozenset({f"{OLLAMA_ID}::{target}"})
    # A device was active "recently" (the manage token auth above touched
    # last_seen for its device — but tick uses the store predicate directly).
    app.state.store.touch_device_last_seen(
        next(iter(app.state.store.list_devices()))["device_id"],
        app.state.clock.now_wall(),
    )
    issued = await app.state.keep_warm.tick()
    assert issued == 1
    assert ollama.server.warm_pings[target] == 1
    assert target in ollama.server.in_memory  # /api/ps now reports it loaded


@pytest.mark.anyio
async def test_keep_warm_loop_lifecycle_starts_and_stops(app_env: Any) -> None:
    app, _lms, _ollama = app_env
    # Startup started the loop (§10.6 order); shutdown must cancel it cleanly.
    task = app.state.keep_warm._task
    assert task is not None and not task.done()
    await app.state.keep_warm.stop()
    assert task.done()
