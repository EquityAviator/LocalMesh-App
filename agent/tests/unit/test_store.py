"""WP-04 unit tests — SQLite store + §14.1 migration (WP-04).

Covers: migration application and drift guard, WAL, identity, devices, tokens,
audit (deny-by-default vocabulary + meta allow-list), settings, model cache,
and §14.1 retention.
"""

import json
import sqlite3
import time
from pathlib import Path

import pytest

from localmesh_agent.store.sqlite import (
    AUDIT_MAX_ROWS,
    AUDIT_RETENTION_SECONDS,
    EXPECTED_TABLES,
    Store,
    StoreError,
)


@pytest.fixture()
def store(tmp_path: Path) -> Store:
    s = Store(tmp_path / "agent.db")
    yield s
    s.close()


def test_migration_applies_schema_verbatim(store: Store) -> None:
    """§14.1 tables/columns exist exactly as specified (drift guard)."""
    conn: sqlite3.Connection = store._conn  # noqa: SLF001 — white-box drift check
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    assert tables == set(EXPECTED_TABLES)
    for table, expected_columns in EXPECTED_TABLES.items():
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        assert columns == expected_columns, f"{table} columns diverge from §14.1"


def test_wal_mode(store: Store, tmp_path: Path) -> None:
    mode = store._conn.execute("PRAGMA journal_mode").fetchone()[0]  # noqa: SLF001
    assert str(mode).lower() == "wal"


def test_migration_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "agent.db"
    first = Store(db_path)
    first.close()
    second = Store(db_path)  # re-open: user_version=1, no re-apply
    assert second.get_identity() is None
    second.close()


def test_identity_roundtrip(store: Store) -> None:
    assert store.get_identity() is None
    store.set_identity("ag_0192f0c1-0000-7000-8000-000000000000", "My PC", 1_760_000_000)
    identity = store.get_identity()
    assert identity is not None
    assert identity["agent_id"].startswith("ag_")
    assert identity["display_name"] == "My PC"
    store.set_identity("ag_replaced", "Renamed", 1_760_000_001)
    assert store.get_identity() is not None
    assert store.get_identity()["agent_id"] == "ag_replaced"  # type: ignore[index]


def test_device_lifecycle(store: Store) -> None:
    store.upsert_device(
        "dv_0192f0c1-0000-7000-8000-000000000000",
        "Pixel 8",
        "android",
        b"\x30\x59\x30\x13",  # placeholder DER bytes (real keys arrive with WP-08)
        "models:read chat",
        1_760_000_000,
    )
    device = store.get_device("dv_0192f0c1-0000-7000-8000-000000000000")
    assert device is not None
    assert device["name"] == "Pixel 8"
    assert device["public_key_spki"] == b"\x30\x59\x30\x13"
    assert device["revoked_at"] is None

    store.touch_device_last_seen("dv_0192f0c1-0000-7000-8000-000000000000", 1_760_000_050)
    assert (
        store.get_device("dv_0192f0c1-0000-7000-8000-000000000000")["last_seen_at"] == 1_760_000_050
    )  # type: ignore[index]

    assert store.revoke_device("dv_0192f0c1-0000-7000-8000-000000000000", 1_760_000_100)
    revoked = store.get_device("dv_0192f0c1-0000-7000-8000-000000000000")
    assert revoked is not None and revoked["revoked_at"] == 1_760_000_100
    # Row is kept after revocation (§14.1); revoke is idempotent via NULL check.
    assert not store.revoke_device("dv_0192f0c1-0000-7000-8000-000000000000", 1_760_000_101)
    assert store.get_device("dv_unknown") is None
    assert store.list_devices()[0]["platform"] == "android"


def test_token_hash_only(store: Store) -> None:
    """Only SHA-256(token) is stored — never the token (§10.4, §14.1)."""
    store.upsert_device("dv_1", "Dev", "android", b"k", "models:read chat", 1_760_000_000)
    token_hash = bytes(range(32))
    store.put_token(token_hash, "dv_1", issued_at=1_760_000_000, expires_at=1_760_000_900)
    row = store.get_token(token_hash)
    assert row is not None and row["device_id"] == "dv_1"
    assert store.get_token(b"\x00" * 32) is None
    assert store.delete_device_tokens("dv_1") == 1
    assert store.get_token(token_hash) is None


def test_audit_vocabulary_is_closed(store: Store) -> None:
    """§20.2: only listed events; deny-by-default on anything else."""
    store.append_audit("chat_started", device_id="dv_1", meta={"backend_id": "lmstudio"})
    events = store.list_audit()
    assert events[0]["event"] == "chat_started"
    with pytest.raises(StoreError):
        store.append_audit("made_up_event")
    with pytest.raises(StoreError):
        # meta keys are limited to the §17.10 allow-list (§20.2)
        store.append_audit("chat_started", meta={"prompt": "canary-content"})


def test_audit_meta_allow_list_enforced(store: Store) -> None:
    store.append_audit("chat_finished", meta={"tokens_out": 10, "duration_ms": 55})
    row = store.list_audit(1)[0]
    assert json.loads(row["meta_json"]) == {"tokens_out": 10, "duration_ms": 55}


def test_settings_roundtrip(store: Store) -> None:
    assert store.get_setting("missing") is None
    store.set_setting("k", "v1")
    store.set_setting("k", "v2")  # upsert
    assert store.get_setting("k") == "v2"


def test_model_cache_replace_snapshot(store: Store) -> None:
    store.replace_model_cache(
        [("lmstudio::a", json.dumps({"mesh_model_id": "lmstudio::a"})), ("ollama::b", "{}")],
        refreshed_at=1_760_000_000,
    )
    cache = store.get_model_cache()
    assert set(cache) == {"lmstudio::a", "ollama::b"}
    store.replace_model_cache([("lmstudio::a", "{}")], refreshed_at=1_760_000_001)
    assert set(store.get_model_cache()) == {"lmstudio::a"}  # stale snapshot removed


def test_prune_retention_policy(store: Store, tmp_path: Path) -> None:
    """§14.1: audit ≤ 90 days / 10 000 rows rolling; tokens pruned on expiry."""
    now = int(time.time())
    # expired audit event
    store.append_audit("auth_ok", ts=now - AUDIT_RETENTION_SECONDS - 10)
    # fresh event
    store.append_audit("auth_ok", ts=now)
    # expired token
    store.upsert_device("dv_1", "Dev", "android", b"k", "models:read chat", now)
    store.put_token(b"\x01" * 32, "dv_1", issued_at=now - 10, expires_at=now - 1)
    removed = store.prune(now)
    assert removed["audit_expired"] == 1
    assert removed["tokens_expired"] == 1
    remaining = store.list_audit()
    assert [row["event"] for row in remaining] == ["auth_ok"]

    # rolling overflow beyond AUDIT_MAX_ROWS (10001 fresh earlier + 10050 now
    # = 10051 rows kept-side -> 51 overflow beyond the 10 000 cap)
    for _ in range(AUDIT_MAX_ROWS + 50):
        store.append_audit("auth_ok", ts=now)
    removed = store.prune(now + 1)
    assert removed["audit_overflow"] == 51
    assert len(store.list_audit(limit=AUDIT_MAX_ROWS + 10)) == AUDIT_MAX_ROWS
