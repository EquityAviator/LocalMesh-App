"""Content-column schema scan — SEC-N3 / CON-02 gate (LM-ARCH-001 §21.4 "security gates").

Scans every SQL schema/migration in the repo for table/column identifiers that
look like they would store **Content** (prompts, completions, attachments,
documents, transcripts, retrieved passages, chat history). The Agent stores no
Content (ADR-011); the Control Plane holds Metadata only (ADR-001, CON-02).

Deny-list stems (case-insensitive, identifier prefixes/suffixes match):
    content, prompt, completion, message, attachment, transcript, passage,
    document, chunk, embedding, conversation, history

A hit is ignored when the line carries an explicit allow marker:
    -- content-scan: allow(<identifier>) <reason>
Allow markers are meant for Metadata-only columns whose *name* merely contains
a stem (e.g. a token-count column); the reviewer decides.

M0 behaviour: the only SQL in the repo is the empty `0001_init.sql` scaffold,
so the scan passes vacuously; it becomes a hard gate for WP-04 (M1) migrations
and is an M6 exit criterion for the Control Plane (§22.1 M6).

Exit codes: 0 = pass, 1 = violations found.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCAN_ROOTS = [
    REPO_ROOT / "agent" / "src" / "localmesh_agent" / "store",
    REPO_ROOT / "control-plane",
]

CONTENT_STEMS = (
    "content",
    "prompt",
    "completion",
    "message",
    "attachment",
    "transcript",
    "passage",
    "document",
    "chunk",
    "embedding",
    "conversation",
    "history",
)
STEM_RE = re.compile(
    r"(?i)\b(?:" + "|".join(re.escape(s) for s in CONTENT_STEMS) + r")[a-z0-9_]*\b"
)
ALLOW_MARKER = re.compile(r"--\s*content-scan:\s*allow\((?P<ident>[A-Za-z0-9_]+)\)")


def strip_sql_comment(line: str) -> str:
    """Remove `-- ...` comments so allow markers and prose don't false-positive."""
    return line.split("--", 1)[0]


def main() -> int:
    violations: list[str] = []
    scanned = 0
    for root in SCAN_ROOTS:
        if not root.exists():
            continue
        for sql in sorted(root.rglob("*.sql")):
            scanned += 1
            for lineno, raw in enumerate(
                sql.read_text(encoding="utf-8", errors="replace").splitlines(), 1
            ):
                marker = ALLOW_MARKER.search(raw)
                code = strip_sql_comment(raw)
                for hit in STEM_RE.findall(code):
                    if marker and marker.group("ident").lower() == hit.lower():
                        continue
                    violations.append(
                        f"{sql.relative_to(REPO_ROOT)}:{lineno}: '{hit}' looks like Content "
                        "(SEC-N3/CON-02; Agent/Control Plane must not store Content). "
                        f"If Metadata-only, add: -- content-scan: allow({hit}) <reason>"
                    )
    if violations:
        print("FAIL: possible Content columns in SQL schema:")
        for v in violations:
            print(f"  - {v}")
        return 1
    print(f"Content-column schema scan: OK ({scanned} SQL file(s) scanned)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
