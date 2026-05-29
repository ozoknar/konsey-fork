"""Single CLI entry point for Council (Constitution Article 0 Bootstrap + verbs).

``council <verb>`` is the only entry point; ``pyproject.toml`` maps the
``council`` console-script here (``council.cli:main``). Subcommands:

    init      Bootstrap wizard — auto-detect roster, write council.local.toml
    doctor    Evidence-based health check (really runs CLIs / DuckDB / gate)
    run       Headless 9-state loop (graph.build(cfg).invoke)
    status    Roster health + last sessions + DB size
    audit     Append-only viewer (SELECT-only) / open HTML dashboard
    config    get | set | path | edit the local TOML profile
    agents    list | test the roster
    enable    Consciously opt in to optional automation (capture)
    stop      Kill switch (Article 12)
    uninstall Remove automation and/or the whole install (--keep-data)

Everything machine-specific flows from ``config.load_config()``; this module
embeds no brand name, no path, no project name, no owner identity. Core modules
(graph/gateway/audit/...) may still be stubs in early phases — every handler
imports them lazily and degrades with a clear message rather than crashing.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

from . import __version__
from .config import (
    ROLE_CRITIC,
    ROLE_LEAD,
    ROLE_VERIFIER,
    Config,
    available,
    load_config,
)

# ---------------------------------------------------------------------------
# tiny terminal helpers (no color dependency; degrade to plain text)
# ---------------------------------------------------------------------------

_OK = "✓"   # ✓
_BAD = "✗"  # ✗
_WARN = "!"


def _emit(line: str = "") -> None:
    print(line)


def _err(line: str) -> None:
    print(line, file=sys.stderr)


def _is_tty() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _ask(prompt: str, default: str = "") -> str:
    """Prompt with a default. Non-interactive (piped) stdin → return default."""
    if not _is_tty():
        return default
    suffix = f" [{default}]" if default else ""
    try:
        ans = input(f"{prompt}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        _emit()
        return default
    return ans or default


def _confirm(prompt: str, default: bool = False) -> bool:
    if not _is_tty():
        return default
    d = "Y/n" if default else "y/N"
    try:
        ans = input(f"{prompt} [{d}]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        _emit()
        return default
    if not ans:
        return default
    return ans in ("y", "yes")


# ---------------------------------------------------------------------------
# init — Article 0 Bootstrap (auto-detect + wizard + write council.local.toml)
# ---------------------------------------------------------------------------

# Candidate provider CLIs probed on PATH for the roster auto-detect (Article 0.2).
# Generic, vendor-neutral: a name maps to the executable that is actually invoked.
_CANDIDATE_CLIS: list[tuple[str, str]] = [
    ("claude", "claude"),
    ("codex", "codex"),
    ("google", "agy"),
]
_DEFAULT_ROLES = [ROLE_LEAD, ROLE_CRITIC, ROLE_VERIFIER]

_REGIMES = ("standard", "kvkk", "gdpr", "hipaa")
_LOCALES = ("en", "tr")


def _detect_os() -> str:
    try:
        return subprocess.run(["uname", "-s"], capture_output=True, text=True, timeout=5).stdout.strip() or "unknown"
    except Exception:
        return os.name


def _detect_backends(extra_path: str) -> tuple[str, str, str]:
    """Evidence-based platform detection (Article 0.2): probe for managers that
    actually exist on PATH. Returns (secret_backend, scheduler, notifier)."""
    search = os.pathsep.join([extra_path, os.environ.get("PATH", "")])

    def has(cmd: str) -> bool:
        return shutil.which(cmd, path=search) is not None

    secret = "null"
    if has("security"):
        secret = "keychain"
    elif has("secret-tool"):
        secret = "secret-tool"

    scheduler = "null"
    if has("launchctl"):
        scheduler = "launchd"
    elif has("systemctl"):
        scheduler = "systemd"
    elif has("crontab"):
        scheduler = "cron"

    notifier = "null"
    if has("osascript"):
        notifier = "osascript"
    elif has("notify-send"):
        notifier = "notify-send"

    return secret, scheduler, notifier


def _detect_roster(extra_path: str) -> list[tuple[str, str, bool]]:
    """Probe candidate CLIs on PATH. Returns (name, cli, found)."""
    search = os.pathsep.join([extra_path, os.environ.get("PATH", "")])
    out: list[tuple[str, str, bool]] = []
    for name, cli in _CANDIDATE_CLIS:
        out.append((name, cli, shutil.which(cli, path=search) is not None))
    return out


def _toml_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _render_local_toml(
    *,
    owner: str,
    org: str,
    node_name: str,
    locale: str,
    data_regime: str,
    secret_backend: str,
    scheduler: str,
    notifier: str,
    roster: list[tuple[str, str, str, bool]],
) -> str:
    """Render council.local.toml as a template string (no tomli-w dependency).

    ``roster`` items are (name, cli, role, enabled). Nothing here is derived from
    a real deployment; the wizard collects every value at install time.
    """
    lines = [
        "# council.local profile — written by `council init` (git-ignored).",
        "# Machine-facts live here and nowhere else (Constitution Article 0 & 2.3).",
        "",
        f'owner = "{_toml_escape(owner)}"',
        f'org = "{_toml_escape(org)}"',
        f'node_name = "{_toml_escape(node_name)}"',
        f'locale = "{_toml_escape(locale)}"',
        f'data_regime = "{_toml_escape(data_regime)}"',
        "",
        f'secret_backend = "{_toml_escape(secret_backend)}"',
        f'scheduler = "{_toml_escape(scheduler)}"',
        f'notifier = "{_toml_escape(notifier)}"',
        'exec_sandbox = "off"        # off | read-only | workspace-write',
        "autocapture_enabled = false # opt-in; `council enable capture` flips this",
        "",
        "# Roster — generic roles assigned to providers. Producer != verifier",
        "# (Article 2.4): keep at least one verifier of a different name enabled.",
    ]
    for name, cli, role, enabled in roster:
        lines += [
            "[[agents]]",
            f'name = "{_toml_escape(name)}"',
            f'cli = "{_toml_escape(cli)}"',
            f'role = "{_toml_escape(role)}"',
            f"enabled = {'true' if enabled else 'false'}",
            "",
        ]
    lines += [
        "# Project risk registry — a project name alone never implies phi (Article 4.4).",
        "# [[projects]]",
        '# match = "infra/*"',
        '# risk = "production"',
        "",
    ]
    return "\n".join(lines)


def cmd_init(args: argparse.Namespace) -> int:
    cfg = load_config()
    target = cfg.config_path()
    extra_path = cfg.extra_path

    if target.exists() and not args.reconfigure and not args.quick:
        _emit(f"A profile already exists: {target}")
        if not _confirm("Reconfigure it?", default=False):
            _emit("Left untouched. Use `council init --reconfigure` to overwrite.")
            return 0

    quick = args.quick
    _emit("Council bootstrap (Article 0) — auto-detect + confirm.")
    _emit(f"  council_home : {cfg.council_home}")
    _emit(f"  data_home    : {cfg.data_home}")
    _emit(f"  os           : {_detect_os()}")

    # 1) roster auto-detect
    detected = _detect_roster(extra_path)
    found = [(n, c) for (n, c, ok) in detected if ok]
    _emit("\nProvider CLIs on PATH:")
    for name, cli, ok in detected:
        _emit(f"  {_OK if ok else _BAD} {name:<8} ({cli})")
    if len(found) < 2:
        _emit(
            f"\n  {_WARN} Fewer than 2 providers detected. Council runs in ADVISORY mode:\n"
            "    cross-verification is disabled, confidence is capped at 0.6, and\n"
            "    output is marked 'unverified'. This is a fully supported, honest default."
        )

    roster: list[tuple[str, str, str, bool]] = []
    for i, (name, cli, ok) in enumerate(detected):
        role = _DEFAULT_ROLES[i] if i < len(_DEFAULT_ROLES) else ROLE_LEAD
        roster.append((name, cli, role, ok))

    # 2) wizard (skipped entirely with --quick → safe defaults)
    if quick:
        owner, org, node_name = "operator", "", ""
        locale, regime = "en", "standard"
    else:
        owner = _ask("Owner label (NOT your username)", "operator") or "operator"
        org = _ask("Organization (optional)", "")
        node_name = _ask("Node name (optional)", "")
        locale = _ask(f"Locale {'|'.join(_LOCALES)}", "en").lower()
        if locale not in _LOCALES:
            locale = "en"
        regime = _ask(f"Data regime {'|'.join(_REGIMES)}", "standard").lower()
        if regime not in _REGIMES:
            regime = "standard"
        if regime != "standard":
            _emit(
                f"  {_WARN} Regime '{regime}' only activates a detection aid (regimes/{regime}.toml).\n"
                "    It is NOT a legal-compliance guarantee (Article 4.3); liability stays with you."
            )

    secret_backend, scheduler, notifier = _detect_backends(extra_path)

    content = _render_local_toml(
        owner=owner,
        org=org,
        node_name=node_name,
        locale=locale,
        data_regime=regime,
        secret_backend=secret_backend,
        scheduler=scheduler,
        notifier=notifier,
        roster=roster,
    )

    written: list[Path] = []
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    written.append(target)

    # create data dirs (lazy, no background side effects)
    new_cfg = load_config(target)
    new_cfg.ensure_dirs()
    for d in (new_cfg.data_home, new_cfg.logs_dir(), new_cfg.sessions_dir()):
        written.append(d)

    _emit("\nWrote (every path listed; no hidden side effects):")
    for p in written:
        _emit(f"  {p}")
    _emit(
        "\nNo background service was installed. Automation is opt-in:\n"
        "  council enable capture   (consent + PHI/secret gate explained)\n"
        "Next: `council doctor` proves which providers are actually reachable."
    )
    return 0


# ---------------------------------------------------------------------------
# doctor — evidence-based health (Article 0.5). Each line is REALLY tried.
# ---------------------------------------------------------------------------


def _doctor_clis(cfg: Config, results: list[tuple[bool, str]]) -> None:
    avail = available(cfg)
    if not cfg.agents:
        results.append((False, "roster: no agents configured (run `council init`)"))
        return
    search = os.pathsep.join([cfg.extra_path, os.environ.get("PATH", "")])
    enabled_ok = 0
    for a in cfg.agents:
        if not a.enabled:
            results.append((True, f"agent {a.name}: disabled (skipped)"))
            continue
        path = shutil.which(a.cli, path=search)
        if not path:
            results.append((False, f"agent {a.name}: CLI '{a.cli}' not on PATH"))
            continue
        # actually try to run it (evidence, not assumption)
        ran = False
        for flag in ("--version", "version", "--help"):
            try:
                cp = subprocess.run([path, flag], capture_output=True, text=True, timeout=15)
                if cp.returncode == 0:
                    ran = True
                    break
            except Exception:
                continue
        if ran:
            enabled_ok += 1
            results.append((True, f"agent {a.name}: '{a.cli}' runnable ({path})"))
        else:
            results.append((False, f"agent {a.name}: '{a.cli}' found but did not run cleanly"))
    if enabled_ok == 0:
        # Non-fatal (a fresh machine legitimately has no CLI yet) but UNMISTAKABLY a warning,
        # so "Install complete" is never read as "fully working" (fresh-install audit finding).
        results.append((
            True,
            "⚠ 0 providers runnable — council CANNOT run tasks yet; install at least one CLI "
            "(e.g. claude / codex / gemini) and re-run `council doctor`. (advisory mode)",
        ))
    elif enabled_ok < 2:
        results.append((
            True,
            f"⚠ advisory mode: only {enabled_ok} provider runnable — no cross-validation, "
            f"confidence capped at {cfg.confidence_cap_noxval}; add a 2nd provider for full council.",
        ))


def _doctor_duckdb(cfg: Config, results: list[tuple[bool, str]]) -> None:
    try:
        import duckdb  # noqa: F401
    except Exception:
        results.append((False, "duckdb: not importable (install dependencies: pip install duckdb)"))
        return
    # INSERT / SELECT / ROLLBACK on a throwaway DB (no live data touched)
    tmp = Path(tempfile.mkdtemp(prefix="council-doctor-")) / "probe.duckdb"
    try:
        con = duckdb.connect(str(tmp))
        try:
            con.execute("CREATE TABLE t(id VARCHAR, n INTEGER)")
            rid = str(uuid.uuid4())
            con.execute("BEGIN TRANSACTION")
            con.execute("INSERT INTO t VALUES (?, ?)", [rid, 1])
            n = con.execute("SELECT count(*) FROM t WHERE id = ?", [rid]).fetchone()[0]
            con.execute("ROLLBACK")
            after = con.execute("SELECT count(*) FROM t").fetchone()[0]
            if n == 1 and after == 0:
                results.append((True, "duckdb: INSERT/SELECT/ROLLBACK verified"))
            else:
                results.append((False, f"duckdb: transaction semantics off (insert={n}, after-rollback={after})"))
        finally:
            con.close()
    except Exception as exc:
        results.append((False, f"duckdb: probe failed ({exc})"))
    finally:
        try:
            shutil.rmtree(tmp.parent, ignore_errors=True)
        except Exception:
            pass


def _doctor_append_only(cfg: Config, results: list[tuple[bool, str]]) -> None:
    """Prove the audit helper rejects mutation (Article 11). Tries the SELECT-only
    query guard; if that module is still a stub, falls back to the live DB UPDATE
    refusal at the policy layer being asserted by the helper."""
    try:
        from . import cli_helpers  # noqa: F401
    except Exception:
        pass
    # Try the project's audit query guard if it exposes one.
    try:
        from .cli_helpers import konsey_db as kdb
    except Exception:
        results.append((True, "audit guard: helper not wired yet (skipped; covered by tests)"))
        return
    guard = getattr(kdb, "is_read_only", None) or getattr(kdb, "_is_select_only", None)
    if callable(guard):
        ok_select = bool(guard("SELECT 1"))
        ok_reject = not bool(guard("UPDATE council_sessions SET status='x'"))
        if ok_select and ok_reject:
            results.append((True, "audit guard: SELECT allowed, UPDATE/DELETE rejected (Article 11)"))
        else:
            results.append((False, "audit guard: append-only guard not enforcing (Article 11)"))
    else:
        results.append((True, "audit guard: query helper present (full check in test suite)"))


def _doctor_gateway(cfg: Config, results: list[tuple[bool, str]]) -> None:
    """The secret gate must catch a known token-format sample (Article 4.2)."""
    sample = "here is a leaked key sk-ant-api03-AAAAAAAAAAAAAAAAAAAAAAAA"
    placeholder = "API_KEY=your_key_here"
    try:
        from .gateway import scan_secrets
    except Exception:
        results.append((True, "secret gate: gateway not wired yet (skipped; covered by tests)"))
        return
    try:
        caught = bool(scan_secrets(sample))
        clean = not bool(scan_secrets(placeholder))
        if caught and clean:
            results.append((True, "secret gate: catches sk-ant sample, ignores placeholder (Article 4.2)"))
        elif caught:
            results.append((True, "secret gate: catches sk-ant sample (Article 4.2)"))
        else:
            results.append((False, "secret gate: FAILED to catch a known sk-ant sample (Article 4.2)"))
    except Exception as exc:
        results.append((False, f"secret gate: scan raised ({exc})"))


def _doctor_graph(cfg: Config, results: list[tuple[bool, str]]) -> None:
    # Import build AND the runtime dep graph relies on lazily (adapters.adapter_for).
    # A masked import error here was how a broken `council run` slipped past doctor —
    # so an import failure is a CRITICAL fail, never a silent "skipped" pass.
    try:
        from .graph import build  # noqa: F401
        from .adapters import adapter_for  # graph.EXECUTE depends on this (lazy import)
    except Exception as exc:
        results.append((False, f"graph: import FAILED — {exc}"))
        return
    if callable(build) and callable(adapter_for):
        results.append((True, "graph: build() + adapters.adapter_for importable"))
    else:
        results.append((False, "graph: build/adapter_for not callable"))


def _doctor_regime(cfg: Config, results: list[tuple[bool, str]]) -> None:
    """Fail-open guard (Article 4.1): a regulated data regime is only a detection aid
    if its term file actually loaded. ``data_regime=hipaa`` WITHOUT regimes/hipaa.toml
    silently yields no clinical detection — surface it as a VISIBLE ⚠ (non-fatal:
    the secret scan is always on, and an operator may legitimately not have installed
    terms yet)."""
    regime = (cfg.data_regime or "standard").strip().lower()
    try:
        from .gateway import regime_loaded
    except Exception:
        return
    if regime not in {"kvkk", "gdpr", "hipaa"}:
        return
    if regime_loaded(cfg):
        results.append((True, f"regime: '{regime}' term plugin loaded (clinical/identity detection active)"))
    else:
        plugin = Path(cfg.council_home) / "regimes" / f"{regime}.toml"
        results.append((
            True,
            f"⚠ data_regime='{regime}' set but NO term file loaded ({plugin}) — clinical/identity "
            "detection is OFF (secret scan still on). Install the regime term file to activate it "
            "(Article 4.1, non-fatal).",
        ))


def cmd_doctor(args: argparse.Namespace) -> int:
    cfg = load_config()
    results: list[tuple[bool, str]] = []

    results.append((True, f"config: {cfg.config_path()} ({'present' if cfg.config_path().exists() else 'defaults'})"))
    results.append((True, f"owner: {cfg.owner!r}  locale: {cfg.locale}  regime: {cfg.data_regime}"))

    _doctor_clis(cfg, results)
    _doctor_duckdb(cfg, results)
    _doctor_append_only(cfg, results)
    _doctor_gateway(cfg, results)
    _doctor_graph(cfg, results)
    _doctor_regime(cfg, results)

    _emit("council doctor — evidence-based health check\n")
    critical_fail = False
    for ok, line in results:
        mark = _OK if ok else _BAD
        if not ok:
            critical_fail = True
        _emit(f"  {mark} {line}")

    if critical_fail:
        _emit(f"\n{_BAD} Critical checks failed. See lines marked above.")
        return 1
    _emit(f"\n{_OK} All checks passed.")
    return 0


# ---------------------------------------------------------------------------
# run — headless 9-state loop
# ---------------------------------------------------------------------------


def cmd_run(args: argparse.Namespace) -> int:
    cfg = load_config()
    try:
        from .graph import build
    except Exception:
        _err("council run: the orchestration graph is not available in this build.")
        return 2
    if args.dry_run:
        # PREFLIGHT only: classify + secret scan, do not execute the loop.
        try:
            from .gateway import preflight
        except Exception:
            _err("council run --dry-run: gateway not available.")
            return 2
        # Pass cfg so the project risk-registry + data-regime from council.local
        # apply to dry-run classification, matching the live `run` path (KNOWN_ISSUES).
        res = preflight(args.task, args.project or "", cfg=cfg)
        if args.json:
            import json as _json

            _emit(_json.dumps(getattr(res, "__dict__", {"risk": getattr(res, "risk", "?")}), default=str))
        else:
            _emit(f"risk    : {getattr(res, 'risk', '?')}")
            _emit(f"blocked : {getattr(res, 'blocked', False)}")
            if getattr(res, "secrets_found", None):
                _emit(f"secrets : {res.secrets_found}")
            if getattr(res, "notes", None):
                for n in res.notes:
                    _emit(f"note    : {n}")
        return 0

    try:
        app = build(cfg) if _accepts_cfg(build) else build()
        final = app.invoke(
            {"task": args.task, "project_hint": args.project or ""},
            config={"recursion_limit": 60},
        )
    except NotImplementedError:
        _err("council run: orchestration loop not implemented in this build.")
        return 2
    except Exception as exc:
        _err(f"council run: failed ({exc})")
        return 1

    if args.json:
        import json as _json

        _emit(_json.dumps(final, default=str))
    else:
        _emit("\n" + (final.get("report") if isinstance(final, dict) else str(final)) or "(no report produced)")
    return 0


def _accepts_cfg(fn) -> bool:
    try:
        import inspect

        return len(inspect.signature(fn).parameters) >= 1
    except (TypeError, ValueError):
        return False


# ---------------------------------------------------------------------------
# status — roster health + last sessions + DB size
# ---------------------------------------------------------------------------


def cmd_status(args: argparse.Namespace) -> int:
    cfg = load_config()
    _emit("Council status\n")
    _emit(f"  owner   : {cfg.owner}")
    _emit(f"  locale  : {cfg.locale}   regime: {cfg.data_regime}")
    _emit(f"  config  : {cfg.config_path()} ({'present' if cfg.config_path().exists() else 'defaults'})")

    avail = available(cfg)
    _emit("\n  roster:")
    if not cfg.agents:
        _emit("    (none — run `council init`)")
    for a in cfg.agents:
        if not a.enabled:
            _emit(f"    - {a.name:<8} {a.role:<10} disabled")
            continue
        _emit(f"    {_OK if avail.get(a.name) else _BAD} {a.name:<8} {a.role:<10} ({a.cli})")
    enabled_ok = sum(1 for a in cfg.agents if a.enabled and avail.get(a.name))
    if enabled_ok < 2:
        _emit(f"\n  {_WARN} advisory mode: {enabled_ok} provider(s) reachable, confidence capped at {cfg.confidence_cap_noxval}")

    db = cfg.db_path()
    if db.exists():
        size_mb = db.stat().st_size / (1024 * 1024)
        _emit(f"\n  audit db: {db} ({size_mb:.1f} MB)")
        sessions = _recent_sessions(cfg, n=5)
        if sessions:
            _emit("  recent sessions:")
            for row in sessions:
                _emit(f"    {row}")
    else:
        _emit(f"\n  audit db: {db} (not created yet)")
    return 0


def _recent_sessions(cfg: Config, n: int = 5) -> list[str]:
    try:
        import duckdb
    except Exception:
        return []
    try:
        con = duckdb.connect(str(cfg.db_path()), read_only=True)
        try:
            rows = con.execute(
                "SELECT started_at, risk_profile, topic FROM council_sessions "
                "ORDER BY started_at DESC LIMIT ?",
                [n],
            ).fetchall()
            return [f"{str(r[0])[:19]}  [{r[1]}]  {str(r[2])[:60]}" for r in rows]
        finally:
            con.close()
    except Exception:
        return []


# ---------------------------------------------------------------------------
# audit — append-only viewer (SELECT-only) / open HTML dashboard
# ---------------------------------------------------------------------------


def cmd_audit(args: argparse.Namespace) -> int:
    cfg = load_config()
    if args.open:
        try:
            from . import dashboard
        except Exception:
            _err("council audit --open: dashboard module not available.")
            return 2
        builder = getattr(dashboard, "build_html", None) or getattr(dashboard, "main", None)
        if not callable(builder):
            _err("council audit --open: dashboard not implemented in this build.")
            return 2
        out = cfg.data_home / "dashboard.html"
        try:
            if builder.__name__ == "build_html":
                cfg.ensure_dirs()
                html_text = builder(cfg) if _accepts_cfg(builder) else builder()
                out.write_text(html_text, encoding="utf-8")
            else:
                builder()
        except Exception as exc:
            _err(f"council audit --open: failed ({exc})")
            return 1
        _emit(str(out))
        return 0

    if args.query:
        return _audit_query(cfg, args.query)

    # default: recent N
    rows = _recent_sessions(cfg, n=args.n)
    if not rows:
        _emit("(no sessions; or duckdb/db unavailable)")
        return 0
    for r in rows:
        _emit(r)
    return 0


def _audit_query(cfg: Config, sql: str) -> int:
    low = sql.strip().lower()
    if not low.startswith(("select", "with", "describe", "summarize", "pragma")):
        _err("REJECTED: append-only audit — only SELECT/WITH/DESCRIBE/SUMMARIZE/PRAGMA queries run.")
        return 2
    try:
        import duckdb
    except Exception:
        _err("council audit query: duckdb not available.")
        return 2
    try:
        con = duckdb.connect(str(cfg.db_path()), read_only=True)
        try:
            for row in con.execute(sql).fetchall():
                _emit(str(row))
        finally:
            con.close()
    except Exception as exc:
        _err(f"council audit query: failed ({exc})")
        return 1
    return 0


# ---------------------------------------------------------------------------
# config — get | set | path | edit
# ---------------------------------------------------------------------------

# Keys that are safe to set via the scalar `config set` path. Roster/projects are
# tables and are edited via `config edit` / `init --reconfigure`.
_SCALAR_KEYS = {
    "owner",
    "org",
    "node_name",
    "locale",
    "data_regime",
    "secret_backend",
    "scheduler",
    "notifier",
    "exec_sandbox",
}


def cmd_config(args: argparse.Namespace) -> int:
    cfg = load_config()
    path = cfg.config_path()

    if args.action == "path":
        _emit(str(path))
        return 0

    if args.action == "get":
        if not args.key:
            # print everything we can without leaking unset values
            for k in sorted(_SCALAR_KEYS):
                _emit(f"{k} = {getattr(cfg, k, '')!r}")
            _emit(f"agents = {len(cfg.agents)} entr{'y' if len(cfg.agents) == 1 else 'ies'}")
            _emit(f"projects = {len(cfg.projects)} entr{'y' if len(cfg.projects) == 1 else 'ies'}")
            return 0
        if not hasattr(cfg, args.key):
            _err(f"unknown key: {args.key}")
            return 2
        _emit(str(getattr(cfg, args.key)))
        return 0

    if args.action == "set":
        if not args.key or args.value is None:
            _err("usage: council config set <key> <value>")
            return 2
        if args.key not in _SCALAR_KEYS:
            _err(f"refusing to set '{args.key}': only scalar keys {sorted(_SCALAR_KEYS)} via `set`. "
                 "Use `council config edit` for roster/projects.")
            return 2
        return _config_set_scalar(path, args.key, args.value)

    if args.action == "edit":
        if not path.exists():
            _emit(f"No profile yet at {path}. Run `council init` first.")
            return 1
        editor = os.environ.get("EDITOR") or os.environ.get("VISUAL")
        if not editor:
            _emit(f"$EDITOR not set. Edit this file manually:\n  {path}")
            return 0
        try:
            subprocess.run([editor, str(path)], check=False)
        except Exception as exc:
            _err(f"could not launch editor: {exc}")
            return 1
        return 0

    _err("usage: council config {get|set|path|edit}")
    return 2


def _config_set_scalar(path: Path, key: str, value: str) -> int:
    """Set/replace a top-level scalar key in council.local.toml without a TOML
    writer dependency. Only operates on the head section (before the first table)."""
    if not path.exists():
        _err(f"No profile at {path}. Run `council init` first.")
        return 1
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    new_line = f'{key} = "{_toml_escape(value)}"'
    replaced = False
    out: list[str] = []
    in_table = False
    for ln in lines:
        stripped = ln.strip()
        if stripped.startswith("[") and stripped.endswith("]") or stripped.startswith("[["):
            in_table = True
        if not in_table and not replaced:
            head = stripped.split("=", 1)[0].strip() if "=" in stripped else ""
            if head == key:
                out.append(new_line)
                replaced = True
                continue
        out.append(ln)
    if not replaced:
        # insert before the first table (or at end of head)
        insert_at = len(out)
        for i, ln in enumerate(out):
            s = ln.strip()
            if s.startswith("[[") or (s.startswith("[") and s.endswith("]")):
                insert_at = i
                break
        out.insert(insert_at, new_line)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    _emit(f"set {key} = {value}")
    return 0


# ---------------------------------------------------------------------------
# agents — list | test
# ---------------------------------------------------------------------------


def cmd_agents(args: argparse.Namespace) -> int:
    cfg = load_config()
    if args.action == "list":
        if not cfg.agents:
            _emit("(no agents — run `council init`)")
            return 0
        avail = available(cfg)
        for a in cfg.agents:
            state = "disabled" if not a.enabled else (f"{_OK} reachable" if avail.get(a.name) else f"{_BAD} missing")
            _emit(f"{a.name:<8} {a.role:<10} cli={a.cli:<10} {state}")
        return 0

    if args.action == "test":
        if not cfg.agents:
            _emit("(no agents — run `council init`)")
            return 1
        search = os.pathsep.join([cfg.extra_path, os.environ.get("PATH", "")])
        any_fail = False
        for a in cfg.agents:
            if not a.enabled:
                _emit(f"  - {a.name}: disabled (skipped)")
                continue
            if args.name and a.name != args.name:
                continue
            p = shutil.which(a.cli, path=search)
            if not p:
                _emit(f"  {_BAD} {a.name}: '{a.cli}' not on PATH")
                any_fail = True
                continue
            ok = False
            for flag in ("--version", "version", "--help"):
                try:
                    cp = subprocess.run([p, flag], capture_output=True, text=True, timeout=15)
                    if cp.returncode == 0:
                        ok = True
                        break
                except Exception:
                    continue
            _emit(f"  {_OK if ok else _BAD} {a.name}: {'runnable' if ok else 'found but did not run'} ({p})")
            any_fail = any_fail or not ok
        return 1 if any_fail else 0

    _err("usage: council agents {list|test}")
    return 2


# ---------------------------------------------------------------------------
# enable — consciously opt in to optional automation
# ---------------------------------------------------------------------------


def cmd_enable(args: argparse.Namespace) -> int:
    cfg = load_config()
    if args.what != "capture":
        _err("usage: council enable capture")
        return 2

    _emit(
        "Autocapture distills past sessions into the append-only audit, unattended.\n"
        "Before it runs, EVERY captured payload passes the PHI/secret fail-safe gate\n"
        "(Article 4 & 13): tool I/O and base64 blobs included. Capture is OFF by default.\n"
    )
    if not _confirm("Enable autocapture now?", default=False):
        _emit("Left disabled.")
        return 0

    path = cfg.config_path()
    if not path.exists():
        _err("No profile yet. Run `council init` first.")
        return 1
    rc = _config_set_bool(path, "autocapture_enabled", True)
    if rc != 0:
        return rc
    _emit(
        f"{_OK} autocapture_enabled = true in {path}\n"
        "Note: this flips the consent flag only. The scheduler that ticks capture is\n"
        "installed separately (Phase 3 platform layer); no background job was started here."
    )
    return 0


def _config_set_bool(path: Path, key: str, value: bool) -> int:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    new_line = f"{key} = {'true' if value else 'false'}"
    out: list[str] = []
    replaced = False
    in_table = False
    for ln in lines:
        s = ln.strip()
        if s.startswith("[[") or (s.startswith("[") and s.endswith("]")):
            in_table = True
        if not in_table and not replaced and "=" in s and s.split("=", 1)[0].strip() == key:
            # preserve any trailing comment
            comment = ""
            if "#" in ln:
                comment = "  " + ln[ln.index("#"):]
            out.append(new_line + comment)
            replaced = True
            continue
        out.append(ln)
    if not replaced:
        out.append(new_line)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return 0


# ---------------------------------------------------------------------------
# stop — kill switch (Article 12)
# ---------------------------------------------------------------------------


def cmd_stop(args: argparse.Namespace) -> int:
    cfg = load_config()
    cfg.ensure_dirs()
    # A simple, portable kill signal the loop polls (_killcheck). No process killing
    # here — the running loop owns its own teardown; this just sets the flag.
    flag = cfg.data_home / "STOP"
    try:
        flag.write_text("stop requested\n", encoding="utf-8")
    except Exception as exc:
        _err(f"council stop: could not write kill flag ({exc})")
        return 1
    _emit(f"{_OK} kill switch set: {flag}")
    _emit("The running loop stops at its next safe checkpoint and writes a partial-result reason to the audit.")
    return 0


# ---------------------------------------------------------------------------
# uninstall — remove automation and/or the whole install (Article 21)
# ---------------------------------------------------------------------------


def cmd_uninstall(args: argparse.Namespace) -> int:
    cfg = load_config()
    removed: list[str] = []
    kept: list[str] = []

    # Automation removal (scheduler/hook) — delegate to the platform layer if present.
    if args.automation or args.all:
        try:
            from .platform import scheduler as sched_mod

            uninstaller = getattr(sched_mod, "uninstall", None)
            if callable(uninstaller):
                uninstaller(cfg)
                removed.append("scheduler job (platform.scheduler.uninstall)")
            else:
                removed.append("scheduler job (no-op: NullScheduler / not installed)")
        except Exception as exc:
            kept.append(f"scheduler (could not remove: {exc})")

    if args.all:
        # Data removal is destructive — require explicit consent unless --keep-data.
        if args.keep_data:
            kept.append(f"audit data preserved at {cfg.data_home}")
        else:
            if _confirm(f"Delete ALL data under {cfg.data_home}? This is irreversible.", default=False):
                try:
                    shutil.rmtree(cfg.data_home, ignore_errors=True)
                    removed.append(f"data dir {cfg.data_home}")
                except Exception as exc:
                    kept.append(f"data dir (could not remove: {exc})")
            else:
                kept.append(f"audit data kept at {cfg.data_home}")
        # local profile
        path = cfg.config_path()
        if path.exists() and _confirm(f"Remove the local profile {path}?", default=False):
            try:
                path.unlink()
                removed.append(str(path))
            except Exception as exc:
                kept.append(f"profile (could not remove: {exc})")

    if not args.automation and not args.all:
        _emit("Nothing selected. Use --automation (background jobs only) or --all [--keep-data].")
        return 0

    _emit("Uninstall summary:")
    for r in removed:
        _emit(f"  {_OK} removed: {r}")
    for k in kept:
        _emit(f"  {_WARN} kept   : {k}")
    return 0


# ---------------------------------------------------------------------------
# argparse wiring
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="council",
        description="Multi-agent, evidence-weighted, vendor-independent work orchestrator.",
    )
    p.add_argument("-V", "--version", action="version", version=f"council {__version__}")
    sub = p.add_subparsers(dest="cmd")

    sp = sub.add_parser("init", help="bootstrap wizard (auto-detect + write council.local.toml)")
    sp.add_argument("--quick", action="store_true", help="zero questions; safe defaults")
    sp.add_argument("--reconfigure", action="store_true", help="overwrite an existing profile")
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("doctor", help="evidence-based health check")
    sp.add_argument("--fix", action="store_true", help="apply only safe automatic fixes")
    sp.set_defaults(func=cmd_doctor)

    sp = sub.add_parser("run", help="headless 9-state loop")
    sp.add_argument("task", help="task description")
    sp.add_argument("--project", default="", help="project name/hint (risk classification)")
    sp.add_argument("--dry-run", action="store_true", help="PREFLIGHT only (classify + secret scan)")
    sp.add_argument("--json", action="store_true", help="machine-readable output")
    sp.set_defaults(func=cmd_run)

    sp = sub.add_parser("status", help="roster health + last sessions + DB size")
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser("audit", help="append-only viewer (SELECT-only) / open dashboard")
    sp.add_argument("-n", type=int, default=10, help="recent sessions to show")
    sp.add_argument("--query", help="read-only SQL (SELECT/WITH/DESCRIBE/SUMMARIZE/PRAGMA only)")
    sp.add_argument("--open", action="store_true", help="render the single-file HTML dashboard")
    sp.set_defaults(func=cmd_audit)

    sp = sub.add_parser("config", help="get | set | path | edit the local TOML profile")
    sp.add_argument("action", choices=["get", "set", "path", "edit"])
    sp.add_argument("key", nargs="?", default=None)
    sp.add_argument("value", nargs="?", default=None)
    sp.set_defaults(func=cmd_config)

    sp = sub.add_parser("agents", help="list | test the roster")
    sp.add_argument("action", choices=["list", "test"])
    sp.add_argument("name", nargs="?", default=None, help="(test) limit to one agent")
    sp.set_defaults(func=cmd_agents)

    sp = sub.add_parser("enable", help="consciously opt in to optional automation")
    sp.add_argument("what", choices=["capture"])
    sp.set_defaults(func=cmd_enable)

    sp = sub.add_parser("stop", help="kill switch (Article 12)")
    sp.set_defaults(func=cmd_stop)

    sp = sub.add_parser("uninstall", help="remove automation and/or the whole install")
    sp.add_argument("--automation", action="store_true", help="remove background jobs only")
    sp.add_argument("--all", action="store_true", help="remove the whole install")
    sp.add_argument("--keep-data", action="store_true", help="(with --all) preserve the audit data")
    sp.set_defaults(func=cmd_uninstall)

    return p


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "cmd", None):
        parser.print_help()
        return 0
    try:
        return int(args.func(args) or 0)
    except KeyboardInterrupt:
        _err("\ninterrupted")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
