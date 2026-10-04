"""Unit tests for security/pairing.py — SM-PAIR (§15.2) and FR-PAIR-01/02/04.

Uses a tiny in-memory fake Store (the security layer types against the
`adapters.ports.Store` port, §10.1 dependency rule) and an injectable fake
Clock; no SQLite, no asyncio.
"""

import pytest
from tests.unit.fake_store import FakeClock, FakeStore

from localmesh_agent.security import crypto
from localmesh_agent.security.devices import DeviceService
from localmesh_agent.security.pairing import (
    CLAIM_TIMEOUT_S,
    LOCKOUT_COOLDOWN_S,
    MAX_BAD_PROOFS,
    PairingError,
    PairingErrorCode,
    PairingService,
    SessionState,
)

AGENT_ID = "ag_0192f0c1-0000-7000-8000-000000000000"
PIN = "abcd1234efgh5678"
EP = "https://test-pc:8443"


def make_service(
    clock: FakeClock | None = None,
    require_confirmation: bool = True,
    ttl: int = 300,
) -> tuple[PairingService, FakeStore, FakeClock]:
    clock = clock or FakeClock()
    store = FakeStore()
    devices = DeviceService(store)  # type: ignore[arg-type]
    service = PairingService(
        store=store,  # type: ignore[arg-type]
        devices=devices,
        clock=clock,  # type: ignore[arg-type]
        ttl_seconds=ttl,
        require_confirmation=require_confirmation,
        agent_id=AGENT_ID,
        display_name="Test PC",
        spki_pin=PIN,
        endpoints=(EP,),
    )
    return service, store, clock


def claim_params(session: PairingService, opened) -> dict[str, str]:
    """Build a valid pair/complete payload from the operator-side QR."""
    # Parse the QR (§17.4 URI) the way the phone would.
    query = dict(
        part.split("=", 1) for part in opened.qr.removeprefix("localmesh://pair?").split("&")
    )
    secret = crypto.b64url_decode(query["sec"])
    nonce = bytes(range(16))  # any 16 client bytes work
    spki = _spki_der()
    proof = crypto.pairing_proof(secret, AGENT_ID, query["pid"], nonce, spki)
    return {
        "pair_id": query["pid"],
        "client_nonce": crypto.b64url_encode(nonce),
        "device_name": "Pixel 8",
        "platform": "android",
        "spki": spki,
        "proof": crypto.b64url_encode(proof),
        "secret": secret,
    }


def _spki_der() -> bytes:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    key = ec.generate_private_key(ec.SECP256R1())
    return key.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def test_open_creates_single_open_session_with_qr_fields() -> None:
    service, _store, _clock = make_service()
    opened = service.open()
    assert opened.pair_id.startswith("pr_")
    assert opened.qr.startswith("localmesh://pair?")
    assert f"aid={AGENT_ID}" in opened.qr
    assert "n=Test%20PC" in opened.qr
    assert f"fp={PIN}" in opened.qr
    assert f"pid={opened.pair_id}" in opened.qr
    assert "sec=" in opened.qr
    assert "ep=https%3A%2F%2Ftest-pc%3A8443" in opened.qr  # urlencoded endpoint
    state, pending = service.pending()
    assert state is SessionState.OPEN and pending is None
    # Opening again invalidates the previous session (§15.2).
    second = service.open()
    assert second.pair_id != opened.pair_id


def test_complete_happy_path_claims_and_sas_shown() -> None:
    service, _store, _clock = make_service()
    opened = service.open()
    params = claim_params(service, opened)
    service.complete(
        pair_id=params["pair_id"],
        client_nonce_b64url=params["client_nonce"],
        device_name=params["device_name"],
        platform=params["platform"],
        device_public_key_spki_b64url=crypto.b64url_encode(params["spki"]),
        proof_b64url=params["proof"],
    )
    state, pending = service.pending()
    assert state is SessionState.CLAIMED
    assert pending is not None
    assert pending.name == "Pixel 8"
    assert len(pending.sas) == 6 and pending.sas.isdigit()
    # SAS matches the independent derivation from §13.2.
    expected_sas = crypto.sas_code(
        params["secret"], params["pair_id"], bytes(range(16)), params["spki"]
    )
    assert pending.sas == expected_sas


