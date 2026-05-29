"""Dispatch + scheduler (Constitution Article 14) — opt-in autonomy, default inert.

- inbox→outbox folder bridge: drop a task file → council runs → result + notification.
- scheduled jobs (``<bridge>/scheduled/*.json``): a scheduler tick fires periodically.
- AUTONOMY CEILING (Article 14 / 5.3): only ``<= internal`` finishes unattended; everything
  else (pii / sensitive / production / secret-bearing) goes to the human queue.

Run: ``python -m council.dispatch tick``    (the OS scheduler calls this)
     ``python -m council.dispatch inbox``   (single inbox pass)

Everything machine-specific arrives through ``Config``:
  * the bridge root is ``cfg.bridge_dir`` (``None`` → the whole module is inert);
  * desktop notifications go through ``platform.get_notifier(cfg.notifier)`` (the F9
    AppleScript-injection fix lives in that backend, not here);
  * the autonomy ceiling ``ALLOWED_AUTO`` is a fixed constant a config cannot widen.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from .config import Config, load_config
from .platform import get_notifier

# Autonomy ceiling (Article 14 / 5.3). FIXED — no config may widen it. Anything above
# this, or any blocked preflight, is routed to queue-human regardless of profile.
ALLOWED_AUTO = {"public", "internal"}


# ----------------------------------------------------------------------------- bridge paths
class _Bridge:
    """Resolved dispatch layout under ``cfg.bridge_dir``. ``active`` is False when no
    bridge is configured → every dispatch entry point becomes inert (no dirs created)."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.active = cfg.bridge_dir is not None
        root = cfg.bridge_dir
        if root is None:
            # placeholders only; never touched while inert (active is False).
            self.inbox = self.outbox = self.queue_human = self.processed = Path(os.devnull)
            self.sched_dir = self.state = Path(os.devnull)
            return
        self.inbox = root / "inbox"
        self.outbox = root / "outbox"
        self.queue_human = root / "queue-human"
        self.processed = root / "processed"
        self.sched_dir = root / "scheduled"
        self.state = self.sched_dir / ".state.json"

    def ensure(self) -> None:
        if not self.active:
            return
        for d in (self.inbox, self.outbox, self.queue_human, self.processed, self.sched_dir):
            d.mkdir(parents=True, exist_ok=True)


# ----------------------------------------------------------------------------- small helpers
def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower())[:40].strip("-") or "task"


def _ts() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _notify(cfg: Config, title: str, msg: str) -> None:
    """Best-effort desktop notification via the configured backend (default NullNotifier).
    The backend escapes its own arguments (F9) and never raises."""
    try:
        get_notifier(cfg.notifier).notify(title, msg)
    except Exception:
        pass  # notification is optional; failure never stops the flow


def _preflight(task: str, hint: str, cfg: Config | None = None):
    """Defensive bridge to gateway.preflight. Returns the GatewayResult, or a fail-SAFE
    shim that forces queue-human when the gateway is unavailable (never auto-runs an
    unclassified task). ``cfg`` is forwarded so the project risk registry is honoured."""
    try:
        from .gateway import preflight  # type: ignore[attr-defined]
        try:
            return preflight(task, hint, cfg)
        except TypeError:
            return preflight(task, hint)   # tolerate an older signature without cfg
    except Exception:
        class _Shim:
            risk = "production"        # fail-safe: unknown classification → above the ceiling
            blocked = True
            block_reason = "gateway unavailable (Phase-2 stub) — refusing autonomous run"
            notes: list[str] = []
        return _Shim()


# ----------------------------------------------------------------------------- gate abstraction
class AutoGate:
    """Runs ``<= internal`` tasks unattended (Article 5.3). Never reached for higher risk —
    the security invariant in ``_decide_gate`` keeps prod/sensitive/blocked work on QueueGate."""

    name = "auto"

    def allows(self, gw) -> bool:
        return (not getattr(gw, "blocked", False)) and getattr(gw, "risk", "") in ALLOWED_AUTO


class QueueGate:
    """Routes a task to ``queue-human/`` for explicit human review. The fallback for
    everything the AutoGate does not allow. (InteractiveGate is the CLI's job, not dispatch's.)"""

    name = "queue-human"

    def allows(self, gw) -> bool:
        return False


def _decide_gate(gw) -> object:
    """Security invariant (config-non-bypassable, Article 5.3): blocked, or any risk above
    ``ALLOWED_AUTO``, is ALWAYS >= QueueGate. Only clean ``public|internal`` reaches AutoGate."""
    if getattr(gw, "blocked", False) or getattr(gw, "risk", "") not in ALLOWED_AUTO:
        return QueueGate()
    return AutoGate()


# ----------------------------------------------------------------------------- task running
def _parse_task(path: Path) -> tuple[str, str]:
    raw = path.read_text(encoding="utf-8", errors="replace").strip()
    if path.suffix == ".json":
        try:
            d = json.loads(raw)
            # accept both the example schema ("project") and the legacy key ("project_hint")
            return d.get("task", "").strip(), (d.get("project") or d.get("project_hint") or "")
        except Exception:
            pass
    return raw, ""


def _run_graph(task: str, hint: str, cfg: Config):
    """Defensive bridge to graph.build(cfg).invoke. Returns the final state dict, or a
    minimal dict when the graph is unavailable (so dispatch can be exercised in isolation)."""
    try:
        from .graph import build  # type: ignore[attr-defined]
        try:
            final = build(cfg).invoke({"task": task, "project_hint": hint},
                                      config={"recursion_limit": 60})
        except TypeError:
            # tolerate a build() that takes no cfg argument
            final = build().invoke({"task": task, "project_hint": hint},
                                   config={"recursion_limit": 60})
        return final or {}
    except Exception as e:
        return {"report": f"(graph unavailable: {e})", "decision": {}}


