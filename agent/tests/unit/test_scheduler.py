"""WP-06 unit tests — scheduler admission (§16.4, §13.8)."""

import asyncio

import pytest

from localmesh_agent.core.errors import MeshError
from localmesh_agent.core.scheduler import Scheduler


def test_admit_and_release_cycle() -> None:
    scheduler = Scheduler({"lmstudio": 1})
    job = scheduler.admit(request_id="rq_1", device_id="dv_1", backend_id="lmstudio")
    assert scheduler.has("rq_1")
    assert scheduler.queue_stats() == {"active": 0, "queued": 1, "max_queued": 8}
    job.state = "running"  # simulate acquire
    scheduler.release(job, duration_s=0.2)
    assert not scheduler.has("rq_1")
    assert scheduler.queue_stats()["active"] == 0


def test_per_device_limit_rejects_queue_full() -> None:
    """§13.8: active generations per Device default 2 → 429 QUEUE_FULL."""
    scheduler = Scheduler({"lmstudio": 4}, per_device_active=2)
    scheduler.admit(request_id="rq_1", device_id="dv_1", backend_id="lmstudio")
    scheduler.admit(request_id="rq_2", device_id="dv_1", backend_id="lmstudio")
    with pytest.raises(MeshError) as excinfo:
        scheduler.admit(request_id="rq_3", device_id="dv_1", backend_id="lmstudio")
    assert excinfo.value.code == "QUEUE_FULL"
    assert excinfo.value.http_status == 429
    assert excinfo.value.details is not None
    assert "retry_after_s" in excinfo.value.details


async def test_global_queue_limit_rejects_with_retry_after() -> None:
    """§16.4: queue full → QUEUE_FULL with Retry-After estimate."""
    scheduler = Scheduler({"lmstudio": 1}, max_queued=1)
    running = scheduler.admit(request_id="rq_running", device_id="dv_1", backend_id="lmstudio")
    await scheduler.await_running(running)  # occupy the slot
    scheduler.admit(request_id="rq_queued", device_id="dv_2", backend_id="lmstudio")
    with pytest.raises(MeshError) as excinfo:
        scheduler.admit(request_id="rq_3", device_id="dv_3", backend_id="lmstudio")
    assert excinfo.value.code == "QUEUE_FULL"
    assert excinfo.value.details is not None
    assert excinfo.value.details["retry_after_s"] > 0


async def test_retry_after_estimated_from_recent_durations() -> None:
    """§16.4: Retry-After estimated from recent durations."""
    scheduler = Scheduler({"lmstudio": 1}, max_queued=0)
    running = scheduler.admit(request_id="rq_running", device_id="dv_1", backend_id="lmstudio")
    await scheduler.await_running(running)
    scheduler._recent_durations.extend([2.0, 4.0])  # noqa: SLF001
    with pytest.raises(MeshError) as excinfo:
        scheduler.admit(request_id="rq_2", device_id="dv_2", backend_id="lmstudio")
    assert excinfo.value.details is not None
    assert excinfo.value.details["retry_after_s"] == pytest.approx(3.0)


def test_cancel_and_cancel_by_device() -> None:
    scheduler = Scheduler({"lmstudio": 1})
    job = scheduler.admit(request_id="rq_1", device_id="dv_1", backend_id="lmstudio")
    job2 = scheduler.admit(request_id="rq_2", device_id="dv_1", backend_id="lmstudio")
    assert scheduler.cancel("rq_1")
    assert job.token.cancelled
    # cancel_by_device skips already-cancelled jobs
    assert scheduler.cancel_by_device("dv_1") == 1
    assert job2.token.cancelled
    assert not scheduler.cancel("rq_missing")
    # §13.7: revoke path frees slots via release (same mechanism)
    scheduler.release(job)
    scheduler.release(job2)
    assert scheduler.queue_stats()["active"] == 0


async def test_cancelled_while_queued_raises_cancelled() -> None:
    """Cancel while queued: never takes the slot, CANCELLED raised (§16.4)."""
    scheduler = Scheduler({"lmstudio": 1})
    blocker = scheduler.admit(request_id="rq_block", device_id="dv_0", backend_id="lmstudio")
    await scheduler.await_running(blocker)  # occupy the single slot
    job = scheduler.admit(request_id="rq_1", device_id="dv_1", backend_id="lmstudio")
    assert job.state == "queued"
    scheduler.cancel("rq_1")
    with pytest.raises(MeshError) as excinfo:
        await scheduler.await_running(job)
    assert excinfo.value.code == "CANCELLED"
    scheduler.release(blocker)
    assert scheduler.queue_stats()["active"] == 0


async def test_queued_ms_measured_and_fifo_drain() -> None:
    """Slot release drains the FIFO waiter; queued_ms recorded (§16.4)."""
    scheduler = Scheduler({"lmstudio": 1})
    first = scheduler.admit(request_id="rq_1", device_id="dv_1", backend_id="lmstudio")
    second = scheduler.admit(request_id="rq_2", device_id="dv_2", backend_id="lmstudio")
    run_first = asyncio.create_task(scheduler.await_running(first))
    run_second = asyncio.create_task(scheduler.await_running(second))
    await run_first
    assert first.queued_ms == 0
    await asyncio.sleep(0.05)
    scheduler.release(first, duration_s=0.05)
    await asyncio.wait_for(run_second, timeout=2)
    assert second.queued_ms >= 40  # waited for the first to finish
