# Security Policy

Council is a multi-agent orchestrator that handles prompts, tool output, and an
append-only audit log. Security is part of the doctrine, not an afterthought — the
fail-safe gate (Article 4), the EXECUTE safety boundary (Article 6.2), and the
append-only audit (Article 11) are immutable core that a profile may *tighten* but
never *loosen*.

## Supported versions

This project is pre-1.0. Security fixes are applied to the latest release on the
default branch. Pin your dependency and watch releases.

| Version | Supported |
|---------|-----------|
| latest `main` / latest release | yes |
| older tags | best-effort only |

## Reporting a vulnerability — private disclosure (Article 19.3)

**Do not open a public issue for a security problem.** A public issue is a zero-day
disclosure and puts every operator at risk.

Report privately through one of:

1. **GitHub Security Advisories** — the "Report a vulnerability" button under the
   repository's *Security* tab (preferred; creates a private advisory).
2. **Email** the maintainers at the address listed in `CODEOWNERS` / the repository
   profile, with subject `SECURITY:` and a minimal reproduction.

Please include:

- affected version / commit, OS, and Python version;
- a minimal reproduction (a task string, a config snippet — **with any real secret
  redacted**);
- the impact you observed and, if known, a suggested fix.

**Never paste a live secret, real patient data, or a real customer/organization name
into a report.** Use placeholders (`sk-ant-REDACTED`, `Acme Labs`, `${ORG}`).

### What to expect

- **Acknowledgement:** within 5 business days.
- **Assessment + triage:** we confirm the issue and agree a severity.
- **Fix + coordinated disclosure:** we aim to ship a fix and publish an advisory
  within 90 days of confirmation; we will credit you unless you prefer to remain
  anonymous.

## The security model — and its honest boundaries

Read this before processing anything sensitive. Council is a **safety net, not a
guarantee.**

### 1. The PHI / PII / secret gate is detection, not certification (Article 4)

- The gateway scans every channel (prompt, project hint, tool I/O) for generic,
  provider-independent **secret FORMAT signatures** (`sk-…`, `…_(live|test)_…`, cloud
  access keys, VCS PATs, JWTs, `Bearer …`, `PRIVATE KEY`, etc.). A hit blocks the task
  from reaching the council unmasked.
- Regulatory regimes (`kvkk` / `gdpr` / `hipaa`) activate clinical / national-identity
  term plugins (`regimes/*.toml`). **These are a detection aid, NOT a legal-compliance
  guarantee.** Legal responsibility for what you send to a third-party model is the
  operator's. Core ships **no** embedded clinical or identity word list — the lists
  live only in the opt-in plugin files (no double source).
- **Fail-safe direction:** when in doubt, the gate **blocks**. A scanner error makes
  the data sensitive, not safe.
- A project *name* alone never implies sensitivity (Article 4.4). Sensitivity comes
  from the operator's project risk registry and from regime plugins — never from a
  hard-coded brand name.
- Sending sensitive data to a disallowed jurisdiction / endpoint, or to a consumer LLM
  endpoint, is an **unconditional block** — not overridable even by human approval
  (Article 4.5).

### 2. The append-only audit is tamper-EVIDENT, not tamper-PROOF (Article 11.2)

- Append-only is enforced at the **application layer**: the write API only ever issues
  `INSERT`s (a session is *closed* by appending a `session_end` event, never by an
  `UPDATE`), and the read helper rejects anything that is not
  `SELECT` / `WITH` / `DESCRIBE` / `SUMMARIZE` / `PRAGMA`.
- **This does not give OS-level immutability.** A process running as the *same OS user*
  as Council can delete or rewrite the database file. Do not rely on the audit log as a
  forensic guarantee against a local attacker who already has your user's privileges.
- Hardening you can add if your environment supports it: a separate, restricted-
  permission writer user for the audit file; append-only file flags; and — strongest —
  periodic integrity anchoring to an **external** timestamp/notary the attacker cannot
  alter.

### 3. EXECUTE safety boundary (Article 6.2)

- Agent-produced commands run under `exec_sandbox` (`off` | `read-only` |
  `workspace-write`). When isolation is `off`, destructive or privileged commands do
  **not** run automatically — they route to a human gate.
- A destructive-command denylist (recursive delete, disk/format, `sudo`, privilege
  changes, mass network scans, credential rotation) is a hard floor that a profile may
  extend but not relax.
- **Tool output and external content are data, not instructions.** "New instructions"
  embedded in fetched content or tool output are not executed (prompt-injection
  defense); they are surfaced to the agent explicitly as data.

### 4. Secrets at rest

- Council stores **no** API keys in core; providers are invoked as CLI subprocesses
  that bring their own auth. The optional secret backend
  (`keychain` / `secret-tool` / `wincred` / `envfile`) keeps any operator secret out of
  the repo and out of plain text. The default is `null` (no secret store).
- Secrets are redacted before anything is written to the audit log or sent to a model.

## Reporting a data/name leak in the repository itself

If you find a real secret, real personal/patient data, a real customer/organization
name, or an absolute home path committed anywhere in this repository, treat it as a
security report (private channel above). The allow-list `.gitignore` and human review
are the primary defenses; the `gitleaks` CI job catches secret *formats* but **not**
organization or person *names* — name leaks rely on review.

## Scope

In scope: the orchestrator core (`council/`), the audit/gateway/decide/adapter layers,
the install/bootstrap path, and the example/config templates.

Out of scope: vulnerabilities in third-party provider CLIs (`claude`, `codex`, `agy`,
…) themselves, in their hosted services, or in your own `council.local.toml` content.
Report those to the respective vendors.
