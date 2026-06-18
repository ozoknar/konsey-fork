"""Tests for project mode — the multi-task, cross-verified council driver.

Deterministic: worker/verifier are injected fakes, so the orchestration logic is
proven without any live LLM call. A separate live smoke (examples/) exercises the
real provider wiring.
"""
from __future__ import annotations

import pytest

from council.artifacts import TaskLedger
from council.project import ProjectResult, run_project


def _always_pass(task, produced):
    return True, "PASS deterministic"


def test_all_tasks_completed_with_cross_verification(tmp_path):
    led = TaskLedger(tmp_path)
    res = run_project(
        led, ["design schema", "write loader", "add tests"],
        work_fn=lambda t: f"work for {t.id}",
        verify_fn=_always_pass,
        worker_agent="claude", verifier_agent="codex",
    )
    assert isinstance(res, ProjectResult)
    assert sorted(res.done) == ["T1", "T2", "T3"]
    assert res.abandoned == []
    # every task carries evidence with producer != verifier
    final = led.snapshot()
    for t in final.tasks:
        assert t.status == "done"
        ev = t.evidence[-1]
        assert ev["produced_by"] == "claude"
        assert ev["verified_by"] == "codex"
        assert ev["produced_by"] != ev["verified_by"]


def test_failing_task_is_abandoned_not_silently_done(tmp_path):
    led = TaskLedger(tmp_path)

    def verify(task, produced):
        # T2 can never be certified; others pass
        return (task.id != "T2", "PASS" if task.id != "T2" else "FAIL bad output")

    res = run_project(
        led, ["a", "b", "c"],
        work_fn=lambda t: "x",
        verify_fn=verify,
        worker_agent="claude", verifier_agent="codex",
        max_attempts=2,
    )
    assert sorted(res.done) == ["T1", "T3"]
    assert res.abandoned == ["T2"]
    # T2 ended back in the pool (todo), never marked done
    assert led.snapshot().task("T2").status == "todo"
    # it was retried exactly max_attempts times before being abandoned
    t2_attempts = [o.attempts for o in res.outcomes if o.task_id == "T2"]
    assert max(t2_attempts) == 2


def test_producer_equals_verifier_is_rejected_upfront(tmp_path):
    led = TaskLedger(tmp_path)
    with pytest.raises(ValueError, match="producer != verifier"):
        run_project(
            led, ["t"],
            work_fn=lambda t: "x", verify_fn=_always_pass,
            worker_agent="claude", verifier_agent="claude",
        )


def test_evidence_count_matches_done_tasks(tmp_path):
    led = TaskLedger(tmp_path)
    run_project(
        led, ["one", "two"],
        work_fn=lambda t: f"r-{t.id}", verify_fn=_always_pass,
        worker_agent="codex", verifier_agent="claude",
    )
    final = led.snapshot()
    assert sum(len(t.evidence) for t in final.tasks) == 2
