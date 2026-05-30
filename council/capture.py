"""Autocapture + distillation bridge (Constitution Article 13) — opt-in, default OFF.

Distils Claude Code / agent sessions into the append-only audit DB without human
intervention, *only when explicitly enabled* (``cfg.autocapture_enabled`` and a
configured ``cfg.bridge_dir``). With either unset, every entry point is inert.

Flow (unchanged from the reviewed design; F1–F10 safety fixes preserved):
  1) A Stop hook drops ``capture/cc-<sid>.json`` pointers (overwritten in place).
  2) A scheduler tick calls ``process_capture(cfg)``: once a transcript is "cold"
     (``COLD_MIN`` minutes idle):
       PHI/secret gate (Article 4 — scans the RAW transcript, tool I/O included) →
       if clean, distil via the roster's *distiller* agent (``cfg.by_role("distiller")``)
       → append-only DB; PHI/secret → queue-human (skeleton record, never distilled).
       (sid + content-hash dedup → a resumed session adds new content as a segment.)
  3) The tick writes ``recall-cache.json``; a SessionStart hook just cats it (no DB).

INSERT-only (Article 10). Recursion guard: ``KONSEY_DISTILL`` env (no lock — F1).

Two former machine-specific sources are removed here:
  * the clinical/PHI term list is NOT embedded — it is loaded at runtime from the
    active regime plugin (``regimes/{data_regime}.toml``); ``standard`` carries none
    (single-source rule, Article 4.3 / 13).
  * the audit owner is ``cfg.owner`` ("operator"), never a machine username.
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

from .config import ROLE_DISTILLER, Config, load_config
from .i18n import load_catalog, t

COLD_MIN = 25            # minutes of transcript idle before a session is "cold"
KEEP_BACKUPS = 14        # daily DB snapshots retained
_DISTILL_MAX = 40000     # chars sent to the distiller before truncation (mask-then-trim, F7)


# ----------------------------------------------------------------------------- secret patterns
# F3/F10: the generic SECRET_PATTERNS in gateway.py are the SINGLE source (preflight scans the
# same list). Capture adds only ``long_digits`` (MRN/file-no) — mask-only, never a gate trigger,
# because it is too noisy to block preflight. Imported lazily so this module compiles even while
# gateway is a Phase-2 stub.
def _secret_patterns() -> dict[str, "re.Pattern[str]"]:
    try:
        from .gateway import SECRET_PATTERNS  # type: ignore[attr-defined]
        base = dict(SECRET_PATTERNS)
    except Exception:
        base = {}
    base["long_digits"] = re.compile(r"\b\d{8,}\b")   # MRN/file-no — capture-only, MASK only
    return base


def _gate_secret_patterns(patterns: dict) -> dict:
    # email + long_digits are noisy → mask them, but do NOT let them trip the gate.
    return {k: p for k, p in patterns.items() if k not in ("email", "long_digits")}


# F2: base64/media blob stripper so a screenshot blob does not false-positive as a JWT.
_B64_BLOB = re.compile(r"[A-Za-z0-9+/]{200,}={0,2}")


# ----------------------------------------------------------------------------- regime plugin
def _fold(s: str) -> str:
    """Drop common diacritics so an ASCII transliteration is matched too. Locale-agnostic:
    the table is a fixed transliteration map, not a language word list."""
    return s.translate(str.maketrans("ıİşŞğĞüÜöÖçÇ", "iIsSgGuUoOcC")).lower()


def _regime_field(path: Path) -> str:
    """Read the top-level ``regime`` field of a plugin file (best-effort)."""
    try:
        import tomllib
        with open(path, "rb") as fh:
            return str(tomllib.load(fh).get("regime", "")).strip().lower()
    except Exception:
        return ""


def _regime_plugin_path(cfg: Config) -> Path | None:
    """Locate the active regime plugin. ``standard`` → no plugin (secret-only gate).

    Resolution order (first match wins):
      1. ``$KONSEY_REGIME_FILE`` (preferred) or ``$COUNCIL_REGIME_FILE`` (deprecated) override
      2. ``<council_home>/regimes/{data_regime}.toml`` (operator-installed plugin)
      3. shipped sample under ``<council_home>/examples/regimes/`` whose ``regime``
         field equals the active regime (the sample is named by its domain, e.g.
         ``clinical.example.toml`` with ``regime = "hipaa"`` inside).
    The clinical/identity term lists live ONLY in these files, never in core (Article 4.3)."""
    regime = (cfg.data_regime or "standard").strip().lower()
    if regime in ("", "standard"):
        return None
    env = os.environ.get("KONSEY_REGIME_FILE") or os.environ.get("COUNCIL_REGIME_FILE")
    if env:
        p = Path(env).expanduser()
        return p if p.exists() else None
    installed = cfg.council_home / "regimes" / f"{regime}.toml"
    if installed.exists():
        return installed
    sample_dir = cfg.council_home / "examples" / "regimes"
    if sample_dir.is_dir():
        # exact-name sample first, then any sample whose internal regime field matches.
        named = sample_dir / f"{regime}.example.toml"
        if named.exists():
            return named
        for c in sorted(sample_dir.glob("*.example.toml")):
            if _regime_field(c) == regime:
                return c
    return None


def _load_regime(cfg: Config) -> tuple["re.Pattern[str] | None", list["re.Pattern[str]"]]:
    """Return ``(folded_term_pattern, identifier_patterns)`` from the regime plugin.

    The term pattern matches any plugin ``terms`` entry on a diacritic-folded string;
    identifier patterns come from each ``[[identifiers]]`` ``pattern``. With no active
    plugin (``standard``) both are empty and only the generic secret gate applies."""
    path = _regime_plugin_path(cfg)
    if path is None:
        return None, []
    try:
        import tomllib
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
    except Exception:
        return None, []

    terms = [str(t) for t in (data.get("terms") or []) if str(t).strip()]
    term_pat: "re.Pattern[str] | None" = None
    if terms:
        # terms are matched against a folded string, so fold them too; escape to treat as literals.
        alts = "|".join(re.escape(_fold(t)) for t in terms)
        term_pat = re.compile(r"(?:" + alts + r")")

    ident_pats: list["re.Pattern[str]"] = []
    for item in data.get("identifiers") or []:
        if not isinstance(item, dict):
            continue
        raw = str(item.get("pattern", "")).strip()
        if not raw:
            continue
        try:
            ident_pats.append(re.compile(raw))
        except re.error:
            continue
    return term_pat, ident_pats


# ----------------------------------------------------------------------------- bridge paths
class _Bridge:
    """Resolved bridge directory layout. Built from ``cfg.bridge_dir``; when that is
    ``None`` (or autocapture is disabled) the bridge is *inert* — ``active`` is False and
    nothing is created or touched."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.active = cfg.bridge_dir is not None and bool(cfg.autocapture_enabled)
        root = cfg.bridge_dir
        if root is None:
            # placeholders only; never used while inert.
            self.cap = self.processed = self.queue_human = Path(os.devnull)
            self.captured_log = self.recall_cache = Path(os.devnull)
            return
        self.cap = root / "capture"
        self.processed = self.cap / "processed"
        self.queue_human = self.cap / "queue-human"
        self.captured_log = self.cap / ".captured.log"   # F8: "sid\tcontent_hash" dedup ledger
        self.recall_cache = root / "recall-cache.json"   # F5: tick writes, hook cats

    def ensure(self) -> None:
        if not self.active:
            return
        for d in (self.cap, self.processed, self.queue_human):
            d.mkdir(parents=True, exist_ok=True)


