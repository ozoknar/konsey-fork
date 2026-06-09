"""Konsey telemetri ingest sunucusu — referans MVP (stdlib + DuckDB).

Anonim metadata olaylarını alır, doğrular (allowlist), install_id'yi TUZLU-HASH'ler
(ham UUID saklanmaz), append-only `events` tablosuna yazar. Basit agregat döndürür.

Üretim notu: TLS, rate-limit, managed DB ve gerçek tuz (KONSEY_TELEMETRY_SALT) şart.
Çalıştır:  python telemetry-backend/server.py [host] [port]
Env:       KONSEY_TELEMETRY_DB (vars. telemetry-backend/telemetry.duckdb)
           KONSEY_TELEMETRY_SALT (üretimde MUTLAKA gizli, güçlü bir değer)
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import duckdb

_WLOCK = threading.Lock()   # ThreadingHTTPServer + DuckDB tek-yazar: yazımları serileştir

_ROOT = Path(__file__).resolve().parent
DB = Path(os.getenv("KONSEY_TELEMETRY_DB", _ROOT / "telemetry.duckdb"))
SALT = os.getenv("KONSEY_TELEMETRY_SALT", "dev-salt-CHANGE-IN-PROD")

# İstemci sözleşmesiyle aynı allowlist (TELEMETRY.md). Başka alan REDDEDİLİR.
_FIELDS = {"event", "konsey_version", "os", "py", "status", "risk_class",
           "providers_count", "security_level", "duration_ms", "exit_code",
           "error_type", "command"}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
  id UUID DEFAULT uuid() PRIMARY KEY,
  install_hash TEXT,
  event TEXT, konsey_version TEXT, os TEXT, py TEXT,
  status TEXT, risk_class TEXT, providers_count INTEGER, security_level TEXT,
  duration_ms INTEGER, exit_code INTEGER, error_type TEXT, command TEXT,
  ts TIMESTAMP DEFAULT now()
);
"""


def _conn():
    DB.parent.mkdir(parents=True, exist_ok=True)   # volume/dizin yoksa oluştur (dayanıklılık)
    c = duckdb.connect(str(DB))
    c.execute(_SCHEMA)
    return c


def _hash_install(raw: str) -> str:
    """install_id'yi tuzla+hash'le — ham UUID asla saklanmaz (anonimlik)."""
    return hashlib.sha256((SALT + (raw or "")).encode("utf-8")).hexdigest()[:32]


def ingest(payload: dict) -> dict:
    """Tek olayı doğrula + kaydet. Yalnız allowlist alanları; install_id hash'lenir."""
    if not isinstance(payload, dict) or not payload.get("event"):
        return {"ok": False, "reason": "event zorunlu"}
    row = {k: payload.get(k) for k in _FIELDS}
    ih = _hash_install(str(payload.get("install_id", "")))
    cols = ["install_hash"] + list(_FIELDS)
    vals = [ih] + [row[k] for k in _FIELDS]
    placeholders = ",".join(["?"] * len(cols))
    with _WLOCK, _conn() as c:
        c.execute(f"INSERT INTO events({','.join(cols)}) VALUES ({placeholders})", vals)
    return {"ok": True}


def stats() -> dict:
    """Basit agregat — dashboard/gelir analizi için temel."""
    with _conn() as c:
        total = c.execute("SELECT count(*) FROM events").fetchone()[0]
        installs = c.execute("SELECT count(DISTINCT install_hash) FROM events").fetchone()[0]
        by_ver = dict(c.execute(
            "SELECT konsey_version, count(*) FROM events GROUP BY 1 ORDER BY 2 DESC").fetchall())
        by_level = dict(c.execute(
            "SELECT security_level, count(*) FROM events GROUP BY 1").fetchall())
    return {"total_events": total, "unique_installs": installs,
            "by_version": by_ver, "by_security_level": by_level}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code: int, obj: dict | None = None):
        body = json.dumps(obj or {}).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/v1/events":
            return self._send(404, {"reason": "bilinmeyen yol"})
        try:
            n = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(n) or b"{}")
        except Exception as e:
            return self._send(400, {"reason": f"geçersiz JSON: {e}"})
        try:
            r = ingest(payload)
        except Exception as e:
            return self._send(500, {"reason": f"ingest hata: {e}"})
        self._send(204 if r["ok"] else 400, None if r["ok"] else r)

    def do_GET(self):
        if self.path in ("/health", "/"):
            return self._send(200, {"status": "ok"})
        if self.path == "/v1/stats":
            try:
                return self._send(200, stats())
            except Exception as e:
                return self._send(500, {"reason": f"stats hata: {e}"})
        self._send(404, {"reason": "bilinmeyen yol"})


def serve(host: str = "127.0.0.1", port: int = 8900) -> None:
    if SALT == "dev-salt-CHANGE-IN-PROD":
        print("⚠ KONSEY_TELEMETRY_SALT ayarlanmamış — üretimde MUTLAKA güçlü bir değer verin.")
    srv = ThreadingHTTPServer((host, port), Handler)
    print(f"Telemetri ingest: http://{host}:{port}  (POST /v1/events · GET /v1/stats)")
    srv.serve_forever()


if __name__ == "__main__":
    import sys
    env_port = os.getenv("PORT")
    if env_port:                          # Railway/PaaS: $PORT verir → 0.0.0.0'a bağlan
        serve("0.0.0.0", int(env_port))
    else:
        h = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
        p = int(sys.argv[2]) if len(sys.argv) > 2 else 8900
        serve(h, p)
