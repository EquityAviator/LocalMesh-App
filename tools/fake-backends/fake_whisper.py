"""Fake Whisper-class speech-to-text service (M7; FR-MM-02, S-13).

Test asset only — NOT part of the Agent and not on any content path.

Implements the OpenAI audio-API conventions the `whisper` backend kind speaks
(adapters/backends/whisper.py):
  GET  /v1/models                  model list (OpenAI shape)
  POST /v1/audio/transcriptions    multipart (file, model, language?) -> {"text": "…"}

UNVERIFIED_SHAPE rule (same as fake_core): no real Whisper-service fixture
exists at capture time (docs/fixtures/CAPTURE.md); every response carries the
marker. The transcript is DETERMINISTIC test scaffolding — it echoes a fixed
sentence annotated with the received audio size, so tests can assert the
multipart body actually carried the bytes. It is NOT captured-from-real
behaviour; fixtures from a real Whisper service outrank it (§21.5).

Scenario headers (fake_core):
  ok                    -> deterministic transcript
  http-500              -> synthetic 500
  slow-first-token      -> delay before answering (duration test)

Run (test tool; not a product contract):
  python fake_whisper.py --port 9000 [--fixtures-dir docs/fixtures/whisper/<version>]
"""

from __future__ import annotations

import argparse
import re
import time
from pathlib import Path
from typing import Any

from fake_core import (
    UNVERIFIED,
    FakeBackendServer,
    FakeHandler,
    marked,
)

DEFAULT_MODEL = "whisper-fake-small"


def parse_multipart(body: bytes, content_type: str) -> dict[str, Any]:
    """Minimal multipart/form-data parser (fake-only; stdlib re based).

    Returns {"fields": {name: str}, "files": {name: bytes}}. Good enough for
    the fixed Whisper-service upload shape; NOT a product component.
    """
    match = re.search(r"boundary=([^;]+)", content_type)
    fields: dict[str, str] = {}
    files: dict[str, bytes] = {}
    if match is None:
        return {"fields": fields, "files": files}
    boundary = match.group(1).strip('"').encode("utf-8")
    for part in body.split(b"--" + boundary):
        part = part.strip(b"\r\n")
        if not part or part == b"--":
            continue
        header_blob, _sep, payload = part.partition(b"\r\n\r\n")
        name_match = re.search(rb'name="([^"]+)"', header_blob)
        filename_match = re.search(rb'filename="([^"]*)"', header_blob)
        if name_match is None:
            continue
        name = name_match.group(1).decode("utf-8")
        if filename_match is not None:
            files[name] = payload.rstrip(b"\r\n")
        else:
            fields[name] = payload.decode("utf-8", errors="replace").strip()
    return {"fields": fields, "files": files}


class FakeWhisperHandler(FakeHandler):
    server: FakeWhisper

    # -- HTTP dispatch -------------------------------------------------------

    def do_GET(self) -> None:
        self.route_get(self.path.split("?", 1)[0])

    def do_POST(self) -> None:
        self.route_post(self.path.split("?", 1)[0])

    # -- routes ------------------------------------------------------------

    def route_get(self, path: str) -> None:
        if path == "/v1/models":
            if self.maybe_fail():
                return
            self.send_json(
                self.fixture_response(
                    "v1-models.json",
                    lambda: marked(
                        {
                            "object": "list",
                            "data": [
                                {
                                    "id": m,
                                    "object": "model",
                                    "owned_by": "localmesh-fake",
                                }
                                for m in self.server.models
                            ],
                        }
                    ),
                )
            )
            return
        self.send_json(marked({"error": {"message": f"not found: {path}"}}), status=404)

    def route_post(self, path: str) -> None:
        if path == "/v1/audio/transcriptions":
            self.transcriptions()
            return
        self.send_json(marked({"error": {"message": f"not found: {path}"}}), status=404)

    def transcriptions(self) -> None:
        if self.maybe_fail():
            return
        scenario = self.scenario
        if scenario.is_slow_first_token:
            time.sleep(max(0, scenario.delay_ms) / 1000.0)
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        parsed = parse_multipart(raw, self.headers.get("Content-Type", ""))
        audio = parsed["files"].get("file", b"")
        model = parsed["fields"].get("model", DEFAULT_MODEL)
        language = parsed["fields"].get("language")
        if not audio:
            self.send_json(
                marked({"error": {"message": "missing file field"}}), status=400
            )
            return
        # Deterministic scaffold transcript: asserts the bytes arrived intact
        # without claiming real Whisper behaviour (UNVERIFIED_SHAPE).
        transcript = f"Fake transcript of {len(audio)} bytes via {model}"
        if language:
            transcript += f" [{language}]"
        self.send_json(
            self.fixture_response(
                "transcriptions.json", lambda: marked({"text": transcript})
            )
        )


class FakeWhisper(FakeBackendServer):
    """Loopback-only fake STT service; optional bearer auth like fake LM Studio."""

    def __init__(
        self,
        address: tuple[str, int],
        *,
        auth_token: str | None = None,
        fixtures_dir: Path | None = None,
    ) -> None:
        super().__init__(
            address,
            FakeWhisperHandler,
            auth_token=auth_token,
            fixtures_dir=fixtures_dir,
        )
        self.models: list[str] = [DEFAULT_MODEL]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fake Whisper-class STT service (test asset, M7 FR-MM-02)"
    )
    parser.add_argument("--port", type=int, default=9000)
    parser.add_argument("--host", default="127.0.0.1")  # loopback only (SEC-N2 spirit)
    parser.add_argument("--token", default=None, help="optional bearer token")
    parser.add_argument(
        "--fixtures-dir",
        default=None,
        help="dir with recorded fixtures (see docs/fixtures)",
    )
    args = parser.parse_args()

    fixtures = Path(args.fixtures_dir) if args.fixtures_dir else None
    server = FakeWhisper(
        (args.host, args.port), auth_token=args.token, fixtures_dir=fixtures
    )
    print(f"fake Whisper on http://{args.host}:{args.port} shape={UNVERIFIED}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
