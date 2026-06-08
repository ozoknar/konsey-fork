"""Telemetri backend testleri: doğrulama, allowlist, install_id hash, agregat.

duckdb gerektirir → proje venv'i ile koşulur.
"""
import importlib.util
import os
import sys
import tempfile
from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")  # venv yoksa atla

_root = Path(__file__).resolve().parent.parent


def _load_server(db: str):
    os.environ["KONSEY_TELEMETRY_DB"] = db
    os.environ["KONSEY_TELEMETRY_SALT"] = "test-salt"
    spec = importlib.util.spec_from_file_location(
        "tbserver", _root / "telemetry-backend" / "server.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules["tbserver"] = m
    spec.loader.exec_module(m)
    return m


def _db():
    return os.path.join(tempfile.mkdtemp(), "t.duckdb")


def test_ingest_requires_event():
    srv = _load_server(_db())
    assert srv.ingest({"install_id": "x"})["ok"] is False
    assert srv.ingest({"event": "council_run", "install_id": "u"})["ok"] is True


def test_stats_counts():
    srv = _load_server(_db())
    srv.ingest({"event": "council_run", "install_id": "u1", "konsey_version": "0.1.0"})
    srv.ingest({"event": "council_run", "install_id": "u1", "konsey_version": "0.1.0"})
    st = srv.stats()
    assert st["total_events"] == 2
    assert st["unique_installs"] == 1  # aynı install_id → tek hash


def test_content_fields_not_stored():
    srv = _load_server(_db())
    srv.ingest({"event": "x", "install_id": "u", "task": "GİZLİ", "prompt": "secret"})
    with srv._conn() as c:
        cols = [r[0] for r in c.execute("DESCRIBE events").fetchall()]
    assert "task" not in cols and "prompt" not in cols  # allowlist dışı → şemada yok


def test_install_id_is_hashed():
    srv = _load_server(_db())
    srv.ingest({"event": "x", "install_id": "raw-uuid-123"})
    with srv._conn() as c:
        h = c.execute("SELECT install_hash FROM events").fetchone()[0]
    assert h != "raw-uuid-123" and len(h) == 32
