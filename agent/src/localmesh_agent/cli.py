"""Agent CLI: `run | doctor | pair | devices | revoke` (LM-ARCH-001 §10.1).

WP-08 (M2) topology (§10.5/§10.6 step 6): ONE process, TWO listeners —
the public Mesh API (TLS 1.3 only, §17.3) on `[listen].host:port` and the
admin listener (HTTP, ADR-014) bound to 127.0.0.1:`[listen].admin_port`.
`--dev-insecure-loopback` (§17.9) keeps the M1 HTTP loopback listener for
development and is never a default (SEC-N6).

`pair` / `devices` / `revoke` are operator commands (§15.4/§15.6): they talk
to the ADMIN listener of the RUNNING Agent over loopback HTTP with the
per-install admin token (ADR-014) — pairing sessions and device state live in
the Agent process, so the CLI is an admin client, not a second authority.
`doctor` remains WP-13 (M3) and reports its milestone (§1.2).
"""

from __future__ import annotations

import argparse
import json
import signal
import ssl
import sys
import time
import urllib.error
import urllib.request

from localmesh_agent.config import load_settings

_DEV_FLAG = "--dev-insecure-loopback"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="localmesh-agent",
        description="LocalMesh AI Desktop Agent (LM-ARCH-001 §10.1)",
    )
    sub = parser.add_subparsers(dest="command")

    run_parser = sub.add_parser("run", help="start the Agent (public TLS 1.3 + admin listener)")
    run_parser.add_argument("--config", default=None, help="path to config.toml")
    run_parser.add_argument(
        _DEV_FLAG,
        dest="dev_insecure",
        action="store_true",
        help=(
            "Development mode: HTTP listener bound to 127.0.0.1 ONLY (§17.9). "
            "Off by default (SEC-N6); the default is TLS 1.3 (§17.3)."
        ),
    )

    pair_parser = sub.add_parser("pair", help="open Pairing Mode and show the QR (§15.4)")
    pair_parser.add_argument("--config", default=None, help="path to config.toml")
    pair_parser.add_argument(
        "--no-wait", action="store_true", help="print the QR and exit (session stays open)"
    )
    pair_parser.add_argument(
        "--approve", action="store_true", help="approve the currently claimed device"
    )
    pair_parser.add_argument(
        "--deny", action="store_true", help="deny the currently claimed device"
    )

    devices_parser = sub.add_parser("devices", help="list paired devices (§15.6)")
    devices_parser.add_argument("--config", default=None, help="path to config.toml")

    revoke_parser = sub.add_parser("revoke", help="revoke a device by id (§15.6, FR-PAIR-06)")
    revoke_parser.add_argument("device_id", help="device id (dv_…) as listed by `devices`")
    revoke_parser.add_argument("--config", default=None, help="path to config.toml")

    doctor_parser = sub.add_parser(
        "doctor", help="run the §18.4 connection-ladder self-check (FR-CONN-06)"
    )
    doctor_parser.add_argument("--config", default=None, help="path to config.toml")
    doctor_parser.add_argument(
        "--json", dest="as_json", action="store_true", help="emit findings as JSON"
    )
    doctor_parser.add_argument(
        "--rotate-tls",
        dest="rotate_tls",
        action="store_true",
        help="explicit TLS key rotation (§17.5) — all Phones must re-pair",
    )
    return parser


# -- admin HTTP client (loopback, ADR-014) -------------------------------------


class AdminUnreachable(RuntimeError):
    """The admin listener is not reachable (Agent not running?)."""

    def __init__(self, reason: str, port: int) -> None:
        super().__init__(
            f"cannot reach the admin listener on 127.0.0.1:{port} ({reason}) — "
            "start the Agent with `localmesh-agent run` first (§15.4)"
        )
        self.port = port


def _admin_request(
    settings: object, method: str, path: str, body: dict[str, object] | None = None
) -> tuple[int, dict[str, object]]:
    """One admin API call; returns (status, json). The token travels ONLY in
    the spec-named `X-Admin-Token` header (§13.1/T-11) — never in a URL
    (§17.6)."""
    from pathlib import Path

    from localmesh_agent.admin_app import load_or_create_admin_token

    data_dir = Path(settings.ensure_data_dir())
    token = load_or_create_admin_token(data_dir)
    port = settings.listen.admin_port  # type: ignore[attr-defined]
    url = f"http://127.0.0.1:{port}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("X-Admin-Token", token)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload: dict[str, object] = json.loads(response.read().decode("utf-8") or "{}")
            return response.status, payload
    except urllib.error.HTTPError as error:
        payload = json.loads(error.read().decode("utf-8") or "{}")
        return error.code, payload
    except urllib.error.URLError as error:
        raise AdminUnreachable(str(error.reason), port) from None


