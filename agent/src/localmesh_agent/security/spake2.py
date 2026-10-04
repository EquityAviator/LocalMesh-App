"""SPAKE2+ (RFC 9383) — manual-code pairing (M9, FR-PAIR-07; ADR-007).

Ciphersuite: P256-SHA256-HKDF-SHA256-HMAC-SHA256 (RFC 9383 Table 1).
FR-PAIR-07 acceptance criterion — "RFC-conformant test vectors pass" — is
enforced by tests/security/test_spake2_vectors.py against the RFC's own
Appendix C vectors (P-256/SHA-256 suite).

Role split (ADR-007: SPAKE2+ is reserved for the typed-code fallback; the QR
path stays HMAC-based): the PHONE is the Prover (w0, w1 from the typed code),
the AGENT is the Verifier (w0 + L = w1·G). The PBKDF that maps the typed code
to (w0, w1) is NOT part of the ciphersuite (RFC 9383 §4); `derive_w0_w1`
provides PBKDF2-HMAC-SHA256 as the [DESIGN] default.

Curve arithmetic is a minimal, self-contained P-256 implementation (affine
Jacobian-free double-and-add) — the `cryptography` library does not expose
raw point ops on P-256. The module is constant-memory, allocation-light and
test-vector-verified; point validation (`is_on_curve`, subgroup membership
via cofactor 1) is enforced on received shares per RFC 9383 §3.1.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

# -- P-256 (secp256r1) domain parameters --------------------------------------

P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
A = P - 3
B = 0x5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604B
GX = 0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296
GY = 0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5
CURVE_ORDER = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551  # n
COFACTOR = 1  # prime-order group for P-256 (RFC 9383 §3.1 h=1)

# RFC 9383 Appendix B seeds for P-256 (compressed SEC1 points, §4/Table 1).
M_COMPRESSED = bytes.fromhex("02886e2f97ace46e55ba9dd7242579f2993b64e16ef3dcab95afd497333d8fa12f")
N_COMPRESSED = bytes.fromhex("03d8bbd6c639c62937b04d997f38c3770719c629d7014d49a24b4f98baa1292b49")

# -- minimal P-256 point arithmetic (affine, None = point at infinity) --------


def _inv(value: int, mod: int = P) -> int:
    return pow(value, -1, mod)


def _add(p1: tuple[int, int] | None, p2: tuple[int, int] | None) -> tuple[int, int] | None:
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    x1, y1 = p1
    x2, y2 = p2
    if x1 == x2 and (y1 + y2) % P == 0:
        return None
    if p1 == p2:
        lam = (3 * x1 * x1 + A) * _inv(2 * y1) % P
    else:
        lam = (y2 - y1) * _inv(x2 - x1) % P
    x3 = (lam * lam - x1 - x2) % P
    y3 = (lam * (x1 - x3) - y1) % P
    return x3, y3


def _mul(scalar: int, point: tuple[int, int] | None) -> tuple[int, int] | None:
    result: tuple[int, int] | None = None
    addend = point
    while scalar:
        if scalar & 1:
            result = _add(result, addend)
        addend = _add(addend, addend)
        scalar >>= 1
    return result


G = (GX, GY)
_M_POINT: tuple[int, int] | None = None
_N_POINT: tuple[int, int] | None = None


def _decompress(data: bytes) -> tuple[int, int]:
    """SEC1 compressed point → affine point (sqrt via p ≡ 3 mod 4)."""
    if data[0] not in (0x02, 0x03):
        raise ValueError("not a compressed point")
    x = int.from_bytes(data[1:], "big")
    alpha = (pow(x, 3, P) + A * x + B) % P
    y = pow(alpha, (P + 1) // 4, P)
    if (y * y) % P != alpha:
        raise ValueError("x is not on the curve")
    if (y % 2) != (data[0] & 1):
        y = P - y
    return x, y


def _uncompress_encode(point: tuple[int, int]) -> bytes:
    x, y = point
    return b"\x04" + x.to_bytes(32, "big") + y.to_bytes(32, "big")


def _parse_point(data: bytes) -> tuple[int, int] | None:
    """Parse a received point share. RFC 9383 uses the UNCOMPRESSED format
    for shares (§Appendix C) and compressed for the M/N seeds (§Appendix B);
    both are accepted here defensively."""
    if len(data) == 65 and data[0] == 0x04:
        x = int.from_bytes(data[1:33], "big")
        y = int.from_bytes(data[33:], "big")
        point = (x, y)
        return point if is_on_curve(point) else None
    if len(data) == 33 and data[0] in (0x02, 0x03):
        try:
            return _decompress(data)
        except ValueError:
            return None
    return None


def is_on_curve(point: tuple[int, int] | None) -> bool:
    if point is None:
        return False
    x, y = point
    return (y * y - (pow(x, 3, P) + A * x + B)) % P == 0


# Decompress the RFC M/N seeds once, after the helpers above are defined.
_M_POINT = _decompress(M_COMPRESSED)
_N_POINT = _decompress(N_COMPRESSED)


# -- transcript + key schedule (RFC 9383 §3.3/A.3/A.4) -------------------------


def _len8(data: bytes) -> bytes:
    """8-byte length prefix. RFC 9383 vectors show LITTLE-endian lengths."""
    return len(data).to_bytes(8, "little")


def compute_transcript(
    context: bytes,
    id_prover: bytes,
    id_verifier: bytes,
    share_p: bytes,
    share_v: bytes,
    z: bytes,
    v: bytes,
    w0: bytes,
) -> bytes:
    """RFC 9383 A.3 — TT over the M/N/share/Z/V/w0 byte strings.

    The Appendix C vectors show M and N entering TT in the UNCOMPRESSED
    (0x04-prefixed, 65-byte) encoding — the compressed form is only used in
    Appendix B for seed publication."""
    # Fail-closed guard: _M_POINT/_N_POINT are set at import (below); the
    # `| None` annotation exists only for the pre-init window. mypy --strict
    # requires the narrowing, and a None here must never become a TypeError
    # deep in the transcript math.
    if _M_POINT is None or _N_POINT is None:  # pragma: no cover — import-time init
        raise RuntimeError("SPAKE2+ M/N constants failed to initialize")
    m_uncompressed = _uncompress_encode(_M_POINT)
    n_uncompressed = _uncompress_encode(_N_POINT)
    return (
        _len8(context)
        + context
        + _len8(id_prover)
        + id_prover
        + _len8(id_verifier)
        + id_verifier
        + _len8(m_uncompressed)
        + m_uncompressed
        + _len8(n_uncompressed)
        + n_uncompressed
        + _len8(share_p)
        + share_p
        + _len8(share_v)
        + share_v
        + _len8(z)
        + z
        + _len8(v)
        + v
        + _len8(w0)
        + w0
    )


def _kdf(nil_salt: bytes, ikm: bytes, info: bytes, length: int) -> bytes:
    _ = nil_salt
    hkdf = HKDF(algorithm=hashes.SHA256(), length=length, salt=None, info=info)
    return hkdf.derive(ikm)


def _mac(key: bytes, message: bytes) -> bytes:
    return hmac.new(key, message, hashlib.sha256).digest()


@dataclass(frozen=True)
class KeySchedule:
    k_main: bytes
    k_confirm_p: bytes
    k_confirm_v: bytes
    k_shared: bytes


def compute_key_schedule(tt: bytes) -> KeySchedule:
    """RFC 9383 A.4 — K_main = Hash(TT); confirmation + shared keys via KDF."""
    k_main = hashlib.sha256(tt).digest()
    both = _kdf(b"", k_main, b"ConfirmationKeys", 64)
    k_confirm_p, k_confirm_v = both[:32], both[32:]
    k_shared = _kdf(b"", k_main, b"SharedKey", 32)
    return KeySchedule(k_main, k_confirm_p, k_confirm_v, k_shared)


def confirm_p_tag(k_confirm_p: bytes, share_v: bytes) -> bytes:
    return _mac(k_confirm_p, share_v)  # RFC 9383: confirmP = MAC(K_confirmP, shareV)


def confirm_v_tag(k_confirm_v: bytes, share_p: bytes) -> bytes:
    return _mac(k_confirm_v, share_p)  # RFC 9383: confirmV = MAC(K_confirmV, shareP)


# -- PBKDF (RFC 9383 §4: outside the ciphersuite; PBKDF2 is the [DESIGN] pick) --


def derive_w0_w1(password: str, salt: bytes, *, iterations: int = 100_000) -> tuple[bytes, bytes]:
    """Typed code → (w0, w1), each reduced into [1, n-1] (RFC 9383 §3.1)."""
    material = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations, dklen=64)
    w0_raw = int.from_bytes(material[:32], "big") % CURVE_ORDER
    w1_raw = int.from_bytes(material[32:], "big") % CURVE_ORDER
    w0 = w0_raw if w0_raw > 0 else 1
    w1 = w1_raw if w1_raw > 0 else 1
    return w0.to_bytes(32, "big"), w1.to_bytes(32, "big")


# -- roles ----------------------------------------------------------------------


@dataclass(frozen=True)
class ProverShare:
    x_private: bytes  # scalar, kept secret
    share_p: bytes  # wire: uncompressed SEC1 point


class Prover:
    """The phone (knows w0, w1 — RFC 9383 A.1)."""

    def __init__(
        self, context: bytes, id_prover: bytes, id_verifier: bytes, w0: bytes, w1: bytes
    ) -> None:
        self._context = context
        self._id_prover = id_prover
        self._id_verifier = id_verifier
        self._w0 = w0
        self._w1 = w1
        self._x: int | None = None

    def start(self) -> ProverShare:
        """ProverInit: x ← random; X = x·G + w0·M."""
        self._x = int.from_bytes(os.urandom(32), "big") % CURVE_ORDER
        while self._x == 0:  # pragma: no cover — astronomically unlikely
            self._x = int.from_bytes(os.urandom(32), "big") % CURVE_ORDER
        point = _add(_mul(self._x, G), _mul(int.from_bytes(self._w0, "big"), _M_POINT))
        assert point is not None and is_on_curve(point)
        return ProverShare(self._x.to_bytes(32, "big"), _uncompress_encode(point))

    def finish(self, share_v: bytes) -> tuple[KeySchedule, bytes]:
        """ProverFinish: Z = x·(Y − w0·N); V = w1·(Y − w0·N); verify confirmV.

        Returns (key schedule, own confirmP tag). Raises ValueError when the
        Verifier's share is invalid or its confirmation tag mismatches.
        """
        if self._x is None:
            raise ValueError("start() was not called")
        point = _parse_point(share_v)
        if point is None:
            raise ValueError("invalid Verifier share")
        # RFC 9383 A.1 ProverFinish: Z = x·(Y − w0·N); V = w1·(Y − w0·N).
        base = _add(point, _mul(CURVE_ORDER - int.from_bytes(self._w0, "big"), _N_POINT))
        z = _mul(self._x, base)
        v = _mul(int.from_bytes(self._w1, "big"), base)
        tt = compute_transcript(
            self._context,
            self._id_prover,
            self._id_verifier,
            self._share_p_bytes(),
            share_v,
            _uncompress_encode(z) if z else b"",
            _uncompress_encode(v) if v else b"",
            self._w0,
        )
        schedule = compute_key_schedule(tt)
        _ = schedule.k_confirm_p  # the Prover sends confirmP below
        return schedule, confirm_p_tag(schedule.k_confirm_p, share_v)

    def _share_p_bytes(self) -> bytes:
        if self._x is None:
            raise ValueError("start() was not called")
        point = _add(_mul(self._x, G), _mul(int.from_bytes(self._w0, "big"), _M_POINT))
        assert point is not None
        return _uncompress_encode(point)


class Verifier:
    """The agent (knows w0 and L = w1·G — RFC 9383 A.2)."""

    def __init__(
        self,
        context: bytes,
        id_prover: bytes,
        id_verifier: bytes,
        w0: bytes,
        l_point: bytes | None = None,
        w1: bytes | None = None,
    ) -> None:
        self._context = context
        self._id_prover = id_prover
        self._id_verifier = id_verifier
        self._w0 = w0
        if l_point is not None:
            self._l = _parse_point(l_point)
        elif w1 is not None:
            self._l = _mul(int.from_bytes(w1, "big"), G)
        else:
            raise ValueError("either l_point or w1 is required")

    def start(self) -> tuple[bytes, bytes]:
        """VerifierInit: y ← random; Y = y·G + w0·N. Returns (y_private, shareV)."""
        self._y = int.from_bytes(os.urandom(32), "big") % CURVE_ORDER
        while self._y == 0:  # pragma: no cover
            self._y = int.from_bytes(os.urandom(32), "big") % CURVE_ORDER
        point = _add(_mul(self._y, G), _mul(int.from_bytes(self._w0, "big"), _N_POINT))
        assert point is not None and is_on_curve(point)
        return self._y.to_bytes(32, "big"), _uncompress_encode(point)

    def finish(self, share_p: bytes) -> tuple[KeySchedule, bytes, bytes]:
        """VerifierFinish on the Prover's share: Z = y·(X − w0·M); V = y·L.

        Returns (key schedule, own confirmV tag, expected confirmP tag the
        Prover must present). Raises ValueError on an invalid share.
        """
        if getattr(self, "_y", None) is None:
            raise ValueError("start() was not called")
        point = _parse_point(share_p)
        if point is None:
            raise ValueError("invalid Prover share")
        base = _add(point, _mul(CURVE_ORDER - int.from_bytes(self._w0, "big"), _M_POINT))
        z = _mul(self._y, base)
        v = _mul(self._y, self._l)
        tt = compute_transcript(
            self._context,
            self._id_prover,
            self._id_verifier,
            share_p,
            self._share_v_bytes(),
            _uncompress_encode(z) if z else b"",
            _uncompress_encode(v) if v else b"",
            self._w0,
        )
        schedule = compute_key_schedule(tt)
        return (
            schedule,
            confirm_v_tag(schedule.k_confirm_v, share_p),
            confirm_p_tag(schedule.k_confirm_p, self._share_v_bytes()),
        )

    def _share_v_bytes(self) -> bytes:
        point = _add(_mul(self._y, G), _mul(int.from_bytes(self._w0, "big"), _N_POINT))
        assert point is not None
        return _uncompress_encode(point)
