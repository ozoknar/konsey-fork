# Changelog

All notable changes to Konsey. Format loosely follows [Keep a Changelog](https://keepachangelog.com).

## [Unreleased]
### Added
- **Connectors** — messaging-platform integrations (opt-in, config-driven). Telegram implemented
  (Bot API long-poll); Slack/Notion/WhatsApp on the roadmap. See [CONNECTORS.md](./CONNECTORS.md).
- **Local models** — Ollama / llama.cpp / LM Studio as first-class providers (data stays on-device;
  ideal for PHI/offline). See `konsey.providers.example.toml`.
- **i18n** — locale-aware CLI (English default; Turkish when system locale is `tr`). `konsey doctor`
  is bilingual; `KONSEY_LANG` overrides. (`orchestrator/i18n.py`.)
- **Bilingual README** — English-primary `README.md` + Turkish `README.tr.md`.

### Notes / roadmap
- i18n currently covers `konsey doctor`; install.sh prompts, run report, and gateway messages reuse
  the same catalog next.
- Connectors: Slack (Socket Mode), Notion (polling), WhatsApp (Meta Cloud API) to follow Telegram.

## [0.1.0] — 2026-06-09
First publish-ready release.
### Added
- Config-driven providers (claude/codex/google + custom) with role-based selection.
- Security levels: `strict` / `medium` / `weak`.
- Opt-in anonymous telemetry + live ingest backend; PHI/secret never transmitted.
- `konsey doctor`, append-only DuckDB audit, A2A (fail-closed), cross-platform support.
- One-command + version-pinned install, 27 tests, green CI, gitleaks, LICENSE/CONTRIBUTING/SECURITY.
