"""Generate `docs/openapi/mesh-v1.json` from code (LM-ARCH-001 §21.3, ADR-015).

Since WP-08 (M2) the exported spec mirrors the SERVED public API: the real
routers (`api/v1/*`) are included from a throwaway FastAPI app that is never
served or configured — handlers reference `request.app.state` at runtime
only, so no store/backends are needed to *describe* the contract.

CI regenerates this file and fails if the committed one differs
(§21.3, NFR-MAINT-01).

Usage:
    python scripts/export_openapi.py            # (re)write docs/openapi/mesh-v1.json

Interpreter note: the generated schema embeds pydantic/FastAPI version
artifacts; the committed spec must come from the LOCKFILE interpreter
(agent/.venv). Both OpenAPI scripts re-exec under `agent/.venv/bin/python`
when present (CI installs the lockfile into its own venv — unaffected).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "agent" / "src"))

_REEXEC_GUARD = "LOCALMESH_OPENAPI_SCRIPT_REEXEC"


def reexec_with_agent_venv() -> None:
    """Prefer the lockfile interpreter for reproducible schema generation.

    A system python with a different pydantic/fastapi generates a different
    ValidationError schema — round-9 QA false-failed the drift check that way
    (same failure class as the pytest_layer.sh interpreter bug, round 7)."""
    if os.environ.get(_REEXEC_GUARD) == "1":
        return
    venv_python = REPO_ROOT / "agent" / ".venv" / "bin" / "python"
    if not venv_python.is_file():
        return
    venv_dir = venv_python.parent.parent.resolve()
    if Path(sys.prefix).resolve() == venv_dir:
        return  # already running under the lockfile venv
    # NOTE: comparing resolved executables does NOT work — a venv python is a
    # symlink to the very same base interpreter as system python3.
    env = dict(os.environ, _REEXEC_GUARD="1")
    # sys.argv[0], NOT __file__: the shim lives in export_openapi.py but is
    # also imported by check_openapi_drift.py — __file__ would re-exec the
    # EXPORTER from the checker (round-9 QA caught exactly that).
    script = Path(sys.argv[0]).resolve()
    os.execve(str(venv_python), [str(venv_python), str(script)], env)


from fastapi import FastAPI  # noqa: E402

from localmesh_agent.api.v1 import (  # noqa: E402
    auth,
    chat,
    device,
    health,
    info,
    models,
    pair,
    requests,
)

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
    app.include_router(device.router)
    app.include_router(chat.router)
    app.include_router(requests.router)
    return app


def build_openapi() -> dict[str, Any]:
    """Return the OpenAPI document for the current schema state."""
    return build_app().openapi()


def main() -> int:
    reexec_with_agent_venv()
    out = REPO_ROOT / "docs" / "openapi" / "mesh-v1.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    spec = build_openapi()
    out.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out.relative_to(REPO_ROOT)} ({len(spec.get('paths', {}))} path(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
