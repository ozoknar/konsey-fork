"""Durable project artifacts + single-writer task ledger (Constitution Art. 6/7/10).

This is the persistence backbone that lets the council work *end-to-end* as a team
instead of running once and handing off to a single agent. Two pieces:

  * ``ArtifactStore`` — durable ``spec.md`` / ``plan.md`` / ``tasks.md`` under a
    per-project directory. The artifacts are the shared source of truth (the idea
    borrowed from spec-driven development — without taking on the dependency).
  * ``TaskLedger`` — a file-backed, **single-writer** task board. Agents never write
    it concurrently: every mutation takes an exclusive ``flock`` and is guarded by an
    optimistic **version compare-and-swap** (CAS). A mutation computed against a stale
    snapshot is rejected (``StaleLedgerError``) so a worker that planned against an
    out-of-date board is forced to re-read before retrying.

Design rationale (cross-verified by the council, 2026-06-18):
  - The lock alone prevents *file* corruption (lost updates); the **version CAS**
    additionally prevents *semantic* drift — both independent verifier nodes flagged
    stale-workspace patches as the #1 residual risk, so CAS is a first-class invariant
    here, not an afterthought.
  - ``complete()`` enforces ``producer != verifier`` at the data layer: a task cannot
    be marked done by evidence whose verifier is its claimant.

No third-party dependency: stdlib ``json`` + ``fcntl`` only. Importing has no side
effects; all state lives under an explicit ``root`` the caller chooses (tests pass a
``tmp_path``).
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

ARTIFACT_NAMES = ("spec.md", "plan.md", "tasks.md")
_VALID_STATES = ("todo", "claimed", "done")


class StaleLedgerError(RuntimeError):
    """Raised when a mutation's ``expected_version`` no longer matches the ledger.

    Signals optimistic-concurrency loss: someone else advanced the board since the
    caller's snapshot. The caller should re-read (``snapshot``) and retry — this is
    the anti-drift guard, not a fatal error.
    """


class TaskStateError(RuntimeError):
    """Raised on an illegal state transition or a producer==verifier violation."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _h(s: str) -> str:
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()[:16]


@dataclass
class Task:
    """One unit of work on the board.

    ``evidence`` is append-only: each entry records who produced the work and who
    independently verified it, plus the applied-content hash — the audit trail that
    answers "who did what, checked by whom" months later.
    """
    id: str
    title: str
    status: str = "todo"
    owner: str = ""
    evidence: list[dict] = field(default_factory=list)


@dataclass
class Ledger:
    """An immutable-ish snapshot of the board at a given ``version``."""
    version: int
    tasks: list[Task]

    def task(self, task_id: str) -> Task:
        for t in self.tasks:
            if t.id == task_id:
                return t
        raise KeyError(f"no such task: {task_id}")

    def by_status(self, status: str) -> list[Task]:
        return [t for t in self.tasks if t.status == status]


class ArtifactStore:
    """Durable spec/plan/tasks artifacts for one project, under ``root``."""

    def __init__(self, root: str | os.PathLike) -> None:
        self.root = Path(root)

    def _path(self, name: str) -> Path:
        if name not in ARTIFACT_NAMES:
            raise ValueError(f"unknown artifact {name!r}; expected one of {ARTIFACT_NAMES}")
        return self.root / name

    def write(self, name: str, content: str) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        p = self._path(name)
        p.write_text(content, encoding="utf-8")
        return p

    def read(self, name: str) -> str:
        return self._path(name).read_text(encoding="utf-8")

    def exists(self, name: str) -> bool:
        return self._path(name).is_file()


