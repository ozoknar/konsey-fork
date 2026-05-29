# The Council Constitution

The portable doctrine that the orchestrator enforces. Version **7.1.0** (portable
core). Doctrine text is licensed **CC-BY-4.0** (the reference implementation code is
Apache-2.0, separately — see the repository root `LICENSE`).

> **Where the full text lives.** The shipped canonical doctrine is **this summary**
> until the English `COUNCIL_CONSTITUTION.md` (+ `.tr.md` mirror) lands (Phase 2,
> below). The full Turkish working draft is intentionally kept out of the repo: the
> filename `KONSEY_ANAYASASI.md` is `.gitignore`d so that a machine-specific *live*
> constitution of the same name can never leak into this OSS tree.

## What it is

Council is a multi-agent, evidence-weighted, vendor-independent work doctrine. The
constitution is the immutable rule set; all machine-facts (owner, org, paths, agent
roster, project risk registry, data regime) come from a git-ignored `council.local`
profile — never embedded in the doctrine text.

## Summary of the binding articles

- **Article 0 — Bootstrap:** `council init` auto-detects the environment and writes
  `council.local`; no core file is hand-edited.
- **Article 2 — Core principles (immutable):** evidence over consensus; at least two
  independent providers; the producer of a claim is never its sole verifier;
  reversibility (no direct production writes).
- **Article 2.6 — Node execution isolation (immutable, new in v7.1.0):** a node must
  run its provider CLI *isolated* from the host machine's own AI config (`CLAUDE.md` /
  `AGENTS.md` / `GEMINI.md`, settings/hooks, MCP); otherwise one machine's
  instructions leak into every provider at once and collapse the cross-provider
  independence Article 2.2 requires. Full environment inheritance is forbidden;
  inheriting host config is an explicit, trust-lowering opt-in; `council doctor` must
  prove non-leakage with evidence. *Status: detection shipped; enforcement in
  progress — see `KNOWN_ISSUES.md` (node-isolation).*
- **Article 3 — Roles & roster:** generic roles (Lead / Critic / Researcher /
  Verifier) assigned to providers at run time; with a single agent it runs in
  *advisory mode* (confidence capped, output marked "unverified").
- **Article 4 — Fail-safe gate (PHI / PII / secret):** highest priority; when in
  doubt, block. Generic secret-pattern scanning is in core; regulatory regimes
  (kvkk/gdpr/hipaa) are opt-in plugins — a detection aid, NOT a compliance guarantee.
- **Article 7 — Evidence-weighted decision:** decisions are scored on
  cross-verification and evidence, not a majority vote; sensitive/production/
  low-confidence escalates to a human.
- **Article 10 — Append-only audit:** every message, evidence item, decision, and
  dissent is written INSERT-only to a local DuckDB store.

> **Full EN translation: TODO Phase 2.** The English canonical
> `COUNCIL_CONSTITUTION.md` (and `COUNCIL_CONSTITUTION.tr.md` mirror) plus annexes
> A–F will be added then. This summary is informative, not authoritative.
