"""Faz 3a real-work execution — proven WITHOUT a live agent or real git.

Locks the safety contract: producer≠verifier (success ONLY via a fresh acceptance rc==0;
the worker's self-report is ignored), no-acceptance → UNVERIFIED (never success), no-git /
no-provider / destructive-acceptance refusals, and the three default-OFF locks in `do`.
"""
from __future__ import annotations

import argparse

from council import execute, worktree
from council.config import Config, RosterEntry


class FakeGit:
    def __init__(self, status=" M f.py", diff="+x", head="basesha", ok=True):
        self.calls = []
        self.status, self.diff, self.head, self.ok = status, diff, head, ok

    def __call__(self, argv, *, cwd=None, timeout=60):
        self.calls.append(tuple(argv))
        if argv[:2] == ["rev-parse", "HEAD"]:
            return worktree.GitResult(self.head, 0, self.ok)
        if argv[:1] == ["status"]:
            return worktree.GitResult(self.status, 0, True)
        if argv[:2] == ["diff", "HEAD"]:
            return worktree.GitResult(self.diff, 0, True)
        return worktree.GitResult("", 0, True)


def _cfg(tmp_path, agents=None):
    # data_home OUTSIDE council_home (the real default is XDG ~/.local/share/council), so the
    # worktree lands outside the repo — matching production, not the inside-repo refusal case.
    return Config(council_home=tmp_path / "repo", data_home=tmp_path / "data",
                  agents=agents if agents is not None else [RosterEntry("claude", "claude", "lead", True)])


def _worker_ok(argv, env, *, cwd, timeout):
    return execute.repair.RepairRunResult("done — I edited the file", 0, True)


def _boom(*a, **k):
    raise AssertionError("worker runner must NOT be called")


def _spec(tmp_path, **kw):
    base = dict(task="add a docstring", repo_root=str(tmp_path / "repo"), acceptance_cmd="true", provider="claude")
    base.update(kw)
    return execute.WorkSpec(**base)


# --------------------------------------------------------------------------- #
# pick_work_provider — claude>codex; agy excluded                              #
# --------------------------------------------------------------------------- #

def test_pick_work_provider_excludes_agy(tmp_path, monkeypatch):
    monkeypatch.setattr(execute.shutil, "which", lambda *a, **k: "/usr/bin/x")
    cfg = _cfg(tmp_path, [RosterEntry("google", "agy", "researcher", True)])
    assert execute.pick_work_provider(cfg) is None       # agy is not a work provider
    cfg2 = _cfg(tmp_path, [RosterEntry("codex", "codex", "critic", True),
                           RosterEntry("claude", "claude", "lead", True)])
    assert execute.pick_work_provider(cfg2) == "claude"   # preference claude > codex


# --------------------------------------------------------------------------- #
# do_work — producer≠verifier + refusals                                       #
# --------------------------------------------------------------------------- #

def test_do_work_success_only_when_acceptance_passes(tmp_path):
    r = execute.do_work(_cfg(tmp_path), _spec(tmp_path), runner=_worker_ok,
                        git=FakeGit(), acceptance_fn=lambda p: 0)
    assert r.refused is False and r.tests_pass is True
    assert r.plan is not None and r.diff == "+x" and r.changed_files


def test_do_work_self_report_ignored_when_acceptance_fails(tmp_path):
    # worker exits 0 + says "done", but the fresh acceptance check fails → NOT verified.
    r = execute.do_work(_cfg(tmp_path), _spec(tmp_path), runner=_worker_ok,
                        git=FakeGit(), acceptance_fn=lambda p: 1)
    assert r.refused is False and r.tests_pass is False


def test_do_work_no_acceptance_is_unverified_not_success(tmp_path):
    r = execute.do_work(_cfg(tmp_path), _spec(tmp_path, acceptance_cmd=None), runner=_worker_ok,
                        git=FakeGit(), acceptance_fn=None)
    assert r.tests_pass is None        # tri-state: never silently a pass


