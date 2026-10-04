"""Unit tests for security/crypto.py (WP-08, §17.3/§13.2).

The framing vectors are computed independently with the standard library in
the test body (hmac/struct), so the production code is not self-verifying.
"""

import hashlib
import hmac as hmac_mod
import struct

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from localmesh_agent.security import crypto


def _reference_lp(value: bytes) -> bytes:
    return struct.pack(">I", len(value)) + value


def test_lp_framing_is_four_byte_be_length_plus_bytes() -> None:
    assert crypto.lp(b"") == b"\x00\x00\x00\x00"
    assert crypto.lp(b"abc") == b"\x00\x00\x00\x03abc"
    long = b"x" * 300
    assert crypto.lp(long) == struct.pack(">I", 300) + long


def test_pairing_proof_matches_independent_hmac_computation() -> None:
    """API-PAIR-01 framing, computed independently (§13.2 verbatim)."""
    secret = bytes(range(32))
    agent_id = "ag_0192f0c1-0000-7000-8000-000000000000"
    pair_id = "pr_AAAAAAAAAAAAAAA"
    nonce = b"\x01" * 16
    spki = b"\x02" * 91

    expected = hmac_mod.new(
        secret,
        _reference_lp(b"localmesh-pair-v1")
        + _reference_lp(agent_id.encode())
        + _reference_lp(pair_id.encode())
        + _reference_lp(nonce)
        + _reference_lp(spki),
        hashlib.sha256,
    ).digest()
    assert crypto.pairing_proof(secret, agent_id, pair_id, nonce, spki) == expected


def test_status_proof_matches_independent_hmac_computation() -> None:
    secret = b"\x03" * 32
    pair_id = "pr_BBBBBBBBBBBBBBB"
    nonce = b"\x04" * 16
    expected = hmac_mod.new(
        secret,
        _reference_lp(b"localmesh-status-v1")
        + _reference_lp(pair_id.encode())
        + _reference_lp(nonce),
        hashlib.sha256,
    ).digest()
    assert crypto.status_proof(secret, pair_id, nonce) == expected


def test_sas_code_is_six_digits_zero_padded_and_in_range() -> None:
    secret = b"\x05" * 32
    sas = crypto.sas_code(secret, "pr_C", b"\x06" * 16, b"\x07" * 91)
    assert len(sas) == 6
    assert sas.isdigit()
    # Deterministic for the same inputs; differs for a different nonce.
    assert crypto.sas_code(secret, "pr_C", b"\x06" * 16, b"\x07" * 91) == sas
    assert crypto.sas_code(secret, "pr_C", b"\x08" * 16, b"\x07" * 91) != sas


def test_sas_matches_reference_modulo_derivation() -> None:
    secret = b"\x09" * 32
    pair_id = "pr_D"
    nonce = b"\x0a" * 16
    spki = b"\x0b" * 91
    digest = hmac_mod.new(
        secret,
        _reference_lp(b"localmesh-sas-v1")
        + _reference_lp(pair_id.encode())
        + _reference_lp(nonce)
        + _reference_lp(spki),
        hashlib.sha256,
    ).digest()
    expected = f"{struct.unpack('>I', digest[:4])[0] % 1_000_000:06d}"
    assert crypto.sas_code(secret, pair_id, nonce, spki) == expected


def test_b64url_roundtrip_without_padding_and_rejects_standard_base64() -> None:
    raw = bytes(range(256))
    encoded = crypto.b64url_encode(raw)
    assert "=" not in encoded
    assert "+" not in encoded and "/" not in encoded
    assert crypto.b64url_decode(encoded) == raw
    # Standard-Base64 alphabet is rejected (Appendix C trap).
    with pytest.raises(crypto.EncodingError):
        crypto.b64url_decode("AB+C/")
    with pytest.raises(crypto.EncodingError):
        crypto.b64url_decode("")


def test_constant_time_eq_matches_semantics() -> None:
    assert crypto.constant_time_eq(b"same", b"same")
    assert not crypto.constant_time_eq(b"same", b"other")
    assert not crypto.constant_time_eq(b"same", b"sam")


def test_auth_message_is_newline_joined_utf8_with_b64url_nonce() -> None:
    """§13.2 message construction — the b64url nonce string reading
    (QUESTION-103): raw bytes would not be valid UTF-8."""
    message = crypto.auth_message("ag_X", "dv_Y", "ch_Z", "nonce-b64url")
    assert message == b"localmesh-auth-v1\nag_X\ndv_Y\nch_Z\nnonce-b64url"


def _generated_key_spki() -> tuple[ec.EllipticCurvePrivateKey, bytes]:
    key = ec.generate_private_key(ec.SECP256R1())
    spki = key.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return key, spki


def test_verify_device_signature_accepts_valid_and_rejects_tampered() -> None:
    key, spki = _generated_key_spki()
    message = b"localmesh-auth-v1\nag_X\ndv_Y\nch_Z\nnonce"
    signature = key.sign(message, ec.ECDSA(hashes.SHA256()))
    assert crypto.verify_device_signature(spki, message, signature)
    assert not crypto.verify_device_signature(spki, message + b"x", signature)
    assert not crypto.verify_device_signature(spki, message, signature[:-3] + b"\x00\x00\x00")


def test_verify_device_signature_rejects_non_p256_and_garbage() -> None:
    key384 = ec.generate_private_key(ec.SECP384R1())
    spki384 = key384.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    signature = key384.sign(b"m", ec.ECDSA(hashes.SHA256()))
    # P-384 keys are refused (ADR-008: P-256 only).
    assert not crypto.verify_device_signature(spki384, b"m", signature)
    assert not crypto.verify_device_signature(b"not-a-key", b"m", b"\x30\x00")


def test_sha256_token_hash_is_over_presented_bytes() -> None:
    token = "abc123"
    assert crypto.sha256_token_hash(token) == hashlib.sha256(b"abc123").digest()
