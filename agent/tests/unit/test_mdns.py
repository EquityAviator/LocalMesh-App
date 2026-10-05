"""WP-11 unit tests — mDNS advertisement (§16.2, FR-AGT-04, CI-24).

Covers: instance-name shape, TXT record contract (keys/values/limits/fp
hint), interface selection (virtual-adapter exclusion, private-IPv4-only,
explicit config, default-route preference, offline fallback), advertiser
lifecycle against a stubbed AsyncZeroconf (register/unregister/re-announce,
watchdog no-op vs re-register on change), and QR endpoint resolution
(QUESTION-103 item 5: LAN IP leads the QR `ep` list).

No real network/multicast is touched: zeroconf is stubbed, psutil and the
UDP-connect default-route probe are monkeypatched.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any

import pytest

from localmesh_agent.adapters.discovery import mdns as mdns_mod
from localmesh_agent.adapters.ports import ServiceAd

# ---------------------------------------------------------------------------
# stubs
# ---------------------------------------------------------------------------


class StubServiceInfo:
    """Captures the ServiceInfo kwargs the advertiser passes."""

    infos: list[dict[str, Any]] = []

    def __init__(self, type_: str, name: str, **kwargs: Any) -> None:
        self.type_ = type_
        self.name = name
        self.kwargs = kwargs
        StubServiceInfo.infos.append({"type": type_, "name": name, **kwargs})


class StubAsyncZeroconf:
    """Records register/unregister/close calls; no sockets involved."""

    instances: list[StubAsyncZeroconf] = []

    def __init__(self, interfaces: Any = None) -> None:  # noqa: ANN001
        self.interfaces = interfaces
        self.registered: list[StubServiceInfo] = []
        self.unregistered: list[StubServiceInfo] = []
        self.closed = False
        StubAsyncZeroconf.instances.append(self)

    async def async_register_service(self, info: StubServiceInfo) -> None:
        self.registered.append(info)

    async def async_unregister_service(self, info: StubServiceInfo) -> None:
        self.unregistered.append(info)

    async def async_close(self) -> None:
        self.closed = True


@pytest.fixture()
def stub_zc(monkeypatch: pytest.MonkeyPatch) -> Iterator[type[StubAsyncZeroconf]]:
    """Patch the zeroconf classes the advertiser imports lazily."""
    StubAsyncZeroconf.instances = []
    StubServiceInfo.infos = []
    monkeypatch.setattr("zeroconf.asyncio.AsyncZeroconf", StubAsyncZeroconf)
    monkeypatch.setattr("zeroconf.ServiceInfo", StubServiceInfo)
    yield StubAsyncZeroconf


@pytest.fixture(autouse=True)
def fake_net(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deterministic interface map + default route for every test.

    Mirrors the REAL interface_ipv4_map contract: virtual interfaces and
    non-private IPv4s are ALREADY filtered out — only eth0/wlan0 appear.
    """
    monkeypatch.setattr(
        mdns_mod,
        "interface_ipv4_map",
        lambda: {
            "eth0": ["192.168.1.10"],
            "wlan0": ["192.168.1.11"],
        },
    )
    monkeypatch.setattr(mdns_mod, "default_route_ipv4", lambda: "192.168.1.10")


def make_ad(**overrides: Any) -> ServiceAd:
    base: dict[str, Any] = dict(
        agent_id="ag_0192abcd-1234-7abc-9def-0123456789ab",
        display_name="Gaming PC",
        port=8443,
        txt=mdns_mod.build_txt(
            "ag_0192abcd-1234-7abc-9def-0123456789ab",
            "Gaming PC",
            "qUyZ0123456789abcdefghij-k lmnopqrstuvwxyz_-",
            pairing_open=False,
        ),
    )
    base.update(overrides)
    return ServiceAd(**base)


# ---------------------------------------------------------------------------
# instance name + TXT (§16.2 verbatim contract)
# ---------------------------------------------------------------------------


def test_instance_name_is_display_plus_first_six_of_agent_uuid() -> None:
    """§16.2: "<display_name> (<first 6 of agent uuid>)" — uuid part only."""
    assert mdns_mod.build_instance_name("Gaming PC", "ag_0192ab-xx") == "Gaming PC (0192ab)"
    # no prefix → uuid taken verbatim
    assert mdns_mod.build_instance_name("Box", "abcdef-rest") == "Box (abcdef)"


