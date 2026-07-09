"""Council configuration — THE single injection point (Constitution Article 0 & 2.3).

Everything machine-specific (owner, org, node name, agent roster, project risk
registry, data regime, paths, scheduler/notifier/secret backends) lives here and
flows out of ``load_config()``. No other core module embeds a brand name, a path,
a project name, or an owner identity. Swapping a provider changes one roster line,
never the architecture.

Read-only at runtime: ``council.local.toml`` (git-ignored, written by Bootstrap)
is parsed with the stdlib ``tomllib`` (Python 3.11+). When the file is absent the
safe defaults below apply (advisory single-agent mode, ``standard`` data regime,
``operator`` owner, ``en`` locale, no background automation).
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

# --- Constitution thresholds (Article 6, 7, 9). Defaults; overridable via config. ---
MAX_VERIFY_RETRIES = 2          # verify→execute retry cap before escalation (Md.6)
KILL_TOOL_FAILURES = 3          # consecutive tool-failure streak → kill switch (Md.9.1)
CONFIDENCE_FLOOR = 0.7          # below this, decision escalates to a human (Md.7.3)
CONFIDENCE_CAP_NOXVAL = 0.6     # no cross-verification → confidence ceiling (Md.7.2, advisory)

# --- decide() scoring weights (Article 7) — evidence-weighted, NOT a vote. Previously
# hardcoded literals inside decide.py; moved here so an operator can tune emphasis
# (e.g. weigh cross-verification more heavily) without editing core. Defaults are
# byte-identical to the pre-existing hardcoded values — this is a pure refactor. ---
DECIDE_BASE_SCORE = 0.45              # starting score before any evidence is applied
DECIDE_CROSSVERIFY_WEIGHT = 0.15      # per cross-verified outcome, capped at 3 (primary weight)
DECIDE_EVIDENCE_WEIGHT = 0.05         # per evidence item, capped at 3 (secondary weight)
DECIDE_CONSENSUS_BONUS = 0.10         # agreement AND >=2 providers (signal only, small)
DECIDE_DISSENT_PENALTY = 0.10         # per unresolved dissent
DECIDE_TOOL_FAILURE_PENALTY = 0.15    # per tool failure

# --- Role names are generic and provider-independent (Constitution Article 3). ---
ROLE_LEAD = "lead"
ROLE_CRITIC = "critic"
ROLE_RESEARCHER = "researcher"
ROLE_VERIFIER = "verifier"
ROLE_DISTILLER = "distiller"

_CONFIG_FILENAME = "council.local.toml"


def _default_extra_path() -> str:
    """Platform-typical bin dirs prepended to PATH so an installed CLI is never
    silently missed (critique §2). The macOS/ARM Homebrew prefix is kept on purpose."""
    home = Path.home()
    return os.pathsep.join([
        str(home / ".local" / "bin"),
        "/opt/homebrew/bin",   # mac-arm reasonable default — kept intentionally
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
    ])


def _default_council_home() -> Path:
    """Repo root = script-relative (Article 0.2). ``config.py`` lives in ``council/``."""
    env = os.environ.get("KONSEY_HOME") or os.environ.get("COUNCIL_HOME")
    if env:
        return Path(env).expanduser().resolve()
    return Path(__file__).resolve().parent.parent


def _default_data_home() -> Path:
    """XDG-style data dir; falls back to ``~/.local/share/council`` (audit.py DB lives here)."""
    env = os.environ.get("KONSEY_DATA_HOME") or os.environ.get("COUNCIL_DATA_HOME")
    if env:
        return Path(env).expanduser().resolve()
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg).expanduser() if xdg else (Path.home() / ".local" / "share")
    return (base / "council").resolve()


@dataclass(frozen=True)
class RosterEntry:
    """One provider in the roster. ``cli`` is the executable resolved on PATH; ``role``
    is one of the generic roles (lead/critic/researcher/verifier/distiller)."""
    name: str               # logical adapter name, e.g. "claude", "codex", "google"
    cli: str                # executable invoked as subprocess, e.g. "claude", "agy"
    role: str               # generic role from ROLE_* constants
    enabled: bool = True


@dataclass(frozen=True)
class ProjectEntry:
    """Project risk registry entry. ``match`` is a glob; ``risk`` is one of
    public|internal|pii|phi|production. A project name alone never implies phi (Md.4.4)."""
    match: str
    risk: str = "internal"


@dataclass(frozen=True)
class Config:
    """The portable runtime profile. All machine-facts arrive here and nowhere else."""
    council_home: Path = field(default_factory=_default_council_home)
    data_home: Path = field(default_factory=_default_data_home)
    bridge_dir: Path | None = None          # autocapture inbox/outbox; None → autocapture inert
    owner: str = "operator"                 # NOT $USER — never leak the machine username to audit
    org: str = ""
    node_name: str = ""
    locale: str = "en"
    data_regime: str = "standard"           # standard|kvkk|gdpr|hipaa (Md.4.3)
    preset: str = "balanced"                 # onboarding posture: advisory|balanced|autonomous (S4, provenance)
    agents: list[RosterEntry] = field(default_factory=list)
    projects: list[ProjectEntry] = field(default_factory=list)
    secret_backend: str = "null"            # keychain|secret-tool|wincred|envfile|null
    scheduler: str = "null"                 # launchd|systemd|schtasks|cron|null
    notifier: str = "null"                  # osascript|notify-send|win-toast|null
    exec_sandbox: str = "off"               # off|read-only|workspace-write (Md.6.2)
    autocapture_enabled: bool = False       # opt-in; default OFF (Md.0.7)
    unsafe_inherit_provider_config: bool = False # opt-in: do not isolate node subprocess environment (PR2)
    parallel_plan: bool = False             # opt-in: fan the PLAN providers out concurrently (default OFF, Md.3)
    parallel_plan_max: int = 4              # concurrency cap for the PLAN fan-out (bounded resource use)
    parallel_verify: bool = False           # opt-in: fan VERIFY out to every non-executor agent (default OFF)
    parallel_verify_max: int = 4            # concurrency cap for the VERIFY fan-out (bounded resource use)
    verify_cmd: str = ""                    # opt-in: real acceptance command run at VERIFY (exit-code > LLM, Md.2.1/2.7)
    extra_path: str = field(default_factory=_default_extra_path)
    budgets: dict[str, dict[str, Any]] = field(default_factory=dict)
    # thresholds (per-instance, default to module constants)
    max_verify_retries: int = MAX_VERIFY_RETRIES
    kill_tool_failures: int = KILL_TOOL_FAILURES
    confidence_floor: float = CONFIDENCE_FLOOR
    confidence_cap_noxval: float = CONFIDENCE_CAP_NOXVAL
    decide_base_score: float = DECIDE_BASE_SCORE
    decide_crossverify_weight: float = DECIDE_CROSSVERIFY_WEIGHT
    decide_evidence_weight: float = DECIDE_EVIDENCE_WEIGHT
    decide_consensus_bonus: float = DECIDE_CONSENSUS_BONUS
    decide_dissent_penalty: float = DECIDE_DISSENT_PENALTY
    decide_tool_failure_penalty: float = DECIDE_TOOL_FAILURE_PENALTY

    # ----- roster resolution (kills the hard-coded ("claude","codex","google")) -----

    def by_role(self, role: str) -> list[str]:
        """Return logical agent names assigned to ``role``, enabled only, in roster order.
        graph.py reads its roster from here instead of a literal tuple (Md.3)."""
        return [a.name for a in self.agents if a.enabled and a.role == role]

    def verifier(self, exclude: str) -> str | None:
        """Pick a verifier whose *provider/name* differs from the executor (producer ≠
        verifier invariant, Md.2.4). Prefers an explicit ``verifier`` role; falls back to
        any other enabled agent. Returns None → advisory mode (no cross-verification)."""
        verifiers = [a for a in self.agents if a.enabled and a.role == ROLE_VERIFIER and a.name != exclude]
        if verifiers:
            return verifiers[0].name
        # fallback: any enabled agent that is not the producer
        for a in self.agents:
            if a.enabled and a.name != exclude:
                return a.name
        return None

    # ----- path helpers (XDG-derived; nothing hard-coded) -----

    def db_path(self) -> Path:
        """Append-only audit DuckDB file (Md.10)."""
        return self.data_home / "council.duckdb"

    def config_path(self) -> Path:
        """Where ``council.local.toml`` is read from / written to."""
        return self.council_home / _CONFIG_FILENAME

    def logs_dir(self) -> Path:
        return self.data_home / "logs"

    def sessions_dir(self) -> Path:
        return self.data_home / "sessions"

    def locales_dir(self) -> Path:
        return self.council_home / "council" / "locales"

    def ensure_dirs(self) -> None:
        """Create the data dirs lazily (no side effects at import time)."""
        for d in (self.data_home, self.logs_dir(), self.sessions_dir()):
            d.mkdir(parents=True, exist_ok=True)


def _coerce_agents(raw: Any) -> list[RosterEntry]:
    out: list[RosterEntry] = []
    seen: set[str] = set()
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        # Logical name is the key the orchestrator indexes by (plans[name],
        # verifier(exclude=name)); a duplicate would silently overwrite a prior plan and
        # could collapse producer≠verifier. Keep the FIRST entry, drop later collisions.
        if name in seen:
            continue
        seen.add(name)
        out.append(RosterEntry(
            name=name,
            cli=str(item.get("cli", name)).strip() or name,
            role=str(item.get("role", ROLE_LEAD)).strip() or ROLE_LEAD,
            enabled=bool(item.get("enabled", True)),
        ))
    return out


def _coerce_projects(raw: Any) -> list[ProjectEntry]:
    out: list[ProjectEntry] = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        match = str(item.get("match", "")).strip()
        if not match:
            continue
        out.append(ProjectEntry(match=match, risk=str(item.get("risk", "internal")).strip() or "internal"))
    return out


def load_config(path: str | os.PathLike[str] | None = None) -> Config:
    """Load ``council.local.toml`` if present; otherwise return safe defaults.

    Resolution order for the config file:
      1. explicit ``path`` argument
      2. ``$KONSEY_CONFIG`` (preferred) or ``$COUNCIL_CONFIG`` (deprecated) env var
      3. ``<council_home>/council.local.toml``
    Unknown keys are ignored. Parse/IO errors degrade to defaults (fail-open on
    *config*, never on the security gate — that lives in gateway.py)."""
    import tomllib

    home = _default_council_home()
    if path is not None:
        cfg_file: Path | None = Path(path).expanduser()
    elif os.environ.get("KONSEY_CONFIG") or os.environ.get("COUNCIL_CONFIG"):
        cfg_file = Path(os.environ.get("KONSEY_CONFIG") or os.environ["COUNCIL_CONFIG"]).expanduser()
    else:
        cfg_file = home / _CONFIG_FILENAME

    if cfg_file is None or not cfg_file.exists():
        return Config()

    try:
        with open(cfg_file, "rb") as fh:
            data = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        return Config()

    base = Config()
    council_home = Path(data.get("council_home", base.council_home)).expanduser()
    data_home = Path(data["data_home"]).expanduser() if data.get("data_home") else base.data_home
    bridge = data.get("bridge_dir")
    bridge_dir = Path(bridge).expanduser() if bridge else None

    return replace(
        base,
        council_home=council_home,
        data_home=data_home,
        bridge_dir=bridge_dir,
        owner=str(data.get("owner", base.owner)) or base.owner,
        org=str(data.get("org", base.org)),
        node_name=str(data.get("node_name", base.node_name)),
        locale=str(data.get("locale", base.locale)) or base.locale,
        data_regime=str(data.get("data_regime", base.data_regime)) or base.data_regime,
        preset=str(data.get("preset", base.preset)) or base.preset,   # old profiles → "balanced"
        agents=_coerce_agents(data.get("agents")),
        projects=_coerce_projects(data.get("projects")),
        secret_backend=str(data.get("secret_backend", base.secret_backend)) or base.secret_backend,
        scheduler=str(data.get("scheduler", base.scheduler)) or base.scheduler,
        notifier=str(data.get("notifier", base.notifier)) or base.notifier,
        exec_sandbox=str(data.get("exec_sandbox", base.exec_sandbox)) or base.exec_sandbox,
        autocapture_enabled=bool(data.get("autocapture_enabled", base.autocapture_enabled)),
        unsafe_inherit_provider_config=bool(data.get("unsafe_inherit_provider_config", base.unsafe_inherit_provider_config)),
        parallel_plan=bool(data.get("parallel_plan", base.parallel_plan)),
        parallel_plan_max=max(1, int(data.get("parallel_plan_max", base.parallel_plan_max))),
        parallel_verify=bool(data.get("parallel_verify", base.parallel_verify)),
        parallel_verify_max=max(1, int(data.get("parallel_verify_max", base.parallel_verify_max))),
        verify_cmd=str(data.get("verify_cmd", base.verify_cmd)) or base.verify_cmd,
        extra_path=str(data.get("extra_path", base.extra_path)) or base.extra_path,
        budgets=dict(data.get("budgets", base.budgets)),
        max_verify_retries=int(data.get("max_verify_retries", base.max_verify_retries)),
        kill_tool_failures=int(data.get("kill_tool_failures", base.kill_tool_failures)),
        confidence_floor=float(data.get("confidence_floor", base.confidence_floor)),
        confidence_cap_noxval=float(data.get("confidence_cap_noxval", base.confidence_cap_noxval)),
        decide_base_score=float(data.get("decide_base_score", base.decide_base_score)),
        decide_crossverify_weight=float(data.get("decide_crossverify_weight", base.decide_crossverify_weight)),
        decide_evidence_weight=float(data.get("decide_evidence_weight", base.decide_evidence_weight)),
        decide_consensus_bonus=float(data.get("decide_consensus_bonus", base.decide_consensus_bonus)),
        decide_dissent_penalty=float(data.get("decide_dissent_penalty", base.decide_dissent_penalty)),
        decide_tool_failure_penalty=float(data.get("decide_tool_failure_penalty", base.decide_tool_failure_penalty)),
    )


def available(cfg: Config) -> dict[str, bool]:
    """Evidence-based roster health: is each agent's CLI actually resolvable on PATH?
    (``council doctor`` uses this; Md.0.2/0.5.) PATH is augmented with ``cfg.extra_path``
    so a Homebrew-installed CLI is not silently reported missing."""
    search_path = os.pathsep.join([cfg.extra_path, os.environ.get("PATH", "")])
    out: dict[str, bool] = {}
    for a in cfg.agents:
        if not a.enabled:
            out[a.name] = False
            continue
        out[a.name] = shutil.which(a.cli, path=search_path) is not None
    return out
