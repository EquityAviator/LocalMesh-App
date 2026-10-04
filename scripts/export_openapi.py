"""Generate `docs/openapi/mesh-v1.json` from code (LM-ARCH-001 §21.3, ADR-015).

Since WP-08 (M2) the exported spec mirrors the SERVED public API: the real
routers (`api/v1/*`) are included from a throwaway FastAPI app that is never
served or configured — handlers reference `request.app.state` at runtime
only, so no store/backends are needed to *describe* the contract.

CI regenerates this file and fails if the committed one differs
(§21.3, NFR-MAINT-01).

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

from localmesh_agent.api.v1 import auth, chat, health, info, pair, models, requests  # noqa: E402

# §13.1: every Mesh API response carries `X-Mesh-Api-Version: 1`.
MESH_API_VERSION = "1"


def build_app() -> FastAPI:
    """Build the throwaway schema app with every served public route."""
    app = FastAPI(
        title="LocalMesh Mesh API",
        description="Mesh API (`/mesh/v1`) of the LocalMesh Desktop Agent (LM-ARCH-001 §13).",
        version=MESH_API_VERSION,
    )
    # The real routers — the contract follows the served code (§21.3).
    app.include_router(info.router)
    app.include_router(pair.router)
    app.include_router(auth.router)
    app.include_router(models.router)
    app.include_router(health.router)
    app.include_router(chat.router)
    app.include_router(requests.router)
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
