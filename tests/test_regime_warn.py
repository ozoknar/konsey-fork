"""Regime fail-open warning tests (Constitution Article 4.1).

THE invariant being closed (KNOWN_ISSUES "Regime term-file presence (fail-open
edge)"): the secret scan is always on, but clinical/identity detection needs the
regime *term file* (``regimes/<regime>.toml``). Setting ``data_regime=hipaa``
WITHOUT that file silently yields no clinical detection — the dangerous fail-open
case. ``gateway.regime_loaded(cfg)`` reports it, and ``council doctor`` surfaces a
VISIBLE ⚠ (non-fatal: doctor still exits 0 when this is the only issue).

Evidence > consensus: ``regime_loaded`` is called directly, and the warning is
asserted on real captured ``cmd_doctor`` stdout.
"""
from __future__ import annotations

import argparse
import textwrap

import pytest

from council.config import Config
from council.cli import cmd_doctor
from council.gateway import regime_loaded


# --------------------------------------------------------------------------- #
# regime_loaded(cfg) — the boolean guard.                                       #
# --------------------------------------------------------------------------- #

def _seed_regime_file(tmp_path, regime: str, body: str) -> Config:
    regimes = tmp_path / "regimes"
    regimes.mkdir(exist_ok=True)
    (regimes / f"{regime}.toml").write_text(textwrap.dedent(body), encoding="utf-8")
    return Config(council_home=tmp_path, data_regime=regime)


def test_regime_loaded_false_under_standard(tmp_path):
    # standard is not a regulated regime → no plugin expected, not a misconfiguration.
    assert regime_loaded(Config(council_home=tmp_path, data_regime="standard")) is False


def test_regime_loaded_false_when_regulated_but_no_file(tmp_path):
    # The dangerous fail-open case: regime set, no term file → detection silently off.
    assert regime_loaded(Config(council_home=tmp_path, data_regime="hipaa")) is False


def test_regime_loaded_true_when_terms_present(tmp_path):
    cfg = _seed_regime_file(tmp_path, "hipaa", 'terms = ["confidential_clinical_marker"]')
    assert regime_loaded(cfg) is True


def test_regime_loaded_true_when_only_identifiers_present(tmp_path):
    cfg = _seed_regime_file(tmp_path, "kvkk", """
        [[identifiers]]
        name = "demo_id"
        pattern = "\\\\b[0-9]{9}\\\\b"
    """)
    assert regime_loaded(cfg) is True


def test_regime_loaded_false_when_file_empty(tmp_path):
    # An empty/broken file must not read as "loaded" (fail-safe).
    cfg = _seed_regime_file(tmp_path, "gdpr", "# nothing here\n")
    assert regime_loaded(cfg) is False


# --------------------------------------------------------------------------- #
# council doctor — VISIBLE ⚠ when regulated regime is set but no file loads.    #
# --------------------------------------------------------------------------- #

def _profile(tmp_path, regime: str, *, with_terms: bool = False) -> "object":
    profile = tmp_path / "council.local.toml"
    profile.write_text(textwrap.dedent(f"""
        owner = "tester"
        data_regime = "{regime}"
        council_home = "{tmp_path}"
    """), encoding="utf-8")
    if with_terms:
        regimes = tmp_path / "regimes"
        regimes.mkdir(exist_ok=True)
        (regimes / f"{regime}.toml").write_text(
            'terms = ["confidential_clinical_marker"]\n', encoding="utf-8"
        )
    return profile


def _doctor(profile, monkeypatch, capsys):
    monkeypatch.setenv("COUNCIL_CONFIG", str(profile))
    rc = cmd_doctor(argparse.Namespace(fix=False))
    return rc, capsys.readouterr().out


def test_doctor_warns_regulated_regime_without_file(tmp_path, monkeypatch, capsys):
    profile = _profile(tmp_path, "hipaa", with_terms=False)
    rc, out = _doctor(profile, monkeypatch, capsys)
    assert "⚠" in out
    assert "data_regime='hipaa'" in out
    assert "NO term file loaded" in out
    # Non-fatal: the regime gap alone must not make doctor exit non-zero.
    # (Other lines like duckdb/graph are environment-dependent; assert the regime
    #  line itself is presented as a warning, not a ✗ critical failure.)
    regime_lines = [ln for ln in out.splitlines() if "data_regime=" in ln]
    assert regime_lines and all("✗" not in ln for ln in regime_lines)


def test_doctor_no_regime_warning_under_standard(tmp_path, monkeypatch, capsys):
    profile = _profile(tmp_path, "standard")
    rc, out = _doctor(profile, monkeypatch, capsys)
    assert "data_regime='standard'" not in out
    assert "NO term file loaded" not in out


def test_doctor_confirms_regime_when_file_present(tmp_path, monkeypatch, capsys):
    profile = _profile(tmp_path, "hipaa", with_terms=True)
    rc, out = _doctor(profile, monkeypatch, capsys)
    assert "term plugin loaded" in out
    assert "NO term file loaded" not in out


# --------------------------------------------------------------------------- #
# Render glyph: a passing-but-warning line must NOT carry a contradictory       #
# "✓ ⚠ ..." double glyph (integration / fresh-install audit finding).           #
# --------------------------------------------------------------------------- #

def test_doctor_warning_line_has_no_double_glyph(tmp_path, monkeypatch, capsys):
    """A non-fatal ⚠ line is rendered with its own ⚠ marker, never prefixed by ✓."""
    profile = _profile(tmp_path, "hipaa", with_terms=False)
    rc, out = _doctor(profile, monkeypatch, capsys)
    warn_lines = [ln for ln in out.splitlines() if "data_regime='hipaa'" in ln]
    assert warn_lines, "expected a regime warning line"
    for ln in warn_lines:
        # The warning glyph is present...
        assert "⚠" in ln
        # ...but never as a "✓ ⚠" (or "✓  ⚠") double glyph.
        assert "✓ ⚠" not in ln and "✓  ⚠" not in ln
        # The visible marker for the line is ⚠ itself, not ✓.
        assert ln.lstrip().startswith("⚠")
