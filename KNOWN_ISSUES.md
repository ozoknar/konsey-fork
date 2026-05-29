# Known Limitations / Bilinen Sınırlar (Phase 2 backlog)

> Honest scope statement (Constitution Art. 2.1 — no unverified "it works" claims).
> The MVP core is functional and tested (92/92, incl. a fresh Linux Docker install). The items in the
> two sections below are deliberately deferred and must NOT be presented as already-complete; items that
> have since been fixed and verified are moved down to the **Resolved** sections (with their evidence).

## EN

- **node-isolation — Art. 2.6 enforcement deferred to PR2 (detection shipped).** A node
  subprocess (claude/codex/agy) currently inherits the full host environment
  (`adapters.py:_env`) and the host's AI instruction files (`CLAUDE.md`/`AGENTS.md`/
  `GEMINI.md`), settings/hooks and MCP — verified by behavioural probe (`claude -p`
  leaked the host CLAUDE.md persona; `codex debug prompt-input` showed global+repo
  `AGENTS.md` injected). This collapses the cross-provider independence Art. 2.2
  requires. **Shipped (PR1):** detection — `council/isolation.py` + a non-fatal ⚠ in
  `council doctor` + an install-time list in `council init`, plus the Art. 2.6 doctrine.
  **Deferred (PR2):** *enforcement* — isolated argv + env allow-list + clean CWD per
  provider (claude `--strict-mcp-config`/`--setting-sources`; codex isolated
  `CODEX_HOME` + `-c project_doc_max_bytes=0` + `--ignore-user-config` + clean `-C`; agy
  clean HOME, no native flag), default-on with an explicit `--unsafe-inherit-provider-config`
  opt-in, and an audited isolation manifest; plus **repo-bound scope** for the project-config
  parent-walk (the PR1 detector walks cwd to the filesystem root, which can over-detect
  ancestor configs above the repo/`$HOME` — acceptable for a warning, to be tightened to the
  git-repo boundary). Until PR2 lands: do not assume nodes are independent of the host
  machine's AI config.
- **Art. 6.2 EXECUTE sandbox not yet enforced.** `exec_sandbox` exists in `Config` but is
  not wired into an execution path, because this MVP's orchestrator only invokes **provider
  CLIs** (claude/codex/agy) — it does not run arbitrary shell extracted from model output.
  Full Art. 6.2 enforcement (destructive-command denylist, isolation, prompt-injection
  "output-is-data") lands when/if a shell-executing step is added. Until then: do not rely
  on konsey for sandboxing untrusted commands.
- **Audit cfg threading.** `graph.py` audit calls pass `user=cfg.owner` but not the full
  `cfg`; with a *non-default* injected config the audit layer may resolve its DB via
  `load_config()` defaults. The default single-config install is correct; multi-config
  isolation is Phase 2.
- **`run --dry-run` config application.** Dry-run preflight uses gateway defaults; the
  project risk-registry / data-regime from `council.local` are not yet applied to dry-run
  classification (live `run` path applies them).
- **i18n — only prompts externalized so far.** The LLM-facing **prompts** are in `locales/{en,tr}.json`
  (en canonical, tr full mirror, per-key fallback). But **non-prompt UI/diagnostic/report strings**
  (doctor lines, report headers, decision rationale, gateway notes in `graph.py`/`cli.py`/`gateway.py`)
  are still hardcoded **English** — acceptable as the default locale, but full Art. 17 ("no embedded
  prose in core") is not yet met. Note: machine-readable contract tokens (`VERDICT: PASS/FAIL`,
  `DISSENT:`) are intentionally kept English-literal (graph verdict parsing depends on them).
- **Live-daemon scheduler validation (systemd / Windows).** The `cron` scheduler + `Null*`
  fallbacks are validated on Linux (see Resolved). Still **unvalidated against a running
  daemon: systemd user timers and Windows Task Scheduler.** Both backends exist
  (`platform/scheduler.py`) and are reversible via `uninstall()`, but have not been exercised
  with a live timer/scheduled task. Until then, on those OSes prefer the `cron` backend (Linux)
  or run `council dispatch tick` manually.

## TR

