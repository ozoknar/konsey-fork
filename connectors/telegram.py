"""Telegram Bot connector — getUpdates long-poll (yeni bağımlılık yok, stdlib).

Kurulum: @BotFather → bot oluştur → token. connectors.toml: enabled=true,
auth_env="TELEGRAM_BOT_TOKEN". Opsiyonel allowed_chats ile yalnız belirli sohbetler.

Akış: mesaj → run_council (gate + council) → yanıt. phi/prod otomatik reddedilir.
"""
from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request

from .base import run_council

_API = "https://api.telegram.org/bot{token}/{method}"


def _call(token: str, method: str, params: dict | None = None, timeout: int = 70) -> dict:
    url = _API.format(token=token, method=method)
    data = urllib.parse.urlencode(params or {}).encode("utf-8")
    req = urllib.request.Request(url, data=data)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def run(token: str | None = None, allowed_chats: list[str] | None = None,
        poll_timeout: int = 50) -> None:
    token = token or os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("TELEGRAM_BOT_TOKEN yok — Telegram connector devre dışı.")
        return
    offset = 0
    print("Telegram connector çalışıyor (Ctrl-C ile durdur)…")
    while True:
        try:
            resp = _call(token, "getUpdates", {"offset": offset, "timeout": poll_timeout})
        except Exception as e:  # noqa: BLE001
            print(f"getUpdates hata: {e}; 5s bekle")
            time.sleep(5)
            continue
        for upd in resp.get("result", []):
            offset = upd["update_id"] + 1
            msg = upd.get("message") or {}
            text = (msg.get("text") or "").strip()
            chat_id = str((msg.get("chat") or {}).get("id", ""))
            if not text or not chat_id:
                continue
            if allowed_chats and chat_id not in allowed_chats:
                _call(token, "sendMessage", {"chat_id": chat_id, "text": "Yetkisiz sohbet."})
                continue
            _call(token, "sendMessage", {"chat_id": chat_id, "text": "⏳ Konsey çalışıyor…"})
            try:
                reply = run_council(text)
            except Exception as e:  # noqa: BLE001
                reply = f"Hata: {e}"
            _call(token, "sendMessage", {"chat_id": chat_id, "text": reply})
