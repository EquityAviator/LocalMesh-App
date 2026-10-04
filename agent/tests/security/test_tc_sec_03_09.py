"""TC-SEC-03 + TC-SEC-09 — formal §17.13 security test entries (LM-ARCH-001
§17.13: "TC-SEC-03 replayed pairing/auth fails · TC-SEC-09 rate-limit/lockout
behaviour"; must exist before M9).

TC-SEC-03 — every captured wire artifact, replayed, fails CLOSED:
  a. pairing claim (proof) replay → first use 202, replay 403 (secret
     single-use, §15.2: secret destroyed on CLAIM)
  b. valid proof after the session LOCKED → 429 PAIRING_LOCKED (§13.8:
     5 bad proofs → lockout rejects even correct proofs during cooldown)
  c. auth signature replay against a FRESH challenge → uniform 401
     AUTH_FAILED (challenge nonce is bound into the signed message, §13.2
     API-AUTH-02; a captured signature cannot satisfy a new nonce)
  d. auth challenge reuse (same challenge answered twice) → 401
  e. Bearer token replay after device revocation → 401 (hash deleted,
     §17.8: revocation is indistinguishable from expiry on the wire)

TC-SEC-09 — rate-limit/lockout behaviour:
  f. GET /info 31st request inside the window → 429 RATE_LIMITED (§13.8:
     30/min per source IP), envelope-shaped error body
  g. POST /auth/challenge 11th request inside the window → 429 (per-IP
     dimension; the per-device_id dimension shares the limiter, key
     independence is unit-covered in test_tokens.py)

These entries deliberately overlap single behaviours already asserted in
tests/integration/test_pairing_auth.py — §17.13 requires NAMED, traceable
entries; each test below is tagged with its TC-SEC id and the spec clause.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Any

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

TOOLS_FAKE = Path(__file__).resolve().parents[3] / "tools" / "fake-backends"
if str(TOOLS_FAKE) not in sys.path:
    sys.path.insert(0, str(TOOLS_FAKE))

from fake_lmstudio import FakeLMStudio  # noqa: E402

from localmesh_agent.app import create_app  # noqa: E402
from localmesh_agent.config import Settings  # noqa: E402
from localmesh_agent.security import crypto  # noqa: E402


@pytest.fixture()
def fake_lmstudio() -> Any:
    server = FakeLMStudio(("127.0.0.1", 0), cold_load_ms=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def make_settings(base_url: str, data_dir: Path) -> Settings:
    return Settings(
        agent={"data_dir": str(data_dir)},
        backends=[{"id": "lmstudio", "kind": "lmstudio", "base_url": base_url}],
    )


def make_client(app: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")


def _device_key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


def _spki_b64url(key: ec.EllipticCurvePrivateKey) -> str:
    spki = key.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return crypto.b64url_encode(spki)


def _qr_query(qr: str) -> dict[str, str]:
    return dict(part.split("=", 1) for part in qr.removeprefix("localmesh://pair?").split("&"))


def _claim_body(qr: str, key: ec.EllipticCurvePrivateKey) -> dict[str, str]:
    """Valid API-PAIR-01 body (§13.2 framing; nonce fixed for reproducibility)."""
    query = _qr_query(qr)
    secret = crypto.b64url_decode(query["sec"])
    nonce = bytes(range(16))
    spki = key.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    proof = crypto.pairing_proof(secret, query["aid"], query["pid"], nonce, spki)
    return {
        "pair_id": query["pid"],
        "client_nonce": crypto.b64url_encode(nonce),
        "device_name": "Pixel 8",
        "platform": "android",
        "device_public_key_spki": crypto.b64url_encode(spki),
        "proof": crypto.b64url_encode(proof),
    }


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _challenge_and_token(
    app: Any,
    client: httpx.AsyncClient,
    key: ec.EllipticCurvePrivateKey,
    device_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Fetch a challenge and return (challenge, token-request-body)."""
    challenge_response = await client.post("/mesh/v1/auth/challenge", json={"device_id": device_id})
    assert challenge_response.status_code == 200, challenge_response.text
    challenge = challenge_response.json()
    message = crypto.auth_message(
        str(app.state.agent_id), device_id, challenge["challenge_id"], challenge["nonce"]
    )
    signature = key.sign(message, ec.ECDSA(hashes.SHA256()))
    body = {
        "device_id": device_id,
        "challenge_id": challenge["challenge_id"],
        "signature": crypto.b64url_encode(signature),
    }
    return challenge, body


async def _pair_approve_get_token(
    app: Any, client: httpx.AsyncClient, key: ec.EllipticCurvePrivateKey
) -> tuple[str, str]:
    """Full §15.4 flow; returns (access_token, device_id)."""
    opened = app.state.pairing.open()
    claim = await client.post("/mesh/v1/pair/complete", json=_claim_body(opened.qr, key))
    assert claim.status_code == 202, claim.text
    device_id = app.state.pairing.approve()
    _challenge, body = await _challenge_and_token(app, client, key, device_id)
    token_response = await client.post("/mesh/v1/auth/token", json=body)
    assert token_response.status_code == 200, token_response.text
    return str(token_response.json()["access_token"]), device_id


# -- TC-SEC-03 -----------------------------------------------------------------


async def test_tc_sec_03a_pairing_proof_replay_fails(fake_lmstudio: str, tmp_path: Path) -> None:
    """Captured claim replayed against the (destroyed) session → 403."""
    app = create_app(make_settings(fake_lmstudio, tmp_path), dev_insecure=False)
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        async with make_client(app) as client:
            opened = app.state.pairing.open()
            body = _claim_body(opened.qr, _device_key())
            first = await client.post("/mesh/v1/pair/complete", json=body)
            assert first.status_code == 202
            replay = await client.post("/mesh/v1/pair/complete", json=body)
            assert replay.status_code == 403, replay.text
            assert replay.json()["error"]["request_id"]