- **Madde 6.2 EXECUTE sandbox henüz uygulanmadı.** `exec_sandbox` config'te var ama bir
  yürütme yoluna bağlı değil — bu MVP'nin orkestratörü yalnız **sağlayıcı CLI'larını**
  çağırıyor, model çıktısından çıkarılan rastgele shell komutu çalıştırmıyor. Tam Madde 6.2
  (yıkıcı-komut denylist, izolasyon, prompt-injection) shell-yürüten adım eklenince gelecek.
  O zamana dek: güvenilmez komut sandbox'ı için konsey'e güvenmeyin.
- **Audit cfg geçişi.** `graph.py` audit çağrıları `user=cfg.owner` geçiyor ama tam `cfg`
  geçmiyor; *varsayılan-olmayan* enjekte config'te audit DB'sini `load_config()` varsayılanıyla
  çözebilir. Varsayılan tek-config kurulum doğru; çoklu-config izolasyonu Faz 2.
- **`run --dry-run` config uygulaması.** Dry-run preflight gateway varsayılanlarını kullanır;
  `council.local`'daki proje risk-sicili / veri-rejimi dry-run sınıflandırmasına henüz
  uygulanmıyor (canlı `run` yolu uygular).
- **i18n kataloğu.** `en.json` kanonik; `tr.json` ve tam prompt dışsallaştırması kısmi.
- **Canlı-daemon scheduler doğrulaması (systemd / Windows).** `cron` scheduler + `Null*`
  fallback'leri Linux'ta doğrulandı (bkz. Resolved). **Çalışan bir daemon'a karşı henüz
  doğrulanmadı: systemd kullanıcı timer'ları ve Windows Task Scheduler.** İki backend de
  (`platform/scheduler.py`) mevcut ve `uninstall()` ile geri-alınabilir, ama canlı bir
  timer/scheduled-task ile denenmedi. O zamana dek bu OS'larda `cron` backend'ini (Linux)
  tercih edin ya da `council dispatch tick`'i elle çalıştırın.

## Resolved in Phase 2 (moved out of the backlog above — fixed + verified)

- **Regime term-file fail-open now warns (was Phase 2 in this file).** `council doctor`
  emits a visible `⚠` when a regulated regime (`kvkk` / `gdpr` / `hipaa`) is set but its
  `regimes/*.toml` term file did not load — clinical/identity detection OFF, secret scan
  still on, non-fatal (Art. 4.1). Implemented in `cli._doctor_regime` (wired into
  `cmd_doctor`) + `gateway.regime_loaded`. Verified live: `data_regime='hipaa'` without a
  term file yields the warning; `standard` adds nothing.
- **Linux scheduler / fallback layer validated.** The `cron` scheduler + `Null*` backends
  are validated on Linux via a fresh-install Docker audit (`python:3.12-slim`: install →
  init → doctor → run + cron install/uninstall round-trip + pytest 92/92, all green;
  macOS-only backends called on Linux returned None/False without raising). (Live
  systemd/Windows daemons remain open above.)
- **`doctor` advisory-mode visibility.** `doctor` now warns when 0 providers are runnable
  (CANNOT run) and when fewer than 2 are runnable (advisory mode, no cross-validation).

## Resolved in the MVP audit round (cross-provider council found, fixed + verified)

- **SHOWSTOPPER:** `adapters.adapter_for` was missing → `council run` crashed (Google caught
  it; a Claude integration agent's "91/91, works end-to-end" had hidden it because the import
  is lazy and `doctor` swallowed the error). Fixed: `adapter_for(cfg, name)` added; `capture.py`
  switched to it; `doctor` now reports the import as a CRITICAL failure instead of masking it.
- **Art. 7.1 violation:** low confidence escalated *all* risks to human; now public/internal
  complete autonomously (advisory), only **pii / sensitive / production** escalate. (Canonical
  class is "sensitive" — what the gateway emits; "phi" kept as a defensive alias.)
- **Risk-vocabulary mismatch (cross-provider catch):** `decide.py` and `capture.py`'s gate
  checked `"phi"` while `gateway.py` emits `"sensitive"` → sensitive decisions weren't escalated
  and sensitive sessions weren't gated. Both realigned to "sensitive" (+phi alias). Tests assert
  the canonical class. pytest 92/92 (incl. fresh Docker-Linux install audit).
