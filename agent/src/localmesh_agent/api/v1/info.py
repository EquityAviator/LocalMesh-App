"""API-INFO-01 `GET /info` response schema (LM-ARCH-001 §13.2).

M0: schema only. This module is consumed by `scripts/export_openapi.py` to
generate the committed OpenAPI skeleton (`docs/openapi/mesh-v1.json`) per
§21.3 / ADR-015 / NFR-MAINT-01. The route itself is served from M2 (§13.1);
do NOT wire it into a listener before its milestone (§22.1 scope fence).

Contract (§13.2, verbatim shape):

    { "agent_id": "ag_0192f0c1-....", "display_name": "Gaming PC",
      "api": { "versions": ["v1"], "agent_version": "0.1.0" },
      "pairing_open": false }

No OS, no model info, no IPs (limits pre-auth disclosure).
"""

from pydantic import BaseModel, Field


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
