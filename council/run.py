"""Headless entry → graph.build(cfg).invoke (Article 6).

``council run "<task>" [--project NAME] [--dry-run] [--json]`` runs the full
9-state loop once and prints the report. Configuration (roster, thresholds,
owner, locale, project risk registry) is loaded once from ``council.local.toml``
via ``load_config`` and injected into the graph — nothing machine-specific is
embedded here.
"""
from __future__ import annotations

import argparse
import json
import sys

from .config import available, load_config


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="council run",
        description="Deterministic multi-agent orchestrator (9-state loop).",
    )
    ap.add_argument("task", help="task description")
    ap.add_argument("--project", "--project-hint", dest="project", default="",
                    help="project name/hint for risk classification")
    ap.add_argument("--config", default=None, help="path to council.local.toml (overrides discovery)")
    ap.add_argument("--dry-run", action="store_true",
                    help="classify risk + show the resolved roster, but do not call any provider")
    ap.add_argument("--json", action="store_true", help="emit the final state as JSON instead of the text report")
    a = ap.parse_args(argv)

    cfg = load_config(a.config)

    if a.dry_run:
        # Evidence-first: prove what WOULD run without spending a single provider call.
        from .gateway import preflight as gw_preflight

        avail = available(cfg)
        gw = gw_preflight(a.task, a.project, cfg)
        info = {
            "dry_run": True,
            "task": a.task,
            "risk": gw.risk,
            "blocked": gw.blocked,
            "block_reason": gw.block_reason,
            "budget": gw.budget,
            "providers_available": avail,
            "n_providers": sum(1 for v in avail.values() if v),
            "owner": cfg.owner,
            "locale": cfg.locale,
        }
        if a.json:
            print(json.dumps(info, ensure_ascii=False, indent=2))
        else:
            for k, v in info.items():
                print(f"{k}: {v}")
        return 0

    from .graph import build

    app = build(cfg)
    final = app.invoke(
        {"task": a.task, "project_hint": a.project},
        config={"recursion_limit": 60},
    )

    if a.json:
        # Drop unserializable / bulky internals; the report + decision carry the answer.
        payload = {
            "task": final.get("task"),
            "risk": final.get("risk"),
            "blocked": final.get("blocked", False),
            "killed": final.get("killed", False),
            "advisory": final.get("advisory", False),
            "providers_ok": final.get("providers_ok", 0),
            "decision": final.get("decision", {}),
            "report": final.get("report", ""),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print("\n" + final.get("report", "(no report produced)"))

    dec = final.get("decision", {})
    # Exit non-zero when a human must decide (blocked / killed / low confidence) so a
    # caller or CI can gate on it (evidence > consensus: do not claim success silently).
    if final.get("blocked") or final.get("killed") or dec.get("human_required"):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
