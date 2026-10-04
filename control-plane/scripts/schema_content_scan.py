#!/usr/bin/env python3
"""TC-SEC-08 — Control Plane schema scan for Content columns (§17.13).

FR-CP-04: "Control Plane stores zero Content, enforced by schema and
review." The enforcement half lives here: every ``*.sql`` file under
``control-plane/`` (migrations, policies, seeds) is scanned for column
names matching the forbidden pattern from §12.2:

    /prompt|message|content|completion|attachment/i

A match fails the build. SQL comments are stripped before matching so
documentation inside a migration cannot false-positive (the review half of
FR-CP-04 is human).

Agent-side Content-at-rest is covered separately by TC-SEC-01 (canary grep
of the Agent data dir, ADR-011 stateless rule).

Usage:
    python3 control-plane/scripts/schema_content_scan.py [paths...]

    # CI style (exit 1 on violation):
    python3 control-plane/scripts/schema_content_scan.py control-plane

    # As a library (used by agent/tests/security/test_tc_sec_08_cp_schema.py):
    from schema_content_scan import scan_sql_files, ContentColumnViolation
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

FORBIDDEN_COLUMN_PATTERN = re.compile(
    r"prompt|message|content|completion|attachment", re.IGNORECASE
)

# SQL line comments + block comments are documentation, not schema (§12.2
# speaks of column names; the review half of FR-CP-04 is human).
_LINE_COMMENT = re.compile(r"--[^\n]*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
# A column definition is roughly:  <ident> <type> …  inside a CREATE TABLE
# body. We conservatively match identifier-followed-by-Postgres-type lines.
_COLUMN_DEF = re.compile(
    r"^\s*\"?([a-zA-Z_][a-zA-Z0-9_]*)\"?\s+"
    r"(?:uuid|text|bytea|timestamptz|timestamp|boolean|bool|integer|int|bigint|"
    r"smallint|numeric|decimal|real|double|jsonb|json|date|varchar|char|"
    r"character varying|character)\b",
    re.IGNORECASE | re.MULTILINE,
)


class ContentColumnViolation(Exception):
    """A forbidden Content-ish column name was found (FR-CP-04)."""

    def __init__(self, path: Path, column: str, line_no: int) -> None:
        super().__init__(
            f"{path}:{line_no}: forbidden Content column {column!r} "
            "(FR-CP-04 / TC-SEC-08, §12.2 pattern)"
        )
        self.path = path
        self.column = column
        self.line_no = line_no


def strip_sql_comments(sql_text: str) -> str:
    """Remove line and block comments (documentation is not schema)."""
    return _BLOCK_COMMENT.sub(" ", _LINE_COMMENT.sub("", sql_text))


def scan_sql_text(sql_text: str) -> list[str]:
    """Return forbidden column names in the given SQL text (comment-stripped)."""
    cleaned = strip_sql_comments(sql_text)
    return [
        match.group(1)
        for match in _COLUMN_DEF.finditer(cleaned)
        if FORBIDDEN_COLUMN_PATTERN.search(match.group(1))
    ]


def scan_sql_files(roots: list[Path]) -> list[ContentColumnViolation]:
    """Scan every ``*.sql`` file under the given roots (recursive)."""
    violations: list[ContentColumnViolation] = []
    seen: set[Path] = set()
    for root in roots:
        if root.is_file():
            candidates = [root]
        elif root.is_dir():
            candidates = sorted(root.rglob("*.sql"))
        else:
            continue
        for path in candidates:
            if path in seen:
                continue
            seen.add(path)
            text = path.read_text(encoding="utf-8")
            for column, line_no in _forbidden_with_lines(text):
                violations.append(ContentColumnViolation(path, column, line_no))
    return violations


def _forbidden_with_lines(sql_text: str) -> list[tuple[str, int]]:
    """(column, 1-based line) pairs of forbidden columns in ``sql_text``."""
    cleaned = strip_sql_comments(sql_text)
    hits: list[tuple[str, int]] = []
    for line_no, line in enumerate(cleaned.splitlines(), start=1):
        for match in _COLUMN_DEF.finditer(line):
            column = match.group(1)
            if FORBIDDEN_COLUMN_PATTERN.search(column):
                hits.append((column, line_no))
    return hits


def main(argv: list[str]) -> int:
    roots = [Path(arg) for arg in argv[1:]] or [Path(__file__).resolve().parent.parent]
    violations = scan_sql_files(roots)
    if violations:
        for violation in violations:
            print(f"TC-SEC-08 FAIL: {violation}", file=sys.stderr)
        print(
            f"TC-SEC-08: {len(violations)} forbidden Content column(s) — "
            "FR-CP-04 violated; remove them or move that data out of the CP.",
            file=sys.stderr,
        )
        return 1
    file_count = sum(
        1 for root in roots if root.is_dir() for _ in root.rglob("*.sql")
    ) + sum(1 for root in roots if root.is_file() and root.suffix == ".sql")
    print(f"TC-SEC-08 OK: no Content columns in {file_count} SQL file(s) (FR-CP-04).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
