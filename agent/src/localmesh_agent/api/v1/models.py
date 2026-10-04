"""API-MODEL-01/02/03 (§13.1, §13.2, §13.5).

`GET /models` returns the Capability Registry snapshot (normalized,
provenance-carrying); scope `models:read`.

`POST /models/load|unload` (WP-15 part 2, FR-MOD-04): body
`{ "mesh_model_id": "lmstudio::…" }` → 202 `{"state":"loading"}`;
501 `UNSUPPORTED_CAPABILITY` if the Backend adapter lacks the capability;
404 `MODEL_NOT_FOUND` for unknown ids. Scope `models:manage` (§13.2 API
table). Rate limits: §13.8 enumerates the limited endpoints exhaustively and
has no `/models/load|unload` row — none is added (same reading as /device).

Response-state note (QUESTION-106): the spec's single contract line shows the
LOAD response state `loading` (§13.5 vocabulary). For unload the Agent
returns the mirrored `unloaded` from the same closed vocabulary — recorded in
docs/OPEN_QUESTIONS.md pending owner confirmation.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from localmesh_agent.api.deps import get_principal, require_scope
from localmesh_agent.core.errors import MeshError
from localmesh_agent.core.policy import validate_model_ref_payload

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


async def _model_op(request: Request, *, operation: str) -> JSONResponse:
    """Shared body of API-MODEL-02/03 (§13.2): resolve → capability-gate → call.

    The Router raises MODEL_NOT_FOUND for unknown ids; the adapter raises
    UNSUPPORTED_CAPABILITY (§10.2 base contract) which maps to 501 via the
    Appendix D table. Backend transport/protocol failures surface as the
    adapter's MeshError codes (§10.3 rule 3 — never a raw backend body).
    """
    principal = get_principal(request)
    require_scope(principal, "models:manage")

    try:
        payload = await request.json()
    except Exception as exc:  # malformed JSON → §13.4 envelope, not a 500
        raise MeshError("INVALID_REQUEST", "Request body must be valid JSON.") from exc
    mesh_model_id = validate_model_ref_payload(payload)

    backend, backend_model_id, _entry = request.app.state.router.resolve(mesh_model_id)
    if operation == "load":
        await backend.load_model(backend_model_id)
        # §13.2 verbatim: 202 {"state":"loading"}.
        return JSONResponse(status_code=202, content={"state": "loading"})
    await backend.unload_model(backend_model_id)
    # QUESTION-106: §13.2 shows only the load state; `unloaded` is the mirror
    # from the closed §13.5 vocabulary.
    return JSONResponse(status_code=202, content={"state": "unloaded"})


@router.post("/mesh/v1/models/load")
async def load_model(request: Request) -> JSONResponse:
    """API-MODEL-02 (§13.2, FR-MOD-04): 202 `{"state":"loading"}`."""
    return await _model_op(request, operation="load")


@router.post("/mesh/v1/models/unload")
async def unload_model(request: Request) -> JSONResponse:
    """API-MODEL-03 (§13.2, FR-MOD-04): 202 `{"state":"unloaded"}` (see
    module docstring / QUESTION-106 for the response-state note)."""
    return await _model_op(request, operation="unload")
