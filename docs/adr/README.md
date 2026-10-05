# ADRs

One file per ADR change, named `NNN-kebab-case-title.md`, using the template in
`_template.md` (LM-ARCH-001 Appendix F).

- ADR-001…ADR-016 are recorded in LM-ARCH-001 §8 and are **not** duplicated here.
- New decisions, refinements and supersessions land here as new files.
- Status lifecycle: `Proposed` (needs owner approval) -> `Accepted` (overrides
  everything below it in precedence, §1.1) -> `Superseded by ADR-MMM`.

| ADR | Title | Status |
|---|---|---|
| 017 | Python build backend: setuptools | Proposed |
| 018 | NVIDIA NVML binding distribution: `nvidia-ml-py` (not `pynvml`) | Proposed |
| 019 | Control Plane activation for M6 (Supabase REST, Metadata-only) | Accepted |
| 020 | Agent-runtime tool sandbox: default-deny allow-list | Accepted |
| 021 | Go/Rust single-binary rewrite: M9 decision gate closed (keep Python) | Accepted |
