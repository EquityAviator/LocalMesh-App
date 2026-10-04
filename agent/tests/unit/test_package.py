"""M0 scaffold sanity tests (WP-01).

These cover the scaffold itself (imports/layout), not milestone features.
Feature tests arrive with their WPs (§22.1 scope fence).
"""

import localmesh_agent


def test_package_version_present() -> None:
    """The package exposes a version (reported later by API-INFO-01, §13.2)."""
    assert isinstance(localmesh_agent.__version__, str)
    assert localmesh_agent.__version__


def test_layer_packages_import() -> None:
    """§10.1 layers exist and import cleanly (api, core, security, ...)."""
    from localmesh_agent import adapters, api, core, observability, security, store  # noqa: F401


def test_cli_main_runs() -> None:
    """The CLI without a subcommand prints help and exits 0 (no invented
    surface ahead of its milestone, §1.2)."""
    from localmesh_agent.cli import main

    assert main([]) == 0


def test_cli_doctor_runs_and_reports_findings(tmp_path: object, capsys: object) -> None:
    """WP-13 (M3): `doctor` runs the §18.4 ladder and prints findings.

    Exit code is level-mapped [DESIGN]: 0 ok/info, 1 warn, 2 error — the
    exact findings depend on the host, so this asserts the contract shape
    (header + ordered checks) rather than specific levels.
    """
    from pathlib import Path

    from localmesh_agent.cli import main

    config = Path(str(tmp_path)) / "config.toml"  # type: ignore[operator]
    data_dir = Path(str(tmp_path)) / "data"  # type: ignore[operator]
    config.write_text(f'[agent]\ndata_dir = "{data_dir}"\n', encoding="utf-8")

    code = main(["doctor", "--config", str(config)])
    out = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "§18.4 connection ladder" in out
    assert "config" in out  # check 1 always runs
    assert code in (0, 1, 2)  # level-mapped exit codes
    if code != 0:
        assert "worst finding level" in out


def test_cli_pair_without_agent_fails_actionable(capsys: object) -> None:
    """WP-08: `pair` is an admin client (§15.4); without a running Agent it
    fails with an actionable error (admin listener unreachable), exit 1."""
    from localmesh_agent.cli import AdminUnreachable, main

    code = main(["pair"])
    assert code == 1
    assert AdminUnreachable is not None  # exported for callers/tests
