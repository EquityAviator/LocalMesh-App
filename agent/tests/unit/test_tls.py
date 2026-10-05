"""WP-07 unit tests — TLS identity + pin calc (§17.3, §17.5, §17.6, §10.7).

Covers: pin encoding (base64url no padding), create→load stability, renew
with same key (pin unchanged ⇒ no re-pair), explicit rotate (pin changes),
owner-only key file (§17.6), corruption/expiry refusal (§10.7), SAN/params
(§17.3).
"""

import base64
import hashlib
import re
import stat
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography import x509

from localmesh_agent.security.tls import (
    CERT_FILENAME,
    CERT_VALIDITY_DAYS,
    KEY_FILENAME,
    TlsIdentityError,
    compute_pin,
    generate_identity,
    load_identity,
    load_or_create_identity,
    renew_identity,
    rotate_identity,
)


def test_pin_is_base64url_no_padding() -> None:
    """§17.3: b64url WITHOUT padding, everywhere (Appendix C trap)."""
    identity = generate_identity()
    pin = identity.spki_sha256
    assert "=" not in pin, "padding must be stripped (§17.3 encoding rule)"
    assert "+" not in pin and "/" not in pin, "must be URL-safe alphabet"
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", pin), "SHA-256 → 32 bytes → 43 unpadded b64url chars"


def test_pin_matches_manual_der_spki_hash() -> None:
    """Pin = SHA-256 over the DER SubjectPublicKeyInfo (§17.3, normative)."""
    identity = generate_identity()
    cert = x509.load_pem_x509_certificate(identity.cert_pem)
    from cryptography.hazmat.primitives import serialization

    spki_der = cert.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(spki_der).digest()).decode("ascii").rstrip("=")
    )
    assert compute_pin(identity.cert_pem) == expected
    assert identity.spki_sha256 == expected


def test_create_then_load_same_pin(tmp_path: Path) -> None:
    """§17.5 Create: persisted identity reloads with the SAME pin."""
    identity = load_or_create_identity(tmp_path)
    assert (tmp_path / KEY_FILENAME).is_file()
    assert (tmp_path / CERT_FILENAME).is_file()
    reloaded = load_or_create_identity(tmp_path)
    assert reloaded.spki_sha256 == identity.spki_sha256
    assert reloaded.key_pem == identity.key_pem  # same key, not regenerated


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission check")
def test_key_file_owner_only(tmp_path: Path) -> None:
    """§17.6: TLS private key file is owner-only (0600)."""
    load_or_create_identity(tmp_path)
    mode = stat.S_IMODE((tmp_path / KEY_FILENAME).stat().st_mode)
    assert mode == stat.S_IRUSR | stat.S_IWUSR, f"expected 0600, got {oct(mode)}"


def test_cert_params_per_spec(tmp_path: Path) -> None:
    """§17.3: ECDSA P-256, self-signed, ~10 y validity, SAN localmesh-agent."""
    identity = load_or_create_identity(tmp_path)
    cert = x509.load_pem_x509_certificate(identity.cert_pem)
    public_key = cert.public_key()
    assert public_key.curve.name == "secp256r1"  # P-256
    assert cert.issuer == cert.subject  # self-signed
    assert (
        cert.subject.get_attributes_for_oid(x509.NameOID.COMMON_NAME)[0].value == "localmesh-agent"
    )
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert "localmesh-agent" in san.get_values_for_type(x509.DNSName)
    duration = cert.not_valid_after_utc - cert.not_valid_before_utc
    assert duration.days >= CERT_VALIDITY_DAYS - 2  # long validity ("e.g. 10 y")


def test_renew_same_key_pin_unchanged(tmp_path: Path) -> None:
    """§17.5 Renew: re-issue cert with the SAME key ⇒ pin unchanged."""
    identity = generate_identity()
    renewed = renew_identity(identity.key_pem, cert_pem=identity.cert_pem)
    assert renewed.spki_sha256 == identity.spki_sha256
    assert renewed.key_pem == identity.key_pem
    old_cert = x509.load_pem_x509_certificate(identity.cert_pem)
    new_cert = x509.load_pem_x509_certificate(renewed.cert_pem)
    assert new_cert.serial_number != old_cert.serial_number  # fresh cert


def test_renew_refuses_unrelated_key() -> None:
    """Renewing must not silently replace an unrelated identity (§17.5)."""
    a = generate_identity()
    b = generate_identity()
    with pytest.raises(TlsIdentityError):
        renew_identity(b.key_pem, cert_pem=a.cert_pem)


