"""Deterministic orchestrator — LangGraph 9-state machine (Article 5.2 & 6).

9 states: PREFLIGHT → PLAN → CRITIQUE → SYNTHESIZE → EXECUTE → VERIFY → DECIDE → REPORT → MEMORY

Kill switch: budget / wall-time overrun, tool-failure streak ≥ cfg.kill_tool_failures,
stagnation (Article 9.1). Vendor-neutral adapters provide the nodes (Article 2.3);
the decision is evidence-weighted, never a vote (Article 7).

Portability: the roster is NOT hard-coded. Lead/critic/distiller agents come from
``cfg.by_role(role)`` and the verifier from ``cfg.verifier(exclude=executor)`` so the
producer is never its own sole verifier (Article 2.4). With fewer than two providers
the council degrades to *advisory mode* — it does not hard-block; the missing
cross-verification is reflected as a capped confidence in ``decide`` (Article 7.1/7.2).
"""
from __future__ import annotations

import operator
import time
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from . import audit, prompts
from .config import (
    ROLE_CRITIC,
    ROLE_DISTILLER,
    ROLE_LEAD,
    Config,
    available,
)
from .decide import decide
from .exec_policy import classify_command, mark_untrusted, redact_secrets
from .gateway import preflight as gw_preflight
from .i18n import load_catalog, t


class S(TypedDict, total=False):
    task: str
    project_hint: str
    risk: str
    budget: dict
    session_id: str
    blocked: bool
    block_reason: str
    advisory: bool          # < 2 providers OR no cross-verifier → advisory (not blocked)
    advisory_reason: str
    killed: bool
    kill_reason: str
    plans: dict
    providers_ok: int
    executor: str           # logical name of the agent that produced the execution
    critique: str
    joint_plan: str
    execution: str
    exec_needs_human: bool   # 6.2.2: destructive command in output → human gate before run
    verify_verdict: str
    verify_ok: bool
    verify_retries: int
    decision: dict
    report: str
    t_start: float
    evidence: Annotated[list, operator.add]
    dissents: Annotated[list, operator.add]
    calls: Annotated[int, operator.add]
    tool_failures: Annotated[int, operator.add]


def _dead(s: S) -> bool:
    return bool(s.get("killed") or s.get("blocked"))


def _killcheck(s: S, cfg: Config) -> dict:
    """Budget / wall-time / tool-failure kill switch (Article 9.1)."""
    b = s.get("budget", {})
    elapsed = time.time() - s.get("t_start", time.time())
    max_wall = b.get("max_wall_s", 900)
    if elapsed > max_wall:
        cat = load_catalog(cfg)
        return {"killed": True,
                "kill_reason": t(cat, "graph.kill_wall_time", elapsed=int(elapsed), max_wall=max_wall)}
    if s.get("tool_failures", 0) >= cfg.kill_tool_failures:
        cat = load_catalog(cfg)
        return {"killed": True,
                "kill_reason": t(cat, "graph.kill_tool_failures", n=cfg.kill_tool_failures)}
    return {}


def _ask(s: S, cfg: Config, agent: str, prompt_text: str, mtype: str, timeout: int = 180) -> tuple[str, dict]:
    """Run one adapter, audit the message + a terminal-exit evidence row, and return
    ``(text, aggregate-delta)``. Adapter resolution goes through the vendor-neutral
    registry (``adapters.adapter_for``); a missing CLI degrades to a tool failure
    rather than crashing the graph (Article 2.3).

    EXECUTE security boundary (Article 6.2): the adapter's output is **untrusted
    external data**. Secrets are redacted before anything is written to the audit log
    (6.2.5) and the returned text is wrapped with ``mark_untrusted`` so any embedded
    "new instruction / run this" content is treated as data, not a directive, when it
    is fed into the next agent's prompt (6.2.3)."""
    from .adapters import adapter_for  # lazy: keeps build(cfg) importable before adapters lands

    r = adapter_for(cfg, agent).run(prompt_text, timeout=timeout)
    sid = s["session_id"]
    # 6.2.5: redact secrets before the model output touches the audit log.
    safe_text = redact_secrets(r.text)
    audit.message(sid, agent, mtype, {"text": safe_text[:4000], "exit": r.exit_code, "secs": r.seconds}, cfg=cfg)
    ev = {"agent": agent, "type": "terminal_exit", "ok": r.ok, "secs": r.seconds}
    audit.evidence(sid, "terminal_exit", f"{agent} {mtype} exit={r.exit_code} ok={r.ok}", agent,
                   "orchestrator", cfg=cfg)
    # 6.2.3: the adapter output is untrusted data — mark it so the next node treats it
    # as data, not instructions. Already secret-redacted.
    return mark_untrusted(safe_text), {"calls": 1, "tool_failures": 0 if r.ok else 1,
                                       "evidence": [ev], "_ok": r.ok}


