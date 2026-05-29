# Contributing to Council

**English** · [Türkçe (below)](#türkçe)

Thank you for considering a contribution. Council's whole premise is *evidence over
consensus* — so the bar for a change is evidence, not agreement. This guide is short on
purpose; it states what the project will and will not accept.

## The two rules everything follows

1. **Evidence > consensus.** A claim that something "works" is invalid without external
   evidence: a passing test, an exit code, an HTTP status, static-analysis output. A PR
   that says "tested locally, works" without the output attached is not done. Run it;
   paste what the terminal said.
2. **Nothing machine-specific in the repo, ever.** No secrets, no real organization /
   product / person names, no absolute home paths, no live data. Everything concrete is
   a `${variable}` or lives in the git-ignored `council.local.toml` that Bootstrap
   writes. This is enforced by human review + the allow-list `.gitignore`; the
   `gitleaks` CI job catches secret *formats* but **not** names — so review is the real
   gate.

## What a good contribution looks like

- **A new provider** is a roster line plus, at most, one argv shape in
  `adapters.BUILTIN_PROFILES` — **not** a new adapter subclass and **never** an SDK /
  HTTP-key dependency. The dependency contract is *CLI subprocess only* (Article 2.3).
  If you find yourself adding `import requests` / `import openai` to the adapter layer,
  stop — that is out of scope.
- **A new regulatory regime** (clinical / identity term lists, national-ID regexes) is
  **one plugin file** under `regimes/*.toml`, activated by `data_regime`. It does **not**
  go into core, audit, or capture code (no double source, Article 4.3). Ship it with the
  "detection aid, not a compliance guarantee" note.
- **Core changes** keep the single injection point intact: machine-facts flow only
  through `council/config.py` (`Config`, `by_role()`, `verifier(exclude=)`). If your
  change adds a hard-coded brand name, path, project name, or owner identity to a core
  module, it will be rejected.
- **Tests are part of the change, not a follow-up.** The orchestrator that preaches
  evidence-weighted decisions cannot ship untested code (Article 10.3). Add real tests
  with real imports — see `tests/` for the pattern (gateway secret/risk, decide
  ceiling/floor, append-only rejection, adapter graceful degradation, config bootstrap).
  No mock-of-a-mock; a fake-green test is not evidence (Article 10.1).

## The immutable core (a profile may tighten, never loosen)

These articles are not negotiable in a PR — you may make them *stricter*, never
*weaker* (Article 18):

- **Article 2** — evidence > consensus, ≥2 independent providers, CLI-only dependency,
  producer ≠ verifier.
- **Article 4** — the fail-safe PHI / PII / secret gate and its hard endpoint block.
- **Article 5** — human-approval classes and the config-undefeatable gate invariant.
- **Article 6.2** — the EXECUTE safety boundary.
- **Article 7** — the confidence ceiling (`0.6` with no cross-verification) and floor
  (`0.7`).
- **Article 11** — append-only audit + the honest authority-separation boundary.

## Development setup

```bash
git clone <repo> council && cd council
python3 -m venv .venv && . .venv/bin/activate     # Python ≥ 3.12 (the proven version)
pip install -e ".[dev]"                           # ruff, pytest, mypy, build
```

## Before you open a PR — run the gate locally

The same checks run in CI (`.github/workflows/ci.yml` and `secret-scan.yml`):

```bash
ruff check council tests          # lint
mypy council                      # types
pytest -q                         # tests — paste the summary into the PR
```

A merge requires every required check to be **green** (Article 9). A red CI is never
merged; fix the root cause and push one clean run rather than a flurry of retries. On a
"PR-required" repository, do **not** push directly to the default branch.

## Pull-request checklist

The PR template restates this; in short, every PR must confirm:

- [ ] no secret, key, or token (real or look-alive) in the diff or history;
- [ ] no real organization / product / person name; placeholders only (`Acme Labs`,
      `${ORG}`);
- [ ] no absolute home path (`/Users/...`, `/home/...`, `C:\Users\...`);
- [ ] no machine-specific value baked into a core module — it belongs in
      `council.local` or as a `${variable}`;
- [ ] tests added/updated and **their output pasted**;
- [ ] no relaxation of the immutable core (Article 18).

## Reporting security issues

Security problems go through **private** disclosure — see [`SECURITY.md`](./SECURITY.md).
Never open a public issue for a vulnerability.

## License of contributions

- Code is licensed **Apache-2.0**; by contributing code you agree it is released under
  that license (which includes a patent grant).
- The constitution / doctrine text is **CC-BY-4.0**. Doctrine changes are governed by
  the versioning rules in Article 18 (SemVer, mandatory changelog, header-version =
  body-version consistency).

---

<a name="türkçe"></a>

# Konsey'e Katkı (Türkçe)

Katkınız için teşekkürler. Konsey'in tüm tezi *kanıt > konsensüs*'tür — bu yüzden bir
değişikliğin ölçütü anlaşma değil, kanıttır.

## Her şeyin uyduğu iki kural

1. **Kanıt > konsensüs.** "Çalışıyor" iddiası dış kanıt olmadan geçersizdir: geçen test,
   exit code, HTTP durumu, statik analiz çıktısı. "Yerelde test ettim, çalışıyor" diyen
   ama çıktıyı eklemeyen PR tamam değildir. Çalıştırın; terminalin ne dediğini yapıştırın.
2. **Repoda makineye-özel hiçbir şey, asla.** Sır yok, gerçek kurum / ürün / kişi adı yok,
   mutlak ev yolu yok, gerçek veri yok. Tüm somut değerler `${değişken}` veya Bootstrap'in
   yazdığı git-ignored `council.local.toml`'dadır. Bu, insan review + allow-list
   `.gitignore` ile zorlanır; `gitleaks` CI işi sır *formatlarını* yakalar ama *isimleri*
   yakalamaz — gerçek kapı insan incelemesidir.

## İyi bir katkı neye benzer

- **Yeni sağlayıcı** = bir roster satırı + en fazla `adapters.BUILTIN_PROFILES`'ta bir
  argv şekli. Yeni adapter sınıfı **değil**, SDK / HTTP-key bağımlılığı **asla**.
  Bağımlılık sözleşmesi *yalnız CLI subprocess*'tir (Madde 2.3).
- **Yeni düzenleyici rejim** (klinik/kimlik terim listeleri) = `regimes/*.toml` altında
  **tek eklenti dosyası**, `data_regime` ile aktive olur. Çekirdek/audit/capture koduna
  **girmez** (çift-kaynak yasak, Madde 4.3).
- **Çekirdek değişiklikleri** tek enjeksiyon noktasını korur: makine-gerçekleri yalnız
  `council/config.py`'den akar. Bir çekirdek modüle sabit marka/yol/proje/sahip adı
  eklerseniz reddedilir.
- **Testler değişikliğin parçasıdır.** Kanıt-ağırlıklı kararı vaaz eden orkestratör test
  edilmemiş kod yayınlayamaz (Madde 10.3). Gerçek importlarla gerçek testler ekleyin;
  sahte-yeşil kanıt değildir (Madde 10.1).

## Değiştirilemez çekirdek (profil sıkılaştırır, gevşetemez — Madde 18)

Madde 2, Madde 4, Madde 5, Madde 6.2, Madde 7 (tavan 0.6 / floor 0.7), Madde 11 — PR'da
yalnız *sıkılaştırılabilir*, asla zayıflatılamaz.

## Kurulum ve yerel kapı

```bash
python3 -m venv .venv && . .venv/bin/activate     # Python ≥ 3.12
pip install -e ".[dev]"
ruff check council tests && mypy council && pytest -q
```

Merge için tüm zorunlu kontroller **yeşil** olmalı (Madde 9); kırmızı CI ile merge yok.

## Güvenlik

Güvenlik sorunları **özel** bildirim ile — bkz. [`SECURITY.md`](./SECURITY.md). Açık
issue ile zafiyet ifşası yasak.

## Lisans

Kod **Apache-2.0**; doktrin metni **CC-BY-4.0**.
