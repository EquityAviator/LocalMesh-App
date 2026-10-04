"""M8 integration — `model:"auto"` + tool calling e2e (§16.6, ADR-020)."""

from __future__ import annotations

import json
import sys
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

TOOLS_FAKE = Path(__file__).resolve().parents[3] / "tools" / "fake-backends"
sys.path.insert(0, str(TOOLS_FAKE))

from fake_ollama import DEFAULT_MODEL as OLLAMA_MODEL  # noqa: E402
from fake_ollama import FakeOllama  # noqa: E402

from localmesh_agent.app import create_app  # noqa: E402
from localmesh_agent.config import Settings  # noqa: E402

CHAT_MODEL = f"ollama::{OLLAMA_MODEL}"


@pytest.fixture()
def fake_ollama() -> Iterator[FakeOllama]:
    server = FakeOllama(("127.0.0.1", 0))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


@pytest.fixture()
async def runtime_app(
    tmp_path: Path, fake_ollama: FakeOllama
) -> Iterator[tuple[Any, dict[str, str], httpx.AsyncClient]]:
    """Token-mode app; the paired device has the default scopes (§13.1)."""
    settings = Settings(
        agent={"data_dir": str(tmp_path)},
        backends=[
            {
                "id": "ollama",
                "kind": "ollama",
                "base_url": f"http://127.0.0.1:{fake_ollama.server_address[1]}",
            }
        ],
        agent_runtime={"enabled": True},
    )
    app = create_app(settings, dev_insecure=False)
    app.state.store.upsert_device(
        device_id="dv_m8",
        name="M8 Phone",
        platform="android",
        public_key_spki=b"\x30\x59m8-device-key",
        scopes="models:read chat",
        created_at=1_700_000_000,
    )
    issued = app.state.tokens.issue("dv_m8")
    headers = {"Authorization": f"Bearer {issued.token}"}
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield app, headers, client


def parse_sse_events(text: str) -> list[tuple[str | None, str]]:
    events: list[tuple[str | None, str]] = []
    name: str | None = None
    for line in text.splitlines():
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            name = line[6:].strip()
        elif line.startswith("data:"):
            events.append((name, line[5:].strip()))
            name = None
    return events


class TestAutoRouting:
    async def test_auto_resolves_and_explains_in_mesh_meta(
        self, runtime_app: tuple[Any, dict[str, str], httpx.AsyncClient]
    ) -> None:
        _app, headers, client = runtime_app
        response = await client.post(
            "/mesh/v1/chat/completions",
            headers=headers,
            json={
                "model": "auto",
                "messages": [{"role": "user", "content": "Hi"}],
                "stream": True,
            },
        )
        assert response.status_code == 200
        events = parse_sse_events(response.text)
        meta = next(json.loads(data) for name, data in events if name == "mesh.meta")
        routing = meta["routing"]  # §22.1 M8 gate: decisions explained in mesh.meta
        assert routing["mode"] == "auto"
        assert routing["mesh_model_id"] == CHAT_MODEL
        assert routing["candidates"], "per-candidate scores present"
        assert "est_tokens" in routing  # §16.6: flagged as estimate
        assert any(name == "mesh.stats" for name, _data in events), (
            "normal stream continues after auto resolution"
        )

    async def test_pinned_model_reports_pinned_routing(
        self, runtime_app: tuple[Any, dict[str, str], httpx.AsyncClient]
    ) -> None:
        _app, headers, client = runtime_app
        response = await client.post(
            "/mesh/v1/chat/completions",
            headers=headers,
            json={"model": CHAT_MODEL, "messages": [{"role": "user", "content": "Hi"}]},
        )
        events = parse_sse_events(response.text)
        meta = next(json.loads(data) for name, data in events if name == "mesh.meta")
        assert meta["routing"]["mode"] == "pinned"

    async def test_auto_with_vision_requirement_no_candidate_404(
        self, runtime_app: tuple[Any, dict[str, str], httpx.AsyncClient]
    ) -> None:
        # The fake Ollama model carries no vision capability → no candidate.
        _app, headers, client = runtime_app
        response = await client.post(
            "/mesh/v1/chat/completions",
            headers=headers,
            json={
                "model": "auto",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "look"},
                            {
                                "type": "image_url",
                                "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="},
                            },
                        ],
                    }
                ],
            },
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "MODEL_NOT_FOUND"


