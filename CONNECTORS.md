# Connectors — Messaging Platform Integrations

Connectors let you drive the council from a chat platform (Telegram, Slack, …). Each connector
is **opt-in + config-driven** (just like providers): it stays disabled until you supply credentials.

**Flow:** platform message → `run_council()` → **risk gate (`preflight`)** → if `≤internal` runs the
council and replies; if `phi/production/secret` it is **not** run automatically — the user is told
human approval is required. The same gate that protects the CLI protects every channel.

## Status

| Platform | Status | Mechanism | Difficulty |
|---|---|---|---|
| **Telegram** | ✅ implemented | Bot API `getUpdates` long-poll | easiest |
| **Notion** | ✅ implemented | REST polling a database → comment reply | medium |
| **Slack** | ✅ implemented¹ | Socket Mode (no public URL); needs `pip install slack_sdk` | medium |
| **WhatsApp** | ✅ implemented¹ | Meta Cloud API webhook (stdlib server) | hardest |

¹ Code complete; **not yet live-tested by the maintainer** — Slack needs a Slack app + `slack_sdk`,
WhatsApp needs a Meta Business account + public HTTPS webhook. They run gracefully (opt-in, no creds → no-op).

## Setup

```bash
cp connectors.example.toml connectors.toml      # edit: enabled=true
```

### Telegram (works today)
1. Talk to [@BotFather](https://t.me/BotFather) → `/newbot` → copy the bot token.
2. In `.env`: `TELEGRAM_BOT_TOKEN=123456:ABC...`
3. In `connectors.toml`: `[connectors.telegram] enabled = true` (optionally `allowed_chats = ["<your-chat-id>"]`).
4. Run the connector:
   ```bash
   ./bin/konsey-connectors          # long-polls Telegram; message the bot a task
   ```
   Send the bot a message → it replies with the council's report. `phi/production` tasks are
   refused automatically (human approval required).

> Keep it running under a process manager (systemd/launchd/`tmux`) for always-on operation.

## Adding a connector (architecture)

A connector is a thin adapter; the council graph is never touched directly:
- `connectors/base.py` — `run_council(task)` (gate + council → reply text).
- `connectors/config.py` — loads `connectors.toml` (`enabled` + `auth_env`).
- `connectors/<platform>.py` — poll inbound → `run_council` → send reply.
- `connectors/__main__.py` — runs the enabled connector (`python -m connectors`).

For Slack/Notion/WhatsApp, copy `telegram.py`'s shape: read credentials from the `auth_env`,
poll/receive a message, call `run_council`, post the reply. Each must stay graceful (no creds → no-op).
