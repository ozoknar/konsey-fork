# Agent Factory Architecture

The Council project is designed as an **autonomous, proactive, and self-correcting** AI Agent Organization (Agent Factory) to eliminate single-model blind spots and prevent unverified code from reaching production.

This document details how the project's deterministic 9-state LangGraph orchestrator maps directly to factory roles and its core operational principles.

---

## 1. Architectural Roles and Mapping (Roster Mapping)

During Council's workflow, each AI provider (LLM CLI subprocess) assumes a specific role in the agent factory:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            DIRECTOR AGENT                                   │
│            (Preflight Risk Classification & Initial Planning)               │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            COORDINATOR AGENT                                │
│            (LangGraph Orchestrator & State/Budget Management)               │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       ▼
┌──────────────────────────────────────┼──────────────────────────────────────┐
│                                      │                                      │
▼                                      ▼                                      ▼
┌──────────────────────────┐ ┌──────────────────────────┐ ┌───────────────────┐
│        SCOUT AGENT       │ │      BUILDER/CODERS      │ │    QA & SECURITY  │
│   (Node Isolation & Host │ │  (Git Worktree Isolated  │ │   (Verifier:      │
│    Footprint Scanner)    │ │   Execution & Edits)     │ │    Cross-Verify &  │
│                          │ │                          │ │    Execution Gate) │
└──────────────────────────┘ └──────────────────────────┘ └───────────────────┘
```

### A. Director Agent
* **Council Node Mapping:** `preflight` and `plan` (Lead) nodes.
* **Responsibilities:** Classifies the task risk profile (public, internal, sensitive, production) and runs secret/PHI filters. Splits goals into initial parallel drafted plans.

### B. Coordinator Agent (Project Manager / PM)
* **Council Node Mapping:** `Config` dataclass, `presets.py`, and the LangGraph StateGraph (`graph.py`).
* **Responsibilities:** Coordinates the step sequence, parallel execution lines, budgets/timeouts, and data integrity across state transitions.

### C. Scout Agent (Explorer)
* **Council Node Mapping:** `isolation.py` and the `doctor` subcommand.
* **Responsibilities:** Proactively maps dependencies, files, missing assets, and scans host configurations that could leak into the provider nodes.

### D. Builder/Coder Agent
* **Council Node Mapping:** `execute.py` and `worktree.py` (`konsey do` runner).
* **Responsibilities:** Performs code modifications and runs local build/test checks inside a fully yoked, isolated Git worktree branch.

### E. QA & Security Agent
* **Council Node Mapping:** `verify.py`, `decide.py`, and `exec_policy.py`.
* **Responsibilities:** Asserts code quality, filters destructive CLI commands, and manages cross-validation. Ensures the **Producer ≠ Verifier** invariant by choosing a different provider CLI to verify results.

---

## 2. Core Security & Decisions

### A. Producer ≠ Verifier Invariant
* The provider that generates a result (`claude` etc.) can **never** verify it.
* If a machine lacks multiple providers, it degrades to **Advisory Mode**: confidence is capped at `0.6` and outputs are stamped "unverified".

### B. Evidence-Weighted Decisions
Decisions are scored using a deterministic formula based on evidence and consensus:
$$\text{Score} = \text{Base (0.45)} + \text{Cross-Verify Bonus (+0.15)} + \text{Evidence Bonus (+0.05)} - \text{Dissent (-0.10)} - \text{Tool Failure (-0.15)}$$

### C. Node Isolation Enforcement (PR2)
To keep nodes clean from global host configs, environmental wrappers are applied:
* **Google/agy:** Diverts `HOME` to a pristine temporary folder.
* **Claude:** Appends `--strict-mcp-config` and `--setting-sources none` flags.
* **Codex:** Sets `CODEX_HOME` to a temp directory and appends `-c project_doc_max_bytes=0`, `--ignore-user-config`, and `-C`.
