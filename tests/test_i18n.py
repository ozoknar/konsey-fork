"""i18n catalog + prompt-externalization tests (Constitution Article 17).

Evidence > consensus: every assertion is a real call against the shipped catalogs and
the real ``council.i18n`` / ``council.prompts`` modules — no stubs. These lock in the
contract that (1) ``en.json`` is canonical and ``tr.json`` is a full mirror, (2) a key
missing from a locale falls back to English *per key*, (3) the 9-state prompts are
sourced from the catalog (not embedded in Python), and (4) no natural-language prose
is left hard-coded in the prompt core.
"""
from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from council import i18n, prompts
from council.config import Config

_LOCALES = Path(i18n.__file__).resolve().parent / "locales"
# Keys present purely as catalog metadata, not translatable strings.
_META_KEYS = {"_meta"}


def _keys(locale: str) -> set[str]:
    data = json.loads((_LOCALES / f"{locale}.json").read_text(encoding="utf-8"))
    return set(data) - _META_KEYS


# --------------------------------------------------------------------------- #
# (1) en canonical + tr full mirror: identical key sets                       #
# --------------------------------------------------------------------------- #

def test_en_and_tr_have_identical_key_sets():
    en, tr = _keys("en"), _keys("tr")
    assert en == tr, f"en-only={en - tr!r} tr-only={tr - en!r}"


def test_every_state_prompt_is_in_canonical_catalog():
    en = _keys("en")
    for key in prompts.PROMPT_KEYS:
        assert prompts.catalog_key(key) in en, f"{key} missing from en.json"


def test_canonical_is_english():
    cat = i18n.canonical_catalog()
    assert cat[prompts.catalog_key("plan")].startswith("Task:")


# --------------------------------------------------------------------------- #
# (2) per-key English fallback for a locale that omits a key                  #
# --------------------------------------------------------------------------- #

def _write_council_home(tmp_path: Path, en: dict, other_locale: str, other: dict) -> Config:
    loc = tmp_path / "council" / "locales"
    loc.mkdir(parents=True)
    (loc / "en.json").write_text(json.dumps(en), encoding="utf-8")
    (loc / f"{other_locale}.json").write_text(json.dumps(other), encoding="utf-8")
    return Config(council_home=tmp_path, locale=other_locale)


def test_missing_key_falls_back_to_english_per_key(tmp_path):
    cfg = _write_council_home(
        tmp_path,
        en={"a": "EN_A", "b": "EN_B"},
        other_locale="xx",
        other={"a": "XX_A"},  # deliberately omits 'b'
    )
    cat = i18n.load_catalog(cfg)
    assert cat["a"] == "XX_A"   # locale override wins
    assert cat["b"] == "EN_B"   # missing → English fallback


def test_load_catalog_str_overload_uses_bundled_dir():
    en = i18n.load_catalog("en")
    tr = i18n.load_catalog("tr")
    assert en[prompts.catalog_key("plan")].startswith("Task:")
    assert tr[prompts.catalog_key("plan")].startswith("Görev:")


def test_load_catalog_config_overload_matches_locale(tmp_path):
    cfg = _write_council_home(
        tmp_path, en={"k": "EN"}, other_locale="tr", other={"k": "TR"}
    )
    assert i18n.load_catalog(cfg)["k"] == "TR"


def test_unknown_locale_yields_pure_english(tmp_path):
    _write_council_home(tmp_path, en={"k": "EN"}, other_locale="zz", other={"k": "ZZ"})
    # A config asking for a locale whose file is absent gets canonical English.
    cfg = Config(council_home=tmp_path, locale="de")  # no de.json written
    assert i18n.load_catalog(cfg)["k"] == "EN"


def test_load_catalog_none_is_english_only():
    cat = i18n.load_catalog(None)
    assert cat[prompts.catalog_key("verify")].startswith("Task:")


# --------------------------------------------------------------------------- #
# (3) the t() resolver: catalog → canonical → key-as-marker                   #
# --------------------------------------------------------------------------- #

def test_t_prefers_catalog_then_canonical_then_key():
    assert i18n.t({"advisory_mode": "OVERRIDE"}, "advisory_mode") == "OVERRIDE"
    # not in given catalog → canonical English
    assert "Advisory mode" in i18n.t({}, "advisory_mode")
    # in neither → the key itself (loud, debuggable marker, never blank)
    assert i18n.t({}, "totally.unknown.key") == "totally.unknown.key"
    assert i18n.t(None, "totally.unknown.key") == "totally.unknown.key"


# --------------------------------------------------------------------------- #
# (4) prompts are sourced from the catalog, not embedded in Python            #
# --------------------------------------------------------------------------- #

def test_prompt_resolves_from_catalog_en_and_tr():
    en = i18n.load_catalog("en")
    tr = i18n.load_catalog("tr")
    assert prompts.prompt("plan", en, task="DEMO", repo_lessons="").startswith("Task: DEMO")
    assert prompts.prompt("plan", tr, task="DEMO", repo_lessons="").startswith("Görev: DEMO")


def test_prompt_falls_back_to_canonical_with_no_catalog():
    # No catalog passed at all → canonical English template must still resolve + fill.
    out = prompts.prompt("synthesize", None, task="T", plans="P", critique="C")
    assert "T" in out and "P" in out and "C" in out


def test_all_state_prompts_fill_their_slots():
    slots = {
        "plan": {"task": "T", "repo_lessons": ""},
        "critique": {"task": "T", "plans": "P"},
        "synthesize": {"task": "T", "plans": "P", "critique": "C"},
        "execute": {"task": "T", "joint_plan": "J", "prior_failure": ""},
        "verify": {"task": "T", "execution": "E"},
    }
    for locale in ("en", "tr"):
        cat = i18n.load_catalog(locale)
        for key in prompts.PROMPT_KEYS:
            text = prompts.prompt(key, cat, **slots[key])
            assert text and "{" not in text  # fully filled, no dangling placeholders


def test_missing_slot_raises_loudly():
    with pytest.raises(KeyError):
        prompts.prompt("plan", i18n.load_catalog("en"))  # 'task' slot omitted


def test_machine_contract_tokens_preserved_in_all_locales():
    # The verdict / dissent tokens are matched by the orchestrator, so they must stay
    # literal (English) regardless of locale.
    for locale in ("en", "tr"):
        cat = i18n.load_catalog(locale)
        assert "VERDICT: PASS" in prompts.prompt("verify", cat, task="T", execution="E")
        assert "VERDICT: FAIL" in prompts.prompt("verify", cat, task="T", execution="E")
        assert "DISSENT:" in prompts.prompt("critique", cat, task="T", plans="P")


def test_no_embedded_natural_language_in_prompts_core():
    """The prompt core must not re-embed prose templates (the whole point of Art. 17)."""
    src = inspect.getsource(prompts)
    # Fingerprints of the old hard-coded templates that must now live only in JSON.
    for fingerprint in ("adversarially", "Joint Plan", "VERDICT", "independent plan"):
        assert fingerprint not in src, f"embedded prose leaked back into prompts.py: {fingerprint!r}"
