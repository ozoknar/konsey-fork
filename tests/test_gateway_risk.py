"""Risk-classification gate tests (Constitution Article 4.4 & 4.5).

THE invariant: a project *name* alone never implies sensitivity. Risk is driven by
generic intent signals (deploy/prod → production), by the operator's project risk
*registry* (``cfg.projects``), and — only under a regulated data regime — by the
clinical/identity terms in a regime plugin. Core ships NO embedded clinical word
list (no double-source, Article 4.3): under the default ``standard`` regime a bare
"patient"/"DICOM" mention does not by itself escalate risk.

These run against the REAL ``council.gateway`` (cfg is a required argument).
"""
from __future__ import annotations

import textwrap

import pytest

from council.config import Config, ProjectEntry
from council.gateway import classify_risk, preflight


def _cfg(projects=None, regime="standard", **kw) -> Config:
    return Config(projects=projects or [], data_regime=regime, **kw)


# --------------------------------------------------------------------------- #
# A project NAME alone is never sensitive (Article 4.4).                        #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("task,hint", [
    ("Refactor the imaging module and add unit tests", "some-medical-app"),
    ("Improve the README and the architecture diagram", "clinical-portal"),
    ("Write a config loader", "radiology-saas"),
    ("Plan the sprint", "patient-records-ui"),
])
def test_project_name_alone_is_not_sensitive(task, hint):
    risk = classify_risk(task, hint, _cfg())
    assert risk not in ("sensitive", "phi"), (
        f"a bare project name must not escalate to sensitive (got {risk})"
    )


def test_registry_raises_the_floor_but_a_name_does_not():
    cfg = _cfg(projects=[ProjectEntry(match="infra/*", risk="production")])
    # The same hint is only production because the operator registered it — not
    # because of anything in its name.
    assert classify_risk("tweak a setting", "infra/api", cfg) == "production"
    assert classify_risk("tweak a setting", "frontend/api", cfg) == "internal"


def test_registry_never_lowers_a_higher_generic_risk():
    # A 'public' registry entry cannot demote a task whose intent is production.
    cfg = _cfg(projects=[ProjectEntry(match="docs/*", risk="public")])
    assert classify_risk("deploy to production now", "docs/site", cfg) == "production"


# --------------------------------------------------------------------------- #
# Generic intent signals.                                                       #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("task", [
    "Deploy the service to production",
    "Push to main and run the live migration",
    "Rotate the production secret",
])
def test_production_hints_raise_production(task):
    assert classify_risk(task, "", _cfg()) == "production"


@pytest.mark.parametrize("task", [
    "Summarize this open-source documentation",
    "Compare these two architecture options",
    "Improve the public README",
])
def test_public_signals_classify_as_public_or_internal(task):
    assert classify_risk(task, "", _cfg()) in ("public", "internal")


@pytest.mark.parametrize("task", [
    "Export the employee payroll list",
    "Build the personnel contact list report",
])
def test_pii_signals_classify_as_pii(task):
    assert classify_risk(task, "", _cfg()) == "pii"


# --------------------------------------------------------------------------- #
# Regulated regime: clinical/identity terms come ONLY from the plugin file.     #
# --------------------------------------------------------------------------- #

def _regime_cfg(tmp_path, regime="hipaa") -> Config:
    regimes = tmp_path / "regimes"
    regimes.mkdir()
    (regimes / f"{regime}.toml").write_text(textwrap.dedent(f"""
        regime = "{regime}"
        terms = ["confidential_clinical_marker"]
        [[identifiers]]
        name = "demo_id"
        pattern = "\\\\b[0-9]{{9}}\\\\b"
    """), encoding="utf-8")
    return Config(council_home=tmp_path, data_regime=regime)


def test_clinical_term_is_inert_under_standard_regime():
    # Core ships no clinical dictionary: under 'standard', the term does nothing.
    assert classify_risk("contains confidential_clinical_marker", "", _cfg()) != "sensitive"


def test_regime_plugin_term_raises_sensitive(tmp_path):
    cfg = _regime_cfg(tmp_path)
    assert classify_risk("note contains confidential_clinical_marker here", "", cfg) == "sensitive"


def test_regime_identifier_pattern_raises_sensitive(tmp_path):
    cfg = _regime_cfg(tmp_path)
    assert classify_risk("subject id 123456789 attached", "", cfg) == "sensitive"


# --------------------------------------------------------------------------- #
# preflight: sensitive is blocked; production requires a human.                 #
# --------------------------------------------------------------------------- #

def test_sensitive_is_blocked(tmp_path):
    cfg = _regime_cfg(tmp_path)
    res = preflight("note: confidential_clinical_marker", cfg=cfg)
    assert res.risk == "sensitive"
    assert res.blocked is True
    assert res.block_reason


def test_production_requires_human():
    res = preflight("deploy to production", cfg=_cfg())
    assert res.risk == "production"
    assert res.budget.get("human_required") is True


def test_phi_project_name_in_text_does_not_block():
    # Discussing a phi-adjacent topic is fine; only real (regime/registry) data blocks.
    res = preflight("Plan the roadmap for the radiology product", project_hint="radiology", cfg=_cfg())
    assert res.risk != "sensitive"
    assert res.blocked is False


def test_preflight_default_cfg_does_not_crash():
    # cfg=None must fall back to safe defaults, not raise.
    res = preflight("a harmless internal task")
    assert res.risk in ("public", "internal", "pii", "production")
