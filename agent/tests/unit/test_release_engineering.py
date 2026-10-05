"""M9 release engineering — version sync + SEC-N6 dev default (§22.1, §21.6).

The release tooling lives in `scripts/release_gate.sh` / `release_build.sh`
(dev helpers, §21.1); the INVARIANTS a release depends on are pinned here so
they run on every CI pass, not only at tag time.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

SEMVER_RE = r"^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$"


def test_agent_version_is_semver() -> None:
    """NFR-COMP-02: AGENT_VERSION (GET /mesh/v1/info) must be valid SemVer."""
    from localmesh_agent.app import AGENT_VERSION

    assert re.match(SEMVER_RE, AGENT_VERSION), f"not SemVer: {AGENT_VERSION}"
    assert AGENT_VERSION == "1.0.0-rc.1", "M9 release candidate version drifted"


def test_pyproject_version_matches_agent_version_pep440() -> None:
    """The wheel metadata version and /info's AGENT_VERSION are two spellings
    of ONE release version: PEP 440 `1.0.0rc1` ↔ SemVer `1.0.0-rc.1`.
    A tag that builds a wheel whose metadata disagrees with /info would be
    unreproducible from artifacts."""
    import tomllib

    from localmesh_agent.app import AGENT_VERSION

    pyproject = tomllib.loads((REPO_ROOT / "agent" / "pyproject.toml").read_text())
    pep440 = pyproject["project"]["version"]
    m = re.fullmatch(r"(\d+\.\d+\.\d+)rc(\d+)", pep440)
    assert m is not None, f"pyproject version not PEP 440 rc: {pep440}"
    assert f"{m.group(1)}-rc.{m.group(2)}" == AGENT_VERSION, (
        f"wheel metadata {pep440!r} and /info {AGENT_VERSION!r} describe different releases"
    )


def test_release_scripts_exist_and_are_gate_complete() -> None:
    """RELEASE.md's 9 gates must all be wired into scripts/release_gate.sh,
    and the build script must produce checksums + artifact scan (§21.6)."""
    gate = (REPO_ROOT / "scripts" / "release_gate.sh").read_text()
    for needle in (
        "pytest_layer.sh agent/tests/unit",
        "pytest_layer.sh agent/tests/contract",
        "pytest_layer.sh tools/fake-backends/tests agent/tests/integration",
        "pytest_layer.sh agent/tests/security",
        "lint-imports",
        "check_openapi_drift.py",
        "scan_cleartext_manifest.py",
        "scan_content_columns.py",
        "scan_secrets.py",
        "pip-audit",
        "check_dev_default.py",
        "pentest-signoff.md",
    ):
        assert needle in gate, f"release gate missing: {needle}"
    build = (REPO_ROOT / "scripts" / "release_build.sh").read_text()
    for needle in ("SHA256SUMS", "scan_artifacts.py", "minisign"):
        assert needle in build, f"release build missing: {needle}"


def test_cli_dev_flag_defaults_off_sec_n6() -> None:
    """SEC-N6 (§17.9/§21.4): dev-mode must be unreachable by default. The CLI
    flag is the ONLY dev surface; the parsed default must be False, and the
    Settings model must expose no dev field at all (env cannot enable it)."""
    from localmesh_agent.cli import build_parser
    from localmesh_agent.config import Settings

    args = build_parser().parse_args(["run"])
    assert args.dev_insecure is False
    dev_fields = [f for f in type(Settings()).model_fields if "dev" in f.lower()]
    assert dev_fields == [], f"Settings exposes dev-mode fields: {dev_fields}"


def test_pentest_signoff_template_is_not_pre_signed() -> None:
    """The committed sign-off file is a TEMPLATE: it must not claim a release
    was pen-tested when only the sandbox exists (honesty rule, AGENTS.md)."""
    signoff = REPO_ROOT / "docs" / "security" / "pentest-signoff.md"
    text = signoff.read_text()
    assert "TEMPLATE" in text
    assert "<VERSION>" in text  # placeholder, not a real release id