async def test_tc_sec_03b_valid_proof_rejected_while_locked(
    fake_lmstudio: str, tmp_path: Path
) -> None:
    """§13.8 lockout: 5 bad proofs → LOCKED; a CORRECT proof is 429 too."""
    app = create_app(make_settings(fake_lmstudio, tmp_path), dev_insecure=False)
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        async with make_client(app) as client:
            opened = app.state.pairing.open()
            good_body = _claim_body(opened.qr, _device_key())
            bad = dict(good_body)
            bad["proof"] = crypto.b64url_encode(b"\x00" * 64)
            for _ in range(5):
                bad_response = await client.post("/mesh/v1/pair/complete", json=bad)
                assert bad_response.status_code in (400, 401, 403), bad_response.text
            locked = await client.post("/mesh/v1/pair/complete", json=good_body)
            assert locked.status_code == 429, locked.text
            assert locked.json()["error"]["code"] == "PAIRING_LOCKED"


async def test_tc_sec_03c_captured_signature_fails_fresh_challenge(
    fake_lmstudio: str, tmp_path: Path
) -> None:
    """Replay attack: a captured (challenge_id, signature) pair cannot
    authenticate against a NEW challenge — the nonce is bound in
    (§13.2 API-AUTH-02)."""
    app = create_app(make_settings(fake_lmstudio, tmp_path), dev_insecure=False)
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        async with make_client(app) as client:
            key = _device_key()
            token, device_id = await _pair_approve_get_token(app, client, key)
            assert token

            # Capture a challenge + matching signature, do NOT submit.
            _challenge, captured_body = await _challenge_and_token(app, client, key, device_id)

            # Fresh challenge (new nonce, new challenge_id) + replayed signature.
            fresh = await client.post("/mesh/v1/auth/challenge", json={"device_id": device_id})
            assert fresh.status_code == 200
            fresh_challenge = fresh.json()
            replay = await client.post(
                "/mesh/v1/auth/token",
                json={
                    "device_id": device_id,
                    "challenge_id": fresh_challenge["challenge_id"],
                    "signature": captured_body["signature"],
                },
            )
            assert replay.status_code == 401, replay.text
            assert replay.json()["error"]["code"] == "AUTH_FAILED"


async def test_tc_sec_03d_challenge_answered_twice_is_401(
    fake_lmstudio: str, tmp_path: Path
) -> None:
    """Single-use challenges (§17.3): the SECOND valid answer fails."""
    app = create_app(make_settings(fake_lmstudio, tmp_path), dev_insecure=False)
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        async with make_client(app) as client:
            key = _device_key()
            token, device_id = await _pair_approve_get_token(app, client, key)
            assert token
            _challenge, body = await _challenge_and_token(app, client, key, device_id)
            first = await client.post("/mesh/v1/auth/token", json=body)
            assert first.status_code == 200
            second = await client.post("/mesh/v1/auth/token", json=body)
            assert second.status_code == 401, second.text


async def test_tc_sec_03e_token_replay_after_revocation_is_401(
    fake_lmstudio: str, tmp_path: Path
) -> None:
    """§17.8: a captured Bearer token stops working the moment the Device
    is revoked — the hash is deleted (uniform 401, no information leak)."""
    app = create_app(make_settings(fake_lmstudio, tmp_path), dev_insecure=False)
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        async with make_client(app) as client:
            key = _device_key()
            token, device_id = await _pair_approve_get_token(app, client, key)
            headers = _auth_headers(token)
            ok = await client.get("/mesh/v1/models", headers=headers)
            assert ok.status_code == 200
            app.state.devices.revoke(device_id)
            replay = await client.get("/mesh/v1/models", headers=headers)
            assert replay.status_code == 401, replay.text
            assert replay.json()["error"]["code"] in ("AUTH_FAILED", "TOKEN_EXPIRED")


# -- TC-SEC-09 -----------------------------------------------------------------


async def test_tc_sec_09a_info_rate_limited_30_per_minute(
    fake_lmstudio: str, tmp_path: Path
) -> None:
    """§13.8: GET /info 30/min per source IP → the 31st is 429 RATE_LIMITED."""
    app = create_app(make_settings(fake_lmstudio, tmp_path), dev_insecure=False)
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        async with make_client(app) as client:
            for _ in range(30):
                ok = await client.get("/mesh/v1/info")
                assert ok.status_code == 200
            limited = await client.get("/mesh/v1/info")
            assert limited.status_code == 429, limited.text
            assert limited.json()["error"]["code"] == "RATE_LIMITED"


async def test_tc_sec_09b_challenge_rate_limited_10_per_minute(
    fake_lmstudio: str, tmp_path: Path
) -> None:
    """§13.8: /auth/challenge 10/min per IP AND per device_id → 429."""
    app = create_app(make_settings(fake_lmstudio, tmp_path), dev_insecure=False)
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        async with make_client(app) as client:
            key = _device_key()
            token, device_id = await _pair_approve_get_token(app, client, key)
            assert token
            # NOTE: the pairing flow already consumed ONE challenge (§13.8
            # counts every challenge request); 9 more reach exactly 10/min.
            for _ in range(9):
                ok = await client.post("/mesh/v1/auth/challenge", json={"device_id": device_id})
                assert ok.status_code == 200
            limited = await client.post("/mesh/v1/auth/challenge", json={"device_id": device_id})
            assert limited.status_code == 429, limited.text
            assert limited.json()["error"]["code"] == "RATE_LIMITED"
            # /info is a DIFFERENT limiter bucket — unaffected (isolation).
            info_ok = await client.get("/mesh/v1/info")
            assert info_ok.status_code == 200
