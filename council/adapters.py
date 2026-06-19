"""Vendor-neutral AgentAdapter layer (Constitution Article 2.3).

Each node hands a single CLI a prompt and gets back text + an exit code. Swapping a
provider means changing one roster line in ``council.local.toml`` — not the
orchestration logic, and not (usually) the code here.

Design:
  * ``AgentAdapter`` — abstract base; one ``run(prompt, timeout) -> AgentResult``.
  * ``GenericCLIAdapter`` — the only adapter most providers ever need. It builds an
    argv from a small, declarative profile (``argv_template`` with ``{cli}`` and
    ``{prompt}`` placeholders, plus an optional ``prompt_prefix`` and a
    ``timeout_arg`` for CLIs that take a self-imposed deadline). A new provider is a
    ``[[agents]]`` line whose ``cli`` resolves on PATH — no new Python class.
  * ``BUILTIN_PROFILES`` — argv shapes for the CLIs shipped out of the box
    (Claude, Codex, Gemini/agy). Unknown logical names fall back to the plain
    ``{cli} -p {prompt}`` shape, which is the common single-prompt convention.
  * ``build_registry(cfg)`` — turns the enabled roster into ``{name: adapter}``.
  * ``available(cfg)`` — re-exported from ``council.config`` so the roster-execution
    surface and the doctor/health surface agree on PATH resolution.

PATH is augmented at *call time* with ``cfg.extra_path`` (mac-arm ``/opt/homebrew/bin``
kept on purpose) so an installed CLI is never silently missed. The current process
environment is inherited so recursion-guard env vars (e.g. a no-autocapture flag)
propagate to the child. No SDK / HTTP-key dependency: CLI subprocess only.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import time
from dataclasses import dataclass

from .config import Config, available as _config_available

# Re-export so callers can do ``from .adapters import available`` and get the exact
# same PATH-resolution logic the config/doctor layer uses (single source of truth).
available = _config_available


def _env(cfg: Config, agent_name: str | None = None, temp_home: str | None = None) -> dict[str, str]:
    """Build the child-process environment at call time (NOT an import-time snapshot).

    The live ``os.environ`` is inherited so guard/flag env vars reach the subprocess,
    and PATH is prepended with ``cfg.extra_path`` so a Homebrew/`~/.local/bin` CLI is
    found rather than silently reported missing (critique §2)."""
    env = {**os.environ, "PATH": os.pathsep.join([cfg.extra_path, os.environ.get("PATH", "")])}
    if not cfg.unsafe_inherit_provider_config and temp_home:
        if agent_name == "google":
            env["HOME"] = temp_home
        elif agent_name == "codex":
            env["CODEX_HOME"] = temp_home
    return env


@dataclass
class AgentResult:
    agent: str
    text: str
    exit_code: int
    seconds: float
    ok: bool
    evidence_hash: str


def _run(agent: str, cmd: list[str], timeout: int, env: dict[str, str]) -> AgentResult:
    """Run one CLI invocation; return text + exit code, never raise.

    ``ok`` requires exit 0 *and* non-empty stdout (a clean exit with no output is not
    evidence). Timeout and missing-CLI degrade gracefully so a single absent provider
    cannot crash the council (Md.2.7 graceful degradation)."""
    t0 = time.time()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
        out = (p.stdout or "").strip()
        err = (p.stderr or "").strip()
        text = out if out else err
        ok = p.returncode == 0 and bool(out)
        code = p.returncode
    except subprocess.TimeoutExpired:
        text, ok, code = f"[TIMEOUT {timeout}s]", False, 124
    except FileNotFoundError:
        text, ok, code = f"[CLI not found: {cmd[0]}]", False, 127
    secs = round(time.time() - t0, 1)
    h = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return AgentResult(agent, text, code, secs, ok, h)


@dataclass(frozen=True)
class CLIProfile:
    """Declarative argv shape for one CLI family.

    ``argv_template`` tokens: each token is rendered with ``str.format`` against
    ``cli``, ``prompt`` and ``timeout`` (and any ``timeout`` value). A literal token
    with no placeholder is passed through unchanged.

    ``prompt_prefix`` is prepended to the prompt (e.g. to force plain-text, no-tool
    reasoning for determinism). ``timeout_arg`` is the integer seconds subtracted
    from the wall-clock timeout for CLIs that take their own deadline flag (so the
    CLI exits a touch before the subprocess hard-kill); 0 disables it.

    ``default_timeout`` is the per-provider default when the caller does not pass one.
    """
    argv_template: tuple[str, ...] = ("{cli}", "-p", "{prompt}")
    prompt_prefix: str = ""
    timeout_slack: int = 0          # seconds shaved off for a CLI-self-deadline arg
    default_timeout: int = 180


# Built-in argv shapes. A logical roster name not listed here uses _DEFAULT_PROFILE,
# i.e. the plain ``<cli> -p <prompt>`` single-prompt convention. Adding a provider
# with a different shape is still just a config line + (optionally) one entry here.
_PLAIN_TEXT_PREFIX = "Answer directly in plain text. Do not use any tools.\n\n"

_DEFAULT_PROFILE = CLIProfile()

BUILTIN_PROFILES: dict[str, CLIProfile] = {
    # Claude: plain-text reasoning, tools off → headless determinism.
    "claude": CLIProfile(
        argv_template=("{cli}", "-p", "{prompt}"),
        prompt_prefix=_PLAIN_TEXT_PREFIX,
        default_timeout=180,
    ),
    # Codex: exec subcommand; skip git-repo check so it runs anywhere.
    # approval_policy=never + sandbox_mode=read-only make the call truly headless:
    # without them codex blocks on an interactive approval prompt that never arrives
    # in a piped subprocess, hanging until the hard timeout (proven failure mode).
    # read-only is correct for reasoning nodes (PLAN/CRITIQUE/VERIFY produce text only;
    # real file/command execution is the separate opt-in execute path).
    "codex": CLIProfile(
        argv_template=("{cli}", "exec", "--skip-git-repo-check",
                       "-c", "approval_policy=never", "-c", "sandbox_mode=read-only",
                       "{prompt}"),
        default_timeout=240,
    ),
    # Gemini / Antigravity (agy): self-imposed print deadline a bit under the hard kill.
    "google": CLIProfile(
        argv_template=("{cli}", "--print-timeout", "{deadline}s", "-p", "{prompt}"),
        timeout_slack=10,
        default_timeout=240,
    ),
}


class AgentAdapter:
    """Abstract base: a node that turns a prompt into an :class:`AgentResult`."""
    name: str = "base"

    def run(self, prompt: str, timeout: int | None = None) -> AgentResult:  # pragma: no cover
        raise NotImplementedError


class GenericCLIAdapter(AgentAdapter):
    """Config-driven adapter — the only adapter most providers need.

    Bound to a logical ``name``, an executable ``cli`` (resolved on PATH via
    ``cfg.extra_path``), and a :class:`CLIProfile` argv shape. Reads ``cfg`` so PATH
    augmentation and any future per-config knobs stay in one place."""

    def __init__(self, name: str, cli: str, cfg: Config, profile: CLIProfile | None = None):
        self.name = name
        self.cli = cli
        self.cfg = cfg
        self.profile = profile or BUILTIN_PROFILES.get(name, _DEFAULT_PROFILE)

    def _argv(self, prompt: str, timeout: int, temp_home: str | None = None) -> list[str]:
        prof = self.profile
        text = (prof.prompt_prefix + prompt) if prof.prompt_prefix else prompt
        deadline = max(1, timeout - prof.timeout_slack)
        argv: list[str] = []
        for tok in prof.argv_template:
            argv.append(tok.format(cli=self.cli, prompt=text, timeout=timeout, deadline=deadline))

        # Enforce node isolation (PR2) if not opted out
        if not self.cfg.unsafe_inherit_provider_config:
            if self.name == "claude":
                if len(argv) > 1 and argv[0] == self.cli:
                    # --setting-sources takes a comma-separated list (user|project|local);
                    # the EMPTY string loads none → isolation. ``none`` is NOT a valid value
                    # and makes the claude CLI error out (it rejects the argument and the
                    # provider call fails) — found by a live run, the gate-test≠real-test catch.
                    argv = [argv[0], "--strict-mcp-config", "--setting-sources", ""] + argv[1:]
            elif self.name == "codex":
                if len(argv) > 1 and argv[0] == self.cli:
                    try:
                        exec_idx = argv.index("exec")
                        prefix_args = ["-c", "project_doc_max_bytes=0"]
                        if temp_home:
                            prefix_args += ["-C", temp_home]
                        argv = argv[:exec_idx] + prefix_args + ["exec", "--ignore-user-config"] + argv[exec_idx+1:]
                    except ValueError:
                        prefix_args = ["-c", "project_doc_max_bytes=0"]
                        if temp_home:
                            prefix_args += ["-C", temp_home]
                        argv = [argv[0]] + prefix_args + ["--ignore-user-config"] + argv[1:]
        return argv

    def run(self, prompt: str, timeout: int | None = None) -> AgentResult:
        t = timeout if timeout is not None else self.profile.default_timeout
        temp_home = None
        if not self.cfg.unsafe_inherit_provider_config:
            import tempfile
            temp_home = tempfile.mkdtemp(prefix=f"council-isolated-{self.name}-")

        try:
            env = _env(self.cfg, self.name, temp_home)
            argv = self._argv(prompt, t, temp_home)
            return _run(self.name, argv, t, env)
        finally:
            if temp_home:
                import shutil
                shutil.rmtree(temp_home, ignore_errors=True)


def build_registry(cfg: Config) -> dict[str, GenericCLIAdapter]:
    """Map each *enabled* roster agent to a :class:`GenericCLIAdapter`.

    The orchestrator selects from this dict by logical name (via ``cfg.by_role`` /
    ``cfg.verifier``); a CLI that is absent on PATH still yields an adapter whose
    ``run`` degrades to ``ok=False`` (exit 127) rather than vanishing — so the graph
    sees an explicit non-result instead of a missing key."""
    registry: dict[str, GenericCLIAdapter] = {}
    for a in cfg.agents:
        if not a.enabled:
            continue
        registry[a.name] = GenericCLIAdapter(name=a.name, cli=a.cli, cfg=cfg)
    return registry


def adapter_for(cfg: Config, name: str) -> GenericCLIAdapter:
    """Return the adapter for one logical roster name (used by graph/capture).

    Looks the name up in the *enabled* roster; an unknown/disabled name still yields a
    GenericCLIAdapter bound to ``name`` as the CLI, so a missing provider degrades to a
    graceful tool failure (exit 127) instead of a KeyError (Md.2.7 graceful degrade)."""
    for a in cfg.agents:
        if a.name == name and a.enabled:
            return GenericCLIAdapter(name=a.name, cli=a.cli, cfg=cfg)
    return GenericCLIAdapter(name=name, cli=name, cfg=cfg)
