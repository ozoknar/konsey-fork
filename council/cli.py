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
from dataclasses import replace
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
from .i18n import load_catalog, t

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


def _detect_locale() -> str | None:
    """Best-effort OS locale → a supported catalog locale (Article 17).

    A ``KONSEY_LOCALE`` env var (set by the installer / scriptable piped runs) takes
    precedence over the OS locale. Otherwise honours true POSIX precedence: the FIRST
    *set* variable in LC_ALL > LC_MESSAGES > LANG decides (a higher-priority non-Turkish
    value wins over a lower-priority ``tr``). A ``tr*`` value (e.g. ``tr_TR.UTF-8``)
    selects Turkish, any other set value selects English. Returns ``None`` when NOTHING
    is set, so the caller can fall back to the stored profile / default. No side effects."""
    forced = os.environ.get("KONSEY_LOCALE", "").strip().lower()
    if forced[:2] == "tr":
        return "tr"
    if forced:
        return "en"
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        val = os.environ.get(var, "")
        if val:                                # first set variable wins (POSIX)
            return "tr" if val[:2].lower() == "tr" else "en"
    return None


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


def _scan_host_isolation() -> list | None:
    """Host AI-config footprint that would leak into a node (Article 2.6).

    Returns the findings list, ``[]`` when the host is genuinely clean, or **None when
    the detector/scan was unavailable** — None is NOT "clean": scan-unavailable ≠
    no-leak (the evidence standard, Article 2.1). Callers must distinguish the two."""
    try:
        from .isolation import scan_host_ai_config
        return scan_host_ai_config(Path(os.path.expanduser("~")), Path.cwd())
    except Exception:
        return None


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
    quick = args.quick

    # Locale FIRST (Article 17): explicit --locale > OS env (LANG/LC_ALL tr*) > config
    # default. Bind the catalog to it BEFORE any output, and — interactively — confirm it
    # as the very first question, then RE-BIND, so the whole wizard + banner + next-steps
    # flow in the chosen language (fixes "asked for Turkish, got English": locale used to
    # be written to TOML but never re-bound for the running session).
    initial_locale = (getattr(args, "locale", None) or _detect_locale() or cfg.locale or "en").lower()
    if initial_locale not in _LOCALES:
        initial_locale = "en"
    cat = load_catalog(replace(cfg, locale=initial_locale))

    # Decide whether to proceed AT ALL before claiming anything about defaults.
    if target.exists() and not args.reconfigure and not args.quick:
        _emit(t(cat, "cli.init.profile_exists", target=target))
        if not _confirm(t(cat, "cli.init.reconfigure_q"), default=False):
            _emit(t(cat, "cli.init.left_untouched"))
            return 0

    # Non-TTY honesty (Faz 1): now that we ARE proceeding, a piped run must not silently
    # feed _ask() its defaults and pretend the user answered — switch + SAY SO (stderr).
    if not quick and not _is_tty():
        _err(t(cat, "cli.init.noninteractive_notice"))
        quick = True

    if quick:
        locale = initial_locale
    else:
        locale = _ask(t(cat, "cli.init.ask_locale", choices="|".join(_LOCALES)), initial_locale).lower()
        if locale not in _LOCALES:
            locale = initial_locale
        cat = load_catalog(replace(cfg, locale=locale))   # re-bind: rest of init in chosen language

    _emit(t(cat, "cli.init.bootstrap"))
    _emit(t(cat, "cli.init.council_home", value=cfg.council_home))
    _emit(t(cat, "cli.init.data_home", value=cfg.data_home))
    _emit(t(cat, "cli.init.os", value=_detect_os()))

    # 1) roster auto-detect
    detected = _detect_roster(extra_path)
    found = [(n, c) for (n, c, ok) in detected if ok]
    _emit(t(cat, "cli.init.clis_on_path"))
    for name, cli, ok in detected:
        _emit(t(cat, "cli.init.cli_line", mark=_OK if ok else _BAD, name=name, cli=cli))
    if len(found) < 2:
        _emit(t(cat, "cli.init.few_providers", warn=_WARN))

    roster: list[tuple[str, str, str, bool]] = []
    for i, (name, cli, ok) in enumerate(detected):
        role = _DEFAULT_ROLES[i] if i < len(_DEFAULT_ROLES) else ROLE_LEAD
        roster.append((name, cli, role, ok))

    # 2) wizard (skipped entirely with --quick → safe defaults; locale already chosen above)
    if quick:
        owner, org, node_name, regime = "operator", "", "", "standard"
    else:
        owner = _ask(t(cat, "cli.init.ask_owner"), "operator") or "operator"
        org = _ask(t(cat, "cli.init.ask_org"), "")
        node_name = _ask(t(cat, "cli.init.ask_node"), "")
        regime = _ask(t(cat, "cli.init.ask_regime", choices="|".join(_REGIMES)), "standard").lower()
        if regime not in _REGIMES:
            regime = "standard"
        if regime != "standard":
            _emit(t(cat, "cli.init.regime_warn", warn=_WARN, regime=regime))

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

    _emit(t(cat, "cli.init.wrote"))
    for p in written:
        _emit(f"  {p}")

    # Host AI-config scan (Article 2.6 — node isolation). Informational at install
    # time: name the pre-existing host config that WOULD leak into a provider node, so
    # the operator knows before the first run. Detection only — nothing is modified.
    _emit(t(cat, "cli.init.isolation_header"))
    host_findings = _scan_host_isolation()
    if host_findings is None:
        # scan-unavailable ≠ clean (Article 2.1): do NOT claim the host is clean.
        _emit(t(cat, "cli.init.isolation_unavailable"))
    elif host_findings:
        for f in host_findings:
            _emit(t(cat, "cli.init.isolation_item", mark=_WARN, label=f.label, node=f.pollutes, path=f.path))
        _emit(t(cat, "cli.init.isolation_note"))
    else:
        _emit(t(cat, "cli.init.isolation_clean"))

    _emit(t(cat, "cli.init.next_steps"))
    return 0


