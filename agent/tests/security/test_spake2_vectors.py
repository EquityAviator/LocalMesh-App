"""M9 security tests — SPAKE2+ (RFC 9383) conformance (FR-PAIR-07).

FR-PAIR-07 AC: "RFC-conformant test vectors pass". The vector below is the
RFC 9383 Appendix C P-256-SHA256-HKDF-SHA256-HMAC-SHA256 vector, transcribed
verbatim (Context, idProver=b'client', idVerifier=b'server', fixed w0/w1/x/y).
"""

from __future__ import annotations

import pytest

from localmesh_agent.security import spake2

# -- RFC 9383 Appendix C: P256-SHA256-HKDF-SHA256-HMAC-SHA256 -------------------

CONTEXT = b"SPAKE2+-P256-SHA256-HKDF-SHA256-HMAC-SHA256 Test Vectors"
ID_PROVER = b"client"
ID_VERIFIER = b"server"

W0 = 0xBB8E1BBCF3C48F62C08DB243652AE55D3E5586053FCA77102994F23AD95491B3
W1 = 0x7E945F34D78785B8A3EF44D0DF5A1A97D6B3B460409A345CA7830387A74B1DBA
X = 0xD1232C8E8693D02368976C174E2088851B8365D0D79A9EEE709C6A05A2FAD539
Y = 0x717A72348A182085109C8D3917D6C43D59B224DC6A7FC4F0483232FA6516D8B3

SHARE_P = bytes.fromhex(
    "04ef3bd051bf78a2234ec0df197f7828060fe9856503579bb17330090"
    "42c15c0c1de127727f418b5966afadfdd95a6e4591d171056b333dab9"
    "7a79c7193e341727"
)
SHARE_V = bytes.fromhex(
    "04c0f65da0d11927bdf5d560c69e1d7d939a05b0e88291887d679fcad"
    "ea75810fb5cc1ca7494db39e82ff2f50665255d76173e09986ab46742"
    "c798a9a68437b048"
)
Z = bytes.fromhex(
    "04bbfce7dd7f277819c8da21544afb7964705569bdf12fb92aa3880594"
    "08d50091a0c5f1d3127f56813b5337f9e4e67e2ca633117a4fbd559946"
    "ab474356c41839"
)
V = bytes.fromhex(
    "0458bf27c6bca011c9ce1930e8984a797a3419797b936629a5a937cf2f"
    "11c8b9514b82b993da8a46e664f23db7c01edc87faa530db01c2ee4052"
    "30b18997f16b68"
)
K_MAIN = bytes.fromhex("4c59e1ccf2cfb961aa31bd9434478a1089b56cd11542f53d3576fb6c2a438a29")
K_CONFIRM_P = bytes.fromhex("871ae3f7b78445e34438fb284504240239031c39d80ac23eb5ab9be5ad6db58a")
K_CONFIRM_V = bytes.fromhex("ccd53c7c1fa37b64a462b40db8be101cedcf838950162902054e644b400f1680")
CONFIRM_P = bytes.fromhex("926cc713504b9b4d76c9162ded04b5493e89109f6d89462cd33adc46fda27527")
CONFIRM_V = bytes.fromhex("9747bcc4f8fe9f63defee53ac9b07876d907d55047e6ff2def2e7529089d3e68")
K_SHARED = bytes.fromhex("0c5f8ccd1413423a54f6c1fb26ff01534a87f893779c6e68666d772bfd91f3e7")


def fixed_prover() -> spake2.Prover:
    prover = spake2.Prover(
        CONTEXT, ID_PROVER, ID_VERIFIER, W0.to_bytes(32, "big"), W1.to_bytes(32, "big")
    )
    object.__setattr__(prover, "_x", X)  # RFC vector forces the scalar
    return prover


def fixed_verifier() -> spake2.Verifier:
    verifier = spake2.Verifier(
        CONTEXT, ID_PROVER, ID_VERIFIER, W0.to_bytes(32, "big"), w1=W1.to_bytes(32, "big")
    )
    object.__setattr__(verifier, "_y", Y)  # RFC vector forces the scalar
    return verifier


