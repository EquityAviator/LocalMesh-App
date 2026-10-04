"""WP-08 integration tests — pairing + auth + tokens + revoke + admin over
the real app (API-PAIR-01/02, API-AUTH-01/02, API-INFO-01, §15.4/§15.6,
FR-PAIR-01/02/04/06, TC-SEC-04 seed).

The public app runs in TOKEN mode (dev_insecure=False, the §17.9 default) so
every authenticated endpoint exercises the real Bearer path.
"""

import asyncio
import sys
import threading
import time
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

from localmesh_agent.admin_app import create_admin_app  # noqa: E402
from localmesh_agent.app import create_app  # noqa: E402
from localmesh_agent.config import Settings  # noqa: E402
from localmesh_agent.security import crypto  # noqa: E402
from localmesh_agent.security.tls import rotate_identity  # noqa: E402


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
    """Build a valid API-PAIR-01 body from the operator QR (§13.2 framing)."""
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


def _status_body(qr: str) -> dict[str, str]:
    query = _qr_query(qr)
    secret = crypto.b64url_decode(query["sec"])
    proof = crypto.status_proof(secret, query["pid"], bytes(range(16)))
    return {
        "pair_id": query["pid"],
        "client_nonce": crypto.b64url_encode(bytes(range(16))),
        "status_proof": crypto.b64url_encode(proof),
    }


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _pair_and_get_token(
    app: Any, client: httpx.AsyncClient, key: ec.EllipticCurvePrivateKey
) -> str:
    """Full §15.4 flow: open (admin action) → complete → approve → token."""
    opened = app.state.pairing.open()
    response = await client.post("/mesh/v1/pair/complete", json=_claim_body(opened.qr, key))
    assert response.status_code == 202, response.text
    device_id = app.state.pairing.approve()
    challenge_response = await client.post("/mesh/v1/auth/challenge", json={"device_id": device_id})
    assert challenge_response.status_code == 200, challenge_response.text
    challenge = challenge_response.json()
    message = crypto.auth_message(
        str(app.state.agent_id), device_id, challenge["challenge_id"], challenge["nonce"]
    )
    signature = key.sign(message, ec.ECDSA(hashes.SHA256()))
    token_response = await client.post(
        "/mesh/v1/auth/token",
        json={
            "device_id": device_id,
            "challenge_id": challenge["challenge_id"],
            "signature": crypto.b64url_encode(signature),
        },
    )
    assert token_response.status_code == 200, token_response.text
    return str(token_response.json()["access_token"])


# -- API-PAIR-01/02 ------------------------------------------------------------


async def test_pair_complete_202_then_status_awaiting(fake_lmstudio: str, tmp_path: Path) -> None:
    app = create_app(make_settings(fake_lmstudio, tmp_path), dev_insecure=False)
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        async with make_client(app) as client:
            opened = app.state.pairing.open()
            response = await client.post(
                "/mesh/v1/pair/complete", json=_claim_body(opened.qr, _device_key())
            )
            assert response.status_code == 202
            assert response.json() == {"status": "awaiting_confirmation"}
            status = await client.post("/mesh/v1/pair/status", json=_status_body(opened.qr))
            assert status.status_code == 200
            body = status.json()
            assert body["status"] == "awaiting_confirmation"
            assert body["agent_id"].startswith("ag_")
            assert "device_id" not in body  # only when approved (§13.2)


async def test_pair_complete_409_when_closed(fake_lmstudio: str, tmp_path: Path) -> None:
    app = create_app(make_settings(fake_lmstudio, tmp_path), dev_insecure=False)
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        async with make_client(app) as client:
            response = await client.post(
                "/mesh/v1/pair/complete",
                json={
                    "pair_id": "pr_x",
                    "client_nonce": "AAAAAAAAAAAAAAAAAAAAAQ",
                    "device_name": "d",
                    "platform": "android",
                    "device_public_key_spki": "AAAA",
                    "proof": "AAAA",
                },
            )
            assert response.status_code == 409
            assert response.json()["error"]["code"] == "PAIRING_CLOSED"


