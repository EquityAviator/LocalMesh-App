"""Model resolution (§10.4 Router).

v1: exact `mesh_model_id` resolution against the Capability Registry;
`"auto"` arrives at M8 (§22.1, ADR-013). mesh_model_id splits on the FIRST
'::' (§14.3): "<backend_id>::<backend_model_id>".
"""

from __future__ import annotations

from localmesh_agent.adapters.ports import InferenceBackend
from localmesh_agent.core.entities import ModelEntry
from localmesh_agent.core.errors import MeshError
from localmesh_agent.core.registry import CapabilityRegistry


class Router:
    """Resolves `model` -> `(backend, backend_model_id)`; rejects unknown
    ids with `MODEL_NOT_FOUND` (§10.4)."""

    def __init__(self, registry: CapabilityRegistry, backends: dict[str, InferenceBackend]) -> None:
        self._registry = registry
        self._backends = backends

    def resolve(self, mesh_model_id: str) -> tuple[InferenceBackend, str, ModelEntry]:
        """Return (backend, backend_model_id, registry entry).

        Raises MODEL_NOT_FOUND for unknown ids (Appendix D; §10.4).
        """
        entry = self._registry.get(mesh_model_id)
        if entry is None:
            raise MeshError("MODEL_NOT_FOUND", "Unknown mesh_model_id.")
        backend = self._backends.get(entry.backend_id)
        if backend is None:  # pragma: no cover — registry and adapters share ids
            raise MeshError("MODEL_NOT_FOUND", "Unknown mesh_model_id.")
        return backend, entry.backend_model_id, entry
