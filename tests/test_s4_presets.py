"""S4 — onboarding posture presets (advisory | balanced | autonomous).

Evidence > consensus: the pure mapping is asserted directly, and the wizard
integration is exercised through the REAL `cmd_init` writing a REAL
council.local.toml into a temp home (no mocks of the write path). The HONESTY
invariants (no preset can grant workspace-write / autocapture / a compliance
regime) are pinned as tests so a future edit to the table can't silently make a
named posture more permissive.
"""
from __future__ import annotations

import argparse

from council import i18n
from council.cli import _SCALAR_KEYS, cmd_init
from council.config import load_config
from council.presets import (
    DEFAULT_PRESET,
    PRESET_NAMES,
    normalize_preset,
    preset_overrides,
)


# --------------------------------------------------------------------------- #
# (1) the pure preset table — and its honesty invariants                       #
# --------------------------------------------------------------------------- #

def test_balanced_is_the_safe_default():
    assert DEFAULT_PRESET == "balanced"
    ov = preset_overrides("balanced")
    assert ov["exec_sandbox"] == "off"          # no autonomous writes by default
    assert ov["roster_enable"] == "all"


def test_no_preset_ever_grants_workspace_write():
    # The core honesty invariant: not even `autonomous` may unlock real writes by name.
    for name in PRESET_NAMES:
        assert preset_overrides(name)["exec_sandbox"] != "workspace-write"


def test_autonomous_only_arms_read_only():
    assert preset_overrides("autonomous")["exec_sandbox"] == "read-only"


def test_advisory_is_lead_only_and_off():
    ov = preset_overrides("advisory")
    assert ov["roster_enable"] == "lead-only"   # single provider → honest advisory mode
    assert ov["exec_sandbox"] == "off"


def test_unknown_and_none_fall_back_to_balanced():
    assert preset_overrides("garbage") == preset_overrides("balanced")
    assert preset_overrides(None) == preset_overrides("balanced")
    assert normalize_preset("nope") == "balanced"
    assert normalize_preset(None) == "balanced"
    assert normalize_preset("AUTONOMOUS") == "autonomous"   # case-insensitive


# --------------------------------------------------------------------------- #
# (2) cmd_init integration — real write into a temp home                       #
# --------------------------------------------------------------------------- #

def _init(tmp_path, monkeypatch, capsys, *, quick=True, preset=None, reconfigure=False):
    monkeypatch.setenv("KONSEY_HOME", str(tmp_path))
    monkeypatch.setenv("KONSEY_DATA_HOME", str(tmp_path / "data"))
    for v in ("COUNCIL_HOME", "COUNCIL_CONFIG", "KONSEY_CONFIG",
              "LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE", "KONSEY_LOCALE"):
        monkeypatch.delenv(v, raising=False)
    rc = cmd_init(argparse.Namespace(
        quick=quick, reconfigure=reconfigure, locale="en", preset=preset,
    ))
    out = capsys.readouterr()
    cfg = load_config(tmp_path / "council.local.toml")
    return rc, out, cfg


def test_quick_default_preset_is_balanced_and_safe(tmp_path, monkeypatch, capsys):
    rc, _out, cfg = _init(tmp_path, monkeypatch, capsys, quick=True, preset=None)
    assert rc == 0
    assert cfg.preset == "balanced"
    assert cfg.exec_sandbox == "off"
    assert cfg.owner == "operator"


def test_preset_flag_autonomous_writes_read_only(tmp_path, monkeypatch, capsys):
    _rc, _out, cfg = _init(tmp_path, monkeypatch, capsys, quick=True, preset="autonomous")
    assert cfg.preset == "autonomous"
    assert cfg.exec_sandbox == "read-only"          # armed, never workspace-write
    assert cfg.exec_sandbox != "workspace-write"


def test_advisory_enables_at_most_one_provider(tmp_path, monkeypatch, capsys):
    _rc, _out, cfg = _init(tmp_path, monkeypatch, capsys, quick=True, preset="advisory")
    enabled = [a for a in cfg.agents if a.enabled]
    assert len(enabled) <= 1                         # lead-only → honest advisory mode


def test_advisory_enables_first_DETECTED_not_roster_index_zero(tmp_path, monkeypatch, capsys):
    # Codex S4 finding: when the nominal lead (index 0) is NOT installed but a later
    # provider IS, advisory must enable that DETECTED provider — not leave the profile
    # all-disabled (which would be a useless single-provider posture that can't run).
    monkeypatch.setattr(
        "council.cli._detect_roster",
        lambda _extra: [("claude", "claude", False), ("codex", "codex", True), ("google", "agy", False)],
    )
    _rc, _out, cfg = _init(tmp_path, monkeypatch, capsys, quick=True, preset="advisory")
    enabled = [a.name for a in cfg.agents if a.enabled]
    assert enabled == ["codex"]                      # the first DETECTED, not the absent index-0 lead


def test_org_and_node_default_empty_no_longer_interrogated(tmp_path, monkeypatch, capsys):
    _rc, _out, cfg = _init(tmp_path, monkeypatch, capsys, quick=True, preset="balanced")
    assert cfg.org == "" and cfg.node_name == ""     # dropped from the wizard (S4)


# --------------------------------------------------------------------------- #
# (3) non-TTY honesty — names the applied preset, flag still wins              #
# --------------------------------------------------------------------------- #

def test_non_tty_uses_default_and_names_it(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("council.cli._is_tty", lambda: False)
    rc, out, cfg = _init(tmp_path, monkeypatch, capsys, quick=False, preset=None)
    assert rc == 0
    assert "non-interactive" in out.err              # the honest stderr notice
    assert "balanced" in out.err                     # names the preset it applied
    assert cfg.preset == "balanced"


def test_non_tty_still_honours_explicit_preset_flag(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("council.cli._is_tty", lambda: False)
    _rc, out, cfg = _init(tmp_path, monkeypatch, capsys, quick=False, preset="autonomous")
    assert cfg.preset == "autonomous"                # flag beats the non-TTY default
    assert "autonomous" in out.err


# --------------------------------------------------------------------------- #
# (4) backward-compat + wiring                                                  #
# --------------------------------------------------------------------------- #

def test_old_profile_without_preset_loads_as_balanced(tmp_path):
    p = tmp_path / "council.local.toml"
    p.write_text('owner = "x"\nlocale = "en"\n', encoding="utf-8")   # no preset key
    cfg = load_config(p)
    assert cfg.preset == "balanced"                  # defaulted, never raises
    assert cfg.owner == "x"


def test_preset_is_a_settable_scalar_key():
    assert "preset" in _SCALAR_KEYS                  # `konsey config set preset ...` works


def test_ask_preset_key_present_with_choices_in_both_locales():
    for loc in ("en", "tr"):
        cat = i18n.load_catalog(loc)
        assert "cli.init.ask_preset" in cat
        assert "{choices}" in cat["cli.init.ask_preset"]
