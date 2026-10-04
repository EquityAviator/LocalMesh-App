#!/usr/bin/env bash
# Release gate — all automated §21.4/§21.6 gates from docs/RELEASE.md, in order.
# (M9, §22.1 M9 exit: "§17.13 all green; release gates pass".)
#
# Usage (MUST be called from the repo root, like scripts/pytest_layer.sh):
#   bash scripts/release_gate.sh             # dev run: automated gates only
#   bash scripts/release_gate.sh --release   # release run: additionally requires
#                                            # docs/security/pentest-signoff.md
#                                            # (manual §17.13 pen-pass sign-off)
#
# venv note (same convention as pytest_layer.sh / check_openapi_drift.py):
# when agent/.venv exists (sandbox), its interpreter and tools are preferred;
# CI (no venv) uses PATH unchanged.

set -uo pipefail
cd "$(dirname "$0")/.."

RELEASE_MODE=0
for arg in "$@"; do
  case "$arg" in
    --release) RELEASE_MODE=1 ;;
    *) echo "unknown flag: $arg"; exit 2 ;;
  esac
done

VENV_BIN=""
if [ -d "agent/.venv/bin" ]; then VENV_BIN="$(pwd)/agent/.venv/bin"; fi
PY="${VENV_BIN}/python"; [ -x "$PY" ] || PY="python3"
RUFF="${VENV_BIN}/ruff"; [ -x "$RUFF" ] || RUFF="ruff"
MYPY="${VENV_BIN}/mypy"; [ -x "$MYPY" ] || MYPY="mypy"
LINT_IMPORTS="${VENV_BIN}/lint-imports"; [ -x "$LINT_IMPORTS" ] || LINT_IMPORTS="lint-imports"
PIP_AUDIT="${VENV_BIN}/pip-audit"; [ -x "$PIP_AUDIT" ] || PIP_AUDIT="pip-audit"

FAILED=0
step() { # step <name> <cmd...>
  local name="$1"; shift
  echo ""
  echo "=== release-gate: ${name} ==="
  if "$@"; then
    echo "--- ${name}: PASS"
  else
    echo "--- ${name}: FAIL"
    FAILED=1
  fi
}

# 1. Lint (§21.2).
step "ruff check"   "$RUFF" check --config agent/pyproject.toml agent tools scripts
step "ruff format"  "$RUFF" format --check --config agent/pyproject.toml agent tools scripts

# 2. Typecheck (§21.2: mypy --strict on core/ + security/).
( cd agent && step "mypy --strict" "$MYPY" --strict src/localmesh_agent/core src/localmesh_agent/security )

# 3-6. Test layers (§21.5 + §17.13). Contract tests vs recorded fixtures remain
# an announced skip until the owner records real-Backend fixtures (CAPTURE.md);
# the release-gate contract layer therefore runs the framework and reports the
# skip state honestly rather than pretending a hard gate it cannot satisfy.
step "unit tests"        bash scripts/pytest_layer.sh agent/tests/unit
step "contract tests"    bash scripts/pytest_layer.sh agent/tests/contract
step "integration tests" bash scripts/pytest_layer.sh tools/fake-backends/tests agent/tests/integration
step "security tests"    bash scripts/pytest_layer.sh agent/tests/security

# 7. Import-linter (§10.1).
( cd agent && PYTHONPATH="$(pwd)/src" step "import-linter" "$LINT_IMPORTS" --config .importlinter )

# 8. OpenAPI drift (§21.3).
step "openapi drift" "$PY" scripts/check_openapi_drift.py

# 9. Repo-level security gates (§21.4 / TC-SEC-07 manifest scans).
step "cleartext scan"      "$PY" scripts/security/scan_cleartext_manifest.py
step "content-column scan" "$PY" scripts/security/scan_content_columns.py
step "secret scan"         "$PY" scripts/security/scan_secrets.py

# 10. Dependency audit (§17.11).
( cd agent && step "pip-audit" "$PIP_AUDIT" -r requirements.txt --progress-spinner off )

# 11. SEC-N6: dev-mode must be unreachable by default in a release build.
step "dev-default off (SEC-N6)" "$PY" scripts/security/check_dev_default.py

echo ""
if [ "$FAILED" -ne 0 ]; then
  echo "RELEASE GATE: FAILED (see --- FAIL lines above)"
  exit 1
fi

if [ "$RELEASE_MODE" -eq 1 ]; then
  if [ ! -f "docs/security/pentest-signoff.md" ]; then
    echo "RELEASE GATE (--release): FAILED — docs/security/pentest-signoff.md missing."
    echo "The manual pen-test section of docs/security/pentest-checklist.md must be"
    echo "signed off by the operator before tagging (docs/RELEASE.md gate 9)."
    exit 1
  fi
  echo "RELEASE GATE: PASS (automated gates + pentest sign-off present)"
  echo "Next: bash scripts/release_build.sh, then sign (docs/RELEASE.md 'Build & sign')."
else
  echo "RELEASE GATE: PASS (automated gates) — NOT A RELEASE RUN:"
  echo "manual pen-test sign-off is still PENDING (docs/security/pentest-checklist.md)."
  echo "Run with --release after signing off to enforce the manual gate."
fi
