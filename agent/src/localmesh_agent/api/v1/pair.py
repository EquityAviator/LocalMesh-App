"""Pairing endpoints — API-PAIR-01/02 (§13.2, WP-08).

    POST /mesh/v1/pair/complete   (only while a PairingSession is OPEN)
    POST /mesh/v1/pair/status     (≤ 1 Hz poll by the pairing phone)

These endpoints are unauthenticated BY DESIGN (§17.7 row "/info, /auth/*,
/pair/*: rate-limited / proof") — the proof IS the authentication. Errors use
the §13.4 envelope with the Appendix D pairing codes; failed proofs count
toward the per-session lockout (§13.8: 5 → session closed + 15-min cooldown,
enforced inside `security.pairing`).

The API layer is THIN (§10.1): validate the wire shape → call the
PairingService → map PairingError to the envelope. No crypto here.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from localmesh_agent.core.errors import MeshError
from localmesh_agent.security.pairing import PairingError

router = APIRouter()

# §13.8: "Poll ≤ 1 Hz, ≤ 120 s" — this server-side bound is deliberately a
# multiple of 1 Hz to absorb clock jitter; the ≤ 1 Hz duty itself belongs to
# the App. Abuse beyond the bound gets RATE_LIMITED.
STATUS_POLL_LIMIT_PER_MIN = 10


def _require_fields(payload: dict[str, Any], *names: str) -> None:
    """Reject missing/extra fields with 422 INVALID_REQUEST (§13.6 style)."""
    unknown = sorted(set(payload) - set(names))
    missing = sorted(set(names) - set(payload))
    if unknown or missing:
        details: dict[str, object] = {}
        if unknown:
            details["unknown_fields"] = unknown
        if missing:
            details["missing_fields"] = missing
        raise MeshError(
            "INVALID_REQUEST",
            "Request body does not match the §13.2 shape.",
            details=details,
        )


def _pairing_error(error: PairingError) -> MeshError:
    """Map PairingError → Appendix D code (the table carries the HTTP status)."""
    return MeshError(error.code.value, str(error))


async def _json_object(request: Request) -> dict[str, Any]:
    try:
        payload: Any = await request.json()
    except Exception as exc:
        raise MeshError("INVALID_REQUEST", "Request body must be valid JSON.") from exc
    if not isinstance(payload, dict):
        raise MeshError("INVALID_REQUEST", "Request body must be a JSON object.")
    return payload


@router.post("/mesh/v1/pair/complete", tags=["pairing"], status_code=202)
async def pair_complete(request: Request) -> dict[str, str]:
    """API-PAIR-01 (§13.2): claim the open session with an HMAC proof → 202."""
    payload = await _json_object(request)
    _require_fields(
        payload,
        "pair_id",
        "client_nonce",
        "device_name",
        "platform",
        "device_public_key_spki",
        "proof",
    )
    service = request.app.state.pairing
    try:
        service.complete(
            pair_id=str(payload["pair_id"]),
            client_nonce_b64url=str(payload["client_nonce"]),
            device_name=str(payload["device_name"]),
            platform=str(payload["platform"]),
            device_public_key_spki_b64url=str(payload["device_public_key_spki"]),
            proof_b64url=str(payload["proof"]),
        )
    except PairingError as error:
        raise _pairing_error(error) from None
    return {"status": "awaiting_confirmation"}  # §13.2 body; route status 202 below


@router.post("/mesh/v1/pair/status", tags=["pairing"])
async def pair_status(request: Request) -> dict[str, Any]:
    """API-PAIR-02 (§13.2): authenticated status poll (device_id/endpoints
    only when approved)."""
    limiter = request.app.state.limiter
    client_ip = request.client.host if request.client else "unknown"
    if not limiter.allow(f"pair-status:{client_ip}", STATUS_POLL_LIMIT_PER_MIN):
        raise MeshError("RATE_LIMITED", "Poll rate exceeded (§13.8: ≤ 1 Hz).")
    payload = await _json_object(request)
    _require_fields(payload, "pair_id", "client_nonce", "status_proof")
    service = request.app.state.pairing
    try:
        return service.status(
            pair_id=str(payload["pair_id"]),
            client_nonce_b64url=str(payload["client_nonce"]),
            status_proof_b64url=str(payload["status_proof"]),
        )
    except PairingError as error:
        raise _pairing_error(error) from None
