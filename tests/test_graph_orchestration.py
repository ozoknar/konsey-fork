"""End-to-end orchestration test for the 9-state graph (council/graph.py).

The #1 test gap the whole-project council evaluation surfaced: the full
PREFLIGHT→PLAN→CRITIQUE→SYNTHESIZE→EXECUTE→VERIFY→DECIDE→REPORT→MEMORY loop was only
exercised through its pieces, never as one compiled run. This injects FAKE adapters
(no live agent / no subprocess) plus a forced provider-availability map, runs the REAL
compiled graph, and asserts the flow, the producer≠verifier invariant, advisory
degradation with <2 providers, and the BOUNDED verify-retry router (no infinite loop).
"""
from __future__ import annotations

from pathlib import Path

import duckdb

from council import audit, graph
from council.config import ROLE_CRITIC, ROLE_LEAD, ROLE_VERIFIER, Config, RosterEntry
from council.exec_policy import mark_untrusted, unwrap_untrusted

SCHEMA = (Path(audit.__file__).resolve().parent / "db" / "schema.sql").read_text(encoding="utf-8")


class _Result:
    """Mimics the adapter run-result shape that graph._ask reads."""
    def __init__(self, text: str, ok: bool = True) -> None:
        self.text, self.ok = text, ok
        self.exit_code = 0 if ok else 1
        self.seconds = 0.01


class _Adapter:
    def __init__(self, reply: str) -> None:
        self._reply = reply

    def run(self, prompt: str, timeout: int = 180) -> _Result:   # noqa: ARG002 (stub)
        return _Result(self._reply)


def _cfg(tmp_path, agents, **overrides) -> Config:
    return Config(council_home=tmp_path, data_home=tmp_path / "data", owner="op", agents=agents,
                 **overrides)


def _install(monkeypatch, names, reply) -> None:
    # Force which providers are "on PATH" + replace every adapter with a stub.
    monkeypatch.setattr(graph, "available", lambda cfg: {n: True for n in names})
    monkeypatch.setattr("council.adapters.adapter_for", lambda cfg, name: _Adapter(reply))


def _run(cfg: Config) -> dict:
    return graph.build(cfg).invoke(
        {"task": "tidy the docs", "project_hint": ""}, config={"recursion_limit": 80})


def _session_end_count(cfg: Config) -> int:
    with duckdb.connect(str(cfg.db_path())) as c:
        c.execute(SCHEMA)
        return c.execute(
            "SELECT count(*) FROM council_messages WHERE msg_type='session_end'").fetchone()[0]


_FULL_ROSTER = [
    RosterEntry("claude", "claude", ROLE_LEAD),
    RosterEntry("codex", "codex", ROLE_CRITIC),
    RosterEntry("google", "agy", ROLE_VERIFIER),
]


def test_full_loop_with_cross_verification_reaches_a_decision(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, _FULL_ROSTER)
    _install(monkeypatch, ["claude", "codex", "google"], "PASS — looks correct\n(stub output)")
    final = _run(cfg)
    assert final.get("report")                          # REPORT state produced output
    assert "confidence" in final.get("decision", {})    # DECIDE produced a real decision
    # Quorum: ALL three distinct providers ran successfully (lead+critic+verifier), so the
    # cross-provider participation count must be 3 — NOT 1 (the old lead-only plan count,
    # which structurally capped a one-lead roster at 1 even when codex+agy both succeeded).
    assert final.get("providers_ok", 0) == 3
    assert not final.get("advisory")                    # 2+ providers + cross-verify → not advisory
    assert final.get("verify_ok") is True               # the verifier returned PASS
    # producer ≠ verifier: the executor is the lead (claude); the verifier must differ.
    assert final.get("executor") == "claude"
    assert cfg.verifier(exclude="claude") == "google"
    # MEMORY closed the session append-only (a single session_end event).
    assert _session_end_count(cfg) == 1


def test_single_provider_degrades_to_advisory_not_blocked(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, [RosterEntry("claude", "claude", ROLE_LEAD)])
    _install(monkeypatch, ["claude"], "PASS — stub")
    final = _run(cfg)
    assert final.get("advisory") is True                # <2 providers → advisory, NOT a hard block
    assert "confidence" in final.get("decision", {})    # still completes (advisory, capped)
    assert final.get("verify_ok") is False              # no independent verifier available
    assert _session_end_count(cfg) == 1


def test_unwrap_untrusted_recovers_the_verdict_line():
    # Regression for the bug this end-to-end test caught: _ask wraps every adapter output
    # in the untrusted-data envelope, so the verifier's VERDICT is the BODY, not line 0.
    wrapped = mark_untrusted("VERDICT: PASS\nlooks correct")
    assert wrapped.splitlines()[0].startswith("<<<UNTRUSTED")     # the marker WAS line 0
    body = unwrap_untrusted(wrapped)
    assert body.splitlines()[0] == "VERDICT: PASS"                # verdict recoverable
    assert "PASS" in body.split("\n", 1)[0].upper()
    assert unwrap_untrusted("plain") == "plain"                   # unwrapped passes through
    assert unwrap_untrusted("") == ""


