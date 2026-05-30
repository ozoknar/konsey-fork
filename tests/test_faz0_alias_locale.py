"""Faz 0 — `konsey` working alias + Turkish-first locale + argv-derived prog name.

Evidence > consensus: real calls against the shipped pyproject, the real cmd_init
(writing a real council.local.toml), and the real argument parser — no stubs. These
lock in the owner-confirmed Faz 0 contract: (1) `konsey` is a real console-script
alias of `council`; (2) the interface language is chosen FIRST (flag > $LANG tr* >
default) and the whole wizard flows in it — fixing "asked for Turkish, got English";
(3) help/usage/--version reflect the invoked name.
"""
from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path

from council import i18n
from council.cli import _detect_locale, _prog_name, build_parser, cmd_doctor, cmd_init

REPO = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------- #
# (1) `konsey` is a real console-script alias of `council`                     #
# --------------------------------------------------------------------------- #

def test_pyproject_declares_both_council_and_konsey():
    data = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    scripts = data["project"]["scripts"]
    assert scripts.get("council") == "council.cli:main"
    assert scripts.get("konsey") == "council.cli:main", "konsey must be a working alias"


# --------------------------------------------------------------------------- #
# (2) prog name follows the invoked command (council | konsey), else council   #
# --------------------------------------------------------------------------- #

def test_prog_name_reflects_invoked_command(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["konsey", "doctor"])
    assert _prog_name() == "konsey"
    assert build_parser().prog == "konsey"
    monkeypatch.setattr(sys, "argv", ["council"])
    assert _prog_name() == "council"
    monkeypatch.setattr(sys, "argv", ["/usr/bin/python3", "-m", "council.cli"])
    assert _prog_name() == "konsey"    # module/-m invocation falls back to canonical (konsey as of S0)


# --------------------------------------------------------------------------- #
# (3) _detect_locale: $LANG/$LC_ALL tr* → tr, else en (POSIX precedence)        #
# --------------------------------------------------------------------------- #

def _clear_locale_env(monkeypatch):
    for v in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE", "KONSEY_LOCALE"):
        monkeypatch.delenv(v, raising=False)


def test_detect_locale_turkish_from_lang(monkeypatch):
    _clear_locale_env(monkeypatch)
    monkeypatch.setenv("LANG", "tr_TR.UTF-8")
    assert _detect_locale() == "tr"


def test_detect_locale_english_and_unset(monkeypatch):
    _clear_locale_env(monkeypatch)
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    assert _detect_locale() == "en"
    _clear_locale_env(monkeypatch)
    assert _detect_locale() is None   # nothing set → None (caller falls back to profile/default)


def test_detect_locale_posix_precedence_both_directions(monkeypatch):
    # The FIRST set variable wins (LC_ALL > LC_MESSAGES > LANG), in BOTH directions.
    _clear_locale_env(monkeypatch)
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    monkeypatch.setenv("LC_ALL", "tr_TR.UTF-8")
    assert _detect_locale() == "tr"   # LC_ALL(tr) beats LANG(en)
    _clear_locale_env(monkeypatch)
    monkeypatch.setenv("LANG", "tr_TR.UTF-8")
    monkeypatch.setenv("LC_ALL", "en_US.UTF-8")
    assert _detect_locale() == "en"   # LC_ALL(en) beats LANG(tr) — the precedence bug Codex caught
    # LC_MESSAGES is the middle priority: it beats LANG, loses to LC_ALL.
    _clear_locale_env(monkeypatch)
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    monkeypatch.setenv("LC_MESSAGES", "tr_TR.UTF-8")
    assert _detect_locale() == "tr"   # LC_MESSAGES(tr) beats LANG(en)
    _clear_locale_env(monkeypatch)
    monkeypatch.setenv("LC_MESSAGES", "tr_TR.UTF-8")
    monkeypatch.setenv("LC_ALL", "en_US.UTF-8")
    assert _detect_locale() == "en"   # LC_ALL(en) beats LC_MESSAGES(tr)


# --------------------------------------------------------------------------- #
# (4) cmd_init honours the chosen locale AND flows the wizard in it             #
# --------------------------------------------------------------------------- #