def test_rotate_changes_pin(tmp_path: Path) -> None:
    """§17.5 Rotate: NEW key ⇒ pin CHANGES (phones must re-pair)."""
    old = load_or_create_identity(tmp_path)
    new = rotate_identity(tmp_path)
    assert new.spki_sha256 != old.spki_sha256
    assert new.key_pem != old.key_pem
    # Rotation persists; reload sees the new identity.
    assert load_identity(tmp_path).spki_sha256 == new.spki_sha256


def test_corrupt_key_refuses_and_never_regenerates(tmp_path: Path) -> None:
    """§10.7: corrupt identity → explicit error, NOT silent regeneration."""
    load_or_create_identity(tmp_path)
    (tmp_path / KEY_FILENAME).write_bytes(b"not a key")
    with pytest.raises(TlsIdentityError) as excinfo:
        load_or_create_identity(tmp_path)
    assert "corrupt" in str(excinfo.value)
    # The corrupt file is untouched — no silent regeneration.
    assert (tmp_path / KEY_FILENAME).read_bytes() == b"not a key"


def test_expired_cert_is_detected(tmp_path: Path) -> None:
    """§10.7: expired cert → refuse (actionable message, no regeneration)."""
    expired_identity = generate_identity()
    # Forge an already-expired certificate by re-signing with the same key.
    from cryptography import x509 as _x509
    from cryptography.hazmat.primitives import hashes, serialization

    key = serialization.load_pem_private_key(expired_identity.key_pem, password=None)
    old_cert = _x509.load_pem_x509_certificate(expired_identity.cert_pem)
    expired_cert = (
        _x509.CertificateBuilder()
        .subject_name(old_cert.subject)
        .issuer_name(old_cert.issuer)
        .public_key(key.public_key())
        .serial_number(_x509.random_serial_number())
        .not_valid_before(datetime.now(UTC) - timedelta(days=30))
        .not_valid_after(datetime.now(UTC) - timedelta(days=1))
        .add_extension(
            _x509.SubjectAlternativeName([_x509.DNSName("localmesh-agent")]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    (tmp_path / KEY_FILENAME).write_bytes(expired_identity.key_pem)
    (tmp_path / CERT_FILENAME).write_bytes(expired_cert.public_bytes(serialization.Encoding.PEM))
    with pytest.raises(TlsIdentityError) as excinfo:
        load_identity(tmp_path)
    assert "expired" in str(excinfo.value)


def test_expired_cert_auto_renews_with_same_key(tmp_path: Path) -> None:
    """§17.5 Renew path: expired cert is re-issued WITH THE SAME KEY via
    load_or_create — pin unchanged, files refreshed."""
    identity = generate_identity()
    old_pin = identity.spki_sha256
    # Write an expired certificate (same key) directly.
    from cryptography import x509 as _x509
    from cryptography.hazmat.primitives import hashes, serialization

    key = serialization.load_pem_private_key(identity.key_pem, password=None)
    old_cert = _x509.load_pem_x509_certificate(identity.cert_pem)
    expired = (
        _x509.CertificateBuilder()
        .subject_name(old_cert.subject)
        .issuer_name(old_cert.issuer)
        .public_key(key.public_key())
        .serial_number(_x509.random_serial_number())
        .not_valid_before(datetime.now(UTC) - timedelta(days=30))
        .not_valid_after(datetime.now(UTC) - timedelta(days=1))
        .add_extension(
            _x509.SubjectAlternativeName([_x509.DNSName("localmesh-agent")]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    (tmp_path / KEY_FILENAME).write_bytes(identity.key_pem)
    (tmp_path / CERT_FILENAME).write_bytes(expired.public_bytes(serialization.Encoding.PEM))
    renewed = load_or_create_identity(tmp_path)
    assert renewed.spki_sha256 == old_pin  # §17.5: no re-pair needed
    assert (tmp_path / CERT_FILENAME).read_bytes() == renewed.cert_pem


def test_half_identity_refused(tmp_path: Path) -> None:
    """Only one of key/cert present → refuse rather than guess (§10.7)."""
    identity = generate_identity()
    (tmp_path / KEY_FILENAME).write_bytes(identity.key_pem)
    with pytest.raises(TlsIdentityError) as excinfo:
        load_or_create_identity(tmp_path)
    assert "Incomplete" in str(excinfo.value)


def test_missing_identity_gives_actionable_error(tmp_path: Path) -> None:
    """§10.7: missing files → actionable error naming the directory."""
    with pytest.raises(TlsIdentityError) as excinfo:
        load_identity(tmp_path / "nope")
    assert "restore" in str(excinfo.value).lower()


def test_pin_prefix_never_leaks_full_key(tmp_path: Path) -> None:
    """§10.6 step 7: logs carry the fingerprint PREFIX, not key material."""
    identity = load_or_create_identity(tmp_path)
    assert len(identity.pin_prefix) == 12
    assert identity.pin_prefix in identity.spki_sha256
    assert identity.key_pem not in identity.spki_sha256.encode()
