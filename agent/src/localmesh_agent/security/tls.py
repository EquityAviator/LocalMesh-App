"""self-signed cert gen, SPKI pin calc, load/rotate (§10.1, ADR-006).

Implements the WP-07 subset of §17.3/§17.5 (M2):

- **Create** (first run): ECDSA **P-256** key + self-signed X.509 cert,
  long validity (10 y `[DESIGN]` per §17.3 "e.g. 10 y"), SAN =
  `localmesh-agent` + configured hostnames/IPs `[DESIGN]`; persisted
  owner-only (§17.6: `tls/key.pem` owner-only, never logged/backed up).
- **Pin**: SHA-256 over the DER `SubjectPublicKeyInfo` of the leaf cert,
  encoded **base64url without padding** (§17.3; Appendix C trap "Standard
  Base64 in protocol fields").
- **Renew**: re-issue the certificate **with the same key** ⇒ pin unchanged
  ⇒ no re-pair (§17.5).
- **Rotate**: a NEW key is generated **only on explicit request** (doctor
  `--rotate-tls` / `POST /admin/tls/rotate`, §17.5); the caller owns the
  revoke-all-devices prompt.
- **Never** auto-regenerate silently on corruption (§10.7): load failures
  raise `TlsIdentityError` with an actionable message; the public listener
  refuses to start (wired by the app/CLI, not here).

TLS 1.3-only serving (§17.3) is wired by the CLI through
`build_tls13_server_context` (defined here since WP-15 so the TC-SEC-10
entry can handshake against the exact production context).
"""

from __future__ import annotations

import base64
import hashlib
import os
import ssl
import stat
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

# §17.3: self-signed X.509, ECDSA P-256, long validity ("e.g. 10 y").
CERT_VALIDITY_DAYS = 3650
# §17.3 SAN [DESIGN]: identity name + discovered hostnames/IPs (configured).
DEFAULT_SAN_DNS = ("localmesh-agent",)
# Small backdate tolerates client clock skew [DESIGN, not spec'd].
_NOT_BEFORE_BACKDATE = timedelta(hours=1)

KEY_FILENAME = "key.pem"
CERT_FILENAME = "cert.pem"


class TlsIdentityError(RuntimeError):
    """Raised when the TLS identity cannot be loaded (§10.7: refuse to start
    the public listener; never silently regenerate)."""


@dataclass(frozen=True)
class TlsIdentity:
    """Loaded Agent TLS identity (§10.6 step 3)."""

    key_pem: bytes
    cert_pem: bytes
    spki_sha256: str  # the pin: b64url(SHA-256(DER SPKI)), no padding

    @property
    def pin_prefix(self) -> str:
        """Short fingerprint for logs — never the full key material (§10.6)."""
        return self.spki_sha256[:12]


def b64url_nopad(raw: bytes) -> str:
    """§17.3 encoding rule: base64url WITHOUT padding everywhere."""
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def compute_pin(cert_pem: bytes) -> str:
    """SHA-256 over the DER SubjectPublicKeyInfo of the leaf cert (§17.3)."""
    cert = x509.load_pem_x509_certificate(cert_pem)
    spki_der = cert.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return b64url_nopad(hashlib.sha256(spki_der).digest())


def public_spki_der(cert_pem: bytes) -> bytes:
    """The leaf certificate's public key as DER SPKI (§12.2 CP `public_key`).

    M6: the Control Plane stores the Agent's public key (`bytea` SPKI DER);
    the pairing QR already pins its SHA-256 (`fp`, §17.4) — this helper is the
    single place that derives the pre-image so pin and CP key can never drift.
    """
    cert = x509.load_pem_x509_certificate(cert_pem)
    return cert.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def _generate_key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())  # §17.3: P-256


def _build_cert(
    key: ec.EllipticCurvePrivateKey,
    *,
    common_name: str,
    san_dns: tuple[str, ...],
    san_ips: tuple[str, ...],
    not_after: datetime,
) -> x509.Certificate:
    """Self-signed leaf per §17.3 [DESIGN SAN set]: no CA trust used."""
    from ipaddress import IPv4Address

    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    names: list[x509.GeneralName] = [x509.DNSName(n) for n in san_dns]
    names += [x509.IPAddress(IPv4Address(ip)) for ip in san_ips]
    now = datetime.now(UTC)
    return (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)  # self-signed
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - _NOT_BEFORE_BACKDATE)
        .not_valid_after(not_after)
        .add_extension(
            x509.SubjectAlternativeName(names),
            critical=False,
        )
        .add_extension(
            x509.BasicConstraints(ca=False, path_length=None),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .sign(key, hashes.SHA256())  # §17.3: ECDSA with SHA-256
    )


