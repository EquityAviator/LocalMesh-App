"""Contract test — Tailscale probe vs recorded `tailscale status --json`
output (§22.3 WP-14 test column: "Probe parse tests with recorded `tailscale`
output"; §10.3 rule 1 spirit).

NO RECORDING EXISTS YET: the sandbox has no `tailscale` binary to capture
(docs/fixtures/CAPTURE.md §3 holds the capture command; owner action —
QUESTION-104). This runs as an *announced skip* until fixtures land under
`tests/contract/fixtures/tailscale/<version>/`, then becomes a hard gate:
each recording is fed through `parse_tailscale_status_json` and the
§13.2/§16.1 reporting shapes are asserted. A real install whose JSON differs
from the §6.3 [ASSUMPTION] shape fails here loudly (§22.3 "Stop-and-ask if:
Tailscale JSON differs").
"""

import json
from pathlib import Path
from typing import Any

import pytest

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "tailscale"


def _recorded() -> list[Path]:
    return sorted(FIXTURE_ROOT.rglob("*.json")) if FIXTURE_ROOT.is_dir() else []


@pytest.mark.skipif(
    not _recorded(),
    reason=(
        "No recorded `tailscale status --json` fixtures — run "
        "docs/fixtures/CAPTURE.md §3 on a PC with Tailscale installed and "
        "commit under agent/tests/contract/fixtures/tailscale/<version>/ "
        "(§22.3 WP-14; verifies the §6.3 [ASSUMPTION] field names — "
        "QUESTION-104). Fakes do NOT substitute."
    ),
)
def test_tailscale_parse_vs_recorded_output() -> None:
    from localmesh_agent.adapters.tailscale import parse_tailscale_status_json

    for path in _recorded():
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(payload, dict), f"{path}: expected a JSON object capture"
        info = parse_tailscale_status_json(path.read_text(encoding="utf-8"))
        # The parser must locate the documented fields in every real capture
        # (unknown state would mean the §6.3 ASSUMPTION broke — stop and ask).
        assert info.state != "unknown", (
            f"{path}: BackendState not found — tailscale JSON differs from "
            "the §6.3 assumption (QUESTION-104)"
        )
        for ip in info.ips:
            assert ip.startswith("100."), f"{path}: non-CGNAT IP leaked: {ip}"
