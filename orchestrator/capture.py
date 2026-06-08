"""Otomatik oturum yakalama + distil köprüsü (Sprint 18 P0 — audit_bridge_gap kapatma).

Cowork VE Claude Code oturumlarını insan müdahalesi olmadan audit DB'ye işler.
Konsey (Claude+Codex+Google) 2-tur incelemesinden geçti; F1–F10 düzeltmeleri uygulandı.

Akış:
  1) Stop hook → `bin/konsey-capture` → `capture/cc-<sid>.json` işaretçisi (üzerine yazılır).
  2) launchd tick → process_capture(): transcript "soğuk" (≥COLD_MIN dk) ise:
       PHI/secret gate (Madde 2 — HAM transcript'i tarar, tool çıktıları DAHİL) →
       temizse `claude -p` ile distil → append-only DB; PHI/secret → queue-human (iskelet).
       (sid+content-hash dedup → resume yeni içeriği segment olarak eklenir, duplicate yok)
  3) tick recall-cache üretir → SessionStart hook (`konsey-recall`) sadece cat eder (DB yok).

APPEND-ONLY (Madde 10.1): yalnız INSERT. Recursion guard: KONSEY_DISTILL env (lock YOK — F1).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from .adapters import ADAPTERS, available, pick
from .gateway import classify_risk, SECRET_PATTERNS

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "council.duckdb"
BRIDGE = Path.home() / "Claude" / "konsey"
CAP = BRIDGE / "capture"
CAP_PROCESSED = CAP / "processed"
CAP_QUEUE_HUMAN = CAP / "queue-human"
CAPTURED_LOG = CAP / ".captured.log"        # F8: "sid\tcontent_hash" dedup defteri
RECALL_CACHE = BRIDGE / "recall-cache.json"  # F5: tick üretir, hook cat eder
BACKUP_DIR = ROOT / "backups"

COLD_MIN = 25
KEEP_BACKUPS = 14

# F3/F10: gateway.SECRET_PATTERNS TEK KAYNAK (modern formatlar orada — preflight de aynı listeyi tarar).
# capture yalnız long_digits ekler (gateway'de olsa preflight'ı aşırı bloklardı).
_SECRETS = dict(SECRET_PATTERNS)
_SECRETS["long_digits"] = re.compile(r"\b\d{8,}\b")   # MRN/dosya-no — capture-only, yalnız MASK
# gate'i tetikleyenler (email + long_digits noisy → yalnız mask, gate değil)
_GATE_SECRETS = {k: p for k, p in _SECRETS.items() if k not in ("email", "long_digits")}

# F2 base64/medya blob ayıklayıcı (screenshot vb. jwt false-positive yapmasın)
_B64_BLOB = re.compile(r"[A-Za-z0-9+/]{200,}={0,2}")

# PHI klinik göstergeler — diakritik düşürerek (ascii "bobrek" de yakalansın)
def _fold(s: str) -> str:
    return s.translate(str.maketrans("ıİşŞğĞüÜöÖçÇ", "iIsSgGuUoOcC")).lower()


_PHI_FOLDED = re.compile(r"\b(?:" + "|".join([
    "hasta", "patient", "dicom", "goruntu", "mri", "tomografi", "tibbi rapor", "rapor metni",
    "teshis", "tani", "mrn", "tc kimlik", "protokol no", "biyometrik", "kesit", "lezyon",
    "anamnez", "epikriz", "nodule", "nodul", "lesion", "malignan\\w*", "carcinoma", "karsinom\\w*",
    "metasta\\w*", "biopsy", "biyopsi", "tumou?r", "tumor", "birads", "radiolog\\w*",
    "oncolog\\w*", "onkolog", "kitle", "bobrek", "meme", "akciger", "sitoloji", "patoloji", "kist",
]) + r")\b")

for d in (CAP, CAP_PROCESSED, CAP_QUEUE_HUMAN):
    d.mkdir(parents=True, exist_ok=True)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _h(s: str) -> str:
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()[:16]


def _mask(t: str) -> str:
    """claude -p'ye gitmeden TÜM secret/identifier desenlerini redakte et (email dâhil)."""
    for pat in _SECRETS.values():
        t = pat.sub("[REDACTED]", t)
    return t


