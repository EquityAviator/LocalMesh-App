"""§10.1 dependency rule enforced by an import-linter *test*.

The contracts live in `agent/.importlinter`. CI runs the `lint-imports` CLI as
its own §21.4 stage; this test additionally shells out to it so the dependency
rule is covered inside pytest too ("enforced by an import-linter test", §10.1).
"""

import os
import shutil
import subprocess
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[2]


def test_import_linter_contracts_hold() -> None:
    binary = shutil.which("lint-imports")
    if binary is None:
        # Sandbox layout: the tool lives in the agent venv, not on PATH.
        venv_binary = AGENT_DIR / ".venv" / "bin" / "lint-imports"
        binary = str(venv_binary) if venv_binary.is_file() else None
    assert binary is not None, "lint-imports not found; install the agent[dev] extras"
    # Run from the agent dir with src on PYTHONPATH so the rule also holds when
    # the package is used from source (no editable install), e.g. in sandbox CI.
    env = {**os.environ, "PYTHONPATH": str(AGENT_DIR / "src")}
    result = subprocess.run(
        [binary, "--config", str(AGENT_DIR / ".importlinter")],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
        cwd=AGENT_DIR,
        env=env,
    )
    assert result.returncode == 0, (
        f"import-linter contracts failed (§10.1 dependency rule):\n{result.stdout}\n{result.stderr}"
    )
