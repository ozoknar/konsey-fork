"""S6 — the CLI surface for self-continuation: `enable automation`, the scheduler-wiring
fix in `uninstall --automation` (Codex finding), doctor observability, the `watchdog`
command + `dispatch watchdog` subcommand.

All tests use the default NullScheduler (scheduler="null"), so NOTHING touches the real
OS (no launch agent / timer / crontab is created). Evidence > consensus: real cmd_* calls
writing/reading a real temp profile.
"""
from __future__ import annotations

import argparse

from council import dispatch
from council.cli import cmd_doctor, cmd_enable, cmd_uninstall, cmd_watchdog


def _profile(tmp_path, monkeypatch, *, scheduler="null", bridge=False):
    home = tmp_path
    body = f'owner = "op"\nlocale = "en"\nscheduler = "{scheduler}"\n'
    if bridge:
        body += f'bridge_dir = "{home / "data" / "bridge"}"\n'
    # one (disabled) agent so doctor reports advisory mode, not a roster_none failure.
    body += '\n[[agents]]\nname = "claude"\ncli = "claude"\nrole = "lead"\nenabled = false\n'
    (home / "council.local.toml").write_text(body, encoding="utf-8")
    monkeypatch.setenv("KONSEY_HOME", str(home))
    monkeypatch.setenv("KONSEY_DATA_HOME", str(home / "data"))
    for v in ("COUNCIL_HOME", "COUNCIL_CONFIG", "KONSEY_CONFIG",
              "LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE", "KONSEY_LOCALE"):
        monkeypatch.delenv(v, raising=False)
    return home / "council.local.toml"


# --------------------------------------------------------------------------- #
# enable automation — arms the dispatch bridge (default-OFF → opt-in)          #
# --------------------------------------------------------------------------- #

def test_enable_automation_writes_bridge_dir(tmp_path, monkeypatch, capsys):
    prof = _profile(tmp_path, monkeypatch, scheduler="null")
    monkeypatch.setattr("council.cli._confirm", lambda *a, **k: True)
    rc = cmd_enable(argparse.Namespace(what="automation"))
    assert rc == 0
    assert "bridge_dir = " in prof.read_text(encoding="utf-8")   # dispatch + watchdog no longer inert
    # NullScheduler installs nothing, reported honestly (names the bridge it set) — not a crash.
    assert "bridge" in capsys.readouterr().out.lower()


def test_enable_automation_declined_changes_nothing(tmp_path, monkeypatch, capsys):
    prof = _profile(tmp_path, monkeypatch, scheduler="null")
    monkeypatch.setattr("council.cli._confirm", lambda *a, **k: False)
    rc = cmd_enable(argparse.Namespace(what="automation"))
    assert rc == 0
    assert "bridge_dir" not in prof.read_text(encoding="utf-8")   # declined → untouched


# --------------------------------------------------------------------------- #
# uninstall --automation — the Codex reversibility fix (real backend, no crash) #
# --------------------------------------------------------------------------- #

def test_uninstall_automation_resolves_real_backend_no_crash(tmp_path, monkeypatch, capsys):
    _profile(tmp_path, monkeypatch, scheduler="null")
    # NullScheduler.is_installed() is False → a clean "no-op" (not a crash, not a false claim).
    rc = cmd_uninstall(argparse.Namespace(automation=True, all=False, keep_data=False))
    out = capsys.readouterr().out
    assert rc == 0
    assert "scheduler" in out.lower()


# --------------------------------------------------------------------------- #
# doctor observability — you can SEE whether automation is armed               #
# --------------------------------------------------------------------------- #

def test_doctor_reports_automation_state(tmp_path, monkeypatch, capsys):
    _profile(tmp_path, monkeypatch, scheduler="null", bridge=False)
    rc = cmd_doctor(argparse.Namespace(fix=False, json=False, force=False))
    out = capsys.readouterr().out
    assert rc == 0
    assert "automation:" in out
    assert "scheduler=null" in out
    assert "off" in out          # bridge off (not armed)


# --------------------------------------------------------------------------- #
# watchdog command + dispatch subcommand                                       #
# --------------------------------------------------------------------------- #

def test_watchdog_command_runs_and_reports(tmp_path, monkeypatch, capsys):
    _profile(tmp_path, monkeypatch)
    rc = cmd_watchdog(argparse.Namespace())
    out = capsys.readouterr().out
    assert rc == 0
    assert "watchdog:" in out and "scanned=" in out


def test_dispatch_main_watchdog_subcommand(tmp_path, monkeypatch, capsys):
    _profile(tmp_path, monkeypatch)
    dispatch.main(["watchdog"])
    assert "scanned=" in capsys.readouterr().out