def generate_identity(
    *,
    common_name: str = "localmesh-agent",
    san_dns: tuple[str, ...] = DEFAULT_SAN_DNS,
    san_ips: tuple[str, ...] = (),
    validity_days: int = CERT_VALIDITY_DAYS,
) -> TlsIdentity:
    """Create a fresh key + self-signed cert (§17.5 Create; §17.3 params)."""
    key = _generate_key()
    not_after = datetime.now(UTC) + timedelta(days=validity_days)
    cert = _build_cert(
        key,
        common_name=common_name,
        san_dns=san_dns,
        san_ips=san_ips,
        not_after=not_after,
    )
    key_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    return TlsIdentity(key_pem=key_pem, cert_pem=cert_pem, spki_sha256=compute_pin(cert_pem))


def renew_identity(key_pem: bytes, *, cert_pem: bytes) -> TlsIdentity:
    """Re-issue the certificate **with the same key** (§17.5 Renew) — the pin
    is unchanged, so paired Phones need no re-pair.

    `cert_pem` is passed only for validation: the existing certificate must
    correspond to `key_pem`; otherwise the caller is not renewing but
    replacing an unrelated identity (refused).
    """
    key = serialization.load_pem_private_key(key_pem, password=None)
    if not isinstance(key, ec.EllipticCurvePrivateKey):  # pragma: no cover
        raise TlsIdentityError("TLS key is not an EC private key (§17.3).")
    existing = x509.load_pem_x509_certificate(cert_pem)
    existing_spki = existing.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    current_spki = key.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    if existing_spki != current_spki:
        raise TlsIdentityError(
            "Refusing to renew: the on-disk certificate belongs to a "
            "different key (§17.5). Use an explicit rotate instead."
        )
    common_name_attr = existing.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0]
    common_name = (
        common_name_attr.value.decode("utf-8")
        if isinstance(common_name_attr.value, bytes)
        else str(common_name_attr.value)
    )
    not_after = datetime.now(UTC) + timedelta(days=CERT_VALIDITY_DAYS)
    cert = _build_cert(
        key,
        common_name=common_name,
        san_dns=tuple(
            existing.extensions.get_extension_for_class(
                x509.SubjectAlternativeName
            ).value.get_values_for_type(x509.DNSName)
        ),
        san_ips=tuple(
            str(i)
            for i in existing.extensions.get_extension_for_class(
                x509.SubjectAlternativeName
            ).value.get_values_for_type(x509.IPAddress)
        ),
        not_after=not_after,
    )
    cert_pem_new = cert.public_bytes(serialization.Encoding.PEM)
    return TlsIdentity(
        key_pem=key_pem,
        cert_pem=cert_pem_new,
        spki_sha256=compute_pin(cert_pem_new),
    )


def load_identity(tls_dir: Path) -> TlsIdentity:
    """Load the persisted identity; raise `TlsIdentityError` on any problem.

    §10.7: a corrupt/expired identity is NEVER silently regenerated — the
    caller refuses to start the public listener and `doctor` offers explicit
    rotation (§17.5).
    """
    key_path = tls_dir / KEY_FILENAME
    cert_path = tls_dir / CERT_FILENAME
    if not key_path.is_file() or not cert_path.is_file():
        raise TlsIdentityError(
            f"TLS identity files missing in {tls_dir} "
            f"(expected {KEY_FILENAME} + {CERT_FILENAME}). Run the agent once "
            "to create them, or restore a backup."
        )
    key_pem = key_path.read_bytes()
    cert_pem = cert_path.read_bytes()
    try:
        key = serialization.load_pem_private_key(key_pem, password=None)
    except (ValueError, TypeError) as exc:
        raise TlsIdentityError(
            f"TLS private key is corrupt or unreadable: {key_path} "
            "(§10.7: not auto-regenerating — pins would break). Restore the "
            "file or run an explicit rotation."
        ) from exc
    if not isinstance(key, ec.EllipticCurvePrivateKey):
        raise TlsIdentityError(f"TLS private key in {key_path} is not ECDSA P-256 (§17.3).")
    try:
        cert = x509.load_pem_x509_certificate(cert_pem)
    except ValueError as exc:
        raise TlsIdentityError(
            f"TLS certificate is corrupt: {cert_path} (§10.7: not "
            "auto-regenerating). Restore the file or rotate explicitly."
        ) from exc
    # §10.7: expired cert -> refuse to start (actionable, explicit).
    not_after = cert.not_valid_after_utc
    if datetime.now(UTC) >= not_after:
        raise TlsIdentityError(
            f"TLS certificate expired at {not_after.isoformat()} (§10.7: "
            "refusing to start; renew with the same key to keep pins valid)."
        )
    pin = compute_pin(cert_pem)
    return TlsIdentity(key_pem=key_pem, cert_pem=cert_pem, spki_sha256=pin)