# ---------------------------------------------------------------- append (INSERT-only, transaction)
def _append(topic, risk, decision, conf, refs: dict, human_approved, src):
    sid = str(uuid.uuid4())
    did = str(uuid.uuid4())
    erefs = json.dumps(refs, ensure_ascii=False)
    c = duckdb.connect(str(DB))
    try:
        c.execute("BEGIN TRANSACTION")               # 4 INSERT atomik → orphan session yok
        c.execute(
            "INSERT INTO council_sessions(session_id,topic,risk_profile,budget_usd,max_iter,"
            "max_wall_time_s,status,user_id) VALUES (?,?,?,?,?,?,?,?)",
            [sid, topic, risk, None, None, None, "done", src])
        c.execute(
            "INSERT INTO council_messages(session_id,from_agent,msg_type,payload,content_hash)"
            " VALUES (?,?,?,?,?)",
            [sid, src, "session_start",
             json.dumps({"topic": topic, "risk": risk, "ts": _now(), "auto_capture": True}, ensure_ascii=False),
             _h(topic)])
        c.execute(
            "INSERT INTO council_decisions(decision_id,session_id,decision,confidence,evidence_refs,"
            "dissent_refs,human_approved) VALUES (?,?,?,?,?,?,?)",
            [did, sid, decision, conf, erefs, None, human_approved])
        c.execute(
            "INSERT INTO council_messages(session_id,from_agent,msg_type,payload,content_hash)"
            " VALUES (?,?,?,?,?)",
            [sid, src, "session_end",
             json.dumps({"status": "done", "ts": _now(), "auto_capture": True}, ensure_ascii=False), _h(sid)])
        c.execute("COMMIT")
    except Exception:
        try:
            c.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        c.close()
    return sid


# ---------------------------------------------------------------- F8: sid+hash dedup defteri
def _captured_set() -> set:
    try:
        return set(CAPTURED_LOG.read_text(encoding="utf-8").splitlines())
    except Exception:
        return set()


def _mark_captured(sid: str, h: str) -> None:
    # F8/Google: yalnız _append COMMIT başarılı olduktan SONRA çağrılır
    try:
        with CAPTURED_LOG.open("a", encoding="utf-8") as f:
            f.write(f"{sid}\t{h}\n")
    except Exception:
        pass


# ---------------------------------------------------------------- transcript okuma
def _iter_entries(tp: Path):
    for line in tp.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except Exception:
            continue


def _extract_for_gate(tp: Path) -> str:
    """F2: gate için HAM dosyanın tamamı (tool_use/tool_result DAHİL), base64 blob'lar ayıklanmış.
    KIRPILMAZ (gate atlatılamasın). claude -p'ye GÖNDERİLMEZ."""
    try:
        raw = tp.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    return _B64_BLOB.sub(" ", raw)


def _extract_text(tp: Path) -> str:
    """Distil için yalnız user/assistant text (KIRPMA YOK — kırpma _distill'de mask'tan SONRA)."""
    parts = []
    try:
        for o in _iter_entries(tp):
            msg = o.get("message") or {}
            role = msg.get("role") or o.get("type") or ""
            if role not in ("user", "assistant"):
                continue
            c = msg.get("content")
            if isinstance(c, str):
                txt = c
            elif isinstance(c, list):
                txt = " ".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
            else:
                txt = ""
            if txt.strip():
                parts.append(f"{role}: {txt.strip()}")
    except Exception:
        return ""
    return "\n".join(parts)


def _first_user(text: str) -> str:
    for ln in text.splitlines():
        if ln.startswith("user:"):
            return ln[5:].strip()
    return ""


