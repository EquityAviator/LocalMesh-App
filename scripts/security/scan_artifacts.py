"""Artifact scan — TC-SEC-07 extension for the M9 release bundle (§17.13, §21.6).

`scan_secrets.py` scans the TRACKED release surface (the repo). This gate
scans the BUILT release artifacts (wheel / sdist) with the SAME heuristic
patterns, so a secret that sneaks into the source tree only at build time
(e.g. a plugin writing a key into a packaged file) cannot reach a signed
release either. The signing step (docs/RELEASE.md) is only honest if the
exact bytes being signed were scanned.

Usage:
    python scripts/security/scan_artifacts.py [PATH ...]

PATH may be a directory (scanned recursively for *.whl / *.tar.gz /
*.zip — archives are extracted to a temp dir) or a single archive /
text file. Default: agent/dist.

Exit codes: 0 = pass, 1 = violations (or nothing scanned in non-empty dist).
"""

from __future__ import annotations

import re
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scan_secrets import PATTERNS  # noqa: E402 — same tripwire, same definitions

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TARGET = REPO_ROOT / "agent" / "dist"

ARCHIVE_SUFFIXES = {".whl", ".zip", ".tar.gz", ".tgz", ".tar"}


def _iter_text_files(root: Path) -> list[Path]:
    """All files under an extracted tree, text-decodable ones get scanned."""
    return sorted(p for p in root.rglob("*") if p.is_file())


def _extract(archive: Path, dest: Path) -> None:
    """Extract one archive with stdlib readers (no shell, bounded members)."""
    name = archive.name.lower()
    if name.endswith((".whl", ".zip")):
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(dest)  # noqa: S202 — trusted local build output, temp dir
    elif name.endswith((".tar.gz", ".tgz", ".tar")):
        with tarfile.open(archive) as tf:
            # filter="data": refuses absolute paths/traversal; silences the
            # Python 3.14 default-change DeprecationWarning.
            tf.extractall(dest, filter="data")  # trusted local build output
    else:
        raise ValueError(f"unsupported archive type: {archive.name}")


def scan_path(target: Path, violations: list[str]) -> int:
    """Scan one artifact (archive or file). Returns number of files scanned."""
    scanned = 0
    if target.is_dir():
        for child in sorted(target.rglob("*")):
            if child.is_file():
                scanned += scan_path(child, violations)
        return scanned
    if not target.is_file():
        print(f"WARN: artifact missing: {target}")
        return 0

    name = target.name.lower()
    if any(name.endswith(suf) for suf in ARCHIVE_SUFFIXES):
        with tempfile.TemporaryDirectory(prefix="lm-artifact-scan-") as tmp:
            extracted = Path(tmp) / "x"
            extracted.mkdir()
            _extract(target, extracted)
            for path in _iter_text_files(extracted):
                scanned += 1
                _scan_file(path, f"{target.name}!/{path.relative_to(extracted)}", violations)
    else:
        scanned += 1
        _scan_file(target, str(target), violations)
    return scanned


def _scan_file(path: Path, label: str, violations: list[str]) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, PermissionError):
        return  # binary or unreadable: not scannable by a text tripwire
    for lineno, line in enumerate(text.splitlines(), 1):
        for pat_id, pattern in PATTERNS.items():
            if pattern.search(line):
                if re.search(rf"secrets-scan:\s*allow\({pat_id}\)", line):
                    continue
                violations.append(f"{label}:{lineno}: matches {pat_id}")


def main(argv: list[str]) -> int:
    explicit = [Path(a) for a in argv[1:]]
    targets = explicit or [DEFAULT_TARGET]
    violations: list[str] = []
    scanned = 0
    for target in targets:
        scanned += scan_path(target, violations)
    if violations:
        print("FAIL: potential secrets inside release artifacts:")
        for v in violations:
            print(f"  - {v}")
        return 1
    if scanned == 0:
        if explicit:
            print("FAIL: explicit artifact target(s) scanned nothing.")
            return 1
        print(
            "Artifact scan: SKIPPED (no built artifacts yet — run "
            "scripts/release_build.sh before signing; the release-gate build "
            "step re-runs this scan on the fresh bundle)."
        )
        return 0
    print(f"Artifact scan: OK ({scanned} file(s) scanned across {len(targets)} target(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