def _run_task(cfg: Config, bridge: _Bridge, task: str, hint: str, origin: str) -> Path:
    """Apply the gate ceiling; run the graph only when the AutoGate allows it, else queue-human."""
    gw = _preflight(task, hint, cfg)
    gate = _decide_gate(gw)
    base = f"{_ts()}-{_slug(task)}"

    if not isinstance(gate, AutoGate):
        reason = getattr(gw, "block_reason", "") or \
            f"risk={getattr(gw, 'risk', '?')} above autonomous ceiling (<= internal)"
        notes = getattr(gw, "notes", [])
        out = bridge.queue_human / f"{base}.md"
        out.write_text(
            "# HUMAN APPROVAL REQUIRED — not run autonomously\n\n"
            f"- task: {task}\n- source: {origin}\n- risk: {getattr(gw, 'risk', '?')}\n"
            f"- reason: {reason}\n- notes: {notes}\n\n"
            "Review and, if appropriate, run interactively with `council run`.\n",
            encoding="utf-8")
        _notify(cfg, "Queued (human approval)", f"{getattr(gw, 'risk', '?')}: {task[:50]}")
        return out

    # autonomous run (<= internal)
    final = _run_graph(task, hint, cfg)
    out = bridge.outbox / f"{base}.md"
    out.write_text((final.get("report") or "(no report)") + f"\n\n---\nsource: {origin}\n",
                   encoding="utf-8")
    dec = final.get("decision", {}) or {}
    _notify(cfg, "Completed",
            f"conf={dec.get('confidence')} approval={'YES' if dec.get('human_required') else 'no'}")
    return out


# ----------------------------------------------------------------------------- inbox + scheduled
def process_inbox(cfg: Config | None = None) -> int:
    cfg = cfg or load_config()
    bridge = _Bridge(cfg)
    if not bridge.active:
        return 0
    bridge.ensure()
    n = 0
    for f in sorted(bridge.inbox.iterdir()):
        if f.is_dir() or f.name.startswith((".", "_")):   # "_"-prefixed = note/help, not a task
            continue
        task, hint = _parse_task(f)
        if not task:
            f.rename(bridge.processed / f.name)
            continue
        _run_task(cfg, bridge, task, hint, origin=f"inbox/{f.name}")
        f.rename(bridge.processed / f"{_ts()}-{f.name}")
        n += 1
    return n


def _load_state(bridge: _Bridge) -> dict:
    if bridge.state.exists():
        try:
            return json.loads(bridge.state.read_text())
        except Exception:
            return {}
    return {}


def run_scheduled(cfg: Config | None = None) -> int:
    """``scheduled/*.json``: {name, task, project|project_hint, every_minutes, enabled}.
    A missing ``every_minutes`` defaults to daily (1440)."""
    cfg = cfg or load_config()
    bridge = _Bridge(cfg)
    if not bridge.active:
        return 0
    bridge.ensure()
    state = _load_state(bridge)
    now = time.time()
    n = 0
    for jf in sorted(bridge.sched_dir.glob("*.json")):
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
        hint = job.get("project") or job.get("project_hint") or ""
        _run_task(cfg, bridge, job.get("task", ""), hint, origin=f"scheduled/{name}")
        state[name] = now
        n += 1
    if n:
        bridge.state.write_text(json.dumps(state, indent=2))
    return n


# ----------------------------------------------------------------------------- tick
def tick(cfg: Config | None = None) -> None:
    """Single periodic pass: inbox → scheduled → autocapture distil + DB snapshot + recall cache.
    Single-instance via flock (POSIX); on platforms without ``fcntl`` it degrades to no lock."""
    cfg = cfg or load_config()
    bridge = _Bridge(cfg)
    if not bridge.active:
        print(f"[{datetime.now():%Y-%m-%d %H:%M}] tick inert (no bridge_dir configured)")
        return
    bridge.ensure()

    lockf = None
    try:
        import fcntl
        lockf = open(bridge.sched_dir / ".tick.lock", "w")   # single-instance: no double-process
        try:
            fcntl.flock(lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(f"[{datetime.now():%Y-%m-%d %H:%M}] tick skipped (another tick running)")
            lockf.close()
            return
    except ImportError:
        lockf = None   # non-POSIX (Windows) — the OS scheduler should not overlap ticks anyway

    try:
        a = process_inbox(cfg)
        b = run_scheduled(cfg)
        # autocapture distillation + daily DB snapshot + recall cache (Article 13).
        # Inert when autocapture is disabled — process_capture/backup_db short-circuit themselves.
        try:
            from .capture import backup_db, process_capture, write_recall_cache
            c: object = process_capture(cfg)
            backup_db(cfg)
            write_recall_cache(cfg)
        except Exception as e:
            c = f"err:{e}"
        print(f"[{datetime.now():%Y-%m-%d %H:%M}] inbox={a} scheduled={b} capture={c}")
    finally:
        if lockf is not None:
            try:
                import fcntl
                fcntl.flock(lockf, fcntl.LOCK_UN)
            except Exception:
                pass
            lockf.close()


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    cmd = argv[0] if argv else "tick"
    cfg = load_config()
    {
        "tick": lambda: tick(cfg),
        "inbox": lambda: print("inbox:", process_inbox(cfg)),
        "scheduled": lambda: print("scheduled:", run_scheduled(cfg)),
    }.get(cmd, lambda: tick(cfg))()


if __name__ == "__main__":
    main()
