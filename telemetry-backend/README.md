# Konsey Telemetri Backend (referans MVP)

Opt-in istemcinin (`orchestrator/telemetry.py`) gönderdiği **anonim metadata**'yı alır,
doğrular, `install_id`'yi tuzlu-hash'ler ve append-only `events` tablosuna yazar.

> Bağımlılık: yalnız `duckdb` (ana projeyle paylaşılır). Stdlib HTTP sunucu.
> Üretim: TLS, rate-limit, managed DB ve gerçek `KONSEY_TELEMETRY_SALT` şart.

## Çalıştır
```bash
# proje venv'i ile
KONSEY_TELEMETRY_SALT="güçlü-gizli-değer" \
  .venv/bin/python telemetry-backend/server.py 127.0.0.1 8900
```

## Uçnoktalar
| Method | Yol | Açıklama |
|---|---|---|
| POST | `/v1/events` | Tek olay yaz (allowlist doğrulanır) → 204 |
| GET  | `/v1/stats` | Agregat: toplam olay, tekil kurulum, sürüm/seviye dağılımı |
| GET  | `/health` | `{status: ok}` |

## İstemciyi bağla
```bash
# kullanıcı .env'inde:
KONSEY_TELEMETRY=on
KONSEY_TELEMETRY_ENDPOINT=http://127.0.0.1:8900/v1/events
```

## Gizlilik
- `install_id` ham saklanmaz → `sha256(salt + id)[:32]`.
- Yalnız allowlist alanlar kolon olarak saklanır; görev içeriği/PHI/secret **şema dışı**.
- Saklama/silme politikası + gerçek tuz üretimde uygulanmalı (bkz. ../TELEMETRY.md).
