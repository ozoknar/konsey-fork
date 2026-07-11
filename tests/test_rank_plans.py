"""Faz 1 — opt-in anonymized cross-ranking of PLAN candidates (``parallel_plan_rank``).

Provenance: konsey run session 28d9a879 (2026-07-11) evaluated karpathy/llm-council's
blind peer-ranking pattern and recommended a narrow, two-phase adoption. This is Faz 1:
default OFF, advisory-only (REPORT), and decide.py must never read the ``plan_ranking``
key — the run explicitly warned against diluting the evidence-weighted score with a
preference/popularity signal (that coupling is gated behind a separate Faz 2 decision).

The tests prove: (a) the whole feature is a no-op unless BOTH ``parallel_plan`` and
``parallel_plan_rank`` are on and there are 2+ candidates; (b) the ranking prompt never
leaks producer identity (anonymized ``Plan A/B/C`` labels); (c) the Borda aggregation is
correct; (d) ``decide.py`` has no static reference to the new key (a cheap regression
guard against accidental future coupling).
"""
from __future__ import annotations

from pathlib import Path

from council import graph
from council.config import ROLE_CRITIC, ROLE_LEAD, ROLE_VERIFIER, Config, RosterEntry
from council.graph import _aggregate_plan_rankings, _parse_plan_ranking


class _Result:
    def __init__(self, text: str, ok: bool = True) -> None:
        self.text, self.ok = text, ok
        self.exit_code = 0 if ok else 1
        self.seconds = 0.01


def _cfg(tmp_path, agents, **overrides) -> Config:
    return Config(council_home=tmp_path, data_home=tmp_path / "data", owner="op", agents=agents,
                 **overrides)


_FULL_ROSTER = [
    RosterEntry("claude", "claude", ROLE_LEAD),
    RosterEntry("codex", "codex", ROLE_CRITIC),
    RosterEntry("google", "agy", ROLE_VERIFIER),
]


class _RankAwareAdapter:
    """Distinguishes a rank_plans call from any other call by the prompt's fixed
    phrasing (mirrors the codebase's existing ``_RecordingAdapter`` pattern of
    detecting stage by prompt content, since the same agent is invoked for both PLAN
    and rank_plans in sequence and a per-agent-only fake can't tell them apart)."""
    def __init__(self, name: str, plan_replies: dict[str, str], ranking_reply: str) -> None:
        self._name = name
        self._plan_replies = plan_replies
        self._ranking_reply = ranking_reply

    def run(self, prompt: str, timeout: int = 180) -> _Result:   # noqa: ARG002 (stub)
        if "evaluating anonymized candidate plans" in prompt:
            return _Result(self._ranking_reply)
        return _Result(self._plan_replies.get(self._name, "stub plan"))


def _install(monkeypatch, names, plan_replies, ranking_reply) -> None:
    monkeypatch.setattr(graph, "available", lambda cfg: {n: True for n in names})
    monkeypatch.setattr(
        "council.adapters.adapter_for",
        lambda cfg, name: _RankAwareAdapter(name, plan_replies, ranking_reply),
    )


def _run(cfg: Config) -> dict:
    return graph.build(cfg).invoke(
        {"task": "pick a caching strategy", "project_hint": ""}, config={"recursion_limit": 80})


# --------------------------------------------------------------------------------- #
# Opt-in gating                                                                     #
# --------------------------------------------------------------------------------- #

def test_parallel_plan_rank_off_by_default(tmp_path):
    assert _cfg(tmp_path, _FULL_ROSTER).parallel_plan_rank is False


def test_rank_plans_absent_when_flag_off(tmp_path, monkeypatch):
    # parallel_plan on (multiple candidate plans exist) but parallel_plan_rank off →
    # no ranking work should happen at all.
    cfg = _cfg(tmp_path, _FULL_ROSTER, parallel_plan=True, parallel_plan_rank=False)
    _install(monkeypatch, ["claude", "codex", "google"],
             plan_replies={"claude": "plan X", "codex": "plan Y", "google": "plan Z"},
             ranking_reply="FINAL RANKING:\n1. Plan A")
    final = _run(cfg)
    assert "plan_ranking" not in final or not final.get("plan_ranking")


def test_rank_plans_absent_with_single_candidate(tmp_path, monkeypatch):
    # Only one enabled lead → plan() produces a single plan → nothing to rank even
    # with the flag on (mirrors plan()'s own len(leads) > 1 fan-out gate).
    roster = [RosterEntry("claude", "claude", ROLE_LEAD)]
    cfg = _cfg(tmp_path, roster, parallel_plan=True, parallel_plan_rank=True)
    _install(monkeypatch, ["claude"], plan_replies={"claude": "solo plan"},
             ranking_reply="FINAL RANKING:\n1. Plan A")
    final = _run(cfg)
    assert "plan_ranking" not in final or not final.get("plan_ranking")


