"""SEC-N1 gate — Android manifest / network-config cleartext scan (LM-ARCH-001 §21.4, §17.9).

M0 behaviour (VACUOUS PASS): the monorepo has no Android project yet
(`apps/mobile/` is a placeholder), so this gate reports a vacuous pass with an
explicit notice. The moment any `AndroidManifest.xml` appears in the repo, the
scan becomes active and fails on:

  - `android:usesCleartextTraffic="true"` in any manifest; or
  - `cleartextTrafficPermitted="true"` in any network security config XML
    referenced by a manifest (`android:networkSecurityConfig`).

The §17.9 debug-only exception (cleartext to `10.0.2.2`/`127.0.0.1` via a
*debug-only* network_security_config) is enforced release-vs-debug from WP-09
(M2) onwards; until then ANY cleartext permission is a violation.

Exit codes: 0 = pass (or vacuous pass), 1 = violations found.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SKIP_DIRS = {".git", "node_modules", ".venv", "build", ".gradle", "__pycache__"}

CLEARNETWORK_ATTR = re.compile(
    r'android:usesCleartextTraffic\s*=\s*"true"', re.IGNORECASE
)
NSC_REFERENCE = re.compile(
    r'android:networkSecurityConfig\s*=\s*"@xml/([A-Za-z0-9_.]+)"'
)
NSC_CLEARNETWORK = re.compile(r'cleartextTrafficPermitted\s*=\s*"true"', re.IGNORECASE)


def iter_manifests() -> list[Path]:
    return [
        p
        for p in sorted(REPO_ROOT.rglob("AndroidManifest.xml"))
        if not any(part in SKIP_DIRS for part in p.parts)
    ]


def find_nsc_files(name: str) -> list[Path]:
    return [
        p
        for p in sorted((REPO_ROOT / "apps").rglob(f"{name}.xml"))
        if p.is_file() and "xml" in p.parts
    ]


def main() -> int:
    manifests = iter_manifests()
    if not manifests:
        print(
            "VACUOUS PASS: no AndroidManifest.xml found yet (apps/mobile is an M0 placeholder). "
            "This gate activates automatically when the Android project lands (§21.4, SEC-N1)."
        )
        return 0

    violations: list[str] = []
    for manifest in manifests:
        rel = manifest.relative_to(REPO_ROOT)
        text = manifest.read_text(encoding="utf-8", errors="replace")
        if CLEARNETWORK_ATTR.search(text):
            violations.append(
                f'{rel}: android:usesCleartextTraffic="true" (SEC-N1, §17.9)'
            )
        for nsc_name in NSC_REFERENCE.findall(text):
            for nsc in find_nsc_files(nsc_name):
                nsc_text = nsc.read_text(encoding="utf-8", errors="replace")
                if NSC_CLEARNETWORK.search(nsc_text):
                    violations.append(
                        f'{nsc.relative_to(REPO_ROOT)}: cleartextTrafficPermitted="true" '
                        f"(referenced by {rel}) (SEC-N1, §17.9)"
                    )

    if violations:
        print(
            "FAIL: cleartext permission found (SEC-N1; outside §17.9 debug-only scope):"
        )
        for v in violations:
            print(f"  - {v}")
        return 1

    print(
        f"Cleartext manifest scan: OK ({len(manifests)} manifest(s) scanned, no cleartext)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
