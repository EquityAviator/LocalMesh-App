"""Generate `docs/openapi/mesh-v1.json` from code (LM-ARCH-001 §21.3, ADR-015).

M0 skeleton: the generated spec contains exactly one path — `GET /mesh/v1/info`
(API-INFO-01 response schema, §13.2). Later milestones extend the FastAPI app;
CI regenerates and fails if the committed file differs (§21.3, NFR-MAINT-01).

The FastAPI app built here is a throwaway *schema source* only — it is never
served. Serving `/mesh/v1/info` is an M2 deliverable (§13.1).

Usage:
    python scripts/export_openapi.py            # (re)write docs/openapi/mesh-v1.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "agent" / "src"))

from fastapi import FastAPI  # noqa: E402

from localmesh_agent.api.v1.info import AgentApiInfo, AgentInfo  # noqa: E402

# §13.1: every Mesh API response carries `X-Mesh-Api-Version: 1`.
MESH_API_VERSION = "1"


def build_app() -> FastAPI:
    """Build the throwaway schema app registering the API-INFO-01 route (§13.2)."""
    app = FastAPI(
        title="LocalMesh Mesh API",
        description="Mesh API (`/mesh/v1`) of the LocalMesh Desktop Agent (LM-ARCH-001 §13).",
        version=MESH_API_VERSION,
    )

    @app.get(
        "/mesh/v1/info",
        response_model=AgentInfo,
        summary="Agent information (API-INFO-01)",
        tags=["info"],
    )
    def get_info() -> AgentInfo:  # pragma: no cover - schema source only (serving starts M2)
        # Placeholder body; never executed in M0. Values follow the §13.2 example shape.
        return AgentInfo(
            agent_id="ag_00000000-0000-0000-0000-000000000000",
            display_name="scaffold",
            api=AgentApiInfo(versions=["v1"], agent_version="0.1.0"),
            pairing_open=False,
        )

    return app


def build_openapi() -> dict[str, Any]:
    """Return the OpenAPI document for the current schema state."""
    return build_app().openapi()


def main() -> int:
    out = REPO_ROOT / "docs" / "openapi" / "mesh-v1.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    spec = build_openapi()
    out.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out.relative_to(REPO_ROOT)} ({len(spec.get('paths', {}))} path(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
