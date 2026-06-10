"""Konsey orkestratör CLI — headless tam döngü.

Kullanım: ./bin/konsey-run "<görev>" [--project-hint <ad>]
"""
from __future__ import annotations

import argparse
import json
import sys

from .graph import build


def run(task: str, project_hint: str = "") -> dict:
    """Çalıştır, final state döndür (programatik kullanım için)."""
    return build().invoke({"task": task, "project_hint": project_hint},
                          config={"recursion_limit": 60})


def main() -> None:
    ap = argparse.ArgumentParser(description="Konsey deterministic orchestrator (headless)")
    ap.add_argument("task", help="task definition")
    ap.add_argument("--project-hint", default="", help="project name/hint (risk classification)")
    ap.add_argument("--json", action="store_true", dest="as_json",
                    help="structured JSON output instead of the human report")
    a = ap.parse_args()

    final = run(a.task, a.project_hint)
    dec = final.get("decision", {})
    if a.as_json:
        print(json.dumps({
            "task": a.task,
            "risk": final.get("risk"),
            "session_id": final.get("session_id"),
            "providers_ok": final.get("providers_ok", 0),
            "blocked": bool(final.get("blocked")),
            "killed": bool(final.get("killed")),
            "decision": dec,
            "report": final.get("report", ""),
        }, ensure_ascii=False))
    else:
        print("\n" + final.get("report", "(no report produced)"))

    # Production-shaped exit: 2 = bloklandı/öldürüldü, 3 = insan onayı gerekli, 0 = ok.
    if final.get("blocked") or final.get("killed"):
        sys.exit(2)
    if dec.get("human_required"):
        sys.exit(3)


if __name__ == "__main__":
    main()