def test_complete_without_open_session_is_pairing_closed() -> None:
    service, _store, _clock = make_service()
    with pytest.raises(PairingError) as excinfo:
        service.complete("pr_x", "AAAA", "d", "android", "AAAA", "AAAA")
    assert excinfo.value.code is PairingErrorCode.PAIRING_CLOSED


def test_single_use_secret_second_complete_is_invalid() -> None:
    """FR-PAIR-02 AC: second use of same secret → 403 PAIRING_INVALID."""
    service, _store, _clock = make_service()
    opened = service.open()
    params = claim_params(service, opened)
    kwargs = dict(
        pair_id=params["pair_id"],
        client_nonce_b64url=params["client_nonce"],
        device_name=params["device_name"],
        platform=params["platform"],
        device_public_key_spki_b64url=crypto.b64url_encode(params["spki"]),
        proof_b64url=params["proof"],
    )
    service.complete(**kwargs)
    with pytest.raises(PairingError) as excinfo:
        service.complete(**kwargs)  # same session claimed again
    assert excinfo.value.code is PairingErrorCode.PAIRING_INVALID


def test_bad_proofs_lock_session_and_cooldown_blocks_open() -> None:
    """§13.8: 5 bad proofs → LOCKED + 15-min cooldown on open."""
    service, _store, clock = make_service()
    opened = service.open()
    params = claim_params(service, opened)
    bad_proof = crypto.b64url_encode(b"\x00" * 32)
    for _ in range(MAX_BAD_PROOFS):
        with pytest.raises(PairingError):
            service.complete(
                pair_id=params["pair_id"],
                client_nonce_b64url=params["client_nonce"],
                device_name="d",
                platform="android",
                device_public_key_spki_b64url=crypto.b64url_encode(params["spki"]),
                proof_b64url=bad_proof,
            )
    assert service.pending()[0] is SessionState.CLOSED  # session torn down
    with pytest.raises(PairingError) as excinfo:
        service.open()
    assert excinfo.value.code is PairingErrorCode.PAIRING_LOCKED
    clock.advance(LOCKOUT_COOLDOWN_S + 1)
    service.open()  # cooldown elapsed — open works again


def test_ttl_expiry_makes_complete_return_expired() -> None:
    """FR-PAIR-02 AC: use after TTL → 410 PAIRING_EXPIRED."""
    service, _store, clock = make_service(ttl=60)
    opened = service.open()
    params = claim_params(service, opened)
    clock.advance(61)
    with pytest.raises(PairingError) as excinfo:
        service.complete(
            pair_id=params["pair_id"],
            client_nonce_b64url=params["client_nonce"],
            device_name="d",
            platform="android",
            device_public_key_spki_b64url=crypto.b64url_encode(params["spki"]),
            proof_b64url=params["proof"],
        )
    assert excinfo.value.code is PairingErrorCode.PAIRING_EXPIRED


def test_claim_timeout_without_approval_consumes_session() -> None:
    """FR-PAIR-04 AC: without confirm within 120 s → pairing fails."""
    service, _store, clock = make_service()
    opened = service.open()
    params = claim_params(service, opened)
    service.complete(
        pair_id=params["pair_id"],
        client_nonce_b64url=params["client_nonce"],
        device_name="d",
        platform="android",
        device_public_key_spki_b64url=crypto.b64url_encode(params["spki"]),
        proof_b64url=params["proof"],
    )
    clock.advance(CLAIM_TIMEOUT_S + 1)
    state, _pending = service.pending()
    assert state is SessionState.CLOSED
    with pytest.raises(PairingError):
        service.approve()


