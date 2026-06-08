"""Konsey deterministik orkestratör — LangGraph state machine (Anayasa Madde 5.2 & 6).

9 durum: PREFLIGHT → PLAN → CRITIQUE → SYNTHESIZE → EXECUTE → VERIFY → DECIDE → REPORT → MEMORY
Kill switch: bütçe/wall-time aşımı, tool-failure-streak≥3, stagnation (Madde 9.1).
Vendor-neutral adapter ile 3 düğüm (Madde 2.3); kanıt-ağırlıklı karar (Madde 7).
"""
from __future__ import annotations

import operator
import os
import time
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

from . import audit
from .adapters import ADAPTERS, available, pick
from .decide import decide
from .gateway import preflight as gw_preflight

MAX_VERIFY_RETRIES = 2


class S(TypedDict, total=False):
    task: str
    project_hint: str
    risk: str
    budget: dict
    session_id: str
    blocked: bool
    block_reason: str
    killed: bool
    kill_reason: str
    plans: dict
    providers_ok: int
    critique: str
    joint_plan: str
    execution: str
    verify_verdict: str
    verify_ok: bool
    verify_self: bool
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


def _killcheck(s: S) -> dict:
    """Bütçe / wall-time / tool-failure kill switch (Madde 9.1)."""
    b = s.get("budget", {})
    elapsed = time.time() - s.get("t_start", time.time())
    if elapsed > b.get("max_wall_s", 900):
        return {"killed": True, "kill_reason": f"wall-time aşıldı ({int(elapsed)}s > {b.get('max_wall_s')}s)"}
    if s.get("tool_failures", 0) >= 3:
        return {"killed": True, "kill_reason": "ardışık 3 tool failure (Madde 9.1)"}
    return {}


# ---------- DURUMLAR ----------
def preflight(s: S) -> dict:
    gw = gw_preflight(s["task"], s.get("project_hint", ""))
    avail = available()
    n_prov = sum(avail.values())
    sid = audit.start_session(s["task"], gw.risk, gw.budget)
    out = {
        "risk": gw.risk, "budget": gw.budget, "session_id": sid,
        "t_start": time.time(), "verify_retries": 0,
        "evidence": [], "dissents": [], "calls": 0, "tool_failures": 0,
    }
    audit.message(sid, "orchestrator", "preflight",
                  {"risk": gw.risk, "providers": avail, "blocked": gw.blocked})
    if gw.blocked:
        out.update(blocked=True, block_reason=gw.block_reason, killed=True, kill_reason=gw.block_reason)
        audit.incident(sid, "gateway_block", gw.block_reason)
    else:
        _min = int(os.getenv("KONSEY_PROVIDERS_MIN") or
                   (2 if os.getenv("KONSEY_SECURITY_LEVEL", "medium").lower() == "strict" else 1))
        if n_prov < _min:
            out.update(blocked=True,
                       block_reason=f"Yalnız {n_prov} sağlayıcı — gereken min {_min} (strict→2, medium/weak→1)",
                       killed=True, kill_reason="insufficient_providers")
    return out


def _ask(s: S, agent: str, prompt: str, mtype: str, timeout: int = 180) -> tuple[str, dict]:
    r = ADAPTERS[agent].run(prompt, timeout=timeout)
    sid = s["session_id"]
    audit.message(sid, agent, mtype, {"text": r.text[:4000], "exit": r.exit_code, "secs": r.seconds})
    ev = {"agent": agent, "type": "terminal_exit", "ok": r.ok, "secs": r.seconds}
    audit.evidence(sid, "terminal_exit", f"{agent} {mtype} exit={r.exit_code} ok={r.ok}", agent, "orchestrator")
    return r.text, {"calls": 1, "tool_failures": 0 if r.ok else 1, "evidence": [ev], "_ok": r.ok}


def _lead(avail: dict | None = None) -> str:
    """Lead/architect sağlayıcısı: rol 'architect' olan ilk kullanılabilir; yoksa herhangi biri."""
    avail = avail if avail is not None else available()
    return (pick("architect", avail)
            or next((n for n, ok in avail.items() if ok), None)
            or next(iter(ADAPTERS), "claude"))


