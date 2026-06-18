"""Project mode — the council works a whole task board end-to-end (Constitution Art. 6/7).

The base 9-state loop (``graph.py``) handles ONE task and then hands control back. This
driver extends that to a multi-task project so the agent team stays engaged through the
whole job: for every task on the :class:`~council.artifacts.TaskLedger` it runs a small
``claim → produce → cross-verify → complete`` cycle.

Invariants kept from the council doctrine:
  * **orchestrator-only writes** — workers/verifiers return *data*; only this driver
    mutates the ledger (under its single-writer lock + version CAS). No agent edits the
    board directly, so the lost-update class of bug cannot occur.
  * **producer != verifier** — the agent that produced a task's work is never the one
    that certifies it; enforced both here (distinct agent names) and structurally in
    ``TaskLedger.complete``.
  * **evidence, not consensus** — a task is only marked done when an independent
    verifier returns PASS; a failing task is released and retried up to a cap, then
    abandoned (recorded, never silently "done").

``work_fn`` / ``verify_fn`` are injected so this is unit-testable with deterministic
fakes; :func:`adapter_work_fn` / :func:`adapter_verify_fn` wire the real provider CLIs
for live runs.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Callable

from .artifacts import StaleLedgerError, Task, TaskLedger, TaskStateError

WorkFn = Callable[[Task], str]
VerifyFn = Callable[[Task, str], "tuple[bool, str]"]


@dataclass
class Outcome:
    task_id: str
    owner: str
    verifier: str
    ok: bool
    attempts: int
    produced_hash: str
    verdict: str


@dataclass
class ProjectResult:
    done: list[str]
    abandoned: list[str]
    outcomes: list[Outcome]


def _h(s: str) -> str:
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()[:16]


def run_project(
    ledger: TaskLedger,
    task_titles: list[str],
    *,
    work_fn: WorkFn,
    verify_fn: VerifyFn,
    worker_agent: str,
    verifier_agent: str,
    max_attempts: int = 2,
) -> ProjectResult:
    """Drive a whole task board to completion via per-task cross-verified cycles.

    Returns a :class:`ProjectResult` with the done / abandoned task ids and the full
    per-task outcome trail.
    """
    if worker_agent == verifier_agent:
        raise ValueError("producer != verifier: worker_agent and verifier_agent must differ")

    if not ledger.snapshot().tasks:
        ledger.seed(task_titles)

    outcomes: list[Outcome] = []
    attempts: dict[str, int] = {}
    abandoned: set[str] = set()

    while True:
        snap = ledger.snapshot()
        todo = [t for t in snap.by_status("todo") if t.id not in abandoned]
        if not todo:
            break
        task = todo[0]

        # 1. Claim (CAS): if another writer advanced the board, re-read and retry.
        try:
            claimed = ledger.claim(task.id, worker_agent, expected_version=snap.version)
        except (StaleLedgerError, TaskStateError):
            continue

        # 2. Worker produces (untrusted output — only its hash enters the ledger).
        produced = work_fn(task)
        phash = _h(produced)

        # 3. Independent verifier (different provider) certifies.
        ok, verdict = verify_fn(task, produced)
        attempts[task.id] = attempts.get(task.id, 0) + 1

        # 4. Orchestrator applies the result serially under CAS.
        cur = ledger.snapshot().version
        if ok:
            ledger.complete(task.id, owner=worker_agent, produced_hash=phash,
                            verified_by=verifier_agent, expected_version=cur)
        else:
            ledger.release(task.id, worker_agent, expected_version=cur)
            if attempts[task.id] >= max_attempts:
                abandoned.add(task.id)  # recorded as not-done; never silently completed

        outcomes.append(Outcome(
            task_id=task.id, owner=worker_agent, verifier=verifier_agent,
            ok=ok, attempts=attempts[task.id], produced_hash=phash, verdict=verdict[:200],
        ))

    final = ledger.snapshot()
    return ProjectResult(
        done=[t.id for t in final.by_status("done")],
        abandoned=sorted(abandoned),
        outcomes=outcomes,
    )


# --- real-provider wiring (used by live runs; unit tests inject fakes instead) -------
def adapter_work_fn(cfg, agent: str, timeout: int = 180) -> WorkFn:
    """A ``work_fn`` that asks a real provider CLI to do the task."""
    from .adapters import adapter_for

    def fn(task: Task) -> str:
        prompt = (f"Do this task and return ONLY the resulting artifact/answer, no preamble.\n"
                  f"Task {task.id}: {task.title}")
        return adapter_for(cfg, agent).run(prompt, timeout=timeout).text

    return fn


def adapter_verify_fn(cfg, agent: str, timeout: int = 180) -> VerifyFn:
    """A ``verify_fn`` that asks a *different* real provider to certify the work.

    Returns ``(passed, verdict_text)``. The verifier must answer starting with PASS or
    FAIL; anything not clearly PASS is treated as not-verified (fail-safe).
    """
    from .adapters import adapter_for

    def fn(task: Task, produced: str) -> tuple[bool, str]:
        prompt = (f"You are an independent verifier. Task {task.id}: {task.title}\n"
                  f"Proposed result:\n{produced[:2000]}\n\n"
                  f"Reply with PASS or FAIL on the first line, then one reason line.")
        r = adapter_for(cfg, agent).run(prompt, timeout=timeout)
        first = (r.text or "").strip().splitlines()[0].upper() if r.text.strip() else ""
        return (r.ok and first.startswith("PASS"), r.text)

    return fn