def test_approve_persists_device_and_status_delivery_works() -> None:
    service, store, clock = make_service()
    opened = service.open()
    params = claim_params(service, opened)
    service.complete(
        pair_id=params["pair_id"],
        client_nonce_b64url=params["client_nonce"],
        device_name="Pixel 8",
        platform="android",
        device_public_key_spki_b64url=crypto.b64url_encode(params["spki"]),
        proof_b64url=params["proof"],
    )
    device_id = service.approve()
    assert device_id.startswith("dv_")
    device = store.get_device(device_id)
    assert device is not None
    assert device["public_key_spki"] == params["spki"]  # the approved key
    assert device["scopes"] == "models:read chat"
    # pair/status with a valid status_proof → approved + device_id.
    status_proof = crypto.b64url_encode(
        crypto.status_proof(params["secret"], params["pair_id"], bytes(range(16)))
    )
    result = service.status(
        pair_id=params["pair_id"],
        client_nonce_b64url=params["client_nonce"],
        status_proof_b64url=status_proof,
    )
    assert result["status"] == "approved"
    assert result["device_id"] == device_id
    assert result["agent_id"] == AGENT_ID
    assert result["scopes"] == ["models:read", "chat"]
    assert result["endpoints"] == {"lan": [EP], "tailnet": None}
    # Delivery window (60 s) then the session closes (§15.2).
    clock.advance(61)
    state, _pending = service.pending()
    assert state is SessionState.CLOSED


def test_deny_is_observable_via_status() -> None:
    service, store, _clock = make_service()
    opened = service.open()
    params = claim_params(service, opened)
    service.complete(
        pair_id=params["pair_id"],
        client_nonce_b64url=params["client_nonce"],
        device_name="d",
        platform="android",
        device_public_key_spki_b64url=crypto.b64url_encode(params["spki"]),
        proof_b64url=params["proof"],
    )
    service.deny()
    status_proof = crypto.b64url_encode(
        crypto.status_proof(params["secret"], params["pair_id"], bytes(range(16)))
    )
    result = service.status(
        pair_id=params["pair_id"],
        client_nonce_b64url=params["client_nonce"],
        status_proof_b64url=status_proof,
    )
    assert result["status"] == "denied"
    assert "device_id" not in result  # only when approved (§13.2)
    assert store.devices == {}  # denied device is never persisted


def test_status_with_bad_proof_is_invalid() -> None:
    service, _store, _clock = make_service()
    opened = service.open()
    params = claim_params(service, opened)
    service.complete(
        pair_id=params["pair_id"],
        client_nonce_b64url=params["client_nonce"],
        device_name="d",
        platform="android",
        device_public_key_spki_b64url=crypto.b64url_encode(params["spki"]),
        proof_b64url=params["proof"],
    )
    with pytest.raises(PairingError) as excinfo:
        service.status(
            pair_id=params["pair_id"],
            client_nonce_b64url=params["client_nonce"],
            status_proof_b64url=crypto.b64url_encode(b"\x00" * 32),
        )
    assert excinfo.value.code is PairingErrorCode.PAIRING_INVALID


def test_require_confirmation_false_auto_approves() -> None:
    """FR-PAIR-04: confirmation configurable; off → claim approves."""
    service, store, _clock = make_service(require_confirmation=False)
    opened = service.open()
    params = claim_params(service, opened)
    service.complete(
        pair_id=params["pair_id"],
        client_nonce_b64url=params["client_nonce"],
        device_name="d",
        platform="android",
        device_public_key_spki_b64url=crypto.b64url_encode(params["spki"]),
        proof_b64url=params["proof"],
    )
    state, _pending = service.pending()
    assert state is SessionState.APPROVED
    assert len(store.devices) == 1


def test_pairing_open_flag_tracks_usable_session() -> None:
    """API-INFO-01 `pairing_open` (§13.2)."""
    service, _store, clock = make_service(ttl=60)
    assert service.pairing_open() is False
    service.open()
    assert service.pairing_open() is True
    clock.advance(61)
    assert service.pairing_open() is False  # TTL elapsed


def test_qr_secret_never_reaches_audit_or_store() -> None:
    """§17.6: the pairing secret never touches disk/logs — the audit trail
    must not contain it either."""
    service, store, _clock = make_service()
    opened = service.open()
    query = dict(
        part.split("=", 1) for part in opened.qr.removeprefix("localmesh://pair?").split("&")
    )
    secret = query["sec"]
    for event, _device, _meta in store.audit:
        assert secret not in event
    assert store.devices == {}
