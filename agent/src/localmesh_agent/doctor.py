"""Doctor v1 — the §18.4 ordered checks (WP-13 Agent side, FR-CONN-06, M3).

"Agent (`localmesh-agent doctor`): config valid → data dir perms → TLS cert
valid & pin printed (prefix) → port free/listening → Backends reachable on
loopback → Backend bind-address warnings (CI-06/07) → mDNS advertisement
visible on selected interfaces → firewall rule present for TCP 8443
(OS-specific, best effort) → Tailnet status (via `tailscale` CLI if present)
→ clock sanity → prints findings keyed by CI-ID with fixes." (§18.4 verbatim
order; the §18.1 ladder is walked top-down.)

Design:

- Every probe is injected via `DoctorProbes` (§10.2 spirit: test doubles, the
  WP-13 test note demands "Golden-output tests per CI"); `default_probes()`
  wires the real implementations.
- Findings carry **CI-nn keys** (§18.2) plus an actionable fix; text is
  Metadata-only: the SPKI pin appears as its 12-char prefix (§10.6), and no
  token/secret/Content is ever included (§17.6, §17.10).
- Probes are best effort by spec: firewall/mDNS-browse/tailscale degrade to
  `unknown` findings, never to a crash — doctor must work even when the
  Agent is not running.
- `GET /admin/doctor` (spec-named, §13.1) serves the same findings as JSON;
  the admin layer receives them via an injected callable (no import from
  this module — ADR-014 layering).

Boundaries respected:
- The full Tailscale *adapter* (endpoint discovery for SM-CONN) is WP-14
  (M4); doctor only reads `tailscale status --json` [ASSUMPTION §6.3 fields]
  because §18.4 explicitly includes the check in THIS work package.
- mDNS interface selection is reused from `adapters.discovery.mdns` (WP-11).
"""

from __future__ import annotations

import json
import platform
import shutil
import socket
import ssl
import stat
import subprocess
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from localmesh_agent.adapters.discovery.mdns import default_route_ipv4, resolve_advertise_addresses
from localmesh_agent.adapters.ports import TailnetInfo
from localmesh_agent.config import Settings
from localmesh_agent.security.tls import KEY_FILENAME, TlsIdentityError, load_identity

# §18.4 finding levels (worst last; exit code maps [DESIGN]: 0/1/2).
Level = Literal["ok", "info", "warn", "error"]
_LEVEL_ORDER: dict[str, int] = {"ok": 0, "info": 1, "warn": 2, "error": 3}

PortState = Literal["free", "listening", "occupied"]
FirewallState = Literal["rule-present", "no-rule", "unrestricted", "unknown"]

# §10.6: only the pin PREFIX is display data.
PIN_PREFIX_CHARS = 12

# §6.1/§6.2 native list endpoints used for the loopback probe (§10.3 probe
# paths; the Agent itself uses the same ones in the adapters).
_BACKEND_PROBE_PATH: dict[str, str] = {
    "lmstudio": "/v1/models",
    "ollama": "/api/tags",
    "openai_compat": "/v1/models",
}

# §18.4 check order — the rendering and tests rely on this sequence.
CHECK_ORDER: tuple[str, ...] = (
    "config",
    "data_dir",
    "tls",
    "port",
    "backends",
    "backend_bind",
    "mdns",
    "firewall",
    "tailscale",
    "clock",
)


@dataclass(frozen=True)
class Finding:
    """One doctor finding (§18.4): keyed by CI-ID with an actionable fix."""

    check: str  # one of CHECK_ORDER
    level: Level
    summary: str  # one line; Metadata only (pin prefix, counts, addresses)
    ci_ids: tuple[str, ...] = ()  # §18.2 keys this finding maps to
    detail: str = ""  # optional extra line(s), still Metadata-only
    fix: str = ""  # empty for ok/info findings that need no action

    def to_dict(self) -> dict[str, Any]:
        return {
            "check": self.check,
            "level": self.level,
            "ci_ids": list(self.ci_ids),
            "summary": self.summary,
            "detail": self.detail,
            "fix": self.fix,
        }


