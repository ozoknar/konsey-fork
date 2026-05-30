"""S8 — honesty pass: the docs match reality (Constitution Art. 2.1, no unverified
'it works' claims). These guard against the specific over-claims a whole-project council
re-evaluation surfaced (Codex VERDICT: OVERCLAIMS, maturity=alpha) from creeping back:
the stale "92/92" current-count, a missing alpha label, and a missing honest statement of
what is / isn't distributed yet.

Historical "92/92" records (CHANGELOG [0.1.0], the Resolved sections) are intentionally
NOT touched — they accurately describe the past; only PRESENT-TENSE claims are guarded.
"""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
README = REPO / "README.md"
README_TR = REPO / "README.tr.md"
KNOWN_ISSUES = REPO / "KNOWN_ISSUES.md"


def test_readmes_do_not_present_stale_92_as_the_current_count():
    en = README.read_text(encoding="utf-8")
    tr = README_TR.read_text(encoding="utf-8")
    assert "Test evidence: 92/92" not in en, "README still presents 92/92 as the current count"
    assert "92/92 geçer" not in tr, "README.tr still presents 92/92 as the current count"
    # the present-tense KNOWN_ISSUES header must not claim 92/92 as the live count
    header = "\n".join(KNOWN_ISSUES.read_text(encoding="utf-8").splitlines()[:8])
    assert "tested (92/92" not in header, "KNOWN_ISSUES header still claims 92/92 as current"


def test_maturity_is_honestly_labelled_alpha():
    for path in (README, README_TR):
        body = path.read_text(encoding="utf-8").lower()
        assert "alpha" in body, f"{path.name}: maturity not honestly labelled alpha"
    # the live count is sourced from pytest, not a frozen number
    assert "pytest" in README.read_text(encoding="utf-8")


def test_core_value_honesty_callout_present():
    en = README.read_text(encoding="utf-8")
    # honestly distinguishes the distributed DECISION (loop, text-only) from opt-in work
    assert "does not shell out" in en
    assert "opt-in" in en
    assert "Phase 2" in en          # fan-out / graph integration deferred
