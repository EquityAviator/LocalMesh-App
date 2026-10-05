# ADR-018 — NVIDIA NVML binding distribution: `nvidia-ml-py` (not `pynvml`)

Status: Proposed

Context: LM-ARCH-001 §21.2 lists the optional GPU probe dependency as "pynvml"
and delegates the final distribution name to the WP-02 spike
(`agent/pyproject.toml` carried the same deferral comment). The WP-02 report
(`docs/spikes/WP-02-report.md`, "pynvml vs nvidia-ml-py") pre-registered the
decision rule: *"If M5 finds `nvidia-ml-py` is the better-supported
distribution, switching = new dependency → ADR at that time."* At M5 (WP-15),
the installed `pynvml` 13.0.1 emits `FutureWarning: The pynvml package is
deprecated. Please install nvidia-ml-py instead.` on import — the upstream
project itself now names the successor. Evidence: warning text captured at
WP-15 part 1 test runs; `nvidia-ml-py` 13.615.71 (BSD, NVIDIA's official
binding) was already registry-captured by WP-02
(`docs/spikes/evidence/raw-2026-10-04/pypi-nvidia-ml-py.json`).

Decision: switch the optional `nvidia` extra from `pynvml` to
`nvidia-ml-py==13.615.71` (the exact version captured by the WP-02 evidence
run; pinned in `agent/requirements.txt` with hashes, §17.11). Both
distributions ship a module literally named `pynvml`, so
`adapters/hardware/nvidia_probe.py` keeps `import pynvml` and no runtime code,
test stub, or public interface changes.

Consequences: + removes the deprecation FutureWarning from every Agent run
(processes should not train users to ignore warnings, §21.4 hygiene).
+ Stays on NVIDIA's maintained binding; same BSD licensing family.
- §21.2 text still reads "pynvml" — satisfied in spirit (the import name) with
  the distribution decision recorded here; flag for the next spec errata pass.
- No behavior change: the probe's defensive rules (optional import, absent →
  `()`, per-field degradation) are distribution-independent; all 19 hardware
  probe unit tests pass unchanged.

Alternatives rejected: staying on `pynvml` 13.0.1 (upstream-deprecated,
emits a warning on every run); `nvidia-ml-py` re-export wrappers or vendoring
(adds surface for zero benefit, CON-05).

Requirements affected: FR-STAT-01 (GPU inventory source)   Contracts affected: §21.2 (optional dependency), §6.5-adjacent finding in WP-02 report