class TaskLedger:
    """Single-writer, version-CAS task board backed by ``<root>/ledger.json``.

    Every mutating method:
      1. takes an exclusive OS lock (so concurrent processes serialize — no two
         writers ever interleave a read-modify-write);
      2. checks ``expected_version`` against the on-disk version (CAS); a mismatch
         raises :class:`StaleLedgerError` and writes nothing;
      3. applies the change, bumps the version by one, writes atomically.
    """

    def __init__(self, root: str | os.PathLike) -> None:
        self.root = Path(root)
        self.path = self.root / "ledger.json"
        self._lockpath = self.root / "ledger.lock"

    # ----- low-level persistence ------------------------------------------------
    def _read_raw(self) -> dict:
        if not self.path.is_file():
            return {"version": 0, "tasks": []}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write_raw(self, data: dict) -> None:
        # Atomic replace: write a temp sibling then os.replace (no torn file).
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    @contextmanager
    def _exclusive(self) -> Iterator[None]:
        self.root.mkdir(parents=True, exist_ok=True)
        with open(self._lockpath, "w") as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lf, fcntl.LOCK_UN)

    @staticmethod
    def _to_ledger(data: dict) -> Ledger:
        return Ledger(version=data["version"],
                      tasks=[Task(**t) for t in data["tasks"]])

    # ----- public API -----------------------------------------------------------
    def snapshot(self) -> Ledger:
        """Read the current board (no lock needed for a point-in-time read)."""
        return self._to_ledger(self._read_raw())

    def seed(self, titles: list[str]) -> Ledger:
        """Initialise the board with todo tasks (only valid on an empty ledger)."""
        with self._exclusive():
            data = self._read_raw()
            if data["tasks"]:
                raise TaskStateError("ledger already seeded")
            data = {"version": data["version"] + 1,
                    "tasks": [asdict(Task(id=f"T{i+1}", title=t)) for i, t in enumerate(titles)]}
            self._write_raw(data)
            return self._to_ledger(data)

    def claim(self, task_id: str, agent: str, expected_version: int) -> Ledger:
        """Atomically move a task ``todo -> claimed`` for ``agent`` (CAS-guarded)."""
        return self._mutate(expected_version, _claim_op(task_id, agent))

    def release(self, task_id: str, agent: str, expected_version: int) -> Ledger:
        """Return a claimed task to the pool (``claimed -> todo``)."""
        return self._mutate(expected_version, _release_op(task_id, agent))

    def complete(self, task_id: str, *, owner: str, produced_hash: str,
                 verified_by: str, expected_version: int) -> Ledger:
        """Orchestrator-only: mark a claimed task done and append its evidence.

        Enforces the council invariant ``producer != verifier``: the task's claimant
        cannot also be the verifier of record.
        """
        if verified_by == owner:
            raise TaskStateError(
                f"producer != verifier violated: {owner!r} cannot verify its own work")
        return self._mutate(expected_version, _complete_op(task_id, owner, produced_hash, verified_by))

    # ----- the single guarded read-modify-write ---------------------------------
    def _mutate(self, expected_version: int, op) -> Ledger:
        with self._exclusive():
            data = self._read_raw()
            if data["version"] != expected_version:
                raise StaleLedgerError(
                    f"expected version {expected_version}, ledger is at {data['version']}; re-read and retry")
            ledger = self._to_ledger(data)
            op(ledger)  # mutates ledger.tasks in place; raises on illegal transition
            out = {"version": data["version"] + 1,
                   "tasks": [asdict(t) for t in ledger.tasks]}
            self._write_raw(out)
            return self._to_ledger(out)


# --- transition operations (pure; raise TaskStateError on illegal moves) --------
def _claim_op(task_id: str, agent: str):
    def op(ledger: Ledger) -> None:
        t = ledger.task(task_id)
        if t.status != "todo":
            raise TaskStateError(f"cannot claim {task_id}: status is {t.status!r}, not 'todo'")
        t.status, t.owner = "claimed", agent
    return op


def _release_op(task_id: str, agent: str):
    def op(ledger: Ledger) -> None:
        t = ledger.task(task_id)
        if t.status != "claimed" or t.owner != agent:
            raise TaskStateError(f"cannot release {task_id}: not claimed by {agent!r}")
        t.status, t.owner = "todo", ""
    return op


def _complete_op(task_id: str, owner: str, produced_hash: str, verified_by: str):
    def op(ledger: Ledger) -> None:
        t = ledger.task(task_id)
        if t.status != "claimed" or t.owner != owner:
            raise TaskStateError(f"cannot complete {task_id}: not claimed by {owner!r}")
        t.status = "done"
        t.evidence.append({  # append-only: prior evidence is never dropped
            "at": _now(), "produced_by": owner, "verified_by": verified_by,
            "hash": produced_hash,
        })
    return op