@dataclass(frozen=True)
class DoctorProbes:
    """Injectable environment probes (test doubles per WP-13 test note)."""

    port_probe: Callable[[str, int], PortState]
    # (base_url, kind) → (status, version)
    backend_probe: Callable[[str, str], tuple[str, str | None]]
    lan_ip: Callable[[], str | None]
    lan_backend_probe: Callable[[str, int, str], bool]  # (ip, port, path) → reachable
    mdns_addresses: Callable[[], list[str]]
    mdns_browse: Callable[[], int | None]  # _localmesh._tcp instances visible; None = unknown
    firewall_probe: Callable[[int], FirewallState]
    tailscale_probe: Callable[[], TailnetInfo | None]
    wall_now: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))


# ---------------------------------------------------------------------------
# Default (real) probes
# ---------------------------------------------------------------------------


def _info_over_loopback(port: int) -> bool:
    """True when something on 127.0.0.1:port answers `GET /mesh/v1/info` with
    an agent-shaped payload (API-INFO-01). TLS first (§17.3 default), then
    plain HTTP (§17.9 dev mode). Metadata only."""
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE  # self-signed identity is expected here
    for scheme in ("https", "http"):
        try:
            with urllib.request.urlopen(  # noqa: S310 - loopback, scheme pinned above
                f"{scheme}://127.0.0.1:{port}/mesh/v1/info", timeout=2, context=context
            ) as response:
                payload = json.loads(response.read().decode("utf-8") or "{}")
            if isinstance(payload, dict) and "agent_id" in payload:
                return True
        except (urllib.error.URLError, OSError, ValueError):
            continue
    return False


def _port_probe_default(host: str, port: int) -> PortState:
    """Bind test → free; otherwise classify via the loopback /info probe."""
    binder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        binder.bind((host, port))
        return "free"
    except OSError:
        pass
    finally:
        binder.close()
    return "listening" if _info_over_loopback(port) else "occupied"


def _backend_probe_default(base_url: str, kind: str) -> tuple[str, str | None]:
    """Loopback probe with the §6 native list endpoint (§10.3 probe)."""
    import httpx

    path = _BACKEND_PROBE_PATH.get(kind, "/v1/models")
    try:
        with httpx.Client(timeout=httpx.Timeout(3.0)) as client:
            response = client.get(
                base_url.rstrip("/") + path, headers={"Accept": "application/json"}
            )
    except httpx.HTTPError:
        return "down", None
    if response.status_code != 200:
        return "down", None
    return "up", None  # version stays None: no invented values (§13.5)


def _lan_backend_probe_default(ip: str, port: int, path: str) -> bool:
    """CI-06/07 detection: is the Backend ALSO reachable on a LAN address?"""
    import httpx

    try:
        with httpx.Client(timeout=httpx.Timeout(1.5)) as client:
            response = client.get(
                f"http://{ip}:{port}{path}", headers={"Accept": "application/json"}
            )
    except httpx.HTTPError:
        return False
    return response.status_code < 500


def _mdns_addresses_default(settings: Settings) -> list[str]:
    """WP-11 interface selection (§16.2/Appendix E) — reused verbatim."""
    try:
        return resolve_advertise_addresses(settings.mdns.interfaces)
    except Exception:  # noqa: BLE001 - hint service must never crash doctor (T-21)
        return []


