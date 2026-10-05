"""HMAC, ECDSA verify, SAS derivation, constant-time compare (§10.1, ADR-008).

Implements the WP-08 subset of §17.3 (binding) for the pairing and auth
protocols:

- **LP() framing** (§13.2): `LP(x)` = 4-byte big-endian length ‖ bytes —
  unambiguous framing for every HMAC message.
- **Pairing proof** (API-PAIR-01): `HMAC_SHA256(pairing_secret,
  LP("localmesh-pair-v1") ‖ LP(agent_id) ‖ LP(pair_id) ‖ LP(client_nonce_bytes)
  ‖ LP(device_public_key_spki_der))`.
- **Status proof** (API-PAIR-02): `HMAC_SHA256(pairing_secret,
  LP("localmesh-status-v1") ‖ LP(pair_id) ‖ LP(client_nonce_bytes))`.
- **SAS** (§13.2): 6-digit zero-padded code derived from
  `HMAC_SHA256(pairing_secret, LP("localmesh-sas-v1") ‖ LP(pair_id) ‖
  LP(client_nonce_bytes) ‖ LP(device_public_key_spki_der))`.
- **Device key verify** (ADR-008 / API-AUTH-02): ECDSA **P-256**, SHA-256
  digest, **DER** signature over the UTF-8 challenge message.
- **Constant-time compare** (§17.3 "Never … compare secrets with `==`").

Encoding rule (§17.3): all binary-in-JSON/URL values are base64url WITHOUT
padding; standard Base64 is never mixed in.

Interpretations of the two underspecified message details (recorded in
docs/OPEN_QUESTIONS.md as QUESTION-103, conservative readings):

- String identifiers (`agent_id`, `pair_id`, `device_id`, `challenge_id`) are
  framed as their UTF-8 bytes verbatim (including the `ag_`/`pr_`/`dv_`/`ch_`
  prefixes); `client_nonce` and SPKI/DER values are framed as raw bytes.
- The auth message (§13.2 API-AUTH-02) is plain `"\n"`-joined UTF-8 text, so
  the `nonce` component is the **base64url (no padding) string** as issued —
  raw 32 random bytes are not valid UTF-8 and would break the "(UTF-8)"
  property the spec assigns to the whole message.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac as hmac_mod
import struct

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

# Domain-separation labels (§17.3: "domain labels").
PAIR_LABEL = b"localmesh-pair-v1"
STATUS_LABEL = b"localmesh-status-v1"
SAS_LABEL = b"localmesh-sas-v1"
AUTH_LABEL_PREFIX = "localmesh-auth-v1\n"  # §13.2: "\n"-joined UTF-8 message

# Pairing Secret / Device Token / challenge nonce sizes (§17.3).
PAIRING_SECRET_BYTES = 32  # CSPRNG 32 bytes, single-use, memory only
TOKEN_BYTES = 32  # Device Token: 32 random bytes b64url (ADR-008)
CHALLENGE_NONCE_BYTES = 32  # auth challenge nonce (§17.3)
CLIENT_NONCE_BYTES = 16  # API-PAIR-01: client_nonce = b64url 16B

SAS_MODULUS = 1_000_000  # §13.2: uint32 mod 1_000_000, zero-padded to 6 digits


class EncodingError(ValueError):
    """Raised when a protocol field is not valid base64url (no padding)."""


def lp(value: bytes) -> bytes:
    """`LP(x)` = 4-byte big-endian length ‖ bytes (§13.2 framing, unambiguous)."""
    return struct.pack(">I", len(value)) + value


def b64url_encode(raw: bytes) -> str:
    """§17.3 encoding rule: base64url WITHOUT padding."""
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def b64url_decode(value: str) -> bytes:
    """Decode base64url with or without padding; rejects standard-Base64 input
    (+/ characters, Appendix C trap "Standard Base64 in protocol fields")."""
    if not value:
        raise EncodingError("empty base64url value")
    if "+" in value or "/" in value:
        raise EncodingError("standard Base64 alphabet is not allowed (§17.3)")
    padded = value + "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(padded.encode("ascii"))
    except (binascii.Error, ValueError, UnicodeEncodeError) as exc:
        raise EncodingError(f"invalid base64url value: {exc}") from exc


def constant_time_eq(a: bytes, b: bytes) -> bool:
    """§17.3: never compare secrets with `==` (timing side channel)."""
    return hmac_mod.compare_digest(a, b)


def hmac_sha256(key: bytes, message: bytes) -> bytes:
    """HMAC-SHA-256 (§17.3 row "Pairing proof / SAS / status proof")."""
    return hmac_mod.new(key, message, hashlib.sha256).digest()


def pairing_proof(
    secret: bytes,
    agent_id: str,
    pair_id: str,
    client_nonce_bytes: bytes,
    device_public_key_spki_der: bytes,
) -> bytes:
    """API-PAIR-01 proof value (§13.2 framing, verbatim)."""
    message = (
        lp(PAIR_LABEL)
        + lp(agent_id.encode("utf-8"))
        + lp(pair_id.encode("utf-8"))
        + lp(client_nonce_bytes)
        + lp(device_public_key_spki_der)
    )
    return hmac_sha256(secret, message)


def status_proof(secret: bytes, pair_id: str, client_nonce_bytes: bytes) -> bytes:
    """API-PAIR-02 status_proof value (§13.2 framing, verbatim)."""
    message = lp(STATUS_LABEL) + lp(pair_id.encode("utf-8")) + lp(client_nonce_bytes)
    return hmac_sha256(secret, message)


def sas_code(
    secret: bytes,
    pair_id: str,
    client_nonce_bytes: bytes,
    device_public_key_spki_der: bytes,
) -> str:
    """6-digit zero-padded SAS (§13.2: uint32_be(digest[0:4]) mod 1_000_000)."""
    message = (
        lp(SAS_LABEL)
        + lp(pair_id.encode("utf-8"))
        + lp(client_nonce_bytes)
        + lp(device_public_key_spki_der)
    )
    digest = hmac_sha256(secret, message)
    value = struct.unpack(">I", digest[:4])[0] % SAS_MODULUS
    return f"{value:06d}"


def auth_message(agent_id: str, device_id: str, challenge_id: str, nonce_b64url: str) -> bytes:
    """API-AUTH-02 signed message (§13.2 verbatim construction, UTF-8)."""
    text = f"{AUTH_LABEL_PREFIX}{agent_id}\n{device_id}\n{challenge_id}\n{nonce_b64url}"
    return text.encode("utf-8")


def verify_device_signature(
    device_public_key_spki_der: bytes, message: bytes, signature_der: bytes
) -> bool:
    """Verify an ECDSA P-256 / SHA-256 / DER signature (ADR-008, §17.3).

    Returns False (never raises) for unknown key formats or bad signatures —
    the caller maps every failure to the uniform AUTH_FAILED (API-AUTH-02).
    """
    try:
        public_key = serialization.load_der_public_key(device_public_key_spki_der)
        if not isinstance(public_key, ec.EllipticCurvePublicKey):
            return False
        if not isinstance(public_key.curve, ec.SECP256R1):
            return False  # P-256 only (ADR-008: broad hardware support)
        public_key.verify(signature_der, message, ec.ECDSA(hashes.SHA256()))
    except (InvalidSignature, ValueError, TypeError):
        return False
    return True


def sha256_token_hash(token: str) -> bytes:
    """SHA-256 over the exact bytes the client presents as its token (§14.1
    `tokens.token_hash`; §10.4 "store SHA-256 of token only")."""
    return hashlib.sha256(token.encode("utf-8")).digest()