def _first(names: list[str], avail: dict[str, bool]) -> str | None:
    """First roster name that is actually available on PATH, else None."""
    for n in names:
        if avail.get(n):
            return n
    return None


# ---------- STATES ----------
def preflight(s: S, cfg: Config) -> dict:
    gw = gw_preflight(s["task"], s.get("project_hint", ""), cfg)
    avail = available(cfg)
    cat = load_catalog(cfg)
    n_prov = sum(1 for v in avail.values() if v)
    sid = audit.start_session(s["task"], gw.risk, gw.budget, user=cfg.owner, cfg=cfg)
    out: dict[str, Any] = {
        "risk": gw.risk, "budget": gw.budget, "session_id": sid,
        "t_start": time.time(), "verify_retries": 0,
        "evidence": [], "dissents": [], "calls": 0, "tool_failures": 0,
    }
    audit.message(sid, "orchestrator", "preflight",
                  {"risk": gw.risk, "providers": avail, "blocked": gw.blocked}, cfg=cfg)
    if gw.blocked:
        out.update(blocked=True, block_reason=gw.block_reason, killed=True, kill_reason=gw.block_reason)
        audit.incident(sid, "gateway_block", gw.block_reason, cfg=cfg)
    elif n_prov < 2:
        # Honest default (Article 7.1): a single provider does NOT block — the council
        # runs in advisory mode with no cross-verification and a capped confidence.
        out.update(advisory=True,
                   advisory_reason=t(cat, "graph.advisory_reason",
                                     n=n_prov, cap=cfg.confidence_cap_noxval))
    return out


def plan(s: S, cfg: Config) -> dict:
    if _dead(s):
        return {}
    k = _killcheck(s, cfg)
    if k:
        return k
    avail = available(cfg)
    cat = load_catalog(cfg)
    plans: dict[str, str] = {}
    agg: dict[str, Any] = {"calls": 0, "tool_failures": 0, "evidence": []}
    ok_count = 0
    # Roster from config, not a literal tuple. Every enabled lead that is on PATH plans.
    leads = [n for n in cfg.by_role(ROLE_LEAD) if avail.get(n)]
    if not leads:
        # No declared leads available → fall back to any available enabled agent so a
        # minimal/advisory roster still produces a plan instead of silently doing nothing.
        leads = [a.name for a in cfg.agents if a.enabled and avail.get(a.name)]
    for agent in leads:
        text, d = _ask(s, cfg, agent, prompts.prompt("plan", cat, task=s["task"]), "plan")
        plans[agent] = text
        ok_count += 1 if d.pop("_ok") else 0
        for key in ("calls", "tool_failures"):
            agg[key] += d[key]
        agg["evidence"] += d["evidence"]
    return {"plans": plans, "providers_ok": ok_count, **agg}


def critique(s: S, cfg: Config) -> dict:
    if _dead(s):
        return {}
    k = _killcheck(s, cfg)
    if k:
        return k
    avail = available(cfg)
    cat = load_catalog(cfg)
    # Critic: first available declared critic, else any available agent.
    critic = _first(cfg.by_role(ROLE_CRITIC), avail) \
        or _first([a.name for a in cfg.agents if a.enabled], avail)
    if not critic:
        return {}  # no agent available → skip critique (advisory/degraded)
    joined = "\n\n".join(f"[{a}]\n{t[:1500]}" for a, t in s.get("plans", {}).items())
    text, d = _ask(s, cfg, critic, prompts.prompt("critique", cat, task=s["task"], plans=joined), "critique")
    out: dict[str, Any] = {"critique": text, "calls": d["calls"],
                           "tool_failures": d["tool_failures"], "evidence": d["evidence"]}
    if "DISSENT" in text.upper():
        audit.dissent(s["session_id"], critic, text[:500], cfg=cfg)
        out["dissents"] = [{"agent": critic, "rationale": text[:500]}]
    return out


def _distiller(cfg: Config, avail: dict[str, bool]) -> str | None:
    """The agent that merges/produces final output: prefer an explicit distiller,
    then a lead, then any available agent."""
    return (_first(cfg.by_role(ROLE_DISTILLER), avail)
            or _first(cfg.by_role(ROLE_LEAD), avail)
            or _first([a.name for a in cfg.agents if a.enabled], avail))


