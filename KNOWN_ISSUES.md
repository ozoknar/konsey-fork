# Known Limitations / Bilinen Sınırlar (Phase 2 backlog)

> Honest scope statement (Constitution Art. 2.1 — no unverified "it works" claims).
> The MVP core is functional and tested (92/92, incl. a fresh Linux Docker install); the items below are deliberately
> deferred to Phase 2 and must NOT be presented as already-complete.

## EN

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
- **i18n catalog coverage.** `locales/en.json` is canonical; `tr.json` and full prompt
  externalization are partial — some strings remain English-default.
- **Linux/Windows OS layers** (`platform/scheduler`, `secrets`): the **cron scheduler + Null\*
  fallbacks are now validated on Linux** (Docker `python:3.12-slim` fresh-install audit:
  install → init → doctor → run + cron install/uninstall round-trip + pytest 92/92, all green;
  macOS backends called on Linux returned None/False without raising). Still unvalidated with a
  live daemon: **systemd-timer / Windows Task Scheduler**.
- **Regime term-file presence (fail-open edge).** The secret scan is always on (verified:
  sk-ant / AKIA blocked under `standard`). But clinical/identity detection needs the regime
  *term file* (`regimes/*.toml`) installed — setting `data_regime=hipaa` WITHOUT the term file
  silently yields no clinical detection. `council doctor` should warn when a regulated regime is
  set but no term file loads (Phase 2). Generic tools ship example terms only; the operator
  activates them — by design, but the missing-file case must warn, not fail-open silently.

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
- **Linux/Windows OS katmanları** soyutlandı ama yalnız macOS yolu test-edildi; systemd/schtasks
  doğrulanacak iskeletler.

## Resolved this round (cross-provider council found, fixed + verified)

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
