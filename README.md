# Konsey

**English** · [Türkçe](./README.tr.md)

> Multi-agent, evidence-weighted, vendor-independent work doctrine + orchestrator.
> Runs on any machine; configures itself on install. No telemetry — all data local.

[![License: Apache-2.0](https://img.shields.io/badge/code-Apache--2.0-blue.svg)](./LICENSE)
[![Doctrine: CC-BY-4.0](https://img.shields.io/badge/doctrine-CC--BY--4.0-lightgrey.svg)](./constitution/)
[![Python](https://img.shields.io/badge/python-%E2%89%A53.12-blue.svg)](./pyproject.toml)
![No telemetry](https://img.shields.io/badge/telemetry-none-success.svg)

---

## 1. What is Council?

Council turns any task into a **multi-agent, evidence-weighted, fully-audited**
workflow across independent LLM CLIs (for example `claude`, `codex`, `agy`). It runs
entirely in your terminal, calls each provider as a plain subprocess (no SDK, no API
keys in core), and writes every step to a local append-only audit store. Install it on
any machine; it configures itself on first run (Article 0 Bootstrap) — nothing
machine-specific is ever baked into the code.

## 2. Why? — the three pillars

- **Single-LLM blind spot.** One model's confident error is invisible to itself. An
  independent second (or third) provider catches it. In Council the *producer* of a
  claim is never its *sole verifier* — that invariant is enforced, not suggested.
- **Auditability.** Every message, evidence item, decision, and dissent is written
  **append-only** to a local database (no UPDATE / DELETE). Months later you can still
  answer: *who decided what, on what evidence, and who disagreed?*
- **Evidence > consensus.** Decisions are **scored** on cross-verification, evidence,
  and tool-success — not a majority vote. Sensitive / production / low-confidence work
  escalates to a human instead of being auto-completed.

## 3. How it works

A deterministic nine-state loop:

```
PREFLIGHT → PLAN → CRITIQUE → SYNTHESIZE → EXECUTE → VERIFY → DECIDE → REPORT → MEMORY
```

- **PREFLIGHT** — risk classification + secret/PHI fail-safe gate.
- **PLAN / CRITIQUE / SYNTHESIZE** — Lead drafts, Critic attacks adversarially, Lead
  reconciles.
- **EXECUTE** — under an execution safety boundary. Today the loop produces the work as
  provider *output* and human-gates anything destructive; it does **not** shell out — real
  file/command execution is the opt-in `konsey do` path (see [§9](#9-status--maturity)).
- **VERIFY** — a *different provider* than the executor checks the result
  (producer ≠ verifier).
- **DECIDE** — evidence-weighted score, not a vote.
- **REPORT / MEMORY** — summary + append-only audit + distillation.

Invariants: producer ≠ verifier; a kill switch bounded by wall-time and a
consecutive-tool-failure cap (`konsey stop` triggers it manually at any time).

## 4. Architecture

```
                 council.local.toml  (git-ignored, written by Bootstrap)
                          │   the single injection point
                          ▼
                  ┌───────────────┐
                  │   config.py   │  Config dataclass · by_role() · verifier(exclude=)
                  └───────┬───────┘
                          │
  vendor-neutral adapters │      gateway / PREFLIGHT
  (one class per CLI)  ───┼────  (risk class + secret scan)
                          │
                  ┌───────▼────────┐
                  │  9-state graph │  (LangGraph)
                  └───────┬────────┘
                          │
            evidence-weighted decide
                          │
                  append-only audit (DuckDB)
                          │
                 dashboard  ·  A2A (optional, off by default)
```

**Swapping a provider changes one roster line — never the architecture.** Roles
(Lead / Critic / Researcher / Verifier / Distiller) are generic and assigned to
providers at run time via `cfg.by_role()` and `cfg.verifier(exclude=...)`; no core
module hard-codes a brand name, a path, a project name, or an owner identity.

## 5. Install

```bash
git clone <repo> konsey && cd konsey
./install.sh            # detects OS, pins deps, runs the Article-0 Bootstrap
konsey doctor           # PROVES which provider CLIs are actually on PATH
```

Alternative (isolated environment, does not pollute system Python):

```bash
pipx install konsey-cli
```

**Honest notes:**

- **Python ≥ 3.12 is required** (this is the proven, tested version; 3.10/3.11 are
  *not* claimed, only what was verified).
- You need **at least one** provider CLI (`claude` / `codex` / `agy`); the rest
  degrade gracefully.
- **Cross-validation needs ≥ 2 independent providers.** With a single provider konsey
  runs in *advisory mode*: confidence is capped at `0.6` and output is stamped
  "unverified". The third node — `agy` (Google Antigravity) — is **optional** and
  harder to install; most setups run 1–2 providers. This is an honest default, not a
  marketing claim.

## 6. Usage

```bash
konsey run "Refactor X and prove the tests still pass"
konsey run "Audit this design doc" --project myrepo --dry-run
konsey doctor                 # evidence-based health: which CLIs resolve, DB write/rollback
konsey audit                  # browse the append-only log (read-only)
konsey init                   # (re)run the self-configuring Bootstrap
```

`council …` is a **deprecated** but fully-working alias of `konsey …` (the help banner and `--version` reflect whichever name you invoke; calling `council` on a terminal prints a one-line nudge toward `konsey`).

> All subcommands above (`init` / `doctor` / `run` / `status` / `audit` / `config` /
> `agents` / `enable` / `stop` / `uninstall`) are wired and runnable today — verify with
> `konsey --help`. See [Maturity](#9-status--maturity) for what has been exercised on
> which platform.

## 7. Configuration

Everything machine-specific lives in **`council.local.toml`** (git-ignored, written by
Bootstrap) and flows through `council/config.py` — the single injection point. Nothing
machine-specific is ever tracked in the repository.

A real config has no secrets in it, only declarative facts. Start from
[`examples/council.local.example.toml`](./examples/council.local.example.toml) (a
fictional "Acme Labs" profile, **not** derived from any real deployment):

```toml
owner = "operator"          # NOT your machine username — never leaked to the audit log
org = "Acme Labs"
locale = "en"               # en | tr
data_regime = "standard"    # standard | kvkk | gdpr | hipaa
exec_sandbox = "off"        # off | read-only | workspace-write
autocapture_enabled = false # opt-in; default OFF

[[agents]]                  # generic role → provider; producer is never its sole verifier
name = "claude"
cli  = "claude"
role = "lead"

[[projects]]                # a project name alone never implies phi
match = "infra/*"
risk  = "production"
```

Regulatory term lists (clinical / national-ID regexes) live **only** in opt-in regime
plugins (`regimes/*.toml`, activated by `data_regime`) — never in core, audit, or
capture code. See
[`examples/regimes/clinical.example.toml`](./examples/regimes/clinical.example.toml).

## 8. The Constitution

The orchestrator enforces a portable doctrine — the
[Council Constitution](./constitution/), version **7.0.0**, licensed **CC-BY-4.0**
(separately from the Apache-2.0 code). It is the immutable rule set; all machine-facts
arrive from `council.local`, never from the doctrine text.

Binding articles in brief: Bootstrap (Art. 0); evidence over consensus and
producer ≠ verifier (Art. 2); generic roles + advisory mode (Art. 3); the fail-safe
PHI / PII / secret gate (Art. 4); evidence-weighted decisions (Art. 7); append-only
audit (Art. 10/11). The immutable core (Art. 2, 4, 5, EXECUTE safety, decision
ceiling/floor, append-only) can be *tightened* by a profile or session, never
*loosened*.

## 9. Status / maturity

**Honest, current state — v0.1.0, _alpha_ (Phase 0+1 complete, Phase 2 in progress).**
The decision architecture and safety gates are real and tested; live multi-provider
tool-on execution, node-isolation _enforcement_, and live systemd/Windows daemons are
not yet mature — this is alpha, not beta.

- The core is **implemented and tested**: the full CLI (`init` / `doctor` / `run` /
  `status` / `audit` / `config` / `agents` / `enable` / `stop` / `uninstall`) plus the
  modules behind it — `config` / `adapters` / `gateway` / `decide` / `graph` (the
  9-state loop) / `audit` / `capture` / `dispatch`. The configuration contract
  (`Config`, `RosterEntry`, `by_role()`, `verifier(exclude=)`, `available()`) is the
  single injection point.
- **Test evidence: the suite is green** — run `python -m pytest` for the live count
  (361 as of this writing, and growing). It covers config/bootstrap, the risk gateway,
  the secret scan, append-only audit, adapters, the evidence-weighted decide, the
  resilience watchdog, onboarding presets, the de-domestication regime/locale layer, and
  the installer self-test. Verified on Python 3.12 (the CI baseline and the proven
  floor). Newer interpreters (3.13/3.14) are expected to work but 3.12 is what CI pins.
- **What is and isn't distributed yet — read this.** The always-on loop (`konsey run`)
  distributes the *decision*: it runs the providers in their roles (lead plans, critic
  attacks adversarially, distiller synthesizes) across PLAN/CRITIQUE/SYNTHESIZE and
  scores an evidence-weighted, cross-verified decision on their **text** output — the
  loop itself does not shell out or apply changes (`graph.py`). **Real-work execution**
  (`konsey do`, Faz 3a) — a sandboxed provider editing an isolated git worktree — is
  **opt-in, single-provider, triple-locked, and NOT wired into that loop**; cross-provider
  fan-out (3b) and graph integration (3c) are **Phase 2**. So today konsey distributes
  the *decision* fully and executes work in a bounded, opt-in slice — not yet work fanned
  out across providers in the always-on loop. (`konsey enable automation` adds an opt-in
  scheduler + a resilience watchdog that recovers stalled/failed runs.)
- **Verified platforms.** macOS is the primary development target. A **fresh Linux
  install was audited end-to-end** (Docker `python:3.12-slim`: install → init → doctor
  → run + `cron` scheduler install/uninstall round-trip + pytest, all green); the
  macOS-only backends correctly returned no-ops on Linux without raising. **Not yet
  exercised with a live background daemon: systemd user timers and Windows Task
  Scheduler** — those backends exist but are unvalidated against a running scheduler
  (see [`KNOWN_ISSUES.md`](./KNOWN_ISSUES.md)).
- Across the OS abstraction layer, the **scheduler / notify / secret backends** default
  to a no-op (`null`) implementation, so core runs without any of them; background
  automation is opt-in and **default OFF**.

This README does not claim more than the code currently delivers; check
`konsey doctor` for the live, evidence-based status on your machine, and
[`KNOWN_ISSUES.md`](./KNOWN_ISSUES.md) for the deferred items.

## 10. Privacy & security

- **No telemetry. All data is local.** Council routes prompts only to whatever provider
  CLIs *you* install and run as subprocesses — there is no Council-operated server.
- **The gateway is a safety net, not a guarantee.** The secret/PHI scan reduces
  accidental leaks; it does not certify compliance. Regulatory regimes
  (`kvkk` / `gdpr` / `hipaa`) are a *detection aid*, **not** a compliance guarantee —
  legal responsibility is the operator's (Article 4.3).
- **The append-only audit is tamper-*evident*, not tamper-*proof*.** Append-only is
  enforced at the application layer; a process running as the same OS user could still
  rewrite the file. OS-level immutability is **not** guaranteed (Article 11.2). Read
  [`SECURITY.md`](./SECURITY.md) before processing sensitive data.
- Sensitive data is never sent to a disallowed endpoint or a consumer LLM endpoint —
  that is an unconditional block, not overridable by human approval (Article 4.5).

## 11. Contributing

Contributions are welcome. The contribution gate ([`CONTRIBUTING.md`](./CONTRIBUTING.md))
requires: no secrets, no organization/product names, no absolute paths, and tests with
their output. Adding a provider is one adapter class / config line; adding a regulatory
regime is one plugin file — the core does not change. Security issues go through
**private** disclosure (`SECURITY.md`), never a public issue.

## 12. License & citation

- **Code:** Apache-2.0 — see [`LICENSE`](./LICENSE) and [`NOTICE`](./NOTICE).
- **Constitution / doctrine text:** CC-BY-4.0 — see [`constitution/`](./constitution/).
  The doctrine is attributable and may be adapted with attribution.