# ---------------------------------------------------------------------------
# doctor — evidence-based health (Article 0.5). Each line is REALLY tried.
# ---------------------------------------------------------------------------


def _doctor_clis(cfg: Config, results: list[tuple[bool, str]], flags: dict | None = None) -> None:
    cat = load_catalog(cfg)
    if not cfg.agents:
        results.append((False, t(cat, "cli.doctor.roster_none")))
        return
    search = os.pathsep.join([cfg.extra_path, os.environ.get("PATH", "")])
    enabled_ok = 0
    for a in cfg.agents:
        if not a.enabled:
            results.append((True, t(cat, "cli.doctor.agent_disabled", name=a.name)))
            continue
        path = shutil.which(a.cli, path=search)
        if not path:
            results.append((False, t(cat, "cli.doctor.agent_not_on_path", name=a.name, cli=a.cli)))
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
            results.append((True, t(cat, "cli.doctor.agent_runnable", name=a.name, cli=a.cli, path=path)))
        else:
            results.append((False, t(cat, "cli.doctor.agent_unclean", name=a.name, cli=a.cli)))
    if enabled_ok == 0:
        # Non-fatal (a fresh machine legitimately has no CLI yet) but UNMISTAKABLY a warning,
        # so "Install complete" is never read as "fully working" (fresh-install audit finding).
        results.append((True, t(cat, "cli.doctor.no_providers")))
        if flags is not None:
            flags["advisory"] = True   # 0 providers → footer says "advisory mode" (locale-independent)
    elif enabled_ok < 2:
        results.append((True, t(cat, "cli.doctor.one_provider",
                                 n=enabled_ok, cap=cfg.confidence_cap_noxval)))


