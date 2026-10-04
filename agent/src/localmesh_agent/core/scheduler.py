"""Admission control, queues, cancel tokens (§10.4, §16.4).

§16.4 algorithm (normative):
```
admit(req, device):
  if device.active >= per_device_limit: reject QUEUE_FULL
  slot = backend_semaphore(req.backend)
  if slot.available: start immediately (queued_ms=0)
  elif global_queue.size < max_queued: enqueue (FIFO), emit pings
  else reject QUEUE_FULL with Retry-After = est. from recent durations
cancel(request_id) or disconnect: abort upstream, release slot, drain next
cancel_by_device(device_id): cancel all (used on revoke)
```
Defaults: backend concurrency 1 unless configured (§16.4); Appendix E limits:
per_device_active=2, max_queued=8.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Literal

from localmesh_agent.adapters.ports import CancelToken, Clock, SystemClock
from localmesh_agent.core.errors import MeshError
from localmesh_agent.observability.logging import get_logger
from localmesh_agent.observability.metrics import MetricsRegistry

log = get_logger("scheduler")

DEFAULT_RETRY_AFTER_S = 5.0  # [DESIGN] floor while no duration history exists


@dataclass
class Job:
    """One admitted generation (SM-STREAM agent side: queued → running)."""

    request_id: str
    device_id: str
    backend_id: str
    token: CancelToken
    enqueued_at_mono: float
    state: Literal["queued", "running", "done", "cancelled"] = "queued"
    queued_ms: int = 0
    cancel_reason: str | None = None
    cancel_requested_mono: float | None = None  # §20.1 cancel_latency_ms start
    _slot: asyncio.Semaphore | None = field(default=None, repr=False)
    _holds_slot: bool = field(default=False, repr=False)

    @property
    def cancelled(self) -> bool:
        return self.token.cancelled


class Scheduler:
    """Per-Backend concurrency, global FIFO queue, cancel tokens (§16.4)."""

    def __init__(
        self,
        backend_concurrency: dict[str, int],
        *,
        per_device_active: int = 2,
        max_queued: int = 8,
        clock: Clock | None = None,
        metrics: MetricsRegistry | None = None,
    ) -> None:
        self._semaphores = {
            backend_id: asyncio.Semaphore(max(1, concurrency))
            for backend_id, concurrency in backend_concurrency.items()
        }
        self._concurrency = dict(backend_concurrency)
        self._per_device_active = max(1, per_device_active)
        self._max_queued = max(0, max_queued)
        self._clock = clock or SystemClock()
        self._jobs: dict[str, Job] = {}
        self._device_active: dict[str, int] = {}
        self._recent_durations: list[float] = []
        # §20.1 cancel_latency_ms (optional; app factory injects the shared
        # registry — core stays import-light and tests can omit it).
        self._metrics = metrics

    # -- admission (§16.4) ------------------------------------------------------

    def admit(self, *, request_id: str, device_id: str, backend_id: str) -> Job:
        """Validate admission; returns the Job (caller then `await_running`).

        Raises QUEUE_FULL (with Retry-After details) per §13.8/§16.4.
        """
        if self._device_active.get(device_id, 0) >= self._per_device_active:
            raise MeshError(
                "QUEUE_FULL",
                "Device already has the maximum number of active generations.",
                details={"retry_after_s": self._retry_after()},
            )
        # §16.4: start immediately while a Backend slot is free; otherwise
        # enqueue while the GLOBAL queue has room (§13.8); else reject.
        running = sum(
            1
            for job in self._jobs.values()
            if job.backend_id == backend_id and job.state == "running"
        )
        concurrency = max(1, self._concurrency.get(backend_id, 1))
        queued = sum(1 for job in self._jobs.values() if job.state == "queued")
        if running >= concurrency and queued >= self._max_queued:
            raise MeshError(
                "QUEUE_FULL",
                "Global queue is full.",
                details={"retry_after_s": self._retry_after()},
            )
        semaphore = self._semaphores.setdefault(backend_id, asyncio.Semaphore(1))
        job = Job(
            request_id=request_id,
            device_id=device_id,
            backend_id=backend_id,
            token=CancelToken(),
            enqueued_at_mono=self._clock.now_monotonic(),
            _slot=semaphore,
        )
        self._jobs[request_id] = job
        self._device_active[device_id] = self._device_active.get(device_id, 0) + 1
        return job

    async def await_running(self, job: Job) -> None:
        """Block until a Backend slot is free (waiting = queued; FIFO by
        semaphore waiter order). Cancelled jobs never take the slot."""
        slot = job._slot  # noqa: SLF001 — set in admit()
        assert slot is not None
        while True:
            if job.token.cancelled:
                self._finish(job, "cancelled")
                raise MeshError("CANCELLED", "Cancelled while queued.")
            try:
                await asyncio.wait_for(slot.acquire(), timeout=0.5)
                job._holds_slot = True  # noqa: SLF001
                break
            except TimeoutError:  # re-check cancellation periodically (§13.7 ≤1 s)
                continue
        job.state = "running"
        job.queued_ms = int((self._clock.now_monotonic() - job.enqueued_at_mono) * 1000)

    def release(self, job: Job, *, duration_s: float | None = None) -> None:
        """Free the Backend slot and device count; drain next waiter (§16.4)."""
        if job.state in ("done", "cancelled"):
            return
        slot = job._slot  # noqa: SLF001
        if job._holds_slot and slot is not None:  # noqa: SLF001
            job._holds_slot = False  # noqa: SLF001
            slot.release()
        if duration_s is not None:
            self._recent_durations.append(duration_s)
            if len(self._recent_durations) > 32:
                self._recent_durations.pop(0)
        self._finish(job, "done")

    def _finish(self, job: Job, state: Literal["done", "cancelled"]) -> None:
        job.state = state
        self._jobs.pop(job.request_id, None)
        remaining = self._device_active.get(job.device_id, 1) - 1
        if remaining <= 0:
            self._device_active.pop(job.device_id, None)
        else:
            self._device_active[job.device_id] = remaining
        if job.cancel_requested_mono is not None and self._metrics is not None:
            # §20.1 cancel_latency_ms: cancel request → job finished (slot
            # freed), the observable §13.7 "abort ≤ 1 s" commitment.
            self._metrics.observe(
                "cancel_latency_ms",
                max(0.0, (self._clock.now_monotonic() - job.cancel_requested_mono) * 1000),
            )

    # -- cancellation (§13.7: abort ≤ 1 s, free the slot, no further events) ----

    def cancel(self, request_id: str) -> bool:
        """Cancel one generation. Returns False if unknown/finished (§13.2
        API-REQ-01: 404 for unknown/finished; 403 handled by the API layer)."""
        job = self._jobs.get(request_id)
        if job is None:
            return False
        if not job.token.cancelled:
            job.cancel_requested_mono = self._clock.now_monotonic()
        job.token.cancel()
        job.cancel_reason = "client_request"
        return True

    def cancel_by_device(self, device_id: str) -> int:
        """Cancel all generations of one Device (used on revoke, §10.4)."""
        cancelled = 0
        for job in list(self._jobs.values()):
            if job.device_id == device_id and not job.token.cancelled:
                job.cancel_requested_mono = self._clock.now_monotonic()
                job.token.cancel()
                job.cancel_reason = "device_revoked"
                cancelled += 1
        return cancelled

    def is_owner(self, request_id: str, device_id: str) -> bool:
        """True when the request belongs to the Device (API-REQ-01 403 rule)."""
        job = self._jobs.get(request_id)
        return job is not None and job.device_id == device_id

    def has(self, request_id: str) -> bool:
        """True while the request is still tracked (queued or running)."""
        return request_id in self._jobs

    # -- stats (§13.2 API-HEALTH-01 queue block; §20.1) ---------------------------

    def queue_stats(self) -> dict[str, int]:
        active = sum(1 for job in self._jobs.values() if job.state == "running")
        queued = sum(1 for job in self._jobs.values() if job.state == "queued")
        return {"active": active, "queued": queued, "max_queued": self._max_queued}

    def _retry_after(self) -> float:
        """'Retry-After = est. from recent durations' (§16.4)."""
        if not self._recent_durations:
            return DEFAULT_RETRY_AFTER_S
        return max(1.0, sum(self._recent_durations) / len(self._recent_durations))
