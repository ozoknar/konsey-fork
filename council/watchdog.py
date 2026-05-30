"""Resilience watchdog (Constitution Art. 12 reversibility / Art. 14 autonomy).

Turns "failed-and-stopped" into "detected, reaped, and — where safe — re-queued",
so a killed/stalled run does not sit dead forever. It is READ-ONLY over the audit DB
plus APPEND-ONLY writes (Art. 10/11.2: an audit row is never UPDATEd or DELETEd —
a session is "closed" by appending a ``session_end`` event, exactly like the rest of
the audit layer). Default-OFF: it only acts when a dispatch bridge is configured (the
opt-in automation), and it is run by the periodic ``dispatch tick`` / scheduler.

Each idempotent pass:
  * STALLED — a session with ``session_start`` but no ``session_end`` whose last
    activity is older than its own wall-budget: the orchestrator died/hung. The
    watchdog appends ``session_end(status='aborted-watchdog')`` + an incident — the
    eternally-open session is REAPED (a rollback of the dead state), so a stuck
    single-instance state can never fail-stop the whole system.
  * RETRIABLE — a failed/reaped session whose risk is ``<= internal`` AND under the
    retry budget AND a bridge inbox exists: the original task is re-queued into the
    dispatch inbox + a ``watchdog_requeue`` event is appended. The EXISTING autonomy
    ceiling (``dispatch.AutoGate``) re-classifies it on the next tick — gated work
    (pii/sensitive/production) still routes to ``queue-human`` and is NEVER auto-re-run.
    The watchdog therefore can never bypass a human-approval gate.
  * EXHAUSTED / GATED — over the retry budget, or risk above the autonomy ceiling:
    a single incident is appended for human review (no auto-retry). Markers keep it
    from re-flagging the same session every tick.

Testability: pass a temp ``cfg`` (pointing at a seeded temp DB); the DB computes the
idle age itself (``now()``), so a test simulates a stall by seeding a session whose
last message is old. No live scheduler, agent, or clock injection required.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import duckdb

from . import audit
from .config import Config, load_config
from .dispatch import ALLOWED_AUTO, _Bridge, _slug, _ts

# A failed/stalled session is re-queued at most this many times before it is escalated
# to a human (bounded recovery — never an infinite retry loop).
MAX_RETRIES = 2

# Floor on the "stalled" idle threshold (seconds): even a session with a tiny wall
# budget is only reaped once it has been silent for at least this long, so a briefly
# paused run is never mistaken for a dead one.
MIN_STALL_IDLE_S = 600


@dataclass
class WatchdogReport:
    scanned: int = 0
    reaped: int = 0
    requeued: int = 0
    flagged: int = 0
    actions: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (f"scanned={self.scanned} reaped={self.reaped} "
                f"requeued={self.requeued} flagged={self.flagged}")


_SCAN_SQL = """
SELECT
  s.session_id,
  s.topic,
  s.risk_profile,
  COALESCE(s.max_wall_time_s, 900) AS wall_s,
  date_part('epoch', now() - COALESCE(
      (SELECT max(m.ts) FROM council_messages m WHERE m.session_id = s.session_id),
      s.started_at)) AS idle_s,
  (SELECT m2.payload FROM council_messages m2
     WHERE m2.session_id = s.session_id AND m2.msg_type = 'session_end'
     ORDER BY m2.ts DESC LIMIT 1) AS end_payload,
  (SELECT count(*) FROM council_messages m3
     WHERE m3.session_id = s.session_id AND m3.msg_type = 'watchdog_requeue') AS requeues,
  (SELECT count(*) FROM council_messages m4
     WHERE m4.session_id = s.session_id AND m4.msg_type = 'watchdog_escalated') AS escalated
FROM council_sessions s
"""


def _scan(cfg: Config) -> list[dict]:
    """Read-only snapshot of every session's health (no writes)."""
    cfg.ensure_dirs()
    schema = (Path(__file__).resolve().parent / "db" / "schema.sql").read_text(encoding="utf-8")
    with duckdb.connect(str(cfg.db_path())) as c:
        c.execute(schema)   # CREATE TABLE IF NOT EXISTS — harmless on an existing DB
        rows = c.execute(_SCAN_SQL).fetchall()
        cols = [d[0] for d in c.description]
    return [dict(zip(cols, r)) for r in rows]


