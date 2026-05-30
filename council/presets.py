"""Onboarding posture presets (S4).

A *preset* is an opinionated bundle of already-safe ``Config`` values — a convenience
grouping, never a way to unlock something unsafe by name. The axis is OPERATING POSTURE
(how much konsey may do on its own), inspired by rustup's minimal/default/complete
profiles: pick one named bundle instead of answering a long question list.

Honesty invariants (Constitution Art. 2.1 / 6 / 7), enforced BY CONSTRUCTION here and
asserted in tests:
  * No preset ever sets ``exec_sandbox = "workspace-write"``. The most aggressive preset
    (``autonomous``) only *arms the first lock* (``read-only``); ``konsey do`` still
    refuses unless ``exec_sandbox != "off"`` AND ``KONSEY_EXEC=1`` AND a TTY confirm — the
    triple-lock is untouched, so a preset can never silently grant autonomous writes.
  * No preset enables autocapture (``autocapture_enabled`` stays its default ``False`` —
    capture is opt-in via ``konsey enable capture`` with a consent/PHI explainer).
  * No preset selects a non-``standard`` data regime (a regime is only ever a detection
    aid, never a compliance claim).
  * Confidence behaviour is identical across presets (the <2-provider advisory cap is a
    runtime invariant, not a toggle). ``advisory`` simply enables a single provider so the
    profile HONESTLY runs in advisory mode and the name matches the behaviour.
"""
from __future__ import annotations

# Ordered for stable display (advisory → balanced → autonomous = safest → most armed).
PRESET_NAMES: tuple[str, ...] = ("advisory", "balanced", "autonomous")
PRESETS: frozenset[str] = frozenset(PRESET_NAMES)
DEFAULT_PRESET = "balanced"

# Each preset touches ONLY these two knobs; everything else (locale, owner, detected
# backends, roster membership) comes from negotiation/detection, never from the preset.
#   exec_sandbox : "off" | "read-only"  (NEVER "workspace-write" — see module docstring)
#   roster_enable: "all" | "lead-only"  ("lead-only" → single provider → advisory mode)
_TABLE: dict[str, dict[str, str]] = {
    "advisory":   {"exec_sandbox": "off",       "roster_enable": "lead-only"},
    "balanced":   {"exec_sandbox": "off",       "roster_enable": "all"},
    "autonomous": {"exec_sandbox": "read-only", "roster_enable": "all"},
}


def preset_overrides(name: str | None) -> dict[str, str]:
    """Config-field overrides for a posture preset. Pure (no detection, no I/O).

    Unknown / ``None`` name → the ``balanced`` default (fail-safe: an unrecognised
    posture must never resolve to something MORE permissive). Returns a fresh dict."""
    return dict(_TABLE.get((name or "").strip().lower(), _TABLE[DEFAULT_PRESET]))


def normalize_preset(name: str | None) -> str:
    """A valid preset name, or ``DEFAULT_PRESET`` for anything unrecognised."""
    key = (name or "").strip().lower()
    return key if key in PRESETS else DEFAULT_PRESET