def _print_envelope_error(status: int, payload: dict[str, object]) -> None:
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        print(
            f"error [{error.get('code')}] (HTTP {status}): {error.get('message')}",
            file=sys.stderr,
        )
    else:
        print(f"error: HTTP {status}", file=sys.stderr)


# -- subcommands ---------------------------------------------------------------


def _tls13_server_context(cert_path: str, key_path: str) -> ssl.SSLContext:
    """TLS 1.3-only server context (§17.3) — delegates to the security layer
    so the TC-SEC-10 entry exercises the exact production context."""
    from localmesh_agent.security.tls import build_tls13_server_context

    return build_tls13_server_context(cert_path, key_path)


def _run(args: argparse.Namespace) -> int:
    import asyncio

    import uvicorn

    from localmesh_agent.admin_app import create_admin_app, load_or_create_admin_token
    from localmesh_agent.app import create_app

    settings = load_settings(args.config)
    app = create_app(settings, dev_insecure=args.dev_insecure)

    data_dir = settings.ensure_data_dir()
    admin_token = load_or_create_admin_token(data_dir)

    def _admin_doctor() -> list[dict[str, object]]:
        from localmesh_agent.doctor import run_doctor

        return [f.to_dict() for f in run_doctor(settings)]

    def _admin_status() -> dict[str, object]:
        """§13.1 `GET /admin/status` — shape [DESIGN] (the spec names the
        endpoint, not the body). Metadata ONLY (§17.6): no tokens, no full
        SPKI pin (12-char prefix, same rule as §10.6 doctor), no Content."""
        import time as _time

        state = app.state
        device_rows = state.devices.list()
        active = sum(1 for row in device_rows if row.get("revoked_at") is None)
        pairing_state = state.pairing.pending()[0].value
        tailnet = getattr(state, "tailnet", None)
        return {
            "agent_id": state.agent_id,
            "display_name": settings.agent.display_name,
            "agent_version": state.agent_version,
            "uptime_s": int(_time.monotonic() - state.started_mono),
            "pairing_state": pairing_state,
            "devices": {
                "total": len(device_rows),
                "active": active,
                "revoked": len(device_rows) - active,
            },
            "backends": [
                {
                    "id": str(backend.get("id")),
                    "status": str(backend.get("status")),
                }
                for backend in state.registry.snapshot().get("backends", [])
                if isinstance(backend, dict)
            ],
            "queue": state.scheduler.queue_stats(),
            "listen": {
                "host": "127.0.0.1" if args.dev_insecure else settings.listen.host,
                "port": settings.listen.port,
                "admin_port": settings.listen.admin_port,
                "dev_insecure": args.dev_insecure,  # QUESTION-105 context
            },
            "tls": {
                # T-21 hint semantics: prefix only, never the full pin (§17.6).
                "spki_pin_prefix": str(state.spki_pin)[:12],
            },
            "tailnet": (
                {
                    "state": tailnet.state,
                    "dns_name": tailnet.dns_name,
                    "ips": list(tailnet.ips),
                }
                if tailnet is not None
                else None
            ),
            "control_plane": (
                state.control_plane.status()
                if state.control_plane is not None
                else {"enabled": False, "state": "disabled", "registered": False}
            ),
        }

    def _admin_metrics() -> str:
        """§20.1 Prometheus text exposition — pull gauges refreshed at scrape
        so queue/backend gauges reflect live state (observability.metrics)."""
        state = app.state
        state.metrics.refresh_pull_gauges(scheduler=state.scheduler, registry=state.registry)
        return state.metrics.render_prometheus()

    admin_app = create_admin_app(
        pairing=app.state.pairing,
        devices=app.state.devices,
        tls_rotate=_make_tls_rotate(settings),
        admin_token=admin_token,
        admin_port=settings.listen.admin_port,
        doctor_fn=_admin_doctor,
        status_fn=_admin_status,
        metrics_fn=_admin_metrics,
        control_plane=app.state.control_plane,
        cp_audit_cb=lambda event: app.state.store.append_audit(event),
        backup_pin_fn=lambda pin: app.state.store.set_setting("tls_pin_backup", pin),
    )

    public_host = "127.0.0.1" if args.dev_insecure else settings.listen.host
    if args.dev_insecure:
        print(
            f"localmesh-agent DEV loopback on http://127.0.0.1:{settings.listen.port} "
            f"(§17.9 dev-only; token auth BYPASSED — per-process Device identity, "
            f"QUESTION-105; admin on 127.0.0.1:{settings.listen.admin_port})"
        )
    else:
        print(
            f"localmesh-agent public listener https://{settings.listen.host}:"
            f"{settings.listen.port} (TLS 1.3 only, §17.3) — admin on "
            f"127.0.0.1:{settings.listen.admin_port} (ADR-014)"
        )

    if args.dev_insecure:
        public_config = uvicorn.Config(
            app, host=public_host, port=settings.listen.port, log_level="warning", access_log=False
        )
    else:
        # §17.3: TLS 1.3 ONLY — a prebuilt context via uvicorn's
        # ssl_context_factory (uvicorn ≥ 0.54); the identity files are the
        # owner-only ones on disk (§17.6).
        tls_dir = data_dir / "tls"
        cert_file = str(tls_dir / "cert.pem")
        key_file = str(tls_dir / "key.pem")
        public_config = uvicorn.Config(
            app,
            host=public_host,
            port=settings.listen.port,
            log_level="warning",
            access_log=False,
            ssl_certfile=cert_file,
            ssl_keyfile=key_file,
            ssl_context_factory=lambda _cfg, _default: _tls13_server_context(cert_file, key_file),
        )

    admin_config = uvicorn.Config(
        admin_app,
        host="127.0.0.1",
        port=settings.listen.admin_port,
        log_level="warning",
        access_log=False,
    )

    async def serve() -> None:
        public_server = uvicorn.Server(public_config)
        admin_server = uvicorn.Server(admin_config)
        public_server.install_signal_handlers = lambda: None  # type: ignore[method-assign]
        admin_server.install_signal_handlers = lambda: None  # type: ignore[method-assign]

        loop = asyncio.get_running_loop()
        stop = asyncio.Event()

        def _signal(_sig: int, _frame: object) -> None:
            public_server.should_exit = True
            admin_server.should_exit = True
            stop.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _signal, sig, None)
            except NotImplementedError:  # pragma: no cover - Windows
                signal.signal(sig, _signal)

        await asyncio.gather(public_server.serve(), admin_server.serve())

    asyncio.run(serve())
    return 0