def _mdns_browse_default() -> int | None:
    """Best-effort zeroconf browse for `_localmesh._tcp` (2 s). Returns the
    instance count, or None when multicast/zeroconf is unavailable."""
    try:
        from zeroconf.asyncio import AsyncServiceBrowser, AsyncZeroconf
    except Exception:  # noqa: BLE001 - optional dependency path (T-21 hint)
        return None

    import asyncio

    class _Counter:
        def __init__(self) -> None:
            self.count = 0

        def add_service(self, _zc: Any, _type: str, _name: str) -> None:
            self.count += 1

        def update_service(self, _zc: Any, _type: str, _name: str) -> None:
            pass

        def remove_service(self, _zc: Any, _type: str, _name: str) -> None:
            pass

    async def _browse() -> int:
        counter = _Counter()
        aiozc = AsyncZeroconf()
        try:
            browser = AsyncServiceBrowser(
                aiozc.zeroconf, "_localmesh._tcp.local.", listener=counter
            )  # type: ignore[arg-type]
            await asyncio.sleep(2.0)
            await browser.async_cancel()
        finally:
            await aiozc.async_close()
        return counter.count

    try:
        return asyncio.run(asyncio.wait_for(_browse(), timeout=4.0))
    except Exception:  # noqa: BLE001 - multicast unavailable is a legal answer
        return None


def _firewall_probe_default(port: int) -> FirewallState:
    """OS-specific best effort (§18.4): ufw on Linux; netsh on Windows;
    socketfilterfw on macOS; anything else → unknown (manual step)."""
    system = platform.system()
    try:
        if system == "Linux":
            ufw = shutil.which("ufw")
            if ufw is None:
                return "unknown"
            proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
                [ufw, "status"], capture_output=True, text=True, timeout=5, check=False
            )
            out = (proc.stdout + proc.stderr).lower()
            if "inactive" in out:
                return "unrestricted"  # no firewall: nothing blocks the port
            if proc.returncode != 0:
                return "unknown"  # typically needs root; manual step
            return "rule-present" if f"{port}/tcp" in out and "allow" in out else "no-rule"
        if system == "Windows":
            netsh = shutil.which("netsh")
            if netsh is None:
                return "unknown"
            proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
                [netsh, "advfirewall", "firewall", "show", "rule", "name=all"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            return "rule-present" if str(port) in (proc.stdout or "") else "unknown"
        if system == "Darwin":
            fw = "/usr/libexec/ApplicationFirewall/socketfilterfw"
            if not Path(fw).exists():
                return "unknown"
            proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
                [fw, "--getglobalstate"], capture_output=True, text=True, timeout=5, check=False
            )
            return "unknown" if proc.returncode != 0 else "unrestricted"
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    return "unknown"


def _tailscale_probe_default() -> TailnetInfo | None:
    """`tailscale status --json` [ASSUMPTION §6.3 fields]; None = absent."""
    binary = shutil.which("tailscale")
    if binary is None:
        return None
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [binary, "status", "--json"], capture_output=True, text=True, timeout=5, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return TailnetInfo(state="unknown")
    if proc.returncode != 0:
        return TailnetInfo(state="unknown")
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return TailnetInfo(state="unknown")
    state = str(payload.get("BackendState") or "unknown")
    self_obj = payload.get("Self") if isinstance(payload.get("Self"), dict) else {}
    dns_name = self_obj.get("DNSName")
    ips = tuple(str(ip) for ip in (self_obj.get("TailscaleIPs") or [])[:2])
    return TailnetInfo(
        state=state,
        dns_name=str(dns_name).rstrip(".") if dns_name else None,
        ips=ips,
    )


def default_probes(settings: Settings) -> DoctorProbes:
    """Real probes wired against the given settings."""
    return DoctorProbes(
        port_probe=_port_probe_default,
        backend_probe=_backend_probe_default,
        lan_ip=default_route_ipv4,
        lan_backend_probe=_lan_backend_probe_default,
        mdns_addresses=lambda: _mdns_addresses_default(settings),
        mdns_browse=_mdns_browse_default,
        firewall_probe=_firewall_probe_default,
        tailscale_probe=_tailscale_probe_default,
    )


# ---------------------------------------------------------------------------
# The §18.4 ordered checks
# ---------------------------------------------------------------------------


