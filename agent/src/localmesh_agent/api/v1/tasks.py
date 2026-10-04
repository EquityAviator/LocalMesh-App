"""API-TASK-xx `POST/GET/DELETE /tasks…` (M7, §13.9; §13.1 index).

Scope: `tasks` (§13.1: "models:manage and tasks are granted per Device by
the operator"). Wire shapes per §13.9:

- `POST /tasks` `{type, input, options}` → `202 {task_id, status:"queued"}`
- `GET  /tasks/{id}` → `{status, progress, result?, error?}`
- `GET  /tasks/{id}/events` → SSE (queued → running → terminal; close after)
- `DELETE /tasks/{id}` → cancel running / delete terminal row (fetch-ack)
- `PUT  /tasks/{id}/attachments/{name}` → 204; size-capped, encrypted at rest

Ownership: a Device sees only its own tasks — a foreign or unknown id is 404
(API-REQ-01 semantics; never disclose other devices' task ids).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from localmesh_agent.api.deps import get_principal, require_scope
from localmesh_agent.core.errors import MeshError
from localmesh_agent.core.policy import validate_task_payload
from localmesh_agent.security import task_crypto

router = APIRouter()

EVENTS_PING_INTERVAL_S = 15.0  # CI-18 spirit: never leave the phone silent


def _service(request: Request) -> Any:
    service = request.app.state.tasks
    if service is None:  # pragma: no cover — wiring always provides it
        raise MeshError("INVALID_REQUEST", "Tasks are not available on this agent.")
    return service


@router.post("/mesh/v1/tasks")
async def create_task(request: Request) -> object:
    principal = get_principal(request)
    require_scope(principal, "tasks")
    try:
        payload = await request.json()
    except Exception as exc:
        raise MeshError("INVALID_REQUEST", "Request body must be valid JSON.") from exc
    task_type, payload_input, options = validate_task_payload(payload)
    service = _service(request)
    created = await service.create_task(
        device_id=principal.device_id,
        task_type=task_type,
        payload_input=payload_input,
        options=options,
    )
    return JSONResponse(status_code=202, content=created)


@router.get("/mesh/v1/tasks/{task_id}")
async def get_task(task_id: str, request: Request) -> object:
    principal = get_principal(request)
    require_scope(principal, "tasks")
    return _service(request).task_view(task_id, principal.device_id)


@router.get("/mesh/v1/tasks/{task_id}/events")
async def task_events(task_id: str, request: Request) -> object:
    principal = get_principal(request)
    require_scope(principal, "tasks")
    service = _service(request)
    # Ownership gate BEFORE subscribing (404 for foreign/unknown ids).
    service.task_view(task_id, principal.device_id)
    queue = service.subscribe(task_id)

    async def stream() -> asyncio.StreamIterator[str] | Any:
        try:
            # Snapshot the current status first (a task may already be terminal).
            view = service.task_view(task_id, principal.device_id)
            yield _event(
                "task",
                {
                    "task_id": task_id,
                    "status": view["status"],
                    "progress": view["progress"],
                },
            )
            if view["status"] in ("succeeded", "failed", "cancelled"):
                yield "data: [DONE]\n\n"
                return
            while True:
                if await request.is_disconnected():
                    return
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=EVENTS_PING_INTERVAL_S)
                except TimeoutError:
                    yield ": ping\n\n"
                    continue
                if event.get("status") == "deleted":
                    # Fetch-ack delete closes the stream (nothing to report).
                    yield "data: [DONE]\n\n"
                    return
                yield _event(
                    "task",
                    {"task_id": task_id, **event},
                )
                if event.get("status") in ("succeeded", "failed", "cancelled"):
                    yield "data: [DONE]\n\n"
                    return
        finally:
            service.unsubscribe(task_id, queue)

    headers = {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache, no-transform",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(
        stream(), status_code=200, headers=headers, media_type="text/event-stream"
    )


@router.delete("/mesh/v1/tasks/{task_id}")
async def delete_task(task_id: str, request: Request) -> object:
    principal = get_principal(request)
    require_scope(principal, "tasks")
    service = _service(request)
    service.task_view(task_id, principal.device_id)  # ownership + existence (404)
    service.delete_task(task_id, principal.device_id)
    return {"deleted": True}


@router.put("/mesh/v1/tasks/{task_id}/attachments/{name}")
async def put_attachment(name: str, task_id: str, request: Request) -> object:
    principal = get_principal(request)
    require_scope(principal, "tasks")
    _service(request)  # fail fast when tasks are not wired
    state = request.app.state
    row = state.store.get_task(task_id)
    if row is None or row["device_id"] != principal.device_id:
        raise MeshError("INVALID_REQUEST", "No such task.", status_override=404)
    if row["status"] in ("succeeded", "failed", "cancelled"):
        raise MeshError("INVALID_REQUEST", "Task already finished; attachments are closed.")
    if not name or len(name) > 255 or "/" in name or "\\" in name:
        raise MeshError("INVALID_REQUEST", "Attachment name must be a safe single path segment.")
    limit = state.settings.tasks.max_attachment_bytes
    declared = request.headers.get("Content-Length")
    if declared is not None and declared.isdigit() and int(declared) > limit:
        raise MeshError(
            "PAYLOAD_TOO_LARGE",
            "Attachment exceeds the configured size cap (§13.9).",
            details={"limit_bytes": limit},
        )
    body = await request.body()
    if len(body) > limit:
        raise MeshError(
            "PAYLOAD_TOO_LARGE",
            "Attachment exceeds the configured size cap (§13.9).",
            details={"limit_bytes": limit},
        )
    nonce, ciphertext = task_crypto.encrypt(state.tasks_key, body, aad=task_id.encode("utf-8"))
    state.store.put_task_file(
        task_id, name, len(body), ciphertext, nonce, int(state.clock.now_wall())
    )
    return Response(status_code=204)


def _event(name: str, data: dict[str, Any]) -> str:
    return f"event: {name}\ndata: {json.dumps(data, separators=(',', ':'), ensure_ascii=False)}\n\n"