def _backup_dir(cfg: Config) -> Path:
    return cfg.data_home / "backups"


# ----------------------------------------------------------------------------- small helpers
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _h(s: str) -> str:
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()[:16]


def _mask(t: str, patterns: dict) -> str:
    """Redact every secret/identifier pattern (email included) before anything leaves
    the machine to the distiller agent."""
    for pat in patterns.values():
        t = pat.sub("[REDACTED]", t)
    return t


# ----------------------------------------------------------------- append (INSERT-only, transaction)
def _append(cfg: Config, topic, risk, decision, conf, refs: dict, human_approved, src) -> str:
    """Atomic 4-INSERT session record. ``user_id`` = ``cfg.owner`` (never a machine user);
    the capture source is preserved in ``from_agent`` and ``refs``."""
    sid = str(uuid.uuid4())
    did = str(uuid.uuid4())
    erefs = json.dumps(refs, ensure_ascii=False)
    owner = cfg.owner
    c = duckdb.connect(str(cfg.db_path()))
    try:
        c.execute("BEGIN TRANSACTION")               # 4 INSERTs atomic → no orphan session
        c.execute(
            "INSERT INTO council_sessions(session_id,topic,risk_profile,budget_usd,max_iter,"
            "max_wall_time_s,status,user_id) VALUES (?,?,?,?,?,?,?,?)",
            [sid, topic, risk, None, None, None, "done", owner])
        c.execute(
            "INSERT INTO council_messages(session_id,from_agent,msg_type,payload,content_hash)"
            " VALUES (?,?,?,?,?)",
            [sid, src, "session_start",
             json.dumps({"topic": topic, "risk": risk, "ts": _now(), "auto_capture": True},
                        ensure_ascii=False),
             _h(topic)])
        c.execute(
            "INSERT INTO council_decisions(decision_id,session_id,decision,confidence,evidence_refs,"
            "dissent_refs,human_approved) VALUES (?,?,?,?,?,?,?)",
            [did, sid, decision, conf, erefs, None, human_approved])
        c.execute(
            "INSERT INTO council_messages(session_id,from_agent,msg_type,payload,content_hash)"
            " VALUES (?,?,?,?,?)",
            [sid, src, "session_end",
             json.dumps({"status": "done", "ts": _now(), "auto_capture": True},
                        ensure_ascii=False), _h(sid)])
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


