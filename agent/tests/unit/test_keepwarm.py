"""WP-15 part 2 unit tests — §16.5 KeepWarmScheduler (FR-MOD-05).

Covers the policy exactly as specified: interval = min(backend_idle_unload/2,
240 s); pings only `keep_warm = true` override models whose Backend declares
the keep_warm cap (§10.3: Ollama yes, LM Studio n/a, generic no); the pass is
skipped entirely unless a Device was active in the last 60 min ("never keeps
models warm silently"); failing pings degrade to logs, never raise.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from localmesh_agent.adapters.ports import BackendCaps, Clock
from localmesh_agent.core.entities import ModelEntry, TypedValue
from localmesh_agent.core.errors import MeshError
from localmesh_agent.core.warm import (
    ACTIVE_WINDOW_S,
    DEFAULT_BACKEND_IDLE_UNLOAD_S,
    MAX_INTERVAL_S,
    KeepWarmScheduler,
)


class FakeClock(Clock):
    def __init__(self, now: int = 5_000_000) -> None:
        self.now = now

    def now_monotonic(self) -> float:  # pragma: no cover - not used here
        return float(self.now)

    def now_wall(self) -> int:
        return self.now


class StubBackend:
    """Records keep_warm pings; caps configurable per test."""

    def __init__(self, backend_id: str, caps_keep_warm: bool, fail: bool = False) -> None:
        self.id = backend_id
        self.kind = "stub"
        self.fail = fail
        self.pings: list[str] = []
        self.caps = BackendCaps(
            {
                "list_models": True,
                "stream_chat": True,
                "load_unload": False,
                "keep_warm": caps_keep_warm,
                "embeddings": False,
                "vision": False,
                "audio_in": False,
            }
        )

    async def keep_warm(self, backend_model_id: str) -> None:
        self.pings.append(backend_model_id)
        if self.fail:
            raise MeshError("BACKEND_UNAVAILABLE", "Backend transport failed.")


def make_entry(backend_id: str, backend_model_id: str) -> ModelEntry:
    return ModelEntry(
        mesh_model_id=f"{backend_id}::{backend_model_id}",
        backend_id=backend_id,
        backend_model_id=backend_model_id,
        display_name=None,
        state="unloaded",
        modalities_input=("text",),
        modalities_output=("text",),
        modalities_source="unknown",
        capabilities=(),
        capabilities_source="unknown",
        context_length=TypedValue(value=None, source="unknown"),
        quantization=TypedValue(value=None, source="unknown"),
        parameter_size=TypedValue(value=None, source="unknown"),
        size_bytes=None,
        vram_estimate_bytes=None,
        tags=(),
    )


class StubRegistry:
    """Minimal CapabilityRegistry stand-in (entries() only)."""

    def __init__(self, entries: list[ModelEntry]) -> None:
        self._entries = entries

    def entries(self) -> list[ModelEntry]:
        return list(self._entries)


@pytest.fixture()
def ollama_entry() -> ModelEntry:
    return make_entry("ollama", "qwen-fake:7b")


def make_scheduler(
    entries: list[ModelEntry],
    backends: dict[str, Any],
    keep_warm_ids: frozenset[str],
    active: bool = True,
    clock: FakeClock | None = None,
) -> KeepWarmScheduler:
    return KeepWarmScheduler(
        StubRegistry(entries),  # type: ignore[arg-type]
        backends,
        keep_warm_ids,
        lambda since: active,
        clock=clock or FakeClock(),
    )


# -- §16.5 interval formula ----------------------------------------------------


def test_interval_is_half_idle_capped_at_240() -> None:
    # Default idle 300 s → interval 150 s (< cap 240 s).
    scheduler = make_scheduler([], {}, frozenset())
    assert scheduler.interval_s == DEFAULT_BACKEND_IDLE_UNLOAD_S / 2 == 150.0


def test_interval_cap_kicks_in_for_long_idle() -> None:
    # A backend configured to idle-unload after 2 h → capped at 240 s (§16.5).
    scheduler = KeepWarmScheduler(
        StubRegistry([]),  # type: ignore[arg-type]
        {},
        frozenset(),
        lambda since: False,
        backend_idle_unload_s=7200,
    )
    assert scheduler.interval_s == MAX_INTERVAL_S == 240.0


# -- candidate selection -------------------------------------------------------


def test_pings_only_keep_warm_overrides_on_capable_backends(ollama_entry: ModelEntry) -> None:
    backend = StubBackend("ollama", caps_keep_warm=True)
    scheduler = make_scheduler(
        [ollama_entry], {"ollama": backend}, frozenset({ollama_entry.mesh_model_id})
    )
    candidates = scheduler.candidates()
    assert [(b.id, mid) for b, mid, _ in candidates] == [("ollama", "qwen-fake:7b")]


def test_skips_models_without_override(ollama_entry: ModelEntry) -> None:
    backend = StubBackend("ollama", caps_keep_warm=True)
    scheduler = make_scheduler([ollama_entry], {"ollama": backend}, frozenset())
    assert scheduler.candidates() == []


def test_skips_backends_without_keep_warm_cap() -> None:
    # LM Studio (§10.3: keep-warm n/a) and generic adapters are never pinged,
    # even if the user set keep_warm=true (that would be silent warming).
    entry = make_entry("lmstudio", "qwen")
    backend = StubBackend("lmstudio", caps_keep_warm=False)
    scheduler = make_scheduler([entry], {"lmstudio": backend}, frozenset({entry.mesh_model_id}))
    assert scheduler.candidates() == []


def test_skips_entries_without_backend() -> None:
    entry = make_entry("ghost", "m")
    scheduler = make_scheduler([entry], {}, frozenset({entry.mesh_model_id}))
    assert scheduler.candidates() == []


# -- the device-activity gate (§16.5 verbatim) ---------------------------------


def test_quiet_when_no_device_active_recently(ollama_entry: ModelEntry) -> None:
    backend = StubBackend("ollama", caps_keep_warm=True)
    seen: list[int] = []
    scheduler = KeepWarmScheduler(
        StubRegistry([ollama_entry]),  # type: ignore[arg-type]
        {"ollama": backend},
        frozenset({ollama_entry.mesh_model_id}),
        lambda since: seen.append(since) or False,
        clock=FakeClock(now=10_000),
    )
    issued = asyncio.run(scheduler.tick())
    assert issued == 0
    assert backend.pings == []
    # The gate asked about the §16.5 window boundary: now - 3600.
    assert seen == [10_000 - ACTIVE_WINDOW_S]


def test_active_device_within_window_triggers_ping(ollama_entry: ModelEntry) -> None:
    backend = StubBackend("ollama", caps_keep_warm=True)
    scheduler = KeepWarmScheduler(
        StubRegistry([ollama_entry]),  # type: ignore[arg-type]
        {"ollama": backend},
        frozenset({ollama_entry.mesh_model_id}),
        lambda since: since <= 10_000,  # active right "now"
        clock=FakeClock(now=10_000),
    )
    issued = asyncio.run(scheduler.tick())
    assert issued == 1
    assert backend.pings == ["qwen-fake:7b"]


def test_revoked_or_stale_devices_do_not_warm(ollama_entry: ModelEntry) -> None:
    # (app-side predicate filters revoked rows; the scheduler only sees the
    # boolean — this test pins that a False gate issues nothing.)
    backend = StubBackend("ollama", caps_keep_warm=True)
    scheduler = KeepWarmScheduler(
        StubRegistry([ollama_entry]),  # type: ignore[arg-type]
        {"ollama": backend},
        frozenset({ollama_entry.mesh_model_id}),
        lambda since: False,
        clock=FakeClock(),
    )
    assert asyncio.run(scheduler.tick()) == 0
    assert backend.pings == []


# -- failure degradation (best effort, CI-21 mitigation) -----------------------


def test_failing_ping_is_logged_and_pass_continues() -> None:
    down = StubBackend("ollama", caps_keep_warm=True, fail=True)
    healthy_id = make_entry("ollama2", "llama")
    healthy = StubBackend("ollama2", caps_keep_warm=True)
    entries = [make_entry("ollama", "qwen-fake:7b"), healthy_id]
    scheduler = make_scheduler(
        entries,
        {"ollama": down, "ollama2": healthy},
        frozenset({e.mesh_model_id for e in entries}),
    )
    issued = asyncio.run(scheduler.tick())
    assert issued == 1  # healthy backend still pinged
    assert healthy.pings == ["llama"]
    assert down.pings == ["qwen-fake:7b"]  # attempted, failed, logged


# -- lifecycle -----------------------------------------------------------------


def test_start_stop_cancels_cleanly(ollama_entry: ModelEntry) -> None:
    backend = StubBackend("ollama", caps_keep_warm=True)
    scheduler = make_scheduler(
        [ollama_entry], {"ollama": backend}, frozenset({ollama_entry.mesh_model_id})
    )

    async def lifecycle() -> None:
        scheduler.start()
        task = scheduler._task
        assert task is not None
        await asyncio.sleep(0.01)  # let the first tick run
        assert backend.pings == ["qwen-fake:7b"]  # [DESIGN] immediate first ping
        await scheduler.stop()
        assert task.done() or task.cancelled()

    asyncio.run(lifecycle())


def test_start_is_idempotent(ollama_entry: ModelEntry) -> None:
    scheduler = make_scheduler([ollama_entry], {}, frozenset())

    async def lifecycle() -> None:
        scheduler.start()
        first = scheduler._task
        scheduler.start()
        assert scheduler._task is first
        await scheduler.stop()

    asyncio.run(lifecycle())
