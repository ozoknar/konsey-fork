"""WhatsApp connector — Meta Cloud API webhook (stdlib http.server, yeni bağımlılık yok).

Kurulum: Meta Business → WhatsApp app → kalıcı token (WHATSAPP_TOKEN) + phone-number-id
(WHATSAPP_PHONE_ID) + doğrulama token'ı (WHATSAPP_VERIFY_TOKEN). Webhook URL'inizi
(public HTTPS) Meta'ya kaydedin. Bu sunucu GET (doğrulama) + POST (mesaj) işler.

NOT: public HTTPS webhook + Meta Business onayı gerekir; yerelde tünelle (cloudflared) test.
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .base import run_council

_GRAPH = "https://graph.facebook.com/v18.0"


def _send(phone_id: str, token: str, to: str, body: str) -> None:
    data = json.dumps({"messaging_product": "whatsapp", "to": to,
                       "text": {"body": body[:3500]}}).encode("utf-8")
    req = urllib.request.Request(f"{_GRAPH}/{phone_id}/messages", data=data, headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=20).close()
    except Exception as e:  # noqa: BLE001
        print(f"WhatsApp send hata: {e}")


def run(host: str = "0.0.0.0", port: int | None = None) -> None:
    token = os.getenv("WHATSAPP_TOKEN")
    phone_id = os.getenv("WHATSAPP_PHONE_ID")
    verify = os.getenv("WHATSAPP_VERIFY_TOKEN")
    if not token or not phone_id or not verify:
        print("WHATSAPP_TOKEN / WHATSAPP_PHONE_ID / WHATSAPP_VERIFY_TOKEN yok — devre dışı.")
        return
    port = port or int(os.getenv("PORT", "8080"))

    class _H(BaseHTTPRequestHandler):
        def log_message(self, *a):  # sessiz
            pass

        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if q.get("hub.verify_token", [None])[0] == verify:
                ch = q.get("hub.challenge", [""])[0].encode("utf-8")
                self.send_response(200); self.end_headers(); self.wfile.write(ch)
            else:
                self.send_response(403); self.end_headers()

        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            try:
                payload = json.loads(self.rfile.read(n) or b"{}")
            except Exception:  # noqa: BLE001
                payload = {}
            self.send_response(200); self.end_headers()
            for entry in payload.get("entry", []):
                for ch in entry.get("changes", []):
                    for m in (ch.get("value", {}).get("messages") or []):
                        to = m.get("from")
                        text = (m.get("text") or {}).get("body", "").strip()
                        if not to or not text:
                            continue
                        try:
                            reply = run_council(text)
                        except Exception as e:  # noqa: BLE001
                            reply = f"Hata: {e}"
                        _send(phone_id, token, to, reply)

    print(f"WhatsApp webhook: http://{host}:{port}  (Meta'ya public HTTPS olarak kaydedin)")
    ThreadingHTTPServer((host, port), _H).serve_forever()
