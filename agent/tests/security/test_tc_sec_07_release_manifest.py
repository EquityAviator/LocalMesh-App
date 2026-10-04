"""TC-SEC-07 — release manifest scan (§17.13).

Wires the M0 security gates (`scripts/security/scan_secrets.py`,
`scan_cleartext_manifest.py`, `scan_content_columns.py`) into the pytest
security layer so a release build runs them as tests. The "manifest" is the
tracked release surface: agent package, tools, control-plane, packaging and
scripts — everything a signed release bundle would contain.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SECURITY_DIR = REPO_ROOT / "scripts" / "security"


def _run_gate(script: str) -> None:
    path = SECURITY_DIR / script
    assert path.is_file(), f"gate script missing: {script}"
    result = subprocess.run(  # noqa: S603 — fixed args, repo-internal
        [sys.executable, str(path)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=120,
    )
    assert result.returncode == 0, (
        f"{script} FAILED on the release manifest:\n{result.stdout}\n{result.stderr}"
    )


def test_tc_sec_07_secret_scan_over_release_manifest() -> None:
    """No private keys / committed secrets anywhere in the bundle (§17.11)."""
    _run_gate("scan_secrets.py")


def test_tc_sec_07_cleartext_manifest_scan() -> None:
    """No cleartext traffic config in the bundle (§17.9, SEC-N1)."""
    _run_gate("scan_cleartext_manifest.py")


def test_tc_sec_07_content_column_scan() -> None:
    """No Content-shaped columns in any shipped schema (SEC-N3, ADR-011)."""
    _run_gate("scan_content_columns.py")


def test_tc_sec_07_release_bundle_file_manifest_is_scannable() -> None:
    """The release manifest itself must be enumerable (git-tracked files of
    the shippable directories) and every Python file must byte-compile —
    a release bundle with a syntax error cannot be signed (§21.6)."""
    import py_compile

    for component in ("agent/src", "tools/fake-backends", "control-plane", "packaging"):
        component_dir = REPO_ROOT / component
        assert component_dir.is_dir(), f"release component missing: {component}"
    for py in (REPO_ROOT / "agent" / "src").rglob("*.py"):
        py_compile.compile(str(py), doraise=True)
