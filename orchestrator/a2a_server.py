"""A2A sunucusu — bu konseyi A2A agent olarak sunar (Anayasa Faz 4.1).

Stdlib http.server (yeni bağımlılık yok). Varsayılan 127.0.0.1 (LAN'a kapalı — güvenli).
Endpoint'ler:
  GET  /health                       → {status, node}
  GET  /.well-known/agent-card.json  → agent kartı
  POST /a2a/task   {task, project_hint?}  → konseyi çalıştırır (≤internal); phi/prod reddedilir (Md.13.7)
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .gateway import preflight

ROOT = Path(__file__).resolve().parent.parent
CARD = ROOT / "a2a" / "agent-card.json"
ALLOWED_AUTO = {"public", "internal"}   # A2A üstünden otonom tavan (Md.13.7)


def _card() -> dict:
    return json.loads(CARD.read_text(encoding="utf-8"))


def handle_task(payload: dict) -> dict:
    """A2A görev isteğini işler. Gateway sınırını uygular, sonra konsey grafını çalıştırır."""
    task = (payload.get("task") or "").strip()
    hint = payload.get("project_hint", "")
    if not task:
        return {"status": "error", "reason": "boş görev"}
    gw = preflight(task, hint)
    if gw.blocked or gw.risk not in ALLOWED_AUTO:
        return {"status": "rejected",
                "reason": gw.block_reason or f"risk={gw.risk} A2A otonom tavanın üstünde (≤internal)",
                "risk": gw.risk,
                "hint": "phi/production reddedilir; interaktif insan onayıyla veya özel peer'a delege"}
    from .graph import build  # ağır import — yalnız gerçek görevde
    final = build().invoke({"task": task, "project_hint": hint}, config={"recursion_limit": 60})
    dec = final.get("decision", {})
    return {"status": "completed", "risk": gw.risk,
            "report": final.get("report", ""), "decision": dec}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # sessiz
        pass

    def _send(self, code: int, obj: dict):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._send(200, {"status": "ok", "node": "konsey-council"})
        elif self.path in ("/.well-known/agent-card.json", "/agent-card.json"):
            self._send(200, _card())
        else:
            self._send(404, {"status": "error", "reason": "bilinmeyen yol"})

    def do_POST(self):
        if self.path != "/a2a/task":
            return self._send(404, {"status": "error", "reason": "bilinmeyen yol"})
        try:
            n = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(n) or b"{}")
        except Exception as e:
            return self._send(400, {"status": "error", "reason": f"geçersiz JSON: {e}"})
        self._send(200, handle_task(payload))


def serve(host: str = "127.0.0.1", port: int = 8787) -> None:
    srv = ThreadingHTTPServer((host, port), Handler)
    print(f"A2A council node: http://{host}:{port}  (card: /.well-known/agent-card.json)")
    srv.serve_forever()


if __name__ == "__main__":
    import sys
    h = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
    p = int(sys.argv[2]) if len(sys.argv) > 2 else 8787
    serve(h, p)
