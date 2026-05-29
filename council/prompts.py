"""State prompts for the 9-state machine — thin resolver over the i18n catalog.

There are **no embedded natural-language templates here** (Art. 17): every prompt
string lives in ``locales/en.json`` (canonical) and its mirrors (``tr.json``). This
module only knows the state *ids* (``plan``/``critique``/… — identifiers, not prose)
and how to look them up under the ``prompts.`` namespace, falling back to canonical
English per-key via :func:`council.i18n.t`.

Keeping the prompts out of ``graph.py`` *and* out of this module's source is the i18n
injection point: swapping the wording or the language never touches Python.
"""
from __future__ import annotations

from typing import Mapping

from . import i18n

# State ids whose prompt text the 9-state machine resolves from the catalog.
# These are machine identifiers (not translatable prose); the prose lives in locales/.
PROMPT_KEYS: tuple[str, ...] = ("plan", "critique", "synthesize", "execute", "verify")

_NS = "prompts."


def catalog_key(key: str) -> str:
    """The namespaced catalog id for a state ``key`` (e.g. 'plan' → 'prompts.plan')."""
    return f"{_NS}{key}"


def prompt(key: str, catalog: Mapping[str, str] | None = None, **slots: object) -> str:
    """Resolve prompt ``key`` from ``catalog`` (locale override) then the canonical
    English catalog, and fill ``{slots}``. Missing slots raise — a prompt template and
    its caller must agree, and a silent blank prompt is worse than a loud error."""
    template = i18n.t(catalog, catalog_key(key))
    return template.format(**slots)
