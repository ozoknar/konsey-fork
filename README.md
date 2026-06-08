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

**Tek komut (uzak):**
```bash
curl -fsSL https://raw.githubusercontent.com/<ORG>/konsey/main/install.sh | bash
```
Kurulum sırasında **güvenlik seviyesi** ve **opt-in telemetri** sorulur (ikisi de varsayılan-güvenli).

**Veya klonla:**
```bash
git clone <repo-url> konsey && cd konsey
./install.sh                       # venv + bağımlılıklar + DB şeması + .env (tek komut)
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
| `KONSEY_SECURITY_LEVEL` | `medium` | `strict` \| `medium` \| `weak` — akışkanlık ↔ güvenlik |
| `KONSEY_PROVIDERS_MIN` | seviyeden | Min. sağlayıcı (boşsa: strict→2, diğer→1) |
| `KONSEY_TELEMETRY` | `off` | Opt-in anonim telemetri (`on` ile açılır; bkz. PRIVACY.md) |
| `KONSEY_USER` | `local` | Audit kayıtlarındaki kullanıcı etiketi |
| `KONSEY_DB` | `./council.duckdb` | Audit DB yolu |
| `KONSEY_A2A_TOKEN` | — | Loopback dışı A2A bind için zorunlu token |

### Güvenlik seviyeleri

| | secret | PHI | insan onayı | sağlayıcı |
|---|---|---|---|---|
| **strict** | blok | blok | phi/prod zorunlu | ≥2 |
| **medium** | blok | uyarı | — | ≥1 |
| **weak** | uyarı | yok say | — | ≥1 |

> **Guardrail'ler katmanlı + opt-in.** Çekirdek motor kısıtsızdır; PHI/sağlık koruması yalnız
> `strict`'te bloklar (global araç için varsayılan değil). Secret-scan medium+strict'te güvenlik
> tabanıdır. Kendi sağlık/PHI proje adlarınız: `KONSEY_PHI_PROJECTS` (`.env`).

## Sağlayıcılar — hangi YZ ürünlerini kullanıyorsunuz
Yerleşik varsayılan: **claude** (architect) + **codex** (critic) + **google/agy** (researcher).
Kendi ürünlerinizi tanımlamak / eklemek için:

```bash
cp konsey.providers.example.toml konsey.providers.toml   # düzenleyin
./bin/konsey-doctor                                       # ne hazır, auth tamam mı?
```

`konsey.providers.toml` her sağlayıcı için: `enabled`, `role`, `command` (`{prompt}`/`{timeout}`
yer tutucu) ve API-key gerekiyorsa `auth_env`. CLI yoksa veya `auth_env` boşsa sağlayıcı
otomatik "kullanılamaz" sayılır (graceful). Konsey kalan sağlayıcılarla yürür.

**`konsey doctor` çıktısı** kurulumun gerçekten hazır olduğunu tek bakışta gösterir:
```
Sağlayıcılar (kullandığınız YZ ürünleri):
  claude   [architect ] ✓ hazır
  codex    [critic    ] ✗ CLI yok (codex)
  gemini   [researcher] ✗ auth eksik (GEMINI_API_KEY)
```

## Gizlilik & telemetri
Varsayılan **kapalı**. Opt-in açarsanız yalnız **anonim metadata** (özellik kullanımı, hata
kodu, sürüm) gönderilir — **asla görev içeriği/PHI/secret**. Detay + opt-out: [PRIVACY.md](./PRIVACY.md).
Backend (ingest + DB + gelir modeli): [telemetry-backend/](./telemetry-backend/) · [TELEMETRY.md](./TELEMETRY.md).

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