def synthesize(s: S, cfg: Config) -> dict:
    if _dead(s):
        return {}
    avail = available(cfg)
    cat = load_catalog(cfg)
    agent = _distiller(cfg, avail)
    if not agent:
        return {}
    joined = "\n\n".join(f"[{a}]\n{t[:1200]}" for a, t in s.get("plans", {}).items())
    text, d = _ask(s, cfg, agent,
                   prompts.prompt("synthesize", cat, task=s["task"], plans=joined,
                                  critique=s.get("critique", "")[:1500]),
                   "synthesize")
    return {"joint_plan": text, "calls": d["calls"],
            "tool_failures": d["tool_failures"], "evidence": d["evidence"]}


def execute(s: S, cfg: Config) -> dict:
    if _dead(s):
        return {}
    k = _killcheck(s, cfg)
    if k:
        return k
    avail = available(cfg)
    cat = load_catalog(cfg)
    agent = _distiller(cfg, avail)
    if not agent:
        return {}
    text, d = _ask(s, cfg, agent,
                   prompts.prompt("execute", cat, task=s["task"], joint_plan=s.get("joint_plan", "")[:2500]),
                   "execute")
    out: dict[str, Any] = {
        "execution": text, "executor": agent, "calls": d["calls"],
        "tool_failures": d["tool_failures"], "evidence": d["evidence"],
    }
    # Article 6.2.2: if the produced output contains a destructive/privileged command
    # shape it must NOT auto-run — it routes to a human approval gate (Article 5). This
    # MVP does not shell out, so enforcement = flag the session so DECIDE forces
    # human_required and an incident is recorded (the host never runs it unattended).
    if classify_command(text, sandbox=cfg.exec_sandbox) == "needs_human":
        out["exec_needs_human"] = True
        audit.incident(s["session_id"], "destructive_command",
                       t(cat, "graph.incident_destructive"), cfg=cfg)
    return out


def verify(s: S, cfg: Config) -> dict:
    if _dead(s):
        return {}
    avail = available(cfg)
    cat = load_catalog(cfg)
    executor = s.get("executor", "")
    # Cross-verification: producer ≠ verifier. cfg.verifier(exclude=) enforces the
    # invariant in the role layer; None → advisory mode (no independent verifier).
    verifier = cfg.verifier(exclude=executor)
    if verifier and not avail.get(verifier):
        # declared verifier is not on PATH → try any other available agent
        verifier = _first([a.name for a in cfg.agents if a.enabled and a.name != executor], avail)
    if not verifier:
        # No independent verifier available → cannot cross-validate. Mark advisory and
        # record verify_ok=False so decide() applies the no-cross-verification cap (Art.7.2).
        return {"verify_verdict": t(cat, "graph.verify_advisory_verdict"),
                "verify_ok": False,
                "verify_retries": s.get("verify_retries", 0) + 1,
                "advisory": True,
                "advisory_reason": s.get("advisory_reason")
                or t(cat, "graph.verify_advisory_reason")}
    text, d = _ask(s, cfg, verifier,
                   prompts.prompt("verify", cat, task=s["task"], execution=s.get("execution", "")[:2500]),
                   "verify")
    ok = "PASS" in text.split("\n", 1)[0].upper()
    if ok:
        audit.evidence(s["session_id"], "cross_validation", f"{verifier} VERDICT PASS", verifier,
                       "orchestrator", cfg=cfg)
    return {"verify_verdict": text, "verify_ok": ok,
            "verify_retries": s.get("verify_retries", 0) + 1,
            "calls": d["calls"], "tool_failures": d["tool_failures"], "evidence": d["evidence"]}


def route_after_verify(s: S, cfg: Config) -> str:
    if _dead(s):
        return "decide"
    # A failed cross-validation re-runs EXECUTE up to cfg.max_verify_retries. In advisory
    # mode there is no verifier, so retrying cannot help — go straight to decide.
    if (not s.get("verify_ok")
            and not s.get("advisory")
            and s.get("verify_retries", 0) < cfg.max_verify_retries):
        return "execute"
    return "decide"


