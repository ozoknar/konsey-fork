"""WhatsApp connector — Meta Cloud API webhook (stdlib http.server, yeni bağımlılık yok).

Kurulum: Meta Business → WhatsApp app → kalıcı token (WHATSAPP_TOKEN) + phone-number-id
(WHATSAPP_PHONE_ID) + doğrulama token'ı (WHATSAPP_VERIFY_TOKEN) + app secret
(WHATSAPP_APP_SECRET). Webhook URL'inizi (public HTTPS) Meta'ya kaydedin.

GÜVENLİK: her POST `X-Hub-Signature-256` HMAC imzasıyla doğrulanır (fail-closed) — imzasız
istek 403. Bu, public webhook'u kötüye kullanıma karşı korur.
NOT: public HTTPS + Meta Business onayı gerekir; yerelde tünelle (cloudflared) test.
"""
from __future__ import annotations

import hashlib
import hmac
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


def _extract_messages(payload) -> list[tuple[str, str]]:
    """Güvenli ayrıştırma — bozuk/güvenilmez JSON şekli thread'i çökertmesin."""
    out: list[tuple[str, str]] = []
    if not isinstance(payload, dict):
        return out
    for entry in payload.get("entry", []) if isinstance(payload.get("entry"), list) else []:
        changes = entry.get("changes") if isinstance(entry, dict) else None
        for ch in changes if isinstance(changes, list) else []:
            value = ch.get("value") if isinstance(ch, dict) else None
            msgs = value.get("messages") if isinstance(value, dict) else None
            for m in msgs if isinstance(msgs, list) else []:
                if not isinstance(m, dict):
                    continue
                to = m.get("from")
                txt = m.get("text") if isinstance(m.get("text"), dict) else {}
                text = (txt.get("body") or "").strip()
                if to and text:
                    out.append((to, text))
    return out


def run(host: str = "0.0.0.0", port: int | None = None) -> None:
    token = os.getenv("WHATSAPP_TOKEN")
    phone_id = os.getenv("WHATSAPP_PHONE_ID")
    verify = os.getenv("WHATSAPP_VERIFY_TOKEN")
    app_secret = os.getenv("WHATSAPP_APP_SECRET")
    if not token or not phone_id or not verify or not app_secret:
        print("WHATSAPP_TOKEN / WHATSAPP_PHONE_ID / WHATSAPP_VERIFY_TOKEN / "
              "WHATSAPP_APP_SECRET yok — WhatsApp connector devre dışı.")
        return
    port = port or int(os.getenv("PORT", "8080"))

    class _H(BaseHTTPRequestHandler):
        def log_message(self, *a):  # sessiz
            pass

        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if q.get("hub.verify_token", [None])[0] == verify:
                ch = q.get("hub.challenge", [""])[0].encode("utf-8")
                self.send_response(200)
                self.end_headers()
                self.wfile.write(ch)
            else:
                self.send_response(403)
                self.end_headers()

        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(n)
            sig = self.headers.get("X-Hub-Signature-256", "")
            expected = "sha256=" + hmac.new(app_secret.encode(), raw, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(sig, expected):       # fail-closed: imzasız reddet
                self.send_response(403)
                self.end_headers()
                return
            self.send_response(200)                           # Meta hızlı 200 bekler
            self.end_headers()
            try:
                payload = json.loads(raw or b"{}")
            except Exception:  # noqa: BLE001
                return
            for to, text in _extract_messages(payload):
                try:
                    reply = run_council(text)
                except Exception as e:  # noqa: BLE001
                    reply = f"Hata: {e}"
                _send(phone_id, token, to, reply)

    print(f"WhatsApp webhook: http://{host}:{port}  (Meta'ya public HTTPS olarak kaydedin)")
    ThreadingHTTPServer((host, port), _H).serve_forever()