def plan(s: S) -> dict:
    if _dead(s):
        return {}
    k = _killcheck(s)
    if k:
        return k
    avail = available()
    plans, agg = {}, {"calls": 0, "tool_failures": 0, "evidence": []}
    ok_count = 0
    for agent in [n for n, ok in avail.items() if ok]:
        prompt = (f"Görev: {s['task']}\nBağımsız planını/cevabını ver: adımlar, varsayımlar, "
                  f"riskler. Kısa ve somut ol.")
        text, d = _ask(s, agent, prompt, "plan")
        plans[agent] = text
        ok_count += 1 if d.pop("_ok") else 0
        for key in ("calls", "tool_failures"):
            agg[key] += d[key]
        agg["evidence"] += d["evidence"]
    return {"plans": plans, "providers_ok": ok_count, **agg}


def critique(s: S) -> dict:
    if _dead(s):
        return {}
    k = _killcheck(s)
    if k:
        return k
    avail = available()
    critic = pick("critic", avail) or _lead(avail)
    joined = "\n\n".join(f"[{a}]\n{t[:1500]}" for a, t in s.get("plans", {}).items())
    prompt = (f"Konsey görevi: {s['task']}\nTaslak planlar:\n{joined}\n\n"
              f"Adversarial eleştir: anlaşmazlıklar, eksik adımlar, gizli riskler. "
              f"Çoğunluk yönüne TEMELDEN katılmıyorsan ilk satıra 'DISSENT:' yazıp gerekçe ver. Kısa.")
    text, d = _ask(s, critic, prompt, "critique")
    out = {"critique": text, "calls": d["calls"], "tool_failures": d["tool_failures"], "evidence": d["evidence"]}
    if "DISSENT" in text.upper():
        audit.dissent(s["session_id"], critic, text[:500])
        out["dissents"] = [{"agent": critic, "rationale": text[:500]}]
    return out


def synthesize(s: S) -> dict:
    if _dead(s):
        return {}
    joined = "\n\n".join(f"[{a}]\n{t[:1200]}" for a, t in s.get("plans", {}).items())
    prompt = (f"Görev: {s['task']}\nPlanlar:\n{joined}\n\nEleştiri:\n{s.get('critique','')[:1500]}\n\n"
              f"Hepsini birleştiren TEK ortak plan/yaklaşım üret (Joint Plan). Kısa, sahipli adımlar.")
    text, d = _ask(s, _lead(), prompt, "synthesize")
    return {"joint_plan": text, "calls": d["calls"], "tool_failures": d["tool_failures"], "evidence": d["evidence"]}


def execute(s: S) -> dict:
    if _dead(s):
        return {}
    k = _killcheck(s)
    if k:
        return k
    prompt = (f"Görev: {s['task']}\nOrtak plan:\n{s.get('joint_plan','')[:2500]}\n\n"
              f"Nihai çıktıyı üret. Somut, doğrulanabilir. Kısa.")
    text, d = _ask(s, _lead(), prompt, "execute")
    return {"execution": text, "calls": d["calls"], "tool_failures": d["tool_failures"], "evidence": d["evidence"]}


def verify(s: S) -> dict:
    if _dead(s):
        return {}
    avail = available()
    # Çapraz doğrulama: üreten (lead) doğrulayamaz → farklı bir sağlayıcı doğrular
    lead = _lead(avail)
    verifier = pick("researcher", avail, exclude=(lead,)) or pick("critic", avail, exclude=(lead,)) or lead
    self_check = (verifier == lead)   # tek sağlayıcı → kendi-kontrolü, BAĞIMSIZ çapraz değil
    prompt = (f"Görev: {s['task']}\nÜretilen cevap:\n{s.get('execution','')[:2500]}\n\n"
              f"Bağımsız doğrula: olgusal iddialar tutarlı mı? İlk satır 'VERDICT: PASS' veya "
              f"'VERDICT: FAIL', sonra 1-3 madde gerekçe. Kısa.")
    text, d = _ask(s, verifier, prompt, "verify")
    ok = "PASS" in text.split("\n", 1)[0].upper()
    if ok:
        etype = "self_check" if self_check else "cross_validation"
        audit.evidence(s["session_id"], etype, f"{verifier} VERDICT PASS ({etype})", verifier, "orchestrator")
    return {"verify_verdict": text, "verify_ok": ok, "verify_self": self_check,
            "verify_retries": s.get("verify_retries", 0) + 1,
            "calls": d["calls"], "tool_failures": d["tool_failures"], "evidence": d["evidence"]}


def route_after_verify(s: S) -> str:
    if _dead(s):
        return "decide"
    if not s.get("verify_ok") and s.get("verify_retries", 0) < MAX_VERIFY_RETRIES:
        return "execute"   # başarısız doğrulama → EXECUTE'a dön (max 2)
    return "decide"


