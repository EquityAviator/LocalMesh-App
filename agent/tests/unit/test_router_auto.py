"""M8 unit tests — §16.6 auto-routing score (FR-RTE-01/02, verbatim)."""

from __future__ import annotations

import math
from typing import Any

import pytest

from localmesh_agent.core.errors import MeshError
from localmesh_agent.core.registry import CapabilityRegistry
from localmesh_agent.core.router import (
    DEFAULT_QUALITY_RANK,
    Router,
    est_tokens,
)
from localmesh_agent.store.sqlite import Store


class FakeBackend:
    def __init__(self, backend_id: str) -> None:
        self.id = backend_id


def make_entry(
    mesh_model_id: str,
    *,
    state: str = "unloaded",
    modalities: tuple[str, ...] = ("text",),
    capabilities: tuple[str, ...] = ("chat",),
    context_length: int | None = 4096,
) -> Any:
    from localmesh_agent.adapters.ports import TypedValue
    from localmesh_agent.core.entities import ModelEntry

    backend_id, backend_model_id = mesh_model_id.split("::", 1)
    return ModelEntry(
        mesh_model_id=mesh_model_id,
        backend_id=backend_id,
        backend_model_id=backend_model_id,
        display_name=None,
        state=state,
        modalities_input=modalities,
        modalities_output=("text",),
        modalities_source="backend",
        capabilities=capabilities,
        capabilities_source="backend",
        context_length=TypedValue(value=context_length, source="backend"),
        quantization=TypedValue(value=None, source="unknown"),
        parameter_size=TypedValue(value=None, source="unknown"),
        size_bytes=None,
        vram_estimate_bytes=None,
    )


class FakeRegistry(CapabilityRegistry):
    """Registry stub with injected entries/status (no backends needed)."""

    def __init__(self, entries: list[Any], statuses: dict[str, str]) -> None:
        self._injected = {entry.mesh_model_id: entry for entry in entries}
        self._statuses = {k: ("up" if v == "up" else "down") for k, v in statuses.items()}

    def entries(self) -> list[Any]:
        return list(self._injected.values())

    def get(self, mesh_model_id: str) -> Any:
        return self._injected.get(mesh_model_id)

    def backend_status(self, backend_id: str) -> Any:
        from localmesh_agent.adapters.ports import BackendStatus

        state = self._statuses.get(backend_id)
        if state is None:
            return None
        return BackendStatus(backend_id=backend_id, status=state)


def est_tokens_check() -> None:  # §16.6: ceil(chars/4), flagged estimate
    messages = [{"role": "user", "content": "x" * 40}]
    assert est_tokens(messages, 10) == math.ceil(40 / 4) + 10 == 20


def test_no_candidate_satisfying_vision_is_model_not_found() -> None:
    registry = FakeRegistry([make_entry("a::m")], {"a": "up"})
    router = Router(registry, {"a": FakeBackend("a")})
    with pytest.raises(MeshError) as excinfo:
        router.resolve_auto(
            messages=[{"role": "user", "content": "hi"}],
            required_modalities=frozenset({"image"}),
            required_capabilities=frozenset({"vision"}),
        )
    assert excinfo.value.code == "MODEL_NOT_FOUND"


def test_unknown_state_with_down_backend_excluded() -> None:
    entry_unknown = make_entry("a::m", state="unknown")
    registry = FakeRegistry([entry_unknown], {"a": "down"})
    router = Router(registry, {"a": FakeBackend("a")})
    with pytest.raises(MeshError):
        router.resolve_auto(messages=[{"role": "user", "content": "hi"}])


def test_unknown_state_with_up_backend_is_candidate() -> None:
    entry_unknown = make_entry("a::m", state="unknown")
    registry = FakeRegistry([entry_unknown], {"a": "up"})
    router = Router(registry, {"a": FakeBackend("a")})
    backend, _mid, _entry, decision = router.resolve_auto(
        messages=[{"role": "user", "content": "hi"}]
    )
    assert backend.id == "a"
    assert decision.mode == "auto"


def test_capability_unknown_never_matches() -> None:
    # Capabilities empty (unknown source) — a vision requirement excludes it.
    entry = make_entry("a::m", capabilities=())
    registry = FakeRegistry([entry], {"a": "up"})
    router = Router(registry, {"a": FakeBackend("a")})
    with pytest.raises(MeshError):
        router.resolve_auto(
            messages=[{"role": "user", "content": "hi"}],
            required_capabilities=frozenset({"vision"}),
        )


