"""Notion connector — bir veritabanını yoklar, yeni sayfaları görev olarak çalıştırır.

Kurulum: notion.com → internal integration → NOTION_TOKEN; hedef DB'yi integration ile
paylaş; NOTION_DATABASE_ID. Akış: DB'deki her yeni sayfanın başlığı → run_council →
sonucu sayfaya yorum olarak yazar. Görülen sayfa id'leri tekrar işlenmez (in-memory).

Bağımlılık yok (stdlib urllib). Push yok → tick aralığında yoklar.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request

from .base import run_council

_API = "https://api.notion.com/v1"
_VER = "2022-06-28"


def _req(token: str, method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(f"{_API}{path}", data=data, method=method, headers={
        "Authorization": f"Bearer {token}",
        "Notion-Version": _VER,
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def _title_of(page: dict) -> str:
    for prop in (page.get("properties") or {}).values():
        if prop.get("type") == "title":
            return "".join(t.get("plain_text", "") for t in prop.get("title", [])).strip()
    return ""


def run(token: str | None = None, database_id: str | None = None, poll_interval: int = 30) -> None:
    token = token or os.getenv("NOTION_TOKEN")
    database_id = database_id or os.getenv("NOTION_DATABASE_ID")
    if not token or not database_id:
        print("NOTION_TOKEN / NOTION_DATABASE_ID yok — Notion connector devre dışı.")
        return
    seen: set[str] = set()
    print("Notion connector çalışıyor (Ctrl-C ile durdur)…")
    while True:
        try:
            res = _req(token, "POST", f"/databases/{database_id}/query", {"page_size": 20})
        except Exception as e:  # noqa: BLE001
            print(f"Notion query hata: {e}; {poll_interval}s bekle")
            time.sleep(poll_interval)
            continue
        for page in res.get("results", []):
            pid = page.get("id")
            if not pid or pid in seen:
                continue
            seen.add(pid)
            task = _title_of(page)
            if not task:
                continue
            try:
                reply = run_council(task)
            except Exception as e:  # noqa: BLE001
                reply = f"Hata: {e}"
            try:
                _req(token, "POST", "/comments", {
                    "parent": {"page_id": pid},
                    "rich_text": [{"text": {"content": reply[:1900]}}],
                })
            except Exception as e:  # noqa: BLE001
                print(f"Notion comment hata: {e}")
        time.sleep(poll_interval)
