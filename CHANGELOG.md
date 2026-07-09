# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Honesty rule (Constitution Art. 2.1): entries describe only what was verified — no
unverified "it works" claims. Test evidence is cited where it backs an entry.

## [Unreleased] — Phase 2 (in progress)

### Added

- **Opt-in concurrent PLAN fan-out (`parallel_plan`, default OFF).** When enabled, the
  PLAN node runs each lead provider's subprocess *concurrently* instead of one-after-another
  (wall-clock ≈ slowest provider, not the sum). Only the side-effect-free adapter
  subprocess (`graph._invoke`) runs off-thread; every append-only audit write
  (`graph._record`) stays on the orchestrator thread, in **roster order** — so the
  single-writer DuckDB never contends and the audit/evidence sequence is deterministic
  regardless of which provider returns first. Bounded by `parallel_plan_max` (default 4).
  This is concurrent *reasoning* dispatch — NOT cross-provider work fan-out (still Phase 2).
  Evidence: `tests/test_parallel_and_verify_cmd.py` (concurrency, roster-order determinism,
  serial/parallel agreement, default-OFF).
- **Opt-in real-evidence VERIFY command (`verify_cmd`, default empty).** VERIFY can run an
  operator-configured acceptance command (e.g. `pytest -q`) whose **exit code is the
  authoritative verdict** — an LLM "looks correct" can never override a failing real check
  (Constitution Art. 2.1/2.7, evidence > consensus; gate-test ≠ real-test). The command is
  operator config (NOT model output), gated through the `exec_policy` hard-floor
  (`repair.gate_command` — a destructive shape is refused with an incident, never run),
  run with NO shell (`shlex.split`), and its exit code recorded as append-only evidence.
  Empty `verify_cmd` is fully backward-compatible (LLM-only verify, unchanged). Evidence:
  `tests/test_parallel_and_verify_cmd.py` (exit-code overrides LLM both directions,
  destructive refused, evidence recorded, backward-compatible).
- **Opt-in concurrent VERIFY fan-out (`parallel_verify`, default OFF).** When enabled,
  VERIFY asks *every* available non-executor agent independently instead of a single
  producer≠verifier pick, so `n_crossverified` can genuinely exceed 1 (`decide.py`'s
  `min(n_crossverified,3)*weight` scoring formula always supported this; VERIFY never
  fanned out to use it). A split PASS/FAIL verdict across verifiers is **not**
  majority-resolved (Article 7: evidence, not a vote) — it forces `human_required`
  regardless of confidence, the same immutable-override pattern as a destructive command,
  and both verdicts are recorded as dissents. Unanimous agreement (all PASS or all FAIL)
  behaves like the existing single-verifier path, just with every vote counted. Bounded by
  `parallel_verify_max` (default 4). Evidence: `tests/test_graph_orchestration.py`
  (`test_parallel_verify_*` — off-by-default, agreement raises the cross-verify count,
  disagreement escalates to a human + records dissents, unanimous FAIL still retries).
- **`decide()` scoring weights moved from hardcoded literals to `Config`.** The additive
  score (base 0.45, +0.15/crossverify, +0.05/evidence, +0.10 consensus, -0.10/dissent,
  -0.15/tool_failure) is now `decide_base_score` / `decide_crossverify_weight` / etc. on
  `Config`, mirroring the existing `confidence_floor`/`confidence_cap_noxval` pattern —
  the module docstring already claimed these were "profile-overridable"; now they actually
  are. Pure refactor: defaults are byte-identical to the old hardcoded values. Evidence:
  `tests/test_decide.py` (`test_scoring_weights_default_to_the_old_hardcoded_values`,
  `test_scoring_weights_are_tunable_per_instance`).
- **Roster duplicate-name dedupe.** `_coerce_agents` now drops later collisions on a
  logical agent name (keeps the first), so a duplicated roster name can no longer silently
  overwrite a plan or collapse producer≠verifier. Evidence: `tests/test_hardening_small.py`.
