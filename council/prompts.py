"""State prompts for the 9-state machine.

English is the canonical embedded default (``Config.locale`` defaults to "en").
Each prompt is a ``str.format``-style template; the orchestrator fills the slots.
A localized catalog (``locales/{locale}.json``) may override any key by id via
``i18n.load_catalog`` — the keys here are the fallback contract.

Keeping the prompts out of ``graph.py`` is the i18n injection point: swapping the
wording (or the language) never touches the state machine.
"""
from __future__ import annotations

from typing import Mapping

# --- Canonical English prompt templates, keyed by state. ---
_EN: dict[str, str] = {
    "plan": (
        "Task: {task}\n"
        "Give your own independent plan/answer: steps, assumptions, risks. "
        "Be short and concrete."
    ),
    "critique": (
        "Council task: {task}\nDraft plans:\n{plans}\n\n"
        "Critique adversarially: disagreements, missing steps, hidden risks. "
        "If you fundamentally disagree with the majority direction, put 'DISSENT:' on the "
        "first line with your reasoning. Be short."
    ),
    "synthesize": (
        "Task: {task}\nPlans:\n{plans}\n\nCritique:\n{critique}\n\n"
        "Produce ONE joint plan/approach that merges them all (Joint Plan). "
        "Short, owned steps."
    ),
    "execute": (
        "Task: {task}\nJoint plan:\n{joint_plan}\n\n"
        "Produce the final output. Concrete, verifiable. Short."
    ),
    "verify": (
        "Task: {task}\nProduced answer:\n{execution}\n\n"
        "Verify independently: are the factual claims consistent? First line "
        "'VERDICT: PASS' or 'VERDICT: FAIL', then 1-3 bullet points of reasoning. Short."
    ),
}


def prompt(key: str, catalog: Mapping[str, str] | None = None, **slots: object) -> str:
    """Resolve prompt ``key`` from ``catalog`` (locale override) then the English
    fallback, and fill ``{slots}``. Missing slots raise — a prompt template and its
    caller must agree, and a silent blank prompt is worse than a loud error."""
    template = (catalog or {}).get(key) or _EN[key]
    return template.format(**slots)
