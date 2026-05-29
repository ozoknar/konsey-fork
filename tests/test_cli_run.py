"""`council run --dry-run` config-application tests (Constitution Article 4 & 5).

THE invariant being closed (KNOWN_ISSUES "run --dry-run config application"): the
dry-run PREFLIGHT must apply the *same* config the live ``run`` path does — the
operator's project risk *registry* (``cfg.projects``) and the active data *regime*
(``cfg.data_regime``), not gateway defaults. We assert this by driving ``cmd_run``
through a real ``council.local.toml`` (no mock of the gateway): a registered project
escalates to production, and a regulated-regime clinical term escalates to sensitive
and blocks — exactly as a full ``run`` would classify them.

Evidence > consensus: every assertion is a real ``cmd_run`` invocation whose JSON
output is parsed, not a description of intended behaviour.
"""
from __future__ import annotations

import argparse
import json
import textwrap

import pytest

from council.cli import cmd_run


def _ns(task: str, project: str = "", *, dry_run: bool = True, as_json: bool = True) -> argparse.Namespace:
    return argparse.Namespace(task=task, project=project, dry_run=dry_run, json=as_json)


def _write_profile(tmp_path, *, regime: str = "standard", projects_toml: str = "") -> None:
    """Write a real council.local.toml under a council_home and (via env) point
    load_config() at it. Also seeds a regimes/<regime>.toml term file when regulated
    so the regime path has something to load."""
    profile = tmp_path / "council.local.toml"
    profile.write_text(textwrap.dedent(f"""
        owner = "tester"
        locale = "en"
        data_regime = "{regime}"
        council_home = "{tmp_path}"
        {projects_toml}
    """), encoding="utf-8")
    if regime in ("kvkk", "gdpr", "hipaa"):
        regimes = tmp_path / "regimes"
        regimes.mkdir(exist_ok=True)
        (regimes / f"{regime}.toml").write_text(textwrap.dedent("""
            terms = ["confidential_clinical_marker"]
        """), encoding="utf-8")
    return profile


def _run_capture(profile, ns, monkeypatch, capsys):
    monkeypatch.setenv("COUNCIL_CONFIG", str(profile))
    rc = cmd_run(ns)
    out = capsys.readouterr().out
    return rc, out


# --------------------------------------------------------------------------- #
# dry-run applies the project risk REGISTRY (was: gateway defaults).            #
# --------------------------------------------------------------------------- #

def test_dry_run_applies_project_registry(tmp_path, monkeypatch, capsys):
    profile = _write_profile(
        tmp_path,
        projects_toml='[[projects]]\nmatch = "infra/*"\nrisk = "production"',
    )
    rc, out = _run_capture(profile, _ns("tweak a setting", "infra/api"), monkeypatch, capsys)
    assert rc == 0
    data = json.loads(out)
    # Only production because the OPERATOR registered infra/* — not from the name.
    assert data["risk"] == "production"
    assert data["budget"]["human_required"] is True


def test_dry_run_unregistered_project_stays_internal(tmp_path, monkeypatch, capsys):
    profile = _write_profile(
        tmp_path,
        projects_toml='[[projects]]\nmatch = "infra/*"\nrisk = "production"',
    )
    rc, out = _run_capture(profile, _ns("tweak a setting", "frontend/api"), monkeypatch, capsys)
    assert rc == 0
    data = json.loads(out)
    assert data["risk"] == "internal"


# --------------------------------------------------------------------------- #
# dry-run applies the active data REGIME (clinical term → sensitive + blocked). #
# --------------------------------------------------------------------------- #

def test_dry_run_applies_regime_term(tmp_path, monkeypatch, capsys):
    profile = _write_profile(tmp_path, regime="hipaa")
    rc, out = _run_capture(
        profile, _ns("note contains confidential_clinical_marker here"), monkeypatch, capsys
    )
    assert rc == 0
    data = json.loads(out)
    assert data["risk"] == "sensitive"
    assert data["blocked"] is True


def test_dry_run_same_term_inert_under_standard_regime(tmp_path, monkeypatch, capsys):
    # Without the regime active, the same marker must NOT escalate (no double-source).
    profile = _write_profile(tmp_path, regime="standard")
    rc, out = _run_capture(
        profile, _ns("note contains confidential_clinical_marker here"), monkeypatch, capsys
    )
    assert rc == 0
    data = json.loads(out)
    assert data["risk"] != "sensitive"
    assert data["blocked"] is False


# --------------------------------------------------------------------------- #
# dry-run still scans secrets and never executes the loop.                      #
# --------------------------------------------------------------------------- #

def test_dry_run_text_mode_reports_secret(tmp_path, monkeypatch, capsys):
    profile = _write_profile(tmp_path)
    ns = _ns("here is a leaked key sk-ant-api03-AAAAAAAAAAAAAAAAAAAAAAAA", as_json=False)
    rc, out = _run_capture(profile, ns, monkeypatch, capsys)
    assert rc == 0
    assert "blocked : True" in out
    assert "secrets" in out
