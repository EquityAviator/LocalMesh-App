"""API-MODEL-01 `GET /models` (§13.1, §13.5).

Returns the Capability Registry snapshot (normalized, provenance-carrying).
Auth: token scope `models:read` (M2); dev-insecure loopback in M1.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from localmesh_agent.api.deps import get_principal, require_scope

router = APIRouter()


@router.get("/mesh/v1/models")
async def list_models(request: Request) -> dict[str, Any]:
    principal = get_principal(request)
    require_scope(principal, "models:read")
    registry = request.app.state.registry
    snapshot = registry.snapshot()
    # §13.5 envelope keys exactly; X-Mesh-* headers come from middleware.
    return {
        "agent_id": snapshot["agent_id"],
        "generated_at": snapshot["generated_at"],
        "backends": snapshot["backends"],
        "models": snapshot["models"],
    }
