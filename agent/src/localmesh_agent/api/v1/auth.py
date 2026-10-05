"""Auth endpoints — API-AUTH-01/02 (§13.2, WP-08, ADR-008).

    POST /mesh/v1/auth/challenge   {device_id} → {challenge_id, nonce, expires_in: 30}
    POST /mesh/v1/auth/token       {device_id, challenge_id, signature} → Bearer token

Security properties (normative):

- **Anti-enumeration** (§13.2 API-AUTH-01): the challenge is returned even
  for unknown device IDs — identical shape, identical timing envelope.
- **Single use** (§17.3 "Auth challenge: 32 random bytes, TTL 30 s,
  single-use"): a challenge is consumed by the FIRST /auth/token attempt —
  a replayed or retried challenge yields uniform 401 AUTH_FAILED.
- **Uniform failures** (§13.2 API-AUTH-02, §17.8): unknown device, bad
  signature and reused challenge are indistinguishable 401 AUTH_FAILED.
- **DEVICE_REVOKED only after a *valid* signature** from a revoked device's
  key (§13.2): revocation must not be detectable without proving possession
  of the device key.
- **Rate limits** (§13.8): 10/min per source IP AND per device_id on
  /auth/challenge → 429 RATE_LIMITED.

Challenges are in-memory only (§14.1 lists no challenge table; a restart
invalidates pending challenges, which is acceptable — clients re-request).
"""

from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass, field

from fastapi import APIRouter, Request

from localmesh_agent.core.errors import MeshError
from localmesh_agent.security import crypto

router = APIRouter()

CHALLENGE_TTL_S = 30  # §17.3: TTL 30 s, single use
CHALLENGE_LIMIT_PER_MIN = 10  # §13.8: per source IP and per device_id


@dataclass
class _Challenge:
    """One auth challenge (in-memory, single-use, TTL 30 s)."""

    device_id: str
    nonce_b64url: str  # the exact string the device signs (QUESTION-103)
    nonce_raw: bytes
    created_at: int


