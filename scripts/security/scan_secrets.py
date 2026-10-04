"""Secret scan — supply-chain / SEC-N5 gate (LM-ARCH-001 §21.4 "security gates", §17.11).

Heuristic scan of all tracked text files for obviously-committed secrets:
  - PEM private key blocks (BEGIN ... PRIVATE KEY)
  - AWS access key id shape (AKIA + 16 chars)
  - long random-looking assignments to secret-ish variable names
    (secret|token|password|passwd|api_key followed by a 32+ char literal)

This is a tripwire, not a full secret scanner; a dedicated scanner (e.g. gitleaks)
may replace it via an ADR later. Exclusions: `.git`, `node_modules`, `.venv`,
generated OpenAPI, this `scripts/security/` directory itself (the gate
definitions contain the patterns). A line carrying
`# secrets-scan: allow(<pattern-id>) <reason>` is skipped for that pattern id.

Exit codes: 0 = pass, 1 = violations found.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SKIP_PARTS = {
    ".git",
    "node_modules",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}
SKIP_PREFIXES = (
    REPO_ROOT / "scripts" / "security",  # gate definitions contain the patterns themselves
    REPO_ROOT / "docs" / "openapi",  # generated artifact
)

PAT_PEM = "pem-private-key"
PAT_AWS = "aws-access-key-id"
PAT_ASSIGN = "secret-assignment"

PATTERNS: dict[str, re.Pattern[str]] = {
    PAT_PEM: re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    PAT_AWS: re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    PAT_ASSIGN: re.compile(
        r"(?i)\b(secret|token|password|passwd|api_?key)\b\s*[:=]\s*[\"'][A-Za-z0-9+/=_\-]{32,}[\"']"
    ),
}


def main() -> int:
    violations: list[str] = []
    scanned = 0
    for path in sorted(REPO_ROOT.rglob("*")):
        if not path.is_file():
            continue
        parts = set(path.parts)
        if parts & SKIP_PARTS:
            continue
        rel = path.relative_to(REPO_ROOT)
        if any(
            str(rel).startswith(str(p.relative_to(REPO_ROOT))) or path == p for p in SKIP_PREFIXES
        ):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, PermissionError):
            continue  # binary or unreadable: skip
        scanned += 1
        for lineno, line in enumerate(text.splitlines(), 1):
            for pat_id, pattern in PATTERNS.items():
                if pattern.search(line):
                    m = re.search(rf"secrets-scan:\s*allow\({pat_id}\)", line)
                    if m:
                        continue
                    violations.append(f"{rel}:{lineno}: matches {pat_id}")
    if violations:
        print("FAIL: potential committed secrets:")
        for v in violations:
            print(f"  - {v}")
        print("False positive? Add a comment: # secrets-scan: allow(<pattern-id>) <reason>")
        return 1
    print(f"Secret scan: OK ({scanned} file(s) scanned)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
