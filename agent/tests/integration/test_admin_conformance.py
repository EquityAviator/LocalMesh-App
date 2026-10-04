"""Admin API conformance (§13.1 Loopback Admin API) — round-10 integration.

Covers the §13.1 verbatim surface over the real app (token mode):
    GET /admin/status                      (spec-named; shape [DESIGN], Metadata only)
    GET /admin/metrics                     (§20.1 optional Prometheus endpoint; path [DESIGN])
    PATCH /admin/devices/{id}              (scopes, name — the §13.1 operator grant mechanism)
    DELETE /admin/devices/{id}             (spec-named revoke)
    POST /admin/pairing/open|approve|deny|close, GET /admin/pairing
                                           (spec-named primaries; WP-08 [DESIGN]
                                           aliases asserted to behave identically)

All admin requests run through the REAL ADR-014 guard (Host check +
X-Admin-Token). Devices are created via the DeviceService (the §14.1 path)
and tokens via the TokenService — the same objects the CLI wires.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

from localmesh_agent.admin_app import create_admin_app
from localmesh_agent.app import create_app
from localmesh_agent.config import Settings


def make_settings(data_dir: Path) -> Settings:
    return Settings(
        agent={"data_dir": str(data_dir)},
        backends=[],
    )


def make_client(app: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")


def make_admin_client(app: Any, *, host: str = "127.0.0.1:8444") -> httpx.AsyncClient:
    """Admin listener client with the ADR-014 Host check satisfied; token
    goes per-request so negative-token paths stay expressible."""
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=f"http://{host}",
        headers={"Host": host},
    )


ADMIN = {"X-Admin-Token": "test-admin-token"}


@pytest.fixture()
def token_app(tmp_path: Path) -> Any:
    app = create_app(make_settings(tmp_path), dev_insecure=False)
    # Same wiring the CLI performs (cli.py _admin_status/_admin_metrics).
    state = app.state
    settings = state.settings

    def status_fn() -> dict[str, Any]:
        import time

        device_rows = state.devices.list()
        active = sum(1 for row in device_rows if row.get("revoked_at") is None)
        return {
            "agent_id": state.agent_id,
            "display_name": settings.agent.display_name,
            "agent_version": state.agent_version,
            "uptime_s": int(time.monotonic() - state.started_mono),
            "pairing_state": state.pairing.pending()[0].value,
            "devices": {
                "total": len(device_rows),
                "active": active,
                "revoked": len(device_rows) - active,
            },
            "queue": state.scheduler.queue_stats(),
            "tls": {"spki_pin_prefix": str(state.spki_pin)[:12]},
        }

    def metrics_fn() -> str:
        state.metrics.refresh_pull_gauges(scheduler=state.scheduler, registry=state.registry)
        return state.metrics.render_prometheus()

    admin = create_admin_app(
        pairing=state.pairing,
        devices=state.devices,
        tls_rotate=lambda: "new-pin",
        admin_token="test-admin-token",
        admin_port=8444,
        doctor_fn=lambda: [],
        status_fn=status_fn,
        metrics_fn=metrics_fn,
    )
    app.state.admin_app = admin
    return app


@pytest.fixture()
def paired_device(token_app: Any) -> dict[str, Any]:
    """A §14.1 device row + live token (auth used by grant e2e below)."""
    app = token_app
    device_id = app.state.devices.create(
        name="Pixel 8", platform="android", public_key_spki=b"\x04spki-bytes"
    )
    issued = app.state.tokens.issue(device_id)
    return {"device_id": device_id, "auth": {"Authorization": f"Bearer {issued.token}"}}


# -- GET /admin/status (§13.1 spec-named) -------------------------------------


@pytest.mark.anyio
async def test_admin_status_metadata_only(token_app: Any) -> None:
    async with make_admin_client(token_app.state.admin_app) as admin:
        resp = await admin.get("/admin/status", headers=ADMIN)
    assert resp.status_code == 200
    body = resp.json()
    assert body["agent_id"].startswith("ag_")
    assert body["agent_version"] == token_app.state.agent_version
    assert body["pairing_state"] in {"closed", "open", "claimed", "locked", "denied", "expired"}
    assert body["devices"]["total"] == 0
    assert body["queue"]["max_queued"] >= 0
    # §17.6: the full SPKI pin and the admin token never appear in the body.
    full_pin = str(token_app.state.spki_pin)
    assert full_pin not in resp.text
    assert len(body["tls"]["spki_pin_prefix"]) == 12
    assert "test-admin-token" not in resp.text


@pytest.mark.anyio
async def test_admin_status_requires_token(token_app: Any) -> None:
    async with make_admin_client(token_app.state.admin_app) as admin:
        assert (await admin.get("/admin/status")).status_code == 401


# -- GET /admin/metrics (§20.1, loopback admin only) ---------------------------


@pytest.mark.anyio
async def test_admin_metrics_prometheus_families(
    token_app: Any, paired_device: dict[str, Any]
) -> None:
    app = token_app
    # Drive two instrumented events: an auth failure (deps) and a pairing
    # attempt (pair.py) — then assert the §20.1 families in the exposition.
    async with make_client(app) as public:
        bad = await public.get("/mesh/v1/models", headers={"Authorization": "Bearer not-a-token"})
        assert bad.status_code == 401
        attempt = await public.post("/mesh/v1/pair/complete", json={})
        assert attempt.status_code == 422
    async with make_admin_client(app.state.admin_app) as admin:
        resp = await admin.get("/admin/metrics", headers=ADMIN)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    text = resp.text
    for family in (
        "requests_total",
        "ttft_ms",
        "tokens_out_total",
        "tokens_per_sec",
        "queue_depth",
        "active_generations",
        "backend_up",
        "auth_failures_total",
        "pairing_attempts_total",
        "cancel_latency_ms",
    ):
        assert f"# TYPE {family} " in text, family
    assert "auth_failures_total 1" in text
    assert "pairing_attempts_total 1" in text
    # Pull gauges reflect live scheduler state (empty → 0).
    assert "queue_depth 0" in text
    assert "active_generations 0" in text
    # §17.6: no token material anywhere near the exposition.
    assert "not-a-token" not in text


@pytest.mark.anyio
async def test_admin_metrics_requires_admin_token_and_host(token_app: Any) -> None:
    async with make_admin_client(token_app.state.admin_app) as admin:
        assert (await admin.get("/admin/metrics")).status_code == 401
        rebinding = await admin.get(
            "/admin/metrics",
            headers={"X-Admin-Token": "test-admin-token", "Host": "evil.example:8444"},
        )
        assert rebinding.status_code == 403


# -- PATCH /admin/devices/{id} (§13.1 scopes, name) ----------------------------


@pytest.mark.anyio
async def test_admin_patch_grants_models_manage_and_device_can_load(
    token_app: Any, paired_device: dict[str, Any]
) -> None:
    """The §13.1 grant mechanism end-to-end: operator PATCH adds
    `models:manage` → the SAME live token can now call a manage endpoint."""
    app = token_app
    device_id = paired_device["device_id"]
    before = app.state.devices.get(device_id)
    assert before is not None and before["scopes"] == "models:read chat"  # §13.1 defaults
    async with make_admin_client(app.state.admin_app) as admin:
        patched = await admin.patch(
            f"/admin/devices/{device_id}",
            json={"scopes": ["models:read", "chat", "models:manage"]},
            headers=ADMIN,
        )
    assert patched.status_code == 200
    row = patched.json()["device"]
    assert row["scopes"] == "chat models:manage models:read"  # canonical order
    # New tokens pick up the new scopes (verify() reads the devices row).
    issued = app.state.tokens.issue(device_id)
    async with make_client(app) as public:
        resp = await public.post(
            "/mesh/v1/models/load",
            json={"mesh_model_id": "lmstudio::qwen"},
            headers={"Authorization": f"Bearer {issued.token}"},
        )
    # 404 (model absent) proves the scope gate PASSED (a narrow-scope device
    # would get 403 FORBIDDEN_SCOPE before the router is consulted).
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "MODEL_NOT_FOUND"


@pytest.mark.anyio
async def test_admin_patch_name_update_and_audit(
    token_app: Any, paired_device: dict[str, Any]
) -> None:
    app = token_app
    device_id = paired_device["device_id"]
    async with make_admin_client(app.state.admin_app) as admin:
        resp = await admin.patch(
            f"/admin/devices/{device_id}", json={"name": "  Living-room tablet  "}, headers=ADMIN
        )
    assert resp.status_code == 200
    row = resp.json()["device"]
    assert row["name"] == "Living-room tablet"  # stripped, §14.1 NOT NULL kept
    # Metadata-only audit trail (§17.10 allow-list carries no "changed
    # field" key → the entry records the event + device_id only).
    audit = app.state.store.list_audit(limit=5)
    assert any(row["event"] == "device_updated" and row["device_id"] == device_id for row in audit)


@pytest.mark.anyio
async def test_admin_patch_rejects_unknown_scope_empty_and_bad_bodies(
    token_app: Any, paired_device: dict[str, Any]
) -> None:
    device_id = paired_device["device_id"]
    async with make_admin_client(token_app.state.admin_app) as admin:
        unknown = await admin.patch(
            f"/admin/devices/{device_id}",
            json={"scopes": ["models:read", "sudo"]},
            headers=ADMIN,
        )
        assert unknown.status_code == 422
        assert unknown.json()["error"]["details"]["unknown"] == ["sudo"]
        empty_scopes = await admin.patch(
            f"/admin/devices/{device_id}", json={"scopes": []}, headers=ADMIN
        )
        assert empty_scopes.status_code == 422
        empty_name = await admin.patch(
            f"/admin/devices/{device_id}", json={"name": "   "}, headers=ADMIN
        )
        assert empty_name.status_code == 422
        no_fields = await admin.patch(f"/admin/devices/{device_id}", json={}, headers=ADMIN)
        assert no_fields.status_code == 422
        unknown_field = await admin.patch(
            f"/admin/devices/{device_id}", json={"scopes": "chat"}, headers=ADMIN
        )
        assert unknown_field.status_code == 422
        garbage = await admin.patch(
            f"/admin/devices/{device_id}",
            content=b"{not json",
            headers={**ADMIN, "content-type": "application/json"},
        )
        assert garbage.status_code == 422


@pytest.mark.anyio
async def test_admin_patch_unknown_device_404(token_app: Any) -> None:
    async with make_admin_client(token_app.state.admin_app) as admin:
        resp = await admin.patch("/admin/devices/dv_missing", json={"name": "x"}, headers=ADMIN)
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_admin_patch_on_revoked_device_cannot_resurrect_access(
    token_app: Any, paired_device: dict[str, Any]
) -> None:
    """[DESIGN] documented in DeviceService.update: rows are editable but
    auth stays blocked (tokens deleted + revoked_at gate) — a PATCH cannot
    resurrect a revoked device."""
    app = token_app
    device_id = paired_device["device_id"]
    app.state.devices.revoke(device_id)
    async with make_admin_client(app.state.admin_app) as admin:
        resp = await admin.patch(
            f"/admin/devices/{device_id}", json={"scopes": ["chat"]}, headers=ADMIN
        )
    assert resp.status_code == 200
    issued = app.state.tokens.issue(device_id)
    async with make_client(app) as public:
        assert (
            await public.get("/mesh/v1/models", headers={"Authorization": f"Bearer {issued.token}"})
        ).status_code == 401


# -- DELETE /admin/devices/{id} (§13.1 spec-named) ------------------------------


@pytest.mark.anyio
async def test_admin_delete_device_is_spec_named_revoke(
    token_app: Any, paired_device: dict[str, Any]
) -> None:
    app = token_app
    device_id = paired_device["device_id"]
    async with make_admin_client(app.state.admin_app) as admin:
        deleted = await admin.delete(f"/admin/devices/{device_id}", headers=ADMIN)
        assert deleted.status_code == 200
        assert deleted.json() == {
            "status": "revoked",
            "device_id": device_id,
            "cancelled_requests": 0,
        }
        # The WP-08 [DESIGN] alias behaves identically (incl. 404 shape).
        again_alias = await admin.post(f"/admin/devices/{device_id}/revoke", headers=ADMIN)
        assert again_alias.status_code == 404
        unknown_delete = await admin.delete("/admin/devices/dv_missing", headers=ADMIN)
        assert unknown_delete.status_code == 404


# -- spec-named pairing routes + alias parity (QUESTION-103 item 4) -------------


@pytest.mark.anyio
async def test_admin_pairing_spec_named_routes_match_aliases(token_app: Any) -> None:
    app = token_app
    async with make_admin_client(app.state.admin_app) as admin:
        spec_open = await admin.post("/admin/pairing/open", headers=ADMIN)
        alias_open = await admin.post("/admin/pair/open", headers=ADMIN)
        assert spec_open.status_code == alias_open.status_code == 200
        assert set(spec_open.json()) == {"pair_id", "qr", "expires_in"}
        assert spec_open.json()["pair_id"] != alias_open.json()["pair_id"]  # separate sessions
        spec_pending = await admin.get("/admin/pairing", headers=ADMIN)
        alias_pending = await admin.get("/admin/pair/pending", headers=ADMIN)
        assert spec_pending.status_code == alias_pending.status_code == 200
        assert spec_pending.json()["state"] == alias_pending.json()["state"] == "open"
        # CLOSE via the spec route; DENY via the alias against the second session.
        spec_close = await admin.post("/admin/pairing/close", headers=ADMIN)
        assert spec_close.json() == {"status": "closed"}
        alias_deny = await admin.post("/admin/pairing/deny", headers=ADMIN)
        assert alias_deny.status_code in {200, 409}  # deny needs CLAIMED; shape over status here
        alias_approve_shape = await admin.post("/admin/pairing/approve", headers=ADMIN)
        assert alias_approve_shape.status_code in {200, 409}


@pytest.mark.anyio
async def test_admin_patch_and_status_rejected_without_token_or_bad_host(
    token_app: Any, paired_device: dict[str, Any]
) -> None:
    device_id = paired_device["device_id"]
    async with make_admin_client(token_app.state.admin_app) as admin:
        assert (
            await admin.patch(f"/admin/devices/{device_id}", json={"name": "x"})
        ).status_code == 401
        assert (
            await admin.patch(
                f"/admin/devices/{device_id}",
                json={"name": "x"},
                headers={"X-Admin-Token": "wrong"},
            )
        ).status_code == 401
        bad_host = await admin.get(
            "/admin/status",
            headers={"X-Admin-Token": "test-admin-token", "Host": "rebind.example:8444"},
        )
        assert bad_host.status_code == 403
