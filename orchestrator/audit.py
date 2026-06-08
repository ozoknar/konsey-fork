"""Append-only audit yazımı (Anayasa Madde 10). Yalnızca INSERT.

konsey_db.py (CLI) ile aynı council.duckdb'ye yazar; bu modül programatik API sağlar.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import duckdb

_ROOT = Path(__file__).resolve().parent.parent
DB = Path(os.getenv("KONSEY_DB", _ROOT / "council.duckdb"))
SCHEMA = _ROOT / "schema.sql"
_schema_done = False


def _ensure_schema(c) -> None:
    """Taze DB'de şemayı otomatik kur (idempotent; schema.sql = CREATE TABLE IF NOT EXISTS).
    Yeni kullanıcı manuel `duckdb < schema.sql` yapmak zorunda kalmaz."""
    global _schema_done
    if not _schema_done and SCHEMA.exists():
        c.execute(SCHEMA.read_text(encoding="utf-8"))
        _schema_done = True


def _h(s: str) -> str:
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()[:16]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(retries: int = 25, delay: float = 0.12):
    """DuckDB cross-process exclusive-lock'a karşı bounded retry (eşzamanlı konsey komutları)."""
    last = None
    for _ in range(retries):
        try:
            return duckdb.connect(str(DB))
        except Exception as e:  # noqa: BLE001
            if "lock" not in str(e).lower() and "conflicting" not in str(e).lower():
                raise
            last = e
            time.sleep(delay)
    raise last


def _ins(sql: str, params: list) -> None:
    with _connect() as c:
        _ensure_schema(c)
        c.execute(sql, params)


def start_session(topic: str, risk: str, budget: dict, user: str | None = None) -> str:
    user = user or os.getenv("KONSEY_USER", "local")
    sid = str(uuid.uuid4())
    _ins(
        "INSERT INTO council_sessions(session_id,topic,risk_profile,budget_usd,max_iter,"
        "max_wall_time_s,status,user_id) VALUES (?,?,?,?,?,?,?,?)",
        [sid, topic, risk, budget.get("max_cost"), budget.get("max_iter"),
         budget.get("max_wall_s"), "preflight", user],
    )
    message(sid, "orchestrator", "session_start", {"topic": topic, "risk": risk, "ts": _now()})
    return sid


def message(sid: str, frm: str, mtype: str, payload, to: str | None = None) -> None:
    pl = json.dumps(payload, ensure_ascii=False) if not isinstance(payload, str) else payload
    _ins(
        "INSERT INTO council_messages(msg_id,session_id,from_agent,to_agent,msg_type,payload,content_hash)"
        " VALUES (?,?,?,?,?,?,?)",
        [str(uuid.uuid4()), sid, frm, to, mtype, pl, _h(pl)],
    )


def evidence(sid: str, etype: str, source: str, produced_by: str, verified_by: str | None) -> None:
    _ins(
        "INSERT INTO council_evidence(evidence_id,session_id,evidence_type,source,content_hash,"
        "produced_by,verified_by) VALUES (?,?,?,?,?,?,?)",
        [str(uuid.uuid4()), sid, etype, source, _h(source), produced_by, verified_by],
    )


def decision(sid: str, text: str, confidence: float, evidence_refs, dissent_refs, human_approved: bool) -> None:
    _ins(
        "INSERT INTO council_decisions(decision_id,session_id,decision,confidence,evidence_refs,"
        "dissent_refs,human_approved) VALUES (?,?,?,?,?,?,?)",
        [str(uuid.uuid4()), sid, text, confidence,
         json.dumps(evidence_refs, ensure_ascii=False), json.dumps(dissent_refs, ensure_ascii=False),
         human_approved],
    )


def dissent(sid: str, agent: str, rationale: str) -> None:
    _ins(
        "INSERT INTO council_dissent(dissent_id,session_id,agent,rationale) VALUES (?,?,?,?)",
        [str(uuid.uuid4()), sid, agent, rationale],
    )


def incident(sid: str, vtype: str, detail: str) -> None:
    _ins(
        "INSERT INTO council_incidents(incident_id,session_id,violation_type,detail) VALUES (?,?,?,?)",
        [str(uuid.uuid4()), sid, vtype, detail],
    )


def end_session(sid: str, status: str, cost: float | None) -> None:
    message(sid, "orchestrator", "session_end", {"status": status, "cost_usd": cost, "ts": _now()})
