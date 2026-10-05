"""M9 packaging — Windows service + firewall rule + systemd unit templates.

LM-ARCH-001 §21.6/§18.6/FR-AGT-05. These are DEV-DELIVERED TEMPLATES: the
sandbox cannot run Windows or systemd; the release gate is that the scripts
parse, the firewall rule is scoped to the Private profile on TCP 8443 only
(FR-AGT-05), and the TLS/private-key files stay out of any world-readable
path (§17.6). Real verification is an owner action on Windows/a systemd host.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]  # monorepo root
PACKAGING = REPO_ROOT / "packaging"


def test_windows_firewall_rule_is_private_profile_only() -> None:
    """FR-AGT-05: "Windows installer adds firewall rule for the Agent port
    scoped to Private profiles" — asserted at the script-content level here;
    a real Windows run is the owner-side release check."""
    script = PACKAGING / "windows" / "install-agent.ps1"
    assert script.is_file(), "windows installer missing"
    text = script.read_text(encoding="utf-8")
    assert "New-NetFirewallRule" in text
    assert "-Profile Private" in text
    assert "8443" in text, "agent port must be pinned in the rule"
    assert "Public" not in text.split("-Profile")[1].split("\n")[0], (
        "the rule must never open the Public profile (FR-AGT-05)"
    )
    assert "Domain" in text or "Private" in text


def test_windows_installer_does_not_disable_tls_or_auth() -> None:
    script = PACKAGING / "windows" / "install-agent.ps1"
    text = script.read_text(encoding="utf-8")
    # No EXECUTED line may enable dev mode; comments mentioning it are fine.
    executed = [
        line for line in text.splitlines() if line.strip() and not line.strip().startswith("#")
    ]
    assert not any("dev-insecure" in line.lower() for line in executed), (
        "release install must never invoke dev-insecure mode (§17.9)"
    )
    assert "LOCALMESH_DEV" not in text


def test_systemd_unit_hardens_the_service() -> None:
    unit = PACKAGING / "systemd" / "localmesh-agent.service"
    assert unit.is_file(), "systemd unit missing"
    text = unit.read_text(encoding="utf-8")
    for directive in (
        "NoNewPrivileges=true",
        "ProtectSystem=strict",
        "ProtectHome=true",
        "PrivateTmp=true",
    ):
        assert directive in text, f"missing hardening directive: {directive}"
    # The Agent must run as a non-root service account.
    assert "User=" in text and "root" not in text.split("User=")[1].split("\n")[0]


def test_data_dir_acl_note_present() -> None:
    """§17.6/§14.1: data dir owner-only; on Windows the installer completes
    the ACL hardening (config.py documents this platform gap)."""
    script = PACKAGING / "windows" / "install-agent.ps1"
    text = script.read_text(encoding="utf-8")
    assert "icacls" in text.lower(), "installer must restrict the data dir ACL"
