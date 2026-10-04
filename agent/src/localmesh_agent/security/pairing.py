"""PairingSession state machine (SM-PAIR) (§10.1, §15.2).

Implements WP-08 (M2) per §22.2 — "Pairing + auth + tokens + revoke
(+ admin API)", context §13.2 (API-PAIR-01/02), §15.2 (SM-PAIR), §15.4
(sequence), §17.3/§17.4 (crypto + QR), §13.8 (lockout), FR-PAIR-01/02/04.

State machine (§15.2, verbatim):

    CLOSED  (default)          -- operator `open` -->  OPEN
    OPEN    (secret generated, QR available, TTL timer)
            -- valid `pair/complete` --> CLAIMED
            -- TTL --> EXPIRED ; operator `close` --> CLOSED
            -- 5 bad proofs --> LOCKED
    CLAIMED (proof verified; pending Device + SAS shown to operator; 120 s)
            -- `approve` --> APPROVED ; `deny` / timeout --> DENIED / EXPIRED
    APPROVED (Device persisted) -- CLOSED after status delivered (<= 60 s)
    DENIED / EXPIRED / LOCKED (secret destroyed) -- CLOSED; LOCKED cooldown 15 min

Invariants: only one session exists at a time; opening a new one invalidates
the previous (§15.2). The Pairing Secret is CSPRNG 32 bytes, single-use,
memory-only (§17.3) — it NEVER touches disk or logs (§17.6). Sessions are
never persisted (§14.1).

Interpretations of underspecified corners (recorded as QUESTION-103,
conservative readings documented here):

- **Status delivery after terminal states** (§15.2 says the secret is
  destroyed when DENIED/EXPIRED/LOCKED is entered, but §13.2 API-PAIR-02
  defines `denied` as a pollable status and §15.4 shows the phone polling
  after the operator decision): DENIED and APPROVED keep the secret in memory
  for a bounded `status_delivery_window` (60 s, §15.2 "status delivered
  (<= 60 s)") so the phone can observe the outcome, then the session closes
  and the secret is destroyed. EXPIRED and LOCKED destroy the secret
  immediately; their `pair/status` polls fail closed with 410 PAIRING_EXPIRED
  and 429 PAIRING_LOCKED respectively (the phone cannot be authenticated
  without the secret, and silently leaking terminal state to unauthenticated
  polls would weaken the protocol).
- **Single-use secret** (FR-PAIR-02 "Second use of same secret -> 403"): a
  `pair/complete` against a session that is no longer OPEN is 403
  PAIRING_INVALID (not 409), matching the FR-PAIR-02 acceptance criterion.
"""

from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass, field
from enum import StrEnum
from urllib.parse import quote

from localmesh_agent.adapters.ports import Clock, Store
from localmesh_agent.security import crypto
from localmesh_agent.security.devices import DeviceService

# §15.2 / §13.8 timings.
CLAIM_TIMEOUT_S = 120  # CLAIMED → EXPIRED when not approved within 120 s
STATUS_DELIVERY_WINDOW_S = 60  # APPROVED/DENIED → CLOSED after status delivered
LOCKOUT_COOLDOWN_S = 900  # §13.8: 15-min cooldown after 5 bad proofs
MAX_BAD_PROOFS = 5  # §13.8: failed pair/* proofs per session
DEFAULT_SCOPES = ("models:read", "chat")  # §13.1/§13.2 default Device scopes

QR_VERSION = "1"  # §17.4: localmesh://pair?v=1&...


class PairingErrorCode(StrEnum):
    """Machine-readable outcomes mapped to Appendix D codes by the API layer."""

    PAIRING_CLOSED = "PAIRING_CLOSED"  # 409 — no open session
    PAIRING_INVALID = "PAIRING_INVALID"  # 403 — bad proof / single-use reuse
    PAIRING_EXPIRED = "PAIRING_EXPIRED"  # 410 — TTL elapsed
    PAIRING_LOCKED = "PAIRING_LOCKED"  # 429 — too many bad proofs


