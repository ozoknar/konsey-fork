"""PREFLIGHT gateway — the enforcer of Constitution Article 4 & 5.

At PREFLIGHT: risk classification + secret/identity scan + budget policy. A
secret hit, or a sensitive-data hit under a regulatory data regime, does not go
to the council unmasked — it routes to a human approval / local pipeline.

Design invariants (portable core):
  * No project name alone implies sensitivity (Article 4.4). Risk is driven by
    the project risk *registry* (``cfg.projects``) and by generic data/secret
    signals — never by a hard-coded brand or product name.
  * ``SECRET_PATTERNS`` are generic, public token *format* signatures (provider-
    independent pattern recognition, not a brand endorsement or dependency).
  * Clinical / national-identity term lists are NOT in this core file. They live
    only in regime plugins (``regimes/*.toml``) and are activated by
    ``cfg.data_regime`` (Article 4.3). The detection regimes are a *gate aid*,
    NOT a legal-compliance guarantee; liability rests with the operator.
"""
from __future__ import annotations

import fnmatch
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config
from .i18n import load_catalog, t

# --- Generic prod / pii / public signals (provider- and project-name-independent) ---
# These are language-and-intent signals, not brand names. A project name alone
# never escalates risk (Article 4.4); the project risk *registry* does that.
PROD_HINTS = re.compile(
    r"\b(production|prod|live|deploy|deployment|release|master push|push to (?:main|master)|"
    r"database|migration|withdraw|live trade|real money|credential rotat|rotate (?:key|secret))\b",
    re.IGNORECASE,
)
PII_HINTS = re.compile(
    r"\b(employee|personnel|contact list|phone list|e-?mail list|payroll|hr record)\b",
    re.IGNORECASE,
)
PUBLIC_SIGNAL = re.compile(
    r"\b(public|open[- ]?source|documentation|readme|architecture|compare|summari[sz]e|improve)\b",
    re.IGNORECASE,
)

# --- Secret / identity scanners (both input AND output channels are scanned, Md.4.2) ---
# Public token FORMAT signatures only. New format = one registry line; core unchanged.
SECRET_PATTERNS = {
    "api_key_generic": re.compile(r"\bsk-[A-Za-z0-9]{20,}"),
    "bearer": re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{20,}"),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"),
    # modern formats — SINGLE SOURCE shared by gate (capture) + mask + preflight/dispatch (F3/F10)
    "anthropic": re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}"),
    "stripe": re.compile(r"\b(?:sk|pk|rk)_(?:live|test)_[A-Za-z0-9]{16,}"),
    "aws_akia": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "github_pat": re.compile(r"\bgh[posr]_[A-Za-z0-9]{20,}\b"),
    "slack": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    "openai_new": re.compile(r"\bsk-(?:proj|svcacct|admin)-[A-Za-z0-9_\-]{20,}\b"),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b"),
    "secret_kv": re.compile(
        r"(?i)\b(?:api[_-]?key|secret|token|password|passwd|pwd|client[_-]?secret)\b"
        r"\s*[:=]\s*['\"]?"
        r"(?!process\.env|import\.meta|your_|xxx+|<|\$\{|example|placeholder|none|null|true|false|redacted)"
        r"[A-Za-z0-9_\-.]{12,}"
    ),
}

# --- Budget policy per risk class (Article 5 & 12). standard is the default regime. ---
# Risk vocabulary: public | internal | pii | sensitive | production. The "phi" alias
# maps to "sensitive" so a risk-registry value is always budgeted (Md.4.3 / config contract).
BUDGET = {
    "public":     dict(max_iter=5, max_wall_s=900, max_cost=2.0, human_required=False),
    "internal":   dict(max_iter=5, max_wall_s=900, max_cost=2.0, human_required=False),
    "pii":        dict(max_iter=4, max_wall_s=600, max_cost=2.0, human_required=False),
    "sensitive":  dict(max_iter=3, max_wall_s=600, max_cost=1.0, human_required=True),
    "production": dict(max_iter=3, max_wall_s=900, max_cost=2.0, human_required=True),
}
# Backwards/contract alias: callers using "phi" get the sensitive budget.
BUDGET["phi"] = BUDGET["sensitive"]

_RISK_ORDER = ["public", "internal", "pii", "sensitive", "production"]
_RISK_RANK = {r: i for i, r in enumerate(_RISK_ORDER)}
# Registry "phi" is treated as "sensitive" for ranking/budgeting.
_RISK_RANK["phi"] = _RISK_RANK["sensitive"]

# A regime is "regulated" (activates clinical/identity term plugins, Article 4.3) iff it
# is not the "standard" baseline — its terms/regexes then come from a regimes/<name>.toml
# pack DISCOVERED on disk, never from a hardcoded jurisdiction list. De-domestication:
# any jurisdiction (gdpr/hipaa/kvkk/lgpd/ccpa/pipl/pdpa/…) drops in as data, no core edit.
def _is_regulated(regime: str | None) -> bool:
    return bool(regime) and (regime or "").strip().lower() != "standard"


@dataclass
class GatewayResult:
    risk: str
    budget: dict
    blocked: bool = False
    block_reason: str = ""
    secrets_found: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _registry_risk(project_hint: str, cfg: Config) -> str | None:
    """Highest risk class whose glob in ``cfg.projects`` matches the project hint.
    A project name alone never *implies* sensitivity — it is sensitive only because
    the operator put it in the registry (Article 4.4)."""
    hint = (project_hint or "").strip()
    if not hint:
        return None
    best: str | None = None
    best_rank = -1
    for entry in cfg.projects:
        if fnmatch.fnmatch(hint, entry.match):
            rank = _RISK_RANK.get(entry.risk, _RISK_RANK["internal"])
            if rank > best_rank:
                best, best_rank = entry.risk, rank
    return best


