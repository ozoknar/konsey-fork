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
from council.cli import _detect_locale, _prog_name, build_parser, cmd_init

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
    assert _prog_name() == "council"   # module/-m invocation falls back to canonical


# --------------------------------------------------------------------------- #
# (3) _detect_locale: $LANG/$LC_ALL tr* → tr, else en (POSIX precedence)        #
# --------------------------------------------------------------------------- #

def _clear_locale_env(monkeypatch):
    for v in ("LC_ALL", "LC_MESSAGES", "LANG"):
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
