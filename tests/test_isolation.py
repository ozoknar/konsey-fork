"""Node execution isolation — detection tests (Constitution Article 2.6).

Evidence > consensus: every assertion is a real call against ``council.isolation``
and real captured ``cmd_doctor`` stdout — no stubs. These lock in the PR1 contract:
detection is deterministic (only existing paths reported), the ``node:count`` summary
is stable, and ``council doctor`` surfaces a leak as a **non-fatal ⚠** (never a ✗),
matching the regime-warning render contract.

Scope note: these tests cover the DETECTION layer. The enforcement layer (isolated
argv/env/cwd injected in the adapter) is shipped separately and asserted in
``tests/test_adapters_isolation.py`` — see KNOWN_ISSUES.md (node-isolation).
"""
from __future__ import annotations

import argparse
from pathlib import Path

from council.cli import _doctor_host_isolation, cmd_doctor, cmd_init
from council.config import Config
from council.isolation import scan_host_ai_config, summarize


def _touch(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x", encoding="utf-8")


# --------------------------------------------------------------------------- #
# scan_host_ai_config — deterministic, existence-based detection               #
# --------------------------------------------------------------------------- #

def test_empty_home_and_cwd_find_nothing(tmp_path):
    home, cwd = tmp_path / "home", tmp_path / "cwd"
    home.mkdir()
    cwd.mkdir()
    assert scan_host_ai_config(home, cwd) == []


def test_detects_home_and_cwd_signatures(tmp_path):
    home, cwd = tmp_path / "home", tmp_path / "cwd"
    _touch(home / ".claude" / "CLAUDE.md")    # claude / instructions
    _touch(home / ".codex" / "AGENTS.md")     # codex / instructions
    _touch(cwd / "AGENTS.md")                 # codex / instructions (project)
    _touch(cwd / "GEMINI.md")                 # google / instructions (project)
    found = scan_host_ai_config(home, cwd)
    labels = {f.label for f in found}
    assert "global Claude memory" in labels
    assert "global Codex instructions" in labels
    assert "project Codex instructions" in labels
    assert "project Gemini memory" in labels
    assert {"claude", "codex", "google"} <= {f.pollutes for f in found}


def test_only_existing_paths_are_reported(tmp_path):
    home, cwd = tmp_path / "h", tmp_path / "c"
    home.mkdir()
    cwd.mkdir()
    _touch(home / ".claude" / "CLAUDE.md")
    found = scan_host_ai_config(home, cwd)
    assert len(found) == 1
    assert found[0].pollutes == "claude"
    assert found[0].path == home / ".claude" / "CLAUDE.md"


def test_cursorrules_pollutes_all_nodes(tmp_path):
    home, cwd = tmp_path / "h", tmp_path / "c"
    home.mkdir()
    _touch(cwd / ".cursorrules")
    found = scan_host_ai_config(home, cwd)
    assert [f.pollutes for f in found] == ["all"]


def test_detects_project_config_in_a_parent_directory(tmp_path):
    """The blocker found in cross-verify: provider CLIs walk cwd UPWARD, so a config
    in an ancestor still leaks. Running from a deep subdir must still detect it."""
    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "proj"
    deep = project / "src" / "pkg"
    deep.mkdir(parents=True)
    _touch(project / "AGENTS.md")   # two levels above cwd
    found = scan_host_ai_config(home, deep)
    assert any(f.pollutes == "codex" and f.path == project / "AGENTS.md" for f in found)


def test_directory_named_like_a_config_is_not_a_leak(tmp_path):
    """A *directory* named CLAUDE.md does not leak — is_file(), not exists()."""
    home, cwd = tmp_path / "h", tmp_path / "c"
    home.mkdir()
    cwd.mkdir()
    (cwd / "CLAUDE.md").mkdir()      # a directory, not a memory file
    assert scan_host_ai_config(home, cwd) == []


def test_broken_symlink_is_not_a_leak(tmp_path):
    home, cwd = tmp_path / "h", tmp_path / "c"
    home.mkdir()
    cwd.mkdir()
    (cwd / "AGENTS.md").symlink_to(tmp_path / "does-not-exist")
    assert scan_host_ai_config(home, cwd) == []


def test_symlink_to_a_real_file_is_detected(tmp_path):
    home, cwd = tmp_path / "h", tmp_path / "c"
    home.mkdir()
    cwd.mkdir()
    real = tmp_path / "real_agents.md"
    real.write_text("x", encoding="utf-8")
    (cwd / "AGENTS.md").symlink_to(real)
    found = scan_host_ai_config(home, cwd)
    assert [f.pollutes for f in found] == ["codex"]


def test_same_file_is_not_double_counted(tmp_path):
    """A file reachable both as a HOME signature and via the cwd parent-walk (cwd under
    home) is reported once — dedupe by resolved path."""
    home = tmp_path / "home"
    _touch(home / ".claude" / "settings.json")   # HOME signature
    cwd = home / "work"
    cwd.mkdir(parents=True)
    found = scan_host_ai_config(home, cwd)
    paths = [f.path.resolve() for f in found]
    assert len(paths) == len(set(paths))   # no duplicates


# --------------------------------------------------------------------------- #
# summarize — stable node ordering                                             #
# --------------------------------------------------------------------------- #

def test_summarize_is_empty_for_no_findings():
    assert summarize([]) == ""


def test_summarize_stable_node_order(tmp_path):
    home, cwd = tmp_path / "h", tmp_path / "c"
    _touch(home / ".claude" / "CLAUDE.md")       # claude
    _touch(home / ".claude" / "settings.json")   # claude (hooks)
    _touch(home / ".codex" / "AGENTS.md")        # codex
    _touch(cwd / ".cursorrules")                  # all
    # Order is claude, codex, google, all — never insertion/dict order.
    assert summarize(scan_host_ai_config(home, cwd)) == "claude:2 codex:1 all:1"


# --------------------------------------------------------------------------- #
# council doctor — non-fatal ⚠ on leak, ✓ on clean                            #
# --------------------------------------------------------------------------- #

def _profile(tmp_path) -> Path:
    p = tmp_path / "council.local.toml"
    p.write_text(f'owner = "tester"\ncouncil_home = "{tmp_path}"\n', encoding="utf-8")
    return p


def _doctor(profile, fake_home, fake_cwd, monkeypatch, capsys):
    monkeypatch.setenv("COUNCIL_CONFIG", str(profile))
    monkeypatch.setenv("HOME", str(fake_home))   # os.path.expanduser("~") honours $HOME
    monkeypatch.chdir(fake_cwd)
    rc = cmd_doctor(argparse.Namespace(fix=False))
    return rc, capsys.readouterr().out


def test_doctor_reports_clean_when_no_host_config(tmp_path, monkeypatch, capsys):
    home, cwd = tmp_path / "home", tmp_path / "cwd"
    home.mkdir()
    cwd.mkdir()
    _, out = _doctor(_profile(tmp_path), home, cwd, monkeypatch, capsys)
    assert "no host AI-config detected that would leak" in out
    assert "would leak into provider nodes" not in out


def test_doctor_leak_is_a_nonfatal_warning(tmp_path, monkeypatch, capsys):
    home, cwd = tmp_path / "home", tmp_path / "cwd"
    _touch(home / ".claude" / "CLAUDE.md")
    _touch(cwd / "AGENTS.md")
    _, out = _doctor(_profile(tmp_path), home, cwd, monkeypatch, capsys)
    leak_lines = [ln for ln in out.splitlines() if "would leak into provider nodes" in ln]
    assert leak_lines, out
    for ln in leak_lines:
        assert ln.lstrip().startswith("⚠")    # rendered as a warning...
        assert "✗" not in ln                   # ...never a critical failure
    assert "claude:1 codex:1" in out


def test_isolation_check_is_never_critical(tmp_path, monkeypatch):
    """Non-fatality, proven directly at the source (more robust than asserting the
    full `cmd_doctor` rc, which legitimately returns 1 on a roster-less / no-CLI test
    host): the isolation check must only ever append passing (ok=True) lines."""
    home, cwd = tmp_path / "home", tmp_path / "cwd"
    _touch(home / ".claude" / "CLAUDE.md")
    _touch(cwd / "AGENTS.md")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(cwd)
    results: list[tuple[bool, str]] = []
    _doctor_host_isolation(Config(council_home=tmp_path), results)
    assert results, "isolation check produced no line"
    assert all(ok is True for ok, _ in results)   # never a (False) critical line
    assert any("would leak into provider nodes" in line for _, line in results)


def test_isolation_check_survives_a_scan_exception(tmp_path, monkeypatch):
    """The scan probes untrusted host filesystem state; if it raises, doctor must not
    crash and must not emit a misleading 'clean' — it skips silently."""
    def _boom(*_a, **_k):
        raise OSError("hostile host fs")
    monkeypatch.setattr("council.isolation.scan_host_ai_config", _boom)
    results: list[tuple[bool, str]] = []
    _doctor_host_isolation(Config(council_home=tmp_path), results)   # must not raise
    assert results == []   # skipped, neither a leak nor a false "clean"


# --------------------------------------------------------------------------- #
# council init — install-time host-config listing + degraded path              #
# --------------------------------------------------------------------------- #

def _init(tmp_path, fake_home, fake_cwd, monkeypatch, capsys):
    monkeypatch.setenv("COUNCIL_HOME", str(tmp_path / "chome"))
    monkeypatch.delenv("COUNCIL_CONFIG", raising=False)
    # Pin English so these assertions are locale-deterministic regardless of the host's
    # $LANG (init is now Turkish-first when $LANG is tr* — Faz 0).
    for v in ("LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.chdir(fake_cwd)
    rc = cmd_init(argparse.Namespace(quick=True, reconfigure=False, locale="en"))
    return rc, capsys.readouterr().out


def test_cmd_init_lists_host_config_at_install_time(tmp_path, monkeypatch, capsys):
    fake_home, fake_cwd = tmp_path / "home", tmp_path / "cwd"
    _touch(fake_home / ".codex" / "AGENTS.md")
    fake_cwd.mkdir()
    rc, out = _init(tmp_path, fake_home, fake_cwd, monkeypatch, capsys)
    assert rc == 0
    assert "Host AI-config scan" in out
    assert "would leak into node 'codex'" in out


def test_cmd_init_degrades_safely_when_scan_raises(tmp_path, monkeypatch, capsys):
    fake_home, fake_cwd = tmp_path / "home", tmp_path / "cwd"
    fake_home.mkdir()
    fake_cwd.mkdir()

    def _boom(*_a, **_k):
        raise RuntimeError("detector blew up")
    monkeypatch.setattr("council.isolation.scan_host_ai_config", _boom)
    rc, out = _init(tmp_path, fake_home, fake_cwd, monkeypatch, capsys)
    assert rc == 0   # init never fails because the optional scan did
    # Evidence standard (Art 2.1): a failed scan must NOT be reported as clean.
    assert "could NOT prove the host is clean" in out
    assert "no host AI-config detected" not in out


def test_does_not_walk_above_git_repo_root(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "proj"
    repo_root = project / "repo"
    deep = repo_root / "src" / "pkg"
    deep.mkdir(parents=True)

    # Put a .git folder in repo_root to establish a boundary
    (repo_root / ".git").mkdir()

    # Put a project config in repo_root (should be detected)
    _touch(repo_root / "AGENTS.md")

    # Put a project config outside the repo root, in project/ (should NOT be detected)
    _touch(project / "GEMINI.md")

    found = scan_host_ai_config(home, deep)
    labels = {f.label for f in found}
    assert "project Codex instructions" in labels
    assert "project Gemini memory" not in labels

