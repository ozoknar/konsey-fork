"""Watchdog durability invariant: recovery acts on a REAL sustained-silence signal,
never an eager proxy.

A resilience watchdog that reaps too eagerly is worse than none: it kills a run that was
only briefly paused (a false-positive that destroys live work). The hard-won invariant is
that a session is reaped ONLY when its idle time exceeds BOTH its own wall budget AND a
minimum floor (``MIN_STALL_IDLE_S``) — so a short pause is never mistaken for a dead run —
and that the reap is bounded and idempotent (a single append-only close, not a re-kill
every pass). These tests lock that boundary in with a real seeded DuckDB and the real
watchdog. Provider/domain-agnostic — pure orchestration resilience.
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb

from council import audit, watchdog
from council.config import Config

SCHEMA = (Path(audit.__file__).resolve().parent / "db" / "schema.sql").read_text(encoding="utf-8")


def _cfg(tmp_path) -> Config:
    return Config(council_home=tmp_path, data_home=tmp_path / "data")


def _seed_open(cfg, sid, *, idle_min, wall_s):
    cfg.ensure_dirs()
    with duckdb.connect(str(cfg.db_path())) as c:
        c.execute(SCHEMA)
        c.execute(
            "INSERT INTO council_sessions(session_id,topic,risk_profile,status,started_at,"
            "max_wall_time_s,user_id) VALUES (?,?,?,?, now() - to_minutes(?), ?, 'op')",
            [sid, "work", "internal", "planning", idle_min, wall_s])
        c.execute(
            "INSERT INTO council_messages(msg_id,session_id,from_agent,msg_type,payload,"
            "content_hash,ts) VALUES (uuid(),?,?,?,?,?, now() - to_minutes(?))",
            [sid, "orchestrator", "session_start", json.dumps({"topic": "work"}), "h", idle_min])


def test_min_stall_floor_prevents_false_reap_of_briefly_idle_run(tmp_path):
    """A tiny wall budget alone must NOT make a briefly-idle run look dead: idle is past the
    wall but UNDER the MIN_STALL_IDLE_S grace floor → the watchdog leaves it running."""
    assert watchdog.MIN_STALL_IDLE_S >= 600                 # the grace floor exists
    cfg = _cfg(tmp_path)
    # wall = 60s, idle = 5 min (300s): 300 > 60 (wall) BUT 300 < 600 (floor) → NOT stalled.
    _seed_open(cfg, "aaaaaaaa-0000-0000-0000-000000000001", idle_min=5, wall_s=60)
    rep = watchdog.run_watchdog(cfg)
    assert rep.reaped == 0, "a briefly-idle run was falsely reaped despite the grace floor"


def test_idle_past_floor_and_wall_is_reaped_once(tmp_path):
    """Past BOTH the wall budget and the floor → a genuine stall → reaped exactly once
    (append-only session_end), and a second pass does not re-kill it (bounded/idempotent)."""
    cfg = _cfg(tmp_path)
    sid = "aaaaaaaa-0000-0000-0000-000000000002"
    _seed_open(cfg, sid, idle_min=20, wall_s=60)            # 1200s > 60 wall AND > 600 floor
    first = watchdog.run_watchdog(cfg)
    second = watchdog.run_watchdog(cfg)
    assert first.reaped == 1
    assert second.reaped == 0                               # not re-killed — single signal
    with duckdb.connect(str(cfg.db_path())) as c:
        c.execute(SCHEMA)
        ends = c.execute("SELECT count(*) FROM council_messages WHERE session_id=? "
                         "AND msg_type='session_end'", [sid]).fetchone()[0]
    assert ends == 1                                        # exactly one append-only close
