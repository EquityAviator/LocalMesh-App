"""mDNS advertisement (python-zeroconf) — FR-AGT-04, §16.2, §10.6 step 5.

Service contract (§16.2, verbatim):

- Type ``_localmesh._tcp.local.``, instance ``"<display_name> (<first 6 of
  agent uuid>)"``, port = ``listen.port``.
- TXT keys (each ≤ 255 bytes): ``v=1``, ``aid=<agent_id>``, ``n=<display_name>``,
  ``fp=<first 16 chars of b64url(SPKI sha256)>`` (hint only; the full pin is
  verified by TLS), ``api=v1``, ``po=0|1``.
- Advertise only on interfaces/addresses selected by config (Appendix E
  ``[mdns] interfaces``; empty = default-route interface only); exclude
  virtual adapters (Hyper-V/WSL/Docker/VPN) by default (CI-24). IPv6 is NOT
  advertised in v1.
- Re-announce on interface/address change (a watchdog re-resolves and
  re-announces; interval is [DESIGN] — the spec names no detection mechanism).

Interpretations recorded inline ([DESIGN] markers):
- ``po`` mirrors API-INFO-01's ``pairing_open`` (§13.2) — the only "0|1"
  pairing flag the spec defines. TXT is an untrusted hint (T-21); the App's
  authoritative check is ``GET /info``, so the refresh granularity (60 s
  watchdog) is a hint, not a guarantee.
- The "agent uuid" in the instance name is the UUID portion of
  ``ag_<uuid7>`` (§14.3 id shape); the prefix is not part of the uuid.
- Default-route discovery: stateless UDP-connect trick (no packets are
  sent) with a non-virtual-interface fallback when the host is offline —
  a host without a default route still serves its LAN, and CI-24's concern
  (virtual adapters) is handled by the exclusion filter either way.

Discovery is a hint service (T-21): failures to resolve interfaces degrade
to "not advertising" (logged), never to a crash — Agent start must not
depend on multicast being available.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Callable, Sequence
from typing import Any

from localmesh_agent.adapters.ports import ServiceAd
from localmesh_agent.observability.logging import get_logger

log = get_logger("mdns")

SERVICE_TYPE = "_localmesh._tcp.local."
API_VERSION_TXT = "v1"
TXT_VERSION = "1"
FP_PREFIX_CHARS = 16  # §16.2: fp = first 16 chars of the b64url pin

# §16.2 / CI-24: virtual adapters are excluded by default. Matched as
# case-insensitive substrings of the interface name (covers Hyper-V
# "vEthernet (WSL)", "DockerNAT", "tailscale0", "virbr0", "utun3", …).
_VIRTUAL_IFACE_PATTERNS: tuple[str, ...] = (
    "docker",
    "podman",
    "veth",
    "virbr",
    "libvirt",
    "vEthernet",  # Windows Hyper-V switch (case-insensitive match)
    "hyper-v",
    "wsl",
    "vmware",
    "vmnet",
    "virtualbox",
    "vbox",
    "tailscale",
    "tun",  # tun0/tap0/wintun/OpenVPN/zerotier taps
    "tap",
    "wg",  # WireGuard (wg0)
    "utun",
    "lo",
    "loopback",
    "bridge",
)

WATCHDOG_INTERVAL_SECONDS = 60.0  # [DESIGN] §16.2 names no detection interval

# §17.10: only allow-listed keys reach the log formatter.
_COMPONENT = "mdns"


def is_virtual_interface(name: str) -> bool:
    """CI-24: virtual adapters (Hyper-V/WSL/Docker/VPN) are excluded by default."""
    lowered = name.lower()
    return any(pattern.lower() in lowered for pattern in _VIRTUAL_IFACE_PATTERNS)


def _is_advertisable_ipv4(ip: str) -> bool:
    """§16.2: IPv4 private addresses only (no loopback, no IPv6 in v1)."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return addr.version == 4 and addr.is_private and not addr.is_loopback and not addr.is_link_local


def interface_ipv4_map() -> dict[str, list[str]]:
    """name → advertisable private IPv4 addresses for non-virtual interfaces.

    Uses psutil (locked dependency, WP-02): ``net_if_addrs`` covers Linux,
    macOS and Windows uniformly without subprocesses.
    """
    import psutil

    result: dict[str, list[str]] = {}
    for name, addrs in psutil.net_if_addrs().items():
        if is_virtual_interface(name):
            continue
        ips: list[str] = []
        for a in addrs:
            family = getattr(a, "family", None)
            if family == socket.AF_INET and _is_advertisable_ipv4(a.address):
                ips.append(a.address)
        if ips:
            result[name] = ips
    return result


def default_route_ipv4() -> str | None:
    """IPv4 of the interface owning the default route (§16.2 default).

    Stateless UDP-connect trick: ``connect()`` on a SOCK_DGRAM socket only
    selects the egress interface — no packet is sent. Falls back to None
    when the host has no IPv4 default route (offline).
    """
    s: socket.socket | None = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # RFC 5737 TEST-NET-1: never a real destination; nothing is sent.
        s.connect(("192.0.2.1", 9))
        ip = str(s.getsockname()[0])
        return ip if _is_advertisable_ipv4(ip) else None
    except OSError:
        return None
    finally:
        if s is not None:
            s.close()


