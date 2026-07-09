"""Repo-scoped self-improvement loop — council.learn (opt-in, learn_from_repo).

Evidence > consensus: real filesystem reads/writes against ``tmp_path``, no mocks.
Covers the two halves independently: ``discover_lessons`` (read, never writes) and
``record_lesson`` (write, always targets ``.prometheus/LESSONS.md``). Graph wiring
(preflight injects the excerpt, memory gates the write on human_required) is covered
in ``tests/test_graph_orchestration.py``.
"""
from __future__ import annotations

from pathlib import Path

from council.i18n import load_catalog
from council.learn import discover_lessons, record_lesson


def _touch(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


# --------------------------------------------------------------------------- #
# discover_lessons — read-only, never creates anything                         #
# --------------------------------------------------------------------------- #

def test_discover_returns_empty_when_nothing_exists(tmp_path):
    assert discover_lessons(tmp_path) == ""
    # Read-only contract: nothing was created as a side effect.
    assert list(tmp_path.iterdir()) == []


def test_discover_prefers_prometheus_lessons_over_root(tmp_path):
    _touch(tmp_path / "LESSONS.md", "root lessons")
    _touch(tmp_path / ".prometheus" / "LESSONS.md", "prometheus lessons")
    assert discover_lessons(tmp_path) == "prometheus lessons"


def test_discover_falls_back_to_root_lessons_md(tmp_path):
    _touch(tmp_path / "LESSONS.md", "root lessons only")
    assert discover_lessons(tmp_path) == "root lessons only"


def test_discover_falls_back_to_konsey_lessons_md(tmp_path):
    _touch(tmp_path / "KONSEY_LESSONS.md", "konsey-flavored lessons")
    assert discover_lessons(tmp_path) == "konsey-flavored lessons"


def test_discover_falls_back_to_lrn_directory(tmp_path):
    _touch(tmp_path / "lrn" / "LRN-20260101-first.md", "first lesson")
    excerpt = discover_lessons(tmp_path)
    assert "first lesson" in excerpt
    assert "LRN-20260101-first.md" in excerpt


def test_discover_truncates_to_the_tail(tmp_path):
    huge = "x" * 5000
    _touch(tmp_path / "LESSONS.md", huge)
    excerpt = discover_lessons(tmp_path)
    assert len(excerpt) <= 2000
    assert excerpt == huge[-len(excerpt):]   # tail, not head — newest entries are at the end


def test_discover_ignores_empty_file_and_falls_through(tmp_path):
    _touch(tmp_path / ".prometheus" / "LESSONS.md", "   ")   # whitespace-only
    _touch(tmp_path / "KONSEY_LESSONS.md", "real content here")
    assert discover_lessons(tmp_path) == "real content here"


# --------------------------------------------------------------------------- #
# record_lesson — write, always .prometheus/LESSONS.md, never raises           #
# --------------------------------------------------------------------------- #

def test_record_creates_file_with_header_when_missing(tmp_path):
    cat = load_catalog("en")
    path = record_lesson(tmp_path, task="tidy the docs", rationale="risk=production",
                         confidence=0.9, global_candidate=False, catalog=cat)
    assert path == tmp_path / ".prometheus" / "LESSONS.md"
    text = path.read_text(encoding="utf-8")
    assert "Repo Lessons" in text
    assert "tidy the docs" in text
    assert "risk=production" in text
    assert "confidence=0.90" in text
    assert "Global candidate: no" in text


def test_record_appends_without_rewriting_existing_header(tmp_path):
    cat = load_catalog("en")
    existing = "# My Own Header\n\n## Lessons\n\n- 2026-01-01, old entry: something.\n"
    _touch(tmp_path / ".prometheus" / "LESSONS.md", existing)
    path = record_lesson(tmp_path, task="second run", rationale="split verdict",
                         confidence=0.7, global_candidate=True, catalog=cat)
    text = path.read_text(encoding="utf-8")
    assert text.startswith(existing)          # untouched
    assert "second run" in text
    assert "Global candidate: yes" in text


def test_record_uses_locale_labels(tmp_path):
    cat = load_catalog("tr")
    path = record_lesson(tmp_path, task="görev", rationale="gerekçe",
                         confidence=0.5, global_candidate=True, catalog=cat)
    text = path.read_text(encoding="utf-8")
    assert "Global aday: evet" in text


def test_record_returns_none_instead_of_raising_on_unwritable_path(tmp_path):
    # council_home itself is a FILE, not a dir — mkdir(parents=True) must fail cleanly.
    blocked = tmp_path / "not_a_dir"
    blocked.write_text("x", encoding="utf-8")
    result = record_lesson(blocked, task="t", rationale="r", confidence=0.5,
                           global_candidate=False, catalog=None)
    assert result is None
