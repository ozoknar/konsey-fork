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
from pathlib import Path

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
        elif agent_name == "kimi":
            # kimi-code resolves its data/config root from $KIMI_CODE_HOME, falling back to
            # ~/.kimi-code when unset. Confirmed EMPIRICALLY: `kimi doctor` reports config
            # paths under the real ~/.kimi-code by default; `KIMI_CODE_HOME=<dir> kimi doctor`
            # reports the identical paths under <dir> instead, and a live
            # `KIMI_CODE_HOME=<dir> kimi -p "..."` call authenticated and answered correctly
            # with the real $HOME untouched — same "override one dedicated env var" shape as
            # CODEX_HOME, not google's full $HOME override.
            env["KIMI_CODE_HOME"] = temp_home
    return env


# Host-relative credential paths re-seeded into a node's isolated home. Auth is NOT a
# host-instruction leak (Art. 2.6 targets CLAUDE.md/AGENTS.md/GEMINI.md/settings/MCP),
# but a clean HOME/CODEX_HOME also strips the provider's credentials — so the node fails
# to authenticate (codex -> HTTP 401; agy/google -> "Authentication required") and
# silently drops out of the quorum (providers_ok short of the enabled roster size — 4
# once kimi is added). These are the minimal credential paths, verified empirically, that
# let a node auth WITHOUT pulling in any instruction file. For ``google`` the ``.gemini``
# dir is curated to omit exactly the three
# documented leak files, so isolation still holds.
_GEMINI_LEAK_TOP = {"GEMINI.md"}
_GEMINI_LEAK_AGCLI = {"settings.json", "mcp_config.json"}


