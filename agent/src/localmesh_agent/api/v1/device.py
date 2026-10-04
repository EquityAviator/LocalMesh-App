"""API-DEV-01 `GET /mesh/v1/device` (§13.2) — WP-15 (M5, FR-STAT-01).

Contract (§13.2, verbatim shape; all hardware fields nullable, best effort):

    { "agent_id":"ag_...", "display_name":"Gaming PC", "agent_version":"0.1.0",
      "os": { "family":"windows", "version":null },
      "cpu": { "model": null, "logical_cores": 16 },
      "ram": { "total_bytes": 34359738368, "available_bytes": 12000000000 },
      "gpus": [ { "name": null, "vram_total_bytes": null, "vram_used_bytes": null,
                  "utilization_pct": null, "temperature_c": null } ],
      "network": { "lan_addresses": ["192.168.1.100"],
                   "tailnet": { "state":"running", "dns_name":null, "ips":["100.x.y.z"] } } }

- Authorization: Device Token + `models:read` scope (§13.2 API table).
- `network.lan_addresses` reuses the §16.2 interface selection the mDNS
  advertiser uses (same addresses, one source of truth); the resolver only
  ever returns private IPv4s (VPN/public/loopback excluded).
- `network.tailnet` mirrors the WP-14 startup probe (§13.2: "null if no
  Tailscale detected"; §6.3 [ASSUMPTION] fields).
- `gpus` is empty when no GPU is reported — an all-null GPU entry would
  fabricate the EXISTENCE of a GPU (§13.2: unknowns stay null/absent).
  An entry with null fields appears only when a GPU IS detected but some
  attribute is not reported.
- No rate limit: §13.8 enumerates the limits exhaustively and has no
  /device row; the endpoint requires a valid Device Token already.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from localmesh_agent.adapters.ports import HardwareInfo, TailnetInfo
from localmesh_agent.api.deps import get_principal, require_scope

router = APIRouter()


class OsInfo(BaseModel):
    family: str | None = Field(description="OS family, e.g. 'windows'/'linux'/'darwin' (§13.2).")
    version: str | None = Field(description="OS version/release if reported (§13.2).")


class CpuInfo(BaseModel):
    model: str | None = Field(description="CPU model string if reported (§13.2).")
    logical_cores: int | None = Field(description="Logical core count if reported (§13.2).")


class RamInfo(BaseModel):
    total_bytes: int | None = Field(description="Total physical RAM in bytes (§13.2).")
    available_bytes: int | None = Field(description="Currently available RAM in bytes (§13.2).")


class GpuEntry(BaseModel):
    name: str | None = Field(description="GPU name if reported (§13.2).")
    vram_total_bytes: int | None = Field(description="Total VRAM in bytes (§13.2).")
    vram_used_bytes: int | None = Field(description="Used VRAM in bytes (§13.2).")
    utilization_pct: float | None = Field(description="GPU utilization percent (§13.2).")
    temperature_c: float | None = Field(description="GPU temperature in °C (§13.2).")


class TailnetBlock(BaseModel):
    state: str = Field(description="Tailscale probe state (§6.3, WP-14).")
    dns_name: str | None = Field(description="MagicDNS name without trailing dot (§6.3).")
    ips: list[str] = Field(description="100.64.0.0/10 addresses (§6.3).")


class NetworkInfo(BaseModel):
    lan_addresses: list[str] = Field(description="Private LAN IPv4s (§16.2 selection).")
    tailnet: TailnetBlock | None = Field(
        description="Tailnet block, null when Tailscale is absent (§13.2)."
    )


class DeviceResponse(BaseModel):
    agent_id: str = Field(description="Stable Agent identifier (§13.2).")
    display_name: str = Field(description="Operator-set Agent display name (§13.2).")
    agent_version: str = Field(description="Semantic Agent version (NFR-COMP-02).")
    os: OsInfo = Field(description="OS block, all fields nullable (FR-STAT-01).")
    cpu: CpuInfo = Field(description="CPU block, all fields nullable (FR-STAT-01).")
    ram: RamInfo = Field(description="RAM block, all fields nullable (FR-STAT-01).")
    gpus: list[GpuEntry] = Field(description="Detected GPUs; empty when none reported (§13.2).")
    network: NetworkInfo = Field(description="LAN + Tailnet addressing (§13.2).")


def _tailnet_block(info: TailnetInfo) -> TailnetBlock:
    return TailnetBlock(state=info.state, dns_name=info.dns_name, ips=list(info.ips))


def device_payload(
    agent_id: str,
    display_name: str,
    agent_version: str,
    hw: HardwareInfo,
    lan_addresses: list[str],
    tailnet: TailnetInfo | None,
) -> DeviceResponse:
    """Map a HardwareInfo snapshot to the §13.2 response (shared with tests)."""
    return DeviceResponse(
        agent_id=agent_id,
        display_name=display_name,
        agent_version=agent_version,
        os=OsInfo(family=hw.os_family, version=hw.os_version),
        cpu=CpuInfo(model=hw.cpu_model, logical_cores=hw.logical_cores),
        ram=RamInfo(total_bytes=hw.ram_total_bytes, available_bytes=hw.ram_available_bytes),
        gpus=[
            GpuEntry(
                name=g.name,
                vram_total_bytes=g.vram_total_bytes,
                vram_used_bytes=g.vram_used_bytes,
                utilization_pct=g.utilization_pct,
                temperature_c=g.temperature_c,
            )
            for g in hw.gpus
        ],
        network=NetworkInfo(
            lan_addresses=lan_addresses,
            tailnet=_tailnet_block(tailnet) if tailnet is not None else None,
        ),
    )


@router.get("/mesh/v1/device", tags=["device"], response_model=DeviceResponse)
async def get_device(request: Request) -> DeviceResponse:
    """Serve API-DEV-01 (§13.2) — best-effort hardware/network report."""
    principal = get_principal(request)
    require_scope(principal, "models:read")  # §13.2 API table

    app_state = request.app.state
    hardware = getattr(app_state, "hardware", None)
    try:
        hw = await hardware.snapshot() if hardware is not None else HardwareInfo()
    except Exception:  # noqa: BLE001 — FR-STAT-01: no exceptions escape /device
        hw = HardwareInfo()

    # §16.2 interface selection (blocking UDP-connect trick → thread, §10.5).
    settings = app_state.settings
    from localmesh_agent.adapters.discovery.mdns import resolve_advertise_addresses

    try:
        lan_addresses = await asyncio.to_thread(
            resolve_advertise_addresses, settings.mdns.interfaces
        )
    except Exception:  # noqa: BLE001 — addressing degrades to an empty list
        lan_addresses = []

    identity = app_state.store.get_identity()
    display_name = str(identity["display_name"]) if identity else str(settings.agent.display_name)

    tailnet: TailnetInfo | None = getattr(app_state, "tailnet", None)
    return device_payload(
        agent_id=str(app_state.agent_id),
        display_name=display_name,
        agent_version=str(app_state.agent_version),
        hw=hw,
        lan_addresses=list(lan_addresses),
        tailnet=tailnet,
    )