async def test_pair_complete_403_on_second_use_of_secret(
    fake_lmstudio: str, tmp_path: Path
) -> None:
    """FR-PAIR-02 AC: second use of the same secret → 403."""
    app = create_app(make_settings(fake_lmstudio, tmp_path), dev_insecure=False)
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        async with make_client(app) as client:
            opened = app.state.pairing.open()
            body = _claim_body(opened.qr, _device_key())
            first = await client.post("/mesh/v1/pair/complete", json=body)
            assert first.status_code == 202
            second = await client.post("/mesh/v1/pair/complete", json=body)
            assert second.status_code == 403
            assert second.json()["error"]["code"] == "PAIRING_INVALID"


async def test_pair_complete_410_after_ttl(fake_lmstudio: str, tmp_path: Path) -> None:
    """FR-PAIR-02 AC: use after TTL → 410 PAIRING_EXPIRED."""
    app = create_app(make_settings(fake_lmstudio, tmp_path), dev_insecure=False)
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        async with make_client(app) as client:
            opened = app.state.pairing.open()
            body = _claim_body(opened.qr, _device_key())
            # Swap in an advanceable clock for the service only.
            from tests.unit.fake_store import FakeClock

            app.state.pairing.clock = FakeClock.now_stub = None  # type: ignore[attr-defined]
            fake_clock = FakeClock()
            fake_clock.now = int(time.time())
            app.state.pairing.clock = fake_clock  # type: ignore[attr-defined]
            fake_clock.advance(301)
            response = await client.post("/mesh/v1/pair/complete", json=body)
            assert response.status_code == 410
            assert response.json()["error"]["code"] == "PAIRING_EXPIRED"


async def test_pair_complete_lockout_after_five_bad_proofs(
    fake_lmstudio: str, tmp_path: Path
) -> None:
    """§13.8: 5 bad proofs → 429 PAIRING_LOCKED."""
    app = create_app(make_settings(fake_lmstudio, tmp_path), dev_insecure=False)
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        async with make_client(app) as client:
            opened = app.state.pairing.open()
            body = _claim_body(opened.qr, _device_key())
            body["proof"] = crypto.b64url_encode(b"\x00" * 32)
            for i in range(5):
                response = await client.post("/mesh/v1/pair/complete", json=body)
                assert response.status_code == 403, f"attempt {i}"
            sixth = await client.post("/mesh/v1/pair/complete", json=body)
            assert sixth.status_code == 429
            assert sixth.json()["error"]["code"] == "PAIRING_LOCKED"


# -- API-AUTH-01/02 ------------------------------------------------------------


async def test_challenge_anti_enumeration_unknown_device_same_shape(
    fake_lmstudio: str, tmp_path: Path
) -> None:
    """§13.2: challenge returned even for unknown device IDs."""
    app = create_app(make_settings(fake_lmstudio, tmp_path), dev_insecure=False)
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        app.state.limiter.reset()
        async with make_client(app) as client:
            known_key = _device_key()
            token = await _pair_and_get_token(app, client, known_key)
            assert token
            known = await client.post(
                "/mesh/v1/auth/challenge",
                json={"device_id": app.state.pairing.devices.list()[0]["device_id"]},
            )
            unknown = await client.post(
                "/mesh/v1/auth/challenge", json={"device_id": "dv_does_not_exist"}
            )
            assert known.status_code == unknown.status_code == 200
            assert (
                set(known.json())
                == set(unknown.json())
                == {
                    "challenge_id",
                    "nonce",
                    "expires_in",
                }
            )
            assert known.json()["expires_in"] == 30


async def test_challenge_rate_limited_10_per_minute(fake_lmstudio: str, tmp_path: Path) -> None:
    """§13.8: 10/min per source IP and per device_id → 429 RATE_LIMITED."""
    app = create_app(make_settings(fake_lmstudio, tmp_path), dev_insecure=False)
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        app.state.limiter.reset()
        async with make_client(app) as client:
            last = None
            for _ in range(10):
                last = await client.post("/mesh/v1/auth/challenge", json={"device_id": "dv_rate"})
                assert last.status_code == 200
            eleventh = await client.post("/mesh/v1/auth/challenge", json={"device_id": "dv_rate"})
            assert eleventh.status_code == 429
            assert eleventh.json()["error"]["code"] == "RATE_LIMITED"