def _seed_isolated_auth(name: str, temp_home: str) -> None:
    """Symlink the minimal provider credentials into the isolated ``temp_home``.

    Side-effect-free on the host: only symlinks INTO ``temp_home`` are created (the real
    credential files are never copied or modified), and a missing source is skipped so
    the node degrades exactly as before (Md.2.7 graceful degradation). Restores auth
    while keeping the host instruction/config surfaces suppressed (Art. 2.6)."""
    real_home = Path(os.path.expanduser("~"))
    temp = Path(temp_home)

    def _link(src: Path, dst: Path) -> None:
        try:
            if not src.exists() or dst.exists() or dst.is_symlink():
                return
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.symlink_to(src)
        except OSError:
            return

    if name == "codex":
        # CODEX_HOME == temp_home; codex reads its token from ``$CODEX_HOME/auth.json``.
        # ``--ignore-user-config`` already suppresses config.toml/AGENTS.md, so only the
        # credential file is restored.
        _link(real_home / ".codex" / "auth.json", temp / "auth.json")
    elif name == "kimi":
        # Minimal auth surface for kimi-code, mirrored 1:1 into $KIMI_CODE_HOME (== temp_home).
        # credentials/ is a DIRECTORY (~/.kimi-code/credentials/) and device_id is a FILE
        # (~/.kimi-code/device_id) — both symlinked whole, never copied, matching every other
        # _link() call in this function.
        #
        # config.toml must ALSO be linked: verified empirically that credentials+device_id
        # alone are NOT sufficient — a headless `KIMI_CODE_HOME=<isolated dir> kimi -p "..."`
        # call with only those two symlinked fails immediately with "No model configured. Run
        # `kimi` and use /login to sign in, then retry; or set default_model in config.toml."
        # kimi's config.toml is NOT purely an instructions/leak surface (unlike codex's
        # config.toml, already suppressed via --ignore-user-config) — it also carries
        # default_model/provider/model-catalog data that headless -p mode hard-requires.
        # Re-tested with all three symlinked and confirmed a live
        # `kimi --model kimi-code/k3 -p "..."` call authenticates and answers correctly with
        # $HOME left untouched.
        #
        # On this machine config.toml contains ONLY model/provider/service declarations
        # (default_model, [providers.*], [models.*], [thinking], moonshot_search/fetch base
        # urls) — no user-authored instructions — so linking it does not violate Article 2.6.
        # ~/.kimi-code/AGENTS.md (a genuine host-instruction file, analogous to CLAUDE.md/
        # GEMINI.md) does not exist on this machine today and is deliberately NOT linked here
        # even if created later — same suppression intent as _GEMINI_LEAK_TOP for google.
        _link(real_home / ".kimi-code" / "credentials", temp / "credentials")
        _link(real_home / ".kimi-code" / "device_id", temp / "device_id")
        _link(real_home / ".kimi-code" / "config.toml", temp / "config.toml")
    elif name == "google":
        # agy (Antigravity CLI) resolves creds from ``$HOME/.gemini`` PLUS the macOS login
        # keychain at ``$HOME/Library/Keychains`` (where the OAuth refresh token lives).
        # Restore both, but rebuild ``.gemini`` as a curated dir that omits the three
        # google leak files so host instructions/settings/MCP do not reach the node.
        _link(real_home / "Library" / "Keychains", temp / "Library" / "Keychains")
        src_gemini = real_home / ".gemini"
        if src_gemini.is_dir():
            dst_gemini = temp / ".gemini"
            try:
                dst_gemini.mkdir(parents=True, exist_ok=True)
                for child in src_gemini.iterdir():
                    if child.name in _GEMINI_LEAK_TOP:
                        continue
                    if child.name == "antigravity-cli" and child.is_dir():
                        dst_ag = dst_gemini / "antigravity-cli"
                        dst_ag.mkdir(parents=True, exist_ok=True)
                        for sub in child.iterdir():
                            if sub.name in _GEMINI_LEAK_AGCLI:
                                continue
                            _link(sub, dst_ag / sub.name)
                    else:
                        _link(child, dst_gemini / child.name)
            except OSError:
                return


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
        # stdin=DEVNULL: a headless provider CLI (codex/agy) that probes stdin must never
        # block on the inherited terminal until the hard kill — close it so the call stays
        # truly non-interactive (Md.2.7 graceful degradation; orthogonal to approval_policy).
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env,
                           stdin=subprocess.DEVNULL)
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
    # --model claude-opus-5: 2026-07-31 user decision — lead node runs on Opus 5
    # instead of Fable 5 (higher-reasoning tier for the lead/plan role; Fable 5 was
    # the 2026-07-20 choice, superseded).
    "claude": CLIProfile(
        argv_template=("{cli}", "--model", "claude-opus-5", "-p", "{prompt}"),
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
    # --sandbox: restricts terminal/command execution so a tool call requiring the
    # "command"/"read_file" permission is rejected by the sandbox itself rather than
    # left pending on a prompt headless mode can never answer (proven failure mode,
    # 2026-07-17). Known limitation: prompts that imply file reads still fail outright
    # (read_file gets auto-denied) — only --dangerously-skip-permissions works around
    # that, and that flag is intentionally NOT the default here (2026-07-17 user
    # decision: opt-in per run only, reverted immediately after each such run).
    # 2026-07-22: reproduced live — a task string that asks the node to "verify this
    # yourself" (even with a KANIT block already embedded) makes the model reach for a
    # command tool anyway, which the sandbox then silently denies (empty output, 2
    # quorum failures in one session). A trailing no-tool instruction eliminates it:
    # confirmed live (`agy --sandbox -p "...task ending in a no-tool instruction..."`)
    # answers correctly instead of erroring, with no change to the sandbox/permission
    # posture — this only steers the prompt, it does not grant anything.
    "google": CLIProfile(
        argv_template=("{cli}", "--sandbox", "--print-timeout", "{deadline}s", "-p",
                       "{prompt}\n\n(Not: sandbox+headless modda tool/komut izni istenemez ve "
                       "otomatik reddedilir. Yukarıdaki göreve SADECE verilen kanıta dayanarak "
                       "yanıt ver — dosya okuma, komut çalıştırma veya başka bir doğrulama YAPMA.)"),
        timeout_slack=10,
        default_timeout=240,
    ),
    # Kimi K3: --model pins the specific model the owner asked for (K3, not the account's
    # current default_model) — same pinning intent as claude's "--model claude-fable-5" above.
    # --output-format text is kimi's own documented default but made explicit for the same
    # determinism reasons codex/google spell out their flags explicitly.
    #
    # The trailing no-tool instruction is NOT precautionary boilerplate — it is an
    # empirically REQUIRED control. Verified live: a tool-tempting prompt run as
    # `kimi -p "..." --output-format text < /dev/null` (no --yolo/--auto) executed a real `ls`
    # shell command with NO approval gate — kimi has no --sandbox/read-only flag equivalent to
    # codex's sandbox_mode=read-only or google's --sandbox. The SAME prompt with this trailing
    # instruction appended made the model explicitly refrain from calling any tool and answer
    # from static context only — reproduced live, both directions. Without this, every
    # PLAN/CRITIQUE/VERIFY call to kimi risks live, unsandboxed command execution against the
    # orchestrator's real cwd, violating Article 6.2 for a node meant to be reasoning-only.
    "kimi": CLIProfile(
        argv_template=("{cli}", "--model", "kimi-code/k3", "--output-format", "text", "-p",
                       "{prompt}\n\n(Not: bu headless/otomatik modda tool/komut izni "
                       "istenemez ve onaylanamaz. SADECE verilen göreve ve kanıta dayanarak "
                       "düz metin yanıt ver — dosya okuma, komut çalıştırma veya başka bir "
                       "doğrulama YAPMA.)"),
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
            # Re-seed credentials into the clean home so the node can authenticate
            # (auth is not an instruction-leak; without this codex 401s and agy hits
            # "Authentication required", and kimi errors "No model configured", each silently
            # dropping the quorum below the enabled roster size).
            _seed_isolated_auth(self.name, temp_home)

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
