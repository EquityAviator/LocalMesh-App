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


def test_cli_milestone_subcommands_report() -> None:
    """`pair`/`devices`/`revoke`/`doctor` report their milestone (§22.1)."""
    from localmesh_agent.cli import main

    assert main(["doctor"]) == 0
    assert main(["pair"]) == 0
