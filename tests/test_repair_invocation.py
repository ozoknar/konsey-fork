"""The repair-worker invocation BUILDER (the Faz 3 seam) — pure, zero subprocess.

These assert the SHAPE of the tool-ON call: per-provider argv, the single cwd-pin, the
fail-closed env allow-list (secrets dropped, auth kept, os.environ never mutated), and the
secret-scrubbed scoped prompt.
"""
from __future__ import annotations

import os

import pytest

from council import repair
from council.config import Config, RosterEntry

_AGENTS = [
    RosterEntry("claude", "claude", "lead", enabled=True),
    RosterEntry("codex", "codex", "critic", enabled=True),
    RosterEntry("google", "agy", "researcher", enabled=True),
]


def _cfg(tmp_path):
    return Config(council_home=tmp_path, data_home=tmp_path / "d", agents=_AGENTS)


_FINDINGS = [
    {"ok": False, "severity": "critical", "message": "duckdb not importable", "id": "check_2"},
    {"ok": True, "severity": "ok", "message": "fine", "id": "check_0"},
]


def test_claude_argv_is_tool_on_and_scoped(tmp_path):
    inv = repair.build_repair_invocation(_cfg(tmp_path), "claude", _FINDINGS, str(tmp_path))
    repo = str(tmp_path.resolve())
    assert list(inv.argv) == ["claude", "--permission-mode", "acceptEdits", "--add-dir", repo, "-p", inv.prompt]
    assert "--dangerously-skip-permissions" not in inv.argv
    assert inv.prompt in inv.argv          # prompt is a real argv element, never str.format'd


def test_codex_argv_shape(tmp_path):
    inv = repair.build_repair_invocation(_cfg(tmp_path), "codex", _FINDINGS, str(tmp_path))
    repo = str(tmp_path.resolve())
    a = list(inv.argv)
    for tok in ["-a", "never", "-s", "workspace-write", "exec", "--skip-git-repo-check", "--cd", repo]:
        assert tok in a
    assert a[-1] == inv.prompt              # prompt last
    assert a[a.index("--output-last-message") + 1].startswith(repo)


def test_google_argv_is_last_resort_sandboxed(tmp_path):
    inv = repair.build_repair_invocation(_cfg(tmp_path), "google", _FINDINGS, str(tmp_path))
    repo = str(tmp_path.resolve())
    for tok in ["--sandbox", "--dangerously-skip-permissions", "--add-dir", repo]:
        assert tok in inv.argv


def test_cwd_pin_resolves_relative_repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    inv = repair.build_repair_invocation(_cfg(tmp_path), "claude", _FINDINGS, ".")
    assert inv.repo_root == str(tmp_path.resolve())
    assert str(tmp_path.resolve()) in inv.argv   # the --add-dir got the absolute path


def test_env_is_fail_closed_allow_list(tmp_path):
    base = {
        "PATH": "/usr/bin", "HOME": "/h", "LANG": "en_US.UTF-8",
        "ANTHROPIC_API_KEY": "sk-x", "CLAUDE_CONFIG_DIR": "/c",
        "AWS_SECRET_ACCESS_KEY": "shh", "SECRET_DEPLOY_TOKEN": "shh2", "RANDOM_VAR": "x",
        # exact allow-list is fail-closed: NONE of these broad-prefix secrets may pass.
        "KONSEY_PROD_DB_PASSWORD": "shh3", "GOOGLE_APPLICATION_CREDENTIALS": "/creds.json",
        "CLAUDE_RANDOM_THING": "x", "CODEX_SECRET": "shh4",
    }
    before = dict(os.environ)
    inv = repair.build_repair_invocation(_cfg(tmp_path), "claude", _FINDINGS, str(tmp_path), base_env=base)
    assert "ANTHROPIC_API_KEY" in inv.env and "HOME" in inv.env and "CLAUDE_CONFIG_DIR" in inv.env
    for leaky in ("AWS_SECRET_ACCESS_KEY", "SECRET_DEPLOY_TOKEN", "RANDOM_VAR",
                  "KONSEY_PROD_DB_PASSWORD", "GOOGLE_APPLICATION_CREDENTIALS",
                  "CLAUDE_RANDOM_THING", "CODEX_SECRET"):
        assert leaky not in inv.env, f"{leaky} must NOT pass the exact allow-list"
    assert inv.env["PATH"].startswith(_cfg(tmp_path).extra_path)
    assert os.environ == before                  # never mutates the real environment


def test_scrub_manifest_is_recursive(tmp_path):
    m = {
        "changed_files": ["ok.py", "leaked-sk-ant-api03-AAAAAAAAAAAAAAAAAAAAAAAA.txt"],
        "nested": {"k": "token sk-ant-api03-BBBBBBBBBBBBBBBBBBBBBBBB here"},
        "n": 3,
    }
    out = repair._scrub_manifest(m)
    flat = str(out)
    assert "sk-ant-api03-AAAA" not in flat   # secret in a LIST element redacted
    assert "sk-ant-api03-BBBB" not in flat   # secret in a NESTED dict redacted
    assert out["n"] == 3                     # non-strings untouched


def test_prompt_is_scrubbed_and_scoped(tmp_path):
    findings = [{"ok": False, "severity": "critical",
                 "message": "leaked sk-ant-api03-AAAAAAAAAAAAAAAAAAAAAAAA in config", "id": "check_5"}]
    inv = repair.build_repair_invocation(_cfg(tmp_path), "claude", findings, str(tmp_path))
    from council.gateway import scan_secrets
    assert "sk-ant-api03-AAAAAAAAAAAAAAAAAAAAAAAA" not in inv.prompt   # redacted
    assert scan_secrets(inv.prompt) == []                              # nothing the gate would flag
    for must in ("ONLY", str(tmp_path.resolve()), "sudo", "rm -rf", "outside"):
        assert must in inv.prompt                                      # the hard-scope header
    assert "fine" not in inv.prompt                                    # ok==True findings filtered out


def test_unknown_or_disabled_provider_raises(tmp_path):
    with pytest.raises(ValueError):
        repair.build_repair_invocation(_cfg(tmp_path), "ollama", _FINDINGS, str(tmp_path))
    disabled = Config(council_home=tmp_path, agents=[RosterEntry("claude", "claude", "lead", enabled=False)])
    with pytest.raises(ValueError):
        repair.build_repair_invocation(disabled, "claude", _FINDINGS, str(tmp_path))
