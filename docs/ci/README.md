# CI — PR gate workflow (staged)

The wired GitHub Actions pipeline for this repo lives here as
[`PR-GATE.yml`](./PR-GATE.yml) while the publishing token lacks the
**Workflows** permission (GitHub refuses pushes that create
`.github/workflows/*.yml` without it — observed 2026-10-05, commit
`chore(oss): publish readiness`).

## What the pipeline does (§21.4)

Full gate chain on every PR/push to `main`: ruff + ruff format, mypy --strict
(core, security), unit → contract → integration → security pytest layers,
import-linter (§10.1 dependency rule), OpenAPI drift check (ADR-015), the four
security scanners (SEC-N1 cleartext, SEC-N3 content-columns, SEC-N5 secrets,
pip-audit), npm audit for the mobile app, and a JDK 17 `gradlew assembleDebug`
APK build. On tags: the full M9 release gate + wheel/sdist/SHA256SUMS build.

## Restore path (owner, once the token includes the Workflows permission)

```bash
mkdir -p .github/workflows
git mv docs/ci/PR-GATE.yml .github/workflows/ci.yml
git commit -m "ci(gha): restore PR gate workflow [§21.4]"
git push
```

No content changes are needed — the file is written for its final location and
uses repo-relative paths, so the move is purely mechanical.