def decide_node(s: S) -> dict:
    sid = s["session_id"]
    if _dead(s):
        dec = {"confidence": 0.0, "human_required": True,
               "rationale": s.get("kill_reason") or s.get("block_reason") or "aborted"}
        audit.decision(sid, "ABORTED: " + dec["rationale"], 0.0, [], [], False)
        return {"decision": dec}
    n_cross = (1 if (s.get("verify_ok") and not s.get("verify_self")) else 0)
    dec = decide(
        risk=s.get("risk", "internal"),
        n_providers_ok=s.get("providers_ok", 0),
        n_evidence=len(s.get("evidence", [])),
        n_crossverified=n_cross,
        agreement=s.get("providers_ok", 0) >= 2,
        unresolved_dissent=len(s.get("dissents", [])),
        tool_failures=s.get("tool_failures", 0),
    )
    audit.decision(sid, (s.get("execution") or "")[:1000], dec.confidence,
                   [e for e in s.get("evidence", [])], [d for d in s.get("dissents", [])],
                   human_approved=False)
    return {"decision": {"confidence": dec.confidence, "human_required": dec.human_required,
                         "rationale": dec.rationale}}


def report(s: S) -> dict:
    dec = s.get("decision", {})
    elapsed = int(time.time() - s.get("t_start", time.time()))
    lines = [
        f"# Konsey Raporu — {s['task']}",
        f"risk={s.get('risk')} · süre={elapsed}s · çağrı={s.get('calls',0)} · "
        f"tool_failures={s.get('tool_failures',0)} · session={s.get('session_id','')[:8]}",
        "",
    ]
    if s.get("blocked"):
        lines += [f"⛔ GATEWAY BLOKLADI: {s.get('block_reason')}", ""]
    if s.get("killed") and not s.get("blocked"):
        lines += [f"🛑 KILL SWITCH: {s.get('kill_reason')}", ""]
    if not _dead(s):
        lines += [
            f"**Düğümler:** {', '.join(s.get('plans', {}).keys())} ({s.get('providers_ok',0)} ok)",
            "",
            "## Nihai çıktı", (s.get("execution") or "")[:3000], "",
            f"## Doğrulama\n{s.get('verify_verdict','(yok)')[:800]}", "",
        ]
    if s.get("dissents"):
        lines += ["## Dissent"] + [f"- [{d['agent']}] {d['rationale'][:300]}" for d in s["dissents"]] + [""]
    lines += [
        "## Karar",
        f"- confidence: **{dec.get('confidence')}**",
        f"- insan onayı gerekli mi: **{'EVET' if dec.get('human_required') else 'hayır'}**",
        f"- gerekçe: {dec.get('rationale')}",
        f"- kanıt sayısı: {len(s.get('evidence', []))}",
    ]
    return {"report": "\n".join(lines)}


def memory(s: S) -> dict:
    sid = s.get("session_id")
    status = "aborted" if _dead(s) else "done"
    if sid:
        audit.end_session(sid, status, round(s.get("calls", 0) * 0.01, 2))
    try:  # opt-in anonim telemetri (yalnız metadata; ana akışı bozmaz)
        from . import telemetry
        telemetry.emit("council_run", status=status, risk_class=s.get("risk"),
                       providers_count=s.get("providers_ok", 0),
                       duration_ms=int((time.time() - s.get("t_start", time.time())) * 1000),
                       security_level=os.getenv("KONSEY_SECURITY_LEVEL", "medium"))
    except Exception:
        pass
    return {}


def build():
    g = StateGraph(S)
    for name, fn in [("preflight", preflight), ("plan", plan), ("critique", critique),
                     ("synthesize", synthesize), ("execute", execute), ("verify", verify),
                     ("decide", decide_node), ("report", report), ("memory", memory)]:
        g.add_node(name, fn)
    g.add_edge(START, "preflight")
    g.add_edge("preflight", "plan")
    g.add_edge("plan", "critique")
    g.add_edge("critique", "synthesize")
    g.add_edge("synthesize", "execute")
    g.add_edge("execute", "verify")
    g.add_conditional_edges("verify", route_after_verify, {"execute": "execute", "decide": "decide"})
    g.add_edge("decide", "report")
    g.add_edge("report", "memory")
    g.add_edge("memory", END)
    return g.compile()