def test_txt_record_keys_and_values_verbatim() -> None:
    """§16.2 TXT: v=1, aid, n, fp (16 chars), api=v1, po=0|1."""
    txt = mdns_mod.build_txt(
        "ag_0192abcd", "Gaming PC", "AAAAAAAAAAAAAAAA0123456789", pairing_open=True
    )
    assert txt == {
        "v": "1",
        "aid": "ag_0192abcd",
        "n": "Gaming PC",
        "fp": "AAAAAAAAAAAAAAAA",
        "api": "v1",
        "po": "1",
    }
    assert mdns_mod.build_txt("ag_x", "n", "p", pairing_open=False)["po"] == "0"


def test_txt_values_respect_255_byte_limit() -> None:
    """§16.2: each TXT value ≤ 255 bytes — `n` is truncated, never dropped."""
    long_name = "é" * 300  # 600 bytes UTF-8
    txt = mdns_mod.build_txt("ag_x", long_name, "p", pairing_open=False)
    assert len(txt["n"].encode("utf-8")) <= 255


def test_service_ad_carries_txt_and_port() -> None:
    ad = mdns_mod.build_service_ad("ag_0192abcd", "Gaming PC", 8443, "p", pairing_open=False)
    assert ad.port == 8443
    assert ad.txt["v"] == "1" and ad.txt["api"] == "v1"


# ---------------------------------------------------------------------------
# interface selection (§16.2 + CI-24)
# ---------------------------------------------------------------------------


def test_virtual_and_nonprivate_interfaces_are_excluded() -> None:
    """CI-24: docker/tailscale/etc. excluded; RFC1918 private IPv4 only."""
    assert not mdns_mod.is_virtual_interface("eth0")
    assert mdns_mod.is_virtual_interface("vEthernet (WSL (Hyper-V))")
    assert mdns_mod.is_virtual_interface("DockerNAT")
    assert mdns_mod.is_virtual_interface("tailscale0")
    assert mdns_mod.is_virtual_interface("utun3")


def test_default_route_interface_wins_when_config_empty() -> None:
    """§16.2: empty config → private IPv4s of the default-route interface."""
    assert mdns_mod.resolve_advertise_addresses([]) == ["192.168.1.10"]


def test_explicit_interface_names_are_respected() -> None:
    """FR-AGT-04: advertise on the SELECTED interfaces only."""
    assert mdns_mod.resolve_advertise_addresses(["wlan0"]) == ["192.168.1.11"]


def test_explicit_literal_ip_is_accepted() -> None:
    assert mdns_mod.resolve_advertise_addresses(["192.168.1.10"]) == ["192.168.1.10"]


def test_unknown_or_virtual_config_names_are_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unknown names log + skip (FR-AGT-04: only selected ones advertise)."""
    monkeypatch.setattr(mdns_mod, "default_route_ipv4", lambda: None)  # avoid fallback noise
    assert mdns_mod.resolve_advertise_addresses(["does-not-exist"]) == []
    # virtual interfaces never reach the map (filtered upstream) → unknown name
    assert mdns_mod.resolve_advertise_addresses(["docker0"]) == []


def test_offline_fallback_advertises_non_virtual_interfaces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[DESIGN] No default route (offline) → all non-virtual private IPv4s."""
    monkeypatch.setattr(mdns_mod, "default_route_ipv4", lambda: None)
    ips = mdns_mod.resolve_advertise_addresses([])
    assert ips == ["192.168.1.10", "192.168.1.11"]


def test_vpn_egress_is_not_advertised(monkeypatch: pytest.MonkeyPatch) -> None:
    """CI-24: if the default route rides a filtered (virtual) interface,
    prefer NOT advertising over advertising a virtual address."""
    monkeypatch.setattr(mdns_mod, "default_route_ipv4", lambda: "100.64.0.1")
    assert mdns_mod.resolve_advertise_addresses([]) == []


def test_public_egress_ip_is_not_advertised(monkeypatch: pytest.MonkeyPatch) -> None:
    """§16.2 advertises PRIVATE IPv4s only — a public egress IP (direct
    public interface, some VPS shapes) is not a discovery address."""
    monkeypatch.setattr(mdns_mod, "default_route_ipv4", lambda: "9.9.9.9")
    assert mdns_mod.resolve_advertise_addresses([]) == []


# ---------------------------------------------------------------------------
# advertiser lifecycle (stubbed zeroconf)
# ---------------------------------------------------------------------------


