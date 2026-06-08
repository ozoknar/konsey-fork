# KONSEY MİMARİSİ — GENEL (TAŞINABİLİR) ANAYASA

> **Sürüm:** 2.0.0 (portable) · **Taban:** v1.0.0 (makineye-özel) genelleştirildi.
> **Statü:** Makineden **bağımsız** bağlayıcı çekirdek. Hiçbir makineye-özel değer (yol, sahip, proje adı, ajan, veri rejimi, donanım) bu belgede **bulunmaz**; hepsi kurulumda üretilen `COUNCIL.local.md` içinde yaşar (Madde 0 & 16, EK-E).
> **Kapsam:** Birden çok bağımsız LLM ajanını "konsey" düzeninde tartıştıran, çapraz-doğrulatan, kanıta dayalı karara götüren çoklu-ajan çalışma düzeni. Herhangi bir bilgisayara kurulduğunda **kendini o makineye göre yapılandırır.**
> **Değişkenler:** `${COUNCIL_HOME}`, `${HOME}`, `${OWNER}`, `${ORG}`, `${DATA_REGIME}`, `${AGENTS[]}`, `${PROJECTS[]}` — değerleri Bootstrap belirler.

---

## MADDE 0 — KURULUM & KENDİNİ-YAPILANDIRMA (Bootstrap)

Bu Anayasa bir makineye ilk kez kurulduğunda, sistem **makineye-özel hiçbir şeyi varsaymaz**; aşağıdakileri tespit edip yerel yapılandırmayı (`COUNCIL.local.md`) **üretir**:

1. **Ortam:** OS/platform, shell, `${HOME}`. `${COUNCIL_HOME}` belirle (varsayılan `${HOME}/.council` veya operatör seçimi).
2. **Ajan envanteri (roster):** PATH'te hangi ajan CLI'ları var? (örn. `claude`, `codex`, `gemini`, `agy`, `ollama`, yerel modeller…) Her biri için *sağlayıcı* ve *çağırma biçimi* (headless flag) saptanır. **En az 2 bağımsız sağlayıcı** bulunmalı (Madde 2.7); yoksa kurulum uyarır.
3. **Proje taraması:** Yaygın kökleri tara (`${HOME}/Projects`, `${HOME}/Desktop`, `${HOME}/code`, `${HOME}/src`, git depoları). Aday dizinleri **operatöre sun**; operatör hangilerinin proje olduğunu ve **veri hassasiyet katmanını** (Madde 8) onaylar. Sonuç = makineye-özel **risk sicili**.
4. **Veri koruma rejimi:** `${DATA_REGIME}` seç (KVKK / GDPR / HIPAA / PDPA / sektörel / yok). Bu, "hassas veri uyumlu sınır dışına çıkamaz" kurallarını belirler (Madde 8). Sağlık/biyometrik/finansal veri varsa ilgili katman aktive olur.
5. **Audit deposu:** Append-only audit deposunu kur (DuckDB / SQLite / JSONL — mevcut olana göre). Şema EK-C.
6. **Üretim:** `COUNCIL.local.md` (EK-E) + risk sicili + ajan roster + tetikleyici komut(lar) yaz. Anayasa dosyasına dokunma.

> **Kural:** Anayasa **jeneriktir ve değişmez kalır**; her makinede yalnız `COUNCIL.local.md` farklıdır. Bootstrap betiği EK-B'dedir.

---

## MADDE 1 — AMAÇ VE FELSEFE

**Konsey**, birden çok bağımsız sağlayıcının LLM ajanlarının bir orkestratör altında tartışıp kanıt ürettiği, birbirini doğruladığı ve karara bağladığı çoklu-ajan düzenidir. Var oluş gerekçesi: tek LLM, hata/önyargı profili nedeniyle yüksek-riskli kararlar için yetersiz kanıt kaynağıdır; **bir ajanın hatasını diğeri yakalar**. Konsey sihirli doğruluk üretmez; üç ajan **aynı yanlışı** da üretebilir — bu yüzden temel, konsensüs değil **kanıta dayalı doğrulamadır** (Madde 7).

