"""End-to-end orchestration test for the 9-state graph (council/graph.py).

The #1 test gap the whole-project council evaluation surfaced: the full
PREFLIGHT→PLAN→CRITIQUE→SYNTHESIZE→EXECUTE→VERIFY→DECIDE→REPORT→MEMORY loop was only
exercised through its pieces, never as one compiled run. This injects FAKE adapters
(no live agent / no subprocess) plus a forced provider-availability map, runs the REAL
compiled graph, and asserts the flow, the producer≠verifier invariant, advisory
degradation with <2 providers, and the BOUNDED verify-retry router (no infinite loop).
"""
from __future__ import annotations

from pathlib import Path

import duckdb

from council import audit, graph
from council.config import ROLE_CRITIC, ROLE_LEAD, ROLE_VERIFIER, Config, RosterEntry
from council.exec_policy import mark_untrusted, unwrap_untrusted

SCHEMA = (Path(audit.__file__).resolve().parent / "db" / "schema.sql").read_text(encoding="utf-8")


class _Result:
    """Mimics the adapter run-result shape that graph._ask reads."""
    def __init__(self, text: str, ok: bool = True) -> None:
        self.text, self.ok = text, ok
        self.exit_code = 0 if ok else 1
        self.seconds = 0.01


class _Adapter:
    def __init__(self, reply: str) -> None:
        self._reply = reply

    def run(self, prompt: str, timeout: int = 180) -> _Result:   # noqa: ARG002 (stub)
        return _Result(self._reply)


def _cfg(tmp_path, agents) -> Config:
    return Config(council_home=tmp_path, data_home=tmp_path / "data", owner="op", agents=agents)


def _install(monkeypatch, names, reply) -> None:
    # Force which providers are "on PATH" + replace every adapter with a stub.
    monkeypatch.setattr(graph, "available", lambda cfg: {n: True for n in names})
    monkeypatch.setattr("council.adapters.adapter_for", lambda cfg, name: _Adapter(reply))


def _run(cfg: Config) -> dict:
    return graph.build(cfg).invoke(
        {"task": "tidy the docs", "project_hint": ""}, config={"recursion_limit": 80})


def _session_end_count(cfg: Config) -> int:
    with duckdb.connect(str(cfg.db_path())) as c:
        c.execute(SCHEMA)
        return c.execute(
            "SELECT count(*) FROM council_messages WHERE msg_type='session_end'").fetchone()[0]


_FULL_ROSTER = [
    RosterEntry("claude", "claude", ROLE_LEAD),
    RosterEntry("codex", "codex", ROLE_CRITIC),
    RosterEntry("google", "agy", ROLE_VERIFIER),
]


def test_full_loop_with_cross_verification_reaches_a_decision(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, _FULL_ROSTER)
    _install(monkeypatch, ["claude", "codex", "google"], "PASS — looks correct\n(stub output)")
    final = _run(cfg)
    assert final.get("report")                          # REPORT state produced output
    assert "confidence" in final.get("decision", {})    # DECIDE produced a real decision
    # Quorum: ALL three distinct providers ran successfully (lead+critic+verifier), so the
    # cross-provider participation count must be 3 — NOT 1 (the old lead-only plan count,
    # which structurally capped a one-lead roster at 1 even when codex+agy both succeeded).
    assert final.get("providers_ok", 0) == 3
    assert not final.get("advisory")                    # 2+ providers + cross-verify → not advisory
    assert final.get("verify_ok") is True               # the verifier returned PASS
    # producer ≠ verifier: the executor is the lead (claude); the verifier must differ.
    assert final.get("executor") == "claude"
    assert cfg.verifier(exclude="claude") == "google"
    # MEMORY closed the session append-only (a single session_end event).
    assert _session_end_count(cfg) == 1


def test_single_provider_degrades_to_advisory_not_blocked(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, [RosterEntry("claude", "claude", ROLE_LEAD)])
    _install(monkeypatch, ["claude"], "PASS — stub")
    final = _run(cfg)
    assert final.get("advisory") is True                # <2 providers → advisory, NOT a hard block
    assert "confidence" in final.get("decision", {})    # still completes (advisory, capped)
    assert final.get("verify_ok") is False              # no independent verifier available
    assert _session_end_count(cfg) == 1


def test_unwrap_untrusted_recovers_the_verdict_line():
    # Regression for the bug this end-to-end test caught: _ask wraps every adapter output
    # in the untrusted-data envelope, so the verifier's VERDICT is the BODY, not line 0.
    wrapped = mark_untrusted("VERDICT: PASS\nlooks correct")
    assert wrapped.splitlines()[0].startswith("<<<UNTRUSTED")     # the marker WAS line 0
    body = unwrap_untrusted(wrapped)
    assert body.splitlines()[0] == "VERDICT: PASS"                # verdict recoverable
    assert "PASS" in body.split("\n", 1)[0].upper()
    assert unwrap_untrusted("plain") == "plain"                   # unwrapped passes through
    assert unwrap_untrusted("") == ""


def test_failed_verification_retries_then_decides_bounded(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, _FULL_ROSTER)
    _install(monkeypatch, ["claude", "codex", "google"], "FAIL — not convinced")
    final = _run(cfg)
    # A FAIL verdict re-runs EXECUTE up to cfg.max_verify_retries, then DECIDE — it must be
    # bounded (never an infinite execute↔verify loop).
    assert final.get("verify_ok") is False
    assert final.get("verify_retries", 0) >= cfg.max_verify_retries
    assert "confidence" in final.get("decision", {})
