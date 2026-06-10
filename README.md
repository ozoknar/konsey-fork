# Konsey 🏛

> 🇹🇷 **Türkçe:** [README.tr.md](./README.tr.md) · 🇬🇧 English (this page)

![CI](https://github.com/eMediquality/konsey/actions/workflows/ci.yml/badge.svg)
![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)
![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)

**A multi-agent, evidence-weighted work doctrine.** **Evidence** decides — not consensus.

Konsey runs the Claude, Codex, and Google nodes independently, has them cross-critique each
other's plans, validates output with a **producer-cannot-verify** rule, and writes every step
to an append-only audit DB. Instead of trusting a single LLM's "because I said so", it returns
a decision that independent providers have validated against external evidence.

```
PREFLIGHT → PLAN → CRITIQUE → SYNTHESIZE → EXECUTE → VERIFY → DECIDE → REPORT → MEMORY
```

---

## Why Konsey?

- ⚖️ **Evidence over consensus** — independent providers cross-validate; a producer never verifies its own output.
- 🔌 **Vendor-neutral** — Claude, Codex, Gemini, or your own — config-driven, swap any provider in one line.
- 🔒 **Local-first option** — run entirely on-device with Ollama; **no data leaves your machine** (ideal for PHI/regulated work).
- 🛡️ **Layered, opt-in safety** — strict/medium/weak levels, secret + PHI scanning, append-only audit trail.
- 💬 **Meet users where they are** — Telegram, Notion, Slack & WhatsApp connectors, with the **same risk gate on every channel**.
- 🌍 **Bilingual** — English/Turkish, locale-aware (`KONSEY_LANG`).
- 🪶 **Tiny & auditable** — two core deps (`langgraph` + `duckdb`), one-command install, green CI, MIT.

---

## Quick start

**One command (remote):**
```bash
curl -fsSL https://raw.githubusercontent.com/eMediquality/konsey/master/install.sh | bash
```
During install you're asked for a **security level** and **opt-in telemetry** (both default-safe).

> **Pin to a release (recommended):** `master` is the latest, moving code. For a stable,
> auditable install, use a release tag:
> ```bash
> curl -fsSL https://raw.githubusercontent.com/eMediquality/konsey/v0.1.0/install.sh | KONSEY_REF=v0.1.0 bash
> ```

**Or clone (if you prefer to read the code first):**
```bash
git clone https://github.com/eMediquality/konsey.git && cd konsey
less install.sh                    # inspect first if you like (no blind curl|bash)
./install.sh                       # venv + deps + DB schema + .env (one command)
./bin/konsey-run "my first task"   # headless full loop
```

> **Works with a single provider too.** If only the Claude CLI is installed, Konsey runs in solo
> mode (`KONSEY_PROVIDERS_MIN=1`, the default). If Codex (`codex`) and Google (`agy`) are present
> they're auto-detected and full cross-validation kicks in.

### Requirements
- Python ≥ 3.12
- At least one agent CLI: [Claude Code](https://claude.com/claude-code) · (opt.) `codex` · (opt.) `agy`
- Dependencies (installed automatically): `langgraph`, `duckdb`

---

## Two run modes

| Mode | Command | When |
|---|---|---|
| **Interactive** | `/konsey <task>` inside Claude Code | Human in the loop; proceeds in chat |
| **Headless** | `./bin/konsey-run "<task>"` | Cron/automation; deterministic LangGraph state machine |

---

## Configuration (`.env` / environment variables)

| Variable | Default | Description |
|---|---|---|
| `KONSEY_SECURITY_LEVEL` | `medium` | `strict` \| `medium` \| `weak` — fluidity ↔ safety |
| `KONSEY_PROVIDERS_MIN` | by level | Min. providers (empty: strict→2, else→1) |
| `KONSEY_TELEMETRY` | `off` | Opt-in anonymous telemetry (`on` to enable; see PRIVACY.md) |
| `KONSEY_USER` | `local` | User label in audit records |
| `KONSEY_DB` | `./council.duckdb` | Audit DB path |
| `KONSEY_A2A_TOKEN` | — | Required token for non-loopback A2A bind |

### Security levels

| | secret | PHI | human approval | providers |
|---|---|---|---|---|
| **strict** | block | block | required for phi/prod | ≥2 |
| **medium** | block | warn | — | ≥1 |
| **weak** | warn | ignore | — | ≥1 |

> **Guardrails are layered + opt-in.** The core engine is unconstrained; PHI/healthcare protection
> only blocks at `strict` (not the default for a global tool). Secret-scanning is the safety floor
> at medium+strict. Your own healthcare/PHI project names: `KONSEY_PHI_PROJECTS` (`.env`).

## Providers — which AI products do you use?

Built-in defaults: **claude** (architect) + **codex** (critic) + **google/agy** (researcher).
To define/add your own:

```bash
cp konsey.providers.example.toml konsey.providers.toml   # edit
./bin/konsey-doctor                                       # what's ready, is auth set?
```

Each provider in `konsey.providers.toml` takes: `enabled`, `role`, `command` (with `{prompt}`/
`{timeout}` placeholders), and `auth_env` if an API key is needed. If the CLI is missing or
`auth_env` is empty, the provider is treated as "unavailable" (gracefully). Konsey runs with the
remaining providers.

**Local models** (Ollama, llama.cpp, LM Studio) are first-class — just another provider entry.
This keeps data **on-device** (ideal for PHI/offline work):
```toml
[providers.ollama]
enabled = true
role = "architect"
command = ["ollama", "run", "llama3.1", "{prompt}"]
```

**`konsey doctor`** shows at a glance whether the install is truly ready:
```
Providers (the AI products you use):
  claude   [architect ] ✓ ready
  codex    [critic    ] ✗ no CLI (codex)
  gemini   [researcher] ✗ missing auth (GEMINI_API_KEY)
```

## Privacy & telemetry
Default **off**. If you opt in, only **anonymous metadata** (feature usage, error codes, version)
is sent — **never task content/PHI/secrets**. Details + opt-out: [PRIVACY.md](./PRIVACY.md).
Backend (ingest + DB + revenue model): [telemetry-backend/](./telemetry-backend/) · [TELEMETRY.md](./TELEMETRY.md).

---

## Memory / Audit (append-only)

```bash
./bin/konsey recent                    # recent sessions
./bin/konsey query "SELECT * FROM council_decisions"   # SELECT only
```
Schema: `schema.sql` · DB: `council.duckdb` (git-ignored, auto-created on first run).
The helper rejects UPDATE/DELETE — records are immutable (auditability).

---

## A2A — optional agent-relationship protocol

Makes the council callable from the outside as an A2A agent. Default **bound to localhost** (safe):

```bash
./bin/konsey-a2a-serve     # 127.0.0.1:8787 · card: /.well-known/agent-card.json
```
Only ≤internal tasks run automatically over A2A; pii/phi/production are rejected.

---

## Connectors (chat platforms)

Drive the council from a chat app — **Telegram, Notion, Slack, and WhatsApp** connectors. All
opt-in + credential-gated, with the **same risk gate on every channel** (phi/production refused).
Telegram & Notion are maintainer-tested; Slack & WhatsApp are code-complete (WhatsApp webhooks are
HMAC-signature-verified). See [CONNECTORS.md](./CONNECTORS.md).

```bash
cp connectors.example.toml connectors.toml   # enable telegram + set TELEGRAM_BOT_TOKEN in .env
./bin/konsey-connectors                       # bot replies with the council's report
```

## Language

English by default; **Turkish when your system locale is `tr`** — so a visitor abroad sees English,
a user in Turkey sees Turkish. Override with `KONSEY_LANG=tr|en`.

---

## Architecture

| Component | File |
|---|---|
| State machine (9 states) | `orchestrator/graph.py` |
| Risk/PII/secret gateway | `orchestrator/gateway.py` |
| Vendor-neutral adapters | `orchestrator/adapters.py` · `adapters/AGENTS.md` |
| Append-only audit | `orchestrator/audit.py` · `schema.sql` |
| Decision logic | `orchestrator/decide.py` |

## Docs
[Architecture](./docs/architecture.md) · [Examples](./examples/) · [Connectors](./CONNECTORS.md) ·
[Privacy](./PRIVACY.md) · [Changelog](./CHANGELOG.md)

## Contributing & Security
See [CONTRIBUTING.md](./CONTRIBUTING.md) · [SECURITY.md](./SECURITY.md). License: [MIT](./LICENSE).
