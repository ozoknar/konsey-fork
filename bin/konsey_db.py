#!/usr/bin/env python3
"""Konsey audit/memory helper — APPEND-ONLY (Anayasa Madde 10).

Yalnızca INSERT ve SELECT yapar. UPDATE/DELETE yoktur (Madde 13.10).
Session kapanışı UPDATE değil, 'session_end' mesaj event'i olarak eklenir.

Çağrı: ~/Projects/council/.venv/bin/python bin/konsey_db.py <komut> ...
(veya kolaylık için: ./bin/konsey <komut> ...)
"""
import argparse
import hashlib
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
DB = Path(os.getenv("KONSEY_DB", ROOT / "council.duckdb"))
SCHEMA = ROOT / "schema.sql"
_schema_done = False


def _conn():
    """Bağlantı aç (lock'a karşı bounded retry); ilk çağrıda şemayı otomatik kur."""
    global _schema_done
    last = None
    c = None
    for _ in range(25):
        try:
            c = duckdb.connect(str(DB))
            break
        except Exception as e:  # noqa: BLE001
            if "lock" not in str(e).lower() and "conflicting" not in str(e).lower():
                raise
            last = e
            time.sleep(0.12)
    if c is None:
        raise last
    if not _schema_done and SCHEMA.exists():
        c.execute(SCHEMA.read_text(encoding="utf-8"))
        _schema_done = True
    return c


def _hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def _now():
    return datetime.now(timezone.utc).isoformat()


def session(a):
    sid = str(uuid.uuid4())
    with _conn() as c:
        c.execute(
            "INSERT INTO council_sessions(session_id,topic,risk_profile,budget_usd,"
            "max_iter,max_wall_time_s,status,user_id) VALUES (?,?,?,?,?,?,?,?)",
            [sid, a.topic, a.risk, a.budget, a.max_iter, a.max_wall, "preflight", a.user],
        )
        c.execute(
            "INSERT INTO council_messages(session_id,from_agent,msg_type,payload,content_hash)"
            " VALUES (?,?,?,?,?)",
            [sid, "orchestrator", "session_start",
             json.dumps({"topic": a.topic, "risk": a.risk, "ts": _now()}), _hash(a.topic)],
        )
    print(sid)


def end(a):
    payload = json.dumps({"status": a.status, "cost_usd": a.cost, "ts": _now()})
    with _conn() as c:
        c.execute(
            "INSERT INTO council_messages(session_id,from_agent,msg_type,payload,content_hash)"
            " VALUES (?,?,?,?,?)",
            [a.session, "orchestrator", "session_end", payload, _hash(payload)],
        )
    print(f"session_end logged: {a.session} status={a.status}")


def message(a):
    mid = str(uuid.uuid4())
    with _conn() as c:
        c.execute(
            "INSERT INTO council_messages(msg_id,session_id,from_agent,to_agent,msg_type,"
            "payload,content_hash) VALUES (?,?,?,?,?,?,?)",
            [mid, a.session, a.from_agent, a.to, a.type, a.payload, _hash(a.payload or "")],
        )
    print(mid)


def evidence(a):
    eid = str(uuid.uuid4())
    with _conn() as c:
        c.execute(
            "INSERT INTO council_evidence(evidence_id,session_id,evidence_type,source,"
            "content_hash,produced_by,verified_by) VALUES (?,?,?,?,?,?,?)",
            [eid, a.session, a.type, a.source, _hash(a.source or ""), a.produced_by, a.verified_by],
        )
    print(eid)


def decision(a):
    did = str(uuid.uuid4())
    with _conn() as c:
        c.execute(
            "INSERT INTO council_decisions(decision_id,session_id,decision,confidence,"
            "evidence_refs,dissent_refs,human_approved) VALUES (?,?,?,?,?,?,?)",
            [did, a.session, a.decision, a.confidence, a.evidence_refs, a.dissent_refs, a.human_approved],
        )
    print(did)


def dissent(a):
    did = str(uuid.uuid4())
    with _conn() as c:
        c.execute(
            "INSERT INTO council_dissent(dissent_id,session_id,agent,rationale) VALUES (?,?,?,?)",
            [did, a.session, a.agent, a.rationale],
        )
    print(did)


def incident(a):
    iid = str(uuid.uuid4())
    with _conn() as c:
        c.execute(
            "INSERT INTO council_incidents(incident_id,session_id,violation_type,detail)"
            " VALUES (?,?,?,?)",
            [iid, a.session, a.type, a.detail],
        )
    print(iid)


def recent(a):
    with _conn() as c:
        rows = c.execute(
            "SELECT started_at, risk_profile, topic, session_id FROM council_sessions "
            "ORDER BY started_at DESC LIMIT ?", [a.n]
        ).fetchall()
    for r in rows:
        print(f"{r[0]}  [{r[1]:<10}] {r[2]}  ({r[3]})")


def query(a):
    low = a.sql.strip().lower()
    if not (low.startswith("select") or low.startswith("with") or low.startswith("describe")
            or low.startswith("summarize") or low.startswith("pragma")):
        sys.exit("REDDEDİLDİ: append-only — yalnız SELECT/WITH/DESCRIBE sorgusu çalıştırılır.")
    with _conn() as c:
        for row in c.execute(a.sql).fetchall():
            print(row)


def main():
    p = argparse.ArgumentParser(description="Konsey audit/memory (append-only)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("session", help="yeni oturum başlat → session_id döner")
    s.add_argument("topic"); s.add_argument("risk")
    s.add_argument("--budget", type=float, default=2.0)
    s.add_argument("--max-iter", dest="max_iter", type=int, default=5)
    s.add_argument("--max-wall", dest="max_wall", type=int, default=900)
    s.add_argument("--user", default=os.getenv("KONSEY_USER", "local"))
    s.set_defaults(func=session)

    e = sub.add_parser("end", help="oturum kapanış event'i ekle")
    e.add_argument("session"); e.add_argument("status")
    e.add_argument("--cost", type=float, default=None)
    e.set_defaults(func=end)

    m = sub.add_parser("message")
    m.add_argument("session"); m.add_argument("from_agent"); m.add_argument("type")
    m.add_argument("--to", default=None); m.add_argument("--payload", default=None)
    m.set_defaults(func=message)

    ev = sub.add_parser("evidence")
    ev.add_argument("session"); ev.add_argument("type"); ev.add_argument("source")
    ev.add_argument("--produced-by", dest="produced_by", default=None)
    ev.add_argument("--verified-by", dest="verified_by", default=None)
    ev.set_defaults(func=evidence)

    d = sub.add_parser("decision")
    d.add_argument("session"); d.add_argument("decision")
    d.add_argument("--confidence", type=float, default=None)
    d.add_argument("--evidence-refs", dest="evidence_refs", default=None)
    d.add_argument("--dissent-refs", dest="dissent_refs", default=None)
    d.add_argument("--human-approved", dest="human_approved", type=lambda x: x.lower() == "true", default=None)
    d.set_defaults(func=decision)

    di = sub.add_parser("dissent")
    di.add_argument("session"); di.add_argument("agent"); di.add_argument("rationale")
    di.set_defaults(func=dissent)

    inc = sub.add_parser("incident")
    inc.add_argument("session"); inc.add_argument("type"); inc.add_argument("detail")
    inc.set_defaults(func=incident)

    r = sub.add_parser("recent"); r.add_argument("-n", type=int, default=10); r.set_defaults(func=recent)
    q = sub.add_parser("query"); q.add_argument("sql"); q.set_defaults(func=query)

    a = p.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
