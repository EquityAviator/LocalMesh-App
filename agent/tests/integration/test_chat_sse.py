"""WP-06 integration tests — chat SSE over the full app (API-CHAT-01, §13.7;
FR-CHAT-01/02/05; NFR-PERF-03; API-MODEL-01; API-HEALTH-01; API-REQ-01).

Runs the real FastAPI app (dev-insecure loopback mode) over ASGI against the
WP-03 fake Backends.
"""

import sys
import threading
from pathlib import Path
from typing import Any

import httpx
import pytest

TOOLS_FAKE = Path(__file__).resolve().parents[3] / "tools" / "fake-backends"
if str(TOOLS_FAKE) not in sys.path:
    sys.path.insert(0, str(TOOLS_FAKE))

from fake_lmstudio import FakeLMStudio  # noqa: E402

from localmesh_agent.app import create_app  # noqa: E402
from localmesh_agent.config import Settings  # noqa: E402


@pytest.fixture()
def fake_lmstudio_slow() -> Any:
    server = FakeLMStudio(("127.0.0.1", 0), cold_load_ms=2500)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


@pytest.fixture()
def fake_lmstudio() -> Any:
    server = FakeLMStudio(("127.0.0.1", 0), cold_load_ms=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def make_settings(base_url: str, data_dir: Path, max_queued: int = 8) -> Settings:
    return Settings(
        agent={"data_dir": str(data_dir)},
        limits={"max_queued": max_queued},
        backends=[{"id": "lmstudio", "kind": "lmstudio", "base_url": base_url}],
    )


def make_client(app: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")


CHAT_BODY: dict[str, Any] = {
    "model": "lmstudio::qwen-fake-7b-instruct",
    "messages": [{"role": "user", "content": "Hi"}],
    "stream": True,
}


def parse_sse(text: str) -> list[tuple[str | None, str]]:
    """(event, data) tuples; comments dropped; [DONE] included."""
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


async def test_models_endpoint_envelope(fake_lmstudio: str, tmp_path: Path) -> None:
    """API-MODEL-01: §13.5 envelope with provenance-carrying entries."""
    app = create_app(make_settings(fake_lmstudio, tmp_path), dev_insecure=True)
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        async with make_client(app) as client:
            response = await client.get("/mesh/v1/models")
    assert response.status_code == 200
    assert response.headers["X-Mesh-Api-Version"] == "1"
    assert response.headers["X-Mesh-Request-Id"].startswith("rq_")
    assert response.headers["Cache-Control"] == "no-store"
    body = response.json()
    assert body["agent_id"].startswith("ag_")
    assert body["backends"][0]["id"] == "lmstudio"
    assert any(m["mesh_model_id"] == "lmstudio::qwen-fake-7b-instruct" for m in body["models"])
    entry = next(m for m in body["models"] if m["mesh_model_id"].startswith("lmstudio::"))
    assert set(entry) == {
        "mesh_model_id",
        "backend_id",
        "backend_model_id",
        "display_name",
        "state",
        "modalities",
        "capabilities",
        "context_length",
        "quantization",
        "parameter_size",
        "size_bytes",
        "vram_estimate_bytes",
        "tags",
    }
    # §13.5: unknown fields null with provenance — never guessed values.
    assert entry["context_length"] == {"value": None, "source": "unknown"}


async def test_health_endpoint_shape(fake_lmstudio: str, tmp_path: Path) -> None:
    """API-HEALTH-01: {status, uptime_s, backends[], queue{}}."""
    app = create_app(make_settings(fake_lmstudio, tmp_path), dev_insecure=True)
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        async with make_client(app) as client:
            response = await client.get("/mesh/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] in ("ok", "degraded", "down")
    assert isinstance(body["uptime_s"], int)
    assert body["backends"] == [{"id": "lmstudio", "status": "up"}]
    assert body["queue"] == {"active": 0, "queued": 0, "max_queued": 8}


async def test_chat_stream_sse_wire_format(fake_lmstudio: str, tmp_path: Path) -> None:
    """§13.7: mesh.meta first, OpenAI chunks, mesh.stats, [DONE]; headers."""
    app = create_app(make_settings(fake_lmstudio, tmp_path), dev_insecure=True)
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        async with make_client(app) as client:
            async with client.stream(
                "POST", "/mesh/v1/chat/completions", json=CHAT_BODY
            ) as response:
                assert response.status_code == 200
                assert response.headers["Content-Type"].startswith("text/event-stream")
                assert response.headers["Cache-Control"] == "no-cache, no-transform"
                assert response.headers["X-Accel-Buffering"] == "no"
                assert response.headers["X-Mesh-Request-Id"].startswith("rq_")
                text = "".join([chunk async for chunk in response.aiter_text()])
    events = parse_sse(text)
    assert events, "no SSE events received"
    first_event, first_data = events[0]
    assert first_event == "mesh.meta"
    meta = __import__("json").loads(first_data)
    assert meta["model"] == "lmstudio::qwen-fake-7b-instruct"
    assert meta["backend"] == "lmstudio"
    assert meta["request_id"].startswith("rq_")
    assert meta["model_state"] in ("loaded", "unloaded", "loading", "unknown")

    chunk_datas = [d for name, d in events if name is None and d != "[DONE]"]
    assert chunk_datas, "no OpenAI chunk events"
    chunk_payloads = [__import__("json").loads(d) for d in chunk_datas]
    for payload in chunk_payloads:
        assert payload["object"] == "chat.completion.chunk"
        assert payload["model"] == "lmstudio::qwen-fake-7b-instruct"
    content = "".join(p["choices"][0]["delta"].get("content", "") for p in chunk_payloads)
    assert content == "Hello from fake LM Studio."

    named = [(name, d) for name, d in events if name in ("mesh.stats", "mesh.error")]
    assert named and named[0][0] == "mesh.stats"
    stats = __import__("json").loads(named[0][1])
    assert set(stats) == {
        "ttft_ms",
        "tokens_out",
        "tokens_per_sec",
        "duration_ms",
        "finish_reason",
        "token_count_source",
    }
    assert events[-1] == (None, "[DONE]")


async def test_chat_non_stream_completion(fake_lmstudio: str, tmp_path: Path) -> None:
    """§13.2: stream=false returns an OpenAI completion + x_mesh.stats."""
    app = create_app(make_settings(fake_lmstudio, tmp_path), dev_insecure=True)
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        async with make_client(app) as client:
            response = await client.post(
                "/mesh/v1/chat/completions",
                json={**CHAT_BODY, "stream": False},
            )
    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "chat.completion"
    assert body["choices"][0]["message"]["content"] == "Hello from fake LM Studio."
    assert body["x_mesh"]["stats"]["finish_reason"] == "stop"


async def test_unknown_param_422_envelope(fake_lmstudio: str, tmp_path: Path) -> None:
    """§13.4 envelope + §13.6 unknown_fields details."""
    app = create_app(make_settings(fake_lmstudio, tmp_path), dev_insecure=True)
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        async with make_client(app) as client:
            response = await client.post(
                "/mesh/v1/chat/completions",
                json={**CHAT_BODY, "logprobs": True},
            )
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "INVALID_REQUEST"
    assert error["retryable"] is False
    assert error["details"]["unknown_fields"] == ["logprobs"]
    assert error["request_id"].startswith("rq_")


async def test_unknown_model_404_envelope(fake_lmstudio: str, tmp_path: Path) -> None:
    app = create_app(make_settings(fake_lmstudio, tmp_path), dev_insecure=True)
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        async with make_client(app) as client:
            response = await client.post(
                "/mesh/v1/chat/completions",
                json={**CHAT_BODY, "model": "lmstudio::nope"},
            )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "MODEL_NOT_FOUND"


async def test_payload_too_large_413(fake_lmstudio: str, tmp_path: Path) -> None:
    """§13.8: body > 2 MiB → 413 PAYLOAD_TOO_LARGE."""
    app = create_app(make_settings(fake_lmstudio, tmp_path), dev_insecure=True)
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        async with make_client(app) as client:
            response = await client.post(
                "/mesh/v1/chat/completions",
                json={
                    **CHAT_BODY,
                    "messages": [{"role": "user", "content": "x" * (2 * 1024 * 1024 + 100)}],
                },
            )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


async def test_cancel_via_api_req_01(fake_lmstudio_slow: str, tmp_path: Path) -> None:
    """FR-CHAT-02 / §13.7: Stop cancels within 2 s; 202 → stream ends; 404 after.

    Uses a REAL uvicorn server on loopback: httpx's ASGITransport buffers the
    full response body, which cannot exercise a mid-stream cancel (the M1 exit
    criterion is curl-on-loopback streaming, so a real listener is the honest
    harness).
    """
    import socket
    import time as _time

    import uvicorn

    def _free_port() -> int:
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        return port

    app = create_app(make_settings(fake_lmstudio_slow, tmp_path), dev_insecure=True)
    config = uvicorn.Config(app, host="127.0.0.1", port=_free_port(), log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        await asyncio_sleep(0.05)
    base_url = f"http://127.0.0.1:{config.port}"
    try:
        async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
            async with client.stream(
                "POST", "/mesh/v1/chat/completions", json=CHAT_BODY
            ) as response:
                assert response.status_code == 200
                request_id = response.headers["X-Mesh-Request-Id"]
                cancel_start = _time.monotonic()
                cancel_response = await client.delete(f"/mesh/v1/requests/{request_id}")
                assert cancel_response.status_code == 202
                assert cancel_response.json() == {"status": "cancelling"}
                # Stream ends promptly after cancel (no hang, NFR-REL-02).
                text = "".join([chunk async for chunk in response.aiter_text()])
                elapsed = _time.monotonic() - cancel_start
            assert elapsed < 2.0, f"cancel took {elapsed:.2f}s (FR-CHAT-02: ≤ 2 s)"
            assert "mesh.error" not in text  # cancel: no further events (§13.7)
            assert "mesh.stats" not in text  # cancelled: no stats event
            # §13.2 API-REQ-01: 404 once the request is unknown/finished.
            await asyncio_sleep(0.3)
            second = await client.delete(f"/mesh/v1/requests/{request_id}")
            assert second.status_code == 404
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def asyncio_sleep(delay: float) -> Any:
    import asyncio

    return asyncio.sleep(delay)


async def test_chat_with_invalid_json_422(fake_lmstudio: str, tmp_path: Path) -> None:
    app = create_app(make_settings(fake_lmstudio, tmp_path), dev_insecure=True)
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        async with make_client(app) as client:
            response = await client.post(
                "/mesh/v1/chat/completions",
                content=b"{not json",
                headers={"Content-Type": "application/json"},
            )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


async def test_default_mode_fails_closed(tmp_path: Path, fake_lmstudio: str) -> None:
    """SEC-N4/N6: without dev-insecure, authenticated endpoints fail closed."""
    app = create_app(make_settings(fake_lmstudio, tmp_path), dev_insecure=False)
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        async with make_client(app) as client:
            response = await client.get("/mesh/v1/models")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"
