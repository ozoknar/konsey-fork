"""Adapter node-isolation ENFORCEMENT is shipped, not deferred (Constitution Art. 2.6).

These lock in the evidence behind the D4 honesty fix: ``adapters.GenericCLIAdapter._argv``
actually injects the per-provider isolation flags (so the docs may state enforcement is
shipped, not "deferred to PR2"). Deterministic, no live CLI call — we assert the argv the
adapter WOULD run, plus the ``unsafe_inherit_provider_config`` opt-out that disables it.

Scope honesty: this proves the isolation argv/env is INJECTED. Whether each provider CLI
then fully suppresses every host-config surface is that CLI's own flag semantics — the
behavioural cross-surface smoke is tracked in KNOWN_ISSUES, not claimed here.
"""
from __future__ import annotations

from pathlib import Path

from council.adapters import GenericCLIAdapter, _seed_isolated_auth
from council.config import ROLE_LEAD, Config, RosterEntry


def _cfg(**kw) -> Config:
    return Config(agents=[RosterEntry("claude", "claude", ROLE_LEAD),
                          RosterEntry("codex", "codex", ROLE_LEAD)], **kw)


def test_claude_argv_injects_isolation_by_default():
    argv = GenericCLIAdapter("claude", "claude", _cfg())._argv("hi", 180)
    assert "--strict-mcp-config" in argv
    assert "--setting-sources" in argv
    # the EMPTY string loads no setting sources (isolation); "none" is INVALID and breaks
    # the real claude CLI — this asserts the live-verified value, not the broken one.
    assert argv[argv.index("--setting-sources") + 1] == ""


def test_codex_argv_injects_isolation_by_default():
    argv = GenericCLIAdapter("codex", "codex", _cfg())._argv("hi", 180)
    assert "--ignore-user-config" in argv
    assert "project_doc_max_bytes=0" in argv
    # the doc-suppression flag is injected BEFORE the exec subcommand
    assert argv.index("project_doc_max_bytes=0") < argv.index("exec")


def test_unsafe_inherit_opt_out_disables_isolation():
    cfg = _cfg(unsafe_inherit_provider_config=True)
    claude = GenericCLIAdapter("claude", "claude", cfg)._argv("hi", 180)
    codex = GenericCLIAdapter("codex", "codex", cfg)._argv("hi", 180)
    assert "--strict-mcp-config" not in claude
    assert "--ignore-user-config" not in codex


def test_codex_isolated_codex_home_when_temp_home_given():
    argv = GenericCLIAdapter("codex", "codex", _cfg())._argv("hi", 180, temp_home="/tmp/iso-xyz")
    assert "-C" in argv and "/tmp/iso-xyz" in argv     # isolated working dir for the doc walk


# ── Credential re-seeding into the isolated home (auth survives isolation) ──────────
# A clean HOME/CODEX_HOME suppresses host-config leakage but also strips the provider's
# credentials, so the node 401s/"Authentication required" and silently drops the quorum.
# _seed_isolated_auth symlinks back ONLY the credentials, never an instruction file.

def _make_fake_home(home: Path) -> None:
    (home / ".codex").mkdir(parents=True)
    (home / ".codex" / "auth.json").write_text("CRED")
    (home / ".codex" / "config.toml").write_text("INSTR")          # must NOT be seeded
    g = home / ".gemini"
    (g / "antigravity-cli").mkdir(parents=True)
    (g / "oauth_creds.json").write_text("CRED")
    (g / "google_accounts.json").write_text("CRED")
    (g / "GEMINI.md").write_text("INSTR")                          # leak — must NOT be seeded
    (g / "antigravity-cli" / "settings.json").write_text("INSTR")  # leak — must NOT be seeded
    (g / "antigravity-cli" / "state.pb").write_text("CRED")        # non-leak — seeded
    (home / "Library" / "Keychains").mkdir(parents=True)
    (home / "Library" / "Keychains" / "login.keychain-db").write_text("CRED")


def test_seed_isolated_auth_codex_links_only_auth_json(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"; fake_home.mkdir()
    _make_fake_home(fake_home)
    monkeypatch.setenv("HOME", str(fake_home))
    temp = tmp_path / "isolated"; temp.mkdir()
    _seed_isolated_auth("codex", str(temp))
    assert (temp / "auth.json").read_text() == "CRED"   # CODEX_HOME/auth.json restored
    assert not (temp / "config.toml").exists()          # --ignore-user-config covers instructions


def test_seed_isolated_auth_google_restores_creds_and_curates_leaks(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"; fake_home.mkdir()
    _make_fake_home(fake_home)
    monkeypatch.setenv("HOME", str(fake_home))
    temp = tmp_path / "isolated"; temp.mkdir()
    _seed_isolated_auth("google", str(temp))
    # credentials restored (auth works)
    assert (temp / ".gemini" / "oauth_creds.json").read_text() == "CRED"
    assert (temp / ".gemini" / "google_accounts.json").exists()
    assert (temp / ".gemini" / "antigravity-cli" / "state.pb").exists()
    assert (temp / "Library" / "Keychains" / "login.keychain-db").read_text() == "CRED"
    # the three documented leak files stay suppressed (isolation still holds)
    assert not (temp / ".gemini" / "GEMINI.md").exists()
    assert not (temp / ".gemini" / "antigravity-cli" / "settings.json").exists()


def test_seed_isolated_auth_missing_source_is_noop(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "empty"))   # no credentials anywhere
    (tmp_path / "empty").mkdir()
    temp = tmp_path / "isolated"; temp.mkdir()
    _seed_isolated_auth("codex", str(temp))    # must not raise
    _seed_isolated_auth("google", str(temp))   # must not raise
    assert not (temp / "auth.json").exists()
    assert not (temp / ".gemini").exists()
