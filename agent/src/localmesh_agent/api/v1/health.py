"""API-HEALTH-01 `GET /health` (§13.1, §13.2).

Shape (§13.2): `{status: ok|degraded|down, uptime_s, backends: [{id, status}],
queue: {active, queued, max_queued}}`. Scope `models:read` (M2 tokens);
dev-insecure loopback in M1.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from localmesh_agent.api.deps import get_principal, require_scope

router = APIRouter()


def health_payload(request: Request) -> dict[str, Any]:
    """Build the §13.2 health shape (shared by the endpoint and tests)."""
    state = request.app.state
    registry = state.registry
    statuses: list[dict[str, str]] = []
    backends_json = registry.snapshot()["backends"]
    assert isinstance(backends_json, list)
    for backend in backends_json:
        assert isinstance(backend, dict)
        statuses.append({"id": str(backend["id"]), "status": str(backend["status"])})
    if statuses and all(s["status"] == "down" for s in statuses):
        overall = "down"
    elif any(s["status"] == "down" for s in statuses):
        overall = "degraded"  # [DESIGN] some enabled Backend unreachable
    else:
        overall = "ok"
    scheduler = state.scheduler
    return {
        "status": overall,
        "uptime_s": int(state.clock.now_monotonic() - state.started_mono),
        "backends": statuses,
        "queue": scheduler.queue_stats(),
    }


@router.get("/mesh/v1/health")
async def health(request: Request) -> dict[str, Any]:
    principal = get_principal(request)
    require_scope(principal, "models:read")
    return health_payload(request)
