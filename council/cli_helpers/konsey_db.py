#!/usr/bin/env python3
"""Council audit/memory helper — APPEND-ONLY (Constitution Article 10).

INSERT and SELECT only. No UPDATE/DELETE (Article 10.1). Session closure is not an
UPDATE — it is appended to ``council_messages`` as a ``session_end`` event.

Portability (vs. the legacy machine-bound helper):
  * the DB path comes from ``cfg.db_path()`` (XDG-derived ``data_home``) — resolved
    via ``council.config.load_config()``; overridable with ``--db`` or
    ``$COUNCIL_CONFIG``. No ``__file__``-relative ``council.duckdb``.
  * ``--user`` defaults to ``cfg.owner`` ("operator"), never a hard-coded identity.

Invoke as a module so the package import works:
    python -m council.cli_helpers.konsey_db <command> ...
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from council.config import Config, load_config

from ..i18n import load_catalog, t

_SCHEMA = Path(__file__).resolve().parent.parent / "db" / "schema.sql"


def _cfg(a: argparse.Namespace) -> Config:
    """Resolve config; ``--config`` (if present) takes precedence over discovery."""
    return load_config(getattr(a, "config", None))


def _db_path(a: argparse.Namespace) -> Path:
    """Explicit ``--db`` wins; otherwise ``cfg.db_path()``."""
    db = getattr(a, "db", None)
    if db:
        return Path(db).expanduser()
    cfg = _cfg(a)
    cfg.ensure_dirs()
    return cfg.db_path()


def _conn(a: argparse.Namespace) -> duckdb.DuckDBPyConnection:
    c = duckdb.connect(str(_db_path(a)))
    c.execute(_SCHEMA.read_text(encoding="utf-8"))  # idempotent CREATE TABLE IF NOT EXISTS
    return c


def _hash(s: str) -> str:
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()[:16]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def session(a: argparse.Namespace) -> None:
    user = a.user or _cfg(a).owner   # default owner ("operator"), never hard-coded
    sid = str(uuid.uuid4())
    with _conn(a) as c:
        c.execute(
            "INSERT INTO council_sessions(session_id,topic,risk_profile,budget_usd,"
            "max_iter,max_wall_time_s,status,user_id) VALUES (?,?,?,?,?,?,?,?)",
            [sid, a.topic, a.risk, a.budget, a.max_iter, a.max_wall, "preflight", user],
        )
        c.execute(
            "INSERT INTO council_messages(session_id,from_agent,msg_type,payload,content_hash)"
            " VALUES (?,?,?,?,?)",
            [sid, "orchestrator", "session_start",
             json.dumps({"topic": a.topic, "risk": a.risk, "ts": _now()}), _hash(a.topic)],
        )
    print(sid)


def end(a: argparse.Namespace) -> None:
    payload = json.dumps({"status": a.status, "cost_usd": a.cost, "ts": _now()})
    with _conn(a) as c:
        c.execute(
            "INSERT INTO council_messages(session_id,from_agent,msg_type,payload,content_hash)"
            " VALUES (?,?,?,?,?)",
            [a.session, "orchestrator", "session_end", payload, _hash(payload)],
        )
    cat = load_catalog(_cfg(a))
    print(t(cat, "konsey_db.session_end_logged", session=a.session, status=a.status))


def message(a: argparse.Namespace) -> None:
    mid = str(uuid.uuid4())
    with _conn(a) as c:
        c.execute(
            "INSERT INTO council_messages(msg_id,session_id,from_agent,to_agent,msg_type,"
            "payload,content_hash) VALUES (?,?,?,?,?,?,?)",
            [mid, a.session, a.from_agent, a.to, a.type, a.payload, _hash(a.payload or "")],
        )
    print(mid)


def evidence(a: argparse.Namespace) -> None:
    eid = str(uuid.uuid4())
    with _conn(a) as c:
        c.execute(
            "INSERT INTO council_evidence(evidence_id,session_id,evidence_type,source,"
            "content_hash,produced_by,verified_by) VALUES (?,?,?,?,?,?,?)",
            [eid, a.session, a.type, a.source, _hash(a.source or ""), a.produced_by, a.verified_by],
        )
    print(eid)


def decision(a: argparse.Namespace) -> None:
    did = str(uuid.uuid4())
    with _conn(a) as c:
        c.execute(
            "INSERT INTO council_decisions(decision_id,session_id,decision,confidence,"
            "evidence_refs,dissent_refs,human_approved) VALUES (?,?,?,?,?,?,?)",
            [did, a.session, a.decision, a.confidence, a.evidence_refs, a.dissent_refs, a.human_approved],
        )
    print(did)


def dissent(a: argparse.Namespace) -> None:
    did = str(uuid.uuid4())
    with _conn(a) as c:
        c.execute(
            "INSERT INTO council_dissent(dissent_id,session_id,agent,rationale) VALUES (?,?,?,?)",
            [did, a.session, a.agent, a.rationale],
        )
    print(did)


def incident(a: argparse.Namespace) -> None:
    iid = str(uuid.uuid4())
    with _conn(a) as c:
        c.execute(
            "INSERT INTO council_incidents(incident_id,session_id,violation_type,detail)"
            " VALUES (?,?,?,?)",
            [iid, a.session, a.type, a.detail],
        )
    print(iid)


def recent(a: argparse.Namespace) -> None:
    with _conn(a) as c:
        rows = c.execute(
            "SELECT started_at, risk_profile, topic, session_id FROM council_sessions "
            "ORDER BY started_at DESC LIMIT ?", [a.n]
        ).fetchall()
    for r in rows:
        print(f"{r[0]}  [{r[1]:<10}] {r[2]}  ({r[3]})")


def query(a: argparse.Namespace) -> None:
    low = a.sql.strip().lower()
    if not (low.startswith("select") or low.startswith("with") or low.startswith("describe")
            or low.startswith("summarize") or low.startswith("pragma")):
        cat = load_catalog(_cfg(a))
        sys.exit(t(cat, "konsey_db.query_rejected"))
    with _conn(a) as c:
        for row in c.execute(a.sql).fetchall():
            print(row)


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--db", default=None, help="explicit DuckDB path (overrides cfg.db_path())")
    p.add_argument("--config", default=None, help="explicit council.local.toml path")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Council audit/memory (append-only)")
    _add_common(p)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("session", help="start a new session → prints session_id")
    s.add_argument("topic"); s.add_argument("risk")
    s.add_argument("--budget", type=float, default=2.0)
    s.add_argument("--max-iter", dest="max_iter", type=int, default=5)
    s.add_argument("--max-wall", dest="max_wall", type=int, default=900)
    s.add_argument("--user", default=None, help="defaults to cfg.owner ('operator')")
    _add_common(s)
    s.set_defaults(func=session)

    e = sub.add_parser("end", help="append a session_end event")
    e.add_argument("session"); e.add_argument("status")
    e.add_argument("--cost", type=float, default=None)
    _add_common(e)
    e.set_defaults(func=end)

    m = sub.add_parser("message")
    m.add_argument("session"); m.add_argument("from_agent"); m.add_argument("type")
    m.add_argument("--to", default=None); m.add_argument("--payload", default=None)
    _add_common(m)
    m.set_defaults(func=message)

    ev = sub.add_parser("evidence")
    ev.add_argument("session"); ev.add_argument("type"); ev.add_argument("source")
    ev.add_argument("--produced-by", dest="produced_by", default=None)
    ev.add_argument("--verified-by", dest="verified_by", default=None)
    _add_common(ev)
    ev.set_defaults(func=evidence)

    d = sub.add_parser("decision")
    d.add_argument("session"); d.add_argument("decision")
    d.add_argument("--confidence", type=float, default=None)
    d.add_argument("--evidence-refs", dest="evidence_refs", default=None)
    d.add_argument("--dissent-refs", dest="dissent_refs", default=None)
    d.add_argument("--human-approved", dest="human_approved", type=lambda x: x.lower() == "true", default=None)
    _add_common(d)
    d.set_defaults(func=decision)

    di = sub.add_parser("dissent")
    di.add_argument("session"); di.add_argument("agent"); di.add_argument("rationale")
    _add_common(di)
    di.set_defaults(func=dissent)

    inc = sub.add_parser("incident")
    inc.add_argument("session"); inc.add_argument("type"); inc.add_argument("detail")
    _add_common(inc)
    inc.set_defaults(func=incident)

    r = sub.add_parser("recent"); r.add_argument("-n", type=int, default=10)
    _add_common(r)
    r.set_defaults(func=recent)

    q = sub.add_parser("query"); q.add_argument("sql")
    _add_common(q)
    q.set_defaults(func=query)

    a = p.parse_args(argv)
    a.func(a)


if __name__ == "__main__":
    main()
