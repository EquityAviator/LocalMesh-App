"""SEC-N6 check (§17.9, §21.4) — dev-mode must be unreachable by default.

"CI MUST fail a release build if dev-mode code paths are reachable (§21.4)."
The Agent's dev surface is the CLI flag `--dev-insecure-loopback` (§17.9):
HTTP on 127.0.0.1 only, never a routable interface. This gate proves the
RELEASE default is fail-closed:

1. `localmesh-agent run` parsed with NO flags → dev_insecure is False.
2. Settings exposes NO dev-mode field/env default at all (the only path to
   dev mode is the explicit, opt-in CLI flag on the dev workstation).
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "agent" / "src"))

from localmesh_agent.cli import build_parser  # noqa: E402
from localmesh_agent.config import Settings  # noqa: E402


def main() -> int:
    args = build_parser().parse_args(["run"])
    if getattr(args, "dev_insecure", True):
        print("FAIL: `run` defaults dev_insecure=True — SEC-N6 violation.")
        return 1

    settings = Settings()
    dev_fields = [f for f in type(settings).model_fields if "dev" in f.lower()]
    if dev_fields:
        print(f"FAIL: Settings exposes dev-mode field(s): {dev_fields} — SEC-N6 violation.")
        return 1

    print("Dev-default check: OK (run → dev_insecure=False; no dev field on Settings)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