def _init(tmp_path, monkeypatch, capsys, *, locale=None, lang=None):
    monkeypatch.setenv("COUNCIL_HOME", str(tmp_path))
    monkeypatch.setenv("COUNCIL_DATA_HOME", str(tmp_path / "data"))   # keep real ~ clean
    monkeypatch.delenv("COUNCIL_CONFIG", raising=False)
    _clear_locale_env(monkeypatch)
    if lang:
        monkeypatch.setenv("LANG", lang)
    rc = cmd_init(argparse.Namespace(quick=True, reconfigure=False, locale=locale))
    out = capsys.readouterr().out
    toml = (tmp_path / "council.local.toml").read_text(encoding="utf-8")
    return rc, out, toml


def test_init_locale_flag_forces_turkish_and_flows_in_it(tmp_path, monkeypatch, capsys):
    rc, out, toml = _init(tmp_path, monkeypatch, capsys, locale="tr")
    assert rc == 0
    assert 'locale = "tr"' in toml
    # The wizard banner itself must be Turkish (the bug was: written to TOML but the
    # running session stayed English). Assert the real tr catalog string appears.
    assert i18n.load_catalog("tr")["cli.init.bootstrap"] in out


def test_init_autodetects_turkish_from_lang(tmp_path, monkeypatch, capsys):
    rc, out, toml = _init(tmp_path, monkeypatch, capsys, lang="tr_TR.UTF-8")
    assert rc == 0
    assert 'locale = "tr"' in toml


def test_init_explicit_flag_overrides_env(tmp_path, monkeypatch, capsys):
    # LANG says Turkish, but --locale en must win.
    rc, out, toml = _init(tmp_path, monkeypatch, capsys, locale="en", lang="tr_TR.UTF-8")
    assert rc == 0
    assert 'locale = "en"' in toml
    assert i18n.load_catalog("en")["cli.init.bootstrap"] in out


def test_init_quick_defaults_english_without_signal(tmp_path, monkeypatch, capsys):
    rc, out, toml = _init(tmp_path, monkeypatch, capsys)   # no flag, no LANG
    assert rc == 0
    assert 'locale = "en"' in toml


# --------------------------------------------------------------------------- #
# Faz 1 — KONSEY_LOCALE override · non-TTY honesty · doctor advisory footer     #
# --------------------------------------------------------------------------- #

def test_detect_locale_konsey_env_override(monkeypatch):
    _clear_locale_env(monkeypatch)
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    monkeypatch.setenv("KONSEY_LOCALE", "tr")
    assert _detect_locale() == "tr"          # KONSEY_LOCALE beats the OS locale
    monkeypatch.setenv("KONSEY_LOCALE", "en")
    monkeypatch.setenv("LANG", "tr_TR.UTF-8")
    assert _detect_locale() == "en"
    monkeypatch.setenv("KONSEY_LOCALE", "")  # empty → falls through to OS locale
    assert _detect_locale() == "tr"          # LANG=tr_TR wins again


def test_init_non_tty_announces_defaults_not_silent(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("COUNCIL_HOME", str(tmp_path))
    monkeypatch.setenv("COUNCIL_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.delenv("COUNCIL_CONFIG", raising=False)
    _clear_locale_env(monkeypatch)
    monkeypatch.setattr("council.cli._is_tty", lambda: False)
    # quick=False, but a non-TTY (piped) run must auto-default AND say so — not silently.
    rc = cmd_init(argparse.Namespace(quick=False, reconfigure=False, locale="en"))
    cap = capsys.readouterr()
    assert rc == 0
    assert "non-interactive stdin" in cap.err            # the honest notice (stderr)
    assert (tmp_path / "council.local.toml").exists()     # still completed


def test_doctor_advisory_footer_when_zero_providers(tmp_path, monkeypatch, capsys):
    profile = tmp_path / "council.local.toml"
    profile.write_text(
        f'owner = "t"\ncouncil_home = "{tmp_path}"\n'
        '[[agents]]\nname = "claude"\ncli = "claude"\nrole = "lead"\nenabled = false\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("COUNCIL_CONFIG", str(profile))
    monkeypatch.setenv("COUNCIL_DATA_HOME", str(tmp_path / "data"))
    _clear_locale_env(monkeypatch)
    rc = cmd_doctor(argparse.Namespace(fix=False))
    out = capsys.readouterr().out
    assert rc == 0                       # advisory is a PASS, not a failure
    assert "advisory mode" in out        # ...but the footer says so, not "All checks passed."