def _end_status(end_payload) -> str | None:
    """The status recorded in a session_end event, or None if the session is still open."""
    if end_payload is None:
        return None
    try:
        data = json.loads(end_payload) if isinstance(end_payload, str) else end_payload
        return str(data.get("status", "")) if isinstance(data, dict) else ""
    except (ValueError, TypeError):
        return ""


def _classify(row: dict) -> str:
    """One of: done | failed | stalled | open."""
    status = _end_status(row.get("end_payload"))
    if status is not None:                       # session_end present → ended
        return "failed" if "abort" in status.lower() else "done"
    idle = float(row.get("idle_s") or 0)
    wall = float(row.get("wall_s") or 900)
    return "stalled" if idle > max(wall, MIN_STALL_IDLE_S) else "open"


def _requeue(cfg: Config, bridge: _Bridge, row: dict) -> None:
    """Drop the original task back into the dispatch inbox. The existing AutoGate
    ceiling re-classifies it on the next tick — gated work still goes to queue-human."""
    bridge.ensure()
    sid = str(row["session_id"])
    task = str(row.get("topic") or "").strip()
    name = f"{_ts()}-watchdog-{_slug(task)}.json"
    (bridge.inbox / name).write_text(
        json.dumps({"task": task, "_watchdog_resubmit": True, "_origin_session": sid}),
        encoding="utf-8")
    audit.message(sid, "watchdog", "watchdog_requeue",
                  {"task": task[:120], "inbox": name}, cfg=cfg)


def run_watchdog(cfg: Config | None = None) -> WatchdogReport:
    """One idempotent recovery pass. Returns a structured report. Safe to call every
    tick: reaping appends a session_end (so a session is reaped at most once), re-queues
    are bounded by ``MAX_RETRIES``, and escalations are marked so they fire only once."""
    cfg = cfg or load_config()
    bridge = _Bridge(cfg)
    rep = WatchdogReport()
    for row in _scan(cfg):
        rep.scanned += 1
        sid = str(row["session_id"])
        risk = str(row.get("risk_profile") or "internal")
        state = _classify(row)

        if state == "stalled":
            # reap the dead/hung session (append-only close + incident)
            audit.message(sid, "watchdog", "session_end",
                          {"status": "aborted-watchdog", "reason": "stalled past wall budget"}, cfg=cfg)
            audit.incident(sid, "stalled-reaped",
                           f"session idle {int(row.get('idle_s') or 0)}s > wall {int(row.get('wall_s') or 0)}s; reaped by watchdog", cfg=cfg)
            rep.reaped += 1
            rep.actions.append(f"reaped {sid[:8]} ({risk})")
            state = "failed"   # fall through: try to recover it this same pass

        if state != "failed":
            continue

        retriable = risk in ALLOWED_AUTO and int(row.get("requeues") or 0) < MAX_RETRIES and bridge.active
        if retriable:
            _requeue(cfg, bridge, row)
            rep.requeued += 1
            rep.actions.append(f"requeued {sid[:8]} ({risk})")
        elif int(row.get("escalated") or 0) == 0:
            # gated (above ceiling), over budget, or no bridge → human review, ONCE.
            reason = ("retry budget exhausted" if int(row.get("requeues") or 0) >= MAX_RETRIES
                      else f"risk '{risk}' above autonomous ceiling" if risk not in ALLOWED_AUTO
                      else "no dispatch bridge to re-queue into")
            audit.message(sid, "watchdog", "watchdog_escalated", {"reason": reason}, cfg=cfg)
            audit.incident(sid, "watchdog-escalation",
                           f"{reason}; needs human review (no auto-retry)", cfg=cfg)
            rep.flagged += 1
            rep.actions.append(f"escalated {sid[:8]} ({risk}: {reason})")
    return rep