async def test_start_registers_service_with_spec_shape(stub_zc: type[StubAsyncZeroconf]) -> None:
    adv = mdns_mod.MdnsAdvertiser([])
    await adv.start(make_ad())
    assert adv.advertising
    assert stub_zc.instances, "AsyncZeroconf constructed"
    (zc,) = stub_zc.instances
    assert len(zc.registered) == 1
    info = zc.registered[0]
    assert info.type_ == "_localmesh._tcp.local."
    assert info.name.startswith("Gaming PC (0192ab).")
    assert info.kwargs["port"] == 8443
    assert info.kwargs["properties"]["aid"] == "ag_0192abcd-1234-7abc-9def-0123456789ab"
    assert info.kwargs["properties"]["fp"] == "qUyZ0123456789ab"[:16]
    # addresses are packed IPv4 of the default-route interface
    import socket as _socket

    assert b"".join(info.kwargs["addresses"]) == _socket.inet_aton("192.168.1.10")
    await adv.stop()
    assert not adv.advertising
    assert zc.unregistered and zc.closed


async def test_start_without_addresses_degrades_to_not_advertising(
    stub_zc: type[StubAsyncZeroconf], monkeypatch: pytest.MonkeyPatch
) -> None:
    """T-21 hint service: nothing resolvable → log + no registration."""
    monkeypatch.setattr(mdns_mod, "resolve_advertise_addresses", lambda _: [])
    adv = mdns_mod.MdnsAdvertiser([])
    await adv.start(make_ad())
    assert not adv.advertising
    assert not stub_zc.instances
    await adv.stop()  # must be safe


async def test_refresh_noops_when_nothing_changed(stub_zc: type[StubAsyncZeroconf]) -> None:
    adv = mdns_mod.MdnsAdvertiser([])
    await adv.start(make_ad())
    (zc,) = stub_zc.instances
    registered_before = list(zc.registered)
    await adv.refresh()
    assert zc.registered == registered_before  # no re-announce
    await adv.stop()


async def test_refresh_reannounces_when_po_flips(stub_zc: type[StubAsyncZeroconf]) -> None:
    """`po` mirrors pairing_open: flip → watchdog/refresh re-announces."""
    open_state = {"open": False}
    adv = mdns_mod.MdnsAdvertiser([], pairing_open_fn=lambda: open_state["open"])
    await adv.start(make_ad())  # txt built with pairing_open=False → po=0
    (zc,) = stub_zc.instances
    open_state["open"] = True
    await adv.refresh()
    assert len(zc.registered) == 2
    assert zc.registered[1].kwargs["properties"]["po"] == "1"
    assert zc.unregistered  # old registration swapped out
    await adv.stop()


async def test_refresh_reannounces_when_address_changes(
    stub_zc: type[StubAsyncZeroconf], monkeypatch: pytest.MonkeyPatch
) -> None:
    """§16.2: re-announce on interface/address change."""
    adv = mdns_mod.MdnsAdvertiser([])
    await adv.start(make_ad())
    (zc,) = stub_zc.instances
    monkeypatch.setattr(
        mdns_mod,
        "resolve_advertise_addresses",
        lambda _: ["192.168.1.11"],  # DHCP moved the host to wlan0
    )
    await adv.refresh()
    assert adv.addresses == ("192.168.1.11",)
    assert len(zc.registered) == 2
    import socket as _socket

    assert b"".join(zc.registered[1].kwargs["addresses"]) == _socket.inet_aton("192.168.1.11")
    await adv.stop()


async def test_watchdog_refreshes_periodically(
    stub_zc: type[StubAsyncZeroconf], monkeypatch: pytest.MonkeyPatch
) -> None:
    """§16.2 re-announce watchdog ([DESIGN] interval) — fires and refreshes."""
    calls = {"n": 0}

    async def fake_refresh(self: mdns_mod.MdnsAdvertiser, ad: Any = None) -> None:
        calls["n"] += 1

    monkeypatch.setattr(mdns_mod.MdnsAdvertiser, "refresh", fake_refresh)
    adv = mdns_mod.MdnsAdvertiser([], watchdog_interval=0.01)
    await adv.start(make_ad())
    await asyncio.sleep(0.06)
    await adv.stop()
    assert calls["n"] >= 2


async def test_stop_without_start_is_safe() -> None:
    adv = mdns_mod.MdnsAdvertiser([])
    await adv.stop()  # no zeroconf instance, no watchdog → no error
    assert not adv.advertising
