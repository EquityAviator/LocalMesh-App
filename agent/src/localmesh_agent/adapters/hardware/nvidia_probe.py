"""NVIDIA GPU probe via the optional NVML binding — WP-15 (§10.1 "optional pynvml").

Implements the `GpuLister` seam consumed by
`psutil_probe.CompositeHardwareProbe`. Design rules:

- **Optional dependency** (§21.2, distribution per ADR-018): the `nvidia` extra
  installs `nvidia-ml-py`, which ships the `pynvml` module. It may be absent
  (no NVIDIA driver, CPU-only host). An import failure or NVML init failure
  yields an EMPTY tuple — never an error, never a fabricated GPU entry
  (§13.2 API-DEV-01 "MUST NOT fill unknowns with defaults"; FR-STAT-01
  "works with no GPU").
- **Per-field degradation**: NVML reports per-attribute `NVMLError`
  subclasses (e.g. `NVMLError_NotSupported` on some consumer cards); a
  failing attribute leaves that one field `None` while the rest survive.
- **Blocking work in a thread pool with a 2 s timeout** (§10.5). The NVML
  module is injectable for tests (§10.2 injectable-for-tests intent).
  Timeout bounds the WAIT (asyncio.wait), not the thread — a stuck probe
  is abandoned at the deadline, its late result discarded.
- Name decoding: pynvml ≥ 11 returns `str`, older bindings returned
  `bytes` — both are accepted defensively.
"""

from __future__ import annotations

import asyncio
from typing import Any

from localmesh_agent.adapters.ports import GpuInfo
from localmesh_agent.observability.logging import get_logger

log = get_logger("hardware")

COMPONENT = "nvidia"

SNAPSHOT_TIMEOUT_S = 2.0  # §10.5


def _clean_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001 — defensive; never let decoding kill the probe
            return None
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _clean_number(value: Any) -> float | int | None:
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


class NvmlGpuProbe:
    """List NVIDIA GPUs through pynvml; absent/driverless → ()."""

    def __init__(
        self, nvml_module: Any | None = None, timeout_s: float = SNAPSHOT_TIMEOUT_S
    ) -> None:
        self._nvml = nvml_module  # lazy import when None (production path)
        self._timeout_s = timeout_s

    async def gpus(self) -> tuple[GpuInfo, ...]:
        try:
            loop = asyncio.get_running_loop()
            future = loop.run_in_executor(None, self._collect)
            done, _pending = await asyncio.wait({future}, timeout=self._timeout_s)
            if not done:
                log.warning(
                    "gpu_probe_timeout",
                    extra={"component": COMPONENT, "timeout_s": self._timeout_s},
                )
                return ()
            return future.result()
        except Exception:  # noqa: BLE001 — FR-STAT-01: GPU detection never raises
            log.warning(
                "gpu_probe_degraded",
                extra={"component": COMPONENT, "status": "error"},
            )
            return ()

    def _collect(self) -> tuple[GpuInfo, ...]:
        nvml = self._nvml
        if nvml is None:
            try:
                import pynvml as _nvml_mod
            except Exception:  # noqa: BLE001 — optional dep absent (§21.2)
                log.info(
                    "gpu_probe_unavailable",
                    extra={"component": COMPONENT, "status": "absent"},
                )
                return ()
            nvml = _nvml_mod

        try:
            nvml.nvmlInit()
        except Exception:  # noqa: BLE001 — no driver / NVML broken → no GPUs reported
            log.info(
                "gpu_probe_unavailable",
                extra={"component": COMPONENT, "status": "init_failed"},
            )
            return ()
        try:
            count = int(nvml.nvmlDeviceGetCount())
            handles = [nvml.nvmlDeviceGetHandleByIndex(i) for i in range(count)]
            return tuple(self._read_device(nvml, handle) for handle in handles)
        except Exception:  # noqa: BLE001 — enumeration failure degrades to ()
            return ()
        finally:
            try:
                nvml.nvmlShutdown()
            except Exception:  # noqa: BLE001 — shutdown is best effort
                pass

    def _read_device(self, nvml: Any, handle: Any) -> GpuInfo:
        name = self._safe(lambda: _clean_str(nvml.nvmlDeviceGetName(handle)))
        vram_total = self._safe(lambda: self._mem(nvml, handle, "total"))
        vram_used = self._safe(lambda: self._mem(nvml, handle, "used"))
        utilization = self._safe(
            lambda: _clean_number(getattr(nvml.nvmlDeviceGetUtilizationRates(handle), "gpu", None))
        )
        temperature = self._safe(
            lambda: _clean_number(nvml.nvmlDeviceGetTemperature(handle, nvml.NVML_TEMPERATURE_GPU))
        )
        return GpuInfo(
            name=name if isinstance(name, str) else None,
            vram_total_bytes=int(vram_total) if isinstance(vram_total, int) else None,
            vram_used_bytes=int(vram_used) if isinstance(vram_used, int) else None,
            utilization_pct=float(utilization) if isinstance(utilization, (int, float)) else None,
            temperature_c=float(temperature) if isinstance(temperature, (int, float)) else None,
        )

    @staticmethod
    def _mem(nvml: Any, handle: Any, attr: str) -> int | None:
        info = nvml.nvmlDeviceGetMemoryInfo(handle)
        value = getattr(info, attr, None)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        return None

    @staticmethod
    def _safe(fn: Any) -> Any:
        """Per-attribute guard: NVML NotSupported → None for that field only."""
        try:
            return fn()
        except Exception:  # noqa: BLE001 — per-field degradation
            return None
