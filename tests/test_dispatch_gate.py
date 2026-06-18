"""Autonomy-ceiling gate tests for ``council/dispatch.py`` (Constitution Article 5.3 / 14).

``dispatch.py`` is the unattended-execution path: a task file dropped in the inbox (or a
scheduled job) is classified and then EITHER run autonomously OR routed to a human queue.
The single most security-critical invariant in the module — only clean ``public|internal``
work ever reaches the ``AutoGate``; everything blocked or higher-risk is forced to
``queue-human``, and no config can widen that ceiling — had NO direct test (the existing
suite only touched ``dispatch.main`` indirectly). This pins it, plus the fail-safe
(gateway unavailable ⇒ queue-human), the task parser, and the routing in ``_run_task``.

Everything here uses duck-typed gateway stubs and monkeypatched seams (no live agent, no
subprocess, no real gateway) — pure-logic verification of the gate.
"""
from __future__ import annotations

import json

import pytest

from council import dispatch
from council.config import Config


class _Gw:
    """Duck-typed ``GatewayResult`` stand-in (the gate reads ``risk``/``blocked`` via getattr)."""

    def __init__(self, risk: str = "internal", blocked: bool = False,
                 block_reason: str = "", notes: list | None = None) -> None:
        self.risk = risk
        self.blocked = blocked
        self.block_reason = block_reason
        self.notes = notes or []


def _cfg(tmp_path) -> Config:
    return Config(council_home=tmp_path, data_home=tmp_path / "data",
                  bridge_dir=tmp_path / "bridge", owner="op")


# --------------------------------------------------------------------------- the ceiling
@pytest.mark.parametrize("risk", ["public", "internal"])
def test_clean_low_risk_reaches_autogate(risk):
    gate = dispatch._decide_gate(_Gw(risk=risk, blocked=False))
    assert isinstance(gate, dispatch.AutoGate)
    assert gate.allows(_Gw(risk=risk)) is True


@pytest.mark.parametrize("risk", ["pii", "sensitive", "production", "secret", "", "unknown"])
def test_higher_or_unknown_risk_is_forced_to_queue_human(risk):
    # Anything not explicitly in the ceiling — including an UNKNOWN class — must queue.
    gate = dispatch._decide_gate(_Gw(risk=risk, blocked=False))
    assert isinstance(gate, dispatch.QueueGate)
    assert gate.allows(_Gw(risk=risk)) is False


def test_blocked_always_queues_even_when_risk_is_internal():
    # A blocked preflight must NEVER auto-run, regardless of how low the risk looks.
    gate = dispatch._decide_gate(_Gw(risk="internal", blocked=True, block_reason="secret found"))
    assert isinstance(gate, dispatch.QueueGate)


def test_autogate_independently_rejects_blocked_internal():
    # Defense in depth: even if AutoGate were reached, it independently refuses a blocked gw.
    assert dispatch.AutoGate().allows(_Gw(risk="internal", blocked=True)) is False


def test_queuegate_never_allows():
    assert dispatch.QueueGate().allows(_Gw(risk="public")) is False
    assert dispatch.QueueGate().allows(_Gw(risk="internal", blocked=False)) is False


def test_allowed_auto_ceiling_is_exactly_public_internal():
    # The constant a config cannot widen (Article 5.3). If this set ever grows, the
    # autonomy ceiling has been raised and MUST be a conscious, reviewed change — this
    # test is the tripwire that forces that conversation.
    assert dispatch.ALLOWED_AUTO == {"public", "internal"}


# --------------------------------------------------------------------------- fail-safe
def test_preflight_failsafe_shim_when_gateway_unavailable(tmp_path, monkeypatch):
    # If gateway.preflight raises, ``_preflight`` must return a fail-SAFE result (risk above
    # the ceiling + blocked) so the task is queued for a human, never auto-run on an
    # unclassified task.
    import council.gateway as gw_mod

    def boom(*a, **k):
        raise RuntimeError("gateway down")

    monkeypatch.setattr(gw_mod, "preflight", boom)
    shim = dispatch._preflight("do a thing", "", _cfg(tmp_path))
    assert shim.blocked is True
    assert shim.risk not in dispatch.ALLOWED_AUTO                      # above the ceiling
    assert isinstance(dispatch._decide_gate(shim), dispatch.QueueGate)


