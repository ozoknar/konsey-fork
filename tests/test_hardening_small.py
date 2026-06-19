"""Two small hardening fixes a council re-evaluation surfaced.

1. Roster duplicate-name dedupe — the orchestrator indexes by logical name (``plans[name]``,
   ``verifier(exclude=name)``); a duplicate would silently overwrite a prior plan and could
   collapse the producer≠verifier invariant. ``_coerce_agents`` keeps the first, drops later
   collisions.
2. Regime path-traversal negative test — a ``data_regime`` value is used as a path segment
   (``regimes/<regime>.toml``); a value like ``../outside`` must be rejected by the strict
   slug guard so it can never escape the regimes directory (locks in the existing guard).
"""
from __future__ import annotations

from council.config import load_config
from council.gateway import _load_regime_terms
from council.config import Config, replace


def test_roster_duplicate_names_are_deduped(tmp_path):
    cfg_file = tmp_path / "council.local.toml"
    cfg_file.write_text(
        'owner = "op"\n'
        '[[agents]]\nname = "claude"\ncli = "claude"\nrole = "lead"\n'
        '[[agents]]\nname = "claude"\ncli = "claude-evil"\nrole = "verifier"\n'   # collision
        '[[agents]]\nname = "codex"\ncli = "codex"\nrole = "critic"\n',
        encoding="utf-8")
    cfg = load_config(cfg_file)
    names = [a.name for a in cfg.agents]
    assert names == ["claude", "codex"]                 # the second "claude" was dropped
    # the FIRST entry wins (the trustworthy one), not the later "claude-evil" override
    assert next(a for a in cfg.agents if a.name == "claude").cli == "claude"


def test_regime_path_traversal_is_rejected(tmp_path):
    # A malicious/typo regime that tries to climb out of regimes/ resolves to no terms,
    # never an arbitrary file read.
    cfg = Config(council_home=tmp_path, data_regime="../../etc/passwd")
    terms, patterns = _load_regime_terms(cfg)
    assert terms == [] and patterns == []

    # control: a well-formed regime name with no plugin file present also yields nothing,
    # but via the "file absent" path — not the slug rejection (both safe).
    cfg2 = replace(cfg, data_regime="gdpr")
    assert _load_regime_terms(cfg2) == ([], [])
