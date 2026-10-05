"""M7 integration — durable Tasks API e2e (§13.9, FR-MM-01..04).

Real app factory + real fake Backends (in-process, loopback). Device auth is
token mode with a `tasks`-scoped device (§13.1: tasks are granted per Device
by the operator) — NOT dev-insecure, so the scope gate is exercised.
"""

from __future__ import annotations

import sys
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

TOOLS_FAKE = Path(__file__).resolve().parents[3] / "tools" / "fake-backends"
sys.path.insert(0, str(TOOLS_FAKE))  # test asset import (§21.5 shared fixture)

from fake_ollama import DEFAULT_MODEL as OLLAMA_MODEL  # noqa: E402
from fake_ollama import FakeOllama  # noqa: E402
from fake_whisper import DEFAULT_MODEL as WHISPER_MODEL  # noqa: E402
from fake_whisper import FakeWhisper  # noqa: E402

from localmesh_agent.app import create_app  # noqa: E402
from localmesh_agent.config import Settings  # noqa: E402

CHAT_MODEL = f"ollama::{OLLAMA_MODEL}"


def make_settings(
    data_dir: Path,
    *,
    ollama_port: int,
    whisper_port: int,
    whisper_auth: str | None = None,
) -> Settings:
    backends: list[dict[str, Any]] = [
        {"id": "ollama", "kind": "ollama", "base_url": f"http://127.0.0.1:{ollama_port}"},
        {
            "id": "whisper",
            "kind": "whisper",
            "base_url": f"http://127.0.0.1:{whisper_port}",
            **({"auth_ref": "whisper-key"} if whisper_auth else {}),
        },
    ]
    return Settings(
        agent={"data_dir": str(data_dir)},
        backends=backends,
        models={
            "overrides": [
                {
                    "mesh_model_id": CHAT_MODEL,
                    "capabilities": ["chat", "vision", "embedding"],
                }
            ]
        },
        tasks={"result_retention_s": 3600, "max_attachment_bytes": 65536},
    )


@pytest.fixture()
def fake_ollama() -> Iterator[FakeOllama]:
    server = FakeOllama(("127.0.0.1", 0))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


@pytest.fixture()
def fake_whisper() -> Iterator[FakeWhisper]:
    server = FakeWhisper(("127.0.0.1", 0))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


@pytest.fixture()
async def authed_app(
    tmp_path: Path,
    fake_ollama: FakeOllama,
    fake_whisper: FakeWhisper,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[Any, dict[str, str]]]:
    """Real app + one paired device with operator-granted `tasks` scope."""
    monkeypatch.setattr("keyring.get_password", lambda service, ref: "whisper-secret")
    app = create_app(
        make_settings(
            tmp_path,
            ollama_port=fake_ollama.server_address[1],
            whisper_port=fake_whisper.server_address[1],
            whisper_auth=True,
        ),
        dev_insecure=False,
    )
    device_id = "dv_tasks_test"
    app.state.store.upsert_device(
        device_id=device_id,
        name="Tasks Phone",
        platform="android",
        public_key_spki=b"\x30\x59tasks-device-key",
        scopes="models:read chat tasks",
        created_at=1_700_000_000,
    )
    issued = app.state.tokens.issue(device_id)
    headers = {"Authorization": f"Bearer {issued.token}"}
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield app, {"client": client, "headers": headers}


def parse_sse(text: str) -> list[tuple[str | None, str]]:
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


async def _await_terminal(
    client: httpx.AsyncClient, headers: dict[str, str], task_id: str
) -> dict[str, Any]:
    for _ in range(100):
        response = await client.get(f"/mesh/v1/tasks/{task_id}", headers=headers)
        assert response.status_code == 200
        body = response.json()
        if body["status"] in ("succeeded", "failed", "cancelled"):
            return body
        await asyncio_sleep()
    raise AssertionError("task never reached a terminal status")


def asyncio_sleep() -> Any:
    import asyncio

    return asyncio.sleep(0.05)