def _check_data_dir(settings: Settings) -> list[Finding]:
    """§14.1: the data dir (and the TLS key inside it) is owner-only."""
    path = settings.resolved_data_dir()
    if not path.is_dir():
        return [
            Finding(
                check="data_dir",
                level="warn",
                summary=f"Data dir {path} does not exist yet.",
                detail="Created on first run with owner-only permissions (§14.1).",
                fix="Run `localmesh-agent run` once, then re-run doctor.",
            )
        ]
    findings: list[Finding] = []
    if platform.system() != "Windows":
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & 0o077:
            findings.append(
                Finding(
                    check="data_dir",
                    level="warn",
                    summary=f"Data dir {path} is readable by group/other (mode {mode:04o}).",
                    detail="§14.1 requires owner-only permissions.",
                    fix=f"`chmod 700 {path}`",
                )
            )
            return findings
    key_path = path / "tls" / KEY_FILENAME
    if key_path.is_file() and platform.system() != "Windows":
        key_mode = stat.S_IMODE(key_path.stat().st_mode)
        if key_mode & 0o077:
            findings.append(
                Finding(
                    check="data_dir",
                    level="warn",
                    summary=f"TLS private key {key_path} is group/other-readable "
                    f"(mode {key_mode:04o}).",
                    ci_ids=("CI-12",),  # exposed key can lead to identity theft → pin mismatch
                    detail="§17.6: the private key file is owner-only (0600).",
                    fix=f"`chmod 600 {key_path}`",
                )
            )
    if not findings:
        findings.append(
            Finding(
                check="data_dir",
                level="ok",
                summary=f"Data dir {path} perms owner-only (§14.1).",
            )
        )
    return findings


def _check_tls(settings: Settings) -> list[Finding]:
    """§18.4: 'TLS cert valid & pin printed (prefix)' — prefix only (§10.6)."""
    tls_dir = settings.resolved_data_dir() / "tls"
    try:
        identity = load_identity(tls_dir)
    except TlsIdentityError as error:
        return [
            Finding(
                check="tls",
                level="error",
                summary=f"TLS identity unusable: {error}",
                ci_ids=("CI-12",),  # phones would fail the pin check (§18.2)
                fix="Restore the identity files or rotate explicitly: "
                "`localmesh-agent doctor --rotate-tls` (§17.5). "
                "All Phones must re-pair after a rotation.",
            )
        ]
    return [
        Finding(
            check="tls",
            level="ok",
            summary=f"TLS identity valid — SPKI pin prefix {identity.pin_prefix} (§17.3).",
            detail="Full pin is never printed (§10.6); Phones verify it via TLS.",
        )
    ]


def _check_port(settings: Settings, probes: DoctorProbes) -> list[Finding]:
    """§18.4: 'port free/listening'; CI-04 when something else holds it."""
    state = probes.port_probe(settings.listen.host, settings.listen.port)
    if state == "free":
        return [
            Finding(
                check="port",
                level="ok",
                summary=f"Port {settings.listen.port} is free "
                "(Agent not running — start it with `localmesh-agent run`).",
            )
        ]
    if state == "listening":
        return [
            Finding(
                check="port",
                level="ok",
                summary=f"Port {settings.listen.port} is listening "
                "(answered /mesh/v1/info — this Agent).",
            )
        ]
    return [
        Finding(
            check="port",
            level="error",
            summary=f"Port {settings.listen.port} is held by another process (CI-04).",
            ci_ids=("CI-04",),
            detail="The Agent cannot start on it (§18.2 CI-04).",
            fix="Change `listen.port` in config.toml, or stop the other process. "
            "Phones re-learn the port via mDNS/QR.",
        )
    ]