def resolve_advertise_addresses(configured: Sequence[str]) -> list[str]:
    """Interface selection (§16.2 + Appendix E ``[mdns] interfaces``).

    - Non-empty config: entries may be interface names or literal IPv4
      addresses; unknown names / non-private IPs are skipped with a log
      line (FR-AGT-04: advertise on the SELECTED interfaces only).
    - Empty config: private IPv4 addresses of the interface owning the
      default route. If the default route cannot be determined (offline),
      fall back to all non-virtual interfaces' private IPv4s [DESIGN].
    """
    iface_map = interface_ipv4_map()

    if configured:
        selected: list[str] = []
        for entry in configured:
            if _is_advertisable_ipv4(entry):
                if entry not in selected:
                    selected.append(entry)
                continue
            ips = iface_map.get(entry)
            if ips is None:
                # Unknown name, virtual-excluded, or no private IPv4 on it.
                log.warning(
                    "mdns_interface_unresolved",
                    extra={"component": _COMPONENT, "status": "unresolved"},
                )
                continue
            for ip in ips:
                if ip not in selected:
                    selected.append(ip)
        return selected

    primary_ip = default_route_ipv4()
    if primary_ip is not None:
        for _name, ips in iface_map.items():
            if primary_ip in ips:
                return ips
        # Egress IP exists but sits on an interface we filter (edge: VPN
        # owning the default route). Then the config'd exclusion wins —
        # CI-24 prefers not advertising over advertising a virtual IP.
        return []
    # Offline: no default route. Advertise on every non-virtual private
    # IPv4 so LAN discovery keeps working [DESIGN fallback].
    all_ips: list[str] = []
    for ips in iface_map.values():
        for ip in ips:
            if ip not in all_ips:
                all_ips.append(ip)
    return all_ips


def agent_uuid_part(agent_id: str) -> str:
    """UUID portion of ``ag_<uuid>`` (§14.3): strip a leading ``ag_``."""
    return agent_id[3:] if agent_id.startswith("ag_") else agent_id


def build_instance_name(display_name: str, agent_id: str) -> str:
    """§16.2: ``"<display_name> (<first 6 of agent uuid>)"``."""
    return f"{display_name} ({agent_uuid_part(agent_id)[:6]})"


def build_txt(
    agent_id: str,
    display_name: str,
    spki_pin: str,
    *,
    pairing_open: bool,
) -> dict[str, str]:
    """§16.2 TXT record (each value ≤ 255 bytes; ``n`` is truncated to fit).

    ``fp`` is the first 16 chars of the b64url(no-pad) SPKI SHA-256 pin —
    a HINT for QR cross-check only; the full pin is verified by TLS (§16.2).
    """
    name = display_name
    max_name_bytes = 255
    while len(name.encode("utf-8")) > max_name_bytes and name:
        name = name[:-1]
    return {
        "v": TXT_VERSION,
        "aid": agent_id[:255],
        "n": name,
        "fp": spki_pin[:FP_PREFIX_CHARS],
        "api": API_VERSION_TXT,
        "po": "1" if pairing_open else "0",
    }


def build_service_ad(
    agent_id: str,
    display_name: str,
    port: int,
    spki_pin: str,
    *,
    pairing_open: bool,
) -> ServiceAd:
    """Assemble the §16.2 advertisement payload."""
    return ServiceAd(
        agent_id=agent_id,
        display_name=display_name,
        port=port,
        txt=build_txt(agent_id, display_name, spki_pin, pairing_open=pairing_open),
    )