- **Watchdog grace-floor + regime path-traversal regression tests.** Lock in two existing
  safety boundaries with explicit assertions: the watchdog reaps only past BOTH the wall
  budget AND `MIN_STALL_IDLE_S` (a briefly-idle run is never falsely reaped), and a
  path-traversal `data_regime` resolves to no terms (cannot escape `regimes/`). Evidence:
  `tests/test_watchdog_grace_invariant.py`, `tests/test_hardening_small.py`.

### Fixed

- **claude node-isolation argv used an INVALID `--setting-sources` value (provider-breaking).**
  The isolation injection passed `--setting-sources none`, but the claude CLI rejects
  `none` (`Invalid setting source: none. Valid options are: user, project, local`) — so
  with default isolation ON, **every claude provider call failed** (an always-on,
  silently-fatal break). A live end-to-end `konsey run` surfaced it (the exact
  gate-test ≠ real-test lesson: the unit test asserted the flag was *injected*, not that
  the real CLI *accepts* it). Fixed to `--setting-sources ""` (the empty list = load no
  setting sources = the intended isolation), verified live: claude now runs under
  isolation and a full 9-state `konsey run` completes. Tests updated to assert the
  live-verified value.

### Changed

- **Honesty pass — node-isolation enforcement is shipped, not "deferred (PR2)" (Art. 2.1).**
  `adapters.py` already injects the per-provider isolation argv/env (claude
  `--strict-mcp-config --setting-sources none`; codex `--ignore-user-config` +
  `project_doc_max_bytes=0` + isolated `CODEX_HOME`/`-C`), default-ON behind the
  `unsafe_inherit_provider_config` opt-out — but KNOWN_ISSUES and `test_isolation.py` still
  called enforcement "deferred to PR2". A council re-evaluation flagged the doc↔code
  contradiction; the docs are corrected to match the shipped reality (the behavioural
  cross-surface smoke remains the honest open item). Evidence:
  `tests/test_adapters_isolation.py` (the flags are injected) + a regression guard in
  `tests/test_s8_honesty.py` (docs may not drift back to "deferred").

### Removed

- **Dead `council/run.py` module (tech-debt; autonomous cycle 2).** A vestigial headless
  entry that duplicated `cli.py::cmd_run` (the real `konsey run` handler). It had no
  console-script entry (pyproject wires only `council.cli:main`), no importer, no test,
  and no doc reference — a whole-project council eval flagged it as a duplicate with its
  own entry path that packaging never pointed at. Removed; `konsey run` is unaffected (full
  suite green, no test referenced it).

### Changed

- **Honesty pass (S8) — docs match reality (Constitution Art. 2.1).** A whole-project
  council re-evaluation (7 dimensions + Codex adversarial) returned VERDICT: OVERCLAIMS at
  maturity = **alpha**; this lands the doctrine-required corrections. The stale "92/92"
  test count (true at v0.1.0, now 361) is replaced in README / README.tr / KNOWN_ISSUES
  with "run `pytest` for the live count" + the current snapshot; the maturity label is now
  explicitly **alpha**, not beta. A new "what is and isn't distributed yet" callout states
  honestly that the always-on `konsey run` loop distributes the DECISION on provider TEXT
  (it does not shell out — `graph.py`); real-work execution (`konsey do`, Faz 3a) is
  opt-in, single-provider, triple-locked, and NOT in that loop — fan-out (3b) + graph
  integration (3c) stay Phase 2. So "distribute work across providers" is partly shipped
  (decision) and partly roadmap (work-in-loop). The stale `run --dry-run` KNOWN_ISSUE is
  moved to Resolved (the code now passes `cfg`). A regression test guards the 92/92 claim
  and the alpha/callout from reappearing. (Historical "92/92" records in the CHANGELOG
  [0.1.0] and the Resolved sections are left intact — they accurately describe the past.)

### Added

