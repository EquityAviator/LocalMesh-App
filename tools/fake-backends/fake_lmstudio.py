"""Fake LM Studio server (WP-03; LM-ARCH-001 §10.1, §21.5).

Endpoints implemented (§6.1 only — see Appendix C traps for what must NOT exist):
  GET  /api/v1/models                 native model list (shape unknown -> UNVERIFIED_SHAPE)
  POST /api/v1/models/load            native load trigger (request/response shapes unknown)
  POST /api/v1/models/unload          native unload trigger (request/response shapes unknown)
  GET  /v1/models                     OpenAI-compatible model list
  POST /v1/chat/completions           OpenAI-compatible chat, stream=true -> SSE with [DONE]

Deliberately NOT implemented (real LM Studio does not have them / they are traps):
  /v1/list_models, /v1/load_model, /api/v0/* (404), and /api/v1/chat (native chat
  is not used in v1 per ADR-009; a 404 here lets tests assert agents never call it).

Auth (§6.1): the real native server can be configured to require a bearer API
token; default accepts unauthenticated local requests. Fake modes:
  --auth none                (default)
  --auth token --token X     requires `Authorization: Bearer X` on every endpoint

Run (test tool; not a product contract):
  python fake_lmstudio.py --port 1234 [--auth none|token --token SECRET]
      [--cold-load-ms 1500] [--fixtures-dir docs/fixtures/lmstudio/<version>]
"""

from __future__ import annotations

import argparse
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

DEFAULT_MODEL = "qwen-fake-7b-instruct"

# Synthetic model state. Ids/fields are obviously synthetic and marked
# UNVERIFIED_SHAPE in responses (no recorded fixture at capture time).
DEFAULT_MODELS: list[dict[str, Any]] = [
    {"id": DEFAULT_MODEL, "object": "model", "owned_by": "localmesh-fake"},
    {"id": "llama-fake-3-8b", "object": "model", "owned_by": "localmesh-fake"},
]