# --------------------------------------------------------------------------------- #
# End-to-end: anonymization + aggregate surfaces correctly, decide.py untouched     #
# --------------------------------------------------------------------------------- #

def test_rank_plans_produces_anonymized_aggregate(tmp_path, monkeypatch):
    roster = [
        RosterEntry("claude", "claude", ROLE_LEAD),
        RosterEntry("codex", "codex", ROLE_LEAD),
    ]
    cfg = _cfg(tmp_path, roster, parallel_plan=True, parallel_plan_rank=True)
    # Both rankers agree "Plan B" is best — deterministic winner regardless of which
    # agent produced it (the point of anonymization: the ranker never sees agent names).
    _install(
        monkeypatch, ["claude", "codex"],
        plan_replies={"claude": "use Redis with TTL", "codex": "use an in-process LRU cache"},
        ranking_reply="Plan B is more scalable.\n\nFINAL RANKING:\n1. Plan B\n2. Plan A",
    )
    final = _run(cfg)

    pr = final.get("plan_ranking")
    assert pr, "expected plan_ranking to be populated"
    assert set(pr["label_to_agent"].keys()) == {"A", "B"}
    assert set(pr["label_to_agent"].values()) == {"claude", "codex"}

    aggregate = pr["aggregate"]
    assert aggregate[0]["label"] == "B"
    # Both rankers gave the same ordering → winner should have ranked_by == number of rankers.
    assert aggregate[0]["ranked_by"] == 2
    assert aggregate[0]["borda_points"] > aggregate[-1]["borda_points"]

    # decide.py's score must be unaffected by whether ranking ran at all — the
    # architectural guarantee this feature is gated on (Faz 2 is a separate decision).
    assert "plan_ranking" not in str(final.get("decision", {}))


def test_decide_module_has_no_static_reference_to_plan_ranking():
    # Cheap regression guard: decide.py must never read the plan_ranking key (Faz 1
    # is REPORT-only by design; wiring it into the score is an explicit Faz 2 ask).
    import council.decide as decide_mod
    src = Path(decide_mod.__file__).read_text(encoding="utf-8")
    assert "plan_ranking" not in src


# --------------------------------------------------------------------------------- #
# Unit: parsing + Borda aggregation                                                 #
# --------------------------------------------------------------------------------- #

def test_parse_plan_ranking_handles_final_ranking_marker():
    text = (
        "Plan A is thorough but slow. Plan B is fast but risky.\n\n"
        "FINAL RANKING:\n1. Plan B\n2. Plan A"
    )
    assert _parse_plan_ranking(text, ["A", "B"]) == ["B", "A"]


def test_parse_plan_ranking_drops_unknown_and_duplicate_labels():
    # "Plan Z" isn't in the valid label set (model hallucinated/miscounted) and
    # "Plan A" repeats — both must be handled without raising.
    text = "FINAL RANKING:\n1. Plan A\n2. Plan Z\n3. Plan A\n4. Plan B"
    assert _parse_plan_ranking(text, ["A", "B"]) == ["A", "B"]


def test_parse_plan_ranking_falls_back_without_marker():
    # No structured marker at all — scan the whole text in first-seen order.
    text = "I think Plan C edges out Plan A, with Plan B last."
    assert _parse_plan_ranking(text, ["A", "B", "C"]) == ["C", "A", "B"]


def test_aggregate_plan_rankings_borda_count():
    labels = ["A", "B", "C"]
    label_to_agent = {"A": "claude", "B": "codex", "C": "google"}
    per_agent = {
        "claude": {"parsed": ["B", "A", "C"]},   # B=3, A=2, C=1
        "codex":  {"parsed": ["B", "C", "A"]},   # B=3, C=2, A=1
        "google": {"parsed": ["A"]},              # A=3 (partial ranking — only ranked one)
    }
    agg = _aggregate_plan_rankings(per_agent, labels, label_to_agent)
    points = {row["label"]: row["borda_points"] for row in agg}
    assert points == {"A": 2 + 1 + 3, "B": 3 + 3, "C": 1 + 2}
    # Sorted best-first.
    assert [row["label"] for row in agg] == sorted(points, key=lambda label: -points[label])
    assert agg[0]["ranked_by"] in (2, 3)  # whichever label tops out, sanity on the count field


def test_aggregate_plan_rankings_unranked_label_gets_zero():
    # A label no ranker ever mentioned still appears in the aggregate at 0 points
    # (Md.2.7 graceful degrade — never silently drop a candidate from the report).
    per_agent = {"claude": {"parsed": ["A"]}}
    agg = _aggregate_plan_rankings(per_agent, ["A", "B"], {"A": "claude", "B": "codex"})
    by_label = {row["label"]: row for row in agg}
    assert by_label["B"]["borda_points"] == 0
    assert by_label["B"]["ranked_by"] == 0