async def test_auth_token_happy_path_grants_models_access(
    fake_lmstudio: str, tmp_path: Path
) -> None:
    app = create_app(make_settings(fake_lmstudio, tmp_path), dev_insecure=False)
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        app.state.limiter.reset()
        async with make_client(app) as client:
            token = await _pair_and_get_token(app, client, _device_key())
            models = await client.get("/mesh/v1/models", headers=_auth_headers(token))
            assert models.status_code == 200
            assert any(
                m["mesh_model_id"] == "lmstudio::qwen-fake-7b-instruct"
                for m in models.json()["models"]
            )


async def test_auth_token_bad_signature_is_uniform_401(fake_lmstudio: str, tmp_path: Path) -> None:
    app = create_app(make_settings(fake_lmstudio, tmp_path), dev_insecure=False)
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        async with make_client(app) as client:
            key = _device_key()
            opened = app.state.pairing.open()
            await client.post("/mesh/v1/pair/complete", json=_claim_body(opened.qr, key))
            device_id = app.state.pairing.approve()
            challenge = (
                await client.post("/mesh/v1/auth/challenge", json={"device_id": device_id})
            ).json()
            message = crypto.auth_message(
                str(app.state.agent_id), device_id, challenge["challenge_id"], challenge["nonce"]
            )
            signature = key.sign(message + b"tampered", ec.ECDSA(hashes.SHA256()))
            response = await client.post(
                "/mesh/v1/auth/token",
                json={
                    "device_id": device_id,
                    "challenge_id": challenge["challenge_id"],
                    "signature": crypto.b64url_encode(signature),
                },
            )
            assert response.status_code == 401
            assert response.json()["error"]["code"] == "AUTH_FAILED"


async def test_auth_token_reused_challenge_is_401(fake_lmstudio: str, tmp_path: Path) -> None:
    """§17.3: challenges are single-use — replay yields uniform 401."""
    app = create_app(make_settings(fake_lmstudio, tmp_path), dev_insecure=False)
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        async with make_client(app) as client:
            key = _device_key()
            opened = app.state.pairing.open()
            await client.post("/mesh/v1/pair/complete", json=_claim_body(opened.qr, key))
            device_id = app.state.pairing.approve()
            challenge = (
                await client.post("/mesh/v1/auth/challenge", json={"device_id": device_id})
            ).json()
            message = crypto.auth_message(
                str(app.state.agent_id), device_id, challenge["challenge_id"], challenge["nonce"]
            )
            signature = crypto.b64url_encode(key.sign(message, ec.ECDSA(hashes.SHA256())))
            body = {
                "device_id": device_id,
                "challenge_id": challenge["challenge_id"],
                "signature": signature,
            }
            first = await client.post("/mesh/v1/auth/token", json=body)
            assert first.status_code == 200
            replay = await client.post("/mesh/v1/auth/token", json=body)
            assert replay.status_code == 401
            assert replay.json()["error"]["code"] == "AUTH_FAILED"


async def test_revoked_device_valid_signature_gets_403(fake_lmstudio: str, tmp_path: Path) -> None:
    """§13.2: DEVICE_REVOKED only after a *valid* signature (§15.6)."""
    app = create_app(make_settings(fake_lmstudio, tmp_path), dev_insecure=False)
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        async with make_client(app) as client:
            key = _device_key()
            opened = app.state.pairing.open()
            await client.post("/mesh/v1/pair/complete", json=_claim_body(opened.qr, key))
            device_id = app.state.pairing.approve()
            # Issue + revoke BEFORE the token request (§15.6 order).
            app.state.devices.revoke(device_id)
            challenge = (
                await client.post("/mesh/v1/auth/challenge", json={"device_id": device_id})
            ).json()
            message = crypto.auth_message(
                str(app.state.agent_id), device_id, challenge["challenge_id"], challenge["nonce"]
            )
            signature = crypto.b64url_encode(key.sign(message, ec.ECDSA(hashes.SHA256())))
            response = await client.post(
                "/mesh/v1/auth/token",
                json={
                    "device_id": device_id,
                    "challenge_id": challenge["challenge_id"],
                    "signature": signature,
                },
            )
            assert response.status_code == 403
            assert response.json()["error"]["code"] == "DEVICE_REVOKED"