def _check_backends(settings: Settings, probes: DoctorProbes) -> list[Finding]:
    """§18.4: 'Backends reachable on loopback'; CI-05 with per-kind fixes."""
    findings: list[Finding] = []
    for backend in settings.backends:
        if not backend.enabled:
            findings.append(
                Finding(
                    check="backends",
                    level="info",
                    summary=f"Backend '{backend.id}' is disabled in config (skipped).",
                )
            )
            continue
        status, _version = probes.backend_probe(backend.base_url, backend.kind)
        if status == "up":
            findings.append(
                Finding(
                    check="backends",
                    level="ok",
                    summary=f"Backend '{backend.id}' ({backend.kind}) up on loopback.",
                )
            )
            continue
        fix = (
            "Start LM Studio and its local server (§18.2 CI-05)."
            if backend.kind == "lmstudio"
            else "Start Ollama (`ollama serve`) (§18.2 CI-05)."
            if backend.kind == "ollama"
            else "Start the OpenAI-compatible server (§18.2 CI-05)."
        )
        findings.append(
            Finding(
                check="backends",
                level="warn",
                summary=f"Backend '{backend.id}' ({backend.kind}) not reachable on "
                f"{backend.base_url} (CI-05).",
                ci_ids=("CI-05",),
                fix=fix,
            )
        )
    if not settings.backends:
        findings.append(
            Finding(
                check="backends",
                level="warn",
                summary="No Backends configured — chat will return BACKEND_UNAVAILABLE.",
                ci_ids=("CI-05",),
                fix="Add an [[backends]] block to config.toml (Appendix E).",
            )
        )
    return findings


def _check_backend_bind(settings: Settings, probes: DoctorProbes) -> list[Finding]:
    """§18.4: 'Backend bind-address warnings (CI-06/07)' — spec-named
    detection: the Doctor probes the Backend on a LAN address (§18.2 Det)."""
    lan_ip = probes.lan_ip()
    if lan_ip is None:
        return [
            Finding(
                check="backend_bind",
                level="info",
                summary="No LAN IPv4 (offline?) — CI-06/CI-07 bind checks skipped.",
            )
        ]
    findings: list[Finding] = []
    for backend in settings.backends:
        if not backend.enabled or backend.kind not in ("lmstudio", "ollama"):
            continue
        port = backend.base_url.rsplit(":", 1)[-1]
        if not port.isdigit():
            continue
        path = _BACKEND_PROBE_PATH[backend.kind]
        if not probes.lan_backend_probe(lan_ip, int(port), path):
            continue
        if backend.kind == "lmstudio":
            findings.append(
                Finding(
                    check="backend_bind",
                    level="warn",
                    summary=f"LM Studio answers on LAN address {lan_ip}:{port} (CI-06) — "
                    "'serve on local network' is not needed (SEC-N2).",
                    ci_ids=("CI-06",),
                    detail="The Agent uses loopback only (§10.3).",
                    fix="Turn LM Studio's local-network serving off.",
                )
            )
        else:
            findings.append(
                Finding(
                    check="backend_bind",
                    level="warn",
                    summary=f"Ollama answers on LAN address {lan_ip}:{port} without auth "
                    f"(CI-07) — reachable beyond this machine.",
                    ci_ids=("CI-07",),
                    detail="OLLAMA_HOST is likely 0.0.0.0 (§18.2 CI-07).",
                    fix="Rebind Ollama to 127.0.0.1 or firewall the port from the LAN.",
                )
            )
    if not findings:
        findings.append(
            Finding(
                check="backend_bind",
                level="ok",
                summary="No Backend exposure beyond loopback detected (SEC-N2).",
            )
        )
    return findings


