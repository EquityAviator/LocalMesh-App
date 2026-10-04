"""Manual-code pairing (M9, FR-PAIR-07; ADR-007 — SPAKE2+ is reserved for the
typed-code fallback; the QR path remains the primary pairing flow).

FR-PAIR-07: "Manual-code pairing (no camera) using SPAKE2+ — RFC-conformant
test vectors pass; 5 failed attempts → lockout."

Design [DESIGN where the spec is silent]:

- The operator opens a manual pairing session from the admin surface; the
  Agent generates a numeric one-time code + salt and derives (w0, w1) via
  PBKDF2 (`security.spake2.derive_w0_w1`). The code is shown on the PC and
  typed on the phone (the phone derives the same w0/w1 from the typed code).
- The phone plays the SPAKE2+ Prover, the Agent the Verifier (RFC 9383).
- FAILED ATTEMPTS: every failed verification (wrong code / bad share / bad
  confirmation tags) counts against the session; the 5th failure LOCKS the
  session for a 15-minute cooldown (§13.8: "Failed pair/* proofs: 5 per
  PairingSession → session closed, 15 min cooldown"). Lockout state is
  Metadata-only and never logged with code material (§17.10).
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from enum import Enum

from localmesh_agent.security.spake2 import (
    KeySchedule,
    ProverShare,
    Verifier,
    derive_w0_w1,
)
from localmesh_agent.security.spake2 import (
    confirm_p_tag as spake_confirm_p_tag,
)

MAX_FAILED_ATTEMPTS = 5  # FR-PAIR-07 AC
LOCKOUT_SECONDS = 15 * 60  # §13.8: 15 min cooldown
CODE_DIGITS = 6  # [DESIGN] typed-code ergonomics; ≥ 20 bits with rate limits
CODE_TTL_SECONDS = 300  # same window as the QR session (FR-PAIR-02 ≤ 600 s)
CONTEXT = b"localmesh-pair-manual-v1"
ID_PROVER = b"localmesh-phone"
ID_VERIFIER = b"localmesh-agent"


class ManualPairingState(str, Enum):
    OPEN = "open"
    LOCKED = "locked"
    EXPIRED = "expired"


@dataclass
class ManualPairingSession:
    """One typed-code pairing session (Metadata only)."""

    pair_id: str
    code: str
    salt: bytes
    created_at: int
    failed_attempts: int = 0
    state: ManualPairingState = ManualPairingState.OPEN
    locked_until: int | None = None
    expires_at: int = field(default=0)


class ManualPairingService:
    """Owns typed-code sessions and the FR-PAIR-07 lockout counter."""

    def __init__(self, *, ttl_seconds: int = CODE_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._session: ManualPairingSession | None = None

    # -- operator surface -----------------------------------------------------

    def open_session(self, now: int | None = None) -> ManualPairingSession:
        """Generate a fresh typed code (operator-consented, admin surface)."""
        current = int(time.time()) if now is None else now
        code = "".join(secrets.choice("0123456789") for _ in range(CODE_DIGITS))
        salt = secrets.token_bytes(16)
        self._session = ManualPairingSession(
            pair_id=f"pr_{secrets.token_hex(8)}",
            code=code,
            salt=salt,
            created_at=current,
            expires_at=current + self._ttl,
        )
        return self._session

    def current_session(self) -> ManualPairingSession | None:
        return self._session

    def state(self, now: int | None = None) -> ManualPairingState:
        session = self._session
        if session is None:
            return ManualPairingState.EXPIRED
        current = int(time.time()) if now is None else now
        if session.state is ManualPairingState.LOCKED:
            if session.locked_until is not None and current < session.locked_until:
                return ManualPairingState.LOCKED
            session.state = ManualPairingState.EXPIRED  # cooldown elapsed: closed
        if current >= session.expires_at:
            return ManualPairingState.EXPIRED
        return session.state

    # -- SPAKE2+ verification ---------------------------------------------------

    def build_verifier(self, session: ManualPairingSession) -> Verifier:
        """The Agent-side Verifier from the session's code-derived w0/w1."""
        w0, w1 = derive_w0_w1(session.code, session.salt, iterations=100_000)
        return Verifier(CONTEXT, ID_PROVER, ID_VERIFIER, w0, w1=w1)

    def verify_attempt(
        self,
        prover_share: ProverShare,
        confirm_p: bytes,
        *,
        now: int | None = None,
    ) -> tuple[bool, KeySchedule | None]:
        """Verify one phone attempt; counts failures; locks on the 5th.

        Returns (ok, schedule). On failure ok=False (schedule=None) — the
        caller answers 403 and the NEXT failure may trigger the lockout.
        """
        session = self._session
        if session is None or self.state(now) is not ManualPairingState.OPEN:
            return False, None
        try:
            verifier = self.build_verifier(session)
            _y, share_v = verifier.start()
            schedule, _confirm_v, expected_confirm_p = verifier.finish(
                prover_share.share_p
            )
            # RFC 9383 §3.4: the Agent verifies the Prover's tag; the Prover
            # verifies ours with the same key material (constant-time compare
            # happens at the caller boundary via hmac.compare_digest inside
            # spake2._mac consumers — here the tags are compared in full).
            ok = hmac.compare_digest(
                spake_confirm_p_tag(schedule.k_confirm_p, share_v), confirm_p
            )
            _ = expected_confirm_p
        except ValueError:
            ok = False
            schedule = None
        if ok:
            self._session = None  # success closes the session
            return True, schedule
        session.failed_attempts += 1
        if session.failed_attempts >= MAX_FAILED_ATTEMPTS:
            current = int(time.time()) if now is None else now
            session.state = ManualPairingState.LOCKED
            session.locked_until = current + LOCKOUT_SECONDS
        return False, None
