"""OpenAPI drift check (LM-ARCH-001 §21.3, NFR-MAINT-01, ADR-015).

Regenerates the OpenAPI document from code and compares it with the committed
`docs/openapi/mesh-v1.json`. CI fails on any difference.

Usage:
    python scripts/check_openapi_drift.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from export_openapi import REPO_ROOT, build_openapi  # noqa: E402

COMMITTED = REPO_ROOT / "docs" / "openapi" / "mesh-v1.json"


def diff_paths(a: Any, b: Any, prefix: str = "") -> list[str]:
    """Return JSON-pointer-ish paths where `a` (regenerated) and `b` (committed) differ."""
    if isinstance(a, dict) and isinstance(b, dict):
        out: list[str] = []
        for k in sorted(set(a) | set(b)):
            out.extend(diff_paths(a.get(k), b.get(k), f"{prefix}/{k}"))
        return out
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return [f"{prefix} (list length {len(a)} != {len(b)})"]
        out = []
        for i, (x, y) in enumerate(zip(a, b, strict=True)):
            out.extend(diff_paths(x, y, f"{prefix}/{i}"))
        return out
    return [] if a == b else [f"{prefix} (regenerated={a!r} committed={b!r})"]


def main() -> int:
    if not COMMITTED.exists():
        print(
            f"FAIL: {COMMITTED.relative_to(REPO_ROOT)} is missing. "
            "Run scripts/export_openapi.py and commit it."
        )
        return 1
    regenerated = build_openapi()
    committed = json.loads(COMMITTED.read_text(encoding="utf-8"))
    diffs = diff_paths(regenerated, committed)
    if diffs:
        print("FAIL: OpenAPI drift detected (§21.3 / NFR-MAINT-01). First differences:")
        for d in diffs[:20]:
            print(f"  {d}")
        if len(diffs) > 20:
            print(f"  ... and {len(diffs) - 20} more")
        print("Fix: run `python scripts/export_openapi.py` and commit the regenerated file.")
        return 1
    print("OpenAPI drift check: OK (committed spec matches generated output)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