# --------------------------------------------------------------------------- task parser
def test_parse_task_json_with_project_key(tmp_path):
    p = tmp_path / "t.json"
    p.write_text(json.dumps({"task": "tidy docs", "project": "konsey"}), encoding="utf-8")
    assert dispatch._parse_task(p) == ("tidy docs", "konsey")


def test_parse_task_json_legacy_project_hint_key(tmp_path):
    # The legacy ``project_hint`` key is still accepted alongside the example schema's ``project``.
    p = tmp_path / "t.json"
    p.write_text(json.dumps({"task": "tidy docs", "project_hint": "legacy"}), encoding="utf-8")
    assert dispatch._parse_task(p) == ("tidy docs", "legacy")


def test_parse_task_malformed_json_falls_back_to_raw_text(tmp_path):
    p = tmp_path / "t.json"
    p.write_text("{not valid json", encoding="utf-8")
    task, hint = dispatch._parse_task(p)
    assert task == "{not valid json"
    assert hint == ""


def test_parse_task_plain_text(tmp_path):
    p = tmp_path / "t.txt"
    p.write_text("just a task line\n", encoding="utf-8")
    assert dispatch._parse_task(p) == ("just a task line", "")


# --------------------------------------------------------------------------- routing
def test_run_task_routes_high_risk_to_queue_human_not_outbox(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    bridge = dispatch._Bridge(cfg)
    bridge.ensure()
    monkeypatch.setattr(dispatch, "_preflight",
                        lambda *a, **k: _Gw(risk="production", block_reason="prod write"))
    ran = {"graph": False}
    monkeypatch.setattr(dispatch, "_run_graph",
                        lambda *a, **k: ran.__setitem__("graph", True) or {})
    out = dispatch._run_task(cfg, bridge, "deploy to prod", "", origin="inbox/x")
    assert out.parent == bridge.queue_human                  # routed to the human queue
    assert ran["graph"] is False                             # a prod task never auto-ran
    assert out.read_text(encoding="utf-8").strip()           # a human-readable report exists


def test_run_task_autonomous_low_risk_writes_outbox(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    bridge = dispatch._Bridge(cfg)
    bridge.ensure()
    monkeypatch.setattr(dispatch, "_preflight", lambda *a, **k: _Gw(risk="internal"))
    monkeypatch.setattr(dispatch, "_run_graph",
                        lambda *a, **k: {"report": "all done", "decision": {"confidence": 0.9}})
    out = dispatch._run_task(cfg, bridge, "tidy docs", "", origin="inbox/y")
    assert out.parent == bridge.outbox
    assert "all done" in out.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- inbox pass
def test_process_inbox_inert_without_bridge(tmp_path):
    cfg = Config(council_home=tmp_path, data_home=tmp_path / "data", bridge_dir=None)
    assert dispatch.process_inbox(cfg) == 0                  # no bridge → wholly inert


def test_process_inbox_queues_high_risk_and_archives_source(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    bridge = dispatch._Bridge(cfg)
    bridge.ensure()
    (bridge.inbox / "job.txt").write_text("ship the release", encoding="utf-8")
    monkeypatch.setattr(dispatch, "_preflight", lambda *a, **k: _Gw(risk="production"))
    monkeypatch.setattr(dispatch, "_run_graph", lambda *a, **k: {})
    n = dispatch.process_inbox(cfg)
    assert n == 1
    assert list(bridge.queue_human.glob("*.md"))             # routed to human queue
    assert not list(bridge.inbox.glob("job.txt"))            # original consumed
    assert list(bridge.processed.glob("*job.txt"))           # archived under processed/


def test_process_inbox_skips_underscore_and_dot_prefixed_files(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    bridge = dispatch._Bridge(cfg)
    bridge.ensure()
    (bridge.inbox / "_readme.md").write_text("not a task", encoding="utf-8")
    (bridge.inbox / ".hidden").write_text("not a task", encoding="utf-8")
    monkeypatch.setattr(dispatch, "_preflight", lambda *a, **k: _Gw(risk="internal"))
    monkeypatch.setattr(dispatch, "_run_graph", lambda *a, **k: {"report": "x"})
    assert dispatch.process_inbox(cfg) == 0                  # note/help files are not tasks
    assert (bridge.inbox / "_readme.md").exists()            # left untouched
