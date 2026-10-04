"""DeviceRepository use-cases, revoke (§10.1).

Implements the WP-08 DeviceService (M2) per §22.2, context §10.4
("DeviceService — CRUD, revoke → also Scheduler.cancel_by_device()"),
§14.1 (devices/tokens schema), §15.6 (revocation sequence), FR-PAIR-06
("revocation takes effect ≤ 5 s including aborting that Device's active
streams").

Revocation fan-out (§15.6, in order):
  1. delete the Device's token hashes  (next Bearer → uniform 401),
  2. mark `devices.revoked_at`         (row kept, §14.1),
  3. `Scheduler.cancel_by_device()`    (active streams abort ≤ 1 s upstream),
  4. audit `device_revoked` (§20.2).

For the ≤ 5 s stream kill (FR-PAIR-06) the running SSE loop additionally
checks `is_live_revoked()` every chunk: an in-memory set loaded from the
store at startup and updated here, so the check is O(1) and DB-free.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from localmesh_agent.adapters.ports import Store
from localmesh_agent.core.entities import new_uuid7
from localmesh_agent.security import crypto

# §13.1/§13.2: default scopes granted at pairing approval.
DEFAULT_DEVICE_SCOPES = ("models:read", "chat")


class DeviceService:
    """Device use-cases (§10.4); the revoke hook wires the Scheduler."""

    def __init__(self, store: Store, on_revoke: Callable[[str], int] | None = None) -> None:
        """`on_revoke` is called with the device_id after a successful revoke
        (the app factory passes `Scheduler.cancel_by_device`, §10.4)."""
        self._store = store
        self._on_revoke = on_revoke
        self._lock = threading.Lock()
        self._live_revoked: set[str] = {
            str(row["device_id"])
            for row in store.list_devices()
            if row.get("revoked_at") is not None
        }

    def create(self, name: str, platform: str, public_key_spki: bytes) -> str:
        """Persist an approved Device (§14.1 devices row); returns device_id."""
        device_id = f"dv_{new_uuid7()}"  # §14.3 canonical identifier
        scopes = " ".join(DEFAULT_DEVICE_SCOPES)
        created_at = int(__import__("time").time())
        with self._lock:
            self._store.upsert_device(
                device_id=device_id,
                name=name,
                platform=platform,
                public_key_spki=public_key_spki,
                scopes=scopes,
                created_at=created_at,
            )
            self._live_revoked.discard(device_id)
        return device_id

    def get(self, device_id: str) -> dict[str, object] | None:
        with self._lock:
            device = self._store.get_device(device_id)
        return dict(device) if device is not None else None

    def list(self) -> list[dict[str, object]]:
        with self._lock:
            devices = self._store.list_devices()
        return [dict(device) for device in devices]

    def revoke(self, device_id: str) -> tuple[bool, int]:
        """Revoke a Device (§15.6). Returns (revoked?, cancelled_requests).

        Unknown devices return (False, 0) — the admin API surfaces that as a
        404 without inventing a new error code (Appendix D has no
        DEVICE_NOT_FOUND; FastAPI's plain 404 with the §13.4 envelope).
        """
        now = int(__import__("time").time())
        with self._lock:
            # 1. Kill every outstanding token first (ADR-008 instant revocation).
            self._store.delete_device_tokens(device_id)
            revoked = self._store.revoke_device(device_id, revoked_at=now)
            if not revoked:
                return False, 0
            self._live_revoked.add(device_id)
        # 2. Abort this Device's active generations (§10.4, FR-PAIR-06).
        cancelled = 0
        if self._on_revoke is not None:
            cancelled = int(self._on_revoke(device_id))
        # 3. Audit AFTER the side effects are ordered (§20.2).
        self._store.append_audit("device_revoked", device_id=device_id)
        return True, cancelled

    def is_live_revoked(self, device_id: str) -> bool:
        """O(1) revocation check for running SSE loops (FR-PAIR-06 ≤ 5 s)."""
        with self._lock:
            return device_id in self._live_revoked

    def touch_last_seen(self, device_id: str) -> None:
        """Record a successful authentication (§14.1 devices.last_seen_at)."""
        self._store.touch_device_last_seen(device_id, int(__import__("time").time()))


def verify_device_key(spki_der: bytes) -> bool:
    """Defensive shape check used by the pairing flow (P-256 only, ADR-008).

    Full signature verification lives in `security.crypto`; this keeps a
    malformed SPKI out of the store before approval.
    """
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec

        key = serialization.load_der_public_key(spki_der)
        return isinstance(key, ec.EllipticCurvePublicKey) and isinstance(key.curve, ec.SECP256R1)
    except Exception:  # noqa: BLE001 - any malformed input is just "not a key"
        return False


def constant_time_token_eq(presented_hash: bytes, stored_hash: bytes) -> bool:
    """Re-exported comparator so callers never reach for `==` (§17.3)."""
    return crypto.constant_time_eq(presented_hash, stored_hash)
