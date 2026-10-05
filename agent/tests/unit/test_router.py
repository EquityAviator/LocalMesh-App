"""WP-06 unit tests — Router (§10.4; §14.3 split on the FIRST '::')."""

from collections.abc import AsyncIterator

from localmesh_agent.adapters.ports import (
    BackendCaps,
    BackendModel,
    BackendStatus,
    CancelToken,
    ChatChunk,
    ChatRequest,
)
from localmesh_agent.core.errors import MeshError
from localmesh_agent.core.registry import CapabilityRegistry
from localmesh_agent.core.router import Router
from localmesh_agent.store.sqlite import Store


class _StubBackend:
    kind = "stub"

    def __init__(self, backend_id: str) -> None:
        self.id = backend_id
        self.caps: BackendCaps = {
            "list_models": True,
            "stream_chat": True,
            "load_unload": False,
            "keep_warm": False,
            "embeddings": False,
            "vision": False,
            "audio_in": False,
        }

    async def probe(self) -> BackendStatus:
        return BackendStatus(backend_id=self.id, status="up")

    async def list_models(self) -> list[BackendModel]:
        return [BackendModel(backend_model_id="my::model")]  # '::' inside model id!

    def stream_chat(  # pragma: no cover
        self, req: ChatRequest, cancel: CancelToken
    ) -> AsyncIterator[ChatChunk]:
        raise NotImplementedError

    async def load_model(self, backend_model_id: str) -> None:  # pragma: no cover
        raise NotImplementedError

    async def unload_model(self, backend_model_id: str) -> None:  # pragma: no cover
        raise NotImplementedError

    async def keep_warm(self, backend_model_id: str) -> None:  # pragma: no cover
        raise NotImplementedError


async def test_resolve_known_model(store: Store) -> None:
    backend = _StubBackend("lmstudio")
    registry = CapabilityRegistry("ag_t", [backend], store)
    await registry.refresh()
    router = Router(registry, {backend.id: backend})  # type: ignore[dict-item]
    resolved, backend_model_id, entry = router.resolve("lmstudio::my::model")
    assert resolved is backend
    # §14.3: split on the FIRST '::' — the model id keeps the second '::'.
    assert backend_model_id == "my::model"
    assert entry.mesh_model_id == "lmstudio::my::model"


async def test_resolve_unknown_rejected(store: Store) -> None:
    backend = _StubBackend("lmstudio")
    registry = CapabilityRegistry("ag_t", [backend], store)
    await registry.refresh()
    router = Router(registry, {backend.id: backend})  # type: ignore[dict-item]
    try:
        router.resolve("lmstudio::nope")
    except MeshError as error:
        assert error.code == "MODEL_NOT_FOUND"
        assert error.http_status == 404
    else:  # pragma: no cover
        raise AssertionError("expected MODEL_NOT_FOUND")
