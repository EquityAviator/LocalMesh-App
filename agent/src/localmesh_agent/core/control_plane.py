"""Control Plane service (M6, §12) — Metadata-only account sync.

FR-CP-01..04 with the §12.1 fences:

- The CP is **not in the content path** (ADR-001): this service moves ids,
  names, public keys and timestamps — never prompts, outputs or files.
- The Agent **remains authoritative** for authorization and revocation
  (§12.1 "Does NOT: Replace local revocation"); the CP mirror only lets the
  owner's other devices *notice* a revocation (FR-CP-03).
- Failure mode (§12.3): if the CP is unreachable, chat/pairing continue with
  local data and the status surface reports "offline". Nothing here may
  block or degrade the Agent's core duties.

Layer position: `core` (§10.1). Depends on the `ControlPlaneClient` port and
the `Clock` port only — never on httpx or the concrete store. Registration
persistence and device-key lookup are injected as callables from the app
factory, so this module stays free of `store/` (import-linter contract).
"""

from __future__ import annotations

import asyncio
import enum
import json
from collections.abc import Callable
from typing import Any

from localmesh_agent.adapters.ports import Clock, ControlPlaneClient
from localmesh_agent.observability.logging import get_logger

log = get_logger("controlplane")

REGISTRATION_SETTING_KEY = "cp_registration"


class ControlPlaneState(enum.StrEnum):
    """Metadata status surfaced via `GET /admin/status` [DESIGN shape]."""

    DISABLED = "disabled"  # config `[control_plane] enabled = false`
    UNREGISTERED = "unregistered"  # enabled, no one-time-link registration yet
    OK = "ok"  # last CP operation succeeded
    OFFLINE = "offline"  # last CP operation failed — "account sync offline" (§12.3)


class ControlPlaneRegistrationError(RuntimeError):
    """Operator-facing registration failure (invalid/expired code, CP down)."""


