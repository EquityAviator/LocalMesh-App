"""Generic OpenAI-compatible Backend adapter (§10.3, ADR-009).

Also hosts the shared incremental SSE parser required by §10.3 rule 5:
"handles `data:` lines, `[DONE]`, comment lines, partial UTF-8 across chunk
boundaries, and `\\r\\n`".

Adapter rules implemented here (§10.3):
- Parse defensively: missing/renamed fields -> null, never exception; a
  schema-drift warning (no Content) is logged (§10.3 rule 2).
- Backend errors map to `MeshError` codes (Appendix D); raw backend error
  bodies are never forwarded (§10.3 rule 3, SEC-N3).
- Timeouts: connect 3 s; first-token configurable (default 120 s); idle
  between chunks 60 s; total per-request cap (default 15 min) (§10.3 rule 4).
- One `httpx.AsyncClient` per Backend with connection reuse (§10.5).
"""

from __future__ import annotations

import asyncio
import codecs
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from localmesh_agent.adapters.ports import (
    CONNECT_TIMEOUT_S,
    DEFAULT_FIRST_TOKEN_TIMEOUT_S,
    DEFAULT_TOTAL_STREAM_CAP_S,
    IDLE_CHUNK_TIMEOUT_S,
    BackendCaps,
    BackendModel,
    BackendStatus,
    CancelToken,
    ChatChunk,
    ChatRequest,
    SSEEvent,
)
from localmesh_agent.core.errors import MeshError
from localmesh_agent.observability.logging import get_logger

log = get_logger("adapters")

_BASE_CAPS: BackendCaps = {
    "list_models": True,
    "stream_chat": True,
    "load_unload": False,
    "keep_warm": False,
    "embeddings": False,
    "vision": False,
    "audio_in": False,
}


# ---------------------------------------------------------------------------
# SSE parsing (§10.3 rule 5)
# ---------------------------------------------------------------------------


class SSEParser:
    """Incremental Server-Sent-Events parser (§10.3 rule 5).

    Byte-level: handles partial UTF-8 sequences across chunk boundaries via an
    incremental decoder, `\r\n`/`\n`/`\r` line endings, `data:` lines
    (multi-line data joined with '\n'), and comment lines (`: ...`, dropped —
    e.g. keepalives). The literal `[DONE]` sentinel is passed through as an
    event payload; callers distinguish it.
    """

    def __init__(self) -> None:
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")
        self._buffer = ""
        self._data_lines: list[str] = []

    def feed(self, chunk: bytes) -> list[SSEEvent]:
        """Consume raw bytes; return any complete events."""
        try:
            self._buffer += self._decoder.decode(chunk)
        except UnicodeDecodeError as exc:
            raise MeshError("BACKEND_PROTOCOL", "Backend stream contained invalid UTF-8.") from exc
        events: list[SSEEvent] = []
        text = self._buffer
        lines: list[str] = []
        start = 0
        i = 0
        n = len(text)
        while i < n:
            ch = text[i]
            if ch == "\r":
                lines.append(text[start:i])
                if i + 1 < n and text[i + 1] == "\n":
                    i += 1
                start = i + 1
            elif ch == "\n":
                lines.append(text[start:i])
                start = i + 1
            i += 1
        self._buffer = text[start:]
        for line in lines:
            event = self._line(line)
            if event is not None:
                events.append(event)
        return events

    def finish(self) -> list[SSEEvent]:
        """Flush the decoder; emit a trailing unterminated event if any."""
        tail = self._decoder.decode(b"", final=True)
        if tail:
            self._buffer += tail
        events: list[SSEEvent] = []
        if self._buffer:
            event = self._line(self._buffer)
            if event is not None:
                events.append(event)
            self._buffer = ""
        return events

    def _line(self, line: str) -> SSEEvent | None:
        if line == "":
            # Blank line -> dispatch the accumulated event (if any data lines).
            if self._data_lines:
                data = "\n".join(self._data_lines)
                self._data_lines = []
                return SSEEvent(data=data)
            return None
        if line.startswith(":"):  # comment (keepalive) — ignored
            return None
        if line.startswith("data:"):
            value = line[5:]
            if value.startswith(" "):  # single optional leading space is stripped
                value = value[1:]
            self._data_lines.append(value)
        # Other SSE field lines (event:, id:, retry:) are tolerated and ignored
        # (defensive parsing, §10.3 rule 2).
        return None


# ---------------------------------------------------------------------------
# Defensive JSON helpers (§10.3 rule 2: missing/renamed -> None, never raise)
# ---------------------------------------------------------------------------


def as_str(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) else None


