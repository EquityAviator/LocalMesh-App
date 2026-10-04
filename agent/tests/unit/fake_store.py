"""Shared in-memory Store port double for unit tests (§10.1 layering).

The security services type against `adapters.ports.Store`; these tests use
this fake instead of SQLite so unit tests stay fast and IO-free.
"""

from __future__ import annotations

import time
from typing import Any


class FakeStore:
    """Full `adapters.ports.Store` double (devices, tokens, audit, cache)."""

    def __init__(self) -> None:
        self.devices: dict[str, dict[str, Any]] = {}
        self.tokens: dict[bytes, dict[str, Any]] = {}
        self.audit: list[tuple[str, str | None, dict[str, Any] | None]] = []
        self.model_cache: dict[str, dict[str, Any]] = {}

    # -- devices -----------------------------------------------------------------

    def upsert_device(
        self,
        device_id: str,
        name: str,
        platform: str,
        public_key_spki: bytes,
        scopes: str,
        created_at: int,
    ) -> None:
        self.devices[device_id] = {
            "device_id": device_id,
            "name": name,
            "platform": platform,
            "public_key_spki": public_key_spki,
            "scopes": scopes,
            "created_at": created_at,
            "last_seen_at": None,
            "revoked_at": None,
        }

    def get_device(self, device_id: str) -> dict[str, Any] | None:
        return self.devices.get(device_id)

    def list_devices(self) -> list[dict[str, Any]]:
        return list(self.devices.values())

    def revoke_device(self, device_id: str, revoked_at: int) -> bool:
        device = self.devices.get(device_id)
        if device is None or device["revoked_at"] is not None:
            return False
        device["revoked_at"] = revoked_at
        return True

    def touch_device_last_seen(self, device_id: str, ts: int) -> None:
        if device_id in self.devices:
            self.devices[device_id]["last_seen_at"] = ts

    # -- tokens --------------------------------------------------------------------

    def put_token(self, token_hash: bytes, device_id: str, issued_at: int, expires_at: int) -> None:
        self.tokens[token_hash] = {
            "token_hash": token_hash,
            "device_id": device_id,
            "issued_at": issued_at,
            "expires_at": expires_at,
        }

    def get_token(self, token_hash: bytes) -> dict[str, Any] | None:
        return self.tokens.get(token_hash)

    def delete_device_tokens(self, device_id: str) -> int:
        hashes = [h for h, t in self.tokens.items() if t["device_id"] == device_id]
        for h in hashes:
            del self.tokens[h]
        return len(hashes)

    # -- audit ---------------------------------------------------------------------

    def append_audit(
        self,
        event: str,
        device_id: str | None = None,
        meta: dict[str, Any] | None = None,
        ts: int | None = None,
    ) -> None:
        self.audit.append((event, device_id, meta))

    # -- model cache -----------------------------------------------------------------

    def replace_model_cache(self, entries: list[tuple[str, str]], refreshed_at: int) -> None:
        self.model_cache = {
            mesh_id: {"entry": json, "refreshed_at": refreshed_at} for mesh_id, json in entries
        }

    def get_model_cache(self) -> dict[str, dict[str, Any]]:
        return self.model_cache


class FakeClock:
    """Injectable clock (§10.2)."""

    def __init__(self, now: int = 1_700_000_000) -> None:
        self.now = now

    def now_wall(self) -> int:
        return self.now

    def advance(self, seconds: int) -> None:
        self.now += seconds

    def now_monotonic(self) -> float:
        return time.monotonic()