def test_warm_beats_cold_at_equal_quality() -> None:
    warm = make_entry("a::warm", state="loaded")
    cold = make_entry("b::cold", state="unloaded")
    registry = FakeRegistry([warm, cold], {"a": "up", "b": "up"})
    router = Router(registry, {"a": FakeBackend("a"), "b": FakeBackend("b")})
    _backend, _mid, entry, decision = router.resolve_auto(
        messages=[{"role": "user", "content": "hi"}]
    )
    assert entry.mesh_model_id == "a::warm"
    candidates = {c.mesh_model_id: c for c in decision.candidates}
    assert candidates["a::warm"].score > candidates["b::cold"].score
    assert candidates["a::warm"].warm == 1.0
    assert candidates["b::cold"].warm == 0.0


def test_quality_rank_override_flips_the_winner() -> None:
    base = make_entry("a::base", state="loaded")
    other = make_entry("b::other", state="unloaded")
    registry = FakeRegistry([base, other], {"a": "up", "b": "up"})
    # warm=0.25 vs quality difference: quality 1 vs 5 → 0.4*(1/5)=0.08 vs 0.4
    router = Router(
        registry,
        {"a": FakeBackend("a"), "b": FakeBackend("b")},
        quality_ranks={"a::base": 1, "b::other": 5},
    )
    _backend, _mid, entry, _decision = router.resolve_auto(
        messages=[{"role": "user", "content": "hi"}]
    )
    assert entry.mesh_model_id == "b::other"


def test_speed_norm_null_defaults_to_half() -> None:
    entry = make_entry("a::m", state="unloaded")
    registry = FakeRegistry([entry], {"a": "up"})
    router = Router(registry, {"a": FakeBackend("a")}, speed_fn=lambda _m: None)
    _backend, _mid, _entry, decision = router.resolve_auto(
        messages=[{"role": "user", "content": "hi"}]
    )
    assert decision.candidates[0].speed_norm == pytest.approx(0.5)


def test_context_too_small_excluded_unknown_half() -> None:
    tiny = make_entry("a::tiny", context_length=4)  # est_tokens > 4
    unknown_ctx = make_entry("b::unknown", context_length=None)
    registry = FakeRegistry([tiny, unknown_ctx], {"a": "up", "b": "up"})
    router = Router(registry, {"a": FakeBackend("a"), "b": FakeBackend("b")})
    _backend, _mid, entry, decision = router.resolve_auto(
        messages=[{"role": "user", "content": "x" * 100}]
    )
    assert entry.mesh_model_id == "b::unknown"
    assert decision.candidates[0].fit == 0.5  # §16.6: unknown context → fit 0.5


def test_tie_breaks_lexicographic() -> None:
    first = make_entry("a::m", state="unloaded")
    second = make_entry("b::m", state="unloaded")
    registry = FakeRegistry([first, second], {"a": "up", "b": "up"})
    router = Router(registry, {"a": FakeBackend("a"), "b": FakeBackend("b")})
    _backend, _mid, entry, _decision = router.resolve_auto(
        messages=[{"role": "user", "content": "hi"}]
    )
    assert entry.mesh_model_id == "a::m"  # lexicographic (§16.6)


def test_decision_meta_shape_is_metadata_only() -> None:
    entry = make_entry("a::m", state="loaded")
    registry = FakeRegistry([entry], {"a": "up"})
    router = Router(registry, {"a": FakeBackend("a")})
    _backend, _mid, _entry, decision = router.resolve_auto(
        messages=[{"role": "user", "content": "hi"}]
    )
    meta = decision.to_meta()
    assert meta["mode"] == "auto"
    assert meta["mesh_model_id"] == "a::m"
    assert meta["est_tokens"] == est_tokens([{"role": "user", "content": "hi"}], None)
    assert "reason" in meta and "candidates" in meta
    import json

    blob = json.dumps(meta)
    assert "hi" not in blob  # the prompt itself never lands in the meta


def test_default_quality_rank_is_three() -> None:
    assert DEFAULT_QUALITY_RANK == 3  # §16.6 verbatim


def test_pinned_routing_decision_is_reported(store: Store) -> None:
    # §22.1 M8 gate "Routing decisions explained in mesh.meta" also covers
    # pinned resolution (mode=pinned) — the API layer reports it.
    from localmesh_agent.core.router import RoutingDecision

    decision = RoutingDecision(
        mode="pinned", mesh_model_id="a::m", backend_id="a", reason="pinned by the request (§10.4)"
    )
    assert decision.to_meta()["mode"] == "pinned"