class FakeLMStudioHandler(FakeHandler):
    server: FakeLMStudio

    # -- model state -------------------------------------------------------

    @property
    def loaded(self) -> set[str]:
        return self.server.loaded_models

    # -- model list shapes ---------------------------------------------------

    def native_models_items(self, variant: str) -> list[dict[str, Any]]:
        if variant == "b":
            return [
                {
                    "id": m["id"],
                    "context_length": 32768,
                    "loaded": m["id"] in self.loaded,
                    "quantization": "Q4_K_M",
                    "capabilities": ["chat"],
                }
                for m in DEFAULT_MODELS
            ]
        if variant == "c":
            return [
                {
                    "id": m["id"],
                    "max_context_len": 8192,
                    "is_loaded": m["id"] in self.loaded,
                    "quant_lvl": "Q8_0",
                    "capabilities_v2": ["chat", "vision"],
                    "extra_unknown_field": {"nested": True},
                }
                for m in DEFAULT_MODELS
            ]
        return [{"id": m["id"]} for m in DEFAULT_MODELS]

    def openai_models_items(self, variant: str) -> list[dict[str, Any]]:
        if variant == "b":
            return [
                {
                    "id": m["id"],
                    "object": "model",
                    "owned_by": "localmesh-fake",
                    "created": 0,
                }
                for m in DEFAULT_MODELS
            ]
        if variant == "c":
            return [
                {
                    "id": m["id"],
                    "object": "model",
                    "owned_by": m["owned_by"],
                    "unknown_extra": 1,
                }
                for m in DEFAULT_MODELS
            ]
        return [
            {"id": m["id"], "object": "model", "owned_by": m["owned_by"]} for m in DEFAULT_MODELS
        ]

    # -- routes ------------------------------------------------------------

    def route_get(self, path: str) -> None:
        scenario = self.scenario
        if path == "/api/v1/models":
            if self.maybe_fail():
                return
            items = self.native_models_items(scenario.shape_variant)
            self.send_json(
                self.fixture_response(
                    "api-v1-models.json",
                    lambda: marked({"object": "list", "data": items}),
                )
            )
            return
        if path == "/v1/models":
            if self.maybe_fail():
                return
            items = self.openai_models_items(scenario.shape_variant)
            self.send_json(
                self.fixture_response(
                    "v1-models.json",
                    lambda: marked({"object": "list", "data": items}),
                )
            )
            return
        self.send_json(marked({"error": {"message": f"not found: {path}"}}), status=404)

    def route_post(self, path: str) -> None:
        body = self.read_json_body()
        if path in ("/api/v1/models/load", "/api/v1/models/unload"):
            if self.maybe_fail():
                return
            model = body.get("model") or body.get("id") or DEFAULT_MODEL
            if path.endswith("/load"):
                self.loaded.add(model)
            else:
                self.loaded.discard(model)
            # Real request/response shapes are unknown (§6.1 [UNVERIFIED]); the
            # acknowledgement is deliberately minimal and UNVERIFIED-marked.
            self.send_json(marked({"ok": True, "model": model}))
            return
        if path == "/v1/chat/completions":
            self.chat_completions(body)
            return
        if path == "/v1/embeddings":
            # M7 (FR-MM-03): OpenAI-compatible embeddings (§6.1 documents
            # /v1/embeddings for LM Studio); deterministic fake vectors.
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
        self.send_json(marked({"error": {"message": f"not found: {path}"}}), status=404)

    def chat_completions(self, body: dict[str, Any]) -> None:
        if self.maybe_fail():
            return
        model = str(body.get("model") or DEFAULT_MODEL)
        stream = bool(body.get("stream"))
        cold_ms = self.server.cold_load_ms if model not in self.loaded else 0
        if stream:
            self.stream_chat(
                model,
                pieces=["Hello", " from", " fake", " LM", " Studio", "."],
                first_token_delay_ms=cold_ms,
                gap_ms=10,
            )
            # Demand-load mirrors real behaviour: after a cold chat the model is loaded.
            self.loaded.add(model)
            return
        if cold_ms:
            time.sleep(cold_ms / 1000.0)
            self.loaded.add(model)
        self.send_json(self.non_stream_completion(model, "Hello from fake LM Studio."))

    # -- HTTP dispatch -------------------------------------------------------

    def do_GET(self) -> None:
        if not self.authorized():
            self.send_unauthorized()
            return
        self.route_get(self.path.split("?", 1)[0])

    def do_POST(self) -> None:
        if not self.authorized():
            self.send_unauthorized()
            return
        self.route_post(self.path.split("?", 1)[0])


class FakeLMStudio(FakeBackendServer):
    def __init__(
        self,
        address: tuple[str, int],
        auth_token: str | None = None,
        fixtures_dir: Any = None,
        cold_load_ms: int = 1500,
    ) -> None:
        super().__init__(
            address,
            FakeLMStudioHandler,
            auth_token=auth_token,
            fixtures_dir=fixtures_dir,
        )
        self.cold_load_ms = cold_load_ms
        self.loaded_models: set[str] = set()


def main() -> int:
    parser = argparse.ArgumentParser(description="Fake LM Studio backend (test asset)")
    parser.add_argument("--port", type=int, default=1234)
    parser.add_argument("--host", default="127.0.0.1")  # loopback only (SEC-N2 spirit)
    parser.add_argument("--auth", choices=["none", "token"], default="none")
    parser.add_argument("--token", default="", help="bearer token for --auth token")
    parser.add_argument("--cold-load-ms", type=int, default=1500)
    parser.add_argument(
        "--fixtures-dir",
        default=None,
        help="dir with recorded fixtures (see docs/fixtures)",
    )
    args = parser.parse_args()

    token = args.token if args.auth == "token" else None
    if args.auth == "token" and not token:
        parser.error("--auth token requires --token")
    fixtures = None
    if args.fixtures_dir:
        fixtures = Path(args.fixtures_dir)

    server = FakeLMStudio(
        (args.host, args.port),
        auth_token=token,
        fixtures_dir=fixtures,
        cold_load_ms=args.cold_load_ms,
    )
    mode = f"token-auth ({'set' if token else 'MISSING'})" if args.auth == "token" else "no-auth"
    print(f"fake LM Studio on http://{args.host}:{args.port} [{mode}] shape={UNVERIFIED}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
