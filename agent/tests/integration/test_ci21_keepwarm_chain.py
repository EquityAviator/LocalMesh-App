"""CI-21 e2e chain — keep-warm (FR-MOD-05) × `mesh.meta.model_state` (§13.7).

CI-21 (§21.4, "First message after idle takes very long"): the mitigation
column says "Enable keep-warm (FR-MOD-05)". This file chains the two halves
END-TO-END through the real app wiring and the WP-03 fake Ollama:

  cold path — a model on disk but NOT in memory chats with `mesh.meta.
  model_state == "unloaded"` (the CI-21 problem statement, pinned on the
  wire at meta-emission time, which happens BEFORE the backend demand-load)
  and still completes (the demand-load keeps correctness).

  warm path — with `models.overrides[].keep_warm = true` for that model, an
  active (non-revoked, recently seen) device and one §16.5 tick, the fake
  reports the model in memory (`/api/ps`), the registry picks it up on
  refresh, and the SAME chat now emits `model_state == "loaded"` — the
  keep-warm mitigation, observable in the §13.7 stream header.

Registry state derivation for Ollama is §10.3 (presence in `/api/ps` =
`loaded`), so this chain never guesses a state word outside §13.5.
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

from fake_ollama import DEFAULT_IN_MEMORY, DEFAULT_ON_DISK, FakeOllama  # noqa: E402

from localmesh_agent.app import create_app  # noqa: E402
from localmesh_agent.config import BackendConfig, ModelOverrideConfig, Settings  # noqa: E402
from localmesh_agent.core.entities import new_uuid7  # noqa: E402

OLLAMA_ID = "ollama"
WARM_TARGET = DEFAULT_ON_DISK[1]  # llama-fake:8b — on disk, NOT in DEFAULT_IN_MEMORY
MESH_WARM_TARGET = f"{OLLAMA_ID}::{WARM_TARGET}"


def parse_sse(text: str) -> list[tuple[str | None, str]]:
    """(event, data) tuples; comments dropped (same shape as test_chat_sse)."""
    events: list[tuple[str | None, str]] = []
    event_name: str | None = None
    for line in text.splitlines():
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event_name = line[6:].strip()
        elif line.startswith("data:"):
            events.append((event_name, line[5:].strip()))
            event_name = None
    return events


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


def make_settings(data_dir: Path, ollama_url: str, *, keep_warm: bool) -> Settings:
    overrides = (
        [ModelOverrideConfig(mesh_model_id=MESH_WARM_TARGET, keep_warm=True)] if keep_warm else []
    )
    return Settings(
        agent={"data_dir": str(data_dir)},
        backends=[BackendConfig(id=OLLAMA_ID, kind="ollama", base_url=ollama_url)],
        models={"overrides": overrides},
    )


@pytest.fixture()
def fake_ollama() -> Any:
    handle = _FakeServerHandle(FakeOllama(("127.0.0.1", 0)))
    yield handle
    handle.stop()


async def _chat_and_meta(app: Any, model: str) -> dict[str, Any]:
    """One streaming chat (dev-insecure token bypass, QUESTION-105 — auth is
    NOT the subject here); returns the parsed mesh.meta payload (§13.7)."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        async with client.stream(
            "POST",
            "/mesh/v1/chat/completions",
            json={"model": model, "messages": [{"role": "user", "content": "Hi"}], "stream": True},
        ) as response:
            assert response.status_code == 200
            text = "".join([chunk async for chunk in response.aiter_text()])
    events = parse_sse(text)
    meta_events = [data for name, data in events if name == "mesh.meta"]
    assert meta_events, "mesh.meta must be the first named event (§13.7)"
    meta: dict[str, Any] = json_loads(meta_events[0])
    assert any(name is None and data == "[DONE]" for name, data in events), "stream must complete"
    return meta


def json_loads(raw: str) -> dict[str, Any]:
    import json

    out: dict[str, Any] = json.loads(raw)
    return out


async def test_cold_chat_reports_unloaded_and_still_completes(
    tmp_path: Path, fake_ollama: Any
) -> None:
    """No keep-warm: model_state == "unloaded" at meta time; demand-load saves it."""
    app = create_app(make_settings(tmp_path, fake_ollama.url, keep_warm=False), dev_insecure=True)
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        assert WARM_TARGET not in fake_ollama.server.in_memory  # cold precondition
        meta = await _chat_and_meta(app, MESH_WARM_TARGET)
        assert meta["model_state"] == "unloaded"  # CI-21 problem statement on the wire
        assert meta["model"] == MESH_WARM_TARGET
        assert meta["backend"] == OLLAMA_ID
        # Demand-load happened at the backend (correctness path, §6.2).
        assert WARM_TARGET in fake_ollama.server.in_memory


async def test_keep_warm_flips_next_chat_to_loaded(tmp_path: Path, fake_ollama: Any) -> None:
    """CI-21 mitigation: keep-warm tick + active device → model_state "loaded"."""
    app = create_app(make_settings(tmp_path, fake_ollama.url, keep_warm=True), dev_insecure=True)
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        # §16.5 device-activity gate: a non-revoked device seen "recently".
        device_id = "dv_" + new_uuid7()
        app.state.store.upsert_device(
            device_id,
            "Pixel 8",
            "android",
            b"\x04spki-bytes",
            "chat",
            int(app.state.clock.now_wall()),
        )
        app.state.store.touch_device_last_seen(device_id, app.state.clock.now_wall())
        issued = await app.state.keep_warm.tick()
        assert issued == 1
        assert WARM_TARGET in fake_ollama.server.in_memory  # ping loaded it (§6.2)
        await app.state.registry.refresh()  # §16.3 on-demand poll picks up /api/ps
        meta = await _chat_and_meta(app, MESH_WARM_TARGET)
        assert meta["model_state"] == "loaded"  # the CI-21 mitigation, observable


async def test_already_loaded_model_reports_loaded_without_keep_warm(
    tmp_path: Path, fake_ollama: Any
) -> None:
    """Baseline: DEFAULT_IN_MEMORY model reads "loaded" with no keep-warm at all."""
    app = create_app(make_settings(tmp_path, fake_ollama.url, keep_warm=False), dev_insecure=True)
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        assert DEFAULT_IN_MEMORY[0] in fake_ollama.server.in_memory
        meta = await _chat_and_meta(app, f"{OLLAMA_ID}::{DEFAULT_IN_MEMORY[0]}")
        assert meta["model_state"] == "loaded"
