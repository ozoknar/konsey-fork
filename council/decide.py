"""Evidence-weighted decision (Constitution Article 7) — NOT a vote.

Consensus is a *signal*; decision strength comes from external evidence and
cross-verification. ``risk`` in {phi, production} or ``confidence`` below the
floor escalates to a human. With no cross-verification the confidence is capped
(advisory mode) — a single provider cannot self-certify (producer ≠ verifier).

This function is pure: no I/O, no config object, no globals. Thresholds are
passed in by the caller (``graph.decide_node`` reads them from ``Config``), so a
test or a different deployment can override them without monkey-patching.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .i18n import t

# Defaults mirror council.config module constants; the caller normally overrides
# them from Config so a single instance can be tuned without editing core.
DEFAULT_CONFIDENCE_FLOOR = 0.7
DEFAULT_CONFIDENCE_CAP_NOXVAL = 0.6


@dataclass
class Decision:
    confidence: float
    human_required: bool
    rationale: str


def decide(
    *,
    risk: str,
    n_providers_ok: int,
    n_evidence: int,
    n_crossverified: int,
    agreement: bool,
    unresolved_dissent: int,
    tool_failures: int,
    confidence_floor: float = DEFAULT_CONFIDENCE_FLOOR,
    confidence_cap_noxval: float = DEFAULT_CONFIDENCE_CAP_NOXVAL,
    catalog: Mapping[str, str] | None = None,
) -> Decision:
    """Score a decision on evidence, not on a majority vote (Article 7).

    Args:
        risk: classified risk band (public|internal|pii|phi|production).
        n_providers_ok: how many independent providers produced output (SIGNAL only).
        n_evidence: count of collected external evidence items (secondary weight).
        n_crossverified: outputs verified by another agent / external source (the real weight).
        agreement: did the providers converge on the same answer (signal only).
        unresolved_dissent: count of unresolved objections.
        tool_failures: count of tool failures.
        confidence_floor: below this, escalate to a human (Article 7.3 / 6.7).
        confidence_cap_noxval: ceiling when there is no cross-verification (Article 7.2, advisory).
    """
    score = 0.45
    score += min(n_crossverified, 3) * 0.15      # primary weight: external verification
    score += min(n_evidence, 3) * 0.05           # evidence volume (secondary)
    if agreement and n_providers_ok >= 2:
        score += 0.10                            # consensus is only a small bonus (signal)
    score -= unresolved_dissent * 0.10
    score -= tool_failures * 0.15
    if n_crossverified == 0:
        # No external verification → cap below the human-escalation floor. A single
        # provider (advisory mode) can never clear the bar on its own (Article 7.2).
        score = min(score, confidence_cap_noxval)
    confidence = max(0.0, min(1.0, round(score, 2)))

    # Risk vocabulary is v7's generic set: public|internal|pii|sensitive|production.
    # gateway emits "sensitive" (not "phi"); "phi" kept as a defensive alias so a stray
    # value still escalates. Article 7: {sensitive, production} ALWAYS require a human.
    _SENSITIVE = ("sensitive", "phi", "production")
    # Article 7.1: low confidence forces a human ONLY for sensitive classes (+pii). public/
    # internal advisory-mode tasks complete autonomously (stamped "unverified") — otherwise a
    # single-provider setup deadlocks (no-xval cap 0.6 < floor 0.7 → every task would queue-human).
    low_conf_gate = confidence < confidence_floor and risk in (("pii",) + _SENSITIVE)
    human = (risk in _SENSITIVE) or low_conf_gate
    reasons: list[str] = []
    if risk in _SENSITIVE:
        reasons.append(t(catalog, "decide.human_required_risk", risk=risk))
    if low_conf_gate:
        reasons.append(t(catalog, "decide.low_conf_gate",
                         confidence=confidence, confidence_floor=confidence_floor, risk=risk))
    elif confidence < confidence_floor:
        reasons.append(t(catalog, "decide.low_conf_advisory",
                         confidence=confidence, confidence_floor=confidence_floor, risk=risk))
    if n_crossverified == 0:
        reasons.append(t(catalog, "decide.no_crossverification"))
    if not reasons:
        reasons.append(t(catalog, "decide.threshold_met"))
    return Decision(confidence=confidence, human_required=human, rationale="; ".join(reasons))