def _parse_json(s: str):
    m = re.search(r"\{.*\}", s or "", re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def _distill_gate(gate_text: str) -> tuple[bool, str]:
    """(blocked, reason) — fail-SAFE: PHI ya da secret → claude -p'ye GÖNDERME (Madde 2).
    gate_text = _extract_for_gate çıktısı (tool I/O dahil, kırpılmamış)."""
    if not gate_text.strip():
        return False, ""
    if classify_risk(gate_text) == "phi" or _PHI_FOLDED.search(_fold(gate_text)):
        return True, "PHI/klinik gösterge"
    hits = [name for name, pat in _GATE_SECRETS.items() if pat.search(gate_text)]
    if hits:
        return True, f"secret={sorted(hits)[:4]}"
    return False, ""


def _distill(text: str, label: str):
    """claude -p ile özet → dict|None. F7: önce TAM metni maskele, SONRA kırp."""
    if not text.strip():
        return None
    masked = _mask(text)                                   # F7: kırpmadan ÖNCE maskele
    if len(masked) > 40000:
        masked = masked[:30000] + "\n...[kısaltıldı]...\n" + masked[-10000:]
    prompt = (
        f"Aşağıda bir Claude Code/Cowork oturumunun dökümü var (proje: {label}). "
        "Bunu TEK bir konsey audit kaydına özetle. SADECE şu JSON'u döndür:\n"
        '{"topic":"<=80 karakter","risk":"public|internal|pii|production",'
        '"decision":"<=300 karakter ne yapıldı/karar","confidence":0.0,"refs":["PR/commit/dosya"]}\n'
        "KESİN KURAL: çıktına hiçbir API key, token, parola, secret veya hasta kimliği KOYMA.\n\n"
        f"---OTURUM---\n{masked}")
    os.environ["KONSEY_DISTILL"] = "1"                     # recursion guard (adapters env'i çağrı-anında okur)
    try:
        _name = pick("architect", available()) or next(iter(ADAPTERS), None)
        r = ADAPTERS[_name].run(prompt, timeout=120) if _name else None
    finally:
        os.environ.pop("KONSEY_DISTILL", None)
    if not r or not r.ok:
        return None
    return _parse_json(r.text)


def _cold(tp: Path) -> bool:
    if not tp.exists():
        return True
    return (time.time() - tp.stat().st_mtime) >= COLD_MIN * 60


def process_capture() -> int:
    """capture/ kuyruğunu işle. Soğumamış oturumlar atlanır. (F1: lock YOK.)"""
    # F1+crash-orphan: >60dk .processing → queue-human (sessiz kayıp yok; çift-insert riski yok)
    for stale in CAP.glob("*.processing"):
        try:
            if time.time() - stale.stat().st_mtime > 3600:
                stale.rename(CAP_QUEUE_HUMAN / stale.name)
        except Exception:
            pass

    pending = sorted(CAP.glob("cc-*.json")) + sorted(CAP.glob("cowork-*.json"))
    if not pending:
        return 0
    seen = _captured_set()
    n = 0
    for f in pending:
        # idempotency: önce .processing'e claim → çakışan tick/crash tekrar işlemez (glob eşleşmez)
        proc = f.with_name(f.name + ".processing")
        try:
            f.rename(proc)
        except Exception:
            continue
        try:
            ptr = json.loads(proc.read_text(encoding="utf-8"))
        except Exception:
            proc.rename(CAP_PROCESSED / proc.name)
            continue
        tp = Path(ptr.get("transcript_path") or "")
        src = ptr.get("source", "claude-code")
        cwd = ptr.get("cwd", "")
        sid = str(ptr.get("session_id") or proc.name)
        label = (cwd.rstrip("/").split("/")[-1] or "session")
        if tp and tp.exists() and not _cold(tp):
            proc.rename(f)                                 # henüz soğumadı → geri koy
            continue

        gate_text = _extract_for_gate(tp) if (tp and tp.exists()) else ""
        convo = _extract_text(tp) if (tp and tp.exists()) else ""
        chash = _h(gate_text or convo)                     # F8: içerik parmak izi

        if f"{sid}\t{chash}" in seen:                      # F8: birebir aynı → gerçek duplicate, atla
            proc.rename(CAP_PROCESSED / proc.name)
            continue
        resume = any(line.startswith(sid + "\t") for line in seen)  # aynı sid farklı hash = resume segment

        risk = classify_risk(gate_text) if gate_text else "internal"
        blocked, why = _distill_gate(gate_text)
        seg = " [resume]" if resume else ""

        if blocked:                                        # GATE (Madde 2): distil etme
            _append(
                topic=f"[auto-capture {src}{seg}] {label} — GATED ({why})",
                risk=("phi" if risk == "phi" else "internal"),
                decision=f"Oturum yakalandı ama {why} tespit edildi → distil ATLANDI (Madde 2/13). queue-human; insan incelemeli.",
                conf=None, refs={"source": "auto-capture", "gated": True, "reason": why, "cwd": cwd, "sid": sid},
                human_approved=None, src=src)
            dest = CAP_QUEUE_HUMAN / proc.name
        else:
            s = _distill(convo, label)
            if s and s.get("decision"):
                _append(
                    topic=f"[auto-capture {src}{seg}] {str(s.get('topic') or label)[:80]}",
                    risk=(s.get("risk") if s.get("risk") in ("public", "internal", "pii", "production") else risk),
                    decision=str(s.get("decision"))[:600],
                    conf=(float(s["confidence"]) if isinstance(s.get("confidence"), (int, float)) else None),
                    refs={"source": "auto-capture", "cwd": cwd, "sid": sid, "refs": s.get("refs", [])},
                    human_approved=None, src=src)
            else:                                          # F4: iskelet — ilk istek MASKELENİR
                _append(
                    topic=f"[auto-capture {src}{seg}] {label}",
                    risk=risk,
                    decision=f"Oturum kaydedildi (iskelet). İlk istek: {_mask(_first_user(convo))[:160]}",
                    conf=None, refs={"source": "auto-capture-skeleton", "cwd": cwd, "sid": sid},
                    human_approved=None, src=src)
            dest = CAP_PROCESSED / proc.name
        _mark_captured(sid, chash)                         # F8: yalnız _append COMMIT'ten SONRA
        seen.add(f"{sid}\t{chash}")                        # F8: aynı tick'teki ikinci aynı pointer da deduplansın
        try:
            proc.rename(dest)
        except Exception:
            pass
        n += 1
    return n


def backup_db() -> str:
    """F6: CHECKPOINT (WAL'ı ana dosyaya bas) → tek dosyayı tmp'ye kopyala → atomik replace.
    tick tek-örnek flock'ta + Stop hook DB'ye yazmaz → tutarlı snapshot."""
    import shutil
    BACKUP_DIR.mkdir(exist_ok=True)
    try:
        c = duckdb.connect(str(DB))
        c.execute("CHECKPOINT")
        c.close()
    except Exception:
        return ""
    day = datetime.now().strftime("%Y%m%d")
    dst = BACKUP_DIR / f"council-{day}.duckdb"
    tmp = BACKUP_DIR / f".council-{day}.duckdb.tmp"
    try:
        shutil.copy2(DB, tmp)
        os.replace(tmp, dst)                               # atomik
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        return ""
    for old in sorted(BACKUP_DIR.glob("council-*.duckdb"))[:-KEEP_BACKUPS]:
        try:
            old.unlink()
        except Exception:
            pass
    return str(dst)


# ---------------------------------------------------------------- F5: recall cache (tick üretir)
def write_recall_cache() -> None:
    """tick sonunda son durum özetini ATOMİK + 0600 yaz. SessionStart hook bunu cat eder (DB yok)."""
    try:
        con = duckdb.connect(str(DB), read_only=True)
        rows = con.execute(
            "SELECT started_at, risk_profile, substr(topic,1,72) FROM council_sessions "
            "ORDER BY started_at DESC LIMIT 8").fetchall()
        con.close()
    except Exception:
        return
    lines = ["# Konsey — son audit durumu (otomatik recall)"]
    for r in rows:
        lines.append(f"- {str(r[0])[:16]} [{r[1]}] {r[2]}")
    if (ROOT / "sprint18-backlog.md").exists():
        lines.append("\n⚠️ Açık: bkz. sprint18-backlog.md")
    lines.append("Yaşayan Anayasa: v5.0.3 (Madde 11). Tarihçe: council DB + logs/.")
    out = {"hookSpecificOutput": {"hookEventName": "SessionStart",
                                  "additionalContext": "\n".join(lines)}}
    try:
        tmp = RECALL_CACHE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, RECALL_CACHE)                      # atomik (yarım dosya okunmaz)
    except Exception:
        pass