# ----------------------------------------------------------------- F8: sid+hash dedup ledger
def _captured_set(bridge: _Bridge) -> set:
    try:
        return set(bridge.captured_log.read_text(encoding="utf-8").splitlines())
    except Exception:
        return set()


def _mark_captured(bridge: _Bridge, sid: str, h: str) -> None:
    # F8: only ever called AFTER a successful _append COMMIT.
    try:
        with bridge.captured_log.open("a", encoding="utf-8") as f:
            f.write(f"{sid}\t{h}\n")
    except Exception:
        pass


# ----------------------------------------------------------------- transcript reading
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
    """F2: the WHOLE raw file for gating (tool_use/tool_result included), base64 blobs
    stripped. NOT truncated (the gate must not be bypassable). Never sent to the distiller."""
    try:
        raw = tp.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    return _B64_BLOB.sub(" ", raw)


def _extract_text(tp: Path) -> str:
    """Distillation input: user/assistant text only (NO truncation — trimming happens in
    ``_distill`` AFTER masking)."""
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
                txt = " ".join(b.get("text", "") for b in c
                               if isinstance(b, dict) and b.get("type") == "text")
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


# ----------------------------------------------------------------- gate + distil
def _classify_risk(text: str, cfg: Config) -> str:
    """Defensive bridge to gateway.classify_risk. Falls back to ``internal`` only if the
    gateway is unavailable, so capture can be compiled/tested before gateway lands.
    ``cfg`` is forwarded so the gateway can honour the project risk registry / data regime."""
    try:
        from .gateway import classify_risk
        return classify_risk(text, "", cfg)
    except Exception:
        return "internal"


