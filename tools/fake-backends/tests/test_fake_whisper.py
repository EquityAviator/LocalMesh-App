"""Self-tests: fake Whisper service (M7, FR-MM-02)."""

from __future__ import annotations

from typing import Any

import httpx
from fake_core import MARKER_KEY, UNVERIFIED
from fake_whisper import DEFAULT_MODEL, FakeWhisper


def base_url(server: FakeWhisper) -> str:
    return f"http://127.0.0.1:{server.server_address[1]}"


def test_models_marked_unverified(make_whisper: Any) -> None:
    resp = httpx.get(f"{base_url(make_whisper())}/v1/models")
    assert resp.status_code == 200
    body = resp.json()
    assert body[MARKER_KEY]["shape"] == UNVERIFIED
    assert any(m["id"] == DEFAULT_MODEL for m in body["data"])


def test_transcription_deterministic_and_size_annotating(make_whisper: Any) -> None:
    server = make_whisper()
    audio = b"RIFF" + b"\x07" * 100
    resp = httpx.post(
        f"{base_url(server)}/v1/audio/transcriptions",
        data={"model": DEFAULT_MODEL},
        files={"file": ("note.wav", audio, "application/octet-stream")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body[MARKER_KEY]["shape"] == UNVERIFIED
    assert f"{len(audio)} bytes" in body["text"]  # the bytes actually arrived


def test_transcription_requires_file_field(make_whisper: Any) -> None:
    resp = httpx.post(
        f"{base_url(make_whisper())}/v1/audio/transcriptions",
        data={"model": DEFAULT_MODEL},
    )
    assert resp.status_code == 400


def test_transcription_http_500_scenario(make_whisper: Any) -> None:
    from fake_core import SCENARIO_HEADER

    resp = httpx.post(
        f"{base_url(make_whisper())}/v1/audio/transcriptions",
        data={"model": DEFAULT_MODEL},
        files={"file": ("a.wav", b"x", "application/octet-stream")},
        headers={SCENARIO_HEADER: "http-500"},
    )
    assert resp.status_code == 500
