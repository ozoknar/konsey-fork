"""S3 — installer UX kit + crash-resistance, proven by driving the REAL install.sh.

Evidence > consensus: every test runs the actual `install.sh` in its `KONSEY_UI_SELFTEST`
mode (which detects capabilities, exercises each UX primitive, then exits WITHOUT
installing). That proves the kit degrades correctly across the TTY / NO_COLOR /
FORCE_COLOR / locale matrix and that the failure trap fires — without touching the
machine. The subprocess pipe makes stdout a non-TTY, so the spinner/animation paths
stay off here by construction (matching CI/`curl | sh`).
"""
from __future__ import annotations

import os
import pty
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
INSTALL_SH = REPO / "install.sh"
ESC = "\x1b"  # an ANSI escape byte — present iff color was emitted

pytestmark = pytest.mark.skipif(shutil.which("sh") is None, reason="no POSIX sh on PATH")


def _run_selftest(mode: str = "1", **extra_env) -> subprocess.CompletedProcess:
    """Run install.sh in self-test mode with a CLEAN env (only PATH + the vars we
    pin), so the host's TERM/NO_COLOR/LANG can't leak into the result."""
    env = {"PATH": os.environ.get("PATH", ""), "KONSEY_UI_SELFTEST": mode}
    env.update({k: v for k, v in extra_env.items() if v is not None})
    return subprocess.run(
        [shutil.which("sh"), str(INSTALL_SH)],
        capture_output=True, text=True, cwd=str(REPO), env=env,
    )


def _caps(stdout: str) -> dict[str, str]:
    """Parse the first 'UI_COLOR=.. UI_UNICODE=.. UI_TTY=.. UI_WIDTH=..' line."""
    line = stdout.strip().splitlines()[0]
    return dict(tok.split("=", 1) for tok in line.split())


# --------------------------------------------------------------------------- #
# capability detection degrades correctly                                      #
# --------------------------------------------------------------------------- #

def test_plain_when_no_color_and_piped():
    # NO_COLOR + a pipe (non-TTY) → no escapes, ASCII glyphs, the box is ASCII.
    p = _run_selftest(NO_COLOR="1")
    assert p.returncode == 0
    caps = _caps(p.stdout)
    assert caps["UI_COLOR"] == "0"
    assert caps["UI_TTY"] == "0"           # subprocess pipe is never a TTY
    assert ESC not in p.stdout             # zero ANSI bytes
    assert "[OK]" in p.stdout              # ASCII success glyph on stdout
    assert "!!" in p.stderr                # warn() writes to stderr by design
    assert "+--" in p.stdout               # ASCII box border, not unicode ╭─


def test_color_when_forced_even_off_tty():
    # FORCE_COLOR forces color despite the non-TTY pipe (force-color.org contract).
    p = _run_selftest(FORCE_COLOR="1")
    assert p.returncode == 0
    assert _caps(p.stdout)["UI_COLOR"] == "1"
    assert ESC in p.stdout                  # ANSI escapes present


def test_no_color_vetoes_force_color():
    # NO_COLOR is an absolute veto and must win over FORCE_COLOR.
    p = _run_selftest(NO_COLOR="1", FORCE_COLOR="1")
    assert _caps(p.stdout)["UI_COLOR"] == "0"
    assert ESC not in p.stdout


def test_konsey_no_ui_forces_plain():
    # The explicit KONSEY_NO_UI escape hatch beats FORCE_COLOR.
    p = _run_selftest(FORCE_COLOR="1", KONSEY_NO_UI="1")
    caps = _caps(p.stdout)
    assert caps["UI_COLOR"] == "0" and caps["UI_UNICODE"] == "0"
    assert ESC not in p.stdout


def test_unicode_off_without_utf8_locale():
    # Color on, but a non-UTF-8 locale → ASCII glyphs (no mojibake risk).
    p = _run_selftest(FORCE_COLOR="1", LANG="C", LC_ALL="C")
    caps = _caps(p.stdout)
    assert caps["UI_UNICODE"] == "0"
    assert "[OK]" in p.stdout               # ASCII glyph, not ✔


# --------------------------------------------------------------------------- #
# CI is non-interactive even on a real TTY (Codex S3 finding)                   #
# --------------------------------------------------------------------------- #