def test_rfc9383_p256_sha256_vector_verbatim() -> None:
    """The FR-PAIR-07 acceptance criterion: the RFC's own numbers come out."""
    prover = fixed_prover()
    share_p = prover._share_p_bytes()  # noqa: SLF001 — vector test is white-box
    assert share_p == SHARE_P
    verifier = fixed_verifier()
    share_v = verifier._share_v_bytes()  # noqa: SLF001
    assert share_v == SHARE_V

    # Prover side (RFC 9383 A.1): Z/V = x/w1 · (Y − w0·N).
    point_v = spake2._parse_point(SHARE_V)
    base = spake2._add(point_v, spake2._mul(spake2.CURVE_ORDER - W0, spake2._N_POINT))
    assert spake2._uncompress_encode(spake2._mul(X, base)) == Z  # type: ignore[arg-type]
    assert spake2._uncompress_encode(spake2._mul(W1, base)) == V  # type: ignore[arg-type]

    # Verifier side (RFC 9383 A.2): Z = y·(X − w0·M); V = y·L.
    point_p = spake2._parse_point(SHARE_P)
    base_p = spake2._add(point_p, spake2._mul(spake2.CURVE_ORDER - W0, spake2._M_POINT))
    assert spake2._uncompress_encode(spake2._mul(Y, base_p)) == Z  # type: ignore[arg-type]
    assert spake2._uncompress_encode(spake2._mul(Y, verifier._l)) == V  # noqa: SLF001

    # Transcript + key schedule.
    tt = spake2.compute_transcript(
        CONTEXT, ID_PROVER, ID_VERIFIER, SHARE_P, SHARE_V, Z, V, W0.to_bytes(32, "big")
    )
    assert spake2.compute_key_schedule(tt).k_main == K_MAIN
    schedule = spake2.compute_key_schedule(tt)
    assert schedule.k_confirm_p == K_CONFIRM_P
    assert schedule.k_confirm_v == K_CONFIRM_V
    assert schedule.k_shared == K_SHARED
    # Confirmation tags (RFC 9383 §3.4).
    assert spake2.confirm_p_tag(schedule.k_confirm_p, SHARE_V) == CONFIRM_P
    assert spake2.confirm_v_tag(schedule.k_confirm_v, SHARE_P) == CONFIRM_V


def test_prover_finish_verifies_verifier_confirmation() -> None:
    prover = fixed_prover()
    _share_p = prover._share_p_bytes()  # noqa: SLF001
    schedule, confirm_p = prover.finish(SHARE_V)
    assert confirm_p == CONFIRM_P
    assert schedule.k_shared == K_SHARED


def test_verifier_finish_binds_prover_share() -> None:
    verifier = fixed_verifier()
    schedule, confirm_v, expected_confirm_p = verifier.finish(SHARE_P)
    assert confirm_v == CONFIRM_V
    assert expected_confirm_p == CONFIRM_P
    assert schedule.k_shared == K_SHARED


def test_full_roundtrip_random_scalars_agree() -> None:
    """Prover/Verifier roles agree on K_shared and confirmations with fresh
    randomness (the phone↔agent runtime path)."""
    password = "483920"
    salt = b"\x01" * 16
    w0, w1 = spake2.derive_w0_w1(password, salt, iterations=1000)
    context = b"localmesh-pair-manual-v1"
    prover = spake2.Prover(context, ID_PROVER, ID_VERIFIER, w0, w1)
    verifier = spake2.Verifier(context, ID_PROVER, ID_VERIFIER, w0, w1=w1)
    prover_share = prover.start()
    _y, share_v = verifier.start()
    schedule_p, confirm_p = prover.finish(share_v)
    schedule_v, confirm_v, expected_confirm_p = verifier.finish(prover_share.share_p)
    assert schedule_p.k_shared == schedule_v.k_shared
    assert confirm_p == expected_confirm_p  # Verifier validates the Prover
    # The Prover validates the Verifier's tag before treating K_shared as good.
    assert spake2.confirm_v_tag(schedule_p.k_confirm_v, prover_share.share_p) == confirm_v


def test_wrong_password_fails_confirmation() -> None:
    salt = b"\x02" * 16
    w0, w1 = spake2.derive_w0_w1("correct-code", salt, iterations=1000)
    context = b"localmesh-pair-manual-v1"
    prover = spake2.Prover(context, ID_PROVER, ID_VERIFIER, w0, w1)
    prover_share = prover.start()
    # Verifier derives from a DIFFERENT code → tags must mismatch.
    w0_wrong, w1_wrong = spake2.derive_w0_w1("wrong-code", salt, iterations=1000)
    verifier = spake2.Verifier(context, ID_PROVER, ID_VERIFIER, w0_wrong, w1=w1_wrong)
    _y, share_v = verifier.start()
    schedule_p, confirm_p = prover.finish(share_v)
    _schedule_v, _confirm_v, expected_confirm_p = verifier.finish(prover_share.share_p)
    assert confirm_p != expected_confirm_p  # key confirmation catches the mismatch
    assert schedule_p.k_shared != _schedule_v.k_shared


def test_invalid_share_is_rejected() -> None:
    prover = fixed_prover()
    with pytest.raises(ValueError):
        prover.finish(b"\x04" + b"\x00" * 64)  # not a curve point (x=y=0)
    with pytest.raises(ValueError):
        prover.finish(b"garbage")


def test_mn_points_decompress_to_curve() -> None:
    assert spake2.is_on_curve(spake2._M_POINT)
    assert spake2.is_on_curve(spake2._N_POINT)
    # RFC 9383 §3.1: M and N have prime order n (n·M = ∞).
    assert spake2._mul(spake2.CURVE_ORDER, spake2._M_POINT) is None
    assert spake2._mul(spake2.CURVE_ORDER, spake2._N_POINT) is None
