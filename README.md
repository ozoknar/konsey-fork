# Konsey 🏛

**Çok-ajanlı, kanıt-ağırlıklı orkestrasyon düzeni.** Konsensüs değil **kanıt** karar verir.

Konsey; Claude, Codex ve Google düğümlerini bağımsız çalıştırır, planları çapraz-eleştirir,
çıktıyı **üreten-doğrulayamaz** kuralıyla doğrular ve her adımı append-only bir audit DB'sine
yazar. Tek bir LLM'in "öyle dedi" güveni yerine, bağımsız sağlayıcıların dış kanıtla
doğrulanmış kararını verir.

```
PREFLIGHT → PLAN → CRITIQUE → SYNTHESIZE → EXECUTE → VERIFY → DECIDE → REPORT → MEMORY
```

---

## Hızlı başlangıç

```bash
git clone <repo-url> konsey && cd konsey
./install.sh                       # venv + bağımlılıklar + audit DB şeması (tek komut)
cp .env.example .env               # opsiyonel — varsayılanlar makul
./bin/konsey-run "ilk görevim"     # headless tam döngü
```

> **Tek sağlayıcıyla da çalışır.** Sadece Claude CLI kuruluysa konsey solo modda yürür
> (`KONSEY_PROVIDERS_MIN=1`, varsayılan). Codex (`codex`) ve Google (`agy`) kuruluysa
> otomatik algılanır ve tam çapraz-doğrulama devreye girer.

### Gereksinimler
- Python ≥ 3.12
- En az bir ajan CLI'ı: [Claude Code](https://claude.com/claude-code) · (ops.) `codex` · (ops.) `agy`
- Bağımlılıklar (otomatik kurulur): `langgraph`, `duckdb`

---

## İki çalıştırma modu

| Mod | Komut | Ne zaman |
|---|---|---|
| **İnteraktif** | Claude Code içinde `/konsey <görev>` | İnsan başında; sohbette ilerler |
| **Headless** | `./bin/konsey-run "<görev>"` | Cron/otomasyon; deterministik LangGraph state machine |

---

## Yapılandırma (`.env` / ortam değişkenleri)

| Değişken | Varsayılan | Açıklama |
|---|---|---|
| `KONSEY_PROVIDERS_MIN` | `1` | Çalışmak için gereken min. bağımsız sağlayıcı (sıkı mod: `2`) |
| `KONSEY_USER` | `local` | Audit kayıtlarındaki kullanıcı etiketi |
| `KONSEY_DB` | `./council.duckdb` | Audit DB yolu |

> **Guardrail'ler katmanlıdır.** Çekirdek motor kısıtsızdır; KVKK/PHI taraması, secret-scan ve
> audit opsiyonel ara katmandır (`orchestrator/gateway.py`). Sağlık/regülasyon kullanımında
> "sıkı" preset (PHI bloklama + audit + ≥2 sağlayıcı + insan onayı) açılır.

---

## Hafıza / Audit (append-only)

```bash
./bin/konsey recent                    # son oturumlar
./bin/konsey query "SELECT * FROM council_decisions"   # yalnız SELECT
```
Şema: `schema.sql` · DB: `council.duckdb` (git dışı, ilk çalıştırmada otomatik kurulur).
Helper UPDATE/DELETE reddeder — kayıtlar değişmez (denetlenebilirlik).

---

## A2A — opsiyonel ajan-ilişkisi protokolü

Konseyi dışarıdan çağrılabilir bir A2A agent'ı yapar. Varsayılan **localhost'a bağlı** (güvenli):

```bash
./bin/konsey-a2a-serve     # 127.0.0.1:8787 · kart: /.well-known/agent-card.json
```
A2A üstünden yalnız ≤internal görevler otomatik çalışır; pii/phi/production reddedilir.

---

## Mimari

| Bileşen | Dosya |
|---|---|
| State machine (9 durum) | `orchestrator/graph.py` |
| Risk/PII/secret gateway | `orchestrator/gateway.py` |
| Vendor-neutral adapter'lar | `orchestrator/adapters.py` · `adapters/AGENTS.md` |
| Append-only audit | `orchestrator/audit.py` · `schema.sql` |
| Karar mantığı | `orchestrator/decide.py` |

## Katkı & Güvenlik
Bkz. [CONTRIBUTING.md](./CONTRIBUTING.md) · [SECURITY.md](./SECURITY.md). Lisans: [MIT](./LICENSE).
