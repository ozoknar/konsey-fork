"""Parallel PLAN fan-out (D1) + real-evidence VERIFY command (D2).

D1 — ``cfg.parallel_plan`` fans the provider SUBPROCESSES out concurrently while every
audit write stays on the orchestrator thread, in roster order. The tests prove: (a) the
fan-out is actually concurrent (wall-clock ≈ slowest, not the sum); (b) results and the
audit/evidence order are roster-deterministic regardless of which provider returns first;
(c) it is opt-in (default OFF) and identical in outcome to the serial path.

D2 — ``cfg.verify_cmd`` runs an operator-configured acceptance command whose EXIT CODE is
the authoritative verdict (Article 2.1/2.7, evidence > consensus). The tests prove the
exit code overrides the LLM in BOTH directions, a destructive command is refused (never
run) with an incident, an empty verify_cmd is fully backward-compatible, and the run is
recorded as append-only evidence.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import duckdb

from council import audit, graph
from council.config import ROLE_CRITIC, ROLE_LEAD, ROLE_VERIFIER, Config, RosterEntry

SCHEMA = (Path(audit.__file__).resolve().parent / "db" / "schema.sql").read_text(encoding="utf-8")


class _Result:
    def __init__(self, text: str, ok: bool = True) -> None:
        self.text, self.ok = text, ok
        self.exit_code = 0 if ok else 1
        self.seconds = 0.01


class _SleepyAdapter:
    """An adapter whose ``run`` blocks for ``delay`` seconds — so a concurrent fan-out is
    observably faster than a serial one (the subprocess is the slow, I/O-bound part)."""
    def __init__(self, name: str, delay: float) -> None:
        self.name, self.delay = name, delay

    def run(self, prompt: str, timeout: int = 180) -> _Result:  # noqa: ARG002
        time.sleep(self.delay)
        return _Result(f"plan from {self.name}")


class _Adapter:
    def __init__(self, reply: str) -> None:
        self._reply = reply

    def run(self, prompt: str, timeout: int = 180) -> _Result:  # noqa: ARG002
        return _Result(self._reply)


_THREE_LEADS = [RosterEntry("a", "a", ROLE_LEAD),
                RosterEntry("b", "b", ROLE_LEAD),
                RosterEntry("c", "c", ROLE_LEAD)]


def _plan_cfg(tmp_path, parallel: bool) -> Config:
    return Config(council_home=tmp_path, data_home=tmp_path / "data", owner="op",
                  agents=_THREE_LEADS, parallel_plan=parallel)


def _seed_state(cfg: Config) -> dict:
    sid = audit.start_session("plan-bench", "internal", {"max_wall_s": 900}, cfg=cfg)
    return {"task": "tidy", "session_id": sid, "t_start": time.time(),
            "verify_retries": 0, "evidence": [], "calls": 0, "tool_failures": 0}


# --------------------------------------------------------------------------- D1


def test_parallel_default_is_off():
    assert Config().parallel_plan is False          # opt-in, never on by surprise


def test_parallel_plan_is_concurrent(tmp_path, monkeypatch):
    cfg = _plan_cfg(tmp_path, parallel=True)
    monkeypatch.setattr(graph, "available", lambda c: {"a": True, "b": True, "c": True})
    monkeypatch.setattr("council.adapters.adapter_for", lambda c, name: _SleepyAdapter(name, 0.2))
    state = _seed_state(cfg)
    t0 = time.time()
    out = graph.plan(state, cfg)
    elapsed = time.time() - t0
    assert set(out["plans"]) == {"a", "b", "c"}
    assert out["providers_ok"] == 3
    # 3 × 0.2 s serial = 0.6 s; concurrent ≈ 0.2 s. Generous bound to stay non-flaky.
    assert elapsed < 0.45, f"fan-out was not concurrent ({elapsed:.2f}s ~ serial 0.6s)"


def test_serial_plan_is_sequential(tmp_path, monkeypatch):
    cfg = _plan_cfg(tmp_path, parallel=False)
    monkeypatch.setattr(graph, "available", lambda c: {"a": True, "b": True, "c": True})
    monkeypatch.setattr("council.adapters.adapter_for", lambda c, name: _SleepyAdapter(name, 0.2))
    t0 = time.time()
    out = graph.plan(_seed_state(cfg), cfg)
    elapsed = time.time() - t0
    assert set(out["plans"]) == {"a", "b", "c"}
    assert elapsed > 0.5, f"serial path unexpectedly fast ({elapsed:.2f}s)"   # ~0.6s


def test_parallel_plan_keeps_roster_deterministic_order(tmp_path, monkeypatch):
    """Whichever provider returns first, the audit + state order is roster order — because
    only the subprocess is off-thread; the record loop runs serially in roster order."""
    cfg = _plan_cfg(tmp_path, parallel=True)
    monkeypatch.setattr(graph, "available", lambda c: {"a": True, "b": True, "c": True})
    # c is FASTEST, a is SLOWEST → completion order is c,b,a; roster order must stay a,b,c.
    delays = {"a": 0.30, "b": 0.15, "c": 0.02}
    monkeypatch.setattr("council.adapters.adapter_for",
                        lambda c, name: _SleepyAdapter(name, delays[name]))
    out = graph.plan(_seed_state(cfg), cfg)
    assert list(out["plans"].keys()) == ["a", "b", "c"]                 # state order = roster
    assert [e["agent"] for e in out["evidence"]] == ["a", "b", "c"]     # evidence order = roster


def test_parallel_and_serial_agree(tmp_path, monkeypatch):
    monkeypatch.setattr(graph, "available", lambda c: {"a": True, "b": True, "c": True})
    monkeypatch.setattr("council.adapters.adapter_for", lambda c, name: _Adapter(f"plan-{id(name)%3}"))
    par = graph.plan(_seed_state(_plan_cfg(tmp_path / "p", parallel=True)), _plan_cfg(tmp_path / "p", parallel=True))
    ser = graph.plan(_seed_state(_plan_cfg(tmp_path / "s", parallel=False)), _plan_cfg(tmp_path / "s", parallel=False))
    assert list(par["plans"].keys()) == list(ser["plans"].keys()) == ["a", "b", "c"]
    assert par["providers_ok"] == ser["providers_ok"] == 3


# --------------------------------------------------------------------------- D2

_FULL_ROSTER = [RosterEntry("claude", "claude", ROLE_LEAD),
                RosterEntry("codex", "codex", ROLE_CRITIC),
                RosterEntry("google", "agy", ROLE_VERIFIER)]

_PY = sys.executable
_EXIT0 = f'{_PY} -c "import sys;sys.exit(0)"'
_EXIT1 = f'{_PY} -c "import sys;sys.exit(1)"'


def _vcfg(tmp_path, verify_cmd: str) -> Config:
    return Config(council_home=tmp_path, data_home=tmp_path / "data", owner="op",
                  agents=_FULL_ROSTER, verify_cmd=verify_cmd)


def _run_graph(cfg: Config, reply: str, monkeypatch) -> dict:
    monkeypatch.setattr(graph, "available", lambda c: {"claude": True, "codex": True, "google": True})
    monkeypatch.setattr("council.adapters.adapter_for", lambda c, name: _Adapter(reply))
    return graph.build(cfg).invoke({"task": "do x", "project_hint": ""}, config={"recursion_limit": 80})


def test_verify_cmd_exit0_overrides_llm_fail(tmp_path, monkeypatch):
    # The LLM verifier says FAIL, but the real command passes (exit 0) → it WINS.
    final = _run_graph(_vcfg(tmp_path, _EXIT0), "FAIL — model is not convinced", monkeypatch)
    assert final.get("verify_ok") is True
    assert "rc=0" in final.get("verify_verdict", "")


def test_verify_cmd_nonzero_overrides_llm_pass(tmp_path, monkeypatch):
    # The LLM verifier says PASS, but the real command fails (exit 1) → FAIL wins
    # (gate-test ≠ real-test: an LLM "looks correct" cannot override a failing real check).
    final = _run_graph(_vcfg(tmp_path, _EXIT1), "PASS — looks correct to me", monkeypatch)
    assert final.get("verify_ok") is False
    assert "rc=1" in final.get("verify_verdict", "")


def test_no_verify_cmd_is_backward_compatible(tmp_path, monkeypatch):
    # Empty verify_cmd → original LLM-only behaviour (the PASS verdict is honoured).
    final = _run_graph(_vcfg(tmp_path, ""), "PASS — looks correct", monkeypatch)
    assert final.get("verify_ok") is True
    assert "rc=" not in final.get("verify_verdict", "")


def test_destructive_verify_cmd_is_refused_and_not_run(tmp_path, monkeypatch):
    cfg = _vcfg(tmp_path, "rm -rf /tmp/konsey-should-never-run")
    sid = audit.start_session("d", "internal", {"max_wall_s": 60}, cfg=cfg)
    ran, ok, summary = graph._run_verify_cmd({"session_id": sid, "budget": {"max_wall_s": 60}}, cfg)
    assert ran is True and ok is False
    assert "refused" in summary.lower()
    with duckdb.connect(str(cfg.db_path())) as c:
        c.execute(SCHEMA)
        n = c.execute("SELECT count(*) FROM council_incidents WHERE violation_type='verify_cmd_refused'").fetchone()[0]
    assert n == 1                                    # an incident was raised, command never ran


def test_verify_cmd_run_is_recorded_as_evidence(tmp_path, monkeypatch):
    cfg = _vcfg(tmp_path, _EXIT0)
    sid = audit.start_session("e", "internal", {"max_wall_s": 60}, cfg=cfg)
    graph._run_verify_cmd({"session_id": sid, "budget": {"max_wall_s": 60}}, cfg)
    with duckdb.connect(str(cfg.db_path())) as c:
        c.execute(SCHEMA)
        rows = c.execute("SELECT evidence_type, produced_by, verified_by FROM council_evidence "
                         "WHERE evidence_type='verify_cmd'").fetchall()
    assert rows == [("verify_cmd", "harness", "harness")]