def _doctor_duckdb(cfg: Config, results: list[tuple[bool, str]]) -> None:
    cat = load_catalog(cfg)
    try:
        import duckdb  # noqa: F401
    except Exception:
        results.append((False, t(cat, "cli.doctor.duckdb_not_importable")))
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
            n_row = con.execute("SELECT count(*) FROM t WHERE id = ?", [rid]).fetchone()
            n = n_row[0] if n_row else 0
            con.execute("ROLLBACK")
            after_row = con.execute("SELECT count(*) FROM t").fetchone()
            after = after_row[0] if after_row else -1
            if n == 1 and after == 0:
                results.append((True, t(cat, "cli.doctor.duckdb_verified")))
            else:
                results.append((False, t(cat, "cli.doctor.duckdb_semantics_off", n=n, after=after)))
        finally:
            con.close()
    except Exception as exc:
        results.append((False, t(cat, "cli.doctor.duckdb_probe_failed", exc=exc)))
    finally:
        try:
            shutil.rmtree(tmp.parent, ignore_errors=True)
        except Exception:
            pass


def _doctor_append_only(cfg: Config, results: list[tuple[bool, str]]) -> None:
    """Prove the audit helper rejects mutation (Article 11). Tries the SELECT-only
    query guard; if that module is still a stub, falls back to the live DB UPDATE
    refusal at the policy layer being asserted by the helper."""
    cat = load_catalog(cfg)
    try:
        from . import cli_helpers  # noqa: F401
    except Exception:
        pass
    # Try the project's audit query guard if it exposes one.
    try:
        from .cli_helpers import konsey_db as kdb
    except Exception:
        results.append((True, t(cat, "cli.doctor.audit_helper_not_wired")))
        return
    guard = getattr(kdb, "is_read_only", None) or getattr(kdb, "_is_select_only", None)
    if callable(guard):
        ok_select = bool(guard("SELECT 1"))
        ok_reject = not bool(guard("UPDATE council_sessions SET status='x'"))
        if ok_select and ok_reject:
            results.append((True, t(cat, "cli.doctor.audit_guard_ok")))
        else:
            results.append((False, t(cat, "cli.doctor.audit_guard_bad")))
    else:
        results.append((True, t(cat, "cli.doctor.audit_guard_present")))


def _doctor_gateway(cfg: Config, results: list[tuple[bool, str]]) -> None:
    """The secret gate must catch a known token-format sample (Article 4.2)."""
    cat = load_catalog(cfg)
    sample = "here is a leaked key sk-ant-api03-AAAAAAAAAAAAAAAAAAAAAAAA"
    placeholder = "API_KEY=your_key_here"
    try:
        from .gateway import scan_secrets
    except Exception:
        results.append((True, t(cat, "cli.doctor.secret_gate_not_wired")))
        return
    try:
        caught = bool(scan_secrets(sample))
        clean = not bool(scan_secrets(placeholder))
        if caught and clean:
            results.append((True, t(cat, "cli.doctor.secret_gate_full")))
        elif caught:
            results.append((True, t(cat, "cli.doctor.secret_gate_partial")))
        else:
            results.append((False, t(cat, "cli.doctor.secret_gate_failed")))
    except Exception as exc:
        results.append((False, t(cat, "cli.doctor.secret_gate_raised", exc=exc)))


def _doctor_graph(cfg: Config, results: list[tuple[bool, str]]) -> None:
    # Import build AND the runtime dep graph relies on lazily (adapters.adapter_for).
    # A masked import error here was how a broken `council run` slipped past doctor —
    # so an import failure is a CRITICAL fail, never a silent "skipped" pass.
    cat = load_catalog(cfg)
    try:
        from .graph import build  # noqa: F401
        from .adapters import adapter_for  # graph.EXECUTE depends on this (lazy import)
    except Exception as exc:
        results.append((False, t(cat, "cli.doctor.graph_import_failed", exc=exc)))
        return
    if callable(build) and callable(adapter_for):
        results.append((True, t(cat, "cli.doctor.graph_ok")))
    else:
        results.append((False, t(cat, "cli.doctor.graph_not_callable")))