class ControlPlaneService:
    """Heartbeat + registration + revocation mirror (§12.3 flows)."""

    def __init__(
        self,
        client: ControlPlaneClient,
        *,
        agent_id: str,
        display_name: str,
        public_key_spki: bytes,
        clock: Clock,
        load_registration: Callable[[], dict[str, Any] | None],
        save_registration: Callable[[dict[str, Any]], None],
        clear_registration: Callable[[], None],
        device_public_key: Callable[[str], bytes | None],
        heartbeat_interval_s: int = 60,  # §12.3: "low frequency (default 60 s)"
    ) -> None:
        self._client = client
        self._agent_id = agent_id
        self._display_name = display_name
        self._public_key_spki = public_key_spki
        self._clock = clock
        self._load_registration = load_registration
        self._save_registration = save_registration
        self._clear_registration = clear_registration
        self._device_public_key = device_public_key
        self._heartbeat_interval_s = heartbeat_interval_s
        self._state = ControlPlaneState.UNREGISTERED
        self._last_attempt_error: str | None = None
        self._task: asyncio.Task[None] | None = None

    # -- status (Metadata only, §17.6) -----------------------------------------

    @property
    def enabled(self) -> bool:
        return True

    def state(self) -> ControlPlaneState:
        return self._state

    def status(self) -> dict[str, Any]:
        """`GET /admin/status` block [DESIGN shape; §12 Metadata only]."""
        registration = self._load_registration()
        return {
            "enabled": True,
            "state": self._state.value,
            "registered": registration is not None,
            "registered_at": int(registration["registered_at"])
            if isinstance(registration, dict) and "registered_at" in registration
            else None,
            "heartbeat_interval_s": self._heartbeat_interval_s,
            "last_error": self._last_attempt_error,  # short reason, no URL/key
        }

    # -- §12.3 flow 1: registration (operator consented, one-time link code) --

    async def register(self, code: str) -> dict[str, Any]:
        """Exchange the Phone-provided one-time link code (§12.3).

        Raises :class:`ControlPlaneRegistrationError` on failure; the previous
        registration (if any) is left untouched on failure.
        """
        stripped = code.strip()
        if not stripped:
            raise ControlPlaneRegistrationError("code must not be empty")
        try:
            payload = await self._client.register(
                stripped, self._agent_id, self._display_name, self._public_key_spki
            )
        except Exception as exc:  # noqa: BLE001 — degrade, never block (§12.3)
            self._state = ControlPlaneState.OFFLINE
            self._last_attempt_error = "register_failed"
            log.warning(
                "cp_register_failed",
                extra={"component": "controlplane", "status": "error"},
            )
            raise ControlPlaneRegistrationError(
                "Control Plane registration failed; try again when online."
            ) from exc
        device_id = payload.get("device_id")
        if not isinstance(device_id, str) or not device_id:  # defensive; adapter validates
            raise ControlPlaneRegistrationError("Control Plane returned no device id.")
        registration = {
            "cp_device_id": device_id,
            "agent_id": self._agent_id,
            "registered_at": self._clock.now_wall(),
        }
        self._save_registration(registration)
        self._state = ControlPlaneState.OK
        self._last_attempt_error = None
        log.info("cp_registered", extra={"component": "controlplane", "status": "ok"})
        return registration

    def registered(self) -> bool:
        return self._load_registration() is not None

    def cp_device_id(self) -> str | None:
        registration = self._load_registration()
        if isinstance(registration, dict):
            value = registration.get("cp_device_id")
            if isinstance(value, str):
                return value
        return None

    # -- §12.3 flow 2: heartbeat (low frequency, only when registered) ---------

    def start(self) -> None:
        """Start the heartbeat loop (no-op when unregistered — the loop
        re-checks each tick so a later registration is picked up)."""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop(), name="cp-heartbeat")

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self._heartbeat_interval_s)
            try:
                await self.heartbeat_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — §12.3: degrade, never crash the loop
                log.warning(
                    "cp_heartbeat_unexpected_error",
                    extra={"component": "controlplane", "status": "error"},
                )

    async def heartbeat_once(self) -> bool:
        """One `last_seen` upsert; True on success (§12.3 "Heartbeat")."""
        cp_device_id = self.cp_device_id()
        if cp_device_id is None:
            return False  # unregistered: silent skip, no CP calls, no error state
        try:
            await self._client.heartbeat(cp_device_id, self._clock.now_wall())
        except Exception as exc:  # noqa: BLE001 — degrade (§12.3)
            self._state = ControlPlaneState.OFFLINE
            self._last_attempt_error = "heartbeat_failed"
            log.warning(
                "cp_heartbeat_failed",
                extra={"component": "controlplane", "status": "offline"},
            )
            _ = exc  # never logged with details — CP errors carry no Content
            return False
        self._state = ControlPlaneState.OK
        self._last_attempt_error = None
        return True

    # -- §12.3 flow 3 / FR-CP-03: revocation mirror -----------------------------

    async def mirror_device_revocation(self, device_id: str, revoked_at_epoch: int) -> int:
        """Best-effort mirror of a LOCAL revocation (FR-CP-03).

        The Agent's own store stays authoritative — a CP failure here changes
        nothing locally and is swallowed after logging (Metadata-only status).
        Returns the mirrored row count (0 = nothing mirrored / CP offline).
        """
        public_key = self._device_public_key(device_id)
        if public_key is None:
            return 0
        try:
            count = await self._client.mirror_revocation(public_key, revoked_at_epoch)
        except Exception:  # noqa: BLE001 — degrade (§12.3)
            self._state = ControlPlaneState.OFFLINE
            self._last_attempt_error = "mirror_failed"
            log.warning(
                "cp_mirror_failed",
                extra={"component": "controlplane", "status": "offline"},
            )
            return 0
        log.info("cp_mirror_ok", extra={"component": "controlplane", "status": "ok"})
        return count


def registration_codec(
    store_like: Any,
) -> tuple[
    Callable[[], dict[str, Any] | None],
    Callable[[dict[str, Any]], None],
    Callable[[], None],
]:
    """Compose registration persistence over a store with `set_setting`/
    `get_setting` (concrete `store/sqlite.py` surface; injected into the
    service from the app factory so `core` never imports `store`).

    The stored payload is Metadata only: cp_device_id, agent_id, registered_at
    (§12.2 columns; no Content keys — FR-CP-04).
    """

    def load() -> dict[str, Any] | None:
        raw = store_like.get_setting(REGISTRATION_SETTING_KEY)
        if raw is None:
            return None
        try:
            parsed = json.loads(raw)
        except ValueError:
            return None
        return parsed if isinstance(parsed, dict) else None

    def save(registration: dict[str, Any]) -> None:
        store_like.set_setting(
            REGISTRATION_SETTING_KEY, json.dumps(registration, separators=(",", ":"))
        )

    def clear() -> None:
        store_like.set_setting(REGISTRATION_SETTING_KEY, "")

    return load, save, clear
