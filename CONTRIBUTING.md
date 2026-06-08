# Katkı Rehberi

## Geliştirme ortamı

```bash
git clone <repo-url> konsey && cd konsey
./install.sh                 # venv + bağımlılıklar + şema
. .venv/bin/activate
pip install -e ".[dev]"      # ruff + pytest
```

## Çalıştırma / test

```bash
ruff check .                 # lint
pytest                       # testler (tests/)
./bin/konsey-run "deneme"    # uçtan uca headless
```

## İlkeler (Konsey doktrini)

- **Kanıt > konsensüs.** Bir davranış değişikliği test/komut çıktısıyla kanıtlanmalı.
- **Üreten doğrulayamaz.** Kod üreten ajan kendi çıktısını onaylamaz — ayrı doğrulama şart.
- **Append-only audit.** `council_*` tablolarına yalnız INSERT; UPDATE/DELETE yok.
- **Secret asla repoda.** API key/token commit edilmez (`.env` gitignore'lu, `.gitleaks.toml` tarar).
- **Guardrail'ler katmanlı.** Çekirdek kısıtsız; KVKK/PHI/audit opsiyonel ara katman.

## PR kuralları

1. Feature branch aç, küçük ve odaklı tut.
2. `ruff check .` + `pytest` yeşil olmadan PR açma.
3. Davranış değişikliğinde test ekle/güncelle.
4. Secret/kişisel veri sızdırmadığını doğrula (`git diff` + gitleaks).
