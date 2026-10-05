"""Keep-warm policy (§16.5, FR-MOD-05) — core service.

LM-ARCH-001 §16.5 verbatim policy:

    Config per model: `keep_warm = true`. Agent issues a minimal
    backend-specific warm request every `interval = min(backend_idle_unload/2,
    240 s)` only while at least one Device was active in the last 60 min.
    Never keeps models warm silently otherwise. Backend-specific mechanics
    per §6.2/§10.3.

Design notes:

- **Mechanics live in the adapters** (§10.3): the scheduler only calls the
  §10.2 `InferenceBackend.keep_warm()` port. Ollama pings via a native
  `/api/chat` empty-messages call (§6.2: `keep_alive` on the /v1 path is
  `[UNVERIFIED]`); LM Studio keep-warm is n/a (`caps["keep_warm"] is False`,
  §10.3) and is therefore never pinged — its models are demand-loaded and
  unloaded by the Backend itself.
- **Config source**: `models.overrides[].keep_warm = true` (Appendix E — the
  ONLY way a model enters the warm set; default `false` per the Appendix E
  reference value). The scheduler receives the resolved id set; it does not
  import config types (§10.1 dependency rule).
- **Device-activity gate**: "at least one Device was active in the last
  60 min" — evaluated through an injectable predicate over the §14.1
  `devices.last_seen_at` column (wired from the Store in `app.py`). With no
  active device the tick is a no-op ("never keeps models warm silently").
- **Never raises**: a failing ping (backend down, transport error) is logged
  with allow-listed keys (§17.10) and the pass continues — keep-warm is an
  optimization, never a correctness path (CI-21 mitigation, not requirement).
- **Clock injectable** (§10.2) and the run loop is a plain asyncio task
  started after the registry warms (§10.6 order) and cancelled on shutdown.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping

from localmesh_agent.adapters.ports import Clock, InferenceBackend, SystemClock
from localmesh_agent.core.errors import MeshError
from localmesh_agent.core.registry import CapabilityRegistry
from localmesh_agent.observability.logging import get_logger

log = get_logger("warm")

# §6.2 [SRC]: Ollama default idle unload ≈ 5 min. The half-interval rule keeps
# the in-memory timer refreshed well before expiry. [DESIGN] constant, not an
# Appendix E key (the config table is closed; §1.5).
DEFAULT_BACKEND_IDLE_UNLOAD_S = 300
# §16.5 verbatim constants.
ACTIVE_WINDOW_S = 3600
MAX_INTERVAL_S = 240


class KeepWarmScheduler:
    """§16.5 warm-request loop over the §10.2 `keep_warm` port."""

    def __init__(
        self,
        registry: CapabilityRegistry,
        backends: Mapping[str, InferenceBackend],
        keep_warm_ids: frozenset[str],
        device_active_since: Callable[[int], bool],
        *,
        backend_idle_unload_s: int = DEFAULT_BACKEND_IDLE_UNLOAD_S,
        active_window_s: int = ACTIVE_WINDOW_S,
        max_interval_s: int = MAX_INTERVAL_S,
        clock: Clock | None = None,
    ) -> None:
        """`device_active_since(epoch_s)` answers "was any Device active at or
        after this wall-clock second" (§14.1 last_seen_at; wired in app.py)."""
        self._registry = registry
        self._backends = backends
        self._keep_warm_ids = keep_warm_ids
        self._device_active_since = device_active_since
        self._active_window_s = active_window_s
        self._clock = clock or SystemClock()
        # §16.5 verbatim: interval = min(backend_idle_unload/2, 240 s).
        self.interval_s = min(backend_idle_unload_s / 2, float(max_interval_s))
        self._task: asyncio.Task[None] | None = None

    def candidates(self) -> list[tuple[InferenceBackend, str, str]]:
        """(backend, backend_model_id, mesh_model_id) pings this policy allows.

        A model is warmable iff (a) the user configured `keep_warm = true` for
        it (Appendix E override) AND (b) its Backend adapter declares the
        `keep_warm` cap (§10.3 table: Ollama only). Everything else would be
        "keeping models warm silently" — refused (§16.5).
        """
        out: list[tuple[InferenceBackend, str, str]] = []
        for entry in self._registry.entries():
            if entry.mesh_model_id not in self._keep_warm_ids:
                continue
            backend = self._backends.get(entry.backend_id)
            if backend is None or not backend.caps["keep_warm"]:
                continue
            out.append((backend, entry.backend_model_id, entry.mesh_model_id))
        return out

    async def tick(self) -> int:
        """One warm pass; returns the number of pings issued (0 = quiet)."""
        now = self._clock.now_wall()
        if not self._device_active_since(now - self._active_window_s):
            return 0  # §16.5: never keep models warm silently
        issued = 0
        for backend, backend_model_id, mesh_model_id in self.candidates():
            try:
                await backend.keep_warm(backend_model_id)
                issued += 1
            except MeshError as exc:
                # Keep-warm is best effort (CI-21 mitigation): a down backend
                # degrades to a log line; the pass continues.
                log.warning(
                    "keep_warm_ping",
                    extra={
                        "component": "warm",
                        "backend_id": backend.id,
                        "mesh_model_id": mesh_model_id,
                        "status": "error",
                        "error_code": exc.code,
                    },
                )
                continue
            log.info(
                "keep_warm_ping",
                extra={
                    "component": "warm",
                    "backend_id": backend.id,
                    "mesh_model_id": mesh_model_id,
                    "status": "ok",
                },
            )
        return issued

    async def _run(self) -> None:
        # [DESIGN] warm immediately at startup (a freshly restarted Agent with
        # recently active devices should not serve a cold first token, CI-21),
        # then every §16.5 interval.
        while True:
            await self.tick()
            await asyncio.sleep(self.interval_s)

    def start(self) -> None:
        """Start the background loop (idempotent; app lifespan calls once)."""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="keep-warm")

    async def stop(self) -> None:
        """Cancel the loop and wait for it (§10.6 symmetric shutdown)."""
        task = self._task
        self._task = None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
