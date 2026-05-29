"""doctor --json + _doctor_collect — the read-only machine contract the repair loop reads.

Evidence > consensus: real calls against the real cmd_doctor / _doctor_collect; pretty
output must stay byte-identical and rc identical in both modes; JSON severity must equal
the pretty glyph (single source of truth). No agent, no subprocess.
"""
from __future__ import annotations

import argparse
import json

from council.cli import _doctor_collect, build_parser, cmd_doctor
from council.config import Config, RosterEntry


def _clear(monkeypatch):
    for v in ("LC_ALL", "LC_MESSAGES", "LANG", "KONSEY_LOCALE"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.delenv("COUNCIL_CONFIG", raising=False)


def _cfg(tmp_path, agents=None):
    return Config(council_home=tmp_path, data_home=tmp_path / "d", locale="en", agents=agents or [])


# --------------------------------------------------------------------------- #
# _doctor_collect — typed, locale-independent report                           #
# --------------------------------------------------------------------------- #

def test_collect_shape_and_keys(tmp_path, monkeypatch):
    _clear(monkeypatch)
    r = _doctor_collect(_cfg(tmp_path))
    assert r["schema"] == "council.doctor/v1"
    assert set(r) >= {"schema", "ok", "rc", "critical", "advisory", "checks"}
    assert r["rc"] in (0, 1)
    assert r["ok"] is (r["rc"] == 0)
    for c in r["checks"]:
        assert set(c) >= {"ok", "severity", "message", "id"}
        assert c["severity"] in ("ok", "warning", "critical")


def test_collect_advisory_when_zero_providers(tmp_path, monkeypatch):
    _clear(monkeypatch)
    cfg = _cfg(tmp_path, [RosterEntry("claude", "claude", "lead", enabled=False)])
    r = _doctor_collect(cfg)
    assert r["advisory"] is True
    assert r["critical"] is False
    assert r["rc"] == 0


def test_collect_critical_when_enabled_cli_absent(tmp_path, monkeypatch):
    _clear(monkeypatch)
    cfg = _cfg(tmp_path, [RosterEntry("x", "definitely_not_a_real_cli_xyz", "lead", enabled=True)])
    r = _doctor_collect(cfg)
    assert r["critical"] is True
    assert r["rc"] == 1
    assert any(c["severity"] == "critical" for c in r["checks"])


# --------------------------------------------------------------------------- #
# cmd_doctor --json: clean JSON on stdout, rc parity                           #
# --------------------------------------------------------------------------- #

def _profile(tmp_path):
    p = tmp_path / "council.local.toml"
    p.write_text(f'owner = "t"\ncouncil_home = "{tmp_path}"\n', encoding="utf-8")
    return p


def _run(profile, monkeypatch, capsys, **flags):
    _clear(monkeypatch)
    monkeypatch.setenv("COUNCIL_CONFIG", str(profile))
    monkeypatch.setenv("COUNCIL_DATA_HOME", str(profile.parent / "d"))
    base = {"fix": False, "json": False, "force": False}
    base.update(flags)
    rc = cmd_doctor(argparse.Namespace(**base))
    return rc, capsys.readouterr().out


def test_json_is_one_object_with_rc_parity(tmp_path, monkeypatch, capsys):
    rc_json, out = _run(_profile(tmp_path), monkeypatch, capsys, json=True)
    obj = json.loads(out)          # exactly one JSON object, nothing else on stdout
    assert obj["schema"] == "council.doctor/v1"
    assert obj["rc"] == rc_json
    # rc must equal the pretty run's rc on the same profile
    rc_pretty, _ = _run(_profile(tmp_path), monkeypatch, capsys)
    assert rc_json == rc_pretty


def test_pretty_default_unchanged_by_json_flag(tmp_path, monkeypatch, capsys):
    rc1, out_default = _run(_profile(tmp_path), monkeypatch, capsys)            # no json kw → default
    rc2, out_explicit = _run(_profile(tmp_path), monkeypatch, capsys, json=False)
    assert out_default == out_explicit and rc1 == rc2   # default path is byte-identical


def test_severity_equals_pretty_glyph(tmp_path, monkeypatch, capsys):
    # JSON severity must match the glyph the pretty renderer would use (no drift).
    _, pretty = _run(_profile(tmp_path), monkeypatch, capsys)
    _, js = _run(_profile(tmp_path), monkeypatch, capsys, json=True)
    obj = json.loads(js)
    for c in obj["checks"]:
        msg = c["message"]
        if c["severity"] == "critical":
            assert f"  ✗ {msg}" in pretty
        elif c["severity"] == "warning":
            assert f"  {msg}" in pretty   # message itself starts with ⚠
        else:
            assert f"  ✓ {msg}" in pretty


# --------------------------------------------------------------------------- #
# parser wiring                                                                #
# --------------------------------------------------------------------------- #

def test_parser_doctor_flags():
    p = build_parser()
    assert p.parse_args(["doctor", "--json"]).json is True
    assert p.parse_args(["doctor"]).json is False
    assert p.parse_args(["doctor", "--fix"]).fix is True
    assert p.parse_args(["doctor", "--fix", "--force"]).force is True