class TestToolRuntime:
    async def test_tools_disabled_by_default_422(
        self, tmp_path: Path, fake_ollama: FakeOllama
    ) -> None:
        settings = Settings(
            agent={"data_dir": str(tmp_path)},
            backends=[
                {
                    "id": "ollama",
                    "kind": "ollama",
                    "base_url": f"http://127.0.0.1:{fake_ollama.server_address[1]}",
                }
            ],
            # agent_runtime NOT enabled → ADR-020 default-deny
        )
        app = create_app(settings, dev_insecure=False)
        app.state.store.upsert_device(
            device_id="dv_m8",
            name="M8 Phone",
            platform="android",
            public_key_spki=b"\x30\x59m8",
            scopes="models:read chat",
            created_at=1,
        )
        issued = app.state.tokens.issue("dv_m8")
        headers = {"Authorization": f"Bearer {issued.token}"}
        async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/mesh/v1/chat/completions",
                    headers=headers,
                    json={
                        "model": CHAT_MODEL,
                        "stream": False,
                        "messages": [{"role": "user", "content": "Hi"}],
                        "tools": [{"type": "function", "function": {"name": "time_now"}}],
                    },
                )
                assert response.status_code == 422
                assert response.json()["error"]["details"]["tools_disabled"] is True

    async def test_stream_plus_tools_rejected_422(
        self, runtime_app: tuple[Any, dict[str, str], httpx.AsyncClient]
    ) -> None:
        _app, headers, client = runtime_app
        response = await client.post(
            "/mesh/v1/chat/completions",
            headers=headers,
            json={
                "model": CHAT_MODEL,
                "stream": True,
                "messages": [{"role": "user", "content": "Hi"}],
                "tools": [{"type": "function", "function": {"name": "time_now"}}],
            },
        )
        assert response.status_code == 422
        assert response.json()["error"]["details"]["tools_requires_non_stream"] is True

    async def test_tool_loop_runs_end_to_end(
        self, runtime_app: tuple[Any, dict[str, str], httpx.AsyncClient]
    ) -> None:
        app, headers, client = runtime_app
        response = await client.post(
            "/mesh/v1/chat/completions",
            headers=headers,
            json={
                "model": CHAT_MODEL,
                "stream": False,
                "messages": [{"role": "user", "content": "CALL_TOOL:time_now:{}"}],
                "tools": [
                    {"type": "function", "function": {"name": "time_now"}},
                    {"type": "function", "function": {"name": "uuid_v4"}},
                ],
            },
        )
        assert response.status_code == 200
        body = response.json()
        # The loop executed the allow-listed tool and the model produced text.
        assert body["choices"][0]["message"]["content"] == "Hello from fake Ollama."
        trace = body["x_mesh"]["agent_trace"]
        assert trace == [{"tool": "time_now", "status": "executed"}]
        assert body["x_mesh"]["stats"]["finish_reason"] == "tool_loop"
        # Tool arguments never echo into the response trace (ADR-020 §6).
        assert "CALL_TOOL" not in json.dumps(body["x_mesh"])

    async def test_client_declared_unknown_tool_is_denied_in_band(
        self, runtime_app: tuple[Any, dict[str, str], httpx.AsyncClient]
    ) -> None:
        _app, headers, client = runtime_app
        response = await client.post(
            "/mesh/v1/chat/completions",
            headers=headers,
            json={
                "model": CHAT_MODEL,
                "stream": False,
                "messages": [{"role": "user", "content": "CALL_TOOL:malicious_tool:{}"}],
                "tools": [{"type": "function", "function": {"name": "malicious_tool"}}],
            },
        )
        assert response.status_code == 200
        body = response.json()
        # The tool was NOT executed; the loop completed and reports denial
        # via the model's next turn (fake returns plain text afterwards).
        assert body["choices"][0]["message"]["content"] == "Hello from fake Ollama."

    async def test_tools_param_outside_allow_list_is_422(
        self, runtime_app: tuple[Any, dict[str, str], httpx.AsyncClient]
    ) -> None:
        _app, headers, client = runtime_app
        response = await client.post(
            "/mesh/v1/chat/completions",
            headers=headers,
            json={
                "model": CHAT_MODEL,
                "stream": False,
                "messages": [{"role": "user", "content": "Hi"}],
                "tools": [{"type": "weird", "function": {"name": "x"}}],
            },
        )
        assert response.status_code == 422