def _make_tls_rotate(settings: object):
    """§17.5 Rotate hook for `POST /admin/tls/rotate` — explicit only."""

    def rotate() -> str:
        from pathlib import Path

        from localmesh_agent.security.tls import rotate_identity

        data_dir = Path(settings.ensure_data_dir())
        identity = rotate_identity(data_dir / "tls")
        return identity.spki_sha256

    return rotate


def _pair(args: argparse.Namespace) -> int:
    settings = load_settings(args.config)
    if args.approve or args.deny:
        action = "approve" if args.approve else "deny"
        status, payload = _admin_request(settings, "POST", f"/admin/pair/{action}")
        if status != 200:
            _print_envelope_error(status, payload)
            return 1
        print(f"{action}: {json.dumps(payload)}")
        return 0

    status, payload = _admin_request(settings, "POST", "/admin/pair/open")
    if status != 200:
        _print_envelope_error(status, payload)
        return 1
    print("Pairing Mode is OPEN (§15.4). Scan this QR with the LocalMesh App:")
    print(str(payload.get("qr")))
    print(
        f"pair_id {payload.get('pair_id')} — expires in {payload.get('expires_in')}s. "
        "The QR contains the pairing secret: never log or share it (§17.4/§17.6)."
    )
    if args.no_wait:
        return 0

    try:
        while True:
            time.sleep(2)
            _status, state = _admin_request(settings, "GET", "/admin/pair/pending")
            session_state = str(state.get("state"))
            if session_state == "claimed":
                print(
                    f"Device wants to pair: {state.get('device_name')} "
                    f"({state.get('platform')}) — SAS {state.get('sas')}. "
                    "Compare the code with the phone, then approve."
                )
                answer = input("Approve this device? [y/N] ").strip().lower()
                if answer == "y":
                    _approve_status, approved = _admin_request(
                        settings, "POST", "/admin/pair/approve"
                    )
                    print(f"approved: {json.dumps(approved)}")
                else:
                    _deny_status, denied = _admin_request(settings, "POST", "/admin/pair/deny")
                    print(f"denied: {json.dumps(denied)}")
                return 0
            if session_state == "approved":
                print("Device approved.")
                return 0
            if session_state in ("denied", "expired", "closed"):
                print(f"Pairing session {session_state}.")
                return 0
    except KeyboardInterrupt:
        print("\nPairing session left to expire (TTL).")
        return 0


