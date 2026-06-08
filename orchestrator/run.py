"""Konsey orkestratör CLI — headless tam döngü.

Kullanım: ./bin/konsey-run "<görev>" [--project-hint <ad>]
"""
from __future__ import annotations

import argparse

from .graph import build


def main() -> None:
    ap = argparse.ArgumentParser(description="Konsey deterministik orkestratör (Faz 2)")
    ap.add_argument("task", help="görev tanımı")
    ap.add_argument("--project-hint", default="", help="proje adı/ipucu (risk sınıflandırma için)")
    a = ap.parse_args()

    app = build()
    final = app.invoke(
        {"task": a.task, "project_hint": a.project_hint},
        config={"recursion_limit": 60},
    )
    print("\n" + final.get("report", "(rapor üretilmedi)"))


if __name__ == "__main__":
    main()
