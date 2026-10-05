"""CI-18 / CI-21 stream-robustness integration tests (§13.7, §10.3 rule 4).

Agent-side contract under a COLD model load:
- `: ping` keepalives flow every 15 s until the first token (CI-21 mitigation
  "Pings + UI 'Loading model…'"), so the phone's 45 s idle detector (CI-18)
  never fires while the Backend is loading;
- the first-token TIME budget is `limits.first_token_timeout_seconds`
  (Appendix E, default 120 s) — on expiry the stream ends with a TERMINAL
  `mesh.error` `BACKEND_TIMEOUT` (Appendix D 504), never a silent abort
  (NFR-REL-02);
- a fast stream emits NO spurious keepalives.

Real app + real adapter + WP-03 fake Backend over ASGI (dev-insecure).
Timing budgets are shrunk via config / monkeypatching — the SEMANTICS tested
are the production ones.
"""

import sys
import threading
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from localmesh_agent.app import create_app
from localmesh_agent.config import Settings

TOOLS_FAKE = Path(__file__).resolve().parents[3] / "tools" / "fake-backends"
if str(TOOLS_FAKE) not in sys.path:
    sys.path.insert(0, str(TOOLS_FAKE))  # test asset import (§21.5 shared fixture)

from fake_lmstudio import FakeLMStudio  # noqa: E402

CHAT_BODY: dict[str, Any] = {
    "model": "lmstudio::qwen-fake-7b-instruct",
    "messages": [{"role": "user", "content": "Hi"}],
    "stream": True,
}


def make_settings(base_url: str, data_dir: Path, first_token_timeout: int) -> Settings:
    return Settings(
        agent={"data_dir": str(data_dir)},
        limits={"first_token_timeout_seconds": first_token_timeout},
        backends=[{"id": "lmstudio", "kind": "lmstudio", "base_url": base_url}],
    )


def make_client(app: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")


@pytest.fixture()
def fake_lmstudio_cold() -> AsyncIterator[Any]:
    server = FakeLMStudio(("127.0.0.1", 0), cold_load_ms=2500)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


@pytest.fixture()
def fake_lmstudio_warm() -> AsyncIterator[Any]:
    server = FakeLMStudio(("127.0.0.1", 0), cold_load_ms=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


async def test_cold_load_stream_carries_pings_then_terminal_backend_timeout(
    fake_lmstudio_cold: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CI-21/CI-18: cold load longer than the first-token budget ->
    pings while waiting, then TERMINAL mesh.error BACKEND_TIMEOUT, no [DONE]."""
    monkeypatch.setattr(
        "localmesh_agent.api.v1.chat.PING_INTERVAL_S", 0.2
    )  # production value is 15 s (§13.7); shrunk for test speed only
    app = create_app(
        make_settings(fake_lmstudio_cold, tmp_path, first_token_timeout=1), dev_insecure=True
    )
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        async with make_client(app) as client:
            async with client.stream(
                "POST", "/mesh/v1/chat/completions", json=CHAT_BODY
            ) as response:
                assert response.status_code == 200
                assert response.headers["Content-Type"].startswith("text/event-stream")
                assert response.headers["X-Accel-Buffering"] == "no"
                text = "".join([chunk async for chunk in response.aiter_text()])
    # Keepalives flowed while the Backend was loading (before the timeout).
    assert text.count(": ping") >= 3, "cold load must emit §13.7 keepalives"
    # mesh.meta came first; mesh.error is terminal; no [DONE] after an error.
    assert "event: mesh.meta" in text
    assert "event: mesh.error" in text
    assert "data: [DONE]" not in text
    error_line = next(
        line[5:].strip()
        for line in text.splitlines()
        if line.startswith("data:") and "BACKEND_TIMEOUT" in line
    )
    import json

    envelope = json.loads(error_line)["error"]
    assert envelope["code"] == "BACKEND_TIMEOUT"
    assert envelope["retryable"] is True  # Appendix D: 504, retryable
    assert envelope["request_id"].startswith("rq_")
    assert isinstance(envelope["message"], str)
    assert envelope["message"] != ""


async def test_fast_stream_has_no_spurious_pings(fake_lmstudio_warm: str, tmp_path: Path) -> None:
    """Keepalives are a WAITING-phase mechanism only (§13.7) — a stream whose
    first token arrives immediately must not carry any `: ping`. The
    production 15 s interval is kept: a fast stream finishes orders of
    magnitude before the first keepalive could ever fire."""
    app = create_app(
        make_settings(fake_lmstudio_warm, tmp_path, first_token_timeout=5), dev_insecure=True
    )
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        async with make_client(app) as client:
            async with client.stream(
                "POST", "/mesh/v1/chat/completions", json=CHAT_BODY
            ) as response:
                assert response.status_code == 200
                text = "".join([chunk async for chunk in response.aiter_text()])
    assert ": ping" not in text
    assert "event: mesh.stats" in text  # completed normally
    assert "data: [DONE]" in text


async def test_cold_load_within_budget_completes_with_pings(
    fake_lmstudio_cold: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cold load (2.5 s) WITHIN the first-token budget (4 s): pings keep the
    stream alive and generation still completes (the CI-21 mitigation doing
    its job — 2.5 s < 45 s so the phone would live either way, but the pings
    prove the loading phase is signalled)."""
    monkeypatch.setattr("localmesh_agent.api.v1.chat.PING_INTERVAL_S", 0.3)
    app = create_app(
        make_settings(fake_lmstudio_cold, tmp_path, first_token_timeout=4), dev_insecure=True
    )
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        async with make_client(app) as client:
            async with client.stream(
                "POST", "/mesh/v1/chat/completions", json=CHAT_BODY
            ) as response:
                assert response.status_code == 200
                text = "".join([chunk async for chunk in response.aiter_text()])
    assert text.count(": ping") >= 3
    assert "event: mesh.meta" in text
    assert "event: mesh.stats" in text  # survived the cold load
    assert "data: [DONE]" in text
    assert "mesh.error" not in text