# ---------------------------------------------------------------- hook: pointer yaz (Stop)
def hook() -> None:
    try:
        d = json.loads(sys.stdin.read() or "{}")
    except Exception:
        d = {}
    tp = d.get("transcript_path") or ""
    if not tp:
        return                                             # transcript yoksa yakalanacak içerik yok
    sid = str(d.get("session_id") or Path(tp).stem or "unknown")
    CAP.mkdir(parents=True, exist_ok=True)
    (CAP / f"cc-{sid}.json").write_text(json.dumps({
        "source": "claude-code", "session_id": sid,
        "transcript_path": tp, "cwd": d.get("cwd") or "", "ts": _now(),
    }, ensure_ascii=False), encoding="utf-8")


def recall() -> None:
    """Fallback: cache dosyasını bas (normalde konsey-recall doğrudan cat eder)."""
    try:
        sys.stdout.write(RECALL_CACHE.read_text(encoding="utf-8"))
    except Exception:
        pass


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "process"
    {"hook": hook, "recall": recall,
     "process": lambda: print(f"capture processed={process_capture()}"),
     "backup": lambda: print(f"backup={backup_db()}"),
     "recall-cache": lambda: (write_recall_cache(), print("recall-cache yazıldı"))}.get(cmd, lambda: None)()


if __name__ == "__main__":
    main()
