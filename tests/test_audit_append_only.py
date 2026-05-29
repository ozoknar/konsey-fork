"""Append-only audit tests (Constitution Article 10 & 11) — INSERT only.

Three layers, all against REAL DuckDB (no mock):
  1. the shipped schema (council/db/schema.sql) loads and accepts an INSERT;
  2. the programmatic write API (council.audit) only ever appends — session closure
     is a *new* ``session_end`` message, never an UPDATE of the session row;
  3. the read helper (council.cli_helpers.konsey_db.query) REJECTS any statement
     that is not a read (SELECT/WITH/DESCRIBE/SUMMARIZE/PRAGMA).

Honest-boundary note (Md.11.2): app-level append-only does NOT guarantee OS-level
immutability — a process running as the same user could still rewrite the file.
That limitation is documented in SECURITY.md; here we test the app-layer guard,
which is what the code controls.
"""
from __future__ import annotations

import argparse
import uuid
from pathlib import Path

import pytest

import duckdb

from council import audit
from council.cli_helpers import konsey_db
from council.config import Config

SCHEMA = Path(__file__).resolve().parent.parent / "council" / "db" / "schema.sql"


def _fresh_db(tmp_path) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(str(tmp_path / "council.duckdb"))
    con.execute(SCHEMA.read_text(encoding="utf-8"))
    return con


def _cfg(tmp_path) -> Config:
    # Point data_home at a temp dir so audit writes to an isolated DB.
    return Config(data_home=tmp_path)


# --------------------------------------------------------------------------- #
# Layer 1: the real schema loads and accepts INSERTs on real DuckDB.            #
# --------------------------------------------------------------------------- #

def test_schema_loads_and_accepts_insert(tmp_path):
    con = _fresh_db(tmp_path)
    sid = str(uuid.uuid4())
    con.execute(
        "INSERT INTO council_sessions(session_id, topic, risk_profile, status, user_id)"
        " VALUES (?,?,?,?,?)",
        [sid, "a task", "internal", "preflight", "operator"],
    )
    rows = con.execute("SELECT topic, user_id FROM council_sessions WHERE session_id = ?",
                       [sid]).fetchall()
    assert rows == [("a task", "operator")]


# --------------------------------------------------------------------------- #
# Layer 2: the write API appends only; owner defaults to "operator".           #
# --------------------------------------------------------------------------- #

def test_audit_writes_default_owner_operator(tmp_path):
    cfg = _cfg(tmp_path)
    sid = audit.start_session("a task", "internal", {"max_cost": 2.0}, cfg=cfg)
    con = duckdb.connect(str(cfg.db_path()))
    users = {r[0] for r in con.execute("SELECT DISTINCT user_id FROM council_sessions").fetchall()}
    con.close()
    assert users == {"operator"}, "owner must default to 'operator', never a machine username"
    assert uuid.UUID(sid)  # valid id returned


def test_session_close_is_appended_not_an_update(tmp_path):
    cfg = _cfg(tmp_path)
    sid = audit.start_session("a task", "internal", {"max_cost": 2.0}, cfg=cfg)
    audit.end_session(sid, "done", 0.12, cfg=cfg)
    con = duckdb.connect(str(cfg.db_path()))
    # The session row keeps its original status (no UPDATE); closure is a new event.
    status = con.execute("SELECT status FROM council_sessions WHERE session_id = ?", [sid]).fetchone()[0]
    end_events = con.execute(
        "SELECT count(*) FROM council_messages WHERE session_id = ? AND msg_type = 'session_end'",
        [sid],
    ).fetchone()[0]
    con.close()
    assert status == "preflight", "closure must NOT mutate the session row (append-only)"
    assert end_events == 1, "closure is appended as a session_end message event"


def test_audit_module_issues_no_update_or_delete():
    # Structural proof of append-only: the write module contains no UPDATE/DELETE SQL.
    import inspect

    src = inspect.getsource(audit).upper()
    assert "UPDATE " not in src, "append-only audit must not issue UPDATE"
    assert "DELETE " not in src, "append-only audit must not issue DELETE"


# --------------------------------------------------------------------------- #
# Layer 3: the read helper rejects any non-read statement (SELECT-only guard).  #
# --------------------------------------------------------------------------- #

def _query_ns(tmp_path, sql: str) -> argparse.Namespace:
    return argparse.Namespace(sql=sql, db=str(tmp_path / "council.duckdb"), config=None)


@pytest.mark.parametrize("sql", [
    "UPDATE council_sessions SET status='tampered'",
    "DELETE FROM council_sessions",
    "DROP TABLE council_sessions",
    "INSERT INTO council_sessions(session_id) VALUES ('x')",
    "ATTACH 'evil.db'",
    "  update council_decisions set human_approved = true",
])
def test_query_helper_rejects_non_read_statements(tmp_path, sql):
    _fresh_db(tmp_path).close()
    with pytest.raises(SystemExit):
        konsey_db.query(_query_ns(tmp_path, sql))


@pytest.mark.parametrize("sql", [
    "SELECT 1",
    "select count(*) from council_sessions",
    "WITH x AS (SELECT 1) SELECT * FROM x",
    "PRAGMA database_list",
])
def test_query_helper_allows_read_statements(tmp_path, sql, capsys):
    _fresh_db(tmp_path).close()
    konsey_db.query(_query_ns(tmp_path, sql))   # must not raise / exit
