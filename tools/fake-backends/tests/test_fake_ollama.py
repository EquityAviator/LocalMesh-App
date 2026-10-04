"""Self-tests: fake Ollama (WP-03).

Covers the §21.5 behaviours for this Backend: SSE with [DONE], mid-stream
disconnect, slow first token, HTTP 500, model-list shape variants. Ollama has
NO authentication (§6.2) — asserted by construction.
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx
from fake_core import DELAY_HEADER, MARKER_KEY, RECORDED, SCENARIO_HEADER, UNVERIFIED
from fake_ollama import DEFAULT_MODEL, FakeOllama


def base_url(server: FakeOllama) -> str:
    return f"http://127.0.0.1:{server.server_address[1]}"


def test_no_auth_by_construction(make_ollama: Any) -> None:
    server = make_ollama()
    assert server.auth_token is None, "Ollama has no auth (§6.2); fake must not add any"
    for path in ("/api/tags", "/api/ps"):
        resp = httpx.get(f"{base_url(server)}{path}")
        assert resp.status_code == 200, path


def test_api_tags_marked_unverified(make_ollama: Any) -> None:
    resp = httpx.get(f"{base_url(make_ollama())}/api/tags")
    assert resp.status_code == 200
    body = resp.json()
    assert body[MARKER_KEY]["shape"] == UNVERIFIED
    assert {"name": DEFAULT_MODEL} in body["models"] or any(
        m["name"] == DEFAULT_MODEL for m in body["models"]
    )


def test_api_tags_shape_variants(make_ollama: Any) -> None:
    server = make_ollama()
    url = f"{base_url(server)}/api/tags"
    variant_a = httpx.get(url, headers={SCENARIO_HEADER: "shape-variant-a"}).json()["models"]
    assert list(variant_a[0].keys()) == ["name"]
    variant_b = httpx.get(url, headers={SCENARIO_HEADER: "shape-variant-b"}).json()["models"]
    assert "details" in variant_b[0]
    variant_c = httpx.get(url, headers={SCENARIO_HEADER: "shape-variant-c"}).json()["models"]
    assert "extra" in variant_c[0]


def test_api_ps_and_show(make_ollama: Any) -> None:
    server = make_ollama()
    ps = httpx.get(f"{base_url(server)}/api/ps")
    assert ps.status_code == 200
    assert ps.json()[MARKER_KEY]["shape"] == UNVERIFIED
    show = httpx.post(f"{base_url(server)}/api/show", json={"model": DEFAULT_MODEL})
    assert show.status_code == 200
    assert show.json()["details"]["quantization_level"]


def test_streaming_sse_ends_with_done(make_ollama: Any) -> None:
    server = make_ollama()
    with httpx.Client() as client:
        with client.stream(
            "POST",
            f"{base_url(server)}/v1/chat/completions",
            json={"model": DEFAULT_MODEL, "stream": True, "messages": []},
        ) as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/event-stream")
            data_lines = [line for line in resp.iter_lines() if line.startswith("data: ")]
    assert data_lines[-1] == "data: [DONE]"
    first_chunk = json.loads(data_lines[0].removeprefix("data: "))
    assert first_chunk["choices"][0]["delta"]["content"]


def test_mid_stream_disconnect_has_no_done(make_ollama: Any) -> None:
    server = make_ollama()
    with httpx.Client() as client:
        with client.stream(
            "POST",
            f"{base_url(server)}/v1/chat/completions",
            json={"model": DEFAULT_MODEL, "stream": True, "messages": []},
            headers={SCENARIO_HEADER: "mid-stream-disconnect"},
        ) as resp:
            data_lines = [line for line in resp.iter_lines() if line.startswith("data: ")]
    assert data_lines
    assert all(line != "data: [DONE]" for line in data_lines)


def test_http_500_scenario(make_ollama: Any) -> None:
    server = make_ollama()
    resp = httpx.get(f"{base_url(server)}/api/tags", headers={SCENARIO_HEADER: "http-500"})
    assert resp.status_code == 500


def test_slow_first_token_scenario(make_ollama: Any) -> None:
    server = make_ollama()
    started = time.monotonic()
    with httpx.Client() as client:
        with client.stream(
            "POST",
            f"{base_url(server)}/v1/chat/completions",
            json={"model": DEFAULT_MODEL, "stream": True, "messages": []},
            headers={SCENARIO_HEADER: "slow-first-token", DELAY_HEADER: "400"},
        ) as resp:
            [line for line in resp.iter_lines()]
    assert time.monotonic() - started >= 0.35


def test_non_stream_completion(make_ollama: Any) -> None:
    server = make_ollama()
    resp = httpx.post(
        f"{base_url(server)}/v1/chat/completions",
        json={"model": DEFAULT_MODEL, "stream": False, "messages": []},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["object"] == "chat.completion"


def test_native_chat_is_ndjson_marked_unverified(make_ollama: Any) -> None:
    """Native /api/chat kept for keep-warm tests (ADR-009 forbids inference use in v1)."""
    server = make_ollama()
    with httpx.Client() as client:
        with client.stream(
            "POST",
            f"{base_url(server)}/api/chat",
            json={"model": DEFAULT_MODEL, "stream": True, "messages": []},
        ) as resp:
            assert resp.status_code == 200
            lines = [line for line in resp.iter_lines() if line.strip()]
    parsed = [json.loads(line) for line in lines]
    assert parsed[-1][MARKER_KEY]["shape"] == UNVERIFIED
    assert parsed[-1]["done"] is True
    assert any(p.get("message", {}).get("content") for p in parsed[:-1])


def test_api_generate_absent(make_ollama: Any) -> None:
    """/api/generate is documented as not implemented by this fake."""
    server = make_ollama()
    resp = httpx.post(f"{base_url(server)}/api/generate", json={})
    assert resp.status_code == 404


def test_recorded_fixture_is_served_verbatim(make_ollama: Any, tmp_path: Any) -> None:
    (tmp_path / "api-tags.json").write_text('{"models": [{"name": "recorded-ollama-model"}]}')
    server = make_ollama(fixtures_dir=tmp_path)
    resp = httpx.get(f"{base_url(server)}/api/tags")
    body = resp.json()
    assert body["models"] == [{"name": "recorded-ollama-model"}]
    assert body[MARKER_KEY]["shape"] == RECORDED
