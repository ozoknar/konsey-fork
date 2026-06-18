"""Tests for the durable artifact store + single-writer task ledger.

Focus: the invariants the council cross-verified as load-bearing —
  * optimistic version CAS makes the classic "two agents clobber tasks.md" lost
    update structurally impossible (anti-drift);
  * producer != verifier is enforced at the data layer;
  * task evidence is append-only.
"""
from __future__ import annotations

import pytest

from council.artifacts import (
    ArtifactStore,
    StaleLedgerError,
    TaskLedger,
    TaskStateError,
)


def test_artifact_roundtrip(tmp_path):
    store = ArtifactStore(tmp_path / "proj")
    store.write("spec.md", "# Spec\nbuild X")
    store.write("plan.md", "# Plan")
    store.write("tasks.md", "- [ ] T1")
    assert store.read("spec.md").startswith("# Spec")
    assert store.exists("plan.md")
    with pytest.raises(ValueError):
        store.write("notes.md", "nope")  # only the three known artifacts


def test_seed_and_snapshot(tmp_path):
    led = TaskLedger(tmp_path)
    l0 = led.seed(["design schema", "write loader", "add tests"])
    assert l0.version == 1
    assert [t.id for t in l0.tasks] == ["T1", "T2", "T3"]
    assert all(t.status == "todo" for t in l0.tasks)
    # re-seeding a populated ledger is refused
    with pytest.raises(TaskStateError):
        led.seed(["x"])


def test_claim_then_complete_happy_path(tmp_path):
    led = TaskLedger(tmp_path)
    v = led.seed(["task one"]).version
    l1 = led.claim("T1", agent="claude", expected_version=v)
    assert l1.task("T1").status == "claimed"
    assert l1.task("T1").owner == "claude"
    l2 = led.complete("T1", owner="claude", produced_hash="abc123",
                      verified_by="codex", expected_version=l1.version)
    t = l2.task("T1")
    assert t.status == "done"
    assert len(t.evidence) == 1
    assert t.evidence[0]["produced_by"] == "claude"
    assert t.evidence[0]["verified_by"] == "codex"


def test_double_claim_is_refused(tmp_path):
    led = TaskLedger(tmp_path)
    v = led.seed(["t"]).version
    led.claim("T1", "claude", expected_version=v)
    # someone tries to claim the already-claimed task at the *new* version
    cur = led.snapshot().version
    with pytest.raises(TaskStateError):
        led.claim("T1", "codex", expected_version=cur)


def test_anti_drift_cas_blocks_lost_update(tmp_path):
    """The critic's failure scenario: two agents snapshot at v=1, both mutate.

    The first write succeeds (v -> 2). The second, still holding the v=1 snapshot,
    is rejected by CAS instead of silently clobbering the first agent's work.
    """
    led = TaskLedger(tmp_path)
    led.seed(["T1 work", "T2 work"])
    snap_a = led.snapshot()
    snap_b = led.snapshot()           # both agents see version 1
    assert snap_a.version == snap_b.version == 1

    # Agent A claims T1 against v1 -> succeeds, board now at v2
    led.claim("T1", "claude", expected_version=snap_a.version)

    # Agent B, still on its stale v1 snapshot, tries to claim T2 -> REJECTED
    with pytest.raises(StaleLedgerError):
        led.claim("T2", "codex", expected_version=snap_b.version)

    # Nothing was clobbered: A's claim survives, B simply re-reads and retries
    fresh = led.snapshot()
    assert fresh.task("T1").owner == "claude"
    led.claim("T2", "codex", expected_version=fresh.version)
    assert led.snapshot().task("T2").owner == "codex"


def test_producer_must_differ_from_verifier(tmp_path):
    led = TaskLedger(tmp_path)
    v = led.seed(["t"]).version
    l1 = led.claim("T1", "claude", expected_version=v)
    with pytest.raises(TaskStateError, match="producer != verifier"):
        led.complete("T1", owner="claude", produced_hash="h",
                     verified_by="claude", expected_version=l1.version)


def test_evidence_is_append_only_across_tasks(tmp_path):
    led = TaskLedger(tmp_path)
    led.seed(["a", "b"])
    v = led.snapshot().version
    v = led.claim("T1", "claude", expected_version=v).version
    v = led.complete("T1", owner="claude", produced_hash="h1",
                     verified_by="codex", expected_version=v).version
    v = led.claim("T2", "codex", expected_version=v).version
    final = led.complete("T2", owner="codex", produced_hash="h2",
                         verified_by="claude", expected_version=v)
    # T1's evidence is untouched after T2 completes
    assert final.task("T1").evidence[0]["hash"] == "h1"
    assert final.task("T2").evidence[0]["hash"] == "h2"


def test_release_returns_task_to_pool(tmp_path):
    led = TaskLedger(tmp_path)
    v = led.seed(["t"]).version
    l1 = led.claim("T1", "claude", expected_version=v)
    l2 = led.release("T1", "claude", expected_version=l1.version)
    assert l2.task("T1").status == "todo"
    assert l2.task("T1").owner == ""


def test_concurrent_agents_never_double_own(tmp_path):
    """The headline goal: many agents working the board at once, safely.

    Three worker threads hammer the ledger, each repeatedly snapshotting and trying
    to claim a free task with CAS-retry on contention. The lock + version CAS must
    guarantee every task ends up owned by exactly one agent — never clobbered, never
    double-claimed — no matter the interleaving.
    """
    import threading

    led = TaskLedger(tmp_path)
    n_tasks = 30
    led.seed([f"task {i}" for i in range(n_tasks)])
    claimed_by: dict[str, str] = {}
    lock = threading.Lock()

    def worker(agent: str) -> None:
        while True:
            snap = led.snapshot()
            free = snap.by_status("todo")
            if not free:
                return
            try:
                led.claim(free[0].id, agent, expected_version=snap.version)
            except (StaleLedgerError, TaskStateError):
                continue  # lost the race; re-read and try another task
            with lock:
                claimed_by[free[0].id] = agent

    threads = [threading.Thread(target=worker, args=(f"agent{i}",)) for i in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    final = led.snapshot()
    # every task claimed exactly once, by exactly one owner, with no todo left
    assert final.by_status("todo") == []
    owners = {t.id: t.owner for t in final.tasks}
    assert all(owners.values()), "every task must have an owner"
    assert len(owners) == n_tasks
    # the board's record and the workers' record agree — no silent clobber
    assert claimed_by == owners