@dataclass
class ChallengeStore:
    """In-memory single-use challenge registry (§10.4 TokenService side)."""

    ttl_s: int = CHALLENGE_TTL_S
    _challenges: dict[str, _Challenge] = field(default_factory=dict, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def create(self, device_id: str, now: int) -> tuple[str, str]:
        """Issue a challenge; returns (challenge_id, nonce_b64url)."""
        challenge_id = "ch_" + crypto.b64url_encode(secrets.token_bytes(16))  # §14.3
        nonce_raw = secrets.token_bytes(crypto.CHALLENGE_NONCE_BYTES)  # 32 CSPRNG
        nonce_b64url = crypto.b64url_encode(nonce_raw)
        with self._lock:
            self._prune(now)
            self._challenges[challenge_id] = _Challenge(
                device_id=device_id,
                nonce_b64url=nonce_b64url,
                nonce_raw=nonce_raw,
                created_at=now,
            )
        return challenge_id, nonce_b64url

    def consume(self, challenge_id: str, device_id: str, now: int) -> _Challenge | None:
        """Single-use pop: None when unknown/expired/other-device/reused."""
        with self._lock:
            self._prune(now)
            challenge = self._challenges.pop(challenge_id, None)
        if challenge is None or challenge.device_id != device_id:
            return None
        if now > challenge.created_at + self.ttl_s:
            return None
        return challenge

    def _prune(self, now: int) -> None:
        """Drop expired challenges (caller holds the lock)."""
        expired = [
            cid
            for cid, challenge in self._challenges.items()
            if now > challenge.created_at + self.ttl_s
        ]
        for cid in expired:
            del self._challenges[cid]


@router.post("/mesh/v1/auth/challenge", tags=["auth"])
async def auth_challenge(request: Request) -> dict[str, object]:
    """API-AUTH-01 (§13.2): issue a single-use signing challenge."""
    try:
        payload: dict[str, object] = await request.json()  # type: ignore[assignment]
    except Exception as exc:
        raise MeshError("INVALID_REQUEST", "Request body must be valid JSON.") from exc
    if not isinstance(payload, dict) or set(payload) != {"device_id"}:
        raise MeshError(
            "INVALID_REQUEST",
            "Body must be exactly {device_id} (§13.2 API-AUTH-01).",
        )
    device_id = str(payload["device_id"])
    limiter = request.app.state.limiter
    client_ip = request.client.host if request.client else "unknown"
    # §13.8: 10/min per source IP AND per device_id — two independent keys.
    if not limiter.allow(f"auth-ch:ip:{client_ip}", CHALLENGE_LIMIT_PER_MIN) or not (
        limiter.allow(f"auth-ch:dev:{device_id}", CHALLENGE_LIMIT_PER_MIN)
    ):
        raise MeshError("RATE_LIMITED", "Too many auth challenges; slow down.")

    challenges: ChallengeStore = request.app.state.challenges
    clock = request.app.state.clock
    challenge_id, nonce = challenges.create(device_id, clock.now_wall())
    # §13.2: returned even for unknown device IDs (anti-enumeration).
    return {"challenge_id": challenge_id, "nonce": nonce, "expires_in": CHALLENGE_TTL_S}


@router.post("/mesh/v1/auth/token", tags=["auth"])
async def auth_token(request: Request) -> dict[str, object]:
    """API-AUTH-02 (§13.2): verify the ECDSA signature; issue a Device Token."""
    try:
        payload: dict[str, object] = await request.json()  # type: ignore[assignment]
    except Exception as exc:
        raise MeshError("INVALID_REQUEST", "Request body must be valid JSON.") from exc
    if not isinstance(payload, dict):
        raise MeshError("INVALID_REQUEST", "Request body must be a JSON object.")
    required = {"device_id", "challenge_id", "signature"}
    unknown = sorted(set(payload) - required)
    missing = sorted(required - set(payload))
    if unknown or missing:
        raise MeshError(
            "INVALID_REQUEST",
            "Body must be {device_id, challenge_id, signature} (§13.2 API-AUTH-02).",
            details={
                **({"unknown_fields": unknown} if unknown else {}),
                **({"missing_fields": missing} if missing else {}),
            },
        )
    device_id = str(payload["device_id"])
    challenge_id = str(payload["challenge_id"])
    signature_b64url = str(payload["signature"])

    app_state = request.app.state
    now = app_state.clock.now_wall()

    def uniform_auth_fail() -> MeshError:
        app_state.store.append_audit(
            "auth_fail", device_id=device_id, meta={"agent_id": str(app_state.agent_id)}
        )
        return MeshError("AUTH_FAILED", "Authentication failed.")

    # Single-use: the first token attempt consumes the challenge (§17.3).
    challenge = app_state.challenges.consume(challenge_id, device_id, now)
    if challenge is None:
        raise uniform_auth_fail()

    device = app_state.store.get_device(device_id)
    if device is None:
        raise uniform_auth_fail()  # unknown device — uniform (anti-enumeration)

    message = crypto.auth_message(
        str(app_state.agent_id), device_id, challenge_id, challenge.nonce_b64url
    )
    try:
        signature = crypto.b64url_decode(signature_b64url)
    except crypto.EncodingError:
        raise uniform_auth_fail() from None
    if not crypto.verify_device_signature(bytes(device["public_key_spki"]), message, signature):
        raise uniform_auth_fail()  # bad signature — uniform

    # Valid signature from this device's key. NOW (and only now) a revoked
    # device is told so (§13.2: 403 DEVICE_REVOKED "only after a *valid*
    # signature from a revoked device's key").
    if device.get("revoked_at") is not None:
        raise MeshError("DEVICE_REVOKED", "This device has been revoked.")

    issued = app_state.tokens.issue(device_id)
    app_state.store.append_audit(
        "auth_ok", device_id=device_id, meta={"agent_id": str(app_state.agent_id)}
    )
    app_state.devices.touch_last_seen(device_id)
    response: dict[str, object] = {
        "access_token": issued.token,
        "token_type": "Bearer",
        "expires_in": issued.expires_in,
        "scopes": str(device["scopes"]).split(),
    }
    # M9 pin rotation (§17.5 "Smooth rotation", P2): the Agent MAY
    # pre-announce the hash of its NEXT public key here; a paired App stores
    # it and accepts it after rotation, then re-pins. Only present when the
    # operator stages a next pin via `POST /admin/tls/backup-pin`.
    pin_backup = request.app.state.store.get_setting("tls_pin_backup")
    if pin_backup:
        response["pin_backup"] = pin_backup
    return response