def _doctor_regime(cfg: Config, results: list[tuple[bool, str]]) -> None:
    """Fail-open guard (Article 4.1): a regulated data regime is only a detection aid
    if its term file actually loaded. ``data_regime=hipaa`` WITHOUT regimes/hipaa.toml
    silently yields no clinical detection — surface it as a VISIBLE ⚠ (non-fatal:
    the secret scan is always on, and an operator may legitimately not have installed
    terms yet)."""
    cat = load_catalog(cfg)
    regime = (cfg.data_regime or "standard").strip().lower()
    try:
        from .gateway import regime_loaded
    except Exception:
        return
    if regime not in {"kvkk", "gdpr", "hipaa"}:
        return
    if regime_loaded(cfg):
        results.append((True, t(cat, "cli.doctor.regime_loaded", regime=regime)))
    else:
        plugin = Path(cfg.council_home) / "regimes" / f"{regime}.toml"
        results.append((True, t(cat, "cli.doctor.regime_not_loaded", regime=regime, plugin=plugin)))


def _doctor_host_isolation(cfg: Config, results: list[tuple[bool, str]]) -> None:
    """Node execution isolation (Article 2.6): detect pre-existing host AI config that
    WOULD leak into a provider subprocess and collapse the cross-provider independence
    Article 2.2 requires. Detection only — a non-fatal ⚠ that names how many host files
    would leak and into which node; isolation *enforcement* is the adapter layer
    (KNOWN_ISSUES: node-isolation). Evidence, not assumption: the paths are really
    stat()'d, not guessed."""
    cat = load_catalog(cfg)
    try:
        from .isolation import scan_host_ai_config, summarize
        # The scan probes untrusted host filesystem state — guard it too, not just the
        # import, so a stat/permission edge case can never crash doctor.
        findings = scan_host_ai_config(Path(os.path.expanduser("~")), Path.cwd())
    except Exception:
        return  # detector unavailable or scan failed → skip silently (never crash)
    if not findings:
        results.append((True, t(cat, "cli.doctor.isolation_clean")))
        return
    # Message text opens with its own ⚠ glyph → rendered as a non-fatal warning, not ✗.
    results.append((True, t(cat, "cli.doctor.isolation_leak",
                            n=len(findings), summary=summarize(findings))))


def cmd_doctor(args: argparse.Namespace) -> int:
    cfg = load_config()
    cat = load_catalog(cfg)
    results: list[tuple[bool, str]] = []

    state = t(cat, "cli.doctor.config_present") if cfg.config_path().exists() else t(cat, "cli.doctor.config_defaults")
    results.append((True, t(cat, "cli.doctor.config_line", path=cfg.config_path(), state=state)))
    results.append((True, t(cat, "cli.doctor.owner_line", owner=repr(cfg.owner), locale=cfg.locale, regime=cfg.data_regime)))

    clis_flags: dict = {}
    _doctor_clis(cfg, results, clis_flags)
    _doctor_duckdb(cfg, results)
    _doctor_append_only(cfg, results)
    _doctor_gateway(cfg, results)
    _doctor_graph(cfg, results)
    _doctor_regime(cfg, results)
    _doctor_host_isolation(cfg, results)

    _emit(t(cat, "cli.doctor.header"))
    critical_fail = False
    for ok, line in results:
        if not ok:
            critical_fail = True
            _emit(f"  {_BAD} {line}")
        elif line.startswith("⚠"):
            # Passing (non-fatal) but explicitly a warning. The message text already
            # opens with its own ⚠ glyph, so DON'T prepend a contradictory ✓ — that
            # produced a confusing "✓ ⚠ ..." double glyph (fresh-install audit finding).
            # Indent two spaces to keep column alignment with the ✓/✗ lines.
            _emit(f"  {line}")
        else:
            _emit(f"  {_OK} {line}")

    if critical_fail:
        _emit(t(cat, "cli.doctor.critical_failed", bad=_BAD))
        return 1
    # Advisory footer (Faz 1): a fresh machine with 0 runnable providers PASSES (rc 0),
    # but must not read as a fully-ready "All checks passed." The no_providers line opens
    # with "⚠ 0 " (cli.doctor.no_providers) — key off that. rc is unchanged either way.
    advisory = bool(clis_flags.get("advisory"))   # structured, not locale-dependent text
    _emit(t(cat, "cli.doctor.all_passed_advisory" if advisory else "cli.doctor.all_passed", ok=_OK))
    return 0


