"""Stream-timeout budget unit tests (§10.3 rule 4) — CI-18/CI-21 Agent side.

Rule 4 defines two DIFFERENT silence budgets for a Backend stream:
- first-token gap (cold model load): `first_token_timeout_s` (default 120 s);
- gaps after the first parsed chunk: 60 s idle.
Before the 2026-10 hardening round the idle budget was applied uniformly, so
a silent 90 s cold load was killed at 60 s (spec violation) and the API layer
hardened the wait at 30 s with an uncaught TimeoutError (no terminal
mesh.error, NFR-REL-02 violation). These tests pin the fixed semantics.
"""

import asyncio
import time
from collections.abc import AsyncIterator

import httpx
import pytest

from localmesh_agent.adapters.backends.openai_compat import OpenAICompatBackend
from localmesh_agent.adapters.ports import CancelToken, ChatMessage, ChatRequest
from localmesh_agent.core.errors import MeshError


def make_chat_request() -> ChatRequest:
    return ChatRequest(
        model="b::m",
        backend_model_id="m",
        messages=(ChatMessage(role="user", content="Hi"),),
    )


def sse_stream(first_delay_s: float, chunk_gap_s: float, chunks: int = 2) -> AsyncIterator[bytes]:
    """Raw SSE byte stream with controllable timing.

    first_delay_s: silence before the first data event (cold load).
    chunk_gap_s: silence between data events (post-first-token idle).
    Terminates with [DONE] once all chunks are sent (timeout tests raise
    before reaching it).
    """

    async def gen() -> AsyncIterator[bytes]:
        if first_delay_s:
            await asyncio.sleep(first_delay_s)
        for i in range(chunks):
            if i > 0 and chunk_gap_s:
                await asyncio.sleep(chunk_gap_s)
            yield (
                f'data: {{"id":"c{i}","object":"chat.completion.chunk","choices":'
                f'[{{"index":0,"delta":{{"content":"x{i}"}},"finish_reason":null}}]}}\n\n'
            ).encode()
        yield b"data: [DONE]\n\n"

    return gen()


def make_stream_backend(
    *,
    first_delay_s: float,
    chunk_gap_s: float,
    chunks: int,
    first_token_timeout_s: float,
    idle_chunk_timeout_s: float,
) -> OpenAICompatBackend:
    """Backend over a MockTransport serving the timed SSE stream above."""
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            content=sse_stream(
                first_delay_s=first_delay_s,
                chunk_gap_s=chunk_gap_s,
                chunks=chunks,
            ),
        )
    )
    return OpenAICompatBackend(
        "b",
        "http://b.test",
        first_token_timeout_s=first_token_timeout_s,
        idle_chunk_timeout_s=idle_chunk_timeout_s,
        client=httpx.AsyncClient(transport=transport),
    )


async def collect_chunks(backend: OpenAICompatBackend, token: CancelToken) -> list[str]:
    out: list[str] = []
    async for chunk in backend.stream_chat(make_chat_request(), token):
        if chunk.delta_content is not None:
            out.append(chunk.delta_content)
    return out


async def test_first_token_gap_gets_first_token_budget_not_idle_budget() -> None:
    """A silent cold load longer than the IDLE budget but shorter than the
    FIRST-TOKEN budget must survive (old code killed it at the idle budget)."""
    backend = make_stream_backend(
        first_delay_s=0.15,
        chunk_gap_s=0.0,
        chunks=1,
        first_token_timeout_s=1.0,
        idle_chunk_timeout_s=0.02,  # 0.15 s silence > idle, < first-token
    )
    try:
        started = time.monotonic()
        out = await collect_chunks(backend, CancelToken())
        assert out == ["x0"]
        assert time.monotonic() - started < 0.9  # not the 1 s first-token cap
    finally:
        await backend.aclose()


async def test_post_first_token_gap_uses_idle_budget() -> None:
    """After the first parsed chunk, a gap beyond the IDLE budget is dead
    (BACKEND_TIMEOUT), even though it is below the first-token budget."""
    backend = make_stream_backend(
        first_delay_s=0.0,
        chunk_gap_s=0.12,
        chunks=2,
        first_token_timeout_s=1.0,
        idle_chunk_timeout_s=0.02,  # 0.12 s gap > idle after first chunk
    )
    try:
        with pytest.raises(MeshError) as excinfo:
            await collect_chunks(backend, CancelToken())
        assert excinfo.value.code == "BACKEND_TIMEOUT"
    finally:
        await backend.aclose()


async def test_silent_backend_times_out_at_first_token_budget() -> None:
    """No bytes at all within the first-token budget -> BACKEND_TIMEOUT."""
    backend = make_stream_backend(
        first_delay_s=30.0,
        chunk_gap_s=0.0,
        chunks=1,
        first_token_timeout_s=0.05,
        idle_chunk_timeout_s=10.0,  # idle budget alone would never fire here
    )
    try:
        with pytest.raises(MeshError) as excinfo:
            await collect_chunks(backend, CancelToken())
        assert excinfo.value.code == "BACKEND_TIMEOUT"
        # Appendix D: BACKEND_TIMEOUT is 504 + retryable.
        assert excinfo.value.http_status == 504
        assert excinfo.value.retryable is True
    finally:
        await backend.aclose()


async def test_default_budgets_match_spec() -> None:
    """§10.3 rule 4 defaults: connect 3 s, first-token 120 s, idle 60 s,
    total cap 900 s (15 min)."""
    from localmesh_agent.adapters.ports import (
        CONNECT_TIMEOUT_S,
        DEFAULT_FIRST_TOKEN_TIMEOUT_S,
        DEFAULT_TOTAL_STREAM_CAP_S,
        IDLE_CHUNK_TIMEOUT_S,
    )

    assert CONNECT_TIMEOUT_S == 3.0
    assert DEFAULT_FIRST_TOKEN_TIMEOUT_S == 120.0
    assert IDLE_CHUNK_TIMEOUT_S == 60.0
    assert DEFAULT_TOTAL_STREAM_CAP_S == 900.0
    backend = OpenAICompatBackend("b", "http://b.test")
    assert backend._first_token_timeout_s == 120.0  # noqa: SLF001 — spec pin
    assert backend._idle_chunk_timeout_s == 60.0  # noqa: SLF001 — spec pin
    await backend.aclose()


async def test_backends_constructed_by_app_honor_config_limits() -> None:
    """Appendix E [limits] knobs reach the adapters via build_adapters
    (§10.3 rule 4 "configurable" — the wiring used to drop them)."""
    from pathlib import Path

    from localmesh_agent.app import build_adapters
    from localmesh_agent.config import Settings

    settings = Settings(
        agent={"data_dir": str(Path("/tmp/lm-test-adapters"))},
        limits={"first_token_timeout_seconds": 77, "max_stream_seconds": 321},
        backends=[
            {"id": "lms", "kind": "lmstudio", "base_url": "http://127.0.0.1:1"},
            {"id": "oll", "kind": "ollama", "base_url": "http://127.0.0.1:2"},
            {"id": "gen", "kind": "openai_compat", "base_url": "http://127.0.0.1:3"},
        ],
    )
    adapters = build_adapters(settings)
    try:
        assert len(adapters) == 3
        for adapter in adapters:
            assert adapter._first_token_timeout_s == 77.0  # noqa: SLF001
            assert adapter._total_stream_cap_s == 321.0  # noqa: SLF001
    finally:
        for adapter in adapters:
            await adapter.aclose()
