"""Self-tests: fake LM Studio (WP-03).

Covers the §21.5 behaviours for this Backend: SSE with [DONE], mid-stream
disconnect, slow first token (cold load), HTTP 500, model-list shape variants,
no-auth and token-auth modes. Also asserts the Appendix C traps are absent.
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx
from fake_core import DELAY_HEADER, MARKER_KEY, RECORDED, SCENARIO_HEADER, UNVERIFIED
from fake_lmstudio import DEFAULT_MODEL, FakeLMStudio

SSE_HEADER = "text/event-stream"


def base_url(server: FakeLMStudio) -> str:
    return f"http://127.0.0.1:{server.server_address[1]}"


# -- auth modes (§6.1: default no-auth, optional bearer token) ----------------


def test_no_auth_mode_by_default(make_lmstudio: Any) -> None:
    server = make_lmstudio(cold_load_ms=0)
    assert server.auth_token is None
    resp = httpx.get(f"{base_url(server)}/v1/models")
    assert resp.status_code == 200


def test_token_auth_mode_rejects_missing_and_wrong(make_lmstudio: Any) -> None:
    server = make_lmstudio(auth_token="secret-token", cold_load_ms=0)
    url = f"{base_url(server)}/v1/models"
    assert httpx.get(url).status_code == 401
    assert httpx.get(url, headers={"Authorization": "Bearer wrong"}).status_code == 401
    ok = httpx.get(url, headers={"Authorization": "Bearer secret-token"})
    assert ok.status_code == 200


def test_token_auth_applies_to_every_endpoint(make_lmstudio: Any) -> None:
    server = make_lmstudio(auth_token="secret-token", cold_load_ms=0)
    url = base_url(server)
    get_resp = httpx.get(f"{url}/api/v1/models")
    post_resp = httpx.post(f"{url}/v1/chat/completions", json={"stream": False})
    assert get_resp.status_code == 401
    assert post_resp.status_code == 401


# -- model lists + shape variants (§21.5) --------------------------------------


def test_native_model_list_marked_unverified(make_lmstudio: Any) -> None:
    server = make_lmstudio(cold_load_ms=0)
    resp = httpx.get(f"{base_url(server)}/api/v1/models")
    assert resp.status_code == 200
    assert resp.headers["X-Fake-Backend-Shape"] == UNVERIFIED
    body = resp.json()
    assert body[MARKER_KEY]["shape"] == UNVERIFIED
    ids = [item["id"] for item in body["data"]]
    assert DEFAULT_MODEL in ids


def test_openai_model_list(make_lmstudio: Any) -> None:
    server = make_lmstudio(cold_load_ms=0)
    resp = httpx.get(f"{base_url(server)}/v1/models")
    assert resp.status_code == 200
    body = resp.json()
    assert body["object"] == "list"
    assert body[MARKER_KEY]["shape"] == UNVERIFIED


def test_model_list_shape_variants(make_lmstudio: Any) -> None:
    server = make_lmstudio(cold_load_ms=0)
    url = f"{base_url(server)}/api/v1/models"
    variant_b = httpx.get(url, headers={SCENARIO_HEADER: "shape-variant-b"}).json()["data"]
    assert "context_length" in variant_b[0]
    variant_c = httpx.get(url, headers={SCENARIO_HEADER: "shape-variant-c"}).json()["data"]
    assert "max_context_len" in variant_c[0] and "extra_unknown_field" in variant_c[0]
    variant_a = httpx.get(url, headers={SCENARIO_HEADER: "shape-variant-a"}).json()["data"]
    assert list(variant_a[0].keys()) == ["id"]


# -- chat: SSE with [DONE] (§21.5) ----------------------------------------------


def collect_sse(resp: httpx.Response) -> list[str]:
    return [line for line in resp.iter_lines() if line.startswith("data: ")]


def test_streaming_sse_ends_with_done(make_lmstudio: Any) -> None:
    server = make_lmstudio(cold_load_ms=0)
    with httpx.Client() as client:
        with client.stream(
            "POST",
            f"{base_url(server)}/v1/chat/completions",
            json={"model": DEFAULT_MODEL, "stream": True, "messages": []},
        ) as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith(SSE_HEADER)
            data_lines = collect_sse(resp)
    assert data_lines[-1] == "data: [DONE]"
    first_chunk = json.loads(data_lines[0].removeprefix("data: "))
    assert first_chunk[MARKER_KEY]["shape"] == UNVERIFIED
    assert first_chunk["choices"][0]["delta"]["content"]
    assert first_chunk["object"] == "chat.completion.chunk"


def test_mid_stream_disconnect_has_no_done(make_lmstudio: Any) -> None:
    server = make_lmstudio(cold_load_ms=0)
    with httpx.Client() as client:
        with client.stream(
            "POST",
            f"{base_url(server)}/v1/chat/completions",
            json={"model": DEFAULT_MODEL, "stream": True, "messages": []},
            headers={SCENARIO_HEADER: "mid-stream-disconnect"},
        ) as resp:
            data_lines = collect_sse(resp)
    assert len(data_lines) >= 1
    assert all(line != "data: [DONE]" for line in data_lines)


def test_http_500_scenario(make_lmstudio: Any) -> None:
    server = make_lmstudio(cold_load_ms=0)
    resp = httpx.post(
        f"{base_url(server)}/v1/chat/completions",
        json={"model": DEFAULT_MODEL, "stream": True},
        headers={SCENARIO_HEADER: "http-500"},
    )
    assert resp.status_code == 500
    assert resp.json()[MARKER_KEY]["shape"] == UNVERIFIED


def test_slow_first_token_scenario(make_lmstudio: Any) -> None:
    server = make_lmstudio(cold_load_ms=0)
    started = time.monotonic()
    with httpx.Client() as client:
        with client.stream(
            "POST",
            f"{base_url(server)}/v1/chat/completions",
            json={"model": DEFAULT_MODEL, "stream": True, "messages": []},
            headers={SCENARIO_HEADER: "slow-first-token", DELAY_HEADER: "400"},
        ) as resp:
            collect_sse(resp)
    assert time.monotonic() - started >= 0.35


def test_cold_load_then_warm(make_lmstudio: Any) -> None:
    server = make_lmstudio(cold_load_ms=350)  # model starts unloaded

    def stream_once() -> float:
        started = time.monotonic()
        with httpx.Client() as client:
            with client.stream(
                "POST",
                f"{base_url(server)}/v1/chat/completions",
                json={"model": DEFAULT_MODEL, "stream": True, "messages": []},
            ) as resp:
                collect_sse(resp)
        return time.monotonic() - started

    cold = stream_once()
    warm = stream_once()
    assert cold >= 0.3, "first chat on an unloaded model must simulate cold load"
    assert warm < 0.3, "second chat must not pay the cold-load delay again"


def test_non_stream_completion(make_lmstudio: Any) -> None:
    server = make_lmstudio(cold_load_ms=0)
    resp = httpx.post(
        f"{base_url(server)}/v1/chat/completions",
        json={"model": DEFAULT_MODEL, "stream": False, "messages": []},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["object"] == "chat.completion"
    assert body["choices"][0]["message"]["content"]
    assert body[MARKER_KEY]["shape"] == UNVERIFIED


# -- native load/unload + Appendix C traps ---------------------------------------


def test_native_load_unload_acknowledged(make_lmstudio: Any) -> None:
    server = make_lmstudio(cold_load_ms=0)
    url = base_url(server)
    load = httpx.post(f"{url}/api/v1/models/load", json={"model": DEFAULT_MODEL})
    assert load.status_code == 200
    assert load.json()[MARKER_KEY]["shape"] == UNVERIFIED
    unload = httpx.post(f"{url}/api/v1/models/unload", json={"model": DEFAULT_MODEL})
    assert unload.status_code == 200


def test_appendix_c_traps_are_absent(make_lmstudio: Any) -> None:
    """The fake must NOT have /v1/list_models, /v1/load_model, /api/v0/*, /api/v1/chat."""
    server = make_lmstudio(cold_load_ms=0)
    url = base_url(server)
    assert httpx.get(f"{url}/v1/list_models").status_code == 404
    assert httpx.post(f"{url}/v1/load_model", json={}).status_code == 404
    assert httpx.get(f"{url}/api/v0/models").status_code == 404
    assert httpx.post(f"{url}/api/v1/chat", json={}).status_code == 404


# -- fixture mode (fixtures outrank fakes, §21.5) ---------------------------------


def test_recorded_fixture_is_served_verbatim(make_lmstudio: Any, tmp_path: Any) -> None:
    (tmp_path / "v1-models.json").write_text(
        '{"object": "list", "data": [{"id": "recorded-from-real-backend"}]}'
    )
    server = make_lmstudio(cold_load_ms=0, fixtures_dir=tmp_path)
    resp = httpx.get(f"{base_url(server)}/v1/models")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"] == [{"id": "recorded-from-real-backend"}]
    assert body[MARKER_KEY]["shape"] == RECORDED
