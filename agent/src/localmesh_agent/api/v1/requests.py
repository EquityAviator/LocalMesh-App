"""API-REQ-01 `DELETE /requests/{request_id}` (§13.2).

→ 202 `{"status": "cancelling"}`; 404 if unknown/finished; 403 if the request
belongs to another Device. Idempotent (§13.2 API-REQ-01).

Note on the envelope code for an unknown request: §13.2 fixes only the HTTP
status (404); Appendix D names no request-specific code, so `INVALID_REQUEST`
with `details.reason="unknown_or_finished"` is used [DESIGN — Appendix D gap].
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from localmesh_agent.api.deps import get_principal, require_scope
from localmesh_agent.core.errors import MeshError

router = APIRouter()


@router.delete("/mesh/v1/requests/{request_id}", status_code=202)  # §13.2: → 202
async def cancel_request(request: Request, request_id: str) -> dict[str, str]:
    principal = get_principal(request)
    require_scope(principal, "chat")
    scheduler = request.app.state.scheduler
    if scheduler.is_owner(request_id, principal.device_id):
        scheduler.cancel(request_id)  # idempotent by construction
        return {"status": "cancelling"}
    if scheduler.has(request_id):
        # §13.2 API-REQ-01: 403 when the request belongs to another Device.
        raise MeshError("FORBIDDEN_SCOPE", "Request belongs to another Device.")
    # Unknown or already finished: §13.2 API-REQ-01 fixes HTTP 404; Appendix D
    # has no request-specific code, so the envelope carries INVALID_REQUEST
    # with the §13.2 status via status_override [DESIGN — Appendix D gap].
    raise MeshError(
        "INVALID_REQUEST",
        "Unknown or finished request.",
        details={"reason": "unknown_or_finished"},
        status_override=404,
    )
