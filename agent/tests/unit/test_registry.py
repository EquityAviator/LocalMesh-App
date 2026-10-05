"""WP-05 unit tests — CapabilityRegistry merge (§16.3, §13.5, FR-MOD-02).

Key acceptance rule (FR-MOD-02 AC): "Schema test: never emits guessed values"
— unknown fields are null with provenance, and overrides are the only
non-backend source.
"""

import json
from collections.abc import AsyncIterator

from localmesh_agent.adapters.ports import (
    BackendCaps,
    BackendModel,
    BackendStatus,
    CancelToken,
    ChatChunk,
    ChatRequest,
    InferenceBackend,
    SystemClock,
)
from localmesh_agent.core.entities import ModelEntry
from localmesh_agent.core.registry import CapabilityRegistry
from localmesh_agent.store.sqlite import Store


class FakeBackend:
    """Minimal InferenceBackend double for registry tests."""

    kind = "fake"

    def __init__(self, backend_id: str, models: list[BackendModel], up: bool = True) -> None:
        self.id = backend_id
        self._models = models
        self._up = up
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
        return BackendStatus(backend_id=self.id, status="up" if self._up else "down")

    async def list_models(self) -> list[BackendModel]:
        return self._models

    def stream_chat(  # pragma: no cover - not exercised here
        self, req: ChatRequest, cancel: CancelToken
    ) -> AsyncIterator[ChatChunk]:
        raise NotImplementedError

    async def load_model(self, backend_model_id: str) -> None:  # pragma: no cover
        raise NotImplementedError

    async def unload_model(self, backend_model_id: str) -> None:  # pragma: no cover
        raise NotImplementedError

    async def keep_warm(self, backend_model_id: str) -> None:  # pragma: no cover
        raise NotImplementedError


def make_registry(
    store: Store,
    backends: list[InferenceBackend],
    overrides: list[dict[str, object]] | None = None,
) -> CapabilityRegistry:
    from localmesh_agent.config import ModelOverrideConfig

    override_models = [ModelOverrideConfig(**o) for o in (overrides or [])]
    return CapabilityRegistry(
        "ag_test",
        backends,
        store,
        clock=SystemClock(),
        overrides=override_models,  # type: ignore[arg-type]
    )


async def test_never_emits_guessed_values(store: Store) -> None:
    """FR-MOD-02: only backend-reported fields are set; others null/unknown."""
    backend = FakeBackend(
        "lmstudio", [BackendModel(backend_model_id="model-a", context_length=4096)]
    )
    registry = make_registry(store, [backend])
    await registry.refresh()
    entry = registry.get("lmstudio::model-a")
    assert entry is not None
    payload = entry.to_api_json()
    assert payload["context_length"] == {"value": 4096, "source": "backend"}
    assert payload["quantization"] == {"value": None, "source": "unknown"}
    assert payload["parameter_size"] == {"value": None, "source": "unknown"}
    assert payload["capabilities"] == {"values": [], "source": "unknown"}
    assert payload["modalities"] == {"input": [], "output": [], "source": "unknown"}
    assert payload["display_name"] is None


async def test_sort_and_mesh_model_id(store: Store) -> None:
    """Sort by (backend_id, display_name); mesh_model_id = '<bid>::<mid>'."""
    backends = [
        FakeBackend("ollama", [BackendModel(backend_model_id="zeta")]),
        FakeBackend(
            "lmstudio",
            [BackendModel(backend_model_id="b2"), BackendModel(backend_model_id="b1")],
        ),
    ]
    registry = make_registry(store, backends)
    await registry.refresh()
    ids = [e.mesh_model_id for e in registry.entries()]
    assert ids == ["lmstudio::b1", "lmstudio::b2", "ollama::zeta"]


async def test_backend_down_demotes_previous_to_unknown(store: Store) -> None:
    """§16.3: down backend -> previous entries kept with state='unknown'."""
    backend = FakeBackend("lmstudio", [BackendModel(backend_model_id="m")])
    registry = make_registry(store, [backend])
    await registry.refresh()
    assert registry.get("lmstudio::m") is not None
    assert registry.get("lmstudio::m").state == "unknown"  # type: ignore[union-attr]

    backend._up = False
    await registry.refresh()
    entry = registry.get("lmstudio::m")
    assert entry is not None and entry.state == "unknown"
    snapshot = registry.snapshot()
    assert snapshot["backends"][0]["status"] == "down"  # type: ignore[index]


async def test_user_override_sets_capabilities(store: Store) -> None:
    """Appendix E override: capabilities source flips to 'user' (§13.5)."""
    backend = FakeBackend("ollama", [BackendModel(backend_model_id="example")])
    registry = make_registry(
        store,
        [backend],
        overrides=[{"mesh_model_id": "ollama::example", "capabilities": ["chat", "vision"]}],
    )
    await registry.refresh()
    payload = registry.get("ollama::example").to_api_json()  # type: ignore[union-attr]
    assert payload["capabilities"] == {"values": ["chat", "vision"], "source": "user"}


async def test_snapshot_cached_in_store(store: Store) -> None:
    """§16.3: 'store snapshot in model_cache' — cache matches the snapshot."""
    backend = FakeBackend("lmstudio", [BackendModel(backend_model_id="m")])
    registry = make_registry(store, [backend])
    await registry.refresh()
    cache = store.get_model_cache()
    assert "lmstudio::m" in cache
    cached_entry = json.loads(cache["lmstudio::m"]["entry_json"])
    assert cached_entry["mesh_model_id"] == "lmstudio::m"


async def test_snapshot_envelope_shape(store: Store) -> None:
    """§13.5 envelope: agent_id, generated_at (ISO-8601 Z), backends, models."""
    from localmesh_agent.adapters.ports import BackendStatus

    backend = FakeBackend("lmstudio", [BackendModel(backend_model_id="m")])
    registry = make_registry(store, [backend])
    registry._backend_status["lmstudio"] = BackendStatus("lmstudio", "up")  # noqa: SLF001
    await registry.refresh()
    snapshot = registry.snapshot()
    assert set(snapshot) == {"agent_id", "generated_at", "backends", "models"}
    assert snapshot["agent_id"] == "ag_test"
    assert str(snapshot["generated_at"]).endswith("Z")
    model_json = snapshot["models"][0]  # type: ignore[index]
    assert set(model_json) == set(
        ModelEntry.from_backend("x", BackendModel(backend_model_id="y")).to_api_json()
    )  # type: ignore[arg-type]