def as_int(payload: dict[str, Any], key: str) -> int | None:
    value = payload.get(key)
    if isinstance(value, bool):  # bool is an int subtype; not a size
        return None
    return value if isinstance(value, int) else None


def as_str_list(payload: dict[str, Any], key: str) -> tuple[str, ...] | None:
    value = payload.get(key)
    if not isinstance(value, list):
        return None
    return tuple(item for item in value if isinstance(item, str))


def warn_schema_drift(backend_id: str, endpoint: str) -> None:
    """Log a schema-drift warning — Metadata only, never Content (§10.3 rule 2)."""
    log.warning(
        "backend_schema_drift",
        extra={"backend_id": backend_id, "status": endpoint, "error_code": "BACKEND_SCHEMA_DRIFT"},
    )


def chunk_from_sse_data(data: str, backend_id: str = "backend") -> ChatChunk | None:
    """Parse one OpenAI chunk payload defensively (§10.3 rule 2).

    Malformed JSON (not just missing fields) is a protocol error (§10.7:
    "Backend returns malformed stream -> terminal BACKEND_PROTOCOL").
    """
    try:
        payload = json.loads(data)
    except json.JSONDecodeError as exc:
        raise MeshError("BACKEND_PROTOCOL", "Backend sent a malformed SSE payload.") from exc
    if not isinstance(payload, dict):
        raise MeshError("BACKEND_PROTOCOL", "Backend sent a malformed SSE payload.")
    choices = payload.get("choices")
    delta: dict[str, Any] = {}
    finish_reason: str | None = None
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        first = choices[0]
        raw_delta = first.get("delta")
        if isinstance(raw_delta, dict):
            delta = raw_delta
        raw_finish = first.get("finish_reason")
        finish_reason = raw_finish if isinstance(raw_finish, str) else None
    elif choices is not None:
        warn_schema_drift(backend_id, "/v1/chat/completions")
    usage_prompt: int | None = None
    usage_completion: int | None = None
    usage = payload.get("usage")
    if isinstance(usage, dict):
        usage_prompt = as_int(usage, "prompt_tokens")
        usage_completion = as_int(usage, "completion_tokens")
    content = delta.get("content")
    role = delta.get("role")
    chunk = ChatChunk(
        delta_content=content if isinstance(content, str) else None,
        role=role if isinstance(role, str) else None,
        finish_reason=finish_reason,
        usage_prompt_tokens=usage_prompt,
        usage_completion_tokens=usage_completion,
    )
    if chunk.delta_content is None and chunk.role is None and chunk.finish_reason is None:
        warn_schema_drift(backend_id, "/v1/chat/completions")
        return None
    return chunk


# ---------------------------------------------------------------------------
# The generic adapter
# ---------------------------------------------------------------------------


