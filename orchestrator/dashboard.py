"""Konsey audit dashboard — sunucusuz tek-dosya HTML (Anayasa Faz 3.3 hafif sürüm).

council.duckdb'yi READ-ONLY okur, dashboard.html üretir. FastAPI/React yerine
statik dosya: uzak Mac'te de açılır, çalışan servis gerektirmez.
Çalıştırma: python -m orchestrator.dashboard  → dashboard.html
"""
from __future__ import annotations

import html
import os
from datetime import datetime
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
DB = Path(os.getenv("KONSEY_DB", ROOT / "council.duckdb"))
OUT = ROOT / "dashboard.html"

CSS = """
body{font:14px/1.5 -apple-system,Segoe UI,sans-serif;margin:0;background:#0e1116;color:#d6deeb}
header{padding:20px 28px;background:#11161f;border-bottom:1px solid #222b3a}
h1{margin:0;font-size:20px}h2{margin:26px 0 8px;font-size:15px;color:#7fd1b9}
.wrap{padding:0 28px 40px}.muted{color:#6b7a90}
table{border-collapse:collapse;width:100%;margin-top:6px;font-size:13px}
th,td{padding:7px 10px;border-bottom:1px solid #1d2633;text-align:left;vertical-align:top}
th{color:#8aa0b6;font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.04em}
tr:hover td{background:#141b26}
.pill{padding:1px 8px;border-radius:10px;font-size:12px;font-weight:600}
.public{background:#13351f;color:#5fd38a}.internal{background:#143047;color:#6bb6ff}
.pii{background:#3a2f10;color:#e0b341}.phi{background:#3a1414;color:#ff8585}.production{background:#371330;color:#e07ad0}
.yes{color:#ff8585;font-weight:700}.no{color:#5fd38a}
.cards{display:flex;gap:14px;flex-wrap:wrap;margin-top:10px}
.card{background:#11161f;border:1px solid #222b3a;border-radius:10px;padding:14px 18px;min-width:120px}
.card .n{font-size:26px;font-weight:700;color:#fff}.card .l{color:#6b7a90;font-size:12px}
"""


def _q(con, sql, params=None):
    return con.execute(sql, params or []).fetchall()


def build_html() -> str:
    con = duckdb.connect(str(DB), read_only=True)
    counts = {t: _q(con, f"SELECT count(*) FROM {t}")[0][0]
              for t in ("council_sessions", "council_decisions", "council_dissent",
                        "council_evidence", "council_incidents")}
    sessions = _q(con, """
        SELECT s.started_at, s.risk_profile, s.topic,
               d.confidence, d.human_approved,
               (SELECT count(*) FROM council_dissent x WHERE x.session_id=s.session_id),
               (SELECT count(*) FROM council_evidence e WHERE e.session_id=s.session_id)
        FROM council_sessions s LEFT JOIN council_decisions d USING(session_id)
        ORDER BY s.started_at DESC LIMIT 50""")
    dissents = _q(con, """
        SELECT di.ts, di.agent, di.rationale, s.topic
        FROM council_dissent di LEFT JOIN council_sessions s USING(session_id)
        ORDER BY di.ts DESC LIMIT 20""")
    incidents = _q(con, "SELECT ts, violation_type, detail FROM council_incidents ORDER BY ts DESC LIMIT 20")
    con.close()

    def esc(x):
        return html.escape(str(x)) if x is not None else ""

    cards = "".join(
        f'<div class="card"><div class="n">{v}</div><div class="l">{k.replace("council_","")}</div></div>'
        for k, v in counts.items())

    srows = ""
    for st, risk, topic, conf, appr, dis, ev in sessions:
        conf_s = f"{conf:.2f}" if conf is not None else "—"
        appr_s = '<span class="yes">EVET</span>' if appr else '<span class="no">hayır</span>'
        srows += (f"<tr><td class='muted'>{esc(st)[:19]}</td>"
                  f"<td><span class='pill {esc(risk)}'>{esc(risk)}</span></td>"
                  f"<td>{esc(topic)[:80]}</td><td>{conf_s}</td><td>{appr_s}</td>"
                  f"<td>{dis}</td><td>{ev}</td></tr>")

    drows = "".join(
        f"<tr><td class='muted'>{esc(t)[:19]}</td><td>{esc(ag)}</td>"
        f"<td>{esc(rat)[:120]}</td><td>{esc(top)[:50]}</td></tr>"
        for t, ag, rat, top in dissents) or "<tr><td colspan=4 class='muted'>itiraz yok</td></tr>"

    irows = "".join(
        f"<tr><td class='muted'>{esc(t)[:19]}</td><td class='yes'>{esc(v)}</td><td>{esc(d)[:100]}</td></tr>"
        for t, v, d in incidents) or "<tr><td colspan=3 class='muted'>olay yok ✓</td></tr>"

    return f"""<!doctype html><html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Konsey Audit Dashboard</title><style>{CSS}</style></head><body>
<header><h1>🏛 Konsey — Audit Dashboard</h1>
<div class="muted">Üretim: {datetime.now():%Y-%m-%d %H:%M} · kaynak: council.duckdb (read-only, append-only)</div></header>
<div class="wrap">
<div class="cards">{cards}</div>
<h2>Oturumlar (son 50)</h2>
<table><tr><th>Başlangıç</th><th>Risk</th><th>Konu</th><th>Güven</th><th>İnsan onayı</th><th>İtiraz</th><th>Kanıt</th></tr>{srows}</table>
<h2>İtirazlar (Dissent log)</h2>
<table><tr><th>Zaman</th><th>Ajan</th><th>Gerekçe</th><th>Konu</th></tr>{drows}</table>
<h2>Olaylar (Incidents)</h2>
<table><tr><th>Zaman</th><th>Tip</th><th>Detay</th></tr>{irows}</table>
</div></body></html>"""


def main() -> None:
    OUT.write_text(build_html(), encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
