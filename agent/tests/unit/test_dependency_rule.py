"""§10.1 dependency rule enforced by an import-linter *test*.

The contracts live in `agent/.importlinter`. CI runs the `lint-imports` CLI as
its own §21.4 stage; this test additionally shells out to it so the dependency
rule is covered inside pytest too ("enforced by an import-linter test", §10.1).
"""

import shutil
import subprocess
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[2]


def test_import_linter_contracts_hold() -> None:
    binary = shutil.which("lint-imports")
    assert binary is not None, "lint-imports not found; install the agent[dev] extras"
    result = subprocess.run(
        [binary, "--config", str(AGENT_DIR / ".importlinter")],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert result.returncode == 0, (
        f"import-linter contracts failed (§10.1 dependency rule):\n{result.stdout}\n{result.stderr}"
    )
