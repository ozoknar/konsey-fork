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

from council.adapters import GenericCLIAdapter
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