def test_do_work_refuses_destructive_acceptance_before_running(tmp_path):
    r = execute.do_work(_cfg(tmp_path), _spec(tmp_path, acceptance_cmd="sudo rm -rf /"),
                        runner=_boom, git=FakeGit(), acceptance_fn=lambda p: 0)
    assert r.refused is True and "destructive" in (r.refused_reason or "")


def test_do_work_refuses_when_not_a_git_repo(tmp_path):
    r = execute.do_work(_cfg(tmp_path), _spec(tmp_path), runner=_boom,
                        git=FakeGit(ok=False), acceptance_fn=lambda p: 0)
    assert r.refused is True and "git" in (r.refused_reason or "")


def test_do_work_refuses_when_no_provider(tmp_path):
    r = execute.do_work(_cfg(tmp_path, agents=[]), _spec(tmp_path, provider=None),
                        runner=_boom, git=FakeGit(), acceptance_fn=lambda p: 0)
    assert r.refused is True and "provider" in (r.refused_reason or "")


# --------------------------------------------------------------------------- #
# council do — the three default-OFF locks + human-approved keep               #
# --------------------------------------------------------------------------- #

def _profile(tmp_path, sandbox="workspace-write"):
    p = tmp_path / "council.local.toml"
    p.write_text(
        f'owner = "t"\ncouncil_home = "{tmp_path}"\nexec_sandbox = "{sandbox}"\n'
        '[[agents]]\nname = "claude"\ncli = "claude"\nrole = "lead"\nenabled = true\n',
        encoding="utf-8")
    return p


def _do(profile, monkeypatch, capsys, *, accept="pytest -q", force=False, keep=False,
        exec_env=False, task="add a docstring", provider=None):
    for v in ("LC_ALL", "LC_MESSAGES", "LANG", "KONSEY_LOCALE", "KONSEY_EXEC"):
        monkeypatch.delenv(v, raising=False)
    if exec_env:
        monkeypatch.setenv("KONSEY_EXEC", "1")
    monkeypatch.setenv("COUNCIL_CONFIG", str(profile))
    monkeypatch.setenv("COUNCIL_DATA_HOME", str(profile.parent / "d"))
    from council.cli import cmd_do
    rc = cmd_do(argparse.Namespace(task=task, accept=accept, provider=provider, force=force, keep=keep))
    return rc, capsys.readouterr()


def test_do_lock1_sandbox_off_never_spawns(tmp_path, monkeypatch, capsys):
    rc, cap = _do(_profile(tmp_path, sandbox="off"), monkeypatch, capsys, exec_env=True, force=True)
    assert rc == 2 and "exec_sandbox" in cap.err


def test_do_requires_accept(tmp_path, monkeypatch, capsys):
    rc, cap = _do(_profile(tmp_path), monkeypatch, capsys, accept=None, exec_env=True)
    assert rc == 2 and "--accept" in cap.err


def test_do_lock2_opt_out_default_off(tmp_path, monkeypatch, capsys):
    rc, cap = _do(_profile(tmp_path), monkeypatch, capsys, exec_env=False, force=False)
    assert rc == 2 and "opt-in" in cap.err


def test_do_verified_keep_requires_human_then_keeps_branch(tmp_path, monkeypatch, capsys):
    # monkeypatch do_work → a verified result; assert keep commits + keeps the branch.
    plan = worktree.plan_worktree(str(tmp_path / "d"), "sid", "claude", "base")
    monkeypatch.setattr(execute, "do_work",
                        lambda cfg, spec, **k: execute.WorkResult("claude", 0, ["f.py"], "+x", True, plan=plan))
    kept = {}
    monkeypatch.setattr(worktree, "commit_all", lambda p, m, **k: kept.setdefault("commit", True) or True)
    monkeypatch.setattr(worktree, "teardown", lambda repo, p, *, keep_branch, **k: kept.setdefault("keep", keep_branch))
    rc, cap = _do(_profile(tmp_path), monkeypatch, capsys, exec_env=True, force=True, keep=True)
    assert rc == 0
    assert kept.get("commit") is True and kept.get("keep") is True   # committed + branch KEPT for review
    assert plan.branch in cap.out


