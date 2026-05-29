"""Graph wiring tests for the EXECUTE security boundary (6.2) + audit cfg threading.

Two invariants closed here (both KNOWN_ISSUES Phase-2 items), exercised through the
REAL compiled graph with a stubbed adapter (no live CLI, no network):

  (A) Article 6.2.2 — when the executor's output contains a destructive command shape,
      the graph must NOT let it pass as autonomous: ``decision.human_required`` is forced
      True regardless of confidence, a ``destructive_command`` incident is recorded, and
      the report carries an ``[EXEC GATE]`` line. Secrets in adapter output are redacted
      (6.2.5) and the output is data-wrapped (6.2.3) before it re-enters a prompt.

  (B) Audit cfg threading — every ``audit.*`` call in the graph forwards the *injected*
      ``cfg``, so a non-default config writes to ITS OWN DuckDB (under ``cfg.data_home``),
      never the default install DB. We prove this by pointing data_home at a tmp dir and
      asserting the session/incident rows land there.
"""
from __future__ import annotations

import duckdb

from council import adapters, graph
from council.adapters import AgentResult
from council.config import Config, RosterEntry


class _StubAdapter:
    """Returns a fixed text for every node so the graph runs without a live CLI."""

    def __init__(self, name: str, text: str):
        self.name = name
        self._text = text

    def run(self, prompt: str, timeout: int | None = None) -> AgentResult:
        return AgentResult(self.name, self._text, 0, 0.1, True, "deadbeefdeadbeef")


def _cfg(tmp_path) -> Config:
    """Two-provider roster (so cross-verification is available) writing to a tmp DB."""
    return Config(
        data_home=tmp_path / "data",
        agents=[
            RosterEntry(name="lead", cli="lead", role="lead"),
            RosterEntry(name="checker", cli="checker", role="verifier"),
        ],
    )


def _wire(monkeypatch, text_by_node_text: str, *, all_available=True):
    """Patch the roster to look fully available and every adapter to return a fixed text."""
    cfg_agents = ("lead", "checker")
    monkeypatch.setattr(graph, "available", lambda cfg: {n: all_available for n in cfg_agents})

    def fake_adapter_for(cfg, name):
        return _StubAdapter(name, text_by_node_text)

    monkeypatch.setattr(adapters, "adapter_for", fake_adapter_for)


def _run(cfg):
    return graph.build(cfg).invoke({"task": "do a thing", "project_hint": ""},
                                   config={"recursion_limit": 80})


# --------------------------------------------------------------------------- #
# (A) destructive command in output → human gate + incident + report flag      #
# --------------------------------------------------------------------------- #

def test_destructive_output_forces_human_gate(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    # Verifier says PASS so confidence would otherwise be high; the verdict's first line
    # is what verify() checks. The destructive shape must override it to human-required.
    _wire(monkeypatch, "PASS\nProceed: run `sudo rm -rf /var/data` to clean up.")
    final = _run(cfg)

    assert final["decision"]["human_required"] is True, (
        "a destructive command in output must force human approval (Article 6.2.2)"
    )
    assert "6.2.2" in final["decision"]["rationale"]
    assert "[EXEC GATE]" in final["report"]

    # incident row recorded in the INJECTED cfg's DB
    con = duckdb.connect(str(cfg.db_path()))
    incidents = con.execute(
        "SELECT violation_type FROM council_incidents WHERE violation_type = 'destructive_command'"
    ).fetchall()
    con.close()
    assert incidents, "a destructive_command incident must be appended"


def test_benign_output_does_not_trigger_exec_gate(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _wire(monkeypatch, "PASS\nAll good — here is a summary of the plan, no commands.")
    final = _run(cfg)
    assert "[EXEC GATE]" not in final["report"]
    con = duckdb.connect(str(cfg.db_path()))
    n = con.execute(
        "SELECT count(*) FROM council_incidents WHERE violation_type = 'destructive_command'"
    ).fetchone()[0]
    con.close()
    assert n == 0


def test_adapter_output_is_secret_redacted_in_audit(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    leak = "PASS\nhere is the key sk-ant-A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8 do not leak"
    _wire(monkeypatch, leak)
    _run(cfg)
    con = duckdb.connect(str(cfg.db_path()))
    payloads = [r[0] for r in con.execute("SELECT payload FROM council_messages").fetchall()]
    con.close()
    blob = "\n".join(payloads)
    assert "sk-ant-A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8" not in blob, (
        "adapter output secrets must be redacted before reaching the audit log (6.2.5)"
    )
    assert "[REDACTED]" in blob


# --------------------------------------------------------------------------- #
# (B) audit cfg threading — non-default cfg writes to ITS OWN db, not default   #
# --------------------------------------------------------------------------- #

def test_audit_writes_to_injected_cfg_db(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _wire(monkeypatch, "PASS\nclean plan, no commands.")
    final = _run(cfg)
    sid = final["session_id"]

    # the injected cfg's DB has the session; this proves cfg was threaded through audit.*
    db = cfg.db_path()
    assert db.parent == cfg.data_home, "DB must live under the injected cfg.data_home"
    assert db.exists(), "the injected cfg DB file must have been created"
    con = duckdb.connect(str(db))
    rows = con.execute(
        "SELECT session_id, user_id FROM council_sessions WHERE session_id = ?", [sid]
    ).fetchall()
    con.close()
    assert rows and str(rows[0][0]) == sid, "session must be recorded in the injected cfg DB"
    assert rows[0][1] == "operator", "owner defaults to operator, not a machine username"
