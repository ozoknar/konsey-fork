"""The bounded, opt-in repair LOOP — proven WITHOUT a live agent (injected runner/collect).

Locks the safety contract: default-OFF, no-op on healthy, confirm-gated, producer≠verifier
(only a fresh real doctor rc==0 ends it), attempt-cap / no-progress kill, destructive
hard-floor refusal, outside-repo refusal, and append-only audit per attempt.
"""
from __future__ import annotations

import argparse

from council import repair
from council.config import Config, RosterEntry


def _cfg(tmp_path):
    return Config(council_home=tmp_path, data_home=tmp_path / "d",
                  agents=[RosterEntry("claude", "claude", "lead", enabled=True)])


def _report(ncrit: int) -> dict:
    checks = [{"ok": False, "severity": "critical", "message": f"crit{i}", "id": f"c{i}"} for i in range(ncrit)]
    return {"schema": "council.doctor/v1", "ok": ncrit == 0, "rc": 1 if ncrit else 0,
            "critical": ncrit > 0, "advisory": False, "checks": checks}


class _Collect:
    """Returns each report in sequence (last one sticks); counts calls."""
    def __init__(self, *reports):
        self.reports = list(reports)
        self.calls = 0

    def __call__(self, cfg):
        r = self.reports[min(self.calls, len(self.reports) - 1)]
        self.calls += 1
        return r


def _boom_runner(*a, **k):
    raise AssertionError("runner must NOT be called")


def _ok_runner(argv, env, *, cwd, timeout):
    return repair.RepairRunResult("I fixed everything!", 0, True)   # self-report — must be ignored


def _args(force=False):
    return argparse.Namespace(fix=True, force=force, json=False)


def _common(monkeypatch):
    # a provider is always 'available' (no host PATH dependency); never run real git.
    monkeypatch.setattr(repair, "pick_repair_provider", lambda cfg: "claude")


def test_opt_out_default_off_never_spawns(tmp_path, monkeypatch):
    _common(monkeypatch)
    monkeypatch.delenv("KONSEY_REPAIR", raising=False)
    rc = repair.run_repair_loop(_cfg(tmp_path), _args(force=False),
                                runner=_boom_runner, collect=_Collect(_report(1)),
                                changed_files_fn=lambda r: [], dirty_fn=lambda r: False)
    assert rc == 1          # read-only doctor rc surfaced; runner asserted-not-called


def test_no_op_when_already_healthy(tmp_path, monkeypatch):
    _common(monkeypatch)
    monkeypatch.setenv("KONSEY_REPAIR", "1")
    rc = repair.run_repair_loop(_cfg(tmp_path), _args(), runner=_boom_runner,
                                collect=_Collect(_report(0)),   # nothing critical
                                changed_files_fn=lambda r: [], dirty_fn=lambda r: False)
    assert rc == 0          # healthy install never spawns a worker


def test_confirm_gate_blocks_when_declined(tmp_path, monkeypatch):
    _common(monkeypatch)
    monkeypatch.setenv("KONSEY_REPAIR", "1")
    rc = repair.run_repair_loop(_cfg(tmp_path), _args(force=False), runner=_boom_runner,
                                collect=_Collect(_report(1)), confirm=lambda: False,
                                changed_files_fn=lambda r: [], dirty_fn=lambda r: False)
    assert rc == 1          # declined → never runs the tool-ON agent


def test_producer_not_verifier_success_needs_real_doctor(tmp_path, monkeypatch):
    _common(monkeypatch)
    # worker claims success; loop returns 0 ONLY because the SECOND real doctor is clean.
    rc = repair.run_repair_loop(_cfg(tmp_path), _args(force=True), runner=_ok_runner,
                                collect=_Collect(_report(1), _report(0)), confirm=lambda: True,
                                changed_files_fn=lambda r: [], dirty_fn=lambda r: False)
    assert rc == 0


def test_self_report_ignored_when_doctor_still_critical(tmp_path, monkeypatch):
    _common(monkeypatch)
    rc = repair.run_repair_loop(_cfg(tmp_path), _args(force=True), runner=_ok_runner,
                                collect=_Collect(_report(2)),   # always 2 critical → no progress
                                confirm=lambda: True, changed_files_fn=lambda r: [], dirty_fn=lambda r: False)
    assert rc == 1          # 'I fixed it' is not evidence


def test_outside_repo_write_is_refused(tmp_path, monkeypatch):
    _common(monkeypatch)
    rc = repair.run_repair_loop(_cfg(tmp_path), _args(force=True), runner=_ok_runner,
                                collect=_Collect(_report(1)), confirm=lambda: True,
                                changed_files_fn=lambda r: ["/etc/passwd"], dirty_fn=lambda r: False)
    assert rc == 1          # gate_paths refuses an out-of-repo write


# --- the safety gate itself (real exec_policy, no mock) -------------------------------

def test_gate_command_refuses_destructive():
    v, rules = repair.gate_command("sudo rm -rf /")
    assert v == "refused"
    assert rules                       # privilege_escalation / recursive_delete matched
    assert repair.gate_command("sudo apt install x")[0] == "refused"   # privilege is hard-floor


def test_gate_command_allows_a_built_worker_argv(tmp_path):
    inv = repair.build_repair_invocation(_cfg(tmp_path), "claude",
                                         [{"ok": False, "severity": "critical", "message": "m", "id": "c0"}],
                                         str(tmp_path))
    cmd = " ".join(tok for tok in inv.argv if tok != inv.prompt)
    assert repair.gate_command(cmd)[0] == "allowed"


def test_gate_paths_inside_vs_outside(tmp_path):
    assert repair.gate_paths([str(tmp_path / "council" / "cli.py")], str(tmp_path))[0] == "allowed"
    assert repair.gate_paths(["/etc/hosts"], str(tmp_path))[0] == "refused"


# --- append-only audit per attempt ----------------------------------------------------

def test_repair_writes_append_only_audit(tmp_path, monkeypatch):
    _common(monkeypatch)
    cfg = _cfg(tmp_path)
    rc = repair.run_repair_loop(cfg, _args(force=True), runner=_ok_runner,
                                collect=_Collect(_report(1), _report(0)), confirm=lambda: True,
                                changed_files_fn=lambda r: [], dirty_fn=lambda r: False)
    assert rc == 0
    import duckdb
    con = duckdb.connect(str(cfg.db_path()))
    try:
        n = con.execute("SELECT count(*) FROM council_messages WHERE msg_type='repair_attempt'").fetchone()[0]
        payload = con.execute("SELECT payload FROM council_messages WHERE msg_type='repair_attempt' LIMIT 1").fetchone()[0]
    finally:
        con.close()
    assert n >= 1
    assert "doctor_rc_after" in payload and "env_allowlist_keys" in payload and "provider" in payload
    # env is KEYS-only by construction — a secret VALUE must never appear in the manifest.
    assert "sk-" not in payload and "AKIA" not in payload
