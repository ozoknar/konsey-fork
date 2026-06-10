"""Notion connector — bir veritabanını yoklar, yeni sayfaları görev olarak çalıştırır.

Kurulum: notion.com → internal integration → NOTION_TOKEN; hedef DB'yi integration ile
paylaş; NOTION_DATABASE_ID. Akış: DB'deki her yeni sayfanın başlığı → run_council →
sonucu sayfaya yorum olarak yazar.

İdempotent: işlenen sayfa id'leri DİSKE yazılır (yeniden başlatmada tekrar/spam yok).
Yalnız başarılı yorum sonrası "görüldü" işaretlenir → hata sonrası tekrar denenir.
Bağımlılık yok (stdlib urllib). Push yok → poll aralığında yoklar; tam pagination.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from pathlib import Path

from .base import run_council

_API = "https://api.notion.com/v1"
_VER = "2022-06-28"
_SEEN_FILE = Path(__file__).resolve().parent.parent / ".konsey_notion_seen.json"


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


def _load_seen() -> set[str]:
    try:
        return set(json.loads(_SEEN_FILE.read_text(encoding="utf-8")))
    except Exception:  # noqa: BLE001
        return set()


def _save_seen(seen: set[str]) -> None:
    try:
        _SEEN_FILE.write_text(json.dumps(sorted(seen)), encoding="utf-8")
    except OSError:
        pass


def _query_all(token: str, database_id: str) -> list[dict]:
    """Tüm sayfaları çek (has_more/next_cursor ile tam pagination)."""
    pages: list[dict] = []
    cursor = None
    while True:
        body: dict = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        res = _req(token, "POST", f"/databases/{database_id}/query", body)
        pages.extend(res.get("results", []))
        if not res.get("has_more"):
            break
        cursor = res.get("next_cursor")
    return pages


def run(token: str | None = None, database_id: str | None = None, poll_interval: int = 30) -> None:
    token = token or os.getenv("NOTION_TOKEN")
    database_id = database_id or os.getenv("NOTION_DATABASE_ID")
    if not token or not database_id:
        print("NOTION_TOKEN / NOTION_DATABASE_ID yok — Notion connector devre dışı.")
        return
    seen = _load_seen()
    print("Notion connector çalışıyor (Ctrl-C ile durdur)…")
    while True:
        try:
            pages = _query_all(token, database_id)
        except Exception as e:  # noqa: BLE001
            print(f"Notion query hata: {e}; {poll_interval}s bekle")
            time.sleep(poll_interval)
            continue
        for page in pages:
            pid = page.get("id")
            if not pid or pid in seen:
                continue
            task = _title_of(page)
            if not task:
                continue                      # başlık yok → işaretleme (sonra eklenirse yakala)
            try:
                reply = run_council(task)
                _req(token, "POST", "/comments", {
                    "parent": {"page_id": pid},
                    "rich_text": [{"text": {"content": reply[:1900]}}],
                })
                seen.add(pid)                 # yalnız BAŞARILI yorum sonrası
                _save_seen(seen)
            except Exception as e:  # noqa: BLE001
                print(f"Notion işleme hata ({pid}): {e}")   # seen'e eklenmez → tekrar denenir
        time.sleep(poll_interval)