def test_do_force_alone_does_NOT_keep(tmp_path, monkeypatch, capsys):
    # --force opts in to RUNNING only; without --keep (and non-TTY confirm=False) a verified
    # result is DISCARDED, not auto-kept (Codex Faz3a finding).
    plan = worktree.plan_worktree(str(tmp_path / "d"), "sid", "claude", "base")
    monkeypatch.setattr(execute, "do_work",
                        lambda cfg, spec, **k: execute.WorkResult("claude", 0, ["f.py"], "+x", True, plan=plan))
    seen = {}
    monkeypatch.setattr(worktree, "commit_all", lambda p, m, **k: seen.setdefault("commit", True) or True)
    monkeypatch.setattr(worktree, "teardown", lambda repo, p, *, keep_branch, **k: seen.__setitem__("keep", keep_branch))
    rc, cap = _do(_profile(tmp_path), monkeypatch, capsys, exec_env=True, force=True, keep=False)
    assert rc == 0
    assert "commit" not in seen           # NEVER committed without an explicit keep
    assert seen.get("keep") is False      # branch discarded


def test_do_commit_failure_returns_2(tmp_path, monkeypatch, capsys):
    plan = worktree.plan_worktree(str(tmp_path / "d"), "sid", "claude", "base")
    monkeypatch.setattr(execute, "do_work",
                        lambda cfg, spec, **k: execute.WorkResult("claude", 0, ["f.py"], "+x", True, plan=plan))
    monkeypatch.setattr(worktree, "commit_all", lambda p, m, **k: False)   # commit FAILS
    td = {}
    monkeypatch.setattr(worktree, "teardown", lambda repo, p, *, keep_branch, **k: td.__setitem__("keep", keep_branch))
    rc, cap = _do(_profile(tmp_path), monkeypatch, capsys, exec_env=True, force=True, keep=True)
    assert rc == 2 and td.get("keep") is False   # no durable artifact → not "kept", branch removed


def test_do_preflight_failure_is_fail_closed(tmp_path, monkeypatch, capsys):
    import council.gateway as gw
    def _boom(*a, **k):
        raise RuntimeError("classifier down")
    monkeypatch.setattr(gw, "preflight", _boom)
    monkeypatch.setattr(execute, "do_work", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not run")))
    rc, cap = _do(_profile(tmp_path), monkeypatch, capsys, exec_env=True, force=True)
    assert rc == 2   # a classifier error REFUSES (never downgrades to internal + runs)


def test_do_work_forced_google_provider_refused(tmp_path):
    cfg = _cfg(tmp_path, [RosterEntry("google", "agy", "researcher", True)])
    r = execute.do_work(cfg, _spec(tmp_path, provider="google"), runner=_boom,
                        git=FakeGit(), acceptance_fn=lambda p: 0)
    assert r.refused is True and "not allowed for real work" in (r.refused_reason or "")


def test_do_work_refuses_explicit_provider_not_enabled(tmp_path):
    # --provider claude while only codex is enabled: refuse BEFORE provisioning (no leaked
    # worktree / open session), not crash mid-flow (Codex Faz3a round-2 finding).
    cfg = _cfg(tmp_path, [RosterEntry("codex", "codex", "critic", True)])
    g = FakeGit()
    r = execute.do_work(cfg, _spec(tmp_path, provider="claude"), runner=_boom, git=g, acceptance_fn=lambda p: 0)
    assert r.refused is True and "enabled roster agent" in (r.refused_reason or "")
    assert not any(a[:1] == ("worktree",) for a in g.calls)   # never provisioned


def test_do_work_refuses_worktree_inside_repo(tmp_path):
    # data_home INSIDE the repo (repo_root) → worktree would land in the checkout → refused.
    cfg = Config(council_home=tmp_path, data_home=tmp_path / "d",
                 agents=[RosterEntry("claude", "claude", "lead", True)])
    r = execute.do_work(cfg, _spec(tmp_path, repo_root=str(tmp_path)),
                        runner=_boom, git=FakeGit(), acceptance_fn=lambda p: 0)
    assert r.refused is True and "INSIDE the repo" in (r.refused_reason or "")