def test_failed_verification_retries_then_decides_bounded(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, _FULL_ROSTER)
    _install(monkeypatch, ["claude", "codex", "google"], "FAIL — not convinced")
    final = _run(cfg)
    # A FAIL verdict re-runs EXECUTE up to cfg.max_verify_retries, then DECIDE — it must be
    # bounded (never an infinite execute↔verify loop).
    assert final.get("verify_ok") is False
    assert final.get("verify_retries", 0) >= cfg.max_verify_retries
    assert "confidence" in final.get("decision", {})


class _RecordingAdapter:
    """Records every prompt it receives; replies PASS/FAIL depending on whether the
    prompt is a VERIFY call (detected by the verify template's fixed phrasing) so a
    retry can be forced deterministically.

    ``adapter_for`` is called fresh for every single ``_invoke`` (a new instance per
    call, not a reused one) — so the verify counter MUST live in a shared mutable
    object passed in from the test, not on ``self``, or every instance sees count=0
    and "fails" forever."""
    def __init__(self, calls: list[str], verify_count: list[int], fail_first_verify: bool) -> None:
        self._calls = calls
        self._verify_count = verify_count
        self._fail_first_verify = fail_first_verify

    def run(self, prompt: str, timeout: int = 180) -> _Result:   # noqa: ARG002 (stub)
        self._calls.append(prompt)
        if "Verify independently" in prompt:
            self._verify_count[0] += 1
            if self._fail_first_verify and self._verify_count[0] == 1:
                return _Result("VERDICT: FAIL\nthe date is wrong")
            return _Result("VERDICT: PASS\nlooks correct")
        return _Result("stub output")


def test_retry_execute_prompt_includes_prior_verify_failure(tmp_path, monkeypatch):
    # Regression for the blind-retry bug: route_after_verify() re-enters EXECUTE after a
    # FAIL, but execute() used to rebuild its prompt from task+joint_plan only — the
    # retry had zero information about what failed and could repeat the same mistake.
    cfg = _cfg(tmp_path, _FULL_ROSTER)
    calls: list[str] = []
    verify_count = [0]
    monkeypatch.setattr(graph, "available", lambda cfg: {n: True for n in ["claude", "codex", "google"]})
    monkeypatch.setattr("council.adapters.adapter_for",
                        lambda cfg, name: _RecordingAdapter(calls, verify_count, fail_first_verify=True))
    final = _run(cfg)

    execute_prompts = [c for c in calls if "Produce the final output" in c]
    assert len(execute_prompts) >= 2, "expected an initial EXECUTE call plus at least one retry"
    # First attempt: no prior failure to report yet.
    assert "FAILED independent verification" not in execute_prompts[0]
    # Retry: the previous FAIL verdict must be embedded so the agent fixes the actual issue.
    assert "FAILED independent verification" in execute_prompts[1]
    assert "the date is wrong" in execute_prompts[1]
    # And it must have actually recovered on retry (second verify call replies PASS).
    assert final.get("verify_ok") is True


class _PerAgentAdapter:
    """Replies based on which agent it's bound to (unlike ``_Adapter``'s single shared
    reply) — needed to make different fanned-out verifiers disagree deterministically."""
    def __init__(self, name: str, replies: dict[str, str]) -> None:
        self._name = name
        self._replies = replies

    def run(self, prompt: str, timeout: int = 180) -> _Result:   # noqa: ARG002 (stub)
        return _Result(self._replies.get(self._name, "stub output"))


def _install_per_agent(monkeypatch, names, replies) -> None:
    monkeypatch.setattr(graph, "available", lambda cfg: {n: True for n in names})
    monkeypatch.setattr("council.adapters.adapter_for",
                        lambda cfg, name: _PerAgentAdapter(name, replies))


def test_parallel_verify_off_by_default(tmp_path):
    assert _cfg(tmp_path, _FULL_ROSTER).parallel_verify is False


def test_parallel_verify_all_agree_raises_crossverify_above_one(tmp_path, monkeypatch):
    # Both non-executor agents (codex, google) independently PASS → verify_pass_count=2,
    # which decide.py's min(n_crossverified,3)*weight formula can now actually use — the
    # single-verifier path could never report more than 1.
    cfg = _cfg(tmp_path, _FULL_ROSTER, parallel_verify=True)
    _install_per_agent(monkeypatch, ["claude", "codex", "google"], {
        "codex": "VERDICT: PASS\nchecks out",
        "google": "VERDICT: PASS\nagreed",
    })
    final = _run(cfg)
    assert final.get("verify_pass_count") == 2
    assert final.get("verify_ok") is True
    assert final.get("verify_disagreement") is False
    assert final["decision"]["human_required"] is False