class PairingError(RuntimeError):
    """Domain-level pairing failure; carries the Appendix D error code."""

    def __init__(self, code: PairingErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class SessionState(StrEnum):
    """SM-PAIR states (§15.2)."""

    CLOSED = "closed"
    OPEN = "open"
    CLAIMED = "claimed"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"
    LOCKED = "locked"


@dataclass
class _Session:
    """One in-memory PairingSession (never persisted — §14.1)."""

    pair_id: str
    secret: bytes
    opened_at: int
    expires_at: int
    state: SessionState = SessionState.OPEN
    bad_proofs: int = 0
    # Filled on CLAIMED (the proof bound the values; §17.4 "the stored key is
    # the one that was approved"):
    client_nonce: bytes | None = None
    device_name: str | None = None
    device_platform: str | None = None
    device_spki_der: bytes | None = None
    device_id: str | None = None  # filled on APPROVED
    claimed_at: int | None = None
    decided_at: int | None = None

    def status_value(self) -> str:
        """API-PAIR-02 `status` string (§13.2 closed set). An OPEN session
        (QR scanned, proof not yet accepted) is still "awaiting_confirmation"
        from the phone's point of view."""
        if self.state in (SessionState.OPEN, SessionState.CLAIMED):
            return "awaiting_confirmation"
        if self.state is SessionState.APPROVED:
            return "approved"
        if self.state is SessionState.DENIED:
            return "denied"
        return "expired"


@dataclass(frozen=True)
class PairingOpened:
    """Operator-facing result of opening Pairing Mode (§15.4 step 1-2)."""

    pair_id: str
    qr: str
    expires_in: int


@dataclass(frozen=True)
class PendingDevice:
    """What the operator must confirm (§15.4: pending device + SAS)."""

    name: str
    platform: str
    sas: str


@dataclass
class PairingService:
    """SM-PAIR owner (§10.4 PairingService: "One active session at a time")."""

    store: Store
    devices: DeviceService
    clock: Clock
    ttl_seconds: int  # config pairing.ttl_seconds (FR-PAIR-02: <= 600)
    require_confirmation: bool  # config pairing.require_confirmation (FR-PAIR-04)
    agent_id: str
    display_name: str
    spki_pin: str
    endpoints: tuple[str, ...] = ()  # https endpoint(s) advertised in the QR
    _session: _Session | None = field(default=None, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _locked_until: int = 0  # open() refused until this wall time (§13.8)
    # FR-PAIR-02 AC "use after TTL → 410": a just-expired session must answer
    # PAIRING_EXPIRED (410), distinct from a never-opened one (409). The
    # tombstone keeps only (pair_id, until) — never the secret — for one
    # bounded delivery window [DESIGN, QUESTION-103].
    _expired_tombstone: tuple[str, int] = field(default=("", 0), repr=False)

    # -- operator surface (admin listener / §15.4) -----------------------------

    def open(self) -> PairingOpened:
        """Operator opens Pairing Mode: generate secret + QR (§15.2 CLOSED→OPEN)."""
        with self._lock:
            now = self.clock.now_wall()
            if now < self._locked_until:
                raise PairingError(
                    PairingErrorCode.PAIRING_LOCKED,
                    "Pairing is locked after repeated failed proofs; try later.",
                )
            # §15.2: opening a new session invalidates the previous one.
            pair_id = "pr_" + crypto.b64url_encode(secrets.token_bytes(16))  # §14.3
            secret = secrets.token_bytes(crypto.PAIRING_SECRET_BYTES)  # CSPRNG 32B
            self._session = _Session(
                pair_id=pair_id,
                secret=secret,
                opened_at=now,
                expires_at=now + self.ttl_seconds,
            )
            self.store.append_audit("pair_opened", meta={"agent_id": self.agent_id})
            return PairingOpened(
                pair_id=pair_id,
                qr=self._qr_payload(self._session),
                expires_in=self.ttl_seconds,
            )

    def close(self) -> None:
        """Operator closes Pairing Mode (§15.2 OPEN → CLOSED)."""
        with self._lock:
            self._destroy_session(SessionState.CLOSED)

    def pending(self) -> tuple[SessionState, PendingDevice | None]:
        """Operator view: current state + the pending Device/SAS when CLAIMED.

        Applies the SM-PAIR timers (TTL, claim timeout, delivery window) so a
        stale session is observed as its terminal state (§15.2).
        """
        with self._lock:
            session = self._advance_timers()
            if session is None or session.state is SessionState.CLOSED:
                return SessionState.CLOSED, None
            if session.state is SessionState.CLAIMED and session.device_name is not None:
                assert session.client_nonce is not None
                assert session.device_spki_der is not None
                sas = crypto.sas_code(
                    session.secret,
                    session.pair_id,
                    session.client_nonce,
                    session.device_spki_der,
                )
                pending = PendingDevice(
                    name=session.device_name, platform=session.device_platform or "", sas=sas
                )
                return session.state, pending
            if session.state is SessionState.CLAIMED:  # pragma: no cover - defensive
                return session.state, None
            return session.state, None

    # -- phone surface (API-PAIR-01/02, §13.2) ---------------------------------

    def complete(
        self,
        pair_id: str,
        client_nonce_b64url: str,
        device_name: str,
        platform: str,
        device_public_key_spki_b64url: str,
        proof_b64url: str,
    ) -> None:
        """API-PAIR-01 (§13.2): verify proof; OPEN → CLAIMED (or auto-approve)."""
        with self._lock:
            self._advance_timers()
            now = self.clock.now_wall()
            session = self._session
            if session is None or session.state is SessionState.CLOSED:
                # FR-PAIR-02: a session that JUST expired answers 410 (tombstone);
                # one locked by bad proofs answers 429 (§13.8); a never-opened
                # or operator-closed one answers 409.
                if session is None and self._expired_tombstone[0] == pair_id:
                    if now <= self._expired_tombstone[1]:
                        raise PairingError(
                            PairingErrorCode.PAIRING_EXPIRED, "Pairing session expired."
                        )
                if session is None and now < self._locked_until:
                    raise PairingError(
                        PairingErrorCode.PAIRING_LOCKED,
                        "Pairing is locked after repeated failed proofs.",
                    )
                raise PairingError(
                    PairingErrorCode.PAIRING_CLOSED,
                    "Pairing Mode is not open on this Agent.",
                )
            if session.state is SessionState.LOCKED:
                raise PairingError(PairingErrorCode.PAIRING_LOCKED, "Pairing is locked.")
            if session.state in (SessionState.EXPIRED, SessionState.DENIED):
                raise PairingError(PairingErrorCode.PAIRING_EXPIRED, "Pairing session ended.")
            if session.state in (SessionState.CLAIMED, SessionState.APPROVED):
                # FR-PAIR-02: single-use secret — second use → 403.
                raise PairingError(
                    PairingErrorCode.PAIRING_INVALID,
                    "The pairing secret was already used.",
                )
            if pair_id != session.pair_id:
                # Unknown pair_id while a different session is open: same
                # uniform outcome as a bad proof (counts toward lockout).
                self._register_bad_proof(session)
                raise PairingError(PairingErrorCode.PAIRING_INVALID, "Invalid pairing proof.")
            try:
                client_nonce = crypto.b64url_decode(client_nonce_b64url)
                spki_der = crypto.b64url_decode(device_public_key_spki_b64url)
                proof = crypto.b64url_decode(proof_b64url)
            except crypto.EncodingError as exc:
                self._register_bad_proof(session)
                raise PairingError(
                    PairingErrorCode.PAIRING_INVALID, "Malformed pairing payload."
                ) from exc
            if len(client_nonce) != crypto.CLIENT_NONCE_BYTES:
                self._register_bad_proof(session)
                raise PairingError(
                    PairingErrorCode.PAIRING_INVALID, "client_nonce must be 16 bytes."
                )
            expected = crypto.pairing_proof(
                session.secret, self.agent_id, pair_id, client_nonce, spki_der
            )
            if not crypto.constant_time_eq(expected, proof):
                self._register_bad_proof(session)
                raise PairingError(PairingErrorCode.PAIRING_INVALID, "Invalid pairing proof.")

            # Proof verified: CLAIMED; the pending Device + SAS are bound.
            session.state = SessionState.CLAIMED
            session.client_nonce = client_nonce
            session.device_name = device_name
            session.device_platform = platform
            session.device_spki_der = spki_der
            session.claimed_at = self.clock.now_wall()
            self.store.append_audit("pair_claimed", meta={"agent_id": self.agent_id})

            if not self.require_confirmation:
                # FR-PAIR-04: confirmation configurable; when off, auto-approve.
                self._approve_locked(session)

    def status(
        self, pair_id: str, client_nonce_b64url: str, status_proof_b64url: str
    ) -> dict[str, object]:
        """API-PAIR-02 (§13.2): authenticated poll of the session outcome."""
        with self._lock:
            session = self._advance_timers()
            if session is None or session.state is SessionState.CLOSED:
                raise PairingError(PairingErrorCode.PAIRING_CLOSED, "Pairing Mode is not open.")
            if session.state is SessionState.LOCKED:
                # Secret destroyed at LOCKED entry: fail closed (QUESTION-103).
                raise PairingError(PairingErrorCode.PAIRING_LOCKED, "Pairing is locked.")
            if session.state in (SessionState.EXPIRED, SessionState.DENIED) and (
                session.decided_at is None
                or self.clock.now_wall() > session.decided_at + STATUS_DELIVERY_WINDOW_S
            ):
                # Delivery window over (or never claimed): secret gone → 410.
                raise PairingError(PairingErrorCode.PAIRING_EXPIRED, "Pairing session ended.")
            if pair_id != session.pair_id:
                raise PairingError(PairingErrorCode.PAIRING_INVALID, "Unknown pair_id.")
            try:
                client_nonce = crypto.b64url_decode(client_nonce_b64url)
                proof = crypto.b64url_decode(status_proof_b64url)
            except crypto.EncodingError as exc:
                raise PairingError(
                    PairingErrorCode.PAIRING_INVALID, "Malformed status payload."
                ) from exc
            expected = crypto.status_proof(session.secret, pair_id, client_nonce)
            if not crypto.constant_time_eq(expected, proof):
                raise PairingError(PairingErrorCode.PAIRING_INVALID, "Invalid status proof.")

            response: dict[str, object] = {
                "status": session.status_value(),
                "agent_id": self.agent_id,
                "scopes": list(DEFAULT_SCOPES),
                "endpoints": {"lan": list(self.endpoints), "tailnet": None},
            }
            if session.state is SessionState.APPROVED and session.device_id is not None:
                # device_id/endpoints only when approved (§13.2).
                response["device_id"] = session.device_id
            return response

    def approve(self) -> str:
        """Operator confirms the CLAIMED Device (§15.4): CLAIMED → APPROVED."""
        with self._lock:
            session = self._advance_timers()
            if session is None or session.state is not SessionState.CLAIMED:
                raise PairingError(PairingErrorCode.PAIRING_CLOSED, "No claimed device is pending.")
            self._approve_locked(session)
            assert session.device_id is not None
            return session.device_id

    def deny(self) -> None:
        """Operator denies the CLAIMED Device (§15.2: CLAIMED → DENIED)."""
        with self._lock:
            session = self._advance_timers()
            if session is None or session.state is not SessionState.CLAIMED:
                raise PairingError(PairingErrorCode.PAIRING_CLOSED, "No claimed device is pending.")
            session.state = SessionState.DENIED
            session.decided_at = self.clock.now_wall()
            self.store.append_audit("pair_denied", meta={"agent_id": self.agent_id})

    def pairing_open(self) -> bool:
        """`GET /info` field (API-INFO-01): a session is open (usable)."""
        with self._lock:
            session = self._advance_timers()
            return session is not None and session.state is SessionState.OPEN

    # -- internals -------------------------------------------------------------

    def _approve_locked(self, session: _Session) -> None:
        """APPROVED: persist the Device, keep the secret only for status
        delivery (QUESTION-103); caller holds the lock."""
        assert session.client_nonce is not None
        assert session.device_spki_der is not None
        assert session.device_name is not None
        device_id = self.devices.create(
            name=session.device_name,
            platform=session.device_platform or "",
            public_key_spki=session.device_spki_der,
        )
        session.device_id = device_id
        session.state = SessionState.APPROVED
        session.decided_at = self.clock.now_wall()
        self.store.append_audit(
            "pair_approved", device_id=device_id, meta={"agent_id": self.agent_id}
        )

    def _register_bad_proof(self, session: _Session) -> None:
        """§13.8: 5 failed pair/* proofs → session closed + 15-min cooldown."""
        session.bad_proofs += 1
        if session.bad_proofs >= MAX_BAD_PROOFS:
            now = self.clock.now_wall()
            self._locked_until = now + LOCKOUT_COOLDOWN_S
            self._session = None  # secret destroyed
            self.store.append_audit("pair_denied", meta={"agent_id": self.agent_id})

    def _advance_timers(self) -> _Session | None:
        """Apply §15.2 timers; caller holds the lock. Returns the live session."""
        session = self._session
        if session is None:
            return None
        now = self.clock.now_wall()
        if session.state is SessionState.OPEN and now > session.expires_at:
            self._destroy_session(SessionState.EXPIRED)
            return None
        if (
            session.state is SessionState.CLAIMED
            and session.claimed_at is not None
            and now > session.claimed_at + CLAIM_TIMEOUT_S
        ):
            # §15.2: without approval within 120 s the pairing fails and the
            # secret is consumed (FR-PAIR-04 acceptance).
            self._destroy_session(SessionState.EXPIRED)
            return None
        if session.state in (SessionState.APPROVED, SessionState.DENIED):
            assert session.decided_at is not None
            if now > session.decided_at + STATUS_DELIVERY_WINDOW_S:
                self._destroy_session(SessionState.CLOSED)
                return None
        return session

    def _destroy_session(self, terminal: SessionState) -> None:
        """Tear the session down; the secret never outlives the session."""
        session = self._session
        if session is not None and terminal is SessionState.EXPIRED:
            self._expired_tombstone = (
                session.pair_id,
                self.clock.now_wall() + STATUS_DELIVERY_WINDOW_S,
            )
        self._session = None  # secret is garbage-collected; never written down
        if terminal in (SessionState.DENIED, SessionState.EXPIRED):
            self.store.append_audit("pair_denied", meta={"agent_id": self.agent_id})

    def _qr_payload(self, session: _Session) -> str:
        """§17.4 QR URI (verbatim format). Contains the ONLY intentional
        secret exposure (`sec`) — callers must render it locally and never
        log it (§17.4, §17.6)."""
        parts = [
            f"v={QR_VERSION}",
            f"aid={quote(self.agent_id, safe='')}",
            f"n={quote(self.display_name, safe='')}",
            f"fp={self.spki_pin}",
            f"pid={quote(session.pair_id, safe='')}",
            f"sec={crypto.b64url_encode(session.secret)}",
        ]
        parts.extend(f"ep={quote(endpoint, safe='')}" for endpoint in self.endpoints)
        return "localmesh://pair?" + "&".join(parts)
