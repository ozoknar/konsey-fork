"""Konsey Dispatch + Scheduler (Anayasa Faz 3.1 & 3.2).

- inbox→outbox klasör köprüsü (Cowork/mobil): görev dosyası bırak → konsey çalışır → sonuç + bildirim.
- Zamanlanmış işler (scheduled/*.json): launchd periyodik tetikler.
- OTONOMİ SINIRI (Md.13.7): yalnız ≤internal insansız biter; pii/phi/production insan kuyruğuna.

Çalıştırma: python -m orchestrator.dispatch tick    (launchd bunu çağırır)
            python -m orchestrator.dispatch inbox   (tek inbox geçişi)
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from .gateway import preflight
from .graph import build

HOME = Path.home()
BRIDGE = Path(os.getenv("KONSEY_BRIDGE_DIR", HOME / "Claude" / "konsey"))
INBOX, OUTBOX = BRIDGE / "inbox", BRIDGE / "outbox"
QUEUE_HUMAN, PROCESSED = BRIDGE / "queue-human", BRIDGE / "processed"
SCHED_DIR = Path(__file__).resolve().parent.parent / "scheduled"
STATE = SCHED_DIR / ".state.json"

ALLOWED_AUTO = {"public", "internal"}   # otonom çalıştırma tavanı (Md.13.7)
for d in (INBOX, OUTBOX, QUEUE_HUMAN, PROCESSED, SCHED_DIR):
    d.mkdir(parents=True, exist_ok=True)


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower())[:40].strip("-") or "task"


def _ts() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _notify(title: str, msg: str) -> None:
    # F9: AppleScript string enjeksiyonu (RCE) önle — tırnak/ters-eğik/newline/$/backtick temizle, kısalt.
    def _safe(s: str) -> str:
        return re.sub(r'[\\"\n\r`$]', " ", str(s))[:120]
    try:
        import platform
        sysname = platform.system()
        if sysname == "Darwin":
            subprocess.run(["osascript", "-e",
                            f'display notification "{_safe(msg)}" with title "Konsey" subtitle "{_safe(title)}"'],
                           capture_output=True, timeout=10)
        elif sysname == "Linux":
            subprocess.run(["notify-send", f"Konsey — {_safe(title)}", _safe(msg)],
                           capture_output=True, timeout=10)
        # Windows/headless: sessiz (bildirim opsiyonel)
    except Exception:
        pass  # bildirim opsiyonel; başarısızlık akışı durdurmaz


def _parse_task(path: Path) -> tuple[str, str]:
    raw = path.read_text(encoding="utf-8", errors="replace").strip()
    if path.suffix == ".json":
        try:
            d = json.loads(raw)
            return d.get("task", "").strip(), d.get("project_hint", "")
        except Exception:
            pass
    return raw, ""


def _run_task(task: str, hint: str, origin: str) -> Path:
    """Gateway tavanını uygula; ≤internal ise grafı çalıştır, değilse insan kuyruğu."""
    gw = preflight(task, hint)
    base = f"{_ts()}-{_slug(task)}"
    if gw.blocked or gw.risk not in ALLOWED_AUTO:
        reason = gw.block_reason or f"risk={gw.risk} otonom tavanın üstünde (≤internal)"
        out = QUEUE_HUMAN / f"{base}.md"
        out.write_text(
            f"# İNSAN ONAYI GEREKLİ — otonom çalıştırılmadı\n\n"
            f"- görev: {task}\n- kaynak: {origin}\n- risk: {gw.risk}\n- sebep: {reason}\n- notlar: {gw.notes}\n\n"
            f"İncele ve gerekirse interaktif `/konsey` ile elle çalıştır.\n", encoding="utf-8")
        _notify("Kuyruğa alındı (insan onayı)", f"{gw.risk}: {task[:50]}")
        return out
    # Otonom çalıştır
    final = build().invoke({"task": task, "project_hint": hint}, config={"recursion_limit": 60})
    out = OUTBOX / f"{base}.md"
    out.write_text((final.get("report") or "(rapor yok)") + f"\n\n---\nkaynak: {origin}\n", encoding="utf-8")
    dec = final.get("decision", {})
    _notify("Tamamlandı", f"conf={dec.get('confidence')} onay={'EVET' if dec.get('human_required') else 'hayır'}")
    return out


def process_inbox() -> int:
    n = 0
    for f in sorted(INBOX.iterdir()):
        if f.is_dir() or f.name.startswith((".", "_")):  # _ önekli = not/yardım, görev değil
            continue
        task, hint = _parse_task(f)
        if not task:
            f.rename(PROCESSED / f.name)
            continue
        _run_task(task, hint, origin=f"inbox/{f.name}")
        f.rename(PROCESSED / f"{_ts()}-{f.name}")
        n += 1
    return n


def _load_state() -> dict:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text())
        except Exception:
            return {}
    return {}


def run_scheduled() -> int:
    """scheduled/*.json: {name, task, project_hint, every_minutes, enabled}"""
    state = _load_state()
    now = time.time()
    n = 0
    for jf in sorted(SCHED_DIR.glob("*.json")):
        try:
            job = json.loads(jf.read_text())
        except Exception:
            continue
        if not job.get("enabled", True):
            continue
        name = job.get("name", jf.stem)
        due = now - state.get(name, 0) >= job.get("every_minutes", 1440) * 60
        if not due:
            continue
        _run_task(job["task"], job.get("project_hint", ""), origin=f"scheduled/{name}")
        state[name] = now
        n += 1
    if n:
        STATE.write_text(json.dumps(state, indent=2))
    return n


def tick() -> None:
    try:
        import fcntl
    except ModuleNotFoundError:        # Windows: dosya-kilidi yok → tek-örnek garantisi atlanır
        fcntl = None
    lockf = open(SCHED_DIR / ".tick.lock", "w")     # tek-örnek: çakışan tick'ler double-process yapmasın
    if fcntl is not None:
        try:
            fcntl.flock(lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(f"[{datetime.now():%Y-%m-%d %H:%M}] tick atlandı (başka tick çalışıyor)")
            lockf.close()
            return
    try:
        a = process_inbox()
        b = run_scheduled()
        # Sprint 18: oturum yakalama distili + günlük DB snapshot (köprü açığı kapatma)
        try:
            from .capture import process_capture, backup_db, write_recall_cache
            c = process_capture()
            backup_db()
            write_recall_cache()          # F5: SessionStart hook'un cat edeceği cache'i üret
        except Exception as e:
            c = f"err:{e}"
        print(f"[{datetime.now():%Y-%m-%d %H:%M}] inbox={a} scheduled={b} capture={c}")
    finally:
        if fcntl is not None:
            fcntl.flock(lockf, fcntl.LOCK_UN)
        lockf.close()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "tick"
    {"tick": tick, "inbox": lambda: print("inbox:", process_inbox()),
     "scheduled": lambda: print("scheduled:", run_scheduled())}.get(cmd, tick)()
