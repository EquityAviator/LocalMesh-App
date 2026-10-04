"""API-CHAT-01 `POST /chat/completions` (§13.2, §13.7) and API-REQ-01 support.

SSE wire format (§13.7, normative):
- named event `mesh.meta` first (request_id, model, backend, queued_ms,
  model_state);
- unnamed events with OpenAI `chat.completion.chunk` JSON, terminated by the
  literal `data: [DONE]`;
- keepalive comment `: ping` every 15 s while queued/loading — including the
  cold-load first-token wait (CI-21 mitigation "Pings + UI 'Loading model…'",
  CI-18: the phone treats ≥ 45 s of silence as a dead stream);
- the first-token TIME budget itself is the Backend adapter's §10.3 rule 4
  (`first_token_timeout_seconds`, default 120 s) — it surfaces here as a
  terminal `mesh.error` `BACKEND_TIMEOUT` (Appendix D 504), never as a raw
  generator abort (NFR-REL-02);
- named event `mesh.stats` last (before [DONE]);
- `mesh.error` is terminal (no [DONE] follows);
- Cancel (client close or API-REQ-01): abort upstream ≤ 1 s, free the slot,
  no further events.

The Agent is stateless for chat (ADR-011, FR-CHAT-04): nothing about Content
is persisted or logged (canary test TC-SEC-01).

M7 (FR-MM-01/02, §13.6): message content may be an OpenAI-style part list.
- image parts pass through to the Backend and require the resolved model to
  report the `vision` capability (§13.5) — else 501 UNSUPPORTED_CAPABILITY.
- audio parts (`input_audio`) are ACCEPTED BY SHAPE but there is no v1
  Backend contract for audio-in chat (§6: neither Backend documents it; S-13
  routes STT through the separate Whisper service) — chat with audio parts
  returns 501 UNSUPPORTED_CAPABILITY with a hint to use `POST /tasks`
  type=transcribe (FR-MM-02).
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from localmesh_agent.adapters.ports import ChatChunk, ChatMessage, ChatRequest
from localmesh_agent.api.deps import get_principal, require_scope
from localmesh_agent.core.entities import MeshStats
from localmesh_agent.core.errors import MeshError
from localmesh_agent.core.policy import validate_chat_payload

router = APIRouter()

PING_INTERVAL_S = 15.0  # §13.7 keepalive


def _sse_event(event: str, data: str) -> str:
    return f"event: {event}\ndata: {data}\n\n"


def _mesh_message(m: dict[str, Any]) -> ChatMessage:
    """Policy-validated message dict → frozen ChatMessage (M7 parts aware)."""
    content = m["content"]
    if isinstance(content, str):
        return ChatMessage(role=str(m["role"]), content=content)
    return ChatMessage(role=str(m["role"]), content=tuple(content))


def _capability_gate(messages: list[dict[str, Any]], entry: Any) -> None:
    """M7 gate (§13.5 closed vocabulary; §10.4 reject-don't-guess):
    image parts need `vision`; audio parts in chat are out of the v1 Backend
    contract (S-13: STT lives in the separate Whisper adapter)."""
    has_image = False
    has_audio = False
    for message in messages:
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "image_url":
                has_image = True
            elif part.get("type") == "input_audio":
                has_audio = True
    if has_image and "vision" not in entry.capabilities:
        raise MeshError(
            "UNSUPPORTED_CAPABILITY",
            "The selected model does not report vision (§13.5).",
            details={"required_capability": "vision"},
        )
    if has_audio:
        raise MeshError(
            "UNSUPPORTED_CAPABILITY",
            "Audio parts in chat are not supported in v1; use POST /tasks "
            "type=transcribe (FR-MM-02, S-13).",
            details={"required_capability": "speech_to_text", "hint": "POST /tasks"},
        )


def _openai_chunk_json(request_id: str, mesh_model_id: str, chunk: ChatChunk, created: int) -> str:
    """One §13.7 default event: OpenAI chat.completion.chunk JSON."""
    delta: dict[str, str] = {}
    if chunk.role is not None:
        delta["role"] = chunk.role
    if chunk.delta_content is not None:
        delta["content"] = chunk.delta_content
    payload = {
        "id": f"chatcmpl-{request_id}",
        "object": "chat.completion.chunk",
        "created": created,
        "model": mesh_model_id,
        "choices": [{"index": 0, "delta": delta, "finish_reason": chunk.finish_reason}],
    }
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


async def _stream(
    request: Request,
    payload: dict[str, Any],
    request_id: str,
    job: Any,
    backend: Any,
    backend_model_id: str,
    entry: Any,
) -> AsyncIterator[str]:
    state = request.app.state
    scheduler = state.scheduler
    store = state.store
    metrics = getattr(state, "metrics", None)  # §20.1 (optional in tests)
    mesh_model_id = entry.mesh_model_id
    started_mono = time.monotonic()
    store.append_audit(
        "chat_started",
        meta={"backend_id": backend.id, "mesh_model_id": mesh_model_id},
    )

    created = int(time.time())
    ttft_ms: int | None = None
    tokens_out = 0
    backend_completion_tokens: int | None = None
    finish_reason: str | None = None
    job_released = False
    cancelled = False
    # Pending first-chunk fetch (ping race below); cancelled on any exit so a
    # closed stream never leaks a task still pulling from the Backend.
    pending_next: asyncio.Task[ChatChunk] | None = None

    def release_job() -> None:
        nonlocal job_released
        if not job_released:
            job_released = True
            scheduler.release(job, duration_s=time.monotonic() - started_mono)

    try:
        # -- queued phase: pings every 15 s while waiting (§13.7) -------------
        acquire_task = asyncio.create_task(scheduler.await_running(job))
        try:
            while not acquire_task.done():
                done, _ = await asyncio.wait({acquire_task}, timeout=PING_INTERVAL_S)
                if acquire_task not in done:
                    yield ": ping\n\n"
            await acquire_task  # raises CANCELLED if cancelled while queued
        except BaseException:
            release_job()
            raise

        # -- mesh.meta (first named event, §13.7) ------------------------------
        meta = {
            "request_id": request_id,
            "model": mesh_model_id,
            "backend": backend.id,
            "queued_ms": job.queued_ms,
            "model_state": entry.state,
        }
        yield _sse_event("mesh.meta", json.dumps(meta, separators=(",", ":"), ensure_ascii=False))

        # -- generation: forward chunks, poll for client disconnect ------------
        upstream = backend.stream_chat(
            ChatRequest(
                model=mesh_model_id,
                backend_model_id=backend_model_id,
                messages=tuple(_mesh_message(m) for m in payload["messages"]),
                stream=True,
                temperature=payload.get("temperature"),
                top_p=payload.get("top_p"),
                max_tokens=payload.get("max_tokens"),
                stop=tuple(payload["stop"])
                if isinstance(payload.get("stop"), list)
                else (payload["stop"],)
                if isinstance(payload.get("stop"), str)
                else None,
                presence_penalty=payload.get("presence_penalty"),
                frequency_penalty=payload.get("frequency_penalty"),
                seed=payload.get("seed"),
            ),
            job.token,
        )
        first_chunk = True
        while True:
            if await request.is_disconnected():
                # Client closed: cancel upstream ≤ 1 s, no further events.
                job.token.cancel()
                cancelled = True
                break
            if job.token.cancelled:
                # Revoke-during-stream (§15.6 / FR-PAIR-06): the scheduler set
                # cancel_reason="device_revoked" — tell the phone best-effort,
                # then close. Uniform non-revoke cancels stay silent.
                if job.cancel_reason == "device_revoked":
                    release_job()
                    store.append_audit(
                        "chat_finished",
                        meta={
                            "backend_id": backend.id,
                            "mesh_model_id": mesh_model_id,
                            "status": "failed",
                        },
                    )
                    yield _sse_event(
                        "mesh.error",
                        json.dumps(
                            {
                                "error": {
                                    "code": "DEVICE_REVOKED",
                                    "message": "This device has been revoked.",
                                    "retryable": False,
                                    "request_id": request_id,
                                    "details": {},
                                }
                            },
                            separators=(",", ":"),
                            ensure_ascii=False,
                        ),
                    )
                    return
                cancelled = True
                break
            try:
                if first_chunk:
                    # §13.7 "Model loading … then pings until first token" /
                    # CI-21: race the first chunk against 15 s keepalives so a
                    # cold model load (mesh.meta model_state="loading") never
                    # looks dead to the phone's 45 s idle detector (CI-18).
                    # The first-token TIME budget is the adapter's (§10.3 rule
                    # 4, default 120 s): it raises MeshError("BACKEND_TIMEOUT")
                    # through the task — caught below as a terminal mesh.error.
                    # (A former hard `wait_for(…, 30)` here aborted the stream
                    # with an uncaught TimeoutError — no mesh.error, no pings,
                    # and 30 s ≠ the spec's 120 s cold-load budget.)
                    pending_next = asyncio.ensure_future(upstream.__anext__())
                    while True:
                        done, _ = await asyncio.wait({pending_next}, timeout=PING_INTERVAL_S)
                        if pending_next in done:
                            break
                        yield ": ping\n\n"
                    chunk = pending_next.result()
                    pending_next = None
                    first_chunk = False
                else:
                    chunk = await upstream.__anext__()
            except StopAsyncIteration:
                break
            except MeshError as error:
                if error.code == "CANCELLED":
                    # §15.6 / FR-PAIR-06: revoke-during-stream must surface
                    # DEVICE_REVOKED (best effort) whether the loop noticed the
                    # cancel between chunks (above) or the upstream abort
                    # surfaced here.
                    if job.cancel_reason == "device_revoked":
                        release_job()
                        store.append_audit(
                            "chat_finished",
                            meta={
                                "backend_id": backend.id,
                                "mesh_model_id": mesh_model_id,
                                "status": "failed",
                            },
                        )
                        yield _sse_event(
                            "mesh.error",
                            json.dumps(
                                {
                                    "error": {
                                        "code": "DEVICE_REVOKED",
                                        "message": "This device has been revoked.",
                                        "retryable": False,
                                        "request_id": request_id,
                                        "details": {},
                                    }
                                },
                                separators=(",", ":"),
                                ensure_ascii=False,
                            ),
                        )
                        return
                    cancelled = True
                    break
                release_job()
                yield _sse_event(
                    "mesh.error",
                    json.dumps(
                        {
                            "error": {
                                "code": error.code,
                                "message": error.message,
                                "retryable": error.retryable,
                                "request_id": request_id,
                                "details": error.details or {},
                            }
                        },
                        separators=(",", ":"),
                        ensure_ascii=False,
                    ),
                )
                store.append_audit(
                    "chat_finished",
                    meta={
                        "backend_id": backend.id,
                        "mesh_model_id": mesh_model_id,
                        "status": "failed",
                    },
                )
                if metrics is not None:
                    metrics.inc("requests_total", labels={"status": "error", "backend": backend.id})
                return
            if ttft_ms is None and chunk.delta_content is not None:
                ttft_ms = int((time.monotonic() - started_mono) * 1000)
            if chunk.usage_completion_tokens is not None:
                backend_completion_tokens = chunk.usage_completion_tokens
            if chunk.finish_reason is not None:
                finish_reason = chunk.finish_reason
            if chunk.delta_content is not None:
                tokens_out += 1
            yield f"data: {_openai_chunk_json(request_id, mesh_model_id, chunk, created)}\n\n"

        if cancelled:
            release_job()
            # §13.7 Cancel: abort upstream, free slot, NO further events.
            if metrics is not None:
                metrics.inc("requests_total", labels={"status": "cancelled", "backend": backend.id})
            store.append_audit(
                "chat_finished",
                meta={
                    "backend_id": backend.id,
                    "mesh_model_id": mesh_model_id,
                    "status": "cancelled",
                },
            )
            return

        # -- mesh.stats (last named event, before [DONE], §13.7) ---------------
        duration_ms = int((time.monotonic() - started_mono) * 1000)
        if backend_completion_tokens is not None:
            tokens_out = backend_completion_tokens
            token_source = "backend"
        else:
            token_source = "estimated"  # §13.7: estimate when usage absent
        stats = MeshStats(
            ttft_ms=ttft_ms if ttft_ms is not None else duration_ms,
            tokens_out=tokens_out,
            tokens_per_sec=round(tokens_out / (duration_ms / 1000), 2) if duration_ms > 0 else 0.0,
            duration_ms=duration_ms,
            finish_reason=finish_reason,
            token_count_source=token_source,
        )
        yield _sse_event(
            "mesh.stats",
            json.dumps(stats.to_api_json(), separators=(",", ":"), ensure_ascii=False),
        )
        yield "data: [DONE]\n\n"
        release_job()
        if metrics is not None:
            # §20.1 push families at the terminal event (Metadata only).
            metrics.inc("requests_total", labels={"status": "ok", "backend": backend.id})
            metrics.observe("ttft_ms", float(stats.ttft_ms))
            if tokens_out > 0:
                metrics.inc("tokens_out_total", labels={"backend": backend.id}, value=tokens_out)
                metrics.set_gauge("tokens_per_sec", stats.tokens_per_sec)
        store.append_audit(
            "chat_finished",
            meta={
                "backend_id": backend.id,
                "mesh_model_id": mesh_model_id,
                "tokens_out": tokens_out,
                "duration_ms": duration_ms,
            },
        )
    finally:
        if pending_next is not None and not pending_next.done():
            pending_next.cancel()  # stop pulling from the Backend on exit
        job.token.cancel()  # abort upstream on any generator exit (§13.7)
        release_job()


@router.post("/mesh/v1/chat/completions")
async def chat_completions(request: Request) -> object:
    principal = get_principal(request)
    require_scope(principal, "chat")
    try:
        payload = await request.json()
    except Exception as exc:  # malformed JSON body
        raise MeshError("INVALID_REQUEST", "Request body must be valid JSON.") from exc
    payload = validate_chat_payload(payload)

    request_id = request.state.mesh_request_id  # set by middleware (§13.3)

    if payload.get("stream", True) is False:
        # §13.2: non-stream returns an OpenAI-shaped completion + x_mesh.stats
        # (for tests/tools; not used by the App UI).
        collected: list[str] = []
        finish_reason: str | None = None
        usage_tokens: int | None = None
        started = time.monotonic()
        backend, backend_model_id, entry = request.app.state.router.resolve(str(payload["model"]))
        _capability_gate(payload["messages"], entry)
        job = request.app.state.scheduler.admit(
            request_id=request_id, device_id=principal.device_id, backend_id=backend.id
        )
        try:
            await request.app.state.scheduler.await_running(job)
            async for chunk in backend.stream_chat(
                ChatRequest(
                    model=entry.mesh_model_id,
                    backend_model_id=backend_model_id,
                    messages=tuple(_mesh_message(m) for m in payload["messages"]),
                    stream=False,
                    temperature=payload.get("temperature"),
                    max_tokens=payload.get("max_tokens"),
                ),
                job.token,
            ):
                if chunk.delta_content is not None:
                    collected.append(chunk.delta_content)
                if chunk.finish_reason is not None:
                    finish_reason = chunk.finish_reason
                if chunk.usage_completion_tokens is not None:
                    usage_tokens = chunk.usage_completion_tokens
        finally:
            job.token.cancel()
            request.app.state.scheduler.release(job, duration_s=time.monotonic() - started)
        duration_ms = int((time.monotonic() - started) * 1000)
        completion_tokens = (
            usage_tokens if usage_tokens is not None else max(1, len("".join(collected)) // 4)
        )
        metrics = getattr(request.app.state, "metrics", None)
        if metrics is not None:
            # §20.1 — the non-stream shape is a full generation too.
            metrics.inc("requests_total", labels={"status": "ok", "backend": backend.id})
            metrics.observe("ttft_ms", float(duration_ms))  # single-shot: TTFT == duration
            if completion_tokens > 0:
                metrics.inc(
                    "tokens_out_total", labels={"backend": backend.id}, value=completion_tokens
                )
        completion = {
            "id": f"chatcmpl-{request_id}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": entry.mesh_model_id,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "".join(collected)},
                    "finish_reason": finish_reason,
                }
            ],
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": completion_tokens,
                "total_tokens": completion_tokens,
            },
            "x_mesh": {
                "stats": {
                    "ttft_ms": duration_ms,
                    "tokens_out": completion_tokens,
                    "tokens_per_sec": 0.0,
                    "duration_ms": duration_ms,
                    "finish_reason": finish_reason,
                    "token_count_source": "backend" if usage_tokens is not None else "estimated",
                }
            },
        }
        return completion

    # Resolve + admit BEFORE the response starts so error envelopes (404
    # MODEL_NOT_FOUND, 429 QUEUE_FULL, §13.4) go out with their HTTP status.
    backend, backend_model_id, entry = request.app.state.router.resolve(str(payload["model"]))
    _capability_gate(payload["messages"], entry)
    job = request.app.state.scheduler.admit(
        request_id=request_id, device_id=principal.device_id, backend_id=backend.id
    )

    headers = {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache, no-transform",  # §13.3
        "X-Accel-Buffering": "no",  # §13.3: never buffer the stream
        "X-Mesh-Request-Id": request_id,  # §13.3: before the first byte
    }
    return StreamingResponse(
        _stream(request, payload, request_id, job, backend, backend_model_id, entry),
        status_code=200,
        headers=headers,
        media_type="text/event-stream",
    )
