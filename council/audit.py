"""Append-only audit (Constitution Article 10) — INSERT only, no UPDATE/DELETE.

Programmatic API over the same ``council.duckdb`` that ``cli_helpers/konsey_db.py``
writes from the command line. Every message, evidence item, decision, dissent and
incident is appended; a session is never mutated to "closed" — closure is appended
as a ``session_end`` message event (Article 10.1).

Portability (vs. the legacy machine-bound module):
  * the DB lives at ``cfg.db_path()`` (XDG-derived ``data_home``), not a
    ``__file__``-relative ``council.duckdb``;
  * ``user`` defaults to ``cfg.owner`` ("operator"), never a hard-coded identity
    and never the machine username.

The config is resolved lazily on first write (``load_config()``), so importing
this module has no side effects. Pass an explicit ``cfg`` to any function to
override (e.g. tests pointing at a temp DB).
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import duckdb

from .config import Config, load_config

_SCHEMA = Path(__file__).resolve().parent / "db" / "schema.sql"


@lru_cache(maxsize=1)
def _default_cfg() -> Config:
    """Resolve config once, lazily — no work at import time."""
    return load_config()


def _resolve(cfg: Config | None) -> Config:
    return cfg if cfg is not None else _default_cfg()


def _h(s: str) -> str:
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()[:16]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Idempotent CREATE TABLE IF NOT EXISTS from db/schema.sql."""
    con.execute(_SCHEMA.read_text(encoding="utf-8"))


def _ins(cfg: Config, sql: str, params: list[Any]) -> None:
    cfg.ensure_dirs()
    with duckdb.connect(str(cfg.db_path())) as c:
        _ensure_schema(c)
        c.execute(sql, params)


def start_session(
    topic: str,
    risk: str,
    budget: dict[str, Any],
    user: str | None = None,
    *,
    cfg: Config | None = None,
) -> str:
    """Append a new session row plus its ``session_start`` message; return the id.

    ``user`` defaults to ``cfg.owner`` ("operator") — the audit log never carries a
    hard-coded identity or the OS username.
    """
    cfg = _resolve(cfg)
    sid = str(uuid.uuid4())
    _ins(
        cfg,
        "INSERT INTO council_sessions(session_id,topic,risk_profile,budget_usd,max_iter,"
        "max_wall_time_s,status,user_id) VALUES (?,?,?,?,?,?,?,?)",
        [sid, topic, risk, budget.get("max_cost"), budget.get("max_iter"),
         budget.get("max_wall_s"), "preflight", user or cfg.owner],
    )
    message(sid, "orchestrator", "session_start", {"topic": topic, "risk": risk, "ts": _now()}, cfg=cfg)
    return sid


def message(
    sid: str,
    frm: str,
    mtype: str,
    payload: Any,
    to: str | None = None,
    *,
    cfg: Config | None = None,
) -> None:
    pl = json.dumps(payload, ensure_ascii=False) if not isinstance(payload, str) else payload
    _ins(
        _resolve(cfg),
        "INSERT INTO council_messages(msg_id,session_id,from_agent,to_agent,msg_type,payload,content_hash)"
        " VALUES (?,?,?,?,?,?,?)",
        [str(uuid.uuid4()), sid, frm, to, mtype, pl, _h(pl)],
    )


def evidence(
    sid: str,
    etype: str,
    source: str,
    produced_by: str,
    verified_by: str | None,
    *,
    cfg: Config | None = None,
) -> None:
    """Record an evidence item. ``verified_by`` should differ from ``produced_by``
    (producer != verifier invariant, Article 2.4); ``None`` marks advisory/unverified."""
    _ins(
        _resolve(cfg),
        "INSERT INTO council_evidence(evidence_id,session_id,evidence_type,source,content_hash,"
        "produced_by,verified_by) VALUES (?,?,?,?,?,?,?)",
        [str(uuid.uuid4()), sid, etype, source, _h(source), produced_by, verified_by],
    )


def decision(
    sid: str,
    text: str,
    confidence: float,
    evidence_refs: Any,
    dissent_refs: Any,
    human_approved: bool,
    *,
    cfg: Config | None = None,
) -> None:
    _ins(
        _resolve(cfg),
        "INSERT INTO council_decisions(decision_id,session_id,decision,confidence,evidence_refs,"
        "dissent_refs,human_approved) VALUES (?,?,?,?,?,?,?)",
        [str(uuid.uuid4()), sid, text, confidence,
         json.dumps(evidence_refs, ensure_ascii=False), json.dumps(dissent_refs, ensure_ascii=False),
         human_approved],
    )


def dissent(sid: str, agent: str, rationale: str, *, cfg: Config | None = None) -> None:
    _ins(
        _resolve(cfg),
        "INSERT INTO council_dissent(dissent_id,session_id,agent,rationale) VALUES (?,?,?,?)",
        [str(uuid.uuid4()), sid, agent, rationale],
    )


def incident(sid: str, vtype: str, detail: str, *, cfg: Config | None = None) -> None:
    _ins(
        _resolve(cfg),
        "INSERT INTO council_incidents(incident_id,session_id,violation_type,detail) VALUES (?,?,?,?)",
        [str(uuid.uuid4()), sid, vtype, detail],
    )


def end_session(sid: str, status: str, cost: float | None, *, cfg: Config | None = None) -> None:
    """Append a ``session_end`` event — sessions are never mutated to 'closed'."""
    message(sid, "orchestrator", "session_end", {"status": status, "cost_usd": cost, "ts": _now()}, cfg=cfg)
