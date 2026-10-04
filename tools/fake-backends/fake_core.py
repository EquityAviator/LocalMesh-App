"""Shared plumbing for the fake Backends (WP-03; LM-ARCH-001 §10.1, §21.5).

Test asset only — NOT part of the Agent and not on any content path.

Behaviours that MUST be reproducible (§21.5): streaming SSE with `[DONE]`,
mid-stream disconnect, slow first token (cold load), HTTP 500s, model-list
shape variants, no-auth and token-auth modes (fake LM Studio only; Ollama has
no auth, §6.2).

UNVERIFIED_SHAPE rule: no real-Backend fixtures existed at capture time
(see docs/fixtures/CAPTURE.md). Every synthetic response is therefore
explicitly marked:
  - response header  `X-Fake-Backend-Shape: UNVERIFIED_SHAPE`
  - JSON bodies carry a top-level `_localmesh_fake` marker object
  - SSE streams open with an `: localmesh-fake-shape: UNVERIFIED_SHAPE`
    comment and carry the marker on the first chunk
When recorded fixtures are supplied (fixture mode), bodies are served verbatim
from the fixture files and marked `RECORDED_FIXTURE` instead. Fixtures from
real Backends outrank fakes (§21.5).

Scenario/fault injection is driven per request by headers:
  - `X-Fake-Backend-Scenario: ok | http-500 | mid-stream-disconnect |
     slow-first-token | shape-variant-a | shape-variant-b | shape-variant-c`
  - `X-Fake-Backend-Delay-Ms: <int>` (delay used by slow-first-token)

The CLI flags of the fake servers are TEST-TOOL surface. They are not Mesh API
or Agent CLI contract (LM-ARCH-001 §13 / §10.1) and carry no compatibility
promise.
"""

from __future__ import annotations

import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

SHAPE_HEADER = "X-Fake-Backend-Shape"
SCENARIO_HEADER = "X-Fake-Backend-Scenario"
DELAY_HEADER = "X-Fake-Backend-Delay-Ms"
MARKER_KEY = "_localmesh_fake"
UNVERIFIED = "UNVERIFIED_SHAPE"
RECORDED = "RECORDED_FIXTURE"

VALID_SCENARIOS = (
    "ok",
    "http-500",
    "mid-stream-disconnect",
    "slow-first-token",
    "shape-variant-a",
    "shape-variant-b",
    "shape-variant-c",
)


def deterministic_embedding(text: str, dim: int = 16) -> list[float]:
    """Deterministic pseudo-embedding from the text hash (test asset only).

    NOT a semantic embedding: stable per input string so retrieval tests can
    construct similarity by reusing substrings/identical text. Shape follows
    the OpenAI `/v1/embeddings` contract; values are UNVERIFIED_SHAPE by the
    fake marker rule.
    """
    import hashlib as _hashlib

    digest = _hashlib.sha256(text.encode("utf-8")).digest()
    return [round((digest[i % len(digest)] / 255.0) * 2 - 1, 6) for i in range(dim)]


def embeddings_response(model: str, inputs: list[str]) -> dict[str, Any]:
    """OpenAI-shaped /v1/embeddings body (marked UNVERIFIED_SHAPE)."""
    return marked(
        {
            "object": "list",
            "model": model,
            "data": [
                {
                    "object": "embedding",
                    "index": i,
                    "embedding": deterministic_embedding(text),
                }
                for i, text in enumerate(inputs)
            ],
            "usage": {"prompt_tokens": 0, "total_tokens": 0},
        }
    )


def marker(shape: str = UNVERIFIED, note: str | None = None) -> dict[str, Any]:
    """Build the `_localmesh_fake` marker object embedded in JSON bodies."""
    return {
        MARKER_KEY: {
            "shape": shape,
            "note": note
            or "not captured from a real Backend; provide fixtures per docs/fixtures/CAPTURE.md",
        }
    }


def marked(
    obj: dict[str, Any], shape: str = UNVERIFIED, note: str | None = None
) -> dict[str, Any]:
    """Return a copy of `obj` with the shape marker added on top."""
    out = dict(obj)
    out.update(marker(shape, note))
    return out


class Scenario:
    """Per-request fault/shape selection from request headers."""

    def __init__(self, headers: Any) -> None:
        self.name = (headers.get(SCENARIO_HEADER) or "ok").strip().lower()
        if self.name not in VALID_SCENARIOS:
            self.name = "ok"
        raw = (headers.get(DELAY_HEADER) or "0").strip()
        try:
            self.delay_ms = max(0, int(raw))
        except ValueError:
            self.delay_ms = 0

    @property
    def is_500(self) -> bool:
        return self.name == "http-500"

    @property
    def is_disconnect(self) -> bool:
        return self.name == "mid-stream-disconnect"

    @property
    def is_slow_first_token(self) -> bool:
        return self.name == "slow-first-token"

    @property
    def shape_variant(self) -> str:
        if self.name.startswith("shape-variant-"):
            return self.name.removeprefix("shape-variant-")
        return "a"


