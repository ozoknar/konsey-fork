"""Repo-scoped self-improvement loop (opt-in, ``cfg.learn_from_repo``, default OFF).

Konsey's own 9-state graph ends at a MEMORY node that — before this module — did
nothing but close the audit session: no lesson was ever extracted, nothing fed back
into a future run. Meanwhile most of the operator's own repos already keep a
per-project "lessons learned" file (the dominant convention observed across
``~/dev/*`` is ``.prometheus/LESSONS.md``; a handful of variants exist —
``LESSONS.md``/``KONSEY_LESSONS.md`` at the repo root, or a ``lrn/`` directory of
dated files). This module is the bridge:

  * ``discover_lessons`` — READ. Scans ``cfg.council_home`` for the best-matching
    existing lessons file/dir and returns a short, prompt-ready excerpt (most recent
    entries first, truncated) so PLAN can avoid repeating a documented mistake. Pure
    read; returns "" when nothing is found — never raises, never creates a file.
  * ``record_lesson`` — WRITE. Appends ONE new dated entry to
    ``<council_home>/.prometheus/LESSONS.md`` (creating the file with the repo's own
    header convention if it does not exist yet). Callers gate this on
    ``cfg.learn_from_repo`` AND ``decision.human_required`` (Article 7: only a
    genuinely contested/escalated run is lesson-worthy) — this module itself does not
    re-check those; it only knows how to discover and how to append.

Deliberately does NOT touch the append-only audit DB (Article 10/11) — a lessons file
is a human-readable, human-editable document living in the TARGET repo, a different
trust boundary from konsey's own DuckDB.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .i18n import t

# Discovery order mirrors what was actually found scanning the operator's own repos:
# .prometheus/LESSONS.md is the dominant convention (most `~/dev/*` projects), the
# repo-root variants and `lrn/` are real but less common fallbacks. First match wins.
_FILE_CANDIDATES: tuple[str, ...] = (
    ".prometheus/LESSONS.md",
    "LESSONS.md",
    "KONSEY_LESSONS.md",
)
_DIR_CANDIDATES: tuple[str, ...] = ("lrn",)

_WRITE_TARGET = ".prometheus/LESSONS.md"   # record_lesson always writes here (Article 2.3:
                                            # one predictable target, not a guessed one)
_MAX_EXCERPT_CHARS = 2000                  # keeps the PLAN prompt bounded regardless of file size


def _read_text(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def discover_lessons(council_home: Path) -> str:
    """Return a prompt-ready excerpt of the target repo's existing lessons, or "".

    Read-only: never creates or modifies anything. Tries the known file conventions in
    order, then a ``lrn/`` directory of dated files (most-recently-modified first).
    The excerpt is the TAIL of the content (most lessons files are append-only, so the
    newest entries are at the end) truncated to ``_MAX_EXCERPT_CHARS``."""
    for rel in _FILE_CANDIDATES:
        p = council_home / rel
        if p.is_file():
            text = _read_text(p).strip()
            if text:
                return text[-_MAX_EXCERPT_CHARS:]

    for rel in _DIR_CANDIDATES:
        d = council_home / rel
        if d.is_dir():
            try:
                files = sorted((f for f in d.glob("*.md") if f.is_file()),
                               key=lambda f: f.stat().st_mtime, reverse=True)
            except OSError:
                files = []
            if files:
                chunks = []
                budget = _MAX_EXCERPT_CHARS
                for f in files:
                    text = _read_text(f).strip()
                    if not text:
                        continue
                    chunk = f"### {f.name}\n{text}"[:budget]
                    chunks.append(chunk)
                    budget -= len(chunk)
                    if budget <= 0:
                        break
                if chunks:
                    return "\n\n".join(chunks)
    return ""


def record_lesson(
    council_home: Path,
    *,
    task: str,
    rationale: str,
    confidence: float,
    global_candidate: bool,
    catalog=None,
) -> Path | None:
    """Append one dated lesson entry to ``<council_home>/.prometheus/LESSONS.md``.

    Creates the file (and ``.prometheus/``) with a minimal header, in ``catalog``'s
    locale, if it does not exist yet. Side-effect-free on failure: returns None instead
    of raising if the path cannot be written (e.g. read-only filesystem) — a lesson
    that fails to record must never crash the run that surfaced it (Md.2.7)."""
    target = council_home / _WRITE_TARGET
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_text(t(catalog, "learn.file_header"), encoding="utf-8")
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        topic = " ".join(task.split())[:80]
        candidate_label = t(catalog, "learn.global_yes" if global_candidate else "learn.global_no")
        entry = f"- {date}, {topic}: {rationale} (confidence={confidence:.2f}). {candidate_label}\n"
        with target.open("a", encoding="utf-8") as f:
            f.write(entry)
        return target
    except OSError:
        return None
