"""psutil-based hardware probe + composite assembly — WP-15 (§10.1, §10.2).

Implements the `HardwareProbe` port (§10.2: `snapshot() -> HardwareInfo`,
all fields Optional) with psutil for OS/CPU/RAM. Design rules:

- **Best effort, never raising** (FR-STAT-01: "Works with no GPU; no
  exceptions"): every attribute read is individually guarded; a failing
  read leaves that field `None` (§13.2 API-DEV-01: "MUST NOT fill unknowns
  with defaults" — an absent value is reported as `null`).
- **Blocking work in a thread pool with a 2 s timeout** (§10.5: "NVML,
  psutil, subprocess for tailscale run in a thread pool with timeouts").
  Timeout semantics use `asyncio.wait(..., timeout=)` (NOT `wait_for`):
  worker threads cannot be cancelled, so the caller abandons a slow probe
  at the deadline and its late result is discarded — the event loop and
  the request are never blocked beyond the timeout. On timeout/exception
  the probe degrades to an all-`None` snapshot.
- **Injectable seams**: the psutil/platform modules and the
  `/proc/cpuinfo` reader can be injected for tests (§10.2 "injectable for
  tests" Clock analogy); production uses the real modules via lazy import.

`CompositeHardwareProbe` merges a base probe (psutil) with GPU listers
(`nvidia_probe.NvmlGpuProbe`); a GPU probe failing degrades only the `gpus`
tuple, never the base fields.
"""

from __future__ import annotations

import asyncio
import platform as _platform
from collections.abc import Callable, Sequence
from dataclasses import replace
from typing import Any, Protocol

from localmesh_agent.adapters.ports import GpuInfo, HardwareInfo
from localmesh_agent.observability.logging import get_logger

log = get_logger("hardware")

COMPONENT = "hardware"

# §10.5: blocking probe work runs in a thread pool with 2 s timeouts.
SNAPSHOT_TIMEOUT_S = 2.0

CpuinfoReader = Callable[[], str]

_LINUX_CPUINFO_PATH = "/proc/cpuinfo"