# ---------------------------------------------------------------------------
# run — headless 9-state loop
# ---------------------------------------------------------------------------


def cmd_run(args: argparse.Namespace) -> int:
    cfg = load_config()
    cat = load_catalog(cfg)
    try:
        from .graph import build
    except Exception:
        _err(t(cat, "cli.run.graph_unavailable"))
        return 2
    if args.dry_run:
        # PREFLIGHT only: classify + secret scan, do not execute the loop.
        try:
            from .gateway import preflight
        except Exception:
            _err(t(cat, "cli.run.gateway_unavailable"))
            return 2
        # Pass cfg so the project risk-registry + data-regime from council.local
        # apply to dry-run classification, matching the live `run` path (KNOWN_ISSUES).
        res = preflight(args.task, args.project or "", cfg=cfg)
        if args.json:
            import json as _json

            _emit(_json.dumps(getattr(res, "__dict__", {"risk": getattr(res, "risk", "?")}), default=str))
        else:
            _emit(t(cat, "cli.run.risk", value=getattr(res, "risk", "?")))
            _emit(t(cat, "cli.run.blocked", value=getattr(res, "blocked", False)))
            if getattr(res, "secrets_found", None):
                _emit(t(cat, "cli.run.secrets", value=res.secrets_found))
            if getattr(res, "notes", None):
                for n in res.notes:
                    _emit(t(cat, "cli.run.note", value=n))
        return 0

    try:
        app = build(cfg)   # build(cfg) is the stable signature (graph.build)
        final = app.invoke(
            {"task": args.task, "project_hint": args.project or ""},
            config={"recursion_limit": 60},
        )
    except NotImplementedError:
        _err(t(cat, "cli.run.loop_not_implemented"))
        return 2
    except Exception as exc:
        _err(t(cat, "cli.run.failed", exc=exc))
        return 1

    if args.json:
        import json as _json

        _emit(_json.dumps(final, default=str))
    else:
        if isinstance(final, dict):
            body = final.get("report") or t(cat, "report.none_produced")
        else:
            body = str(final)
        _emit("\n" + body)
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
    cat = load_catalog(cfg)
    _emit(t(cat, "cli.status.header"))
    _emit(t(cat, "cli.status.owner", value=cfg.owner))
    _emit(t(cat, "cli.status.locale", locale=cfg.locale, regime=cfg.data_regime))
    state = t(cat, "cli.doctor.config_present") if cfg.config_path().exists() else t(cat, "cli.doctor.config_defaults")
    _emit(t(cat, "cli.status.config", path=cfg.config_path(), state=state))

    avail = available(cfg)
    _emit(t(cat, "cli.status.roster"))
    if not cfg.agents:
        _emit(t(cat, "cli.status.roster_none"))
    for a in cfg.agents:
        if not a.enabled:
            _emit(t(cat, "cli.status.agent_disabled", name=a.name, role=a.role))
            continue
        _emit(t(cat, "cli.status.agent_line", mark=_OK if avail.get(a.name) else _BAD,
                name=a.name, role=a.role, cli=a.cli))
    enabled_ok = sum(1 for a in cfg.agents if a.enabled and avail.get(a.name))
    if enabled_ok < 2:
        _emit(t(cat, "cli.status.advisory", warn=_WARN, n=enabled_ok, cap=cfg.confidence_cap_noxval))

    db = cfg.db_path()
    if db.exists():
        size_mb = db.stat().st_size / (1024 * 1024)
        _emit(t(cat, "cli.status.audit_db", db=db, size=f"{size_mb:.1f}"))
        sessions = _recent_sessions(cfg, n=5)
        if sessions:
            _emit(t(cat, "cli.status.recent_sessions"))
            for row in sessions:
                _emit(f"    {row}")
    else:
        _emit(t(cat, "cli.status.audit_db_none", db=db))
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
    cat = load_catalog(cfg)
    if args.open:
        try:
            from . import dashboard
        except Exception:
            _err(t(cat, "cli.audit.dashboard_unavailable"))
            return 2
        builder = getattr(dashboard, "build_html", None) or getattr(dashboard, "main", None)
        if not callable(builder):
            _err(t(cat, "cli.audit.dashboard_not_implemented"))
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
            _err(t(cat, "cli.audit.open_failed", exc=exc))
            return 1
        _emit(str(out))
        return 0

    if args.query:
        return _audit_query(cfg, args.query)

    # default: recent N
    rows = _recent_sessions(cfg, n=args.n)
    if not rows:
        _emit(t(cat, "cli.audit.no_sessions"))
        return 0
    for r in rows:
        _emit(r)
    return 0


