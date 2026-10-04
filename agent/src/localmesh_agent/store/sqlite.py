"""SQLite store access, WAL mode (§10.1, §14.1).

Implements the `Store` port (§10.2) for SQLite. Metadata only: no table may
contain Content (SEC-N3, ADR-011) — the migration is gated by the schema scan
(scripts/security/scan_content_columns.py) and by unit tests here.

Design notes:
- Sync API on a single connection guarded by a lock (§10.5: blocking work runs
  in a thread pool; async callers wrap calls with `asyncio.to_thread`).
- Migrations are applied via `PRAGMA user_version`; `0001_init.sql` is the
  normative §14.1 schema and is applied verbatim.
- Retention (§14.1): audit_events ≤ 90 days / 10 000 rows (rolling); tokens
  pruned on expiry — see `Store.prune`.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from localmesh_agent.observability.logging import ALLOWED_LOG_KEYS

_MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

# (version, filename) — exactly one migration exists at M1 (§14.1).
_MIGRATIONS: tuple[tuple[int, str], ...] = ((1, "0001_init.sql"),)

# §14.1 retention policy (normative).
AUDIT_RETENTION_SECONDS = 90 * 24 * 3600  # 90 days
AUDIT_MAX_ROWS = 10_000

# §20.2 — closed vocabulary of audit events (Metadata only, never Content).
AUDIT_EVENTS: frozenset[str] = frozenset(
    {
        "pair_opened",
        "pair_claimed",
        "pair_approved",
        "pair_denied",
        "auth_ok",
        "auth_fail",
        "device_revoked",
        "chat_started",
        "chat_finished",
        "backend_down",
        "backend_up",
        "tls_rotated",
    }
)

# §14.1 — expected tables after migration 0001 (drift guard, asserted in tests).
EXPECTED_TABLES: dict[str, frozenset[str]] = {
    "agent_identity": frozenset({"id", "agent_id", "display_name", "created_at"}),
    "devices": frozenset(
        {
            "device_id",
            "name",
            "platform",
            "public_key_spki",
            "scopes",
            "created_at",
            "last_seen_at",
            "revoked_at",
        }
    ),
    "tokens": frozenset({"token_hash", "device_id", "issued_at", "expires_at"}),
    "audit_events": frozenset({"id", "ts", "device_id", "event", "meta_json"}),
    "backends": frozenset({"backend_id", "kind", "base_url", "enabled", "auth_ref"}),
    "model_cache": frozenset({"mesh_model_id", "entry_json", "refreshed_at"}),
    "settings": frozenset({"key", "value"}),
}


class StoreError(RuntimeError):
    """Raised for store misuse (unknown audit event, non-allow-listed meta key)."""


class Store:
    """SQLite store (§14.1). Metadata only; sync API; thread-safe."""

    def __init__(self, db_path: str | Path) -> None:
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._apply_migrations()

    # -- migrations ---------------------------------------------------------

    def _apply_migrations(self) -> None:
        current = int(self._conn.execute("PRAGMA user_version").fetchone()[0])
        for version, filename in _MIGRATIONS:
            if current >= version:
                continue
            script = (_MIGRATIONS_DIR / filename).read_text(encoding="utf-8")
            self._conn.executescript(script)
            self._conn.execute(f"PRAGMA user_version = {version}")
            self._conn.commit()

    # -- identity -------------------------------------------------------------

    def set_identity(self, agent_id: str, display_name: str, created_at: int) -> None:
        """Insert or replace the single identity row (§14.1 agent_identity, id=1)."""
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO agent_identity (id, agent_id, display_name, created_at) "
                "VALUES (1, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET agent_id=excluded.agent_id, "
                "display_name=excluded.display_name, created_at=excluded.created_at",
                (agent_id, display_name, created_at),
            )

    def get_identity(self) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT agent_id, display_name, created_at FROM agent_identity WHERE id = 1"
            ).fetchone()
        return dict(row) if row is not None else None

    # -- devices ---------------------------------------------------------------

    def upsert_device(
        self,
        device_id: str,
        name: str,
        platform: str,
        public_key_spki: bytes,
        scopes: str,
        created_at: int,
    ) -> None:
        """Insert a Device; on conflict refresh name/platform (key never changes)."""
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO devices (device_id, name, platform, public_key_spki, scopes, "
                "created_at) VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(device_id) DO UPDATE SET name=excluded.name, "
                "platform=excluded.platform",
                (device_id, name, platform, public_key_spki, scopes, created_at),
            )

    def get_device(self, device_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT device_id, name, platform, public_key_spki, scopes, created_at, "
                "last_seen_at, revoked_at FROM devices WHERE device_id = ?",
                (device_id,),
            ).fetchone()
        if row is None:
            return None
        device = dict(row)
        device["public_key_spki"] = bytes(device["public_key_spki"])
        return device

    def list_devices(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT device_id, name, platform, public_key_spki, scopes, created_at, "
                "last_seen_at, revoked_at FROM devices ORDER BY created_at"
            ).fetchall()
        devices: list[dict[str, Any]] = []
        for row in rows:
            device = dict(row)
            device["public_key_spki"] = bytes(device["public_key_spki"])
            devices.append(device)
        return devices

    def revoke_device(self, device_id: str, revoked_at: int) -> bool:
        """Mark a Device revoked (row kept, §14.1). Returns False if unknown."""
        with self._lock, self._conn:
            cursor = self._conn.execute(
                "UPDATE devices SET revoked_at = ? WHERE device_id = ? AND revoked_at IS NULL",
                (revoked_at, device_id),
            )
        return cursor.rowcount > 0

    def touch_device_last_seen(self, device_id: str, ts: int) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE devices SET last_seen_at = ? WHERE device_id = ?", (ts, device_id)
            )

    # -- tokens ------------------------------------------------------------------

    def put_token(self, token_hash: bytes, device_id: str, issued_at: int, expires_at: int) -> None:
        """Store SHA-256(token) only — the token itself never touches disk (§10.4)."""
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO tokens (token_hash, device_id, issued_at, expires_at) "
                "VALUES (?, ?, ?, ?)",
                (token_hash, device_id, issued_at, expires_at),
            )

    def get_token(self, token_hash: bytes) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT token_hash, device_id, issued_at, expires_at FROM tokens "
                "WHERE token_hash = ?",
                (token_hash,),
            ).fetchone()
        if row is None:
            return None
        token = dict(row)
        token["token_hash"] = bytes(token["token_hash"])
        return token

    def delete_device_tokens(self, device_id: str) -> int:
        with self._lock, self._conn:
            cursor = self._conn.execute("DELETE FROM tokens WHERE device_id = ?", (device_id,))
        return cursor.rowcount

    # -- audit ----------------------------------------------------------------

    def append_audit(
        self,
        event: str,
        device_id: str | None = None,
        meta: dict[str, Any] | None = None,
        ts: int | None = None,
    ) -> None:
        """Append a Metadata-only audit event (§14.1, §20.2).

        Deny-by-default: `event` must be in the §20.2 vocabulary and every
        `meta` key must be in the §17.10 log allow-list; anything else raises
        StoreError rather than being written.
        """
        if event not in AUDIT_EVENTS:
            raise StoreError(f"audit event not in §20.2 vocabulary: {event!r}")
        meta_json: str | None = None
        if meta is not None:
            unknown = sorted(set(meta) - ALLOWED_LOG_KEYS)
            if unknown:
                raise StoreError(f"audit meta keys outside §17.10 allow-list: {unknown}")
            meta_json = json.dumps(meta, separators=(",", ":"), default=str)
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO audit_events (ts, device_id, event, meta_json) VALUES (?, ?, ?, ?)",
                (ts if ts is not None else int(time.time()), device_id, event, meta_json),
            )

    def list_audit(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, ts, device_id, event, meta_json FROM audit_events "
                "ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    # -- settings ----------------------------------------------------------------

    def set_setting(self, key: str, value: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def get_setting(self, key: str) -> str | None:
        with self._lock:
            row = self._conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return str(row["value"]) if row is not None else None

    # -- model cache (CapabilityRegistry snapshot, §16.3) --------------------------

    def replace_model_cache(self, entries: list[tuple[str, str]], refreshed_at: int) -> None:
        """Atomically replace the snapshot: (mesh_model_id, entry_json) pairs."""
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM model_cache")
            self._conn.executemany(
                "INSERT INTO model_cache (mesh_model_id, entry_json, refreshed_at) "
                "VALUES (?, ?, ?)",
                [(mesh_id, entry_json, refreshed_at) for mesh_id, entry_json in entries],
            )

    def get_model_cache(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT mesh_model_id, entry_json, refreshed_at FROM model_cache"
            ).fetchall()
        return {
            str(row["mesh_model_id"]): {
                "entry_json": str(row["entry_json"]),
                "refreshed_at": int(row["refreshed_at"]),
            }
            for row in rows
        }

    # -- retention (§14.1) -------------------------------------------------------

    def prune(self, now: int) -> dict[str, int]:
        """Apply §14.1 retention: audit ≤ 90 d / 10 000 rows rolling; tokens on expiry."""
        removed = {"audit_expired": 0, "audit_overflow": 0, "tokens_expired": 0}
        with self._lock, self._conn:
            cursor = self._conn.execute(
                "DELETE FROM audit_events WHERE ts < ?", (now - AUDIT_RETENTION_SECONDS,)
            )
            removed["audit_expired"] = cursor.rowcount
            cursor = self._conn.execute(
                "DELETE FROM audit_events WHERE id NOT IN ("
                "SELECT id FROM audit_events ORDER BY id DESC LIMIT ?)",
                (AUDIT_MAX_ROWS,),
            )
            removed["audit_overflow"] = cursor.rowcount
            cursor = self._conn.execute("DELETE FROM tokens WHERE expires_at < ?", (now,))
            removed["tokens_expired"] = cursor.rowcount
        return removed

    def close(self) -> None:
        with self._lock:
            self._conn.close()
