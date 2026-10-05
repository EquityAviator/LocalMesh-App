"""MeshError -> JSON envelope (§13.4) (§10.1).

All non-2xx responses use the §13.4 envelope:
`{"error": {"code", "message", "retryable", "request_id", "details"}}`.
`message` is human-readable and never contains Content or raw backend bodies.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from localmesh_agent.core.errors import MeshError


def error_envelope(request: Request, error: MeshError) -> dict[str, dict[str, Any]]:
    """Build the §13.4 envelope body for a MeshError."""
    return {
        "error": {
            "code": error.code,
            "message": error.message,
            "retryable": error.retryable,
            "request_id": getattr(request.state, "mesh_request_id", None),
            "details": error.details or {},
        }
    }


async def mesh_error_handler(request: Request, error: MeshError) -> JSONResponse:
    """FastAPI exception handler for every MeshError (registered in app.py)."""
    status = error.http_status
    if status == 0:  # CANCELLED is SSE-only; never an HTTP response (Appendix D)
        status = 500
    response = JSONResponse(status_code=status, content=error_envelope(request, error))
    if error.code == "QUEUE_FULL":
        retry_after = (error.details or {}).get("retry_after_s", 5.0)
        response.headers["Retry-After"] = str(max(1, int(round(float(retry_after)))))
    return response