def _run_selftest_on_pty(mode: str = "1", **extra_env) -> str:
    """Run install.sh self-test with stdout wired to a REAL pty, so `[ -t 1 ]` is
    true — the only way to exercise the TTY path (and the CI-overrides-TTY guard)
    from a test. stderr is discarded; returns the decoded stdout."""
    env = {"PATH": os.environ.get("PATH", ""), "KONSEY_UI_SELFTEST": mode}
    env.update({k: v for k, v in extra_env.items() if v is not None})
    master, slave = pty.openpty()
    proc = subprocess.Popen(
        [shutil.which("sh"), str(INSTALL_SH)],
        stdout=slave, stderr=subprocess.DEVNULL, cwd=str(REPO), env=env,
    )
    os.close(slave)
    out = b""
    try:
        while True:
            try:
                chunk = os.read(master, 1024)
            except OSError:                 # EIO once the child closes the slave end
                break
            if not chunk:
                break
            out += chunk
    finally:
        os.close(master)
    proc.wait()
    return out.decode(errors="replace")


def test_pty_is_seen_as_a_tty_without_ci():
    # Sanity: a real pty must register as a TTY — validates the harness so the
    # CI test below is meaningful (it proves CI *overrides* a genuine TTY).
    caps = _caps(_run_selftest_on_pty())
    assert caps["UI_TTY"] == "1"


def test_ci_forces_non_interactive_even_on_a_tty():
    # The Codex finding: CI=1 on a TTY must NOT animate/colour by default — its
    # logs capture \r spinner frames as noise. CI overrides TTY detection.
    out = _run_selftest_on_pty(CI="1")
    assert _caps(out)["UI_TTY"] == "0"      # CI beats a real TTY
    assert ESC not in out                    # → auto-colour off → plain (no FORCE_COLOR set)


def test_ci_still_honours_explicit_force_color():
    # CI suppresses AUTO colour, but an explicit FORCE_COLOR still opts back in
    # (e.g. GitHub Actions renders ANSI) — the override is about animation, not a veto.
    out = _run_selftest_on_pty(CI="1", FORCE_COLOR="1")
    assert _caps(out)["UI_COLOR"] == "1"
    assert ESC in out


# --------------------------------------------------------------------------- #
# crash-resistance: the failure trap                                           #
# --------------------------------------------------------------------------- #

def test_failure_trap_prints_box_names_stage_and_exits_nonzero():
    # `=die` forces a failure mid-"stage"; the EXIT trap must print a friendly,
    # stage-named summary and the process must report a non-zero code.
    p = _run_selftest(mode="die", NO_COLOR="1")
    assert p.returncode != 0
    blob = p.stdout + p.stderr
    assert "Install did not complete" in blob
    assert "selftest stage" in blob          # CURRENT_STEP surfaced
    assert "safe to run again" in blob        # the actionable next step


def test_failure_trap_summary_goes_to_stderr():
    # The summary box must not pollute stdout (so `... | grep` on stdout is clean).
    p = _run_selftest(mode="die", NO_COLOR="1")
    assert "Install did not complete" in p.stderr
    assert "Install did not complete" not in p.stdout


# --------------------------------------------------------------------------- #
# POSIX-sh hygiene: still parses under sh AND (when present) dash               #
# --------------------------------------------------------------------------- #

def test_install_sh_parses_under_dash_if_available():
    dash = shutil.which("dash")
    if dash is None:
        pytest.skip("dash not installed")
    proc = subprocess.run([dash, "-n", str(INSTALL_SH)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def test_no_bash_only_constructs():
    """Guard against the classic bash-isms that break under dash/sh.

    Scan CODE only (drop full-line comments) so the design comments that *name*
    these anti-patterns ("we deliberately do NOT use `set -o pipefail`") don't trip it.
    """
    code = "\n".join(
        ln for ln in INSTALL_SH.read_text().splitlines()
        if not ln.lstrip().startswith("#")
    )
    assert "[[" not in code, "found bash-only [[ ]] test"
    assert "pipefail" not in code, "found bash-only set -o pipefail"
    assert "trap ERR" not in code, "found bash-only trap ERR"