---

## MADDE 2 — DOKUNULMAZ İLKELER

Esnetmek için Madde 15 işletilir.

1. **Kanıt > Oylama.** Her karar dış bir kanıta dayanır (test çıktısı, exit code, kaynak doğrulaması, statik analiz, threat model, insan onayı).
2. **Gateway her oturumun ön kapısıdır.** Veri sınıflandırma + hassas-veri/credential taraması, prompt herhangi bir tüketici uç noktaya gitmeden yapılır.
3. **Vendor-neutral adapter zorunlu.** Hiçbir ajan ismi orkestratör koduna gömülmez; tümü tek bir adapter arayüzünden çağrılır. Sağlayıcı değişimi = adapter değişimi.
4. **Kill switch + bütçe zorunlu.** Her oturum max-iter/time/cost ve ardışık-tool-failure sınırıyla başlar; aşım = dur, insan onayı.
5. **Audit immutability.** Kararlar/mesajlar/itirazlar/kanıtlar append-only yazılır. UPDATE/DELETE yasak.
6. **Kritik kararlarda insan onayı.** Üretim yazımı, hassas veri işleme, finansal işlem, geri-alınamaz silme, kimlik/anahtar kullanımı insan onayı ister.
7. **Çok-sağlayıcılı zorunluluk.** Konsey **en az iki bağımsız sağlayıcıdan** oluşur. Tek sağlayıcı kurulumu konsey değildir.
8. **Hassas veri tüketici endpoint'lere gitmez.** `${DATA_REGIME}` kapsamındaki veri (sağlık/biyometrik/kimlik/ticari sır) ya yerel işlenir ya Gateway'de anonimleştirilir.

---

## MADDE 3 — TANIMLAR

| Terim | Tanım |
|---|---|
| **Konsey** | ≥2 bağımsız sağlayıcının orkestratör altında çalıştığı oturum. |
| **Gateway** | Görevin konseye girmeden taramadan geçtiği ön kapı. |
| **Agent Adapter** | Bir ajanı orkestratöre bağlayan soyut arayüz. |
| **Lead Orchestrator** | Oturumu yöneten süreç (interaktif ajan veya deterministik state machine). |
| **Evidence** | Karara dayanak dış kanıt. |
| **Dissent** | Çoğunluğa gerekçeli itiraz; kayda alınır. |
| **Risk Profili** | `public / internal / personal(PII) / sensitive / production`. |
| **`${DATA_REGIME}`** | Geçerli veri koruma rejimi (KVKK/GDPR/HIPAA/…/yok). |
| **`COUNCIL.local`** | Makineye-özel üretilmiş yapılandırma (yollar, roster, projeler, rejim). |

---

## MADDE 4 — ROLLER (sağlayıcıdan bağımsız)

Roller *yeteneğe* atanır; Bootstrap roster'ından hangi sağlayıcının üstleneceği `COUNCIL.local`'da yazılır.

- **Architect / Writer / Lead** — mimari, çok-dosyalı reasoning, sentez, nihai implementasyon, oturum yönetimi.
- **Critic / Sandbox** — adversarial review, edge-case, güvenlik analizi, izole deneme. Üretim yazma yetkisi yok.
- **Researcher** — geniş bağlam araştırma, divergent fikir, kaynak doğrulama, üçüncü bağımsız göz.
- **Juror (opsiyonel)** — anlaşmazlıkta kanıtları sıralar; karar vermez, insan onayına hazırlar.

> Roller dinamik; değişiklik gerekçeli loglanır. Hangi sağlayıcı hangi rolde = `COUNCIL.local`.

---

## MADDE 5 — MİMARİ KATMANLAR