def _distill_gate(gate_text: str, cfg: Config) -> tuple[bool, str]:
    """(blocked, reason) — fail-SAFE: any PHI/regime indicator or secret → do NOT send to
    the distiller (Article 4 / 13). ``gate_text`` is the raw, untruncated transcript."""
    if not gate_text.strip():
        return False, ""
    cat = load_catalog(cfg)
    term_pat, ident_pats = _load_regime(cfg)
    folded = _fold(gate_text)
    if _classify_risk(gate_text, cfg) in ("sensitive", "phi"):
        return True, t(cat, "capture.gate_sensitive")
    if term_pat is not None and term_pat.search(folded):
        return True, t(cat, "capture.gate_regime_term")
    for ip in ident_pats:
        if ip.search(gate_text):
            return True, t(cat, "capture.gate_regime_identifier")
    patterns = _secret_patterns()
    gate_secrets = _gate_secret_patterns(patterns)
    hits = [name for name, pat in gate_secrets.items() if pat.search(gate_text)]
    if hits:
        return True, t(cat, "capture.gate_secret", secrets=sorted(hits)[:4])
    return False, ""


def _distiller_run(cfg: Config, prompt: str, timeout: int = 120):
    """Run the roster's *distiller* agent on ``prompt``. The agent comes from
    ``cfg.by_role('distiller')`` (no hard-coded provider). Returns an object with
    ``.ok`` / ``.text`` or ``None`` when no distiller is configured / available.

    Imported lazily so this module compiles while adapters is a Phase-2 stub."""
    names = cfg.by_role(ROLE_DISTILLER)
    if not names:
        return None
    try:
        from .adapters import adapter_for
    except Exception:
        return None
    for name in names:
        try:
            adapter = adapter_for(cfg, name)
        except Exception:
            adapter = None
        if adapter is None:
            continue
        os.environ["KONSEY_DISTILL"] = "1"   # recursion guard (adapters read env at call time)
        try:
            r = adapter.run(prompt, timeout=timeout)
        except Exception:
            r = None
        finally:
            os.environ.pop("KONSEY_DISTILL", None)
        if r is not None and getattr(r, "ok", False):
            return r
    return None


def _distill(cfg: Config, text: str, label: str):
    """Summarise a session into one audit record. F7: mask the FULL text first, THEN trim."""
    if not text.strip():
        return None
    cat = load_catalog(cfg)
    masked = _mask(text, _secret_patterns())                 # F7: mask before truncation
    if len(masked) > _DISTILL_MAX:
        masked = masked[:30000] + t(cat, "capture.truncated") + masked[-10000:]
    prompt = t(cat, "capture.distill_prompt", label=label, masked=masked)
    r = _distiller_run(cfg, prompt, timeout=120)
    if r is None:
        return None
    return _parse_json(getattr(r, "text", "") or "")


def _cold(tp: Path) -> bool:
    if not tp.exists():
        return True
    return (time.time() - tp.stat().st_mtime) >= COLD_MIN * 60