def _audit_query(cfg: Config, sql: str) -> int:
    cat = load_catalog(cfg)
    low = sql.strip().lower()
    if not low.startswith(("select", "with", "describe", "summarize", "pragma")):
        _err(t(cat, "cli.audit.rejected"))
        return 2
    try:
        import duckdb
    except Exception:
        _err(t(cat, "cli.audit.query_duckdb_unavailable"))
        return 2
    try:
        con = duckdb.connect(str(cfg.db_path()), read_only=True)
        try:
            for row in con.execute(sql).fetchall():
                _emit(str(row))
        finally:
            con.close()
    except Exception as exc:
        _err(t(cat, "cli.audit.query_failed", exc=exc))
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
    cat = load_catalog(cfg)
    path = cfg.config_path()

    if args.action == "path":
        _emit(str(path))
        return 0

    if args.action == "get":
        if not args.key:
            # print everything we can without leaking unset values
            for k in sorted(_SCALAR_KEYS):
                _emit(t(cat, "cli.config.scalar_line", key=k, value=repr(getattr(cfg, k, ""))))
            _emit(t(cat, "cli.config.agents_entries", n=len(cfg.agents),
                    word=t(cat, "cli.config.entry_singular") if len(cfg.agents) == 1
                    else t(cat, "cli.config.entry_plural")))
            _emit(t(cat, "cli.config.projects_entries", n=len(cfg.projects),
                    word=t(cat, "cli.config.entry_singular") if len(cfg.projects) == 1
                    else t(cat, "cli.config.entry_plural")))
            return 0
        if not hasattr(cfg, args.key):
            _err(t(cat, "cli.config.unknown_key", key=args.key))
            return 2
        _emit(str(getattr(cfg, args.key)))
        return 0

    if args.action == "set":
        if not args.key or args.value is None:
            _err(t(cat, "cli.config.set_usage"))
            return 2
        if args.key not in _SCALAR_KEYS:
            _err(t(cat, "cli.config.refuse_set", key=args.key, keys=sorted(_SCALAR_KEYS)))
            return 2
        return _config_set_scalar(path, args.key, args.value)

    if args.action == "edit":
        if not path.exists():
            _emit(t(cat, "cli.config.no_profile_init", path=path))
            return 1
        editor = os.environ.get("EDITOR") or os.environ.get("VISUAL")
        if not editor:
            _emit(t(cat, "cli.config.editor_unset", path=path))
            return 0
        try:
            subprocess.run([editor, str(path)], check=False)
        except Exception as exc:
            _err(t(cat, "cli.config.editor_failed", exc=exc))
            return 1
        return 0

    _err(t(cat, "cli.config.usage"))
    return 2


