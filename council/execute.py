"""General real-work execution (Faz 3, stage 3a) — a thin generalization of the Faz 2
repair primitive from "fix the install" to an ARBITRARY task.

``do_work`` provisions a per-worker git worktree (isolated, outside the repo), runs ONE
tool-ON provider in it to perform the task, then proves success ONLY by re-running a real
acceptance command itself (producer≠verifier — the worker's "done" is not evidence). It
returns a ``WorkResult`` (data); the caller (``council do``) shows the diff and merges the
verified branch ONLY after explicit human approval. Default OFF behind ``exec_sandbox``.

Reuses, unchanged, the proven repair.py machinery: the per-provider tool-ON argv profiles,
the fail-closed env allow-list, the secret-scrub, the exec_policy destructive gate, the
outside-scope path gate, the injectable runner, and the append-only audit. NO copy.
"""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import audit, gateway, repair, worktree
from .config import Config

# Real-work providers: only the finely-scopable sandboxes, most-scopable first. agy/google
# is deliberately excluded as a work worker (it cannot finely scope) — owner decision.
_WORK_PREFERENCE: tuple[str, ...] = ("claude", "codex")


@dataclass(frozen=True)
class WorkSpec:
    task: str
    repo_root: str
    acceptance_cmd: str | None = None
    risk: str = "internal"
    provider: str | None = None      # None → pick_work_provider


@dataclass
class WorkResult:
    provider: str | None
    worker_exit: int
    changed_files: list[str]
    diff: str
    tests_pass: bool | None          # tri-state: None = no acceptance cmd → UNVERIFIED, never success
    refused: bool = False
    refused_reason: str | None = None
    summary: str = ""
    plan: worktree.WorktreePlan | None = None   # worktree+branch left for the caller to finalize
    evidence: list[dict] = field(default_factory=list)


def pick_work_provider(cfg: Config) -> str | None:
    """First ENABLED roster agent with a tool-ON profile that is finely-scopable and on
    PATH (claude, then codex). None → cannot do real work."""
    search = os.pathsep.join([cfg.extra_path, os.environ.get("PATH", "")])
    by_name = {a.name: a for a in cfg.agents if a.enabled}
    for name in _WORK_PREFERENCE:
        a = by_name.get(name)
        if a and name in repair.WORKER_PROFILES and shutil.which(a.cli, path=search):
            return name
    return None


def _default_acceptance(cmd: str, timeout: int) -> Callable[[str], int]:
    """A no-shell acceptance runner (producer≠verifier): the HARNESS runs the real check
    in the worktree and returns its exit code. shlex.split — never shell=True."""
    def _run(path: str) -> int:
        try:
            p = subprocess.run(shlex.split(cmd), cwd=path, capture_output=True, text=True, timeout=timeout)
            return p.returncode
        except Exception:
            return 1
    return _run


