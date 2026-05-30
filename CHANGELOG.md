# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Honesty rule (Constitution Art. 2.1): entries describe only what was verified — no
unverified "it works" claims. Test evidence is cited where it backs an entry.

## [Unreleased] — Phase 2 (in progress)

### Added

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
