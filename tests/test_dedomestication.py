"""De-domestication (S1+S2): regimes + locales are DISCOVERED, not hardcoded to TR/EU/US.

Evidence > consensus: real calls against the shipped regime packs, the real gateway
loader, and the real locale discovery/negotiation. Proves the {kvkk,gdpr,hipaa}+{en,tr}
worldview is gone — any jurisdiction/language drops in as data with no core edit.
"""
from __future__ import annotations

import argparse
import json
import tomllib
from pathlib import Path

from council import gateway
from council.cli import _detect_locale, _discover_locales, _discover_regimes, cmd_doctor
from council.config import Config

REPO = Path(__file__).resolve().parent.parent
STARTER_REGIMES = {"gdpr", "hipaa", "kvkk", "lgpd", "ccpa", "pipl", "pdpa"}
STARTER_LOCALES = {"es", "fr", "de", "ar"}


def _clear(monkeypatch):
    for v in ("KONSEY_LOCALE", "LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(v, raising=False)


# --------------------------------------------------------------------------- #
# Regimes: a name is "regulated" iff its pack exists — no hardcoded allowlist   #
# --------------------------------------------------------------------------- #

def test_is_regulated_is_just_not_standard():
    assert gateway._is_regulated("standard") is False
    assert gateway._is_regulated("") is False
    assert gateway._is_regulated(None) is False
    for r in ("gdpr", "lgpd", "pipl", "some_future_law"):
        assert gateway._is_regulated(r) is True   # ANY jurisdiction, not a fixed set


def test_starter_packs_load_via_generic_loader():
    # lgpd (Brazil) + pipl (China) prove non-TR/US jurisdictions load with no core edit.
    for regime in ("lgpd", "pipl", "ccpa"):
        cfg = Config(council_home=REPO, data_regime=regime)
        assert gateway.regime_loaded(cfg) is True
        terms, pats = gateway._load_regime_terms(cfg)
        assert terms and pats   # markers + national-ID regex


def test_all_seven_packs_parse_and_disclaim():
    names = set()
    for f in (REPO / "regimes").glob("*.toml"):
        d = tomllib.load(open(f, "rb"))
        names.add(d["regime"])
        assert d.get("terms") or d.get("identifiers")
        assert "NOT a compliance guarantee" in f.read_text(encoding="utf-8")
    assert STARTER_REGIMES <= names


def test_custom_regime_without_pack_is_unloaded(tmp_path):
    # regulated (non-standard) but no pack → fail-open guard reports not-loaded (not crash).
    cfg = Config(council_home=tmp_path, data_regime="zzlaw")
    assert gateway.regime_loaded(cfg) is False


def test_discover_regimes_lists_packs():
    r = set(_discover_regimes(Config(council_home=REPO)))
    assert "standard" in r and STARTER_REGIMES <= r


def test_doctor_health_checks_any_regime(tmp_path, monkeypatch, capsys):
    # a non-standard regime with no local pack → doctor surfaces it (no {kvkk,gdpr,hipaa} gate).
    profile = tmp_path / "council.local.toml"
    profile.write_text(f'owner = "t"\ncouncil_home = "{tmp_path}"\ndata_regime = "lgpd"\n', encoding="utf-8")
    monkeypatch.setenv("COUNCIL_CONFIG", str(profile))
    monkeypatch.setenv("COUNCIL_DATA_HOME", str(tmp_path / "d"))
    _clear(monkeypatch)
    cmd_doctor(argparse.Namespace(fix=False, json=False, force=False))
    assert "lgpd" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# Locales: discovered + BCP-47 negotiation against ANY shipped catalog         #
# --------------------------------------------------------------------------- #

def test_discover_locales_includes_starters():
    assert ({"en", "tr"} | STARTER_LOCALES) <= set(_discover_locales())


def test_detect_locale_negotiates_any_shipped(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("LANG", "es_MX.UTF-8")
    assert _detect_locale() == "es"           # es-MX truncates to the shipped es catalog
    _clear(monkeypatch)
    monkeypatch.setenv("LANG", "ar_SA.UTF-8")
    assert _detect_locale() == "ar"           # RTL exemplar negotiated
    _clear(monkeypatch)
    monkeypatch.setenv("LANGUAGE", "pt:de:en")
    assert _detect_locale() == "de"           # gettext list: pt not shipped → first shipped (de)
    _clear(monkeypatch)
    monkeypatch.setenv("LANG", "ja_JP.UTF-8")
    assert _detect_locale() is None           # not shipped → None (caller falls back)
    _clear(monkeypatch)
    monkeypatch.setenv("LANG", "es_ES.UTF-8")
    monkeypatch.setenv("KONSEY_LOCALE", "fr")
    assert _detect_locale() == "fr"           # explicit override wins


def test_backward_compatible_en_tr(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("LANG", "tr_TR.UTF-8")
    assert _detect_locale() == "tr"
    _clear(monkeypatch)
    monkeypatch.setenv("LC_ALL", "en_US.UTF-8")
    monkeypatch.setenv("LANG", "tr_TR.UTF-8")
    assert _detect_locale() == "en"           # LC_ALL precedence preserved (Faz 0/1 contract)


def test_starter_locales_are_valid_partial_subsets():
    en = set(json.loads((REPO / "council/locales/en.json").read_text(encoding="utf-8")))
    for tag in STARTER_LOCALES:
        data = json.loads((REPO / f"council/locales/{tag}.json").read_text(encoding="utf-8"))
        keys = set(data) - {"_meta", "_meta_dir"}
        assert keys, f"{tag} has no translated keys"
        assert keys <= en, f"{tag} has unknown keys: {keys - en}"   # no drift from canonical
        assert "{ok}" in data.get("cli.doctor.all_passed", "{ok}")  # contract token preserved
    # the RTL exemplar declares its direction
    ar = json.loads((REPO / "council/locales/ar.json").read_text(encoding="utf-8"))
    assert ar.get("_meta_dir") == "rtl"
