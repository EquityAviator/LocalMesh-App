# ADR-021 — Go/Rust single-binary rewrite: M9 decision gate closed (keep Python)

Status: Accepted (M9 gate outcome; per ADR-002's own re-open criteria and R-07)

Context: ADR-002 (recorded in LM-ARCH-001 §8) chose Python for the Agent and
explicitly deferred a Go/Rust single-binary rewrite as "a later optional
rewrite". Two governance hooks require this decision to be MADE (not silently
skipped) at M9:

- §22.1 M9 row: "…installers, signed releases, optional Go/Rust decision".
- R-07 (§21 risk register): "Python Agent footprint/packaging pain on Windows
  — Early packaging spike; Go/Rust decision gate at M9".

§23 / RELEASE.md define the re-open trigger: "revisit only with measured
need (distribution size / startup time)". M9 therefore closes the gate by
EVALUATING the measured need, not by re-litigating the language choice.

Decision:

1. **Keep Python for the 1.0.0 line.** No rewrite is scheduled.
2. The M9 packaging deliverables that R-07 worried about exist as dev-hosted
   templates and are the accepted distribution story for v1.0:
   `pipx`/wheel install (§21.6), `packaging/windows/install-agent.ps1`
   (service + FR-AGT-05 Private-profile firewall + ACL), and
   `packaging/systemd/localmesh-agent.service` (hardened non-root unit).
3. **Re-open criteria** (all three require MEASUREMENTS recorded in a new
   ADR; slowness anecdotes do not qualify):
   a. Installer friction: a Windows packaging defect that the wheel+ps1 path
      cannot fix (e.g. a dependency that cannot be made to install
      unprivileged) — evidenced by a failing install on a real machine.
   b. Footprint: measured wheel+venv on-disk size or cold-start time
      exceeding the owner-approved budget by a documented factor.
   c. Distribution need: an owner decision to ship a Store/single-binary
      channel that the wheel story cannot serve.

Consequences:

- Zero code movement now; the packaging layer stays the R-07 mitigation.
- The rewrite, if ever opened, starts as a new ADR that supersedes this one
  and re-runs the WP-02 dependency spike for the new runtime.
- Known cost accepted: Python runtime dependency on target machines (documented
  in RELEASE.md install paths); no ADR-002 behaviour changes.

Verification: unit `tests/unit/test_release_engineering.py` pins the release
surface; packaging templates are covered by `tests/unit/test_packaging.py`
(Windows firewall scope §FR-AGT-05, systemd hardening). Real-machine installer
runs remain owner verification (sandbox cannot execute Windows/systemd).
