"""TC-SEC-08 — schema scan for Content columns, Control Plane (§17.13).

FR-CP-04: "Control Plane stores zero Content, enforced by schema and
review." The scanner lives in `control-plane/scripts/schema_content_scan.py`;
this test pins that it (a) passes the shipped §12.2 migration verbatim,
(b) FAILS on any Content-ish column, (c) ignores SQL comments, and (d) is
wired to the real repo layout (a deleted scanner or moved migration fails
here).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CP_DIR = REPO_ROOT / "control-plane"
SCANNER_PATH = CP_DIR / "scripts" / "schema_content_scan.py"


def _load_scanner() -> object:
    spec = importlib.util.spec_from_file_location("schema_content_scan", SCANNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["schema_content_scan"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def scanner() -> object:
    if not SCANNER_PATH.exists():
        pytest.fail("TC-SEC-08 scanner missing from control-plane/scripts/")
    return _load_scanner()


def test_shipped_control_plane_schema_has_no_content_columns(scanner: object) -> None:
    """The §12.2 verbatim migration must pass the FR-CP-04 pattern."""
    scan_sql_files = scanner.scan_sql_files  # type: ignore[attr-defined]
    violations = scan_sql_files([CP_DIR / "migrations"])
    assert violations == []
    # Guard against a silently-empty scan (deleted/renamed migration).
    migrations = list((CP_DIR / "migrations").rglob("*.sql"))
    assert migrations, "control-plane/migrations must exist for TC-SEC-08"


def test_forbidden_columns_are_detected(scanner: object, tmp_path: Path) -> None:
    scan_sql_text = scanner.scan_sql_text  # type: ignore[attr-defined]
    for column_type in (
        "prompt text",
        "messages jsonb",
        "content bytea",
        "completion_text text",
        "attachment_name text",
    ):
        sql = f"create table evil (\n  id uuid,\n  {column_type}\n);\n"
        assert scan_sql_text(sql), f"missed forbidden column: {column_type}"


def test_comments_do_not_trigger_false_positives(scanner: object) -> None:
    scan_sql_text = scanner.scan_sql_text  # type: ignore[attr-defined]
    sql = (
        "-- the prompt column lives elsewhere (comment)\n"
        "/* content completion attachment (block comment) */\n"
        "create table devices (\n"
        "  id uuid primary key,\n"
        "  user_id uuid not null,\n"
        "  name text not null,\n"
        "  public_key bytea not null\n"
        ");\n"
    )
    assert scan_sql_text(sql) == []


def test_non_column_identifiers_are_not_flagged(scanner: object) -> None:
    scan_sql_text = scanner.scan_sql_text  # type: ignore[attr-defined]
    sql = (
        "insert into audit (event) values ('message_sent');\n"
        "select content_type from pg_type;  -- identifier, not a column def\n"
    )
    assert scan_sql_text(sql) == []


def test_scanner_cli_exit_codes(scanner: object, tmp_path: Path) -> None:
    main = scanner.main  # type: ignore[attr-defined]
    assert main(["schema_content_scan.py", str(CP_DIR / "migrations")]) == 0
    bad = tmp_path / "bad.sql"
    bad.write_text("create t (\n  messages text\n);", encoding="utf-8")
    assert main(["schema_content_scan.py", str(bad)]) == 1


def test_agent_store_migrations_stay_out_of_cp_pattern_scope(scanner: object) -> None:
    """§17.13 scopes TC-SEC-08 to the Control Plane; the Agent store's own
    Content-at-rest guarantee is TC-SEC-01 (canary). This test documents the
    boundary: the scanner only walks what it is pointed at."""
    scan_sql_files = scanner.scan_sql_files  # type: ignore[attr-defined]
    violations = scan_sql_files([CP_DIR / "migrations"])
    assert violations == []