def _check_mdns(settings: Settings, probes: DoctorProbes, agent_running: bool) -> list[Finding]:
    """§18.4: 'mDNS advertisement visible on selected interfaces'. Hint-layer
    only (T-21): unknown/absent multicast never blocks."""
    if not settings.mdns.enabled:
        return [
            Finding(
                check="mdns",
                level="info",
                summary="mDNS advertisement disabled in config ([mdns] enabled=false).",
            )
        ]
    addresses = probes.mdns_addresses()
    if not addresses:
        return [
            Finding(
                check="mdns",
                level="warn",
                summary="No advertisable private IPv4 — LAN discovery will not find "
                "this Agent (CI-24 pattern).",
                ci_ids=("CI-24", "CI-01"),
                detail="Virtual adapters are excluded by default (CI-24).",
                fix="Connect a network, or set `[mdns] interfaces` in config.toml.",
            )
        ]
    if not agent_running:
        return [
            Finding(
                check="mdns",
                level="info",
                summary=f"Interface selection resolves {len(addresses)} address(es) "
                f"({', '.join(addresses[:3])}); advertisement starts with the Agent.",
            )
        ]
    seen = probes.mdns_browse()
    if seen is None:
        return [
            Finding(
                check="mdns",
                level="info",
                summary=f"Advertising on {len(addresses)} address(es); multicast browse "
                "unavailable here (visibility unverified, T-21 hint layer).",
            )
        ]
    if seen == 0:
        return [
            Finding(
                check="mdns",
                level="warn",
                summary="Agent is running but no _localmesh._tcp instance is visible via "
                "multicast (CI-01 pattern on this host).",
                ci_ids=("CI-01",),
                detail="Phones can still connect via stored endpoints/QR/Tailnet (§18.2 CI-01).",
                fix="Check the network's multicast/AP-isolation settings (§18.2 CI-01).",
            )
        ]
    return [
        Finding(
            check="mdns",
            level="ok",
            summary=f"mDNS advertisement visible ({seen} instance(s) browsed, "
            f"{len(addresses)} advertised address(es)).",
        )
    ]


def _check_firewall(settings: Settings, probes: DoctorProbes) -> list[Finding]:
    """§18.4: 'firewall rule present for TCP 8443 (OS-specific, best effort)'."""
    state = probes.firewall_probe(settings.listen.port)
    if state == "rule-present":
        return [
            Finding(
                check="firewall",
                level="ok",
                summary=f"Firewall allows inbound TCP {settings.listen.port} (§18.7).",
            )
        ]
    if state == "unrestricted":
        return [
            Finding(
                check="firewall",
                level="ok",
                summary="Firewall inactive/unrestricted — nothing blocks the port (§18.7).",
            )
        ]
    if state == "no-rule":
        return [
            Finding(
                check="firewall",
                level="warn",
                summary=f"No firewall rule allows inbound TCP {settings.listen.port} "
                "(CI-03 pattern for LAN Phones).",
                ci_ids=("CI-03",),
                detail="Phones on this LAN would time out connecting (§18.2 CI-03).",
                fix="Allow inbound TCP 8443 for the Private profile (§18.7), "
                'e.g. `sudo ufw allow 8443/tcp`; set the network profile to "Private".',
            )
        ]
    return [
        Finding(
            check="firewall",
            level="info",
            summary="Firewall state unknown here — verify a rule allows inbound TCP "
            f"{settings.listen.port} (§18.7, manual step).",
        )
    ]


def _check_tailscale(probes: DoctorProbes) -> list[Finding]:
    """§18.4: 'Tailnet status (via tailscale CLI if present)' [ASSUMPTION
    §6.3 fields]. Agent-side mapping: state ≠ Running → CI-15 pattern."""
    info = probes.tailscale_probe()
    if info is None:
        return [
            Finding(
                check="tailscale",
                level="info",
                summary="Tailscale CLI not installed — LAN-only mode (§18.5).",
                detail="Away-from-home use needs Tailscale on PC + Phone (§18.5 playbook 2).",
            )
        ]
    if info.state == "Running":
        where = info.dns_name or (info.ips[0] if info.ips else "tailnet")
        return [
            Finding(
                check="tailscale",
                level="ok",
                summary=f"Tailnet up — reachable as {where} (T2 endpoint, §6.3).",
            )
        ]
    if info.state == "unknown":
        return [
            Finding(
                check="tailscale",
                level="info",
                summary="Tailscale CLI present but its state is unreadable here "
                "(§6.3 fields are [ASSUMPTION]).",
            )
        ]
    return [
        Finding(
            check="tailscale",
            level="warn",
            summary=f"Tailscale present but not running (state: {info.state}) — "
            "Phones cannot use T2 endpoints (CI-15 pattern).",
            ci_ids=("CI-15",),
            fix="Start Tailscale and confirm the tailnet account (§18.2 CI-15).",
        )
    ]