async def test_revoked_device_bearer_token_is_uniform_401(
    fake_lmstudio: str, tmp_path: Path
) -> None:
    """§17.8: after revoke (hashes deleted) the Bearer path must NOT reveal
    revocation — uniform AUTH_FAILED, indistinguishable from unknown."""
    app = create_app(make_settings(fake_lmstudio, tmp_path), dev_insecure=False)
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        app.state.limiter.reset()
        async with make_client(app) as client:
            token = await _pair_and_get_token(app, client, _device_key())
            device_id = app.state.pairing.devices.list()[0]["device_id"]
            assert app.state.devices.revoke(device_id)[0]
            response = await client.get("/mesh/v1/models", headers=_auth_headers(token))
            assert response.status_code == 401
            assert response.json()["error"]["code"] == "AUTH_FAILED"


async def test_missing_bearer_fails_closed_401(fake_lmstudio: str, tmp_path: Path) -> None:
    """SEC-N4: token mode (default) fails closed without credentials."""
    app = create_app(make_settings(fake_lmstudio, tmp_path), dev_insecure=False)
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        async with make_client(app) as client:
            response = await client.get("/mesh/v1/models")
            assert response.status_code == 401
            assert response.json()["error"]["code"] == "AUTH_REQUIRED"


# -- API-INFO-01 + pairing_open -------------------------------------------------


async def test_info_pairing_open_reflects_pairing_mode(fake_lmstudio: str, tmp_path: Path) -> None:
    app = create_app(make_settings(fake_lmstudio, tmp_path), dev_insecure=False)
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        app.state.limiter.reset()
        async with make_client(app) as client:
            closed = await client.get("/mesh/v1/info")
            assert closed.status_code == 200
            assert closed.json()["pairing_open"] is False
            opened = app.state.pairing.open()
            assert opened.qr.startswith("localmesh://pair?v=1&")
            open_response = await client.get("/mesh/v1/info")
            assert open_response.json()["pairing_open"] is True
            assert open_response.json()["api"]["versions"] == ["v1"]


# -- FR-PAIR-06 / TC-SEC-04: revocation kills a running stream ------------------


@pytest.fixture()
def fake_lmstudio_slow() -> Any:
    server = FakeLMStudio(("127.0.0.1", 0), cold_load_ms=2500)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


async def test_revocation_during_stream_ends_with_device_revoked(
    fake_lmstudio_slow: str, tmp_path: Path
) -> None:
    """§15.6/FR-PAIR-06/TC-SEC-04: revoke mid-stream → SSE mesh.error
    DEVICE_REVOKED then close, well within the 5 s bound."""
    app = create_app(make_settings(fake_lmstudio_slow, tmp_path), dev_insecure=False)
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        app.state.limiter.reset()
        async with make_client(app) as client:
            token = await _pair_and_get_token(app, client, _device_key())
            device_id = app.state.pairing.devices.list()[0]["device_id"]

            async def revoke_soon() -> None:
                await asyncio.sleep(0.5)  # stream is inside cold load now
                revoked, cancelled = app.state.devices.revoke(device_id)
                assert revoked and cancelled == 1

            started = time.monotonic()
            revoke_task = asyncio.create_task(revoke_soon())
            lines: list[str] = []
            async with client.stream(
                "POST",
                "/mesh/v1/chat/completions",
                json={
                    "model": "lmstudio::qwen-fake-7b-instruct",
                    "messages": [{"role": "user", "content": "Hi"}],
                    "stream": True,
                },
                headers=_auth_headers(token),
            ) as response:
                assert response.status_code == 200
                async for line in response.aiter_lines():
                    lines.append(line)
            await revoke_task
            elapsed = time.monotonic() - started
            text = "\n".join(lines)
            assert "mesh.error" in text
            assert "DEVICE_REVOKED" in text
            assert "[DONE]" not in text  # terminal failure: no [DONE] (§13.7)
            assert elapsed < 5.0  # FR-PAIR-06 ≤ 5 s


# -- admin listener (ADR-014, §15.4/§15.6/§17.5) --------------------------------


def build_admin(app: Any) -> httpx.AsyncClient:
    data_dir = Path(str(app.state.settings.ensure_data_dir()))
    admin = create_admin_app(
        pairing=app.state.pairing,
        devices=app.state.devices,
        tls_rotate=lambda: rotate_identity(data_dir / "tls").spki_sha256,
        admin_token="test-admin-token",
        admin_port=8444,
    )
    app.state.admin_app = admin  # reachable for anonymous-client negative tests
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=admin),
        base_url="http://127.0.0.1:8444",
        headers={"Authorization": "Bearer test-admin-token", "Host": "127.0.0.1:8444"},
    )