```
1) USER LAYER        — tetikleyici komut(lar), dispatch (klasör/uzak), opsiyonel UI
2) GATEWAY           — risk sınıflandırma · hassas-veri/secret tarama · anonymize↔reidentify · bütçe/scope politikası · context cache
3) ORKESTRATÖR       — Lead ajan veya deterministik state machine; durumlar: PREFLIGHT→PLAN→CRITIQUE→SYNTHESIZE→EXECUTE→VERIFY→DECIDE→REPORT→MEMORY
4) AGENT ADAPTER     — her sağlayıcı tek arayüzden (roster ${AGENTS[]})
5) TOOL & EVIDENCE   — test runner, linter, statik analiz, URL/hash doğrulayıcı, (gerekirse) yerel hassas-veri araçları
6) STATE/AUDIT/MEMORY— append-only audit deposu · evidence ledger · dissent log · oturum özeti
```
Tüm yollar değişkendir (`${COUNCIL_HOME}/…`); sabit yol yazılmaz.

---

## MADDE 6 — ÇALIŞMA AKIŞI (9 durum)

`PREFLIGHT → PLAN → CRITIQUE → SYNTHESIZE → EXECUTE → VERIFY → DECIDE → REPORT → MEMORY`

1. **PREFLIGHT** — Gateway risk sınıflandırma, bütçe, hassas-veri taraması, context cache.
2. **PLAN** — Her ajan bağımsız plan `{steps, assumptions, risks, expected_evidence}`.
3. **CRITIQUE** — Ajanlar birbirinin planına adversarial saldırır; itirazlar dissent log'a.
4. **SYNTHESIZE** — Orkestratör Joint Plan üretir; her adımda `owner` + `expected_evidence`.
5. **EXECUTE** — Yürütme; **tool-failure-streak ≥ eşik → dur, insan onayı.**
6. **VERIFY** — Çapraz doğrulama; **ajan kendi çıktısını doğrulayamaz**; dış kanıt şart. Başarısız → EXECUTE'a (sınırlı tur).
7. **DECIDE** — Kanıt-ağırlıklı; `confidence < eşik` → insan onayı; `sensitive/production` → her durumda insan onayı.
8. **REPORT** — Özet + kanıt zinciri + itirazlar + maliyet/zaman.
9. **MEMORY** — Append-only audit + tekrar kullanılabilir playbook.

---

## MADDE 7 — KARAR: KANIT-AĞIRLIKLI DOĞRULAMA

Bir karar geçerli olmak için **en az birine** dayanır: geçen test (exit 0) · terminal çıktısı · doğrulanmış kaynak (HTTP 200/hash) · temiz statik analiz · insan onayı · threat model passed.

- Ajanların aynı fikirde olması **sinyaldir, kanıt değil** — dış kanıtla desteklenmedikçe karara dönmez.
- Anlaşmazlık: çoğunluk + dissent log kaydı; eşit/üç-yönlü ayrılık → Juror kanıt sıralar, insan onayı. `sensitive/production` kararlarda anlaşma olsa bile insan onayı.
- **Yasak:** "hepsi aynı dedi" / "çalıştığını söyledi" / ajanın kendi çıktısını doğrulaması.

---

## MADDE 8 — GÜVENLİK & VERİ KORUMA (rejim-bağımsız)