def _devices(args: argparse.Namespace) -> int:
    settings = load_settings(args.config)
    status, payload = _admin_request(settings, "GET", "/admin/devices")
    if status != 200:
        _print_envelope_error(status, payload)
        return 1
    devices = payload.get("devices") or []
    if not devices:
        print("No devices paired yet.")
        return 0
    for device in devices:
        assert isinstance(device, dict)
        revoked = " REVOKED" if device.get("revoked_at") is not None else ""
        last_seen = device.get("last_seen_at") or "never"
        print(
            f"{device.get('device_id')}  {device.get('name')} ({device.get('platform')}) "
            f"scopes={device.get('scopes')} last_seen={last_seen}{revoked}"
        )
    return 0


def _revoke(args: argparse.Namespace) -> int:
    settings = load_settings(args.config)
    status, payload = _admin_request(settings, "POST", f"/admin/devices/{args.device_id}/revoke")
    if status != 200:
        _print_envelope_error(status, payload)
        return 1
    print(
        f"revoked {payload.get('device_id')} "
        f"(active requests cancelled: {payload.get('cancelled_requests')}; §15.6)"
    )
    return 0


def _doctor(args: argparse.Namespace) -> int:
    """§18.4 ordered checks (WP-13, FR-CONN-06); `--rotate-tls` is the §17.5
    explicit rotation the spec wires into this same command."""
    if args.rotate_tls:
        return _rotate_tls(args)

    from localmesh_agent.doctor import render_text, run_doctor, worst_level

    settings: object | None = None
    config_error: str | None = None
    try:
        settings = load_settings(args.config)
    except Exception as error:  # noqa: BLE001 - any config failure is check 1 (§18.4)
        config_error = f"{type(error).__name__}: {error}"

    findings = run_doctor(settings, config_error=config_error)  # type: ignore[arg-type]
    if args.as_json:
        import json as _json

        print(_json.dumps([f.to_dict() for f in findings], indent=2))
    else:
        header = "LocalMesh Agent doctor — LM-ARCH-001 §18.4 connection ladder"
        print(render_text(findings, header=header))
    worst = worst_level(findings)
    return {"ok": 0, "info": 0, "warn": 1, "error": 2}[worst]  # [DESIGN] exit codes


def _rotate_tls(args: argparse.Namespace) -> int:
    """§17.5 Rotate (explicit only): new key ⇒ new pin ⇒ every paired Phone
    shows PIN_MISMATCH and must re-pair. Suggests revoking all devices
    (§17.5 'Offer to revoke all devices at the same time')."""
    from localmesh_agent.security.tls import TlsIdentityError, load_identity, rotate_identity

    settings = load_settings(args.config)
    tls_dir = settings.ensure_data_dir() / "tls"
    try:
        old_prefix = load_identity(tls_dir).pin_prefix
    except TlsIdentityError:
        old_prefix = "(unusable or missing)"
    identity = rotate_identity(tls_dir)
    print(f"TLS identity rotated (§17.5). Pin prefix {old_prefix} → {identity.pin_prefix}.")
    print("Every paired Phone will show PIN_MISMATCH and must re-pair (§17.5).")
    print("Suggested same-time cleanup (§17.5): list and revoke devices —")
    print("  localmesh-agent devices        # while the Agent is running")
    print("  localmesh-agent revoke <id>    # per device")
    print("If the Agent is running, restart it to serve the new identity.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            return _run(args)
        if args.command == "pair":
            return _pair(args)
        if args.command == "devices":
            return _devices(args)
        if args.command == "revoke":
            return _revoke(args)
        if args.command == "doctor":
            return _doctor(args)
    except AdminUnreachable as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    parser.print_help()
    return 0
