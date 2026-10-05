# ADR-017 — Python build backend: setuptools

Status: Proposed

Context: WP-01 must make the `agent` package installable (`pip install -e agent`)
for CI, local tooling and later `pipx` packaging (§21.6). LM-ARCH-001 §21.2 lists
the Agent runtime and tooling libraries but does not name a PEP 517 build
backend; adding one therefore requires an ADR (AGENTS.md: "No new dependency
without an ADR"; §1.2 rule 5). Evidence: `setuptools` is the default backend
assumed by PEP 517 when `[build-system]` is absent, is packaged with CPython
tooling, and is the least-moving-parts choice (CON-05).

Decision: use `setuptools` (PEP 517/621) as the build backend for
`agent/pyproject.toml`, declared as `requires = ["setuptools>=77"]` (first
version with standardized license expression support, per its changelog; exact
version pinned via the WP-02 registry capture, not from memory). It is a build
dependency only — it never becomes an Agent runtime import.

Consequences: + zero extra tooling to learn, widest documented support.
- A more modern backend (e.g. hatchling) could be swapped later by editing only
  `[build-system]`; no runtime impact.
- Follow-up: record the exact pinned setuptools version in `agent/requirements.txt`
  (§17.11) at WP-02.

Alternatives rejected: hatchling/uv-build (fine, but adds a second build tool
to the stack for no M0 benefit, CON-05); poetry-core (brings its own workflow
contra §21.2 tooling choice of uv/pip-tools); flit (src-layout with package
data migrations is better served by setuptools here).

Requirements affected: NFR-MAINT-01   Contracts affected: §21.2 (tooling), §21.6 (packaging)
