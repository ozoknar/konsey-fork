# Changelog

All notable changes to Konsey. Format loosely follows [Keep a Changelog](https://keepachangelog.com).

## [Unreleased]
### Added
- **Connectors** — messaging-platform integrations (opt-in, config-driven). **Telegram** (Bot API
  long-poll) and **Notion** (DB polling → comment reply) implemented; Slack/WhatsApp roadmap.
  Same risk gate on every channel. See [CONNECTORS.md](./CONNECTORS.md).
- **Local models** — Ollama / llama.cpp / LM Studio as first-class providers (data stays on-device;
  ideal for PHI/offline). See `konsey.providers.example.toml`.
- **i18n** — locale-aware CLI (English default; Turkish when system locale is `tr`; `KONSEY_LANG`
  overrides). Covers `konsey doctor`, `install.sh` prompts, and the run report.
- **Bilingual README** — English-primary `README.md` + Turkish `README.tr.md`.
- **docs/architecture.md** — full system overview (states, providers, gate, audit, surfaces).
- **examples/** — copy-pasteable walkthroughs.

### Notes / roadmap
- i18n: gateway/A2A rejection messages reuse the same catalog next.
- Connectors: Slack (Socket Mode, needs `slack_sdk`), WhatsApp (Meta Cloud API + webhook) to follow.

## [0.1.0] — 2026-06-09
First publish-ready release.
### Added
- Config-driven providers (claude/codex/google + custom) with role-based selection.
- Security levels: `strict` / `medium` / `weak`.
- Opt-in anonymous telemetry + live ingest backend; PHI/secret never transmitted.
- `konsey doctor`, append-only DuckDB audit, A2A (fail-closed), cross-platform support.
- One-command + version-pinned install, 27 tests, green CI, gitleaks, LICENSE/CONTRIBUTING/SECURITY.