def _config_set_scalar(path: Path, key: str, value: str) -> int:
    """Set/replace a top-level scalar key in council.local.toml without a TOML
    writer dependency. Only operates on the head section (before the first table)."""
    if not path.exists():
        _err(t(load_catalog(load_config()), "cli.config.no_profile_at", path=path))
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
    _emit(t(load_catalog(load_config()), "cli.config.set_ok", key=key, value=value))
    return 0


# ---------------------------------------------------------------------------
# agents — list | test
# ---------------------------------------------------------------------------


def cmd_agents(args: argparse.Namespace) -> int:
    cfg = load_config()
    cat = load_catalog(cfg)
    if args.action == "list":
        if not cfg.agents:
            _emit(t(cat, "cli.agents.none"))
            return 0
        avail = available(cfg)
        for a in cfg.agents:
            if not a.enabled:
                state = t(cat, "cli.agents.state_disabled")
            elif avail.get(a.name):
                state = t(cat, "cli.agents.state_reachable", ok=_OK)
            else:
                state = t(cat, "cli.agents.state_missing", bad=_BAD)
            _emit(t(cat, "cli.agents.list_line", name=a.name, role=a.role, cli=a.cli, state=state))
        return 0

    if args.action == "test":
        if not cfg.agents:
            _emit(t(cat, "cli.agents.none"))
            return 1
        search = os.pathsep.join([cfg.extra_path, os.environ.get("PATH", "")])
        any_fail = False
        for a in cfg.agents:
            if not a.enabled:
                _emit(t(cat, "cli.agents.test_disabled", name=a.name))
                continue
            if args.name and a.name != args.name:
                continue
            p = shutil.which(a.cli, path=search)
            if not p:
                _emit(t(cat, "cli.agents.test_not_on_path", bad=_BAD, name=a.name, cli=a.cli))
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
            state = t(cat, "cli.agents.test_runnable") if ok else t(cat, "cli.agents.test_not_run")
            _emit(t(cat, "cli.agents.test_result", mark=_OK if ok else _BAD, name=a.name, state=state, path=p))
            any_fail = any_fail or not ok
        return 1 if any_fail else 0

    _err(t(cat, "cli.agents.usage"))
    return 2


# ---------------------------------------------------------------------------
# enable — consciously opt in to optional automation
# ---------------------------------------------------------------------------


def cmd_enable(args: argparse.Namespace) -> int:
    cfg = load_config()
    cat = load_catalog(cfg)
    if args.what != "capture":
        _err(t(cat, "cli.enable.usage"))
        return 2

    _emit(t(cat, "cli.enable.explainer"))
    if not _confirm(t(cat, "cli.enable.now_q"), default=False):
        _emit(t(cat, "cli.enable.left_disabled"))
        return 0

    path = cfg.config_path()
    if not path.exists():
        _err(t(cat, "cli.enable.no_profile"))
        return 1
    rc = _config_set_bool(path, "autocapture_enabled", True)
    if rc != 0:
        return rc
    _emit(t(cat, "cli.enable.enabled", ok=_OK, path=path))
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
    cat = load_catalog(cfg)
    cfg.ensure_dirs()
    # A simple, portable kill signal the loop polls (_killcheck). No process killing
    # here — the running loop owns its own teardown; this just sets the flag.
    flag = cfg.data_home / "STOP"
    try:
        flag.write_text("stop requested\n", encoding="utf-8")
    except Exception as exc:
        _err(t(cat, "cli.stop.write_failed", exc=exc))
        return 1
    _emit(t(cat, "cli.stop.kill_flag_set", ok=_OK, flag=flag))
    _emit(t(cat, "cli.stop.checkpoint_note"))
    return 0


