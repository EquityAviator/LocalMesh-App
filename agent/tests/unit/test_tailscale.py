"""WP-14 — TailnetProbe adapter units (§6.3, §10.2, §10.5, §16.1, §18.6).

Parser expectations follow the §6.3 CLI facts table — `BackendState`,
`Self.TailscaleIPs`, `Self.DNSName` — each marked `[ASSUMPTION — verify
against installed version]`. No tailscale binary exists in the dev sandbox,
so shape-level verification happens via the recorded-output contract test
(announced skip until an owner capture lands; QUESTION-104,
docs/fixtures/CAPTURE.md §3). These units pin the documented shape (a real
install that diverges fails the contract test loudly — §22.3 "Stop-and-ask
if: Tailscale JSON differs") and fully cover the assumption-independent
defensive behaviour.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any

import pytest

from localmesh_agent.adapters.ports import TailnetInfo, TailnetProbe
from localmesh_agent.adapters.tailscale import (
    DEFAULT_PROBE_TIMEOUT_S,
    TailscaleCliProbe,
    parse_tailscale_status_json,
    t2_endpoint_candidates,
)

# §6.3 [ASSUMPTION] shape — placeholders pending a real capture (QUESTION-104).
ASSUMED_RUNNING = {
    "BackendState": "Running",
    "Self": {
        "DNSName": "gaming-pc.tail1234.ts.net.",
        "TailscaleIPs": ["100.101.102.103", "fd7a:115c:a1e0:ab12::1"],
    },
}


def _probe_with(
    *,
    binary: str | None = "/usr/bin/tailscale",
    runner: Any = None,
) -> TailscaleCliProbe:
    """Build a probe with an injected binary resolver and CLI runner."""
    probe = TailscaleCliProbe(binary_resolver=lambda: binary)
    if runner is not None:
        probe._run_cli = runner  # type: ignore[method-assign]
    return probe


# -- protocol conformance (§10.2) -------------------------------------------


def test_probe_satisfies_tailnetprobe_protocol() -> None:
    assert isinstance(TailscaleCliProbe(), TailnetProbe)


def test_default_timeout_is_two_seconds_per_section_10_5() -> None:
    assert DEFAULT_PROBE_TIMEOUT_S == 2.0
    assert TailscaleCliProbe()._timeout_s == 2.0


# -- parser: documented shape ------------------------------------------------


def test_parse_assumed_shape_running() -> None:
    info = parse_tailscale_status_json(json.dumps(ASSUMED_RUNNING))
    assert info.state == "Running"
    assert info.dns_name == "gaming-pc.tail1234.ts.net"  # trailing dot stripped
    # §16.2/CI-25: v1 is IPv4-centric — the IPv6 ULA address is not reported.
    assert info.ips == ("100.101.102.103",)


def test_parse_stopped_state_kept_verbatim() -> None:
    payload = {"BackendState": "Stopped", "Self": {}}
    info = parse_tailscale_status_json(json.dumps(payload))
    assert info.state == "Stopped"
    assert info.dns_name is None and info.ips == ()


# -- parser: defensive degradation (§10.3 rule 2) -----------------------------


@pytest.mark.parametrize(
    "text",
    ["", "not json", "[1,2]", "null", '{"BackendState":'],
    ids=["empty", "garbage", "array", "null", "truncated"],
)
def test_parse_malformed_input_is_unknown_never_raises(text: str) -> None:
    info = parse_tailscale_status_json(text)
    assert info == TailnetInfo(state="unknown")


def test_parse_missing_fields_degrade() -> None:
    info = parse_tailscale_status_json("{}")
    assert info.state == "unknown"
    assert info.dns_name is None
    assert info.ips == ()


def test_parse_wrong_field_types_degrade() -> None:
    payload = {
        "BackendState": 42,
        "Self": {"DNSName": 7, "TailscaleIPs": "100.64.0.1"},
    }
    info = parse_tailscale_status_json(json.dumps(payload))
    assert info.state == "unknown"
    assert info.dns_name is None
    assert info.ips == ()  # not a list → ignored, never guessed


def test_parse_blank_state_is_unknown() -> None:
    info = parse_tailscale_status_json(json.dumps({"BackendState": "   "}))
    assert info.state == "unknown"


# -- parser: CGNAT filter (§6.3 addressing row) -------------------------------


def test_parse_ips_filtered_to_cgnat_range_and_deduped() -> None:
    payload = {
        "BackendState": "Running",
        "Self": {
            "TailscaleIPs": [
                "100.64.0.1",
                "192.168.1.5",  # LAN-looking — not Tailscale, dropped
                "100.64.0.1",  # duplicate — dropped
                "8.8.8.8",  # public — dropped
                "not-an-ip",  # garbage — dropped
                "100.115.92.1",  # kept
            ]
        },
    }
    info = parse_tailscale_status_json(json.dumps(payload))
    assert info.ips == ("100.64.0.1", "100.115.92.1")


def test_parse_ips_cap_defends_against_garbage_volume() -> None:
    payload = {
        "BackendState": "Running",
        "Self": {"TailscaleIPs": ["100.64.0.255"] * 5000},
    }
    info = parse_tailscale_status_json(json.dumps(payload))
    assert len(info.ips) <= 4


# -- probe: presence/state semantics (§10.2 "None if tailscale absent") -------


async def test_probe_absent_binary_returns_none() -> None:
    probe = _probe_with(binary=None)
    assert await probe.status() is None


async def test_probe_parses_cli_stdout() -> None:
    captured: dict[str, Any] = {}

    def runner(binary: str) -> subprocess.CompletedProcess[str]:
        captured["binary"] = binary
        return subprocess.CompletedProcess(
            [binary, "status", "--json"], 0, json.dumps(ASSUMED_RUNNING), ""
        )

    info = await _probe_with(runner=runner).status()
    assert captured["binary"] == "/usr/bin/tailscale"
    assert info is not None
    assert info.state == "Running"
    assert info.ips == ("100.101.102.103",)


async def test_probe_timeout_degrades_to_unknown() -> None:
    def runner(binary: str) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired([binary, "status", "--json"], timeout=2.0)

    info = await _probe_with(runner=runner).status()
    assert info == TailnetInfo(state="unknown")


async def test_probe_nonzero_exit_degrades_to_unknown() -> None:
    def runner(binary: str) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([binary, "status", "--json"], 1, "", "errored")

    info = await _probe_with(runner=runner).status()
    assert info == TailnetInfo(state="unknown")


async def test_probe_spawn_oserror_degrades_to_unknown() -> None:
    def runner(binary: str) -> subprocess.CompletedProcess[str]:
        raise OSError("cannot spawn")

    info = await _probe_with(runner=runner).status()
    assert info == TailnetInfo(state="unknown")


# -- T2 endpoint candidates (§16.1 step 4, §17.4 ep, §18.5 playbook 2) --------


def test_t2_candidates_dns_first_then_ips() -> None:
    info = TailnetInfo(
        state="Running", dns_name="gaming-pc.tail.ts.net", ips=("100.64.0.1", "100.115.92.1")
    )
    assert t2_endpoint_candidates(info, 8443) == (
        "https://gaming-pc.tail.ts.net:8443",
        "https://100.64.0.1:8443",
        "https://100.115.92.1:8443",
    )


def test_t2_candidates_gate_on_running_state() -> None:
    stopped = TailnetInfo(state="Stopped", dns_name="gaming-pc.tail.ts.net", ips=("100.64.0.1",))
    assert t2_endpoint_candidates(stopped, 8443) == ()
    assert t2_endpoint_candidates(None, 8443) == ()
    running_empty = TailnetInfo(state="Running")
    assert t2_endpoint_candidates(running_empty, 8443) == ()
    assert t2_endpoint_candidates(TailnetInfo(state="Running", ips=("100.64.0.1",)), None) == ()
