# Examples

Short, copy-pasteable walkthroughs. All assume you've run `./install.sh`.

## 1. First headless run
```bash
./bin/konsey-run "Compare two database choices for an append-only audit log: DuckDB vs SQLite. One paragraph, with reasoning."
```
You get a report with the council's cross-validated answer, plus a session id you can inspect:
```bash
./bin/konsey recent
./bin/konsey query "SELECT topic, risk_profile, status FROM council_sessions ORDER BY started_at DESC LIMIT 5"
```

## 2. Check what's ready
```bash
./bin/konsey-doctor      # which providers are installed + authed, security level, telemetry
```

## 3. Use a local model only (offline / privacy)
```bash
cp konsey.providers.example.toml konsey.providers.toml
# set [providers.ollama] enabled = true, disable claude/codex/google
ollama pull llama3.1
./bin/konsey-run "Summarize the tradeoffs of optimistic vs pessimistic locking."
```
Nothing leaves your machine.

## 4. Drive the council from Telegram
```bash
cp connectors.example.toml connectors.toml          # enable telegram
echo 'TELEGRAM_BOT_TOKEN=123:ABC...' >> .env         # from @BotFather
./bin/konsey-connectors
# message your bot a task; it replies with the council's report
```

## 5. Strict mode for sensitive work
```bash
KONSEY_SECURITY_LEVEL=strict ./bin/konsey-run "Review this patient's MRI report"
# → refused automatically: PHI is blocked at strict level, human approval required
```

See [../docs/architecture.md](../docs/architecture.md) for how it all fits together.