def test_parallel_verify_disagreement_escalates_to_human(tmp_path, monkeypatch):
    # codex says PASS, google says FAIL — a genuine split. Not auto-resolved by majority
    # (Article 7: evidence, not a vote): forces human_required regardless of confidence,
    # and both verdicts land in dissents.
    cfg = _cfg(tmp_path, _FULL_ROSTER, parallel_verify=True)
    _install_per_agent(monkeypatch, ["claude", "codex", "google"], {
        "codex": "VERDICT: PASS\nlooks fine to me",
        "google": "VERDICT: FAIL\nfound a real issue",
    })
    final = _run(cfg)
    assert final.get("verify_disagreement") is True
    assert final.get("verify_pass_count") == 1
    assert final["decision"]["human_required"] is True, (
        "a split verifier verdict must escalate to a human, not be silently vote-resolved"
    )
    dissent_agents = {d["agent"] for d in final.get("dissents", [])}
    assert dissent_agents == {"codex", "google"}


def test_parallel_verify_all_fail_still_retries_then_decides(tmp_path, monkeypatch):
    # Unanimous FAIL is not a disagreement — behaves like the single-verifier FAIL path
    # (bounded retry, then DECIDE), just with every non-executor agent's vote counted.
    cfg = _cfg(tmp_path, _FULL_ROSTER, parallel_verify=True)
    _install_per_agent(monkeypatch, ["claude", "codex", "google"], {
        "codex": "VERDICT: FAIL\nnot convinced",
        "google": "VERDICT: FAIL\nalso not convinced",
    })
    final = _run(cfg)
    assert final.get("verify_disagreement") is False
    assert final.get("verify_pass_count") == 0
    assert final.get("verify_ok") is False
    assert final.get("verify_retries", 0) >= cfg.max_verify_retries
    assert "confidence" in final.get("decision", {})


# --------------------------------------------------------------------------- #
# learn_from_repo — read the target repo's lessons into PLAN, write a new one  #
# on a human-required run (opt-in, default OFF; council/learn.py)              #
# --------------------------------------------------------------------------- #

def test_learn_from_repo_off_by_default(tmp_path):
    assert _cfg(tmp_path, _FULL_ROSTER).learn_from_repo is False


def test_learn_from_repo_reads_lessons_into_plan_prompt(tmp_path, monkeypatch):
    (tmp_path / ".prometheus").mkdir()
    (tmp_path / ".prometheus" / "LESSONS.md").write_text(
        "- 2026-01-01, past mistake: do not delete the staging bucket directly.\n",
        encoding="utf-8")
    cfg = _cfg(tmp_path, _FULL_ROSTER, learn_from_repo=True)
    calls: list[str] = []
    verify_count = [0]
    monkeypatch.setattr(graph, "available", lambda cfg: {n: True for n in ["claude", "codex", "google"]})
    monkeypatch.setattr("council.adapters.adapter_for",
                        lambda cfg, name: _RecordingAdapter(calls, verify_count, fail_first_verify=False))
    _run(cfg)
    plan_prompts = [c for c in calls if c.startswith("Task: tidy the docs")]
    assert plan_prompts, "expected at least one PLAN call"
    assert any("do not delete the staging bucket directly" in p for p in plan_prompts)


def test_learn_from_repo_does_not_read_when_off(tmp_path, monkeypatch):
    (tmp_path / ".prometheus").mkdir()
    (tmp_path / ".prometheus" / "LESSONS.md").write_text(
        "- 2026-01-01, past mistake: should never appear in the prompt.\n", encoding="utf-8")
    cfg = _cfg(tmp_path, _FULL_ROSTER)   # learn_from_repo defaults False
    calls: list[str] = []
    verify_count = [0]
    monkeypatch.setattr(graph, "available", lambda cfg: {n: True for n in ["claude", "codex", "google"]})
    monkeypatch.setattr("council.adapters.adapter_for",
                        lambda cfg, name: _RecordingAdapter(calls, verify_count, fail_first_verify=False))
    _run(cfg)
    assert not any("should never appear in the prompt" in c for c in calls)


def test_learn_from_repo_writes_lesson_when_human_required(tmp_path, monkeypatch):
    # A destructive-shaped EXECUTE output forces exec_needs_human -> decision.human_required,
    # regardless of confidence — the trigger memory() gates the write on.
    cfg = _cfg(tmp_path, _FULL_ROSTER, learn_from_repo=True)
    _install(monkeypatch, ["claude", "codex", "google"], "sure, run: rm -rf /var/data")
    final = _run(cfg)
    assert final["decision"]["human_required"] is True
    lessons_path = tmp_path / ".prometheus" / "LESSONS.md"
    assert lessons_path.is_file()
    text = lessons_path.read_text(encoding="utf-8")
    assert "tidy the docs" in text
    assert "Global candidate: yes" in text   # exec_needs_human is a structural trigger


def test_learn_from_repo_does_not_write_on_routine_completion(tmp_path, monkeypatch):
    # A clean PASS with internal risk completes autonomously (human_required=False) —
    # not lesson-worthy; the file must not even be created.
    cfg = _cfg(tmp_path, _FULL_ROSTER, learn_from_repo=True)
    _install(monkeypatch, ["claude", "codex", "google"], "PASS — looks correct\n(stub output)")
    final = _run(cfg)
    assert final["decision"]["human_required"] is False
    assert not (tmp_path / ".prometheus" / "LESSONS.md").exists()
