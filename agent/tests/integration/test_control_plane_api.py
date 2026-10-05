"""M6 Control Plane integration tests (§12, §13.1 admin surface).

Exercises the operator flows end-to-end over the real app factory + admin
app: `POST /admin/control-plane/register`, the `/admin/status` block, the
revocation mirror fan-out on `DELETE /admin/devices/{id}`, and the §12.3
failure mode (CP down ⇒ Agent unaffected).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from tests.integration.test_admin_conformance import ADMIN, make_admin_client, make_settings

from localmesh_agent.adapters.controlplane import SupabaseControlPlaneClient
from localmesh_agent.admin_app import create_admin_app
from localmesh_agent.app import create_app
from localmesh_agent.config import Settings

CP_CALLS: list[dict[str, Any]] = []


def _fake_cp_handler(request: httpx.Request) -> httpx.Response:
    """Minimal fake of the Supabase REST/Edge surface (QUESTION-107 shapes)."""
    CP_CALLS.append(
        {"method": request.method, "url": str(request.url), "body": request.content.decode("utf-8")}
    )
    if request.url.path == "/functions/v1/register-agent":
        return httpx.Response(200, json={"device_id": "cp-row-it-1"})
    return httpx.Response(200, json=[], headers={"Content-Range": "*/1"})


@pytest.fixture()
def cp_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    """App factory with `[control_plane] enabled=true` and a fake CP transport."""
    CP_CALLS.clear()
    monkeypatch.setattr("keyring.get_password", lambda service, ref: "cp-secret")

    real_client = SupabaseControlPlaneClient

    def patched_client(base_url: str, api_key: str, **kwargs: Any) -> SupabaseControlPlaneClient:
        kwargs.pop("transport", None)
        return real_client(base_url, api_key, transport=httpx.MockTransport(_fake_cp_handler))

    monkeypatch.setattr("localmesh_agent.app.SupabaseControlPlaneClient", patched_client)
    settings = Settings(
        agent={"data_dir": str(tmp_path)},
        backends=[],
        control_plane={
            "enabled": True,
            "url": "https://cp.test",
            "auth_ref": "cp-key",
            "heartbeat_interval_s": 3600,
        },
    )
    app = create_app(settings, dev_insecure=False)
    state = app.state
    admin = create_admin_app(
        pairing=state.pairing,
        devices=state.devices,
        tls_rotate=lambda: "new-pin",
        admin_token="test-admin-token",
        admin_port=8444,
        doctor_fn=lambda: [],
        status_fn=lambda: {},  # block checked via app-level unit tests
        metrics_fn=lambda: "",
        control_plane=state.control_plane,
        cp_audit_cb=lambda event: state.store.append_audit(event),
    )
    app.state.admin_app = admin
    return app


@pytest.fixture()
async def cp_admin_client(cp_app: Any) -> AsyncIterator[httpx.AsyncClient]:
    async with make_admin_client(cp_app.state.admin_app) as client:
        yield client


async def _with_lifespan(app: Any, client: httpx.AsyncClient) -> None:
    """Placeholder for future lifespan-scoped flows; keeps import surface stable."""
    _ = app, client


@pytest.mark.anyio
async def test_disabled_cp_rejects_registration(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path), dev_insecure=False)
    state = app.state
    admin = create_admin_app(
        pairing=state.pairing,
        devices=state.devices,
        tls_rotate=lambda: "p",
        admin_token="test-admin-token",
        admin_port=8444,
        control_plane=None,
    )
    async with make_admin_client(admin) as client:
        response = await client.post(
            "/admin/control-plane/register", json={"code": "x"}, headers=ADMIN
        )
        assert response.status_code == 422
        assert response.json()["error"]["details"]["reason"] == "control_plane_disabled"


@pytest.mark.anyio
async def test_register_requires_code(cp_admin_client: httpx.AsyncClient) -> None:
    response = await cp_admin_client.post("/admin/control-plane/register", json={}, headers=ADMIN)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


@pytest.mark.anyio
async def test_register_success_persists_and_audits(
    cp_app: Any, cp_admin_client: httpx.AsyncClient
) -> None:
    response = await cp_admin_client.post(
        "/admin/control-plane/register", json={"code": "link-code-1"}, headers=ADMIN
    )
    assert response.status_code == 200
    body = response.json()
    assert body["registered"] is True
    assert body["state"] == "ok"
    # §12.3: the code exchange hit the Edge Function with the link code.
    register_calls = [c for c in CP_CALLS if "register-agent" in c["url"]]
    assert len(register_calls) == 1
    assert "link-code-1" in register_calls[0]["body"]
    # Payload is Metadata-only (FR-CP-04): id/name/public key — no Content keys.
    sent = json.loads(register_calls[0]["body"])
    assert set(sent) == {"code", "agent_id", "name", "public_key"}
    # Operator action audited (§20.2 vocabulary extension, [DESIGN] hook).
    events = [row["event"] for row in cp_app.state.store.list_audit(limit=10)]
    assert "control_plane_registered" in events
    # Registration persisted in the store settings kv.
    assert "cp-row-it-1" in (cp_app.state.store.get_setting("cp_registration") or "")


@pytest.mark.anyio
async def test_cp_unreachable_maps_to_503_envelope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("keyring.get_password", lambda service, ref: "cp-secret")
    real_client = SupabaseControlPlaneClient

    def patched_client(base_url: str, api_key: str, **kwargs: Any) -> Any:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500)

        kwargs.pop("transport", None)
        return real_client(base_url, api_key, transport=httpx.MockTransport(handler))

    monkeypatch.setattr("localmesh_agent.app.SupabaseControlPlaneClient", patched_client)
    settings = Settings(
        agent={"data_dir": str(tmp_path)},
        backends=[],
        control_plane={
            "enabled": True,
            "url": "https://cp.test",
            "auth_ref": "cp-key",
        },
    )
    app = create_app(settings, dev_insecure=False)
    state = app.state
    admin = create_admin_app(
        pairing=state.pairing,
        devices=state.devices,
        tls_rotate=lambda: "p",
        admin_token="test-admin-token",
        admin_port=8444,
        control_plane=state.control_plane,
    )
    async with make_admin_client(admin) as client:
        response = await client.post(
            "/admin/control-plane/register", json={"code": "c"}, headers=ADMIN
        )
        assert response.status_code == 503  # §12.3: degrade, Agent unaffected
        assert response.json()["error"]["code"] == "BACKEND_UNAVAILABLE"


@pytest.mark.anyio
async def test_revocation_mirrors_to_cp(cp_app: Any, cp_admin_client: httpx.AsyncClient) -> None:
    # Register the agent with the CP first.
    response = await cp_admin_client.post(
        "/admin/control-plane/register", json={"code": "c1"}, headers=ADMIN
    )
    assert response.status_code == 200
    before = len([c for c in CP_CALLS if "devices?" in c["url"]])
    # Pair a device directly through the store (public-key row), then revoke it
    # via the spec-named admin route; the mirror must fire best effort.
    store = cp_app.state.store
    device_id = "dv_cp_mirror_test"
    store.upsert_device(
        device_id=device_id,
        name="Mirror Phone",
        platform="android",
        public_key_spki=b"\x30\x59test-key-bytes",
        scopes="models:read,chat",
        created_at=1_700_000_000,
    )
    response = await cp_admin_client.request("DELETE", f"/admin/devices/{device_id}", headers=ADMIN)
    assert response.status_code in (200, 204)
    mirror_calls = [c for c in CP_CALLS if "devices?public_key=eq." in c["url"]]
    assert len(mirror_calls) == before + 1
    expected_hex = "\\x" + b"\x30\x59test-key-bytes".hex()
    # PostgREST carries the row selector in the URL (query param), the
    # payload stays Metadata-only ({revoked_at}) — FR-CP-04.
    assert expected_hex in mirror_calls[-1]["url"]
    assert set(json.loads(mirror_calls[-1]["body"])) == {"revoked_at"}


@pytest.mark.anyio
async def test_status_block_present_and_metadata_only(cp_app: Any) -> None:
    control_plane = cp_app.state.control_plane
    assert control_plane is not None
    block = control_plane.status()
    assert block["enabled"] is True
    assert block["state"] in {"unregistered", "ok", "offline"}
    blob = json.dumps(block)
    assert "cp-secret" not in blob  # §17.6: keyring secret never resurfaces