def _check_clock(probes: DoctorProbes) -> list[Finding]:
    """§18.4: 'clock sanity'. CI-23: token expiry is monotonic by design, so
    wall-clock skew cannot break auth — but certs/audit use the wall clock."""
    now = probes.wall_now()
    if now.year < 2024:  # [DESIGN] plausibility floor for a 2026-dated spec
        return [
            Finding(
                check="clock",
                level="warn",
                summary=f"System clock implausible ({now.isoformat()}) — certificate "
                "validation and audit timestamps would be wrong.",
                ci_ids=("CI-23",),
                detail="Auth token expiry itself is monotonic-clock based (CI-23, by design).",
                fix="Sync the system clock (NTP).",
            )
        ]
    return [
        Finding(
            check="clock",
            level="ok",
            summary=f"Clock sanity ok (UTC {now.strftime('%Y-%m-%d')}); token expiry uses "
            "the monotonic clock (CI-23 immune by design).",
        )
    ]


def run_doctor(
    settings: Settings | None,
    probes: DoctorProbes | None = None,
    *,
    config_error: str | None = None,
) -> list[Finding]:
    """Run the §18.4 ladder in order and return findings in that order.

    `config_error` short-circuits the ladder with the single `config`
    finding when the settings could not even be loaded (the CLI passes the
    exception text; §18.4 check 1) — `settings` may be None then.
    """
    if config_error is not None or settings is None:
        return [
            Finding(
                check="config",
                level="error",
                summary=f"Configuration invalid: {config_error or 'no settings'}",
                detail="The remaining checks need a valid config (§18.4 check 1).",
                fix="Fix config.toml (Appendix E is the exact key contract).",
            )
        ]
    probes = probes or default_probes(settings)

    findings: list[Finding] = [
        Finding(
            check="config",
            level="ok",
            summary="Configuration valid (Appendix E key contract, strict).",
        )
    ]
    findings += _check_data_dir(settings)
    findings += _check_tls(settings)

    port_findings = _check_port(settings, probes)
    findings += port_findings
    agent_running = any(
        f.check == "port" and f.level == "ok" and "listening" in f.summary for f in port_findings
    )

    findings += _check_backends(settings, probes)
    findings += _check_backend_bind(settings, probes)
    findings += _check_mdns(settings, probes, agent_running)
    findings += _check_firewall(settings, probes)
    findings += _check_tailscale(probes)
    findings += _check_clock(probes)

    order = {name: i for i, name in enumerate(CHECK_ORDER)}
    findings.sort(key=lambda f: order.get(f.check, len(order)))
    return findings


# ---------------------------------------------------------------------------
# Rendering (text for the CLI; JSON for GET /admin/doctor)
# ---------------------------------------------------------------------------


def worst_level(findings: list[Finding]) -> Level:
    """Highest-severity level present (exit-code driver, [DESIGN])."""
    worst: Level = "ok"
    for finding in findings:
        if _LEVEL_ORDER[finding.level] > _LEVEL_ORDER[worst]:
            worst = finding.level
    return worst


def render_text(findings: list[Finding], *, header: str | None = None) -> str:
    """Deterministic text output; findings keyed by CI-ID with fixes (§18.4).

    `header` is printed verbatim when given (the CLI supplies the timestamped
    line; golden tests pass a fixed one).
    """
    lines = [header] if header else []
    if not header:
        lines.append("LocalMesh Agent doctor — LM-ARCH-001 §18.4 connection ladder")
    lines.append("")
    for finding in findings:
        marker = f"[{finding.level}]"
        suffix = f" ({', '.join(finding.ci_ids)})" if finding.ci_ids else ""
        lines.append(f"{marker:<8}{finding.check:<14}{finding.summary}{suffix}")
        if finding.detail:
            lines.append(f"{'':<8}{'':<14}{finding.detail}")
        if finding.fix:
            lines.append(f"{'':<8}{'':<14}fix: {finding.fix}")
    worst = worst_level(findings)
    lines.append("")
    if worst == "ok":
        lines.append("all checks ok")
    else:
        lines.append(f"worst finding level: {worst} ({len(findings)} finding(s))")
    return "\n".join(lines)