- **Onboarding fluidity & honesty (S7) — a guided wizard, not an interrogation.** `konsey
  init` keeps its exact branching but gains the connective copy that makes a new user feel
  guided and in control (people want fluidity + usability as much as security). Additive,
  interactive-only (piped / `--quick` stay terse), no security regression, and — per the
  Codex evaluation — copy/clarity, NOT a structural refactor. New: a one-screen **welcome**
  (what konsey is + what the wizard sets up); a **posture preamble** that explains, BEFORE
  the question, exactly how much each level lets konsey touch the system (and that the
  `autonomous` label only arms read-only — no posture ever grants a blind write); the
  **data-regime liability disclaimer moved BEFORE** its question (was only shown after, too
  late to reconsider); **answer echoes** ("✓ language: en", "✓ owner: …"); the real
  **append-only audit trail surfaced honestly** in the summary (its DB path + `konsey
  audit` — no fabricated "memory" feature, just discoverability of what exists); and a
  confident **"three things to try next"** close that also offers the S6 self-continuation
  (`konsey doctor` · `konsey run` · `konsey enable automation`). 4 new tests (guided
  interactive copy, --quick stays terse but keeps the facts, honest audit surfacing, en/tr
  parity). The wizard's actual question flow and the non-TTY honest-defaults path are
  unchanged.

- **Self-continuation & a resilience watchdog (S6) — opt-in, default OFF.** konsey can now
  continue on its own after install AND recover failed/stalled runs instead of sitting dead.
  New `council/watchdog.py`: a READ-only scan of the audit DB + APPEND-only actions (Art.
  10/11.2 — never mutates an audit row) that each idempotent pass (a) **reaps** a STALLED
  session (session_start with no session_end, idle past its wall-budget) by appending
  `session_end(aborted-watchdog)` + an incident — so a stuck run can't fail-stop forever;
  (b) **re-queues** a RETRIABLE failure (risk ≤ internal, under a bounded retry budget, a
  bridge present) into the dispatch inbox, where the EXISTING autonomy ceiling re-gates it —
  so the watchdog can never bypass a human gate; (c) **escalates** gated (pii/sensitive/
  production) or budget-exhausted work to a human incident, once. It runs inside
  `dispatch tick` (so the scheduler ticks it for free) and via a new `konsey watchdog` /
  `python -m council.dispatch watchdog`. New `konsey enable automation` consciously opts in
  (sets a dispatch `bridge_dir` so dispatch+watchdog are no longer inert + installs the OS
  scheduler via `get_scheduler().install`, idempotent, reversible). **Reversibility fix
  (Codex S6 finding):** `uninstall --automation` previously looked for a non-existent
  module-level `scheduler.uninstall` and always reported a no-op — it now resolves the real
  backend (`get_scheduler(cfg.scheduler).is_installed()/uninstall()`) so an installed
  agent/timer/task is actually removed. `doctor` gains an automation observability line
  (scheduler installed? dispatch bridge armed?). 13 new tests (watchdog reap/requeue/
  escalate/idempotency/budget over a seeded temp DuckDB; the CLI surface with NullScheduler
  so nothing touches the real OS). The autonomy ceiling (`dispatch.AutoGate`, public/internal
  only) is untouched and is reused, not re-implemented.

- **Distribution infrastructure (S5) — release-ready, but PUBLISHES NOTHING.** Everything
  needed to ship to PyPI/Homebrew is in place and mergeable, with zero publish risk.
  **Security fix (load-bearing):** a plain `python -m build` from a working tree leaked
  gitignored machine/doctrine files into the sdist — verified it shipped `council.local.toml`
  (a machine profile) and `constitution/KONSEY_ANAYASASI.md` (the live doctrine draft),
  violating Constitution Art. 2/13. Fixed with an explicit `[tool.hatch.build.targets.sdist]`
  ALLOWLIST (the sdist is now a closed set; only `constitution/README.md` — the CC-BY
  summary — ships, never the draft), plus a CI grep guard and a pytest that builds the real
  sdist and asserts the leak is gone. The version is now single-sourced from
  `council/__init__.py` via `[tool.hatch.version]` (no more duplicated literal); `twine`
  joins `[dev]` and `twine check --strict` passes on both artifacts; project URLs point at
  the real org. New `.github/workflows/release.yml` builds + `twine check` + leak-guards on
  every PR/dispatch/tag but the **upload is inert under four independent locks** (tags-only +
  a `pypi-release` environment that does not exist yet + OIDC-only/no-tokens + the publish
  step commented out) — so merging it cannot publish. New `packaging/konsey.rb` (Homebrew
  personal-tap scaffold, placeholders) and `RELEASING.md` (the exact human steps for the
  eventual, owner-approved, irreversible publish: PyPI Trusted Publisher, TestPyPI dry-run,
  tag, environment approval, brew sha256). 6 new tests (dynamic-version single-source, sdist
  allowlist excludes the leak files / includes the required ones, real-build leak proof).
  **Not done here (deliberate, owner-gated):** the actual public publish — claiming the
  `konsey-cli` name + going public — remains a separate manual act pending the patent /
  dual-license review.

