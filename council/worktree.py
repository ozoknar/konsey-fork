"""Per-worker git worktree isolation (Faz 3).

A tool-ON worker must edit a *copy*, never the live checkout. This module provisions one
``git worktree`` per worker on its own branch, off the current HEAD, **outside** the repo
working tree (under ``data_home``), captures the worker's diff onto that branch, and tears
the worktree down — so a failed or escaped attempt never touches the user's working copy
(reversibility, Constitution Md.2.5).

Pure + injectable: the argv builders are side-effect-free, and every git call goes through
an injected ``GitRunner`` (default = real subprocess), so the whole flow is unit-testable
with a fake recorder and CI never shells out to git.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class WorktreePlan:
    path: str        # the worktree dir (outside the repo, under data_home)
    branch: str      # the isolated branch the worker's commit lands on
    base_sha: str    # HEAD it was forked from


@dataclass(frozen=True)
class GitResult:
    stdout: str
    exit_code: int
    ok: bool


class GitRunner(Protocol):
    def __call__(self, argv: list[str], *, cwd: str | None = None, timeout: int = 60) -> GitResult: ...


def _git_runner(argv: list[str], *, cwd: str | None = None, timeout: int = 60) -> GitResult:
    """Default real git runner; never raises."""
    try:
        p = subprocess.run(["git", *argv], capture_output=True, text=True, timeout=timeout, cwd=cwd)
        return GitResult((p.stdout or "").strip(), p.returncode, p.returncode == 0)
    except subprocess.TimeoutExpired:
        return GitResult(f"[git TIMEOUT {timeout}s]", 124, False)
    except FileNotFoundError:
        return GitResult("[git not found]", 127, False)


# --- pure planners / argv builders ----------------------------------------------------
def plan_worktree(data_home: str, session_id: str, provider: str, base_sha: str) -> WorktreePlan:
    """Compute a collision-free worktree path (OUTSIDE the repo, under data_home) + a
    unique isolated branch. Pure — creates nothing."""
    path = str(Path(data_home).resolve() / "worktrees" / session_id / provider)
    branch = f"konsey/do/{session_id}/{provider}"
    return WorktreePlan(path=path, branch=branch, base_sha=base_sha)


def add_argv(plan: WorktreePlan) -> list[str]:
    return ["worktree", "add", "-b", plan.branch, plan.path, plan.base_sha]


def remove_argv(plan: WorktreePlan) -> list[str]:
    return ["worktree", "remove", "--force", plan.path]


def delete_branch_argv(plan: WorktreePlan) -> list[str]:
    return ["branch", "-D", plan.branch]


def diff_argv() -> list[str]:
    return ["diff", "HEAD"]


def changed_argv() -> list[str]:
    return ["status", "--porcelain"]


def commit_argv(message: str) -> list[str]:
    # add + commit are two calls; expose the commit argv (caller runs `add -A` first).
    return ["commit", "-m", message]


# --- impure orchestration (injected GitRunner) ----------------------------------------
def head_sha(repo: str, *, git: GitRunner = _git_runner) -> str | None:
    r = git(["rev-parse", "HEAD"], cwd=repo)
    return r.stdout if r.ok else None


def is_dirty(repo: str, *, git: GitRunner = _git_runner) -> bool:
    r = git(["status", "--porcelain"], cwd=repo)
    return bool(r.ok and r.stdout.strip())


def provision(repo: str, plan: WorktreePlan, *, git: GitRunner = _git_runner) -> bool:
    """`git worktree add -b <branch> <path> <base_sha>`. Returns True on success."""
    Path(plan.path).parent.mkdir(parents=True, exist_ok=True)
    return git(add_argv(plan), cwd=repo).ok


def changed_files(plan: WorktreePlan, *, git: GitRunner = _git_runner) -> list[str]:
    """Absolute paths git reports changed inside the worktree (IN-worktree only — does
    not see writes outside it; the provider sandbox is the real out-of-tree containment)."""
    r = git(changed_argv(), cwd=plan.path)
    out: list[str] = []
    if r.ok:
        for line in r.stdout.splitlines():
            rel = line[3:].strip().strip('"')
            if rel:
                out.append(str(Path(plan.path) / rel))
    return out


def diff_text(plan: WorktreePlan, *, git: GitRunner = _git_runner) -> str:
    r = git(diff_argv(), cwd=plan.path)
    return r.stdout if r.ok else ""


def commit_all(plan: WorktreePlan, message: str, *, git: GitRunner = _git_runner) -> bool:
    """Stage + commit the worker's changes onto the isolated branch so the artifact
    survives worktree removal (the durable, reviewable result)."""
    if not git(["add", "-A"], cwd=plan.path).ok:
        return False
    return git(commit_argv(message), cwd=plan.path).ok


def teardown(repo: str, plan: WorktreePlan, *, keep_branch: bool, git: GitRunner = _git_runner) -> None:
    """Remove the worktree; delete its branch unless ``keep_branch`` (the human kept a
    verified result for review/PR). Best-effort — never raises."""
    git(remove_argv(plan), cwd=repo)
    if not keep_branch:
        git(delete_branch_argv(plan), cwd=repo)
