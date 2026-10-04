#!/usr/bin/env bash
# Release build — wheel + sdist + checksums + artifact scan (M9, §21.6).
#
# Usage (from the repo root):  bash scripts/release_build.sh
#
# Produces agent/dist/<artifacts> and agent/dist/SHA256SUMS, then runs the
# TC-SEC-07 artifact scan (scripts/security/scan_artifacts.py) over the exact
# bytes that will be signed. SIGNING IS A MANUAL STEP (docs/RELEASE.md):
# the key lives OUTSIDE the repository (hardware token or encrypted keyring)
# and is therefore never available to CI or to this script by design.

set -euo pipefail
cd "$(dirname "$0")/.."

DIST="agent/dist"
mkdir -p "$DIST"
rm -f "$DIST"/*.whl "$DIST"/*.tar.gz "$DIST"/SHA256SUMS 2>/dev/null || true

echo "=== build: wheel + sdist (PEP 517, ADR-017 setuptools backend) ==="
if command -v uv >/dev/null 2>&1; then
  ( cd agent && uv build --out-dir dist )
else
  ( cd agent && python3 -m build --outdir dist )
fi
ls -la "$DIST"

echo ""
echo "=== checksums: SHA256SUMS ==="
( cd "$DIST" && sha256sum -- *.whl *.tar.gz > SHA256SUMS )
cat "$DIST/SHA256SUMS"

echo ""
echo "=== TC-SEC-07: artifact scan over the exact release bytes ==="
if [ -x "agent/.venv/bin/python" ]; then
  PY=agent/.venv/bin/python
else
  PY=python3
fi
"$PY" scripts/security/scan_artifacts.py "$DIST"

echo ""
echo "Build complete. Manual next steps (docs/RELEASE.md 'Build & sign'):"
echo "  1. Verify docs/security/pentest-signoff.md exists (release_gate.sh --release)."
echo "  2. Sign OUTSIDE the repo with the release key:"
echo "       minisign -Sm agent/dist/SHA256SUMS"
echo "  3. Publish agent/dist/* + SHA256SUMS + SHA256SUMS.minisig + the public key."