- **Onboarding posture presets (S4) — `konsey init --preset advisory|balanced|autonomous`.**
  `init` now leads with one opinionated POSTURE choice instead of a long question list
  (rustup-style minimal/default/complete). A preset is a convenience bundle of
  ALREADY-SAFE `Config` values — never a way to unlock something unsafe by name, enforced
  by construction in the new pure `council/presets.py` and pinned by tests:
  `advisory` = single provider + `exec_sandbox=off` (honest advisory mode), `balanced`
  (default) = full council + no writes, `autonomous` = same but `exec_sandbox=read-only`
  which only ARMS the first execution lock — `konsey do` still refuses without
  `KONSEY_EXEC=1` + a TTY confirm, so no posture can silently grant writes. No preset
  enables `workspace-write`, flips `autocapture_enabled`, or selects a non-`standard`
  regime. Resolution is flag > interactive Q2 > balanced; `--preset` works headless and
  the non-TTY notice now NAMES the applied preset. The wizard drops the rarely-needed
  org/node questions (auto `""`, still settable via `konsey config set`), so interactive
  init is shorter (locale → preset → owner → optional regime). A new `preset` scalar is
  written to `council.local.toml` and added to `Config` (default `"balanced"` — old
  profiles load unchanged) and to the `config get/set` scalar allow-list. `init` ends
  with a short fact-only profile summary (posture/owner/roster/execution state — distinct
  from `doctor` health). 14 new tests (pure table + honesty invariants, real `cmd_init`
  writes, advisory→lead-only, non-TTY naming + flag-wins, backward-compat load, en/tr
  parity); the existing init tests keep passing via `getattr(args, "preset", None)`.

- **Installer UX + crash-resistance (S3) — engaging, degrades cleanly, always
  completes or fails honestly.** `install.sh` gains a one-shot capability layer
  (`UI_COLOR/UI_UNICODE/UI_TTY/UI_WIDTH`, honoring `NO_COLOR` veto /
  `FORCE_COLOR`/`CLICOLOR_FORCE` / a `KONSEY_NO_UI` escape hatch) and a small UX
  kit — numbered `[n/N]` step headers, a TTY-only spinner for the slow `pip`
  steps (the wrapped command's real output is CAPTURED and surfaced on failure,
  never hidden), success/warn/error glyphs with ASCII fallback, and a bordered
  summary box. All of it is strictly ADDITIVE: on a pipe / CI / `NO_COLOR` /
  dumb terminal it degrades to plain ASCII identical in spirit to before. The
  core is a POSIX **EXIT + INT/TERM trap** (NOT the bash-only `set -o pipefail`
  / `trap ERR`) that captures `$?` first, prints a stage-named "safe to re-run"
  failure panel on ANY non-zero exit or Ctrl-C, and does SCOPED, idempotent
  cleanup — it removes only a venv it was mid-creating THIS run, never a reused
  one, and never narrates on success. A `KONSEY_UI_SELFTEST` hook drives the kit
  without installing, so CI can prove the capability matrix + the failure box.
  New CI `shellcheck -s sh` job guards the POSIX dialect; 9 new tests (capability
  degradation, NO_COLOR-vetoes-FORCE_COLOR, the failure trap, stderr-only
  summary, dash parse, no-bash-isms). Verified: `sh -n`/`dash -n` clean,
  shellcheck clean, a real non-TTY `./install.sh --no-init` completed exit 0 with
  the new summary box. (Follow-up: a Docker clean-install + pseudo-TTY E2E job —
  see KNOWN_ISSUES.)

