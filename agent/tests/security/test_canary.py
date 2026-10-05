"""TC-SEC-01 — canary test (§17.10, FR-CHAT-04, SEC-N3, NFR-SEC-02).

"After a chat containing a unique canary string, grep the entire data/log
directory and all stdout for the canary ⇒ must find none."

The canary travels as prompt Content through one full chat round-trip; after
it finishes, every persistent artifact the Agent owns (data dir files: agent
DB, log file) and all stdout must be canary-free. The Agent is stateless for
chat (ADR-011).
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
from localmesh_agent.observability.logging import configure_logging  # noqa: E402

CANARY = "TC-SEC-01-canary-9f3ab71d-prompt-content"


@pytest.fixture()
def fake_lmstudio() -> Any:
    server = FakeLMStudio(("127.0.0.1", 0), cold_load_ms=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def test_canary_never_persisted_or_logged(
    fake_lmstudio: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data_dir = tmp_path / "data"
    log_file = tmp_path / "logs" / "agent.log"
    settings = Settings(
        agent={"data_dir": str(data_dir)},
        logging={"level": "debug"},  # even at debug: no Content allowed
        backends=[{"id": "lmstudio", "kind": "lmstudio", "base_url": fake_lmstudio}],
    )
    app = create_app(settings, dev_insecure=True)
    # Attach the file sink AFTER create_app (the factory reconfigures logging
    # per §10.6 step 1, clearing prior handlers).
    configure_logging("debug", log_file=log_file)

    async def run_chat() -> None:
        # Lifespan runs startup (registry refresh per §10.6) and shutdown.
        async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
                response = await client.post(
                    "/mesh/v1/chat/completions",
                    json={
                        "model": "lmstudio::qwen-fake-7b-instruct",
                        "messages": [
                            {"role": "system", "content": f"secret system {CANARY}"},
                            {"role": "user", "content": f"please echo {CANARY}"},
                        ],
                        "stream": True,
                    },
                )
                assert response.status_code == 200
                body = await response.aread()
                # The App may see Content — the AGENT's stores/logs must not. The
                # fake's fixed reply contains no canary; assert that too.
                assert CANARY not in body.decode("utf-8", errors="replace")

    import asyncio

    asyncio.run(run_chat())

    # 1) every file in the data dir + log dir: no canary bytes
    for directory in (data_dir, log_file.parent):
        assert directory.is_dir()
        for path in directory.rglob("*"):
            if path.is_file():
                assert CANARY.encode() not in path.read_bytes(), (
                    f"canary found in Agent artifact: {path} (SEC-N3/FR-CHAT-04)"
                )
    # 2) stdout: no canary
    captured = capsys.readouterr()
    assert CANARY not in captured.out
    assert CANARY not in captured.err
