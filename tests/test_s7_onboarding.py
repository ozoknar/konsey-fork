"""S7 — onboarding fluidity & honesty: the wizard is GUIDED (welcome, preambles,
answer echoes, a confident close, surfaced audit trail) without becoming verbose on
--quick / non-TTY, and the new copy keeps en/tr parity.

Evidence > consensus: real cmd_init calls with _ask/_is_tty stubbed to drive the
interactive path, asserting the actual rendered strings.
"""
from __future__ import annotations

import argparse

from council import i18n
from council.cli import cmd_init


def _run_init(tmp_path, monkeypatch, capsys, *, quick):
    monkeypatch.setenv("KONSEY_HOME", str(tmp_path))
    monkeypatch.setenv("KONSEY_DATA_HOME", str(tmp_path / "data"))
    for v in ("COUNCIL_HOME", "COUNCIL_CONFIG", "KONSEY_CONFIG",
              "LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE", "KONSEY_LOCALE"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setattr("council.cli._is_tty", lambda: True)            # stay interactive
    monkeypatch.setattr("council.cli._ask", lambda prompt, default="": default)  # accept defaults
    rc = cmd_init(argparse.Namespace(quick=quick, reconfigure=False, locale="en", preset=None))
    return rc, capsys.readouterr().out


def test_interactive_init_is_guided(tmp_path, monkeypatch, capsys):
    rc, out = _run_init(tmp_path, monkeypatch, capsys, quick=False)
    assert rc == 0
    assert "Welcome to konsey" in out               # one-screen welcome (what this is)
    assert "how much konsey may touch" in out        # posture preamble (what each level touches)
    assert "NO posture ever grants a blind write" in out   # honest about 'autonomous'
    assert "detection AID" in out                    # regime liability — shown BEFORE the question
    assert "language: en" in out                     # answer echo
    assert "Three things to try next" in out         # confident close
    assert "konsey audit" in out                     # audit trail surfaced
    assert "konsey enable automation" in out         # automation offered in the close


def test_quick_init_stays_terse_but_keeps_facts(tmp_path, monkeypatch, capsys):
    rc, out = _run_init(tmp_path, monkeypatch, capsys, quick=True)
    assert rc == 0
    # interactive-only fluff is suppressed when there are no questions:
    assert "Welcome to konsey" not in out
    assert "how much konsey may touch" not in out
    # ...but the result-facts (close + audit) are always shown:
    assert "Three things to try next" in out
    assert "konsey audit" in out


def test_audit_trail_is_surfaced_honestly(tmp_path, monkeypatch, capsys):
    _rc, out = _run_init(tmp_path, monkeypatch, capsys, quick=True)
    # the REAL append-only DB path is named (not a fabricated 'memory' feature)
    assert "append-only trail at" in out
    assert "council.duckdb" in out


def test_new_onboarding_keys_have_en_tr_parity():
    en, tr = i18n.load_catalog("en"), i18n.load_catalog("tr")
    for k in ("cli.init.welcome", "cli.init.preset_preamble", "cli.init.regime_preamble",
              "cli.init.echo_locale", "cli.init.echo_owner", "cli.init.summary_audit"):
        assert k in en, f"en missing {k}"
        assert k in tr, f"tr missing {k}"