- **Naming flip (S0) — `konsey` is now CANONICAL, `council` a deprecated alias.**
  The command, brand, docs, and install output lead with `konsey`; `_prog_name()`
  now falls back to `konsey` for `python -m`/test invocations. `council` keeps
  working identically, but invoking it on an interactive terminal prints one
  non-fatal stderr nudge (`cli.council_deprecated`, en/tr) — silent on `konsey`,
  on pipes/scripts, and on `python -m` so captured output, CI, and the
  install-time probes stay clean. `KONSEY_*` env vars are now PREFERRED over
  `COUNCIL_*` (each `COUNCIL_*` var still works as a deprecated fallback):
  `KONSEY_HOME`, `KONSEY_CONFIG`, `KONSEY_REGIME_FILE`, `KONSEY_SECRETS_FILE`
  (joining the already-preferred `KONSEY_DATA_HOME`/`KONSEY_LOCALE`/`KONSEY_EXEC`/
  `KONSEY_REPAIR`). **Deliberately NOT renamed** (high-churn + live-user-data
  migration, deferred): the internal Python package `council/`, the
  `council.local.toml` filename, the DuckDB tables, and `cfg.council_home` — a CLI
  name differing from its internal package name is standard and breaks nothing.
  11 new tests assert konsey-first + full `COUNCIL_*` backward-compat + the
  TTY-gated notice; en/tr key parity preserved.

- **De-domestication — regimes + locales are now DISCOVERED, not hardcoded to TR/EU/US.**
  The core was region-neutral by design but strangled by allowlists: `gateway._REGULATED_REGIMES
  = {kvkk,gdpr,hipaa}` (gated the generic pack loader at 3 sites), `cli._REGIMES`/`_LOCALES`
  tuples, and a binary `tr`-or-`en` detector. Now: a regime is "regulated" iff a
  `regimes/<name>.toml` pack exists (any jurisdiction drops in as data — no core edit);
  locales are discovered from `council/locales/*.json`; `_detect_locale` does BCP-47-ish
  negotiation (`KONSEY_LOCALE` > `$LANGUAGE` list > `LC_ALL`/`LC_MESSAGES`/`LANG`, reduced
  `es_MX→es`, first shipped catalog wins). Ships **7 starter regime packs** (gdpr, hipaa,
  kvkk, lgpd, ccpa, pipl, pdpa — each a "detection aid, NOT a compliance guarantee" with a
  national-ID regex) and **4 starter locales** (es, fr, de + ar as an RTL exemplar; partial,
  safe via per-key English fallback). `install.sh --locale` accepts any tag. 10 new tests;
  en/tr parity preserved. (Naming flip to `konsey`-canonical is a separate follow-up.)
