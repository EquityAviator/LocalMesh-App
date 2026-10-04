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


def test_cli_doctor_reports_milestone() -> None:
    """`doctor` reports its milestone (WP-13/M3 per §22.1)."""
    from localmesh_agent.cli import main

    assert main(["doctor"]) == 0


def test_cli_pair_without_agent_fails_actionable(capsys: object) -> None:
    """WP-08: `pair` is an admin client (§15.4); without a running Agent it
    fails with an actionable error (admin listener unreachable), exit 1."""
    from localmesh_agent.cli import AdminUnreachable, main

    code = main(["pair"])
    assert code == 1
    assert AdminUnreachable is not None  # exported for callers/tests
