"""WP-15 integration tests — API-DEV-01 `GET /mesh/v1/device` (§13.2).

Exercises the REAL app in token mode: hardware snapshot (psutil against the
actual sandbox host — Linux, no NVIDIA driver → gpus==[] per FR-STAT-01),
LAN address selection (§16.2), tailnet block passthrough (WP-14, absent in
sandbox → null), auth (Bearer + models:read) and §13.3 wire headers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from localmesh_agent.app import create_app
from localmesh_agent.config import Settings


def make_settings(data_dir: Path) -> Settings:
    return Settings(
        agent={"data_dir": str(data_dir)},
        backends=[],  # hardware probing is backend-independent
    )


def make_client(app: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")


@pytest.fixture()
def token_app(tmp_path: Path) -> Any:
    app = create_app(make_settings(tmp_path), dev_insecure=False)
    return app


@pytest.fixture()
def auth_header(token_app: Any) -> dict[str, str]:
    """A paired Device + valid Device Token (§14.1 path)."""
    app = token_app
    device_id = app.state.devices.create(
        name="Pixel 8", platform="android", public_key_spki=b"\x04spki-bytes"
    )
    issued = app.state.tokens.issue(device_id)
    return {"Authorization": f"Bearer {issued.token}"}


@pytest.mark.anyio
async def test_device_200_full_shape(token_app: Any, auth_header: dict[str, str]) -> None:
    app = token_app
    async with make_client(app) as client:
        resp = await client.get("/mesh/v1/device", headers=auth_header)
    assert resp.status_code == 200
    body = resp.json()
    # §13.2 verbatim key set — no extra top-level fields.
    assert set(body) == {
        "agent_id",
        "display_name",
        "agent_version",
        "os",
        "cpu",
        "ram",
        "gpus",
        "network",
    }
    assert body["agent_id"].startswith("ag_")
    assert body["display_name"]  # from config/identity, never empty default game
    assert body["agent_version"] == app.state.agent_version
    # os block — nullable fields, real host reports linux here.
    assert set(body["os"]) == {"family", "version"}
    assert body["os"]["family"] in {"linux", "darwin", "windows"}  # real host
    # cpu / ram blocks — sandbox psutil reports real values.
    assert set(body["cpu"]) == {"model", "logical_cores"}
    assert isinstance(body["cpu"]["logical_cores"], int)
    assert body["cpu"]["logical_cores"] >= 1
    assert set(body["ram"]) == {"total_bytes", "available_bytes"}
    assert isinstance(body["ram"]["total_bytes"], int)
    assert body["ram"]["total_bytes"] > 0
    # gpus — sandbox has no NVIDIA driver → [] (FR-STAT-01, no fabricated entries).
    assert body["gpus"] == []
    # network block — §16.2-selected private IPv4s + tailnet passthrough.
    network = body["network"]
    assert set(network) == {"lan_addresses", "tailnet"}
    for addr in network["lan_addresses"]:
        parts = addr.split(".")
        assert len(parts) == 4
        first = int(parts[0])
        assert first in {10, 172, 192}  # private ranges only (VPN/public excluded)
    # No tailscale binary in sandbox → None (§13.2 "null if no Tailscale").
    assert network["tailnet"] is None
    # §13.3 wire headers.
    assert resp.headers["X-Mesh-Api-Version"] == "1"
    assert resp.headers["X-Mesh-Request-Id"].startswith("rq_")
    assert resp.headers["Cache-Control"] == "no-store"


@pytest.mark.anyio
async def test_device_401_without_token(token_app: Any) -> None:
    async with make_client(token_app) as client:
        resp = await client.get("/mesh/v1/device")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "AUTH_REQUIRED"  # fail-closed SEC-N4


@pytest.mark.anyio
async def test_device_401_with_garbage_token(token_app: Any) -> None:
    async with make_client(token_app) as client:
        resp = await client.get("/mesh/v1/device", headers={"Authorization": "Bearer not-a-token"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "AUTH_FAILED"  # uniform §17.8


@pytest.mark.anyio
async def test_device_403_missing_models_read_scope(token_app: Any) -> None:
    """§13.2 API table: /device requires `models:read`; §17.7 per-endpoint."""
    app = token_app
    # A device whose §14.1 row carries only the `chat` scope (upsert keeps
    # scopes from the FIRST insert — devices.py DEFAULT_DEVICE_SCOPES never
    # applies here, which is exactly the narrow-scope case under test).
    app.state.store.upsert_device(
        device_id="dv_limited",
        name="Limited",
        platform="android",
        public_key_spki=b"\x04spki",
        scopes="chat",
        created_at=0,
    )
    issued = app.state.tokens.issue("dv_limited")
    async with make_client(app) as client:
        resp = await client.get(
            "/mesh/v1/device", headers={"Authorization": f"Bearer {issued.token}"}
        )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN_SCOPE"


@pytest.mark.anyio
async def test_device_401_revoked_device(token_app: Any, auth_header: dict[str, str]) -> None:
    """§15.6: revocation deletes token hashes → uniform 401 (§17.8)."""
    app = token_app
    devices_list = app.state.devices.list()
    target = next(d for d in devices_list if d["name"] == "Pixel 8")
    app.state.devices.revoke(str(target["device_id"]))
    async with make_client(app) as client:
        resp = await client.get("/mesh/v1/device", headers=auth_header)
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "AUTH_FAILED"


@pytest.mark.anyio
async def test_device_tailnet_block_passthrough(token_app: Any) -> None:
    """§13.2: tailnet block mirrors the WP-14 startup probe when present."""
    from localmesh_agent.adapters.ports import TailnetInfo

    app = token_app
    app.state.tailnet = TailnetInfo(state="running", dns_name="box.tailnet.", ips=("100.64.0.7",))
    device_id = app.state.devices.create(
        name="Pixel 9", platform="android", public_key_spki=b"\x04spki"
    )
    issued = app.state.tokens.issue(device_id)
    async with make_client(app) as client:
        resp = await client.get(
            "/mesh/v1/device", headers={"Authorization": f"Bearer {issued.token}"}
        )
    assert resp.status_code == 200
    tailnet = resp.json()["network"]["tailnet"]
    assert tailnet == {"state": "running", "dns_name": "box.tailnet.", "ips": ["100.64.0.7"]}


@pytest.mark.anyio
async def test_device_never_500_on_probe_failure(token_app: Any) -> None:
    """FR-STAT-01: "works with no GPU; no exceptions" — even a broken probe."""
    from localmesh_agent.adapters.ports import HardwareInfo

    class ExplodingProbe:
        async def snapshot(self) -> HardwareInfo:
            raise RuntimeError("probe on fire")

    app = token_app
    app.state.hardware = ExplodingProbe()
    device_id = app.state.devices.create(
        name="Pixel 10", platform="android", public_key_spki=b"\x04spki"
    )
    issued = app.state.tokens.issue(device_id)
    async with make_client(app) as client:
        resp = await client.get(
            "/mesh/v1/device", headers={"Authorization": f"Bearer {issued.token}"}
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["os"]["family"] is None
    assert body["cpu"]["logical_cores"] is None
    assert body["ram"]["total_bytes"] is None
    assert body["gpus"] == []
    assert body["network"]["tailnet"] is None


def _unused_key() -> ec.EllipticCurvePrivateKey:  # pragma: no cover — keeps import used
    return ec.generate_private_key(ec.SECP256R1())