class TestTasksApi:
    async def test_create_returns_202_queued_shape(
        self, authed_app: tuple[Any, dict[str, Any]]
    ) -> None:
        app, env = authed_app
        response = await env["client"].post(
            "/mesh/v1/tasks",
            headers=env["headers"],
            json={
                "type": "chat",
                "input": {"model": CHAT_MODEL, "messages": [{"role": "user", "content": "Hi"}]},
            },
        )
        assert response.status_code == 202
        body = response.json()
        assert body["status"] == "queued"
        assert body["task_id"].startswith("tk_")

    async def test_chat_task_runs_through_scheduler(
        self, authed_app: tuple[Any, dict[str, Any]]
    ) -> None:
        app, env = authed_app
        created = (
            await env["client"].post(
                "/mesh/v1/tasks",
                headers=env["headers"],
                json={
                    "type": "chat",
                    "input": {"model": CHAT_MODEL, "messages": [{"role": "user", "content": "Hi"}]},
                },
            )
        ).json()
        final = await _await_terminal(env["client"], env["headers"], created["task_id"])
        assert final["status"] == "succeeded"
        assert final["result"]["type"] == "chat"
        assert "Hello from fake Ollama." in final["result"]["message"]
        assert final["progress"] == 100
        assert final["expires_at"] is not None  # §13.9: retention stamped

    async def test_vision_task_with_image_part(
        self, authed_app: tuple[Any, dict[str, Any]]
    ) -> None:
        app, env = authed_app
        created = (
            await env["client"].post(
                "/mesh/v1/tasks",
                headers=env["headers"],
                json={
                    "type": "vision",
                    "input": {
                        "model": CHAT_MODEL,
                        "messages": [
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": "What is this?"},
                                    {
                                        "type": "image_url",
                                        "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="},
                                    },
                                ],
                            }
                        ],
                    },
                },
            )
        ).json()
        final = await _await_terminal(env["client"], env["headers"], created["task_id"])
        assert final["status"] == "succeeded"
        assert final["result"]["type"] == "vision"

    async def test_transcribe_task_via_fake_whisper(
        self, authed_app: tuple[Any, dict[str, Any]]
    ) -> None:
        app, env = authed_app
        audio = b"RIFF" + b"\x00" * 256
        created = (
            await env["client"].post(
                "/mesh/v1/tasks",
                headers=env["headers"],
                json={"type": "transcribe", "input": {"audio": "note.wav"}},
            )
        ).json()
        task_id = created["task_id"]
        # Upload the attachment BEFORE the runner reads it (queued state).
        upload = await env["client"].put(
            f"/mesh/v1/tasks/{task_id}/attachments/note.wav",
            headers=env["headers"],
            content=audio,
        )
        assert upload.status_code == 204
        final = await _await_terminal(env["client"], env["headers"], task_id)
        assert final["status"] == "succeeded", final
        assert f"Fake transcript of {len(audio)} bytes" in final["result"]["text"]
        assert WHISPER_MODEL  # fake whisper advertises its model

    async def test_transcribe_missing_attachment_fails_cleanly(
        self, authed_app: tuple[Any, dict[str, Any]]
    ) -> None:
        app, env = authed_app
        created = (
            await env["client"].post(
                "/mesh/v1/tasks",
                headers=env["headers"],
                json={"type": "transcribe", "input": {"audio": "missing.wav"}},
            )
        ).json()
        final = await _await_terminal(env["client"], env["headers"], created["task_id"])
        assert final["status"] == "failed"
        assert final["error"]["code"] == "INVALID_REQUEST"

    async def test_attachment_size_cap_is_enforced(
        self, authed_app: tuple[Any, dict[str, Any]]
    ) -> None:
        app, env = authed_app
        created = (
            await env["client"].post(
                "/mesh/v1/tasks",
                headers=env["headers"],
                json={"type": "transcribe", "input": {"audio": "big.wav"}},
            )
        ).json()
        task_id = created["task_id"]
        response = await env["client"].put(
            f"/mesh/v1/tasks/{task_id}/attachments/big.wav",
            headers={**env["headers"], "Content-Length": str(70000)},
            content=b"x" * 70000,  # cap configured to 65536
        )
        assert response.status_code == 413
        assert response.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"
        await env["client"].delete(f"/mesh/v1/tasks/{task_id}", headers=env["headers"])

    async def test_events_stream_reports_lifecycle(
        self, authed_app: tuple[Any, dict[str, Any]]
    ) -> None:
        app, env = authed_app
        created = (
            await env["client"].post(
                "/mesh/v1/tasks",
                headers=env["headers"],
                json={
                    "type": "chat",
                    "input": {"model": CHAT_MODEL, "messages": [{"role": "user", "content": "Hi"}]},
                },
            )
        ).json()
        response = await env["client"].get(
            f"/mesh/v1/tasks/{created['task_id']}/events", headers=env["headers"]
        )
        assert response.status_code == 200
        events = parse_sse(response.text)
        names = [name for name, _data in events]
        assert "task" in names
        statuses = [
            __import__("json").loads(data)["status"] for name, data in events if name == "task"
        ]
        assert statuses[0] in ("queued", "running", "succeeded")
        assert statuses[-1] == "succeeded"
        assert events[-1] == (None, "[DONE]")  # §13.7-style terminator

    async def test_fetch_ack_delete_purges_result(
        self, authed_app: tuple[Any, dict[str, Any]]
    ) -> None:
        app, env = authed_app
        created = (
            await env["client"].post(
                "/mesh/v1/tasks",
                headers=env["headers"],
                json={
                    "type": "chat",
                    "input": {"model": CHAT_MODEL, "messages": [{"role": "user", "content": "Hi"}]},
                },
            )
        ).json()
        task_id = created["task_id"]
        await _await_terminal(env["client"], env["headers"], task_id)
        deleted = await env["client"].delete(f"/mesh/v1/tasks/{task_id}", headers=env["headers"])
        assert deleted.status_code == 200
        gone = await env["client"].get(f"/mesh/v1/tasks/{task_id}", headers=env["headers"])
        assert gone.status_code == 404  # fetch-ack: result is gone (§13.9)

    async def test_foreign_task_is_404(
        self, authed_app: tuple[Any, dict[str, Any]], tmp_path: Path
    ) -> None:
        app, env = authed_app
        response = await env["client"].get(
            "/mesh/v1/tasks/tk_does_not_exist", headers=env["headers"]
        )
        assert response.status_code == 404

    async def test_tasks_scope_is_required(self, authed_app: tuple[Any, dict[str, Any]]) -> None:
        app, env = authed_app
        # A device WITHOUT the tasks scope (default §13.1 scopes).
        app.state.store.upsert_device(
            device_id="dv_no_tasks",
            name="Chat-only Phone",
            platform="android",
            public_key_spki=b"\x30\x59no-tasks-key",
            scopes="models:read chat",
            created_at=1_700_000_000,
        )
        issued = app.state.tokens.issue("dv_no_tasks")
        headers = {"Authorization": f"Bearer {issued.token}"}
        response = await env["client"].post(
            "/mesh/v1/tasks",
            headers=headers,
            json={
                "type": "chat",
                "input": {"model": CHAT_MODEL, "messages": [{"role": "user", "content": "Hi"}]},
            },
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "FORBIDDEN_SCOPE"

    async def test_results_are_encrypted_at_rest(
        self, authed_app: tuple[Any, dict[str, Any]]
    ) -> None:
        app, env = authed_app
        canary = "CANARY-task-result-7f3a"
        created = (
            await env["client"].post(
                "/mesh/v1/tasks",
                headers=env["headers"],
                json={
                    "type": "chat",
                    "input": {
                        "model": CHAT_MODEL,
                        "messages": [{"role": "user", "content": canary}],
                    },
                },
            )
        ).json()
        final = await _await_terminal(env["client"], env["headers"], created["task_id"])
        assert final["status"] == "succeeded"
        # The result decrypts in the API view...
        assert "message" in final["result"]
        # ...but the database row holds CIPHERTEXT ONLY — both the task
        # definition (input) and the result (§13.9 + TC-SEC-01 canary rule).
        row = env_client_store(authed_app).get_task(created["task_id"])
        assert row["enc_result"] is not None
        assert canary.encode() not in bytes(row["enc_result"])
        assert canary.encode() not in bytes(row["enc_input"])
        assert canary.encode() not in bytes(row["input_nonce"])


def env_client_store(authed_app: tuple[Any, dict[str, Any]]) -> Any:
    app, _env = authed_app
    return app.state.store


def test_whisper_kind_in_config_vocabulary() -> None:
    from localmesh_agent.config import BACKEND_KINDS

    assert "whisper" in BACKEND_KINDS


def test_mesh_error_codes_unchanged() -> None:
    # Appendix D mapping is untouched by M7 (regression pin).
    from localmesh_agent.core.errors import MESH_ERROR_CODES

    assert MESH_ERROR_CODES["UNSUPPORTED_CAPABILITY"] == (501, False)
