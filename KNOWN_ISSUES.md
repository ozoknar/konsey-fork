# Known Limitations / Bilinen Sınırlar (Phase 2 backlog)

> Honest scope statement (Constitution Art. 2.1 — no unverified "it works" claims).
> Maturity: **alpha** (v0.1.0; Phase 0+1 complete, Phase 2 in progress). The core is
> functional and tested (run `python -m pytest` for the live count — 361 as of this
> writing; the original v0.1.0 audit was 92/92, incl. a fresh Linux Docker install). The items in the
> two sections below are deliberately deferred and must NOT be presented as already-complete; items that
> have since been fixed and verified are moved down to the **Resolved** sections (with their evidence).

## EN

- **Installer UX (S3) — no live end-to-end clean-install CI job yet.** The UX kit +
  crash-resistance traps are proven by `KONSEY_UI_SELFTEST` (capability matrix + failure
  box), `sh -n`/`dash -n`, a `shellcheck -s sh` CI job, and a manual real non-TTY
  `./install.sh --no-init` (exit 0 with the summary box). What is NOT yet automated: a
  Docker clean-box install (Debian slim + python3.12, non-TTY) and a **pseudo-TTY** run
  (`script -qec`) that would exercise the live spinner/animation path end-to-end and prove
  "always completes" on a pristine machine. The spinner/`\r` animation itself is therefore
  only manually verified on a TTY; the non-TTY/plain path is unit-tested. Sub-second
  `sleep 0.1` is probed once and falls back to `sleep 1` where unsupported (coarser
  animation, never a failure).
- **De-domestication — starter packs/locales are EXEMPLARS, and the brand is still split.**
  The regime mechanism is fully open (any `regimes/<name>.toml` activates), but the 7 shipped
  packs carry ILLUSTRATIVE terms + national-ID regexes and an explicit "detection aid, NOT a
  compliance guarantee" disclaimer — operators must replace them with their jurisdiction's
  authoritative lists; konsey never implies legal coverage. The 4 starter locales (es/fr/de/ar)
  are PARTIAL (a curated subset; the rest falls back to English per-key) — full translations +
  more languages come via the same drop-in mechanism (a `CONTRIBUTING-i18n.md`/scaffold + an
  entry_points plugin tier are follow-ups). RTL (ar) is "catalog-supported, terminal rendering
  best-effort" — no full UAX#9 BiDi promise. The single-name brand flip (`konsey` canonical,
  `council` deprecated alias) + PyPI/Homebrew distribution + the installer TUI + richer
  onboarding presets are the next stages of the world-class re-evaluation, not done here.
- **`council do` (Faz 3a) — single-provider, council_home-only, headless-edit caveat.** The
  real-work executor is the smallest safe slice: ONE provider, NO fan-out (3b), NOT wired
  into the always-on `council run` graph (3c), and it runs ONLY against `cfg.council_home`
  (arbitrary `--repo` is deferred — widens the production-write surface). Containment carries
  repair.py's honest limit: `worktree.changed_files` only sees IN-worktree git changes, so a
  worker writing outside the worktree is NOT in the WorkResult — the provider sandbox +
  cwd-pin are the real containment, `gate_paths` is defense-in-depth. Observed in the Faz 2
  smoke: a headless `claude -p --permission-mode acceptEdits` may NOT actually apply a file
  edit, so a verified pass is required before anything is kept and an UNVERIFIED result is
  simply discarded — efficacy (does the agent reliably do the task) is a separate tuning
  matter from the (proven) safety/containment. Merge is NEVER automatic: a verified result
  is left on `konsey/do/<sid>/<provider>` for you to review and merge/PR.
- **AI repair (`doctor --fix`) — path-scope is detection, not prevention.** The repair
  worker runs tool-ON (claude acceptEdits / codex workspace-write / agy
  `--dangerously-skip-permissions`) cwd-pinned to the repo; providers cannot finely scope
  per-file. **The real containment is the provider sandbox** (codex `workspace-write` /
  claude `acceptEdits` within `--add-dir` / agy `--sandbox`) + the cwd-pin — NOT the
  post-run `gate_paths` check, which runs over `git status` and therefore only sees
  IN-repo changes: a worker that writes `/tmp/x` or `~/.zshrc` is NOT detected by it (git
  reports nothing outside the repo). `gate_paths` mainly catches an in-repo symlink whose
  target resolves out, and even then can only refuse to continue + raise an incident — it
  **cannot un-write** an already-edited file. Pre-run guards (default-OFF two-key opt-in,
  cwd-pin, `exec_policy` hard-floor on the worker argv) reduce but do not eliminate this. agy is the
  least-scopable provider and is the last-resort pick. A real tool-ON run is exercised only
  via the opt-in `KONSEY_LIVE_REPAIR` smoke; unit tests use an injected runner. Do not run
  `--fix` against a repo holding uncommitted work you cannot afford to lose (it refuses on a
  dirty tree unless `--force`).