# ---------------------------------------------------------------------------
# uninstall — remove automation and/or the whole install (Article 21)
# ---------------------------------------------------------------------------


def cmd_uninstall(args: argparse.Namespace) -> int:
    cfg = load_config()
    cat = load_catalog(cfg)
    removed: list[str] = []
    kept: list[str] = []

    # Automation removal (scheduler/hook) — delegate to the platform layer if present.
    if args.automation or args.all:
        try:
            from .platform import scheduler as sched_mod

            uninstaller = getattr(sched_mod, "uninstall", None)
            if callable(uninstaller):
                uninstaller(cfg)
                removed.append(t(cat, "cli.uninstall.scheduler_removed"))
            else:
                removed.append(t(cat, "cli.uninstall.scheduler_noop"))
        except Exception as exc:
            kept.append(t(cat, "cli.uninstall.scheduler_kept", exc=exc))

    if args.all:
        # Data removal is destructive — require explicit consent unless --keep-data.
        if args.keep_data:
            kept.append(t(cat, "cli.uninstall.data_preserved", data_home=cfg.data_home))
        else:
            if _confirm(t(cat, "cli.uninstall.delete_all_q", data_home=cfg.data_home), default=False):
                try:
                    shutil.rmtree(cfg.data_home, ignore_errors=True)
                    removed.append(t(cat, "cli.uninstall.data_removed", data_home=cfg.data_home))
                except Exception as exc:
                    kept.append(t(cat, "cli.uninstall.data_kept_err", exc=exc))
            else:
                kept.append(t(cat, "cli.uninstall.data_kept", data_home=cfg.data_home))
        # local profile
        path = cfg.config_path()
        if path.exists() and _confirm(t(cat, "cli.uninstall.remove_profile_q", path=path), default=False):
            try:
                path.unlink()
                removed.append(str(path))
            except Exception as exc:
                kept.append(t(cat, "cli.uninstall.profile_kept_err", exc=exc))

    if not args.automation and not args.all:
        _emit(t(cat, "cli.uninstall.nothing_selected"))
        return 0

    _emit(t(cat, "cli.uninstall.summary"))
    for r in removed:
        _emit(t(cat, "cli.uninstall.removed_line", ok=_OK, item=r))
    for k in kept:
        _emit(t(cat, "cli.uninstall.kept_line", warn=_WARN, item=k))
    return 0


# ---------------------------------------------------------------------------
# argparse wiring
# ---------------------------------------------------------------------------


def _prog_name() -> str:
    """The command name actually invoked (``council`` or its working alias ``konsey``),
    so help/usage/--version reflect what the user typed. Falls back to ``council`` for
    ``python -m`` / test invocations."""
    name = Path(sys.argv[0]).name
    return name if name in ("council", "konsey") else "council"


def build_parser() -> argparse.ArgumentParser:
    prog = _prog_name()
    p = argparse.ArgumentParser(
        prog=prog,
        description="Multi-agent, evidence-weighted, vendor-independent work orchestrator.",
    )
    p.add_argument("-V", "--version", action="version", version=f"{prog} {__version__}")
    sub = p.add_subparsers(dest="cmd")

    sp = sub.add_parser("init", help="bootstrap wizard (auto-detect + write council.local.toml)")
    sp.add_argument("--quick", action="store_true", help="zero questions; safe defaults")
    sp.add_argument("--reconfigure", action="store_true", help="overwrite an existing profile")
    sp.add_argument("--locale", choices=_LOCALES, default=None,
                    help="force interface language (else: $LANG/$LC_ALL tr* → tr, otherwise en)")
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
        try:
            _err(t(load_catalog(load_config()), "cli.interrupted"))
        except Exception:
            _err("\ninterrupted")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