class OpenAICompatBackend:
    """User-configured generic OpenAI-compatible Backend (§10.3 column 3).

    Caps: list, stream (§10.3 table). Auth: optional Bearer (the OS keyring
    holds the secret under `auth_ref`; the adapter receives the token value —
    §17.6; wiring the keyring lookup lands with the WP-05 integration in
    `app.py`).
    """

    kind = "openai_compat"

    def __init__(
        self,
        backend_id: str,
        base_url: str,
        *,
        auth_token: str | None = None,
        first_token_timeout_s: float = DEFAULT_FIRST_TOKEN_TIMEOUT_S,
        total_stream_cap_s: float = DEFAULT_TOTAL_STREAM_CAP_S,
        idle_chunk_timeout_s: float = IDLE_CHUNK_TIMEOUT_S,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.id = backend_id  # §10.2: stable id, e.g. "openai:<name>"
        self.caps: BackendCaps = dict(_BASE_CAPS)
        self._base_url = base_url
        self._auth_token = auth_token
        self._first_token_timeout_s = first_token_timeout_s
        self._total_stream_cap_s = total_stream_cap_s
        self._idle_chunk_timeout_s = idle_chunk_timeout_s
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(
                CONNECT_TIMEOUT_S, read=first_token_timeout_s, write=30.0, pool=30.0
            ),
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    # -- helpers -------------------------------------------------------------

    def _url(self, path: str) -> str:
        return self._base_url.rstrip("/") + path

    def _headers(self, accept: str = "application/json") -> dict[str, str]:
        headers = {"Accept": accept}
        if self._auth_token is not None:
            headers["Authorization"] = f"Bearer {self._auth_token}"
        return headers

    async def _get_json(self, path: str) -> dict[str, Any] | None:
        """GET expecting a JSON object; transport/HTTP failures -> None (probe
        path turns that into `down`; list path raises BACKEND_UNAVAILABLE)."""
        try:
            response = await self._client.get(self._url(path), headers=self._headers())
        except httpx.HTTPError:
            return None
        if response.status_code != 200:
            return None
        try:
            payload = response.json()
        except json.JSONDecodeError:
            warn_schema_drift(self.id, path)
            return None
        return payload if isinstance(payload, dict) else None

    # -- §10.2 port surface ---------------------------------------------------

    async def probe(self) -> BackendStatus:
        """Probe with `GET /v1/models` (cheap) — §10.3."""
        payload = await self._get_json("/v1/models")
        if payload is None:
            return BackendStatus(backend_id=self.id, status="down")
        return BackendStatus(backend_id=self.id, status="up", version=None)

    async def list_models(self) -> list[BackendModel]:
        """`GET /v1/models` — only the OpenAI `id` field is assumed; every
        other §13.5 field stays null (never guessed from names, §13.5)."""
        payload = await self._get_json("/v1/models")
        if payload is None:
            raise MeshError("BACKEND_UNAVAILABLE", "Backend did not answer /v1/models.")
        data = payload.get("data")
        if not isinstance(data, list):
            warn_schema_drift(self.id, "/v1/models")
            return []
        models: list[BackendModel] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            model_id = as_str(item, "id")
            if model_id is None:
                warn_schema_drift(self.id, "/v1/models")
                continue
            models.append(BackendModel(backend_model_id=model_id))
        return models

    def stream_chat(  # noqa: D102  # async generator (PEP 525) — §10.2 async stream
        self, req: ChatRequest, cancel: CancelToken
    ) -> AsyncIterator[ChatChunk]:
        return self._stream_chat(req, cancel)

    async def _stream_chat(self, req: ChatRequest, cancel: CancelToken) -> AsyncIterator[ChatChunk]:
        """`POST /v1/chat/completions` stream=true (§10.3)."""
        body: dict[str, object] = {
            "model": req.backend_model_id,
            "messages": [{"role": m.role, "content": m.content} for m in req.messages],
            "stream": True,
        }
        # §13.6 allow-list pass-through only.
        if req.temperature is not None:
            body["temperature"] = req.temperature
        if req.top_p is not None:
            body["top_p"] = req.top_p
        if req.max_tokens is not None:
            body["max_tokens"] = req.max_tokens
        if req.stop is not None:
            body["stop"] = list(req.stop)
        if req.presence_penalty is not None:
            body["presence_penalty"] = req.presence_penalty
        if req.frequency_penalty is not None:
            body["frequency_penalty"] = req.frequency_penalty
        if req.seed is not None:
            body["seed"] = req.seed

        request = self._client.build_request(
            "POST",
            self._url("/v1/chat/completions"),
            json=body,
            headers=self._headers("text/event-stream"),
        )
        # §13.7: cancel must abort the upstream request ≤ 1 s — including
        # during the pre-first-byte phase (connect/cold model load), so the
        # send itself is raced against the cancel token.
        send_task = asyncio.ensure_future(self._client.send(request, stream=True))
        token_task = asyncio.ensure_future(cancel.wait())
        done, _ = await asyncio.wait(
            {send_task, token_task},
            timeout=self._first_token_timeout_s + 5.0,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if send_task not in done:
            send_task.cancel()
            raise MeshError("CANCELLED", "Cancelled while awaiting the Backend.")
        token_task.cancel()
        try:
            response = send_task.result()
        except httpx.TimeoutException as exc:
            raise MeshError("BACKEND_TIMEOUT", "No response from Backend in time.") from exc
        except httpx.HTTPError as exc:
            raise MeshError("BACKEND_UNAVAILABLE", "Backend transport failed.") from exc
        if cancel.cancelled:
            await response.aclose()
            raise MeshError("CANCELLED", "Cancelled before completion.")

        if response.status_code != 200:
            await response.aclose()
            if response.status_code >= 500:
                raise MeshError("BACKEND_UNAVAILABLE", "Backend returned a server error.")
            raise MeshError("BACKEND_PROTOCOL", "Backend rejected the chat request.")

        try:
            async for chunk in self._consume(response, cancel):
                yield chunk
        finally:
            # Abort upstream on cancel/error/consumer-close within ≤ 1 s (§13.7).
            await response.aclose()

    async def _consume(
        self, response: httpx.Response, cancel: CancelToken
    ) -> AsyncIterator[ChatChunk]:
        """SSE body -> ChatChunks; §10.3 rule 4 budgets — first-token gap uses
        `first_token_timeout_s` (120 s default: a cold model load is silence,
        not death), gaps after the first parsed chunk use the 60 s idle
        budget; plus total cap, [DONE] terminator, cancel honoured even
        mid-read (§13.7: abort upstream ≤ 1 s)."""
        parser = SSEParser()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._total_stream_cap_s
        saw_done = False
        got_first_chunk = False
        raw = response.aiter_bytes()
        while not saw_done:
            if loop.time() > deadline:
                raise MeshError("DEADLINE_EXCEEDED", "Stream exceeded the total duration cap.")
            # Race the next chunk against the cancel token so a cancel during
            # a slow read aborts immediately (§13.7 ≤ 1 s, NFR-PERF-03 path).
            chunk_task: asyncio.Task[bytes] = asyncio.ensure_future(raw.__anext__())
            token_task = asyncio.ensure_future(cancel.wait())
            # §10.3 rule 4: two DIFFERENT silence budgets — before the first
            # parsed chunk the Backend may legitimately be loading the model
            # (cold load, up to `first_token_timeout_s`); afterwards a 60 s
            # gap means the stream is dead.
            gap_budget = (
                self._first_token_timeout_s if not got_first_chunk else self._idle_chunk_timeout_s
            )
            done, _ = await asyncio.wait(
                {chunk_task, token_task},
                timeout=gap_budget,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if chunk_task not in done:
                chunk_task.cancel()
                token_task.cancel()
                if token_task in done:
                    raise MeshError("CANCELLED", "Cancelled before completion.")
                raise MeshError("BACKEND_TIMEOUT", "No response from Backend in time.")
            token_task.cancel()
            if token_task in done and chunk_task.cancelled():
                raise MeshError("CANCELLED", "Cancelled before completion.")
            try:
                chunk = chunk_task.result()
            except StopAsyncIteration:
                break
            except httpx.HTTPError as exc:
                raise MeshError(
                    "BACKEND_UNAVAILABLE", "Backend transport failed mid-stream."
                ) from exc
            for event in parser.feed(chunk):
                if event.data == "[DONE]":
                    saw_done = True
                    break
                parsed = chunk_from_sse_data(event.data, self.id)
                if parsed is not None:
                    got_first_chunk = True
                    yield parsed
        if not saw_done:
            # §10.7: malformed/incomplete backend stream is terminal.
            raise MeshError("BACKEND_PROTOCOL", "Backend stream ended without a terminator.")

    # -- unsupported capabilities (§10.3 table; 501 via API-MODEL-02/03) ------

    async def load_model(self, backend_model_id: str) -> None:
        raise MeshError("UNSUPPORTED_CAPABILITY", "This Backend cannot load/unload models.")

    async def unload_model(self, backend_model_id: str) -> None:
        raise MeshError("UNSUPPORTED_CAPABILITY", "This Backend cannot load/unload models.")

    async def keep_warm(self, backend_model_id: str) -> None:
        raise MeshError("UNSUPPORTED_CAPABILITY", "This Backend cannot keep models warm.")

    # -- M7 embeddings (FR-MM-03; §6: OpenAI-compatible /v1/embeddings on
    #    LM Studio and Ollama alike) -------------------------------------------

    async def embed(self, texts: tuple[str, ...], backend_model_id: str) -> list[list[float]]:
        """`POST /v1/embeddings` (OpenAI shape). Defensive parse (§10.3 rule 2):
        a malformed answer is a protocol error, raw bodies never surfaced."""
        body = {"model": backend_model_id, "input": list(texts)}
        try:
            response = await self._client.post(
                self._url("/v1/embeddings"), json=body, headers=self._headers()
            )
        except httpx.HTTPError as exc:
            raise MeshError("BACKEND_UNAVAILABLE", "Embeddings transport failed.") from exc
        if response.status_code != 200:
            raise MeshError("BACKEND_UNAVAILABLE", "Embeddings request rejected by Backend.")
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            warn_schema_drift(self.id, "/v1/embeddings")
            raise MeshError("BACKEND_PROTOCOL", "Embeddings answer was malformed.") from exc
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list) or len(data) != len(texts):
            warn_schema_drift(self.id, "/v1/embeddings")
            raise MeshError("BACKEND_PROTOCOL", "Embeddings answer was malformed.")
        vectors: list[list[float]] = []
        for item in data:
            embedding = item.get("embedding") if isinstance(item, dict) else None
            if (
                not isinstance(embedding, list)
                or not embedding
                or not all(
                    isinstance(v, (int, float)) and not isinstance(v, bool) for v in embedding
                )
            ):
                warn_schema_drift(self.id, "/v1/embeddings")
                raise MeshError("BACKEND_PROTOCOL", "Embeddings answer was malformed.")
            vectors.append([float(v) for v in embedding])
        return vectors
