# Architecture

Konsey is a small, vendor-neutral orchestration core plus opt-in layers. Everything is
config-driven and fails gracefully when a piece is missing.

## The 9-state loop (`orchestrator/graph.py`)

```
PREFLIGHT → PLAN → CRITIQUE → SYNTHESIZE → EXECUTE → VERIFY → DECIDE → REPORT → MEMORY
```

A LangGraph state machine. Each node returns a partial state update; the graph is compiled
once via `build()` and run with `invoke({task, project_hint})`.

| State | Role |
|---|---|
| **PREFLIGHT** | Risk classification + secret/PII scan (gateway); budget; provider count check |
| **PLAN** | Every available provider produces an independent plan |
| **CRITIQUE** | A critic provider adversarially attacks the plans (dissent recorded) |
| **SYNTHESIZE** | The lead merges plans + critique into one joint plan |
| **EXECUTE** | The lead produces the final output |
| **VERIFY** | A *different* provider validates — **producer cannot verify** (cross-validation) |
| **DECIDE** | Evidence-weighted decision; confidence; human-required flag |
| **REPORT** | Human-readable report (i18n) |
| **MEMORY** | Append-only audit close + opt-in telemetry |

Kill switches: wall-time, budget, `tool_failure_streak ≥ 3` (`_killcheck`). Failed VERIFY
returns to EXECUTE (max 2 retries) then proceeds to DECIDE.

## Providers — vendor-neutral adapters (`orchestrator/adapters.py`)

Providers are defined in `konsey.providers.toml` (or built-in defaults). Each is a command
template with `{prompt}`/`{timeout}` placeholders. Selection is **role-based**: `pick(role)`
returns an available provider for `architect` / `critic` / `researcher`. Missing CLI or missing
`auth_env` → "unavailable" (no crash). Local models (Ollama, etc.) are just another entry.

## Risk gate (`orchestrator/gateway.py`)

`preflight(task)` classifies risk (`public/internal/pii/phi/production`) and scans for secrets +
PII. Behaviour depends on `KONSEY_SECURITY_LEVEL`:
- **strict**: block secret + PHI, require human approval for phi/production, ≥2 providers.
- **medium** (default): block secret, warn on PHI.
- **weak**: warn only.

The same gate guards the CLI, A2A, and every connector — so PHI/production never leaks out an
autonomous channel.

## Audit (`orchestrator/audit.py` + `schema.sql`)

Append-only DuckDB. Sessions, messages, evidence, decisions, dissent, incidents. UPDATE/DELETE
are rejected (immutability = auditability). Cross-process safe via bounded retry on lock.

## Surfaces

| Surface | Entry | Notes |
|---|---|---|
| Interactive | `/konsey` in Claude Code | human in the loop |
| Headless | `bin/konsey-run` → `orchestrator/run.py` | deterministic, cron-friendly |
| Doctor | `bin/konsey-doctor` → `orchestrator/doctor.py` | setup/provider/auth status (i18n) |
| A2A | `bin/konsey-a2a-serve` → `orchestrator/a2a_server.py` | loopback default, fail-closed |
| Dispatch bridge | `bin/konsey-tick` → `orchestrator/dispatch.py` | inbox→outbox, scheduled jobs |
| Connectors | `bin/konsey-connectors` → `connectors/` | Telegram, Notion (opt-in) |
| Dashboard | `bin/konsey-dashboard` → `orchestrator/dashboard.py` | read-only HTML |

## Opt-in layers (off by default)

- **Telemetry** (`orchestrator/telemetry.py`): anonymous metadata only; never task content.
- **i18n** (`orchestrator/i18n.py`): English default; Turkish when locale is `tr`.
- **Connectors** (`connectors/`): chat-platform bridges; each gated by `auth_env`.

## Failure model

Adapters never raise on a missing CLI/timeout — they return `ok=False` (counted as a tool
failure). Telemetry/notification failures are swallowed. The headless report surfaces gateway
blocks, kill-switch reasons, and the session id so failures are diagnosable.