def build_admin_anonymous(app: Any) -> httpx.AsyncClient:
    """Same admin app, NO default Authorization header (negative tests)."""
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app.state.admin_app),
        base_url="http://127.0.0.1:8444",
        headers={"Host": "127.0.0.1:8444"},
    )


async def test_admin_requires_token_and_rejects_bad_host(
    fake_lmstudio: str, tmp_path: Path
) -> None:
    app = create_app(make_settings(fake_lmstudio, tmp_path), dev_insecure=False)
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        async with build_admin(app) as admin:
            # Missing token → 401 (§17.6: header-only, never query strings).
            async with build_admin_anonymous(app) as anonymous:
                no_token = await anonymous.get("/admin/devices")
                assert no_token.status_code == 401
                # Token in the query string must NOT work (§17.6).
                query_trick = await anonymous.get("/admin/devices?token=test-admin-token")
                assert query_trick.status_code == 401
                # Wrong token → 401.
                wrong = await anonymous.get(
                    "/admin/devices", headers={"Authorization": "Bearer nope"}
                )
                assert wrong.status_code == 401
            # DNS-rebinding Host → 403 (ADR-014, TC-SEC-06).
            evil = await admin.get(
                "/admin/devices",
                headers={
                    "Authorization": "Bearer test-admin-token",
                    "Host": "attacker.example:8444",
                },
            )
            assert evil.status_code == 403


async def test_admin_pair_open_pending_approve_flow(fake_lmstudio: str, tmp_path: Path) -> None:
    """§15.4 operator flow over the admin surface."""
    app = create_app(make_settings(fake_lmstudio, tmp_path), dev_insecure=False)
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        async with build_admin(app) as admin:
            opened = await admin.post("/admin/pair/open")
            assert opened.status_code == 200
            qr = opened.json()["qr"]
            assert qr.startswith("localmesh://pair?v=1&")
            pending_before = await admin.get("/admin/pair/pending")
            assert pending_before.json()["state"] == "open"

            key = _device_key()
            async with make_client(app) as client:
                claim = await client.post("/mesh/v1/pair/complete", json=_claim_body(qr, key))
            assert claim.status_code == 202

            pending = await admin.get("/admin/pair/pending")
            body = pending.json()
            assert body["state"] == "claimed"
            assert body["device_name"] == "Pixel 8"
            assert len(body["sas"]) == 6 and body["sas"].isdigit()

            approved = await admin.post("/admin/pair/approve")
            assert approved.status_code == 200
            assert approved.json()["device_id"].startswith("dv_")

            devices = await admin.get("/admin/devices")
            assert len(devices.json()["devices"]) == 1


async def test_admin_revoke_returns_cancel_count(fake_lmstudio: str, tmp_path: Path) -> None:
    app = create_app(make_settings(fake_lmstudio, tmp_path), dev_insecure=False)
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        async with build_admin(app) as admin:
            key = _device_key()
            opened = await admin.post("/admin/pair/open")
            async with make_client(app) as client:
                await client.post(
                    "/mesh/v1/pair/complete", json=_claim_body(opened.json()["qr"], key)
                )
            device_id = (await admin.post("/admin/pair/approve")).json()["device_id"]
            revoked = await admin.post(f"/admin/devices/{device_id}/revoke")
            assert revoked.status_code == 200
            assert revoked.json() == {
                "status": "revoked",
                "device_id": device_id,
                "cancelled_requests": 0,
            }
            unknown = await admin.post("/admin/devices/dv_unknown/revoke")
            assert unknown.status_code == 404


async def test_admin_tls_rotate_returns_new_pin(fake_lmstudio: str, tmp_path: Path) -> None:
    """§17.5 Rotate: explicit endpoint; pin changes; phones must re-pair."""
    app = create_app(make_settings(fake_lmstudio, tmp_path), dev_insecure=False)
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        old_pin = app.state.spki_pin
        async with build_admin(app) as admin:
            rotated = await admin.post("/admin/tls/rotate")
            assert rotated.status_code == 200
            new_pin = rotated.json()["spki_pin"]
            assert new_pin != old_pin
            assert len(new_pin) == 43  # b64url(SHA-256), no padding
