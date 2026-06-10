"""Slack connector — Socket Mode (public URL gerekmez). Opsiyonel `slack_sdk` bağımlılığı.

Kurulum: api.slack.com/apps → uygulama → Socket Mode aç → App-Level Token (xapp-,
connections:write) + Bot Token (xoxb-, scopes: app_mentions:read, chat:write).
.env: SLACK_BOT_TOKEN, SLACK_APP_TOKEN. Bot'a mention/mesaj at → council yanıtı (thread'de).

`pip install slack_sdk`  (yoksa net mesaj; çekirdek bağımlılık değil.)
"""
from __future__ import annotations

import os

from .base import run_council


def run(bot_token: str | None = None, app_token: str | None = None) -> None:
    bot_token = bot_token or os.getenv("SLACK_BOT_TOKEN")
    app_token = app_token or os.getenv("SLACK_APP_TOKEN")
    if not bot_token or not app_token:
        print("SLACK_BOT_TOKEN / SLACK_APP_TOKEN yok — Slack connector devre dışı.")
        return
    try:
        from slack_sdk.socket_mode import SocketModeClient
        from slack_sdk.socket_mode.response import SocketModeResponse
        from slack_sdk.web import WebClient
    except ModuleNotFoundError:
        print("slack_sdk kurulu değil — `pip install slack_sdk` ile kurun, sonra tekrar deneyin.")
        return

    web = WebClient(token=bot_token)
    client = SocketModeClient(app_token=app_token, web_client=web)

    def _handle(c, req) -> None:
        c.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))
        if req.type != "events_api":
            return
        payload = req.payload if isinstance(req.payload, dict) else {}
        ev = payload.get("event", {})
        if not isinstance(ev, dict):
            return
        if ev.get("type") not in ("app_mention", "message") or ev.get("bot_id"):
            return
        text = (ev.get("text") or "").strip()
        channel = ev.get("channel")
        if not text or not channel:
            return
        ts = ev.get("ts")
        web.chat_postMessage(channel=channel, text="⏳ Konsey çalışıyor…", thread_ts=ts)
        try:
            reply = run_council(text)
        except Exception as e:  # noqa: BLE001
            reply = f"Hata: {e}"
        web.chat_postMessage(channel=channel, text=reply[:3500], thread_ts=ts)

    client.socket_mode_request_listeners.append(_handle)
    print("Slack connector çalışıyor (Socket Mode)…")
    client.connect()
    import threading
    threading.Event().wait()