Gateway her görevi sınıflar (makineye-özel risk sicili `COUNCIL.local`'da):

| Katman | Tanım | Konsey'e gönderim |
|---|---|---|
| `public` | Açık veri, dök. | Doğrudan |
| `internal` | Kurum içi kod/notlar | Özet seviyesinde |
| `personal` (PII) | Kişisel veri | Anonymize → konsey → reidentify |
| `sensitive` | Özel kategori: sağlık/biyometrik/finans/sır (`${DATA_REGIME}`'e göre) | Tüketici endpoint'e **GİTMEZ**; yerel işle / anonimleştir |
| `production` | Canlı sistem yazımı, prod credential | İnsan onayı zorunlu, write-scope ajanda yok |

**Rejim kuralları (`${DATA_REGIME}` aktifse):** hassas veri uyumlu coğrafi/yasal sınır dışına çıkmaz; uyumsuz endpoint'ler hassas katman için yasak; tanımlayıcılar (kimlik no, ad, doğum, kayıt no, telefon, e-posta) regex+LLM taramasından geçer; reidentify haritası Gateway dışına çıkmaz. **Credential** asla düz metin — OS anahtar deposu (Keychain/secret manager). **Prompt injection:** araç tanımları doğrulanır, dolaylı talimatlar filtrelenir, web içeriği özet→onay→konsey.

> `${DATA_REGIME}=yok` ise `sensitive` katman boş kalabilir; yine de `production` + credential kuralları geçerlidir.

---

## MADDE 9 — BÜTÇE VE KILL SWITCH

`COUNCIL.local`'da makineye göre ayarlanır; varsayılanlar:

| Parametre | Varsayılan | Üst sınır |
|---|---|---|
| max_iterations | 5 | 10 |
| max_wall_time | 15 dk | 60 dk |
| max_cost (varsa) | düşük | operatör belirler |
| max_consecutive_tool_failures | 3 | 3 (sabit) |
| max_concurrent_agents | roster boyutu | 6 |

**Kill switch:** bütçe aşımı · ardışık tool-failure · Gateway dışı hassas veri · stagnation (yeni kanıt yok) · manuel durdurma. Tetiklenince dur, snapshot, insan onayı.

---

## MADDE 10 — AUDIT, HAFIZA, GERİ ALMA

- **Append-only** audit deposu (impl: DuckDB/SQLite/JSONL): sessions, messages, evidence, decisions, dissent, incidents (EK-C). UPDATE/DELETE yasak; kapanış bir *event* olarak eklenir.
- **Evidence ledger:** karar → kanıt zinciri (tip, kaynak, hash, üreten, doğrulayan).
- **Dissent log:** öğrenme verisi.
- **Rollback:** üretim yazımı doğrudan değil; staging/PR + geri-alma hakkı.

---

## MADDE 11 — YETENEK SEVİYELERİ (makineye göre artımlı)

Bir makine bu seviyeleri ihtiyaç ve kaynağa göre açar (zorunlu sıra değil):

- **L0 — Çekirdek:** Anayasa + `COUNCIL.local` + tetikleyici komut + ≥2 ajan.
- **L1 — Audit:** Append-only depo + evidence/dissent.
- **L2 — Deterministik orkestrasyon:** State-machine + Gateway modülü + kanıt-ağırlıklı karar + kill switch.
- **L3 — Otonomi/Dispatch:** Zamanlayıcı (cron/launchd/systemd) + inbox→outbox; **otonom tavan ≤internal**, üstü insan kuyruğuna.
- **L4 — A2A & Federasyon (opsiyonel):** Ajan-ilişkisi protokolü; düğümü A2A endpoint olarak sun / jenerik peer'lar. (Cross-machine federasyon **isteğe bağlı** ve makineye özeldir; çekirdek gerektirmez.)

---

## MADDE 12 — ÇOK-DENETİM PROTOKOLÜ

Her çıktı için zorunlu denetim: **[Lint/Statik]** (sentaks, ruff/mypy/eslint vb., deprecated yok) · **[Mantık/Doğrulama]** (akış, performans, gerçek senaryo) · **[Güvenlik/Tarama]** (OWASP/injection/secret-leak, rejim uyumu, test exit). Herhangi birinde kritik bulgu → `confidence` düşür, insan onayı.

---

## MADDE 13 — YASAKLAR (istisna yok)

❌ Hassas veri tüketici endpoint'e · ❌ onaysız üretim yazımı · ❌ açık secret · ❌ ajan kendini doğrular · ❌ oylama tek başına karar · ❌ manifestsiz/doğrulanmamış araç konseye · ❌ onaysız 2. otonom tur (kritik) · ❌ tek sağlayıcı "konsey" · ❌ orkestratör dışı audit yazımı · ❌ test geçmemiş kod "tamam" · ❌ Gateway atlanamaz · ❌ **bu Anayasa'ya makineye-özel değer gömülemez** (Madde 16).

---

## MADDE 14 — ACİL DURUM

Otomatik durdurma (Madde 9 tetikleyicileri) veya manuel durdurma. Sonra: state snapshot, yarım araç çağrılarını temizle, post-mortem üret. **İhlal (Madde 13):** oturum anında durur, incident yazılır, kırmızı uyarı, yeni oturum gerekir.

---

## MADDE 15 — ANAYASA DEĞİŞİKLİĞİ

Semver (`MAJOR.MINOR.PATCH`). Değişiklik: öneri → konsey değerlendirmesi (CRITIQUE) → **sahip (`${OWNER}`) onayı** → tarihli yayım → eski sürüm arşive. Acil "override patch" 7 gün içinde tam prosedüre bağlanır.

---

## MADDE 16 — TAŞINABİLİRLİK & YERELLEŞTİRME

1. Bu belge **makineden bağımsızdır**: yol, kullanıcı adı, proje adı, ajan markası/sürümü, donanım, kurum, veri rejimi **içermez**.
2. Tüm makineye-özel değerler `COUNCIL.local.md` (EK-E) içinde, Bootstrap (Madde 0) tarafından **üretilir**.
3. Çalışma zamanı yolları **değişkenle** ifade edilir (`${COUNCIL_HOME}` vb.).
4. Yeni makinede: Anayasa kopyalanır (değişmez) → Bootstrap çalışır → `COUNCIL.local` üretilir → sistem o makineye göre çalışır.
5. Anayasa'ya bir makine-özel değer sızarsa = Madde 13 ihlali; Bootstrap/`COUNCIL.local`'a taşınır.

---

## EK-A — RİSK MATRİSİ (katmana göre, jenerik)

| Görev türü | Katman | Konsey | İnsan onayı |
|---|---|---|---|
| Açık dök./mimari karşılaştırma | public | Tam | Hayır |
| Kurum içi kod iyileştirme | internal | Tam | Hayır |
| Kişisel veri özeti | personal | Anonymize sonrası | Hayır |
| Özel-kategori veri işleme | sensitive | **Yasak/yerel** | Evet |
| Üretim sistemine yazma | production | Plan onayı sonrası | **Evet** |

---

## EK-B — BOOTSTRAP (taşınabilir kurulum prosedürü)

Operatör (veya konseyin kurulum ajanı) ilk çalıştırmada yürütür. Sözde-prosedür:

```bash
# 1) Ortam
COUNCIL_HOME="${COUNCIL_HOME:-$HOME/.council}"; mkdir -p "$COUNCIL_HOME"/{bin,logs,playbooks,sessions,a2a}

# 2) Ajan envanteri (≥2 bağımsız sağlayıcı şart)
for cli in claude codex gemini agy ollama; do command -v "$cli" >/dev/null && echo "bulundu: $cli"; done
#   → her bulunan için sağlayıcı + headless çağrı biçimi COUNCIL.local'a yaz

# 3) Proje taraması (operatör onaylar + hassasiyet katmanı atar)
find "$HOME"/{Projects,Desktop,code,src} -maxdepth 2 -name .git -type d 2>/dev/null | sed 's#/.git##'
#   → aday listesi operatöre sun → risk sicili COUNCIL.local'a

# 4) Veri rejimi
echo "DATA_REGIME = (KVKK|GDPR|HIPAA|PDPA|none) ?"   # operatör seçer

# 5) Audit deposu (mevcut olana göre)
#   duckdb varsa council.duckdb (EK-C); yoksa sqlite3; o da yoksa JSONL fallback

# 6) Üret: COUNCIL.local.md (EK-E) + risk sicili + roster + tetikleyici komut
#   Anayasa dosyasına DOKUNMA.
```

> Not: Anayasa, bir LLM-ajanına "bu makinede Bootstrap'i çalıştır ve `COUNCIL.local` üret" diye verilebilir; ajan Madde 0'ı izleyerek otomatik kurar.

---

## EK-C — AUDIT ŞEMASI (jenerik; DuckDB/SQLite)

```sql
CREATE TABLE council_sessions  (session_id TEXT PRIMARY KEY, topic TEXT, risk_profile TEXT,
  budget_usd REAL, max_iter INT, max_wall_time_s INT, status TEXT,
  started_at TIMESTAMP, ended_at TIMESTAMP, cost_actual_usd REAL, user_id TEXT);
CREATE TABLE council_messages  (msg_id TEXT PRIMARY KEY, session_id TEXT, from_agent TEXT,
  to_agent TEXT, msg_type TEXT, payload TEXT, content_hash TEXT, ts TIMESTAMP);
CREATE TABLE council_evidence  (evidence_id TEXT PRIMARY KEY, session_id TEXT, evidence_type TEXT,
  source TEXT, content_hash TEXT, produced_by TEXT, verified_by TEXT, ts TIMESTAMP);
CREATE TABLE council_decisions (decision_id TEXT PRIMARY KEY, session_id TEXT, decision TEXT,
  confidence REAL, evidence_refs TEXT, dissent_refs TEXT, human_approved BOOLEAN, ts TIMESTAMP);
CREATE TABLE council_dissent   (dissent_id TEXT PRIMARY KEY, session_id TEXT, agent TEXT,
  against_decision TEXT, rationale TEXT, ts TIMESTAMP);
CREATE TABLE council_incidents (incident_id TEXT PRIMARY KEY, session_id TEXT, violation_type TEXT,
  detail TEXT, ts TIMESTAMP);
-- Yalnız INSERT. Kapanış = council_messages'a 'session_end' event'i (UPDATE değil).
```

---

## EK-D — AGENT CARD ŞABLONU (jenerik)

```json
{
  "name": "${NODE_NAME}", "version": "1.0.0",
  "description": "Konsey düğümü — ${ROLES}",
  "url": "http://127.0.0.1:${PORT}",
  "provider": { "organization": "${ORG}", "node": "${NODE_ID}" },
  "nodes": ["${AGENTS[]}"],
  "capabilities": ["multi_agent_council","evidence_weighted_decision","cross_validation"],
  "risk_profile_max": "internal",
  "policy": "A2A üstünden yalnız ≤internal otomatik; sensitive/production reddedilir (Md.13).",
  "endpoints": { "agent_card": "/.well-known/agent-card.json", "task": "/a2a/task", "health": "/health" },
  "auth": "none (yalnız 127.0.0.1; uzak için kasıtlı yapılandırma)"
}
```

---

## EK-E — `COUNCIL.local.md` ŞABLONU (makineye-özel; Bootstrap üretir)

```markdown
# COUNCIL.local — <makine adı>
## Sahip / Kurum: ${OWNER} / ${ORG}
## COUNCIL_HOME: ${COUNCIL_HOME}
## Veri rejimi: ${DATA_REGIME}    # KVKK | GDPR | HIPAA | PDPA | none

## Ajan roster (≥2 bağımsız sağlayıcı)
- <ad> | sağlayıcı | rol | çağrı: <headless komut>     # örn: claude | anthropic | Lead | `claude -p`
- ...

## Tetikleyici(ler)
- interaktif: "<kelime>" / slash komut
- headless: <komut> "<görev>"

## Risk sicili (operatör onaylı)
| Proje yolu | Katman | Üretim | Not |
|---|---|---|---|
| ... | internal/sensitive/production | ... | ... |

## Bütçe / kill switch (varsayılandan sapmalar)
## Yerel notlar (bu makineye özgü)
```

---

## SON HÜKÜM

Bu Anayasa kanıta dayalı doğrulama üzerine kuruludur:

> *"Ajanlar aynı şeyi söylüyorsa şüphelen; dış kanıt yoksa karar verme; karar verdiysen geri alınabilir tut."*

Çelişen herhangi bir oturum talimatı, Madde 2 (Dokunulmaz İlkeler) ve Madde 13 (Yasaklar) önünde geçersizdir. Makineye-özel her şey `COUNCIL.local`'dadır; bu belge her bilgisayarda aynen geçerlidir.

**Sürüm:** 2.0.0 (portable) · **Değişkenler Bootstrap (Madde 0) ile dolar.**
