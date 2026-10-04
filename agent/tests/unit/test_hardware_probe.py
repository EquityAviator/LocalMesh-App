"""WP-15 unit tests — hardware probes (§10.2 HardwareProbe, FR-STAT-01).

Covers:
- PsutilHardwareProbe: full mapping, per-field degradation, OS mapping,
  Linux /proc/cpuinfo fallback, timeout/exception → all-None snapshot.
- NvmlGpuProbe: happy path (2 GPUs), init failure → (), import failure →
  (), per-field NotSupported → None, bytes name decoding, shutdown called.
- CompositeHardwareProbe: independent degradation of base vs GPU parts.
- Port conformance (§10.2 runtime_checkable protocols).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

from localmesh_agent.adapters.hardware.nvidia_probe import NvmlGpuProbe
from localmesh_agent.adapters.hardware.psutil_probe import (
    CompositeHardwareProbe,
    PsutilHardwareProbe,
    _linux_cpu_model,
)
from localmesh_agent.adapters.ports import GpuInfo, HardwareInfo, HardwareProbe

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakePsutil:
    """Minimal psutil-shaped module (injectable; may be configured to raise)."""

    def __init__(
        self,
        logical: int | None = 16,
        total: int = 34_359_738_368,
        available: int = 12_000_000_000,
        *,
        cpu_count_error: bool = False,
        vm_error: bool = False,
    ) -> None:
        self._logical = logical
        self._total = total
        self._available = available
        self._cpu_count_error = cpu_count_error
        self._vm_error = vm_error

    def cpu_count(self, logical: bool = True) -> int | None:  # noqa: ARG002
        if self._cpu_count_error:
            raise RuntimeError("boom")
        return self._logical

    def virtual_memory(self) -> Any:
        if self._vm_error:
            raise RuntimeError("boom")

        class VM:
            total = self._total
            available = self._available

        return VM()


class FakePlatform:
    def __init__(
        self,
        system: str = "Windows",
        release: str = "11",
        processor: str = "Intel64 Family 6",
    ) -> None:
        self._system = system
        self._release = release
        self._processor = processor

    def system(self) -> str:
        return self._system

    def release(self) -> str:
        return self._release

    def processor(self) -> str:
        return self._processor


class FakeNvml:
    """Minimal pynvml-shaped module."""

    NVML_TEMPERATURE_GPU = 0

    class NVMLError(Exception):
        pass

    class NVMLError_NotSupported(NVMLError):
        pass

    def __init__(self, count: int = 2, *, init_error: bool = False) -> None:
        self._count = count
        self._init_error = init_error
        self.shutdown_called = False
        self.init_called = False

    def nvmlInit(self) -> None:  # noqa: N802
        self.init_called = True
        if self._init_error:
            raise self.NVMLError("driver not loaded")

    def nvmlShutdown(self) -> None:  # noqa: N802
        self.shutdown_called = True

    def nvmlDeviceGetCount(self) -> int:  # noqa: N802
        return self._count

    def nvmlDeviceGetHandleByIndex(self, index: int) -> int:  # noqa: N802
        return index

    def nvmlDeviceGetName(self, handle: int) -> str | bytes:  # noqa: N802
        if handle == 0:
            return b"GeForce RTX 4090"  # legacy bytes shape
        return "NVIDIA A100"

    def nvmlDeviceGetMemoryInfo(self, handle: int) -> Any:  # noqa: N802
        class Mem:
            total = 24 * 1024**3
            used = 8 * 1024**3

        return Mem()

    def nvmlDeviceGetUtilizationRates(self, handle: int) -> Any:  # noqa: N802
        if handle == 1:
            raise self.NVMLError_NotSupported("util not supported")

        class Util:
            gpu = 37

        return Util()

    def nvmlDeviceGetTemperature(self, handle: int, sensor: int) -> int:  # noqa: N802,ARG002
        return 62


# ---------------------------------------------------------------------------
# /proc/cpuinfo fallback
# ---------------------------------------------------------------------------


def test_linux_cpu_model_parses_first_model_name() -> None:
    text = "processor\t: 0\nmodel name\t: AMD Ryzen 9 7950X\nflags\t: fpu...\n"
    assert _linux_cpu_model(text) == "AMD Ryzen 9 7950X"


def test_linux_cpu_model_absent_returns_none() -> None:
    assert _linux_cpu_model("processor\t: 0\n") is None
    assert _linux_cpu_model("") is None


# ---------------------------------------------------------------------------
# PsutilHardwareProbe
# ---------------------------------------------------------------------------


def test_psutil_probe_full_mapping() -> None:
    probe = PsutilHardwareProbe(
        psutil_module=FakePsutil(),
        platform_module=FakePlatform(),
        cpuinfo_reader=lambda: "",
    )
    info = asyncio.run(probe.snapshot())
    assert isinstance(info, HardwareInfo)
    assert info.os_family == "windows"  # §13.2 example casing
    assert info.os_version == "11"
    assert info.cpu_model == "Intel64 Family 6"
    assert info.logical_cores == 16
    assert info.ram_total_bytes == 34_359_738_368
    assert info.ram_available_bytes == 12_000_000_000
    assert info.gpus == ()


def test_psutil_probe_protocol_conformance() -> None:
    probe = PsutilHardwareProbe(psutil_module=FakePsutil(), platform_module=FakePlatform())
    assert isinstance(probe, HardwareProbe)  # §10.2 runtime_checkable


def test_psutil_probe_linux_cpu_model_fallback() -> None:
    # platform.processor() empty (typical Linux) → /proc/cpuinfo read.
    probe = PsutilHardwareProbe(
        psutil_module=FakePsutil(),
        platform_module=FakePlatform(system="Linux", processor=""),
        cpuinfo_reader=lambda: "model name\t: Intel Core Ultra 7\n",
    )
    info = asyncio.run(probe.snapshot())
    assert info.cpu_model == "Intel Core Ultra 7"


def test_psutil_probe_unknown_stays_none() -> None:
    # §13.2: MUST NOT fill unknowns with defaults — all sources empty → nulls.
    probe = PsutilHardwareProbe(
        psutil_module=FakePsutil(logical=None),
        platform_module=FakePlatform(system="", release="", processor=""),
        cpuinfo_reader=lambda: "",
    )
    info = asyncio.run(probe.snapshot())
    assert info.os_family is None
    assert info.os_version is None
    assert info.cpu_model is None
    assert info.logical_cores is None


def test_psutil_probe_per_field_errors_degrade() -> None:
    probe = PsutilHardwareProbe(
        psutil_module=FakePsutil(cpu_count_error=True, vm_error=True),
        platform_module=FakePlatform(),
        cpuinfo_reader=lambda: (_ for _ in ()).throw(OSError("no procfs")),
    )
    info = asyncio.run(probe.snapshot())
    assert info.os_family == "windows"  # platform fields survive
    assert info.cpu_model == "Intel64 Family 6"
    assert info.logical_cores is None  # psutil failures → null, not 0
    assert info.ram_total_bytes is None
    assert info.ram_available_bytes is None


def test_psutil_probe_blocking_module_error_degrades_to_empty() -> None:
    class ExplodingPsutil:
        def __getattr__(self, name: str) -> Any:
            raise RuntimeError("no")

    class ExplodingPlatform:
        def system(self) -> str:
            raise RuntimeError("no")

        def release(self) -> str:
            raise RuntimeError("no")

        def processor(self) -> str:
            raise RuntimeError("no")

    def exploding_reader() -> str:
        raise RuntimeError("no")

    probe = PsutilHardwareProbe(
        psutil_module=ExplodingPsutil(),
        platform_module=ExplodingPlatform(),
        cpuinfo_reader=exploding_reader,
    )
    info = asyncio.run(probe.snapshot())
    assert info == HardwareInfo()  # all-None snapshot, no exception (FR-STAT-01)


def test_psutil_probe_timeout_degrades(monkeypatch: pytest.MonkeyPatch) -> None:
    def slow_collect() -> HardwareInfo:
        time.sleep(0.4)
        return HardwareInfo(os_family="windows")

    probe = PsutilHardwareProbe(
        psutil_module=FakePsutil(), platform_module=FakePlatform(), timeout_s=0.05
    )
    monkeypatch.setattr(probe, "_collect", slow_collect)

    async def scenario() -> tuple[HardwareInfo, float]:
        started = time.monotonic()
        info = await probe.snapshot()
        return info, time.monotonic() - started

    info, elapsed = asyncio.run(scenario())
    assert info.os_family is None  # timed out → all-None
    # §10.5 bounds the caller's WAIT: the abandoned thread may keep running,
    # but the awaiter is released at the deadline (the residual time shows up
    # only in asyncio.run's executor teardown, after the coroutine returned).
    assert elapsed < 0.35


# ---------------------------------------------------------------------------
# NvmlGpuProbe
# ---------------------------------------------------------------------------


def test_nvml_probe_two_gpus_with_bytes_name() -> None:
    nvml = FakeNvml(count=2)
    probe = NvmlGpuProbe(nvml_module=nvml)
    gpus = asyncio.run(probe.gpus())
    assert nvml.init_called and nvml.shutdown_called  # symmetric lifecycle
    assert len(gpus) == 2
    assert gpus[0].name == "GeForce RTX 4090"  # bytes decoded
    assert gpus[0].vram_total_bytes == 24 * 1024**3
    assert gpus[0].vram_used_bytes == 8 * 1024**3
    assert gpus[0].utilization_pct == 37.0
    assert gpus[0].temperature_c == 62.0
    assert gpus[1].name == "NVIDIA A100"
    assert gpus[1].utilization_pct is None  # NotSupported → null (per-field)
    assert gpus[1].vram_total_bytes == 24 * 1024**3  # rest survive


def test_nvml_probe_init_failure_returns_empty() -> None:
    nvml = FakeNvml(init_error=True)
    gpus = asyncio.run(NvmlGpuProbe(nvml_module=nvml).gpus())
    assert gpus == ()  # no fabricated GPU entries (§13.2)
    assert nvml.init_called
    # No init success → no matching shutdown (NVML pairs shutdown with a
    # successful init only); enumeration-failure path still shuts down.


def test_nvml_probe_import_failure_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    real_import = builtins.__import__

    def no_pynvml(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "pynvml":
            raise ImportError("No module named 'pynvml'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_pynvml)
    gpus = asyncio.run(NvmlGpuProbe().gpus())  # no module injected → lazy import
    assert gpus == ()  # §21.2 optional dependency, CPU-only host


def test_nvml_probe_zero_devices_returns_empty() -> None:
    gpus = asyncio.run(NvmlGpuProbe(nvml_module=FakeNvml(count=0)).gpus())
    assert gpus == ()


def test_nvml_probe_enumeration_error_degrades() -> None:
    class HalfBroken(FakeNvml):
        def nvmlDeviceGetCount(self) -> int:  # noqa: N802
            raise self.NVMLError("enum failed")

    nvml = HalfBroken()
    gpus = asyncio.run(NvmlGpuProbe(nvml_module=nvml).gpus())
    assert gpus == ()
    assert nvml.shutdown_called  # finally-path shutdown after successful init


def test_nvml_probe_timeout_returns_empty() -> None:
    class SlowNvml(FakeNvml):
        def nvmlDeviceGetCount(self) -> int:  # noqa: N802
            time.sleep(0.5)
            return 1

    async def scenario() -> tuple[tuple[GpuInfo, ...], float]:
        started = time.monotonic()
        gpus = await NvmlGpuProbe(nvml_module=SlowNvml(), timeout_s=0.05).gpus()
        return gpus, time.monotonic() - started

    gpus, elapsed = asyncio.run(scenario())
    assert gpus == ()
    assert elapsed < 0.35  # caller wait bounded (§10.5)


# ---------------------------------------------------------------------------
# CompositeHardwareProbe
# ---------------------------------------------------------------------------


class StaticGpuLister:
    def __init__(self, gpus: tuple[GpuInfo, ...] | None = None, error: bool = False) -> None:
        self._gpus = (
            gpus
            if gpus is not None
            else (
                GpuInfo(
                    name="Test GPU",
                    vram_total_bytes=1,
                    vram_used_bytes=0,
                    utilization_pct=1.0,
                    temperature_c=40.0,
                ),
            )
        )
        self._error = error

    async def gpus(self) -> tuple[GpuInfo, ...]:
        if self._error:
            raise RuntimeError("boom")
        return self._gpus


def test_composite_merges_base_and_gpus() -> None:
    composite = CompositeHardwareProbe(
        PsutilHardwareProbe(psutil_module=FakePsutil(), platform_module=FakePlatform()),
        gpu_probes=(NvmlGpuProbe(nvml_module=FakeNvml(count=1)),),
    )
    info = asyncio.run(composite.snapshot())
    assert info.os_family == "windows"
    assert info.logical_cores == 16
    assert len(info.gpus) == 1
    assert info.gpus[0].name == "GeForce RTX 4090"


def test_composite_gpu_failure_keeps_base_fields() -> None:
    composite = CompositeHardwareProbe(
        PsutilHardwareProbe(psutil_module=FakePsutil(), platform_module=FakePlatform()),
        gpu_probes=(StaticGpuLister(error=True),),
    )
    info = asyncio.run(composite.snapshot())
    assert info.os_family == "windows"  # base survives (independent degradation)
    assert info.gpus == ()


def test_composite_base_failure_yields_all_none() -> None:
    class ExplodingPsutil:
        def __getattr__(self, name: str) -> Any:
            raise RuntimeError("no")

    class ExplodingPlatform:
        def system(self) -> str:
            raise RuntimeError("no")

        def release(self) -> str:
            raise RuntimeError("no")

        def processor(self) -> str:
            raise RuntimeError("no")

    composite = CompositeHardwareProbe(
        PsutilHardwareProbe(
            psutil_module=ExplodingPsutil(),
            platform_module=ExplodingPlatform(),
            cpuinfo_reader=lambda: (_ for _ in ()).throw(RuntimeError("no")),
        ),
        gpu_probes=(StaticGpuLister(),),
    )
    info = asyncio.run(composite.snapshot())
    assert info.os_family is None  # base fully degraded
    assert len(info.gpus) == 1  # GPU part still works


def test_composite_multiple_gpu_probes_concatenate() -> None:
    extra = (
        GpuInfo(
            name="Second",
            vram_total_bytes=2,
            vram_used_bytes=1,
            utilization_pct=None,
            temperature_c=None,
        ),
    )
    composite = CompositeHardwareProbe(
        PsutilHardwareProbe(psutil_module=FakePsutil(), platform_module=FakePlatform()),
        gpu_probes=(StaticGpuLister(), StaticGpuLister(gpus=extra)),
    )
    info = asyncio.run(composite.snapshot())
    assert [g.name for g in info.gpus] == ["Test GPU", "Second"]