class FakeBackendServer(ThreadingHTTPServer):
    """Threaded loopback-only server base; daemon threads for clean shutdown."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        address: tuple[str, int],
        handler: type[BaseHTTPRequestHandler],
        auth_token: str | None = None,
        fixtures_dir: Path | None = None,
    ) -> None:
        super().__init__(address, handler)
        self.auth_token = auth_token
        self.fixtures_dir = fixtures_dir


class FakeHandler(BaseHTTPRequestHandler):
    """Base request handler with marker/scenario/SSE helpers.

    Subclasses implement `route()`. The server (`.server`) must be a
    FakeBackendServer so auth/fixture configuration is reachable.
    """

    protocol_version = "HTTP/1.1"
    server_version = "localmesh-fake-backend/0.1"

    # -- plumbing ---------------------------------------------------------

    def log_message(self, fmt: str, *args: Any) -> None:
        """Silence per-request logs: never echo bodies/Content into logs (SEC-N3 spirit)."""
        return

    @property
    def backend(self) -> FakeBackendServer:
        server = self.server
        assert isinstance(server, FakeBackendServer)
        return server

    @property
    def scenario(self) -> Scenario:
        return Scenario(self.headers)

    def read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}
        return body if isinstance(body, dict) else {}

    # -- auth -------------------------------------------------------------

    def authorized(self) -> bool:
        token = self.backend.auth_token
        if token is None:
            return True
        header = self.headers.get("Authorization") or ""
        return header == f"Bearer {token}"

    def send_unauthorized(self) -> None:
        self.send_json(marked({"error": {"message": "unauthorized"}}), status=401)

    # -- responses --------------------------------------------------------

    def send_json(self, obj: dict[str, Any], status: int = 200) -> None:
        payload = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header(SHAPE_HEADER, obj.get(MARKER_KEY, {}).get("shape", UNVERIFIED))
        self.end_headers()
        self.wfile.write(payload)
        self.wfile.flush()

    def fixture_response(self, fixture_name: str, builder: Any) -> dict[str, Any]:
        """Serve a recorded fixture body verbatim when present, else build synthetic."""
        fixtures_dir = self.backend.fixtures_dir
        if fixtures_dir is not None:
            path = fixtures_dir / fixture_name
            if path.is_file():
                body = json.loads(path.read_text(encoding="utf-8"))
                return marked(
                    body,
                    shape=RECORDED,
                    note=f"served verbatim from fixture {path.name} (real Backend capture)",
                )
        return builder()

    def maybe_fail(self) -> bool:
        """Apply the http-500 scenario. Returns True when the request was handled (failed)."""
        if not self.scenario.is_500:
            return False
        self.send_json(
            marked(
                {
                    "error": {
                        "message": "synthetic internal server error",
                        "type": "server_error",
                    }
                }
            ),
            status=500,
        )
        return True

    # -- SSE --------------------------------------------------------------

    def start_sse(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header(SHAPE_HEADER, UNVERIFIED)
        self.end_headers()

    def stream_chat(
        self,
        model: str,
        pieces: list[str],
        first_token_delay_ms: int = 0,
        gap_ms: int = 0,
    ) -> bool:
        """Stream OpenAI-style SSE chunks ending with `data: [DONE]`.

        Honours the mid-stream-disconnect scenario (socket closed without
        [DONE] after two chunks). Returns True when [DONE] was sent.
        """
        scenario = self.scenario
        if scenario.is_slow_first_token:
            first_token_delay_ms = max(first_token_delay_ms, scenario.delay_ms)
        if first_token_delay_ms > 0:
            time.sleep(first_token_delay_ms / 1000.0)  # cold-load TTFT

        self.start_sse()
        try:
            self.wfile.write(b": localmesh-fake-shape: UNVERIFIED_SHAPE\n\n")
            chunk_id = f"chatcmpl-fake-{int(time.time() * 1000)}"
            created = int(time.time())
            for i, piece in enumerate(pieces):
                if scenario.is_disconnect and i >= 2:
                    # Abrupt disconnect: no terminal [DONE], socket closed.
                    self.wfile.flush()
                    self.close_connection = True
                    return False
                chunk: dict[str, Any] = {
                    "id": chunk_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [
                        {"index": 0, "delta": {"content": piece}, "finish_reason": None}
                    ],
                }
                if i == 0:
                    chunk = marked(chunk)
                self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
                self.wfile.flush()
                if gap_ms:
                    time.sleep(gap_ms / 1000.0)
            final: dict[str, Any] = {
                "id": chunk_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            }
            self.wfile.write(f"data: {json.dumps(final)}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            return True
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True
            return False

    def non_stream_completion(self, model: str, content: str) -> dict[str, Any]:
        """OpenAI-shaped non-streaming completion object (synthetic, marked)."""
        return marked(
            {
                "id": f"chatcmpl-fake-{int(time.time() * 1000)}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                },
            }
        )