class MdnsAdvertiser:
    """python-zeroconf advertisement implementing the DiscoveryAdvertiser port.

    Lifecycle (§10.6 step 5): ``start(ad)`` resolves the advertise
    addresses, registers ``_localmesh._tcp`` and spawns the §16.2
    re-announce watchdog; ``stop()`` unregisters and closes zeroconf.
    ``refresh(ad)`` re-announces with current addresses/``po`` — used by
    the watchdog and available to operators after interface changes.
    """

    def __init__(
        self,
        interfaces: Sequence[str] = (),
        *,
        pairing_open_fn: Callable[[], bool] | None = None,
        watchdog_interval: float = WATCHDOG_INTERVAL_SECONDS,
    ) -> None:
        self._interfaces = list(interfaces)
        self._pairing_open_fn = pairing_open_fn
        self._watchdog_interval = watchdog_interval
        self._addresses: list[str] = []
        self._ad: ServiceAd | None = None
        self._zeroconf: Any | None = None
        self._info: Any | None = None
        self._watchdog: asyncio.Task[None] | None = None

    @property
    def advertising(self) -> bool:
        """True while the service is registered with zeroconf."""
        return self._info is not None

    @property
    def addresses(self) -> tuple[str, ...]:
        """Addresses currently advertised (empty = not advertising)."""
        return tuple(self._addresses)

    async def start(self, ad: ServiceAd) -> None:
        """§10.6 step 5: resolve interfaces and register the service."""
        self._ad = ad
        self._addresses = resolve_advertise_addresses(self._interfaces)
        await self._register()
        self._watchdog = asyncio.create_task(self._watchdog_loop(), name="localmesh-mdns-watchdog")

    async def stop(self) -> None:
        """Unregister and close (§10.6 shutdown symmetry)."""
        if self._watchdog is not None:
            self._watchdog.cancel()
            try:
                await self._watchdog
            except asyncio.CancelledError:
                pass
            self._watchdog = None
        await self._unregister()

    async def refresh(self, ad: ServiceAd | None = None) -> None:
        """Re-announce with freshly resolved addresses / current ``po``.

        Cheap no-op when neither the address set nor the TXT changed.
        """
        if self._ad is None:
            return
        new_ad = ad if ad is not None else self._current_ad()
        if new_ad is None:
            return
        new_addresses = resolve_advertise_addresses(self._interfaces)
        assert self._ad is not None  # guarded above
        if new_addresses == self._addresses and new_ad.txt == self._ad.txt:
            return
        self._ad = new_ad
        await self._reannounce(new_addresses)

    def _current_ad(self) -> ServiceAd | None:
        """Current ad with a fresh ``po``; the 16-char ``fp`` hint (§16.2)
        stays byte-stable across ``po`` updates — it was computed once at
        start from the TLS identity and never changes without a rotate
        (a rotate restarts the process → new registration)."""
        if self._ad is None:
            return None
        pairing_open = bool(self._pairing_open_fn()) if self._pairing_open_fn else False
        txt = dict(self._ad.txt)
        txt["po"] = "1" if pairing_open else "0"
        return ServiceAd(
            agent_id=self._ad.agent_id,
            display_name=self._ad.display_name,
            port=self._ad.port,
            txt=txt,
        )

    async def _watchdog_loop(self) -> None:
        """§16.2: re-announce on interface/address change (interval [DESIGN])."""
        while True:
            await asyncio.sleep(self._watchdog_interval)
            try:
                await self.refresh()
            except Exception:  # noqa: BLE001 — a hint service must not crash the agent
                log.warning(
                    "mdns_refresh_failed",
                    extra={"component": _COMPONENT, "status": "error"},
                )

    # -- zeroconf plumbing ------------------------------------------------------

    def _build_info(self) -> Any:
        """ServiceInfo for the CURRENT ad + resolved addresses."""
        assert self._ad is not None
        from zeroconf import ServiceInfo  # local import: tests stub the module class

        return ServiceInfo(
            SERVICE_TYPE,
            f"{build_instance_name(self._ad.display_name, self._ad.agent_id)}.{SERVICE_TYPE}",
            port=self._ad.port,
            properties=self._ad.txt,
            addresses=[socket.inet_aton(ip) for ip in self._addresses],
        )

    async def _register(self) -> None:
        await self._unregister()
        if self._ad is None or not self._addresses:
            log.warning(
                "mdns_not_advertising",
                extra={"component": _COMPONENT, "status": "no_interfaces"},
            )
            return
        info = self._build_info()
        zc = self._make_zeroconf(self._addresses)
        await zc.async_register_service(info)
        self._zeroconf = zc
        self._info = info
        log.info(
            "mdns_started",
            extra={"component": _COMPONENT, "status": "advertising", "agent_id": self._ad.agent_id},
        )

    async def _reannounce(self, new_addresses: list[str]) -> None:
        """Interface/address (§16.2) or TXT change: swap the registration.

        The AsyncZeroconf instance is REUSED across re-announces (repeated
        socket open/close would churn the network stack); only the service
        record is swapped. A previously degraded (never-registered) state
        takes the full register path instead.
        """
        zc = self._zeroconf
        if zc is None:
            self._addresses = new_addresses
            await self._register()
            return
        if self._info is not None:
            try:
                await zc.async_unregister_service(self._info)
            except Exception:  # noqa: BLE001 — stale registration is not fatal
                pass
        self._addresses = new_addresses
        info = self._build_info()
        await zc.async_register_service(info)
        self._info = info

    async def _unregister(self) -> None:
        zc, info = self._zeroconf, self._info
        self._zeroconf = None
        self._info = None
        if zc is None:
            return
        if info is not None:
            try:
                await zc.async_unregister_service(info)
            except Exception:  # noqa: BLE001
                pass
        try:
            await zc.async_close()
        except Exception:  # noqa: BLE001
            pass
        log.info("mdns_stopped", extra={"component": _COMPONENT, "status": "stopped"})

    def _make_zeroconf(self, interfaces: list[str]) -> Any:
        """Hook for tests (stub AsyncZeroconf); real: zeroconf.asyncio.AsyncZeroconf."""
        from zeroconf.asyncio import AsyncZeroconf

        return AsyncZeroconf(interfaces=interfaces)


def build_mdns_advertiser(
    interfaces: Sequence[str],
    *,
    pairing_open_fn: Callable[[], bool] | None = None,
) -> MdnsAdvertiser:
    """Factory used by the app factory (§10.5: no global mutable state)."""
    return MdnsAdvertiser(interfaces, pairing_open_fn=pairing_open_fn)