- **node-isolation — detection (PR1) AND enforcement argv/env (PR2) are shipped; full
  behavioural cross-surface smoke is the remaining open item.** A node subprocess
  inherits the host environment by default unless isolated. **Shipped (PR1):** detection —
  `council/isolation.py` + a non-fatal ⚠ in `council doctor` + an install-time list in
  `council init`, plus the Art. 2.6 doctrine. **Shipped (PR2):** *enforcement* — the
  isolation argv/env is now INJECTED in `adapters.py:GenericCLIAdapter._argv`/`_env`
  (claude `--strict-mcp-config --setting-sources none`; codex `--ignore-user-config`
  + `-c project_doc_max_bytes=0` + isolated `CODEX_HOME`/`-C`; google/agy HOME-only, as
  it has no native config-suppression flag), default-ON with an explicit
  `unsafe_inherit_provider_config` opt-OUT. The flag injection is asserted by
  `tests/test_adapters_isolation.py` (and a regression guard in `tests/test_s8_honesty.py`
  keeps the docs from drifting back to "deferred"). **Still open:** (a) a *behavioural*
  cross-surface smoke proving each provider CLI fully suppresses every host-config surface
  (the argv is verified to be injected; per-CLI efficacy is the CLI's flag semantics and is
  not yet end-to-end proven for all surfaces); (b) **repo-bound scope** for the
  project-config parent-walk (the detector walks cwd to the filesystem root, which can
  over-detect ancestor configs above the repo/`$HOME` — acceptable for a warning, to be
  tightened to the git-repo boundary). The doctor leak *detector* is independent of the
  per-call argv suppression: it reports that host config FILES exist, not that they WILL
  leak through an isolated node.
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
- **i18n kataloğu.** `en.json` kanonik; `tr.json` ve tam prompt dışsallaştırması kısmi.
- **Canlı-daemon scheduler doğrulaması (systemd / Windows).** `cron` scheduler + `Null*`
  fallback'leri Linux'ta doğrulandı (bkz. Resolved). **Çalışan bir daemon'a karşı henüz
  doğrulanmadı: systemd kullanıcı timer'ları ve Windows Task Scheduler.** İki backend de
  (`platform/scheduler.py`) mevcut ve `uninstall()` ile geri-alınabilir, ama canlı bir
  timer/scheduled-task ile denenmedi. O zamana dek bu OS'larda `cron` backend'ini (Linux)
  tercih edin ya da `council dispatch tick`'i elle çalıştırın.

## Resolved in Phase 2 (moved out of the backlog above — fixed + verified)

- **`providers_ok` mis-counted cross-provider quorum (was: "only claude completes, codex+agy
  time out").** Symptom: three consecutive runs all reported `providers_ok=1` and a "claude
  (1 tamam)" node line, making the 3-agent quorum look unreachable. **Root cause — NOT a
  timeout/auth/isolation failure.** The audited evidence proved codex *and* agy/google both
  ran to success (`ok=true`, codex 5–41s, google 9–19s, all well under the effective 360s
  per-call deadline in `graph._ask`). The bug was purely a counter: `graph.plan()` set
  `providers_ok` to the number of *leads that produced a plan* in the single PLAN node, so a
  one-lead roster (claude lead, codex critic, agy verifier) was structurally capped at 1 even
  when the critic and verifier both contributed. Fix: `graph._distinct_providers_ok(s)` now
  counts the DISTINCT providers with a successful `terminal_exit` evidence row across the whole
  run; `decide_node` uses it for `n_providers_ok`/`agreement` and writes it back into state,
  and the report node lists every participating provider. Verified live: `konsey run` →
  `providers_ok=3`, node line "claude, codex, google (3 tamam)", confidence 0.75→0.85.
  Regression: `tests/test_graph_orchestration.py` asserts `providers_ok == 3` on the full roster.

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
- **`run --dry-run` now applies the profile (was Phase 2 in this file).** Dry-run
  preflight passes the loaded `cfg` to `gateway.preflight`, so the project risk-registry /
  data-regime from `council.local` are applied to dry-run classification, matching the live
  `run` path (`cli.py` `cmd_run` dry-run branch).

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
