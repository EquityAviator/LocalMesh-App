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


def test_tc_sec_07_artifact_scan_detects_key_in_archive(tmp_path: Path) -> None:
    """M9 (§21.6): the artifact scanner must catch a secret that exists only
    inside a BUILT artifact (not in the tracked tree) — otherwise the signed
    bytes are never scanned (scripts/release_build.sh)."""
    import zipfile

    scanner = REPO_ROOT / "scripts" / "security" / "scan_artifacts.py"
    wheel = tmp_path / "localmesh_agent-1.0.0rc1-py3-none-any.whl"
    # Synthetic fixture assembled from fragments: the scanner pattern
    # ("-----BEGIN [A-Z ]*PRIVATE KEY-----") must match the PAYLOAD, while the
    # test source itself must never contain a key-shaped literal (the TC-SEC-07
    # manifest scan scans this very file too).
    begin = "-----BEGIN " + "RSA PRIVATE" + " KEY-----"
    end = "-----END RSA PRIVATE KEY-----"
    with zipfile.ZipFile(wheel, "w") as zf:
        zf.writestr("localmesh_agent/leak.py", f"key = '{begin}\\nabc\\n{end}'\n")
    result = subprocess.run(  # noqa: S603 — fixed args, repo-internal
        [sys.executable, str(scanner), str(wheel)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=120,
    )
    assert result.returncode == 1, f"scanner missed an in-archive key:\n{result.stdout}"
    assert "pem-private-key" in result.stdout


def test_tc_sec_07_artifact_scan_passes_clean_archive(tmp_path: Path) -> None:
    """A clean wheel-shaped archive passes; an explicit target that scans
    nothing FAILS (release_build.sh must never sign an empty bundle)."""
    import zipfile

    scanner = REPO_ROOT / "scripts" / "security" / "scan_artifacts.py"
    wheel = tmp_path / "localmesh_agent-1.0.0rc1-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as zf:
        zf.writestr("localmesh_agent/__init__.py", "AGENT_VERSION = '1.0.0-rc.1'\n")
    result = subprocess.run(  # noqa: S603 — fixed args, repo-internal
        [sys.executable, str(scanner), str(wheel)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=120,
    )
    assert result.returncode == 0, f"clean artifact failed the scan:\n{result.stdout}"
    assert "Artifact scan: OK" in result.stdout

    empty = tmp_path / "empty"
    empty.mkdir()
    result = subprocess.run(  # noqa: S603 — fixed args, repo-internal
        [sys.executable, str(scanner), str(empty)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=120,
    )
    assert result.returncode == 1, "an explicit empty target must fail the gate"
