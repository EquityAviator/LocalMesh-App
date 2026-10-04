"""API-INFO-01 `GET /mesh/v1/info` (LM-ARCH-001 §13.2).

WP-01 built the response schema (consumed by `scripts/export_openapi.py`);
WP-08 (M2, §13.1) serves the route — the pairing flow (ADR-012 probe:
"TLS pin check + GET /info + GET /health") and the `pairing_open` field
(FR-PAIR-01) require it.

Contract (§13.2, verbatim shape):

    { "agent_id": "ag_0192f0c1-....", "display_name": "Gaming PC",
      "api": { "versions": ["v1"], "agent_version": "0.1.0" },
      "pairing_open": false }

No OS, no model info, no IPs (limits pre-auth disclosure). Unauthenticated
by design (§17.7); rate-limited 30/min per source IP (§13.8).
"""

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from localmesh_agent.core.errors import MeshError

router = APIRouter()

INFO_LIMIT_PER_MIN = 30  # §13.8: GET /info 30/min per source IP


class AgentApiInfo(BaseModel):
    """`api` block of the API-INFO-01 response (§13.2)."""

    versions: list[str] = Field(description="Mesh API versions served, e.g. ['v1'] (§13.10).")
    agent_version: str = Field(description="Semantic Agent version (§13.2, NFR-COMP-02).")


class AgentInfo(BaseModel):
    """Body of `GET /mesh/v1/info` (API-INFO-01, §13.2).

    No OS, no model info, no IPs (limits pre-auth disclosure).
    """

    agent_id: str = Field(description="Stable Agent identifier (§13.2).")
    display_name: str = Field(description="Operator-set Agent display name (§13.2).")
    api: AgentApiInfo = Field(description="API version block (§13.2).")
    pairing_open: bool = Field(description="Whether a PairingSession is currently OPEN (§13.2).")


@router.get("/mesh/v1/info", tags=["info"], response_model=AgentInfo)
async def get_info(request: Request) -> AgentInfo:
    """Serve API-INFO-01 (§13.2) — the pre-auth discovery/probe endpoint."""
    limiter = request.app.state.limiter
    client_ip = request.client.host if request.client else "unknown"
    if not limiter.allow(f"info:{client_ip}", INFO_LIMIT_PER_MIN):
        raise MeshError("RATE_LIMITED", "Too many /info requests.")

    app_state = request.app.state
    identity = app_state.store.get_identity()
    display_name = (
        str(identity["display_name"]) if identity else app_state.settings.agent.display_name
    )
    return AgentInfo(
        agent_id=str(app_state.agent_id),
        display_name=display_name,
        api=AgentApiInfo(versions=["v1"], agent_version=str(app_state.agent_version)),
        pairing_open=bool(app_state.pairing.pairing_open()),
    )
