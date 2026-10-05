"""issue/verify/revoke opaque tokens (§10.1, ADR-008).

Implements the WP-08 Device Token service (M2) per §22.2, context ADR-008,
§13.2 (API-AUTH-02 response), §14.1 (`tokens` table), §17.3 ("Device Token:
32 random bytes b64url; TTL 900 s; Agent stores SHA-256(token); compare
constant-time"), §17.6 ("Device Tokens: App memory only; Agent stores hash").

- **Issue**: 32 CSPRNG bytes, presented b64url-no-pad (§17.3 encoding rule);
  only `SHA-256(token)` is persisted (§10.4 "store SHA-256 of token only").
- **Verify**: hash lookup → expiry (injectable clock) → device revocation.
  Failures are UNIFORM — the caller maps them to 401 AUTH_FAILED without
  distinguishing cause (§13.2 API-AUTH-02 "indistinguishable"; §17.8
  "uniform AUTH_FAILED").
- **Revoke**: instant — deleting the token hashes kills every outstanding
  token of the Device (ADR-008 "Consequences"); the devices row is kept with
  `revoked_at` set (§14.1 schema comment wins over ADR-008's "device row"
  wording; §14.1 is the normative schema).
"""

from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass

from localmesh_agent.adapters.ports import Clock, Store
from localmesh_agent.security import crypto

TOKEN_TTL_S = 900  # §13.2 API-AUTH-02: expires_in 900 (15 min)


@dataclass(frozen=True)
class IssuedToken:
    """API-AUTH-02 response fields for one issued token (§13.2)."""

    token: str  # b64url, no padding — the only time the plaintext exists here
    expires_in: int


@dataclass(frozen=True)
class TokenVerdict:
    """Result of verifying a presented Bearer token."""

    device_id: str
    scopes: str  # space-separated (§14.1 devices.scopes)


@dataclass(frozen=True)
class TokenRejection:
    """Why a presented token failed. Appendix D distinguishes TOKEN_EXPIRED
    (401, retryable — client should re-auth once, §15.3) from AUTH_FAILED
    (401, uniform); revocation MUST NOT be distinguishable here because
    revocation deletes the hashes (uniform AUTH_FAILED, §17.8)."""

    expired: bool  # True → TOKEN_EXPIRED; False → AUTH_FAILED


class TokenService:
    """§10.4 TokenService: "Issue/verify/revoke; constant-time compares;
    store SHA-256 of token only"."""

    def __init__(self, store: Store, clock: Clock, ttl_seconds: int = TOKEN_TTL_S) -> None:
        self._store = store
        self._clock = clock
        self._ttl = ttl_seconds
        self._lock = threading.Lock()

    def issue(self, device_id: str) -> IssuedToken:
        """Issue a fresh Device Token; persist the hash only (§14.1)."""
        raw = secrets.token_bytes(crypto.TOKEN_BYTES)
        token = crypto.b64url_encode(raw)
        token_hash = crypto.sha256_token_hash(token)
        now = self._clock.now_wall()
        with self._lock:
            self._store.put_token(token_hash, device_id, issued_at=now, expires_at=now + self._ttl)
        return IssuedToken(token=token, expires_in=self._ttl)

    def verify(self, presented_token: str) -> TokenVerdict | TokenRejection | None:
        """Verify a presented token.

        Returns TokenVerdict on success, TokenRejection for a known-but-expired
        or unknown hash, None for an empty/malformed input. Constant-time
        properties (§17.3): the DB lookup is by SHA-256 digest, so no secret is
        compared byte-wise here; any future in-process comparison MUST use
        `crypto.constant_time_eq`.
        """
        if not presented_token:
            return None
        token_hash = crypto.sha256_token_hash(presented_token)
        with self._lock:
            record = self._store.get_token(token_hash)
            if record is None:
                return TokenRejection(expired=False)
            if self._clock.now_wall() > int(record["expires_at"]):
                return TokenRejection(expired=True)
            device = self._store.get_device(str(record["device_id"]))
            if device is None or device.get("revoked_at") is not None:
                # Revoked devices have their tokens deleted on revoke; this
                # branch is belt-and-braces for the window before deletion —
                # and must stay INDISTINGUISHABLE from unknown (§17.8).
                return TokenRejection(expired=False)
            return TokenVerdict(device_id=str(device["device_id"]), scopes=str(device["scopes"]))
