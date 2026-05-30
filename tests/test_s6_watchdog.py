"""S6 — resilience watchdog: a killed/stalled run is detected, reaped, and (where
safe) re-queued, instead of sitting dead forever.

Evidence > consensus: every test seeds a REAL temp DuckDB (the same schema the audit
layer uses), runs the REAL watchdog, and asserts the append-only effects + the
autonomy ceiling (gated work is escalated to a human, never auto-re-run) + idempotency.
No live scheduler/agent.
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb

from council import audit, watchdog
from council.config import Config

SCHEMA = (Path(audit.__file__).resolve().parent / "db" / "schema.sql").read_text(encoding="utf-8")


def _cfg(tmp_path, *, bridge=False) -> Config:
    return Config(
        council_home=tmp_path,
        data_home=tmp_path / "data",
        bridge_dir=(tmp_path / "bridge") if bridge else None,
    )


def _seed(cfg, sid, topic, risk, *, idle_min, end_status=None, wall_s=900, requeues=0):
    """Insert a session whose last activity is ``idle_min`` minutes ago (so the DB's own
    now() makes it look stalled), optionally already ended, with N prior re-queues."""
    cfg.ensure_dirs()
    with duckdb.connect(str(cfg.db_path())) as c:
        c.execute(SCHEMA)
        c.execute(
            "INSERT INTO council_sessions(session_id,topic,risk_profile,status,started_at,"
            "max_wall_time_s,user_id) VALUES (?,?,?,?, now() - to_minutes(?), ?, 'op')",
            [sid, topic, risk, "planning", idle_min, wall_s])
        c.execute(
            "INSERT INTO council_messages(msg_id,session_id,from_agent,msg_type,payload,"
            "content_hash,ts) VALUES (uuid(),?,?,?,?,?, now() - to_minutes(?))",
            [sid, "orchestrator", "session_start", json.dumps({"topic": topic}), "h", idle_min])
        if end_status is not None:
            c.execute(
                "INSERT INTO council_messages(msg_id,session_id,from_agent,msg_type,payload,"
                "content_hash,ts) VALUES (uuid(),?,?,?,?,?, now() - to_minutes(?))",
                [sid, "orchestrator", "session_end", json.dumps({"status": end_status}), "h", idle_min])
        for _ in range(requeues):
            c.execute(
                "INSERT INTO council_messages(msg_id,session_id,from_agent,msg_type,payload,"
                "content_hash) VALUES (uuid(),?,?,?,?,?)",
                [sid, "watchdog", "watchdog_requeue", json.dumps({"task": topic}), "h"])


def _msgs(cfg, sid, mtype):
    with duckdb.connect(str(cfg.db_path())) as c:
        c.execute(SCHEMA)
        return c.execute(
            "SELECT count(*) FROM council_messages WHERE session_id=? AND msg_type=?",
            [sid, mtype]).fetchone()[0]


# --------------------------------------------------------------------------- #

def test_stalled_open_session_is_reaped(tmp_path):
    cfg = _cfg(tmp_path)
    _seed(cfg, "11111111-1111-1111-1111-111111111111", "refactor X", "internal",
          idle_min=700, wall_s=900)          # idle 700min >> 15min wall → stalled
    rep = watchdog.run_watchdog(cfg)
    assert rep.reaped == 1
    # reaped = an APPENDED session_end(aborted-watchdog) + an incident (no row mutated)
    assert _msgs(cfg, "11111111-1111-1111-1111-111111111111", "session_end") == 1
    assert _msgs(cfg, "11111111-1111-1111-1111-111111111111", "session_start") == 1  # original intact


def test_fresh_open_session_is_left_alone(tmp_path):
    cfg = _cfg(tmp_path)
    _seed(cfg, "22222222-2222-2222-2222-222222222222", "long task", "internal",
          idle_min=2, wall_s=900)            # only 2min idle → still running, not stalled
    rep = watchdog.run_watchdog(cfg)
    assert rep.reaped == 0 and rep.requeued == 0 and rep.flagged == 0


def test_retriable_failure_is_requeued_through_the_inbox(tmp_path):
    cfg = _cfg(tmp_path, bridge=True)
    _seed(cfg, "33333333-3333-3333-3333-333333333333", "tidy logs", "internal",
          idle_min=1, end_status="aborted")
    rep = watchdog.run_watchdog(cfg)
    assert rep.requeued == 1 and rep.reaped == 0
    inbox = list((tmp_path / "bridge" / "inbox").glob("*.json"))
    assert len(inbox) == 1
    body = json.loads(inbox[0].read_text())
    assert body["task"] == "tidy logs" and body["_watchdog_resubmit"] is True


def test_gated_failure_is_escalated_not_auto_retried(tmp_path):
    # A production-risk failure must NEVER be auto-re-queued — it goes to a human.
    cfg = _cfg(tmp_path, bridge=True)
    _seed(cfg, "44444444-4444-4444-4444-444444444444", "deploy prod", "production",
          idle_min=1, end_status="aborted")
    rep = watchdog.run_watchdog(cfg)
    assert rep.flagged == 1 and rep.requeued == 0
    assert not list((tmp_path / "bridge" / "inbox").glob("*.json"))   # nothing auto-queued
    assert _msgs(cfg, "44444444-4444-4444-4444-444444444444", "watchdog_escalated") == 1


def test_retry_budget_bounds_then_escalates(tmp_path):
    cfg = _cfg(tmp_path, bridge=True)
    _seed(cfg, "55555555-5555-5555-5555-555555555555", "flaky job", "internal",
          idle_min=1, end_status="aborted", requeues=watchdog.MAX_RETRIES)   # already at budget
    rep = watchdog.run_watchdog(cfg)
    assert rep.requeued == 0 and rep.flagged == 1     # exhausted → human, not another retry


def test_done_session_is_ignored(tmp_path):
    cfg = _cfg(tmp_path, bridge=True)
    _seed(cfg, "66666666-6666-6666-6666-666666666666", "all good", "internal",
          idle_min=5, end_status="done")
    rep = watchdog.run_watchdog(cfg)
    assert rep.scanned == 1 and rep.reaped == 0 and rep.requeued == 0 and rep.flagged == 0


def test_second_pass_is_idempotent(tmp_path):
    # Re-running must not reap-again / escalate-again the same session (markers + session_end).
    cfg = _cfg(tmp_path)            # no bridge → stalled reap then escalate(once)
    _seed(cfg, "77777777-7777-7777-7777-777777777777", "stuck", "internal",
          idle_min=700, wall_s=900)
    first = watchdog.run_watchdog(cfg)
    second = watchdog.run_watchdog(cfg)
    assert first.reaped == 1
    assert second.reaped == 0 and second.flagged == 0   # already handled — quiescent