def do_work(
    cfg: Config, spec: WorkSpec,
    *,
    runner: repair.RepairRunner = repair._subprocess_runner,
    git: worktree.GitRunner = worktree._git_runner,
    acceptance_fn: Callable[[str], int] | None = None,
    timeout: int = 240,
) -> WorkResult:
    """Do ``spec.task`` in an isolated worktree with ONE tool-ON provider; verify by a
    fresh acceptance run. Returns a WorkResult; the worktree+branch are left for the caller
    to finalize (commit+keep on human approval, or discard). Tears down itself on refusal."""
    repo = str(Path(spec.repo_root).resolve())
    base = worktree.head_sha(repo, git=git)
    if base is None:
        return WorkResult(None, 127, [], "", None, refused=True, refused_reason="not a git repository")

    provider = spec.provider or pick_work_provider(cfg)
    if provider is None:
        return WorkResult(None, 127, [], "", None, refused=True, refused_reason="no scopable provider on PATH")
    # A forced --provider must STILL be a finely-scopable work provider (claude/codex) —
    # never agy/google, even when the operator names it explicitly (Codex Faz3a finding).
    if provider not in _WORK_PREFERENCE:
        return WorkResult(provider, 127, [], "", None, refused=True,
                          refused_reason=f"provider '{provider}' is not allowed for real work (claude/codex only)")
    # Validate the provider is an ENABLED roster agent BEFORE opening a session or
    # provisioning — else build_work_invocation would raise mid-flow, leaking a worktree +
    # an open audit session (Codex Faz3a round-2 finding).
    if not any(a.name == provider and a.enabled for a in cfg.agents):
        return WorkResult(provider, 127, [], "", None, refused=True,
                          refused_reason=f"provider '{provider}' is not an enabled roster agent")

    sid = audit.start_session(f"do: {spec.task[:60]}", spec.risk,
                              gateway.BUDGET.get(spec.risk, gateway.BUDGET["internal"]), cfg=cfg)
    plan = worktree.plan_worktree(str(cfg.data_home), sid, provider, base)

    def _refuse(reason: str, vtype: str) -> WorkResult:
        audit.incident(sid, vtype, reason, cfg=cfg)
        worktree.teardown(repo, plan, keep_branch=False, git=git)
        audit.end_session(sid, "refused", 0.0, cfg=cfg)
        return WorkResult(provider, 1, [], "", None, refused=True, refused_reason=reason)

    # The worktree MUST live outside the repo working tree (isolation). data_home is
    # env/config-controlled, so verify it — refuse if it would land inside the checkout.
    if Path(plan.path).resolve().is_relative_to(Path(repo).resolve()):
        return _refuse(f"worktree path is INSIDE the repo ({plan.path}) — set COUNCIL_DATA_HOME outside", "work_worktree_inside")
    if not worktree.provision(repo, plan, git=git):
        audit.end_session(sid, "provision_failed", 0.0, cfg=cfg)
        return WorkResult(provider, 1, [], "", None, refused=True, refused_reason="worktree provision failed")

    try:
        inv = repair.build_work_invocation(cfg, provider, spec.task, plan.path)
    except (ValueError, repair.RepairError) as exc:
        return _refuse(f"could not build worker invocation: {exc}", "work_build_failed")
    cmd_for_gate = " ".join(tok for tok in inv.argv if tok != inv.prompt)
    verdict, rules = repair.gate_command(cmd_for_gate)
    if verdict != "allowed":
        return _refuse(f"worker argv hit the hard-floor: {rules}", "work_refused")
    # The acceptance command must itself be non-destructive (a verifier can't run sudo/rm).
    if spec.acceptance_cmd and repair.gate_command(spec.acceptance_cmd)[0] != "allowed":
        return _refuse(f"acceptance command is destructive: {spec.acceptance_cmd}", "work_accept_refused")

    result = runner(inv.argv, inv.env, cwd=plan.path, timeout=timeout)

    changed = worktree.changed_files(plan, git=git)
    pverdict, outside = repair.gate_paths(changed, plan.path)
    if pverdict != "allowed":
        return _refuse(f"worker wrote outside the worktree: {outside}", "work_outside_scope")

    tests_pass: bool | None = None
    evidence: list[dict] = []
    if spec.acceptance_cmd:
        acc = acceptance_fn or _default_acceptance(spec.acceptance_cmd, timeout)
        acc_rc = acc(plan.path)
        tests_pass = acc_rc == 0
        evidence.append({"acceptance_cmd": spec.acceptance_cmd, "rc": acc_rc, "verified_by": "harness"})
        audit.evidence(sid, "acceptance_cmd", f"rc={acc_rc} cmd={spec.acceptance_cmd}",
                       produced_by=provider, verified_by="harness", cfg=cfg)

    diff = worktree.diff_text(plan, git=git)
    rel_changed = [str(Path(p).resolve().relative_to(Path(plan.path).resolve()))
                   for p in changed if Path(p).resolve().is_relative_to(Path(plan.path).resolve())]
    audit.message(sid, "orchestrator", "work_attempt", repair._scrub_manifest({
        "provider": provider, "worktree": plan.path, "branch": plan.branch, "base_sha": base,
        "env_allowlist_keys": sorted(inv.env.keys()), "worker_exit": result.exit_code,
        "changed_files": rel_changed, "tests_pass": tests_pass, "acceptance_cmd": spec.acceptance_cmd,
    }), cfg=cfg)
    audit.end_session(sid, "worked" if tests_pass else "unverified", 0.0, cfg=cfg)

    return WorkResult(provider, result.exit_code, rel_changed, diff, tests_pass,
                      refused=False, summary=result.text[:800], plan=plan, evidence=evidence)