# ----------------------------------------------------------------- main queue processor
def process_capture(cfg: Config | None = None) -> int:
    """Process the capture queue. Cold-only; inert unless autocapture is enabled with a
    configured bridge_dir. (F1: no lock — the scheduler tick holds the single-instance flock.)"""
    cfg = cfg or load_config()
    cat = load_catalog(cfg)
    bridge = _Bridge(cfg)
    if not bridge.active:
        return 0                                       # inert: opt-in OFF or no bridge_dir
    bridge.ensure()

    # F1 + crash-orphan: a >60min .processing file → queue-human (no silent loss, no double-insert)
    for stale in bridge.cap.glob("*.processing"):
        try:
            if time.time() - stale.stat().st_mtime > 3600:
                stale.rename(bridge.queue_human / stale.name)
        except Exception:
            pass

    # capture pointers: cc-*.json (agent CLI Stop hook) + session-*.json (any other source)
    pending = sorted(bridge.cap.glob("cc-*.json")) + sorted(bridge.cap.glob("session-*.json"))
    if not pending:
        return 0
    seen = _captured_set(bridge)
    n = 0
    for f in pending:
        # idempotency: claim to .processing first → a racing tick/crash won't reprocess (no glob match)
        proc = f.with_name(f.name + ".processing")
        try:
            f.rename(proc)
        except Exception:
            continue
        try:
            ptr = json.loads(proc.read_text(encoding="utf-8"))
        except Exception:
            proc.rename(bridge.processed / proc.name)
            continue
        tp = Path(ptr.get("transcript_path") or "")
        src = ptr.get("source", "agent-cli")
        cwd = ptr.get("cwd", "")
        sid = str(ptr.get("session_id") or proc.name)
        label = (cwd.rstrip("/").split("/")[-1] or "session")
        if tp and tp.exists() and not _cold(tp):
            proc.rename(f)                             # not cold yet → put it back
            continue

        gate_text = _extract_for_gate(tp) if (tp and tp.exists()) else ""
        convo = _extract_text(tp) if (tp and tp.exists()) else ""
        chash = _h(gate_text or convo)                 # F8: content fingerprint

        if f"{sid}\t{chash}" in seen:                  # F8: exact match → true duplicate, skip
            proc.rename(bridge.processed / proc.name)
            continue
        resume = any(line.startswith(sid + "\t") for line in seen)  # same sid, new hash = resume segment

        risk = _classify_risk(gate_text, cfg) if gate_text else "internal"
        blocked, why = _distill_gate(gate_text, cfg)
        seg = t(cat, "capture.resume_seg") if resume else ""

        if blocked:                                    # GATE (Article 4): do not distil
            _append(
                cfg,
                topic=t(cat, "capture.topic_gated", src=src, seg=seg, label=label, why=why),
                risk=risk,
                decision=t(cat, "capture.decision_gated", why=why),
                conf=None,
                refs={"source": "auto-capture", "gated": True, "reason": why, "cwd": cwd, "sid": sid},
                human_approved=None, src=src)
            dest = bridge.queue_human / proc.name
        else:
            s = _distill(cfg, convo, label)
            if s and s.get("decision"):
                _append(
                    cfg,
                    topic=t(cat, "capture.topic_distilled", src=src, seg=seg,
                            topic=str(s.get("topic") or label)[:80]),
                    risk=(s.get("risk") if s.get("risk") in ("public", "internal", "pii", "sensitive", "production")
                          else risk),
                    decision=str(s.get("decision"))[:600],
                    conf=(float(s["confidence"]) if isinstance(s.get("confidence"), (int, float))
                          else None),
                    refs={"source": "auto-capture", "cwd": cwd, "sid": sid, "refs": s.get("refs", [])},
                    human_approved=None, src=src)
            else:                                      # F4: skeleton — the first request is MASKED
                _append(
                    cfg,
                    topic=t(cat, "capture.topic_skeleton", src=src, seg=seg, label=label),
                    risk=risk,
                    decision=t(cat, "capture.decision_skeleton",
                               first=_mask(_first_user(convo), _secret_patterns())[:160]),
                    conf=None,
                    refs={"source": "auto-capture-skeleton", "cwd": cwd, "sid": sid},
                    human_approved=None, src=src)
            dest = bridge.processed / proc.name
        _mark_captured(bridge, sid, chash)             # F8: only AFTER _append COMMIT
        seen.add(f"{sid}\t{chash}")                    # F8: dedup a second identical pointer this tick
        try:
            proc.rename(dest)
        except Exception:
            pass
        n += 1
    return n


