"""Evidence-weighted decision tests (Constitution Article 7) — NOT a vote.

Hard invariants Phase 2 may NOT relax (Article 18):
  * no cross-verification  →  confidence capped at confidence_cap_noxval (0.6)
  * risk in {phi, production}  →  human_required, regardless of confidence
  * the floor (0.7) / cap (0.6) themselves are not relaxable; only the additive
    score weights are profile-overridable.

Runs against the REAL pure ``council.decide.decide``.
"""
from __future__ import annotations

import inspect

import pytest

from council.config import CONFIDENCE_CAP_NOXVAL, CONFIDENCE_FLOOR
from council.decide import decide


def _call(**kw):
    """Pass only kwargs the signature accepts so the test survives minor signature
    evolution while still exercising the real function."""
    sig = inspect.signature(decide)
    accepted = {k: v for k, v in kw.items() if k in sig.parameters}
    return decide(**accepted)


_STRONG = dict(
    risk="internal", n_providers_ok=3, n_evidence=3, n_crossverified=3,
    agreement=True, unresolved_dissent=0, tool_failures=0,
)
_NOXVAL = dict(
    risk="internal", n_providers_ok=1, n_evidence=3, n_crossverified=0,
    agreement=False, unresolved_dissent=0, tool_failures=0,
)


def test_threshold_constants_are_not_relaxed():
    assert CONFIDENCE_FLOOR == 0.7
    assert CONFIDENCE_CAP_NOXVAL == 0.6


def test_no_crossverification_caps_confidence_at_0_6():
    d = _call(**_NOXVAL)
    assert d.confidence <= CONFIDENCE_CAP_NOXVAL + 1e-9, (
        f"with zero cross-verification confidence must be capped at "
        f"{CONFIDENCE_CAP_NOXVAL}, got {d.confidence}"
    )


def test_crossverified_decision_can_exceed_the_noxval_cap():
    d = _call(**_STRONG)
    assert d.confidence > CONFIDENCE_CAP_NOXVAL, (
        "cross-verified, well-evidenced decisions must be able to clear the 0.6 cap"
    )
    assert 0.0 <= d.confidence <= 1.0


@pytest.mark.parametrize("risk", ["sensitive", "phi", "production"])
def test_sensitive_and_production_always_require_human(risk):
    # Even a perfectly-scored decision escalates for these classes (Art.7). "sensitive" is
    # the canonical v7 class the gateway emits; "phi" is the defensive alias.
    d = _call(**{**_STRONG, "risk": risk})
    assert d.human_required is True


def test_high_confidence_low_risk_runs_autonomously():
    d = _call(**_STRONG)
    assert d.human_required is False, (
        "a strong, cross-verified internal-risk decision should not need a human"
    )


def test_low_confidence_escalates_only_for_sensitive_risk():
    # Article 7.1: no-xval caps confidence at 0.6 < floor 0.7. That low confidence escalates
    # to a human ONLY for sensitive classes (pii/phi/production). public/internal complete
    # autonomously, stamped advisory — otherwise a single-provider setup deadlocks (every
    # task would queue-human).
    internal = _call(**_NOXVAL)                       # risk=internal
    assert internal.confidence < CONFIDENCE_FLOOR
    assert internal.human_required is False, "internal low-confidence must run advisory, not escalate"
    sensitive = _call(**{**_NOXVAL, "risk": "pii"})
    assert sensitive.confidence < CONFIDENCE_FLOOR
    assert sensitive.human_required is True, "pii low-confidence must escalate to human (Art.7.1)"


def test_dissent_and_tool_failures_lower_confidence():
    base = _call(**_STRONG).confidence
    noisy = _call(**{**_STRONG, "unresolved_dissent": 2, "tool_failures": 1}).confidence
    assert noisy < base, "unresolved dissent and tool failures must reduce confidence"


def test_confidence_is_bounded_unit_interval():
    d = _call(risk="internal", n_providers_ok=0, n_evidence=0, n_crossverified=0,
              agreement=False, unresolved_dissent=10, tool_failures=10)
    assert 0.0 <= d.confidence <= 1.0


def test_custom_thresholds_are_honoured_if_supported():
    # If the signature exposes overridable thresholds, a *lower* floor must stop the
    # human escalation that the default floor (0.7) would trigger for a 0.6 decision.
    sig = inspect.signature(decide)
    if "confidence_floor" not in sig.parameters:
        pytest.skip("decide does not expose overridable thresholds")
    # On a sensitive risk, 0.6 < default floor 0.7 → escalates; a lower 0.5 floor stops it.
    # (Use pii: per Art.7.1 internal would never escalate on low confidence alone.)
    noxval_pii = {**_NOXVAL, "risk": "pii"}
    assert decide(**noxval_pii).human_required is True
    assert decide(**noxval_pii, confidence_floor=0.5).human_required is False


def test_decision_carries_a_rationale():
    d = _call(**_NOXVAL)
    assert getattr(d, "rationale", "")  # decisions are explainable, not opaque