def _load_regime_terms(cfg: Config) -> tuple[list[str], list[re.Pattern[str]]]:
    """Load clinical/identity terms + identifier regexes from the active regime
    plugin (``regimes/<regime>.toml`` under council_home). Returns empty lists for
    the ``standard`` regime or when no plugin file is present. These lists are NEVER
    embedded in core — single source is the plugin file (Article 4.3, no double-source)."""
    regime = (cfg.data_regime or "standard").strip().lower()
    if not _is_regulated(regime):
        return [], []
    # The regime name is used as a path segment — require a safe slug so a config value
    # like "../outside" can never escape regimes/ (Codex de-domestication finding).
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", regime):
        return [], []
    plugin = Path(cfg.council_home) / "regimes" / f"{regime}.toml"
    if not plugin.exists():
        return [], []
    try:
        with open(plugin, "rb") as fh:
            data = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        # fail-safe: a broken regime file must not silently disable the gate.
        return [], []
    terms = [str(t) for t in (data.get("terms") or []) if str(t).strip()]
    patterns: list[re.Pattern[str]] = []
    for ident in data.get("identifiers") or []:
        if not isinstance(ident, dict):
            continue
        pat = ident.get("pattern")
        if not pat:
            continue
        try:
            patterns.append(re.compile(str(pat)))
        except re.error:
            continue
    return terms, patterns


def regime_loaded(cfg: Config) -> bool:
    """True iff a *regulated* data regime is active AND its term plugin actually
    loaded at least one term/identifier (Article 4.1 fail-open guard).

    Returns False when:
      * the regime is ``standard`` (no plugin expected — not a misconfiguration), or
      * a regulated regime is set but ``regimes/<regime>.toml`` is missing/empty/broken
        (the dangerous fail-open case: detection silently disabled).

    ``council doctor`` uses this to surface a VISIBLE warning so ``data_regime=hipaa``
    without a term file is never mistaken for active clinical detection. The secret
    scan is always on regardless; this only concerns the regime term plugin."""
    regime = (cfg.data_regime or "standard").strip().lower()
    if not _is_regulated(regime):
        return False
    terms, patterns = _load_regime_terms(cfg)
    return bool(terms or patterns)


def _regime_hit(text: str, cfg: Config) -> bool:
    """True if the active regulatory regime's clinical/identity markers appear in text."""
    terms, patterns = _load_regime_terms(cfg)
    if not terms and not patterns:
        return False
    blob = text or ""
    low = blob.lower()
    for term in terms:
        if term.lower() in low:
            return True
    for pat in patterns:
        if pat.search(blob):
            return True
    return False


def classify_risk(task: str, project_hint: str, cfg: Config) -> str:
    """Risk class from generic signals + the project risk registry. No brand/product
    name is consulted; ``cfg.projects`` (operator-defined) is the only project source."""
    blob = f"{task} {project_hint}"

    if PROD_HINTS.search(blob):
        risk = "production"
    elif _regime_hit(blob, cfg):          # regulated-regime clinical/identity marker → sensitive
        risk = "sensitive"
    elif PII_HINTS.search(blob):
        risk = "pii"
    else:
        risk = "internal"

    # Public intent demotes a plain internal task (aligns with the constitution's
    # public class); it never overrides a higher class.
    if risk == "internal" and PUBLIC_SIGNAL.search(blob):
        risk = "public"

    # The project risk registry can only RAISE the floor, never lower it (Md.18:
    # profile may tighten, never loosen).
    reg = _registry_risk(project_hint, cfg)
    if reg is not None and _RISK_RANK.get(reg, -1) > _RISK_RANK.get(risk, -1):
        risk = "sensitive" if reg == "phi" else reg

    return risk


def scan_secrets(text: str) -> list[str]:
    found = []
    for name, pat in SECRET_PATTERNS.items():
        if pat.search(text or ""):
            found.append(name)
    return found


def preflight(task: str, project_hint: str = "", cfg: Config | None = None) -> GatewayResult:
    """Classify risk, scan secrets, attach the budget, and decide whether the task
    is blocked from going to the council unmasked / without human approval."""
    if cfg is None:
        cfg = Config()
    cat = load_catalog(cfg)

    risk = classify_risk(task, project_hint, cfg)
    budget = BUDGET.get(risk, BUDGET["internal"])
    # F10: project_hint is also sent to the LLM, so it is scanned too.
    secrets = scan_secrets(f"{task} {project_hint}")
    res = GatewayResult(risk=risk, budget=dict(budget), secrets_found=secrets)

    if risk == "sensitive":
        res.blocked = True
        res.block_reason = t(cat, "gateway.block_sensitive")
    if secrets:
        res.blocked = True
        res.block_reason = (res.block_reason + " | " if res.block_reason else "") + \
            t(cat, "gateway.block_secret", secrets=secrets)

    if risk in ("sensitive", "production"):
        res.notes.append(t(cat, "gateway.note_human_approval"))
    if _is_regulated(cfg.data_regime):
        res.notes.append(t(cat, "gateway.note_regime", regime=cfg.data_regime))

    return res