def decide_node(s: S, cfg: Config) -> dict:
    sid = s["session_id"]
    cat = load_catalog(cfg)
    if _dead(s):
        dec = {"confidence": 0.0, "human_required": True,
               "rationale": s.get("kill_reason") or s.get("block_reason") or t(cat, "graph.aborted")}
        audit.decision(sid, "ABORTED: " + dec["rationale"], 0.0, [], [], False, cfg=cfg)
        return {"decision": dec}
    n_cross = 1 if s.get("verify_ok") else 0
    dec = decide(
        risk=s.get("risk", "internal"),
        n_providers_ok=s.get("providers_ok", 0),
        n_evidence=len(s.get("evidence", [])),
        n_crossverified=n_cross,
        agreement=s.get("providers_ok", 0) >= 2,
        unresolved_dissent=len(s.get("dissents", [])),
        tool_failures=s.get("tool_failures", 0),
        confidence_floor=cfg.confidence_floor,
        confidence_cap_noxval=cfg.confidence_cap_noxval,
        catalog=cat,
    )
    # Article 6.2.2: a destructive command in the output can never auto-run — force the
    # human gate regardless of confidence (immutable core; a high score cannot bypass it).
    human_required = dec.human_required
    rationale = dec.rationale
    if s.get("exec_needs_human"):
        human_required = True
        rationale = (rationale + " | " if rationale else "") + \
            t(cat, "graph.decision_destructive")
    audit.decision(sid, (s.get("execution") or "")[:1000], dec.confidence,
                   list(s.get("evidence", [])), list(s.get("dissents", [])),
                   human_approved=False, cfg=cfg)
    return {"decision": {"confidence": dec.confidence, "human_required": human_required,
                         "rationale": rationale}}


def report(s: S, cfg: Config) -> dict:
    dec = s.get("decision", {})
    cat = load_catalog(cfg)
    elapsed = int(time.time() - s.get("t_start", time.time()))
    lines = [
        t(cat, "report.title", task=s["task"]),
        t(cat, "report.meta", risk=s.get("risk"), elapsed=elapsed, calls=s.get("calls", 0),
          tool_failures=s.get("tool_failures", 0), session=s.get("session_id", "")[:8]),
        "",
    ]
    if s.get("blocked"):
        lines += [t(cat, "report.blocked", reason=s.get("block_reason")), ""]
    if s.get("killed") and not s.get("blocked"):
        lines += [t(cat, "report.kill_switch", reason=s.get("kill_reason")), ""]
    if s.get("advisory") and not _dead(s):
        lines += [t(cat, "report.advisory",
                    reason=s.get("advisory_reason") or t(cat, "report.advisory_default")), ""]
    if s.get("exec_needs_human") and not _dead(s):
        lines += [t(cat, "report.exec_gate"), ""]
    if not _dead(s):
        lines += [
            t(cat, "report.nodes", names=", ".join(s.get("plans", {}).keys()),
              n=s.get("providers_ok", 0)),
            "",
            t(cat, "report.final_output"), (s.get("execution") or "")[:3000], "",
            t(cat, "report.verification",
              verdict=s.get("verify_verdict", t(cat, "report.verification_none"))[:800]), "",
        ]
    if s.get("dissents"):
        lines += [t(cat, "report.dissent_heading")] + \
            [t(cat, "report.dissent_item", agent=d["agent"], rationale=d["rationale"][:300]) for d in s["dissents"]] + [""]
    yesno = t(cat, "report.human_required_yes") if dec.get("human_required") else t(cat, "report.human_required_no")
    lines += [
        t(cat, "report.decision_heading"),
        t(cat, "report.confidence", confidence=dec.get("confidence")),
        t(cat, "report.human_required", value=yesno),
        t(cat, "report.rationale", rationale=dec.get("rationale")),
        t(cat, "report.evidence_count", n=len(s.get("evidence", []))),
    ]
    return {"report": "\n".join(lines)}


def memory(s: S, cfg: Config) -> dict:
    sid = s.get("session_id")
    status = "aborted" if _dead(s) else "done"
    if sid:
        audit.end_session(sid, status, round(s.get("calls", 0) * 0.01, 2), cfg=cfg)
    return {}


def build(cfg: Config):
    """Compile the 9-state graph bound to ``cfg``. Every node and the verify-router
    close over ``cfg`` so the roster, thresholds, owner, and locale are injected once
    here and nowhere hard-coded (the single injection point is ``Config``)."""
    g = StateGraph(S)
    nodes = [
        ("preflight", preflight), ("plan", plan), ("critique", critique),
        ("synthesize", synthesize), ("execute", execute), ("verify", verify),
        ("decide", decide_node), ("report", report), ("memory", memory),
    ]
    for name, fn in nodes:
        g.add_node(name, (lambda f: (lambda s: f(s, cfg)))(fn))
    g.add_edge(START, "preflight")
    g.add_edge("preflight", "plan")
    g.add_edge("plan", "critique")
    g.add_edge("critique", "synthesize")
    g.add_edge("synthesize", "execute")
    g.add_edge("execute", "verify")
    g.add_conditional_edges("verify", lambda s: route_after_verify(s, cfg),
                            {"execute": "execute", "decide": "decide"})
    g.add_edge("decide", "report")
    g.add_edge("report", "memory")
    g.add_edge("memory", END)
    return g.compile()