# ----------------------------------------------------------------- DB snapshot (F6)
def backup_db(cfg: Config | None = None) -> str:
    """F6: CHECKPOINT (flush WAL into the main file) → copy single file to tmp → atomic replace.
    The tick runs single-instance (flock) and the Stop hook never writes the DB → consistent snapshot."""
    import shutil
    cfg = cfg or load_config()
    db = cfg.db_path()
    if not db.exists():
        return ""
    backup_dir = _backup_dir(cfg)
    backup_dir.mkdir(parents=True, exist_ok=True)
    try:
        c = duckdb.connect(str(db))
        c.execute("CHECKPOINT")
        c.close()
    except Exception:
        return ""
    day = datetime.now().strftime("%Y%m%d")
    dst = backup_dir / f"council-{day}.duckdb"
    tmp = backup_dir / f".council-{day}.duckdb.tmp"
    try:
        shutil.copy2(db, tmp)
        os.replace(tmp, dst)                           # atomic
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        return ""
    for old in sorted(backup_dir.glob("council-*.duckdb"))[:-KEEP_BACKUPS]:
        try:
            old.unlink()
        except Exception:
            pass
    return str(dst)


# ----------------------------------------------------------------- F5: recall cache (tick writes)
def write_recall_cache(cfg: Config | None = None) -> None:
    """Write the latest-state summary ATOMICALLY + 0600 at the end of a tick. A SessionStart
    hook just cats it (no DB access). Inert when the bridge is not configured."""
    cfg = cfg or load_config()
    bridge = _Bridge(cfg)
    if not bridge.active:
        return
    db = cfg.db_path()
    if not db.exists():
        return
    try:
        con = duckdb.connect(str(db), read_only=True)
        rows = con.execute(
            "SELECT started_at, risk_profile, substr(topic,1,72) FROM council_sessions "
            "ORDER BY started_at DESC LIMIT 8").fetchall()
        con.close()
    except Exception:
        return
    cat = load_catalog(cfg)
    lines = [t(cat, "capture.recall_title")]
    for r in rows:
        lines.append(t(cat, "capture.recall_item", ts=str(r[0])[:16], risk=r[1], topic=r[2]))
    lines.append(t(cat, "capture.recall_footer"))
    out = {"hookSpecificOutput": {"hookEventName": "SessionStart",
                                  "additionalContext": "\n".join(lines)}}
    try:
        tmp = bridge.recall_cache.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, bridge.recall_cache)           # atomic (no half-written file is read)
    except Exception:
        pass


# ----------------------------------------------------------------- hook: write pointer (Stop)
def hook(cfg: Config | None = None) -> None:
    """Stop-hook entry: drop a capture pointer. Inert unless autocapture is enabled with a bridge."""
    cfg = cfg or load_config()
    bridge = _Bridge(cfg)
    if not bridge.active:
        return
    try:
        d = json.loads(sys.stdin.read() or "{}")
    except Exception:
        d = {}
    tp = d.get("transcript_path") or ""
    if not tp:
        return                                         # no transcript → nothing to capture
    sid = str(d.get("session_id") or Path(tp).stem or "unknown")
    bridge.cap.mkdir(parents=True, exist_ok=True)
    (bridge.cap / f"cc-{sid}.json").write_text(json.dumps({
        "source": "claude-code", "session_id": sid,
        "transcript_path": tp, "cwd": d.get("cwd") or "", "ts": _now(),
    }, ensure_ascii=False), encoding="utf-8")


def recall(cfg: Config | None = None) -> None:
    """Fallback: cat the recall cache (normally a recall hook cats it directly)."""
    cfg = cfg or load_config()
    bridge = _Bridge(cfg)
    if not bridge.active:
        return
    try:
        sys.stdout.write(bridge.recall_cache.read_text(encoding="utf-8"))
    except Exception:
        pass


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    cmd = argv[0] if argv else "process"
    cfg = load_config()
    cat = load_catalog(cfg)
    if cmd == "hook":
        hook(cfg)
    elif cmd == "recall":
        recall(cfg)
    elif cmd == "process":
        print(t(cat, "capture.cli.processed", count=process_capture(cfg)))
    elif cmd == "backup":
        print(t(cat, "capture.cli.backup", path=backup_db(cfg)))
    elif cmd == "recall-cache":
        write_recall_cache(cfg)
        print(t(cat, "capture.cli.recall_cache_written"))


if __name__ == "__main__":
    main()
