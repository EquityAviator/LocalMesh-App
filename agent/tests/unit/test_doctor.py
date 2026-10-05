"""WP-13 Doctor v1 tests — §18.4 ordered checks, golden outputs per CI.

Test note (§22.2 WP-13): "Findings keyed by CI-ID; no secrets/Content;
Golden-output tests per CI." Each CI mapping gets an explicit test with the
exact expected finding text; the no-secrets rule is asserted against the
full pin / admin token values.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from localmesh_agent.config import Settings
from localmesh_agent.doctor import (
    CHECK_ORDER,
    DoctorProbes,
    Finding,
    render_text,
    run_doctor,
    worst_level,
)
from localmesh_agent.security.tls import load_or_create_identity


def make_settings(tmp_path: Path, **kwargs: object) -> Settings:
    return Settings(agent={"data_dir": str(tmp_path / "data")}, **kwargs)  # type: ignore[arg-type]


def ok_probes(**overrides: object) -> DoctorProbes:
    """All-green probe set (agent NOT running; offline tailscale/mdns)."""
    base: dict[str, object] = {
        "port_probe": lambda host, port: "free",
        "backend_probe": lambda base_url, kind: ("up", None),
        "lan_ip": lambda: None,
        "lan_backend_probe": lambda ip, port, path: False,
        "mdns_addresses": lambda: ["192.168.1.10"],
        "mdns_browse": lambda: None,
        "firewall_probe": lambda port: "rule-present",
        "tailscale_probe": lambda: None,
        "wall_now": lambda: datetime(2026, 10, 4, 12, 0, 0, tzinfo=UTC),
    }
    base.update(overrides)
    return DoctorProbes(**base)  # type: ignore[arg-type]


# -- §18.4 check 1: config -------------------------------------------------------


def test_config_error_short_circuits_the_ladder() -> None:
    findings = run_doctor(None, config_error="ValueError: bad [backends] kind")
    assert [f.check for f in findings] == ["config"]
    assert findings[0].level == "error"
    assert "bad [backends] kind" in findings[0].summary
    assert "Appendix E" in findings[0].fix


# -- §18.4 ladder order -----------------------------------------------------------


def test_ladder_order_follows_18_4(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    load_or_create_identity(settings.ensure_data_dir() / "tls")
    findings = run_doctor(settings, ok_probes())
    # Multiple findings may share a check (e.g. two Backends); the LADDER
    # order is the order of first occurrence.
    seen = list(dict.fromkeys(f.check for f in findings))
    assert seen == list(CHECK_ORDER)
    assert findings[0].check == "config" and findings[0].level == "ok"
    assert findings[-1].check == "clock"


# -- §18.4 check 2: data dir perms (§14.1) ----------------------------------------


def test_data_dir_too_open_warns_with_chmod_fix(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    data_dir = settings.ensure_data_dir()
    data_dir.chmod(0o755)
    findings = run_doctor(settings, ok_probes())
    data_dir_findings = [f for f in findings if f.check == "data_dir"]
    assert data_dir_findings[0].level == "warn"
    assert "group/other" in data_dir_findings[0].summary
    assert "owner-only" in data_dir_findings[0].detail
    assert "chmod 700" in data_dir_findings[0].fix


def test_data_dir_owner_only_is_ok(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    settings.ensure_data_dir().chmod(0o700)
    findings = run_doctor(settings, ok_probes())
    data_dir_findings = [f for f in findings if f.check == "data_dir"]
    assert data_dir_findings[0].level == "ok"


# -- §18.4 check 3: TLS identity (CI-12) -------------------------------------------


def test_tls_missing_is_error_with_rotate_fix(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    settings.ensure_data_dir()
    findings = run_doctor(settings, ok_probes())
    tls_findings = [f for f in findings if f.check == "tls"]
    assert tls_findings[0].level == "error"
    assert tls_findings[0].ci_ids == ("CI-12",)
    assert "--rotate-tls" in tls_findings[0].fix


def test_tls_ok_prints_prefix_only_never_full_pin(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    tls_dir = settings.ensure_data_dir() / "tls"
    identity = load_or_create_identity(tls_dir)
    findings = run_doctor(settings, ok_probes())
    tls_findings = [f for f in findings if f.check == "tls"]
    assert tls_findings[0].level == "ok"
    assert identity.pin_prefix in tls_findings[0].summary
    # No-secrets rule (§10.6/§17.6): the FULL pin never appears anywhere.
    rendered = render_text(findings)
    assert identity.spki_sha256 not in rendered
    assert identity.spki_sha256.startswith(identity.pin_prefix)
    assert len(identity.pin_prefix) == 12


# -- §18.4 check 4: port (CI-04) ----------------------------------------------------


def test_ci04_port_occupied_by_other_process(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    findings = run_doctor(settings, ok_probes(port_probe=lambda host, port: "occupied"))
    port_findings = [f for f in findings if f.check == "port"]
    assert port_findings[0].level == "error"
    assert port_findings[0].ci_ids == ("CI-04",)
    assert "listen.port" in port_findings[0].fix


def test_port_listening_is_ok(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    findings = run_doctor(settings, ok_probes(port_probe=lambda host, port: "listening"))
    port_findings = [f for f in findings if f.check == "port"]
    assert port_findings[0].level == "ok"
    assert "/mesh/v1/info" in port_findings[0].summary


# -- §18.4 check 5: backends on loopback (CI-05) -------------------------------------


def test_ci05_lmstudio_down_golden(tmp_path: Path) -> None:
    settings = make_settings(
        tmp_path,
        backends=[{"id": "lmstudio", "kind": "lmstudio", "base_url": "http://127.0.0.1:1234"}],
    )
    findings = run_doctor(settings, ok_probes(backend_probe=lambda base_url, kind: ("down", None)))
    backend_findings = [f for f in findings if f.check == "backends"]
    assert backend_findings[0].level == "warn"
    assert backend_findings[0].ci_ids == ("CI-05",)
    assert backend_findings[0].summary == (
        "Backend 'lmstudio' (lmstudio) not reachable on http://127.0.0.1:1234 (CI-05)."
    )
    assert backend_findings[0].fix == "Start LM Studio and its local server (§18.2 CI-05)."


def test_ci05_ollama_down_golden_fix(tmp_path: Path) -> None:
    settings = make_settings(
        tmp_path,
        backends=[{"id": "ollama", "kind": "ollama", "base_url": "http://127.0.0.1:11434"}],
    )
    findings = run_doctor(settings, ok_probes(backend_probe=lambda base_url, kind: ("down", None)))
    backend_findings = [f for f in findings if f.check == "backends"]
    assert backend_findings[0].fix == "Start Ollama (`ollama serve`) (§18.2 CI-05)."


# -- §18.4 check 6: backend bind-address warnings (CI-06/CI-07) -----------------------


def test_ci06_lmstudio_reachable_on_lan(tmp_path: Path) -> None:
    settings = make_settings(
        tmp_path,
        backends=[{"id": "lmstudio", "kind": "lmstudio", "base_url": "http://127.0.0.1:1234"}],
    )
    probes = ok_probes(
        lan_ip=lambda: "192.168.1.10",
        lan_backend_probe=lambda ip, port, path: path == "/v1/models" and port == 1234,
    )
    findings = run_doctor(settings, probes)
    bind_findings = [f for f in findings if f.check == "backend_bind"]
    assert bind_findings[0].level == "warn"
    assert bind_findings[0].ci_ids == ("CI-06",)
    assert "192.168.1.10:1234" in bind_findings[0].summary
    assert "not needed (SEC-N2)" in bind_findings[0].summary


def test_ci07_ollama_reachable_on_lan_without_auth(tmp_path: Path) -> None:
    settings = make_settings(
        tmp_path,
        backends=[{"id": "ollama", "kind": "ollama", "base_url": "http://127.0.0.1:11434"}],
    )
    probes = ok_probes(
        lan_ip=lambda: "192.168.1.10",
        lan_backend_probe=lambda ip, port, path: path == "/api/tags" and port == 11434,
    )
    findings = run_doctor(settings, probes)
    bind_findings = [f for f in findings if f.check == "backend_bind"]
    assert bind_findings[0].ci_ids == ("CI-07",)
    assert "without auth" in bind_findings[0].summary
    assert "Rebind Ollama to 127.0.0.1" in bind_findings[0].fix


def test_backend_bind_clean_when_lan_probe_fails(tmp_path: Path) -> None:
    settings = make_settings(
        tmp_path,
        backends=[{"id": "lmstudio", "kind": "lmstudio", "base_url": "http://127.0.0.1:1234"}],
    )
    probes = ok_probes(lan_ip=lambda: "192.168.1.10")
    findings = run_doctor(settings, probes)
    bind_findings = [f for f in findings if f.check == "backend_bind"]
    assert bind_findings[0].level == "ok"


# -- §18.4 check 7: mDNS (CI-24 / CI-01) ----------------------------------------------


def test_ci24_no_advertisable_addresses(tmp_path: Path) -> None:
    findings = run_doctor(make_settings(tmp_path), ok_probes(mdns_addresses=lambda: []))
    mdns_findings = [f for f in findings if f.check == "mdns"]
    assert mdns_findings[0].level == "warn"
    assert "CI-24" in mdns_findings[0].ci_ids
    assert "[mdns] interfaces" in mdns_findings[0].fix


def test_mdns_disabled_by_config_is_info(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, mdns={"enabled": False})
    findings = run_doctor(settings, ok_probes())
    mdns_findings = [f for f in findings if f.check == "mdns"]
    assert mdns_findings[0].level == "info"


def test_mdns_browse_unavailable_is_info_never_error(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    findings = run_doctor(
        settings,
        ok_probes(port_probe=lambda host, port: "listening", mdns_browse=lambda: None),
    )
    mdns_findings = [f for f in findings if f.check == "mdns"]
    assert mdns_findings[0].level == "info"
    assert "T-21" in mdns_findings[0].summary


def test_ci01_running_but_advertisement_not_visible(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    findings = run_doctor(
        settings,
        ok_probes(port_probe=lambda host, port: "listening", mdns_browse=lambda: 0),
    )
    mdns_findings = [f for f in findings if f.check == "mdns"]
    assert mdns_findings[0].level == "warn"
    assert mdns_findings[0].ci_ids == ("CI-01",)


def test_mdns_visible_while_running_is_ok(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    findings = run_doctor(
        settings,
        ok_probes(port_probe=lambda host, port: "listening", mdns_browse=lambda: 1),
    )
    mdns_findings = [f for f in findings if f.check == "mdns"]
    assert mdns_findings[0].level == "ok"


# -- §18.4 check 8: firewall (CI-03) ---------------------------------------------------


def test_ci03_firewall_rule_missing(tmp_path: Path) -> None:
    findings = run_doctor(make_settings(tmp_path), ok_probes(firewall_probe=lambda port: "no-rule"))
    fw_findings = [f for f in findings if f.check == "firewall"]
    assert fw_findings[0].level == "warn"
    assert fw_findings[0].ci_ids == ("CI-03",)
    assert "Private profile" in fw_findings[0].fix


def test_firewall_unknown_is_manual_info(tmp_path: Path) -> None:
    findings = run_doctor(make_settings(tmp_path), ok_probes(firewall_probe=lambda port: "unknown"))
    fw_findings = [f for f in findings if f.check == "firewall"]
    assert fw_findings[0].level == "info"
    assert "manual step" in fw_findings[0].summary


# -- §18.4 check 9: tailscale (CI-15) ---------------------------------------------------


def test_tailscale_absent_is_lan_only_info(tmp_path: Path) -> None:
    findings = run_doctor(make_settings(tmp_path), ok_probes(tailscale_probe=lambda: None))
    ts_findings = [f for f in findings if f.check == "tailscale"]
    assert ts_findings[0].level == "info"
    assert "LAN-only" in ts_findings[0].summary


def test_ci15_tailscale_stopped_warns(tmp_path: Path) -> None:
    from localmesh_agent.adapters.ports import TailnetInfo

    probes = ok_probes(tailscale_probe=lambda: TailnetInfo(state="Stopped"))
    findings = run_doctor(make_settings(tmp_path), probes)
    ts_findings = [f for f in findings if f.check == "tailscale"]
    assert ts_findings[0].level == "warn"
    assert ts_findings[0].ci_ids == ("CI-15",)


def test_tailscale_running_is_ok_with_dns_name(tmp_path: Path) -> None:
    from localmesh_agent.adapters.ports import TailnetInfo

    probes = ok_probes(
        tailscale_probe=lambda: TailnetInfo(state="Running", dns_name="pc.tailnet.example.")
    )
    findings = run_doctor(make_settings(tmp_path), probes)
    ts_findings = [f for f in findings if f.check == "tailscale"]
    assert ts_findings[0].level == "ok"
    assert "pc.tailnet.example" in ts_findings[0].summary  # trailing dot stripped


# -- WP-14: the default (real) probe delegates to the shared adapter parser --


def test_default_tailscale_probe_uses_shared_parser(monkeypatch: pytest.MonkeyPatch) -> None:
    """§18.4 + §22.3 WP-14: doctor and the serving Agent must interpret a real
    install identically — the doctor's subprocess wrapper feeds the SAME
    `parse_tailscale_status_json` used by `TailscaleCliProbe`."""
    import subprocess

    from localmesh_agent.adapters.ports import TailnetInfo
    from localmesh_agent.doctor import _tailscale_probe_default

    monkeypatch.setattr(
        "shutil.which", lambda name: "/usr/bin/tailscale" if name == "tailscale" else None
    )
    payload = (
        '{"BackendState": "Running", "Self": {"DNSName": "pc.tail.ts.net.", '
        '"TailscaleIPs": ["100.64.9.9", "10.1.2.3"]}}'
    )

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(["tailscale", "status", "--json"], 0, payload, "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    info = _tailscale_probe_default()
    assert info == TailnetInfo(state="Running", dns_name="pc.tail.ts.net", ips=("100.64.9.9",))


def test_default_tailscale_probe_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    from localmesh_agent.doctor import _tailscale_probe_default

    monkeypatch.setattr("shutil.which", lambda name: None)
    assert _tailscale_probe_default() is None


# -- §18.4 check 10: clock (CI-23) -------------------------------------------------------


def test_clock_implausible_warns_ci23(tmp_path: Path) -> None:
    probes = ok_probes(wall_now=lambda: datetime(1999, 1, 1, tzinfo=UTC))
    findings = run_doctor(make_settings(tmp_path), probes)
    clock_findings = [f for f in findings if f.check == "clock"]
    assert clock_findings[0].level == "warn"
    assert clock_findings[0].ci_ids == ("CI-23",)
    assert "NTP" in clock_findings[0].fix


def test_clock_ok_mentions_monotonic_ci23_immunity(tmp_path: Path) -> None:
    findings = run_doctor(make_settings(tmp_path), ok_probes())
    clock_findings = [f for f in findings if f.check == "clock"]
    assert clock_findings[0].level == "ok"
    assert "monotonic" in clock_findings[0].summary


# -- rendering / exit codes / no-secrets --------------------------------------------------


def test_render_golden_output() -> None:
    findings = [
        Finding(
            check="tls",
            level="error",
            summary="TLS identity unusable: boom",
            ci_ids=("CI-12",),
            fix="Rotate: `localmesh-agent doctor --rotate-tls` (§17.5).",
        ),
        Finding(check="clock", level="ok", summary="Clock sanity ok."),
    ]
    expected = (
        "LocalMesh Agent doctor — LM-ARCH-001 §18.4 connection ladder"
        "\n"
        "\n"
        "[error] tls           TLS identity unusable: boom (CI-12)"
        "\n"
        "                      fix: Rotate: `localmesh-agent doctor --rotate-tls` (§17.5)."
        "\n"
        "[ok]    clock         Clock sanity ok."
        "\n"
        "\n"
        "worst finding level: error (2 finding(s))"
    )
    assert render_text(findings) == expected


def test_worst_level_drives_exit_codes(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    load_or_create_identity(settings.ensure_data_dir() / "tls")
    # The green path still carries info findings (e.g. tailscale absent) —
    # info maps to exit 0 [DESIGN]; only warn/error fail the command.
    assert worst_level(run_doctor(settings, ok_probes())) == "info"
    occupied = run_doctor(
        make_settings(tmp_path / "second"),
        ok_probes(port_probe=lambda host, port: "occupied"),
    )
    assert worst_level(occupied) == "error"


def test_no_secrets_in_full_run_output(tmp_path: Path) -> None:
    """§17.6/§17.10: the admin token and the full pin never reach the output."""
    settings = make_settings(tmp_path)
    data_dir = settings.ensure_data_dir()
    identity = load_or_create_identity(data_dir / "tls")
    (data_dir / "admin.token").write_text("super-secret-admin-token\n", encoding="utf-8")
    findings = run_doctor(settings, ok_probes())
    rendered = render_text(findings)
    assert "super-secret-admin-token" not in rendered
    assert identity.spki_sha256 not in rendered