def _default_cpuinfo_reader() -> str:
    """Read /proc/cpuinfo (Linux only); any failure yields an empty string."""
    try:
        with open(_LINUX_CPUINFO_PATH, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def _linux_cpu_model(cpuinfo_text: str) -> str | None:
    """Extract the first `model name` from /proc/cpuinfo content, or None.

    This reads a value REPORTED BY THE OS (not a guess): `platform.processor()`
    is frequently empty on Linux, and the spec's example (`"model": null`)
    shows an unknown model must stay null when the OS does not report one.
    """
    for line in cpuinfo_text.splitlines():
        key, _, value = line.partition(":")
        if key.strip() == "model name":
            model = value.strip()
            return model or None
    return None


def _clean(value: Any) -> Any:
    """Empty strings / falsy scalars become None (no invented defaults)."""
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return value


class GpuLister(Protocol):
    """A probe that can list GPU snapshots (implemented by NvmlGpuProbe)."""

    async def gpus(self) -> tuple[GpuInfo, ...]: ...


class PsutilHardwareProbe:
    """`HardwareProbe` port implementation (§10.2) backed by psutil + platform."""

    def __init__(
        self,
        psutil_module: Any | None = None,
        platform_module: Any | None = None,
        cpuinfo_reader: CpuinfoReader | None = None,
        timeout_s: float = SNAPSHOT_TIMEOUT_S,
    ) -> None:
        self._psutil = psutil_module  # lazy import when None (production path)
        self._platform = platform_module if platform_module is not None else _platform
        self._cpuinfo_reader = cpuinfo_reader or _default_cpuinfo_reader
        self._timeout_s = timeout_s

    async def snapshot(self) -> HardwareInfo:
        try:
            return await self._run_bounded(self._collect)
        except Exception as exc:  # noqa: BLE001 — FR-STAT-01: probe never raises
            log.warning(
                "hardware_probe_degraded",
                extra={"component": COMPONENT, "status": "error"},
            )
            log.debug("hardware_probe_error", extra={"component": COMPONENT, "detail": repr(exc)})
            return HardwareInfo()

    async def _run_bounded(self, fn: Callable[[], HardwareInfo]) -> HardwareInfo:
        """Run a blocking collect in the default executor with true timeout.

        §10.5 bounds the WAIT, not the thread: a probe stuck past the
        deadline is abandoned (its result dropped, never awaited), which a
        `wait_for` around `to_thread` cannot guarantee (worker threads are
        uncancellable, so the await would ride until the thread returns).
        """
        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(None, fn)
        done, _pending = await asyncio.wait({future}, timeout=self._timeout_s)
        if not done:
            log.warning(
                "hardware_probe_timeout",
                extra={"component": COMPONENT, "timeout_s": self._timeout_s},
            )
            return HardwareInfo()
        return future.result()

    def _collect(self) -> HardwareInfo:
        """Blocking collection — runs in a worker thread (§10.5)."""
        psutil = self._psutil
        if psutil is None:
            import psutil as _psutil_mod

            psutil = _psutil_mod

        os_family = _clean(str(self._platform.system()) if self._platform.system() else None)
        if isinstance(os_family, str):
            os_family = os_family.lower()  # §13.2 example: "windows"
        os_version = _clean(self._platform.release())
        cpu_model = _clean(self._platform.processor())
        if cpu_model is None:
            cpu_model = _linux_cpu_model(self._cpuinfo_reader())

        logical_cores: int | None = None
        ram_total: int | None = None
        ram_available: int | None = None
        try:
            logical_cores = _clean(psutil.cpu_count(logical=True))
        except Exception:  # noqa: BLE001 — per-field degradation
            logical_cores = None
        try:
            vm = psutil.virtual_memory()
            ram_total = _clean(getattr(vm, "total", None))
            ram_available = _clean(getattr(vm, "available", None))
        except Exception:  # noqa: BLE001 — per-field degradation
            ram_total = None
            ram_available = None

        return HardwareInfo(
            os_family=os_family if isinstance(os_family, str) else None,
            os_version=os_version if isinstance(os_version, str) else None,
            cpu_model=cpu_model if isinstance(cpu_model, str) else None,
            logical_cores=logical_cores,
            ram_total_bytes=ram_total,
            ram_available_bytes=ram_available,
            gpus=(),  # GPUs come from GpuLister probes (nvidia_probe), merged below
        )


class CompositeHardwareProbe:
    """Merge a base HardwareProbe with GPU listers (WP-15 assembly).

    Each part degrades independently (FR-STAT-01): a GPU probe failure
    yields an empty/partial `gpus` tuple while OS/CPU/RAM fields survive.
    """

    def __init__(
        self,
        base: PsutilHardwareProbe,
        gpu_probes: Sequence[GpuLister] = (),
        timeout_s: float = SNAPSHOT_TIMEOUT_S,
    ) -> None:
        self._base = base
        self._gpu_probes = tuple(gpu_probes)
        self._timeout_s = timeout_s

    async def snapshot(self) -> HardwareInfo:
        try:
            base_info = await asyncio.wait_for(self._base.snapshot(), timeout=self._timeout_s)
        except Exception:  # noqa: BLE001 — FR-STAT-01
            base_info = HardwareInfo()

        gpus: list[GpuInfo] = []
        for probe in self._gpu_probes:
            try:
                listed = await asyncio.wait_for(probe.gpus(), timeout=self._timeout_s)
                gpus.extend(listed)
            except Exception:  # noqa: BLE001 — GPU detection degrades only itself
                log.warning(
                    "gpu_probe_degraded",
                    extra={"component": COMPONENT, "status": "error"},
                )
        return replace(base_info, gpus=tuple(gpus))