- **Real-work execution — `council do "<task>"` (Faz 3a, opt-in, default OFF).** The
  centerpiece's smallest safe increment: ONE sandboxed provider (claude→codex; agy
  excluded — least-scopable) edits an **isolated git worktree** (off HEAD, under
  `data_home`, outside the repo) to perform a task; success is proven ONLY by a fresh
  acceptance command the harness re-runs itself (producer≠verifier — the worker's "done"
  is not evidence; `--accept` is REQUIRED, no-accept ⇒ tri-state UNVERIFIED, never a
  pass); the verified branch is kept for the human to review/merge/PR ONLY on explicit
  approval — konsey NEVER auto-merges (esp. not to master). Three independent OFF locks:
  `exec_sandbox != "off"` + `KONSEY_EXEC=1`/`--force` + a TTY confirm. New `council/execute.py`
  (`do_work`→`WorkResult`) + `council/worktree.py` (injected `GitRunner`), both thin over
  the Faz 2 `repair.py` primitive (same profiles/env-allow-list/scrub/gate/runner). Also
  `council doctor --json` (from Faz 2). 16 new tests with injected git+worker+acceptance
  (no live agent). NOT wired into the always-on `council run` graph (that's 3c). Fan-out
  across providers + winner-select is 3b.
- **AI-assisted install repair — the first tool-ON execution primitive (Faz 2, opt-in).**
  `council doctor --json` emits a structured, locale-independent report (`{schema, ok, rc,
  critical, advisory, checks[]}`) from a single source of truth (`_doctor_collect`); the
  pretty default is byte-identical. `council doctor --fix` (default **OFF** — needs
  `KONSEY_REPAIR=1` **or** `--force` **and** a TTY confirm) may hand a broken install to a
  sandboxed, repo-scoped provider via the new `council/repair.py`: a pure invocation
  builder (claude `--permission-mode acceptEdits` / codex `-s workspace-write -a never` /
  agy `--sandbox`, cwd-pinned, fail-closed env allow-list, secret-scrubbed prompt), an
  `exec_policy` hard-floor gate, a post-run outside-repo path gate, and a bounded
  (≤3 attempts, no-progress kill) loop that verifies success ONLY by re-running the real
  doctor (producer≠verifier — the worker's "I fixed it" is not evidence), auditing every
  attempt append-only. The worker profile is kept OUT of the council reasoning roster.
  Verified by 24 new tests with an injected runner (no live agent); a real tool-ON smoke
  is opt-in behind `KONSEY_LIVE_REPAIR`. This is the safe, bounded seam Faz 3 reuses.
- **Node execution isolation — detection (Constitution Article 2.6, new).** A node that
  shells out to a provider CLI loads the *host machine's* AI config (`CLAUDE.md` /
  `AGENTS.md` / `GEMINI.md`, settings/hooks, MCP) — which collapses the cross-provider
  independence Article 2.2 requires and can break a run. New `council/isolation.py`
  (`scan_host_ai_config`) detects that footprint; `council init` lists it at install
  time and `council doctor` surfaces it as a **non-fatal ⚠** (with a `node:count`
  summary). Constitution bumped v7.0.0 → **v7.1.0** (additive, tightening). **Scope:**
  this is PR1 = *detection + doctrine*; isolation **enforcement** (clean argv/env/cwd in
  the adapter layer) is deliberately deferred to PR2 and is tracked in KNOWN_ISSUES.md
  (node-isolation) — it is NOT claimed complete here.
- `council doctor` now emits a **warning when fewer than 2 runnable providers** are on
  PATH, so a single-provider (advisory-mode) install is surfaced rather than silently
  accepted.

### Changed

- Fresh-install audit on Linux (Docker `python:3.12-slim`): install → init → doctor →
  run + `cron` scheduler install/uninstall round-trip + `pytest`, all green; macOS-only
  backends correctly returned no-ops on Linux without raising.
- `pyproject.toml` project URLs corrected to the `konsey` repository.
- `install.sh` prints an informational note when the chosen interpreter is newer than
  the CI baseline (3.12); the version gate itself is unchanged (`>= 3.12` floor, no
  upper bound enforced).
- READMEs (EN + TR) "Status / maturity" updated to reflect the implemented-and-tested
  MVP (92/92) instead of the earlier "Phase 1 scaffold / documented stubs" wording;
  stale `(Phase 2)` references to `SECURITY.md` / `CONTRIBUTING.md` removed (both ship
  now); the subcommand note now lists all wired commands instead of claiming they are
  "being ported".

### Known limitations

- See [`KNOWN_ISSUES.md`](./KNOWN_ISSUES.md). Outstanding Phase 2 items include live
  **systemd-timer** and **Windows Task Scheduler** daemon validation (the backends exist
  but have not been exercised against a running scheduler), full i18n catalog coverage,
  and multi-config audit isolation.

## [0.1.0] — 2026-05-29 — MVP (Phase 0+1)

First portable, vendor-independent release of the Council orchestrator and doctrine.

### Added

- **CLI** (`council`, with a `konsey` alias): `init`, `doctor`, `run`, `status`,
  `audit`, `config`, `agents`, `enable`, `stop`, `uninstall` — all wired and runnable.
- **9-state loop** (`graph.py`): PREFLIGHT → PLAN → CRITIQUE → SYNTHESIZE → EXECUTE →
  VERIFY → DECIDE → REPORT → MEMORY, with the producer ≠ verifier invariant, a
  wall-time kill switch, and a consecutive-tool-failure cap.
- **Configuration contract** (`config.py`): `Config`, `RosterEntry`, `by_role()`,
  `verifier(exclude=)`, `available()` — the single injection point. All machine-facts
  arrive from a git-ignored `council.local.toml`; no brand, path, project, or owner
  identity is baked into the code.
- **Vendor-neutral adapters** (`adapters.py`): one class per provider CLI
  (`claude` / `codex` / `agy`), resolved via `adapter_for(cfg, name)`; swapping a
  provider is a single roster line.
- **PREFLIGHT gateway** (`gateway.py`): risk classification (public / internal / pii /
  sensitive / production) plus an always-on secret/PHI fail-safe scan (e.g. `sk-ant`,
  `AKIA` blocked under `standard`). Sensitive data is never routed to a disallowed or
  consumer LLM endpoint (Art. 4.5).
- **Evidence-weighted decide** (`decide.py`): decisions scored on cross-verification,
  evidence, and tool-success — not a majority vote. Only pii / sensitive / production
  (or low-confidence) escalate to a human; public/internal complete autonomously in
  advisory mode (Art. 7.1).
- **Append-only audit** (`audit.py`, DuckDB): every message, evidence item, decision,
  and dissent written append-only (no UPDATE / DELETE), enforced at the application
  layer (tamper-evident, not tamper-proof — Art. 11.2).
- **Capture / dispatch** (`capture.py`, `dispatch.py`): opt-in autocapture (default
  OFF) and a single-instance-locked periodic `dispatch tick`.
- **OS abstraction layer** (`platform/`): `scheduler` (launchd / systemd / schtasks /
  cron / Null), `notify`, and `secrets` backends — all defaulting to a no-op (`null`)
  so the core runs without any of them; background automation is opt-in and default
  OFF.
- **Advisory mode**: with a single provider, confidence is capped at `0.6` and output
  is stamped "unverified"; cross-validation requires ≥ 2 independent providers.
- **Opt-in regulatory regimes** (`regimes/*.toml`, `standard` / `kvkk` / `gdpr` /
  `hipaa`): regulatory term lists live only in plugins, never in core/audit/capture
  code — a detection aid, not a compliance guarantee (Art. 4.3).
- **Council Constitution v7.0.0** (`constitution/`, CC-BY-4.0) — the portable doctrine
  the orchestrator enforces, licensed separately from the Apache-2.0 code.
- **Self-configuring install** (`install.sh`, Art. 0 Bootstrap): POSIX, idempotent,
  sudo-free; detects OS + Python (≥ 3.12 floor), creates an isolated `.venv`, installs
  pinned deps, then runs `council init` + `council doctor`.
- **Tooling & docs**: `README.md` / `README.tr.md`, `SECURITY.md`, `CONTRIBUTING.md`,
  `KNOWN_ISSUES.md`, GitHub CI (ruff + mypy + pytest on macOS + Ubuntu, Python 3.12)
  and a secret-scan workflow.

### Verified

- **92/92 tests pass** (`python -m pytest`) covering config/bootstrap, the risk gateway,
  the secret scan, append-only audit, adapters, and decide — on Python 3.12 (the CI
  baseline and proven floor).
- **Fresh Linux install** audited end-to-end in Docker `python:3.12-slim` (install →
  init → doctor → run + cron install/uninstall round-trip + pytest, all green).

### Security / privacy

- No telemetry; all data is local. Providers are invoked as plain subprocesses — no
  SDK, no API keys in core, no Council-operated server.

[Unreleased]: https://github.com/OWNER/konsey/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/OWNER/konsey/releases/tag/v0.1.0
