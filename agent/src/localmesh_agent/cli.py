"""Agent CLI: `run | doctor | pair | devices | revoke` (LM-ARCH-001 §10.1).

M1 scope (§22.1): `run` only, and only as the **dev-insecure loopback**
listener (§17.9) — the flag is opt-in and never a default (SEC-N6). Without
it, `run` refuses to start: the public TLS listener arrives with WP-07 (M2).
`pair`/`devices`/`revoke` arrive with WP-08 (M2); `doctor` with WP-13 (M3) —
they report their milestone instead of inventing behaviour (§1.2).
"""

from __future__ import annotations

import argparse
import sys

from localmesh_agent.config import load_settings

_DEV_FLAG = "--dev-insecure-loopback"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="localmesh-agent",
        description="LocalMesh AI Desktop Agent (LM-ARCH-001 §10.1)",
    )
    sub = parser.add_subparsers(dest="command")

    run_parser = sub.add_parser("run", help="start the Agent (see --dev-insecure-loopback)")
    run_parser.add_argument("--config", default=None, help="path to config.toml")
    run_parser.add_argument(
        _DEV_FLAG,
        dest="dev_insecure",
        action="store_true",
        help=(
            "M1 development mode: HTTP listener bound to 127.0.0.1 ONLY "
            "(§17.9). Off by default (SEC-N6); the TLS listener arrives with M2."
        ),
    )

    for name in ("doctor", "pair", "devices", "revoke"):
        sub.add_parser(name, help=f"delivered with its milestone (§22.1: {name})")
    return parser


def _run(args: argparse.Namespace) -> int:
    settings = load_settings(args.config)
    if not args.dev_insecure:
        print(
            "Refusing to start: the public TLS listener arrives with M2 (WP-07, "
            "LM-ARCH-001 §22.1). For development on loopback only, pass "
            f"{_DEV_FLAG} (§17.9; SEC-N6: never a default).",
            file=sys.stderr,
        )
        return 2
    if settings.listen.host not in ("127.0.0.1", "localhost", "::1"):
        # Dev mode binds loopback ONLY (§17.9: "never a routable interface").
        print(
            f"{_DEV_FLAG} binds 127.0.0.1 only; [listen].host "
            f"{settings.listen.host!r} is ignored in dev mode (§17.9).",
            file=sys.stderr,
        )
    import uvicorn

    from localmesh_agent.app import create_app

    app = create_app(settings, dev_insecure=True)
    print(
        f"localmesh-agent dev loopback on http://127.0.0.1:{settings.listen.port} "
        f"(admin listener + TLS arrive with M2; §22.1)"
    )
    uvicorn.run(
        app,
        host="127.0.0.1",  # §17.9: loopback only, never a routable interface
        port=settings.listen.port,
        log_level="warning",
        access_log=False,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "run":
        return _run(args)
    if args.command in ("pair", "devices", "revoke", "doctor"):
        milestone = {"doctor": "M3 (WP-13)"}.get(args.command, "M2 (WP-08)")
        print(
            f"'{args.command}' is delivered with {milestone} per LM-ARCH-001 "
            "§22.1/§22.2 — nothing is invented ahead of its milestone (§1.2)."
        )
        return 0
    parser.print_help()
    return 0
