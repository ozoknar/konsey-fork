"""git-worktree isolation (Faz 3a) — pure planners + injected GitRunner (no real git)."""
from __future__ import annotations

from pathlib import Path

from council import worktree


class FakeGit:
    """Records argv; returns canned results (no real git)."""
    def __init__(self, status: str = "", diff: str = "+code", head: str = "basesha", ok: bool = True):
        self.calls: list[tuple] = []
        self.status, self.diff, self.head, self.ok = status, diff, head, ok

    def __call__(self, argv, *, cwd=None, timeout=60):
        self.calls.append((tuple(argv), cwd))
        if argv[:2] == ["rev-parse", "HEAD"]:
            return worktree.GitResult(self.head, 0, self.ok)
        if argv[:1] == ["status"]:
            return worktree.GitResult(self.status, 0, True)
        if argv[:2] == ["diff", "HEAD"]:
            return worktree.GitResult(self.diff, 0, True)
        return worktree.GitResult("", 0 if self.ok else 1, self.ok)


def test_plan_is_outside_repo_with_unique_branch(tmp_path):
    plan = worktree.plan_worktree(str(tmp_path / "data"), "sid123", "claude", "abc")
    assert plan.branch == "konsey/do/sid123/claude"
    assert plan.base_sha == "abc"
    # the worktree path is under data_home, NOT inside any repo working tree.
    assert Path(plan.path).resolve().is_relative_to((tmp_path / "data").resolve())
    assert "worktrees/sid123/claude" in plan.path


def test_argv_builders_shape():
    plan = worktree.plan_worktree("/d", "s", "codex", "SHA")
    assert worktree.add_argv(plan) == ["worktree", "add", "-b", "konsey/do/s/codex", plan.path, "SHA"]
    assert worktree.remove_argv(plan) == ["worktree", "remove", "--force", plan.path]
    assert worktree.delete_branch_argv(plan) == ["branch", "-D", "konsey/do/s/codex"]
    assert worktree.diff_argv() == ["diff", "HEAD"]


def test_provision_and_changed_and_diff_via_fake(tmp_path):
    g = FakeGit(status=" M council/cli.py\n?? new.py", diff="+hello")
    plan = worktree.plan_worktree(str(tmp_path), "s", "claude", "base")
    assert worktree.provision("/repo", plan, git=g) is True
    assert (tuple(worktree.add_argv(plan)), "/repo") in g.calls
    changed = worktree.changed_files(plan, git=g)
    assert all(Path(c).resolve().is_relative_to(Path(plan.path).resolve()) for c in changed)
    assert any(c.endswith("council/cli.py") for c in changed) and any(c.endswith("new.py") for c in changed)
    assert worktree.diff_text(plan, git=g) == "+hello"


def test_head_sha_and_is_dirty(tmp_path):
    assert worktree.head_sha("/repo", git=FakeGit(head="deadbeef")) == "deadbeef"
    assert worktree.is_dirty("/repo", git=FakeGit(status=" M x")) is True
    assert worktree.is_dirty("/repo", git=FakeGit(status="")) is False


def test_teardown_keep_vs_delete_branch(tmp_path):
    plan = worktree.plan_worktree("/d", "s", "claude", "b")
    g_keep = FakeGit()
    worktree.teardown("/repo", plan, keep_branch=True, git=g_keep)
    assert any(a[0] == tuple(worktree.remove_argv(plan)) for a in g_keep.calls)
    assert not any(a[0][:1] == ("branch",) for a in g_keep.calls)   # branch KEPT
    g_del = FakeGit()
    worktree.teardown("/repo", plan, keep_branch=False, git=g_del)
    assert any(a[0] == ("branch", "-D", plan.branch) for a in g_del.calls)   # branch DELETED
