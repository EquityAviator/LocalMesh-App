"""Tailscale CLI/JSON probe — the §10.2 `TailnetProbe` port implementation
(WP-14, M4; §6.3, §16.1 step 4, §18.6, §22.2/§22.3).

Scope fence (§22.1): the Agent NEVER manages the user's Tailscale login —
"it only *detects* (`tailscale` CLI present? running?) and *reports* name/IPs"
(§18.6). Tailnet membership is connectivity Metadata, never authorization
(SEC-N4: "Network position (LAN or tailnet membership) is never authorization").

Delivered here:

- `parse_tailscale_status_json` — total, defensive parser for
  `tailscale status --json` (§10.3 rule 2: missing/renamed fields → null,
  never an exception; §6.3 CLI facts table).
- `TailscaleCliProbe` — async `status()` per the §10.2 port; the blocking
  subprocess runs in a thread pool with a 2 s timeout (§10.5: "Blocking work
  (NVML, psutil, subprocess for `tailscale`) runs in a thread pool with
  timeouts (2 s)").
- `t2_endpoint_candidates` — T2 candidate URLs in §16.1 step-4 order
  ("MagicDNS name, then `100.x` IP"); consumed by the pairing QR `ep` list
  (§17.4 `[&ep=…]`, §18.5 playbook 2: "QR carries Tailnet name/IP if the
  Agent detected them") and by API-PAIR-02 `endpoints.tailnet` (§13.2).

Consumers:
- `app.py` startup (§10.6 step 7: ready log carries the Tailnet status) and
  the pairing snapshot (§18.6 "reports name/IPs … in pairing `endpoints`").
- `doctor.py` check 9 (§18.4 "Tailnet status (via `tailscale` CLI if
  present)") — the doctor subprocess wrapper shares THIS parser so both
  surfaces interpret a real install identically.
- `GET /device` reports the same block when WP-15 lands (§13.2/FR-CONN-08;
  scope fence — NOT pulled forward here, §22.1).

Verification status (Appendix G): the `status --json` field names are
§6.3 `[ASSUMPTION]` ("verify against installed version"). No tailscale
binary exists in the dev sandbox, so the recorded-output contract test is an
announced skip until an owner capture lands (docs/fixtures/CAPTURE.md §3,
QUESTION-104). The parser below implements exactly the documented shape; if
a real install diverges, the contract test fails loudly (§22.3 "Stop-and-ask
if: Tailscale JSON differs") and the fix is local to this module.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import shutil
import subprocess
from collections.abc import Callable
from typing import Any

from localmesh_agent.adapters.ports import TailnetInfo
from localmesh_agent.observability.logging import get_logger

log = get_logger("tailscale")

# §10.5: subprocess work for tailscale runs with a 2 s timeout [SPEC].
DEFAULT_PROBE_TIMEOUT_S = 2.0

# §6.3: "Tailnet IPs in `100.64.0.0/10`" — the CGNAT range Tailscale allocates
# from. Anything else in `Self.TailscaleIPs` (e.g. IPv6 ULA fd7a::/48, which v1
# does not advertise — §16.2 "IPv6 not advertised in v1", CI-25) is dropped
# rather than reported, because §13.2 forbids filling unknowns with guesses.
TAILNET_CGNAT_V4 = ipaddress.ip_network("100.64.0.0/10")

# Defensive cap on reported addresses (a real install reports 1-2).
MAX_REPORTED_IPS = 4

_MAX_IPS_FROM_CLI = 8  # parse bound before filtering (protects against garbage)


def _clean_dns_name(value: Any) -> str | None:
    """§6.3 MagicDNS name; CLI emits a trailing dot ("host.tailnet.ts.net.")."""
    if not isinstance(value, str):
        return None
    name = value.strip().rstrip(".")
    return name or None


def _clean_ips(value: Any) -> tuple[str, ...]:
    """Keep only well-formed IPv4 addresses inside 100.64.0.0/10 (§6.3)."""
    if not isinstance(value, list):
        return ()
    out: list[str] = []
    for raw in value[:_MAX_IPS_FROM_CLI]:
        try:
            ip = ipaddress.ip_address(str(raw))
        except ValueError:
            continue
        if ip.version == 4 and ip in TAILNET_CGNAT_V4:
            text = str(ip)
            if text not in out:
                out.append(text)
        if len(out) >= MAX_REPORTED_IPS:
            break
    return tuple(out)


def parse_tailscale_status_json(text: str) -> TailnetInfo:
    """Parse `tailscale status --json` output (total — never raises).

    Field names follow §6.3 `[ASSUMPTION]`: `BackendState`, `Self.TailscaleIPs`,
    `Self.DNSName` ("verify against installed version" — QUESTION-104). Any
    missing/renamed field degrades to the unknown-info shape (§10.3 rule 2);
    malformed JSON degrades to `state="unknown"` rather than raising, so
    callers never need a try/except around parsing (§18.4 doctor contract:
    probes are best effort and must not crash the ladder).
    """
    try:
        payload: Any = json.loads(text)
    except json.JSONDecodeError:
        return TailnetInfo(state="unknown")
    if not isinstance(payload, dict):
        return TailnetInfo(state="unknown")
    state_raw = payload.get("BackendState")
    state = state_raw.strip() if isinstance(state_raw, str) and state_raw.strip() else "unknown"
    self_obj = payload.get("Self") if isinstance(payload.get("Self"), dict) else {}
    return TailnetInfo(
        state=state,
        dns_name=_clean_dns_name(self_obj.get("DNSName")),
        ips=_clean_ips(self_obj.get("TailscaleIPs")),
    )


def t2_endpoint_candidates(info: TailnetInfo | None, port: int | None) -> tuple[str, ...]:
    """T2 endpoint URLs in §16.1 step-4 order: MagicDNS name, then `100.x` IPs.

    Only a *running* tailnet yields candidates (a Stopped/NeedsLogin Backend
    reports stale or absent addresses); empty output means "no T2 candidate",
    which callers surface as `endpoints.tailnet: null` (§13.2) and as simply
    no extra `ep` in the QR (§17.4).
    """
    if info is None or port is None or info.state.lower() != "running":
        return ()
    out: list[str] = []
    if info.dns_name:
        out.append(f"https://{info.dns_name}:{port}")
    out.extend(f"https://{ip}:{port}" for ip in info.ips)
    return tuple(out)


class TailscaleCliProbe:
    """`TailnetProbe` port implementation (§10.2): `None` if tailscale absent.

    `binary_resolver` is injectable for tests (the DoctorProbes pattern);
    the default resolves `tailscale` via `PATH`. Presence vs state semantics
    (§10.2 + §18.4):
    - binary not found → `None` (tailscale absent — LAN-only mode, §18.5);
    - present but unreadable (timeout / non-zero exit / spawn failure /
      malformed output) → `TailnetInfo(state="unknown")` — the doctor and the
      ready log distinguish "absent" from "present but unreadable";
    - otherwise the parsed §6.3 shape.
    """

    def __init__(
        self,
        *,
        timeout_s: float = DEFAULT_PROBE_TIMEOUT_S,
        binary_resolver: Callable[[], str | None] | None = None,
    ) -> None:
        self._timeout_s = timeout_s
        self._binary_resolver = binary_resolver or (lambda: shutil.which("tailscale"))

    def _run_cli(self, binary: str) -> subprocess.CompletedProcess[str]:
        # §6.3 CLI facts: `tailscale status --json` is expected to expose
        # BackendState / Self.TailscaleIPs / Self.DNSName [ASSUMPTION].
        # noqa: S603 - fixed argv, no shell, resolved binary
        return subprocess.run(  # noqa: S603
            [binary, "status", "--json"],
            capture_output=True,
            text=True,
            timeout=self._timeout_s,
            check=False,
        )

    async def status(self) -> TailnetInfo | None:
        """Async port call; the blocking subprocess runs in a thread (§10.5)."""
        binary = self._binary_resolver()
        if binary is None:
            return None
        try:
            proc = await asyncio.to_thread(self._run_cli, binary)
        except subprocess.TimeoutExpired:
            log.warning(
                "tailscale_probe_timeout",
                extra={"component": "tailscale", "status": "unknown"},
            )
            return TailnetInfo(state="unknown")
        except OSError:
            log.warning(
                "tailscale_probe_spawn_failed",
                extra={"component": "tailscale", "status": "unknown"},
            )
            return TailnetInfo(state="unknown")
        if proc.returncode != 0:
            return TailnetInfo(state="unknown")
        return parse_tailscale_status_json(proc.stdout)
