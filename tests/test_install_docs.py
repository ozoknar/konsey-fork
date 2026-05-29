"""Guard tests for the install script and the human-facing docs.

These cover the deliverables of the docs/install workflow (README{,.tr}.md,
install.sh, CHANGELOG.md, KNOWN_ISSUES.md) — not the Python core. They assert
two invariants that are easy to silently break:

1. ``install.sh`` stays a syntactically valid POSIX shell script, and its
   "newer than the CI baseline" note fires *only* for Python minor > 12 — i.e.
   it is informational and never gates the >= 3.12 floor.
2. The docs do not over-claim (no stale "documented stubs / being ported in
   Phase 2" wording) and do not leak machine-specific identity (no real owner
   handle baked into the changelog links — the portable ``OWNER`` placeholder
   is used, matching pyproject).
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
INSTALL_SH = REPO / "install.sh"
README = REPO / "README.md"
README_TR = REPO / "README.tr.md"
CHANGELOG = REPO / "CHANGELOG.md"
KNOWN_ISSUES = REPO / "KNOWN_ISSUES.md"


def _sh() -> str | None:
    return shutil.which("sh")


@pytest.mark.skipif(_sh() is None, reason="no POSIX sh on PATH")
def test_install_sh_is_valid_posix() -> None:
    """``sh -n`` parses the installer without error (no syntax regression)."""
    proc = subprocess.run([_sh(), "-n", str(INSTALL_SH)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def test_install_sh_version_note_is_informational_not_a_gate() -> None:
    """The version note must be a NOTE, never a second gate.

    Replicates the branch logic from install.sh: the note fires for minor > 12
    only, and the hard floor (die on < 3.12) is unchanged.
    """
    text = INSTALL_SH.read_text()
    # The informational note exists and names the CI baseline.
    assert "newer than the CI baseline" in text
    assert "PYMINOR" in text and 'if [ "$PYMINOR" -gt 12 ]' in text
    # The note must NOT call die()/exit on the > 12 path (would break 3.14).
    note_start = text.index('if [ "$PYMINOR" -gt 12 ]')
    note_block = text[note_start: note_start + 400]
    assert "die" not in note_block and "exit 1" not in note_block
    # The real floor is still a die() on < 3.12.
    assert "Python >= 3.12 is required" in text

    # Mirror the shell comparison in Python for representative versions.
    def fires(minor: int) -> bool:
        return minor > 12

    assert fires(13) and fires(14)
    assert not fires(12)
    assert not fires(11)  # 3.11 is rejected by the floor, never reaches the note


def test_readmes_do_not_over_claim() -> None:
    """No stale "scaffold / documented stubs / being ported" wording remains."""
    for path in (README, README_TR):
        body = path.read_text()
        assert "documented stubs" not in body, f"{path.name} still says 'documented stubs'"
        assert "being ported in Phase 2" not in body, f"{path.name}: stale 'being ported'"
        assert "Faz 2'de taşınıyor" not in body, f"{path.name}: stale TR 'being ported'"
        # The maturity section should cite the verified test count, not silence.
        assert "92/92" in body, f"{path.name}: missing 92/92 test evidence"


def test_readmes_link_existing_docs_not_phase2_placeholders() -> None:
    """SECURITY.md and CONTRIBUTING.md exist now; the old "(Phase 2)" tags are gone."""
    assert (REPO / "SECURITY.md").exists()
    assert (REPO / "CONTRIBUTING.md").exists()
    for path in (README, README_TR):
        body = path.read_text()
        assert "SECURITY.md` (Phase 2)" not in body
        assert "Phase 2 `CONTRIBUTING.md`" not in body
        assert "SECURITY.md` (Faz 2)" not in body


def test_changelog_is_portable_and_keepachangelog() -> None:
    """CHANGELOG follows Keep a Changelog and leaks no machine-specific identity."""
    body = CHANGELOG.read_text()
    assert "Keep a Changelog" in body
    assert "[0.1.0]" in body and "[Unreleased]" in body
    # Portable link target — same placeholder as pyproject, no real owner handle.
    assert "github.com/OWNER/konsey" in body
    assert "drhakankilic" not in body
    # The MVP entry must cite its evidence honestly.
    assert "92/92" in body


def test_known_issues_keeps_live_daemon_open_and_records_resolved() -> None:
    """systemd/Windows live-daemon stays open; resolved items are recorded with a Resolved section."""
    body = KNOWN_ISSUES.read_text()
    assert "systemd" in body and "Windows Task Scheduler" in body
    assert "Resolved in Phase 2" in body
    # Linux cron round-trip is recorded as done (not still listed as unvalidated).
    assert "cron install/uninstall round-trip" in body
