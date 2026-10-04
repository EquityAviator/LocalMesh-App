"""Fake Ollama server (WP-03; LM-ARCH-001 §10.1, §21.5).

Endpoints implemented (§6.2):
  GET  /api/tags              models on disk (shape -> UNVERIFIED_SHAPE until captured)
  GET  /api/ps                models in memory incl. VRAM footprint
  POST /api/show              model details incl. context length / quantization
  POST /v1/chat/completions   OpenAI-compatible chat, stream=true -> SSE with [DONE]
  POST /api/chat              native chat (NDJSON stream) — kept for keep-warm tests
                              (§6.2 recommends warming via native endpoints; ADR-009
                              forbids using native chat for inference in v1)

Deliberately NOT implemented: /api/generate (not needed by any M0–M5 flow), and
any auth (Ollama has NO authentication, §6.2 — a token-auth fake Ollama would be
wrong by construction).

`keep_alive` on the /v1 path is [UNVERIFIED] (§6.2): the fake ignores it, which
matches the safe assumption; the CAPTURE.md probe will settle it.

Run (test tool; not a product contract):
  python fake_ollama.py --port 11434 [--fixtures-dir docs/fixtures/ollama/<version>]
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from fake_core import (
    UNVERIFIED,
    FakeBackendServer,
    FakeHandler,
    embeddings_response,
    marked,
)

DEFAULT_MODEL = "qwen-fake:7b"

DEFAULT_ON_DISK = ["qwen-fake:7b", "llama-fake:8b"]
DEFAULT_IN_MEMORY = ["qwen-fake:7b"]  # fake "loaded" set


class FakeOllamaHandler(FakeHandler):
    server: FakeOllama

    # -- shapes ------------------------------------------------------------

    def tags_models(self, variant: str) -> list[dict[str, Any]]:
        if variant == "b":
            return [
                {
                    "name": m,
                    "model": m,
                    "size": 4700000000,
                    "digest": f"fake{'0' * 56}",
                    "details": {"parameter_size": "7B", "quantization_level": "Q4_K_M"},
                }
                for m in DEFAULT_ON_DISK
            ]
        if variant == "c":
            return [
                {
                    "name": m,
                    "model": m,
                    "modified_at": "2026-01-01T00:00:00Z",
                    "extra": [1, 2],
                }
                for m in DEFAULT_ON_DISK
            ]
        return [{"name": m} for m in DEFAULT_ON_DISK]

    def ps_models(self, variant: str) -> list[dict[str, Any]]:
        # WP-15 part 2: the in-memory set is SERVER state (mutated by demand-
        # load on native chat / chat completions and by keep-warm pings), so
        # adapter tests can observe a keep_warm() call flipping list state.
        in_memory = sorted(self.server.in_memory)
        if variant == "c":
            return [
                {"name": m, "model": m, "vram_bytes": 5000000000} for m in in_memory
            ]
        return [
            {
                "name": m,
                "model": m,
                "size": 4700000000,
                "size_vram": 5000000000,
                "expires_at": "2026-01-01T00:05:00Z",
            }
            for m in in_memory
        ]

    def show_body(self) -> dict[str, Any]:
        return {
            "license": "<license text omitted by fake>",
            "modelfile": "<modelfile omitted by fake>",
            "parameters": "stop                           <|im_end|>",
            "template": "<template omitted by fake>",
            "details": {
                "parent_model": None,
                "format": "gguf",
                "family": "qwen2",
                "families": ["qwen2"],
                "parameter_size": "7B",
                "quantization_level": "Q4_K_M",
            },
            "model_info": {
                "general.architecture": "qwen2",
                "general.parameter_count": 7615622400,
            },
        }

    # -- routes ------------------------------------------------------------

    def route_get(self, path: str) -> None:
        scenario = self.scenario
        if path == "/api/tags":
            if self.maybe_fail():
                return
            self.send_json(
                self.fixture_response(
                    "api-tags.json",
                    lambda: marked(
                        {"models": self.tags_models(scenario.shape_variant)}
                    ),
                )
            )
            return
        if path == "/api/ps":
            if self.maybe_fail():
                return
            self.send_json(
                self.fixture_response(
                    "api-ps.json",
                    lambda: marked({"models": self.ps_models(scenario.shape_variant)}),
                )
            )
            return
        self.send_json(marked({"error": f"not found: {path}"}), status=404)

    def route_post(self, path: str) -> None:
        body = self.read_json_body()
        if path == "/api/show":
            if self.maybe_fail():
                return
            self.send_json(self.fixture_response("api-show.json", self.show_body))
            return
        if path == "/v1/chat/completions":
            self.chat_completions(body)
            return
        if path == "/v1/embeddings":
            # M7 (FR-MM-03): OpenAI-compatible embeddings (§6.2 documents
            # /v1/embeddings for Ollama); deterministic fake vectors.
            if self.maybe_fail():
                return
            inputs = body.get("input")
            if not isinstance(inputs, list):
                inputs = [str(inputs or "")]
            self.send_json(
                embeddings_response(
                    str(body.get("model") or DEFAULT_MODEL), [str(t) for t in inputs]
                )
            )
            return
        if path == "/api/chat":
            self.native_chat(body)
            return
        self.send_json(marked({"error": f"not found: {path}"}), status=404)

    def chat_completions(self, body: dict[str, Any]) -> None:
        if self.maybe_fail():
            return
        model = str(body.get("model") or DEFAULT_MODEL)
        # Demand-load mirrors real behaviour: any chat request loads the model
        # (keep_alive on the /v1 path is [UNVERIFIED] §6.2 — the fake ignores
        # it, matching the safe assumption; CAPTURE.md probe will settle it).
        self.server.in_memory.add(model)
        # M8 (FR-AGENT-RT): tools present + the scaffold marker in the last
        # user message -> one function-call turn (SSE deltas when streamed,
        # JSON when not). Deterministic scaffolding (UNVERIFIED_SHAPE) — NOT
        # real Ollama behaviour.
        tools = body.get("tools")
        if isinstance(tools, list) and tools:
            messages = body.get("messages")
            last = messages[-1] if isinstance(messages, list) and messages else {}
            content = last.get("content") if isinstance(last, dict) else ""
            if isinstance(content, str) and content.startswith("CALL_TOOL:"):
                tool_name, _, arg_blob = content[len("CALL_TOOL:") :].partition(":")
                self.send_tool_call_turn(model, str(tool_name), arg_blob or "{}")
                return
        if body.get("stream"):
            self.stream_chat(
                model, pieces=["Hello", " from", " fake", " Ollama", "."], gap_ms=10
            )
            return
        self.send_json(self.non_stream_completion(model, "Hello from fake Ollama."))

    def send_tool_call_turn(self, model: str, tool_name: str, arguments: str) -> None:
        """One tool_calls turn: SSE delta form (upstream is always SSE per
        ADR-009's single-parser rule) ending with [DONE]."""
        self.start_sse()
        try:
            self.wfile.write(b": localmesh-fake-shape: UNVERIFIED_SHAPE\n\n")
            chunk_id = f"chatcmpl-fake-{int(time.time() * 1000)}"
            created = int(time.time())
            delta: dict[str, Any] = {
                "id": chunk_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "tool_calls": [
                                {
                                    "id": "call_fake_1",
                                    "type": "function",
                                    "function": {
                                        "name": tool_name,
                                        "arguments": arguments,
                                    },
                                }
                            ]
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
            }
            self.wfile.write(f"data: {json.dumps(marked(delta))}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True

    def native_chat(self, body: dict[str, Any]) -> None:
        """NDJSON stream (Ollama native default). Shape UNVERIFIED — no fixture yet.

        WP-15 part 2: an empty-messages body is the §16.5/§6.2 keep-warm ping —
        it loads the model and refreshes the idle timer, which the fake mirrors
        by moving the model into `in_memory` (observable via `/api/ps`).
        """
        if self.maybe_fail():
            return
        model = str(body.get("model") or DEFAULT_MODEL)
        messages = body.get("messages")
        if isinstance(messages, list) and not messages:
            self.server.warm_pings[model] = self.server.warm_pings.get(model, 0) + 1
        self.server.in_memory.add(model)
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Connection", "close")
        self.send_header("X-Fake-Backend-Shape", UNVERIFIED)
        self.end_headers()
        try:
            for piece in ["Hello", " from", " native", " chat", "."]:
                line = marked(
                    {
                        "model": model,
                        "created_at": "2026-01-01T00:00:00Z",
                        "message": {"role": "assistant", "content": piece},
                        "done": False,
                    }
                )
                self.wfile.write(f"{json.dumps(line)}\n".encode())
                self.wfile.flush()
                time.sleep(0.01)
            done = marked(
                {
                    "model": model,
                    "created_at": "2026-01-01T00:00:01Z",
                    "done": True,
                    "done_reason": "stop",
                }
            )
            self.wfile.write(f"{json.dumps(done)}\n".encode())
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True

    # -- HTTP dispatch -------------------------------------------------------

    def do_GET(self) -> None:
        self.route_get(self.path.split("?", 1)[0])

    def do_POST(self) -> None:
        self.route_post(self.path.split("?", 1)[0])


class FakeOllama(FakeBackendServer):
    """Ollama has no auth (§6.2): auth_token stays None by construction.

    WP-15 part 2: `in_memory` starts as a copy of DEFAULT_IN_MEMORY and is
    mutated by chat/native-chat demand-load and keep-warm pings (server state,
    observable via /api/ps); `warm_pings` counts §16.5 keep-warm pings per
    model for test assertions only (test-tool surface, no contract).
    """

    def __init__(
        self, address: tuple[str, int], fixtures_dir: Path | None = None
    ) -> None:
        super().__init__(
            address, FakeOllamaHandler, auth_token=None, fixtures_dir=fixtures_dir
        )
        self.in_memory: set[str] = set(DEFAULT_IN_MEMORY)
        self.warm_pings: dict[str, int] = {}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fake Ollama backend (test asset, no auth per §6.2)"
    )
    parser.add_argument("--port", type=int, default=11434)
    parser.add_argument("--host", default="127.0.0.1")  # loopback only (SEC-N2 spirit)
    parser.add_argument(
        "--fixtures-dir",
        default=None,
        help="dir with recorded fixtures (see docs/fixtures)",
    )
    args = parser.parse_args()

    fixtures = Path(args.fixtures_dir) if args.fixtures_dir else None
    server = FakeOllama((args.host, args.port), fixtures_dir=fixtures)
    print(
        f"fake Ollama on http://{args.host}:{args.port} [no-auth per §6.2] shape={UNVERIFIED}"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