def _chmod_owner_only(path: Path) -> None:
    """§17.6: owner-only key file (POSIX 0600; Windows ACL completion is the
    installer's job at M9, §21.6 — noted in the milestone report)."""
    if os.name != "nt":
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def load_or_create_identity(
    tls_dir: Path,
    *,
    common_name: str = "localmesh-agent",
    san_dns: tuple[str, ...] = DEFAULT_SAN_DNS,
    san_ips: tuple[str, ...] = (),
) -> TlsIdentity:
    """§10.6 step 3 / §17.5: create on first run, load afterwards.

    Expired certs renew WITH THE SAME KEY (pin unchanged, §17.5); corrupt
    material raises (never silent regeneration, §10.7).
    """
    key_path = tls_dir / KEY_FILENAME
    cert_path = tls_dir / CERT_FILENAME
    if key_path.is_file() and cert_path.is_file():
        try:
            identity = load_identity(tls_dir)
        except TlsIdentityError as exc:
            if "expired" not in str(exc):
                raise
            # Expired: renew with the same key (§17.5 Renew) — pin unchanged.
            identity = renew_identity(key_path.read_bytes(), cert_pem=cert_path.read_bytes())
            cert_path.write_bytes(identity.cert_pem)
            _chmod_owner_only(cert_path)
            return identity
        return identity
    if key_path.is_file() or cert_path.is_file():
        # Half-identity: refuse rather than guess (§10.7 spirit).
        raise TlsIdentityError(
            f"Incomplete TLS identity in {tls_dir}: exactly one of "
            f"{KEY_FILENAME}/{CERT_FILENAME} exists. Restore or remove both, "
            "then re-run."
        )
    identity = generate_identity(common_name=common_name, san_dns=san_dns, san_ips=san_ips)
    tls_dir.mkdir(parents=True, exist_ok=True)
    key_path.write_bytes(identity.key_pem)
    cert_path.write_bytes(identity.cert_pem)
    _chmod_owner_only(key_path)  # §17.6: owner-only private key
    return identity


def rotate_identity(tls_dir: Path) -> TlsIdentity:
    """Explicit key rotation (§17.5 Rotate) — pin CHANGES; every paired Phone
    will show PIN_MISMATCH and must re-pair. Called only from
    `doctor --rotate-tls` or `POST /admin/tls/rotate`."""
    identity = generate_identity()
    tls_dir.mkdir(parents=True, exist_ok=True)
    (tls_dir / KEY_FILENAME).write_bytes(identity.key_pem)
    (tls_dir / CERT_FILENAME).write_bytes(identity.cert_pem)
    _chmod_owner_only(tls_dir / KEY_FILENAME)
    return identity


def build_tls13_server_context(cert_path: str, key_path: str) -> ssl.SSLContext:
    """TLS 1.3-ONLY server context loading the Agent identity (§17.3).

    The public listener negotiates TLS 1.3 or nothing: `minimum_version` is
    pinned to `TLSVersion.TLSv1_3`, so TLS 1.2 (and older) clients fail the
    handshake closed. There is no upper bound to configure — TLS 1.3 is the
    protocol ceiling. Wired into uvicorn via `ssl_context_factory` by the CLI
    (§17.3) and asserted by the TC-SEC-10 entry (§17.13,
    `tests/security/test_tc_sec_10_tls13.py`) with real handshakes.
    """
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    context.load_cert_chain(cert_path, key_path)
    return context
