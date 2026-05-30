# Konsey

[English](./README.md) · **Türkçe**

> Çok-ajanlı, kanıt-ağırlıklı, sağlayıcı-bağımsız çalışma doktrini + orkestratör.
> Her makinede çalışır; kurulurken kendini yapılandırır. Telemetri yok — tüm veri yerel.

[![Lisans: Apache-2.0](https://img.shields.io/badge/kod-Apache--2.0-blue.svg)](./LICENSE)
[![Doktrin: CC-BY-4.0](https://img.shields.io/badge/doktrin-CC--BY--4.0-lightgrey.svg)](./constitution/)
[![Python](https://img.shields.io/badge/python-%E2%89%A53.12-blue.svg)](./pyproject.toml)
![Telemetri yok](https://img.shields.io/badge/telemetri-yok-success.svg)

> Not: İngilizce sürüm ([README.md](./README.md)) kanonik (asıl) metindir; bu dosya
> birebir Türkçe aynasıdır. Çelişki olursa İngilizce metin geçerlidir.

---

## 1. Konsey nedir?

Konsey, bir görevi **çok-ajanlı, kanıt-ağırlıklı, tam-denetlenebilir** bir iş akışına
çevirir; bunu bağımsız LLM CLI'ları (örneğin `claude`, `codex`, `agy`) arasında yapar.
Tamamen terminalde çalışır, her sağlayıcıyı düz bir subprocess olarak çağırır
(çekirdekte SDK yok, API anahtarı yok) ve her adımı yerel, yalnız-ekleme bir denetim
deposuna yazar. Her makineye kurulur; ilk çalıştırmada kendini yapılandırır (Madde 0
Bootstrap) — koda makineye-özel hiçbir şey gömülmez.

## 2. Neden? — üç sütun

- **Tek-LLM kör noktası.** Bir modelin kendinden emin hatası kendine görünmez.
  Bağımsız ikinci (veya üçüncü) sağlayıcı bunu yakalar. Konsey'de bir iddiayı *üreten*,
  asla onun *tek doğrulayıcısı* olamaz — bu kural önerilmez, zorunlu kılınır.
- **Denetlenebilirlik.** Her mesaj, kanıt, karar ve muhalefet yerel bir veritabanına
  **yalnız-ekleme** olarak yazılır (UPDATE / DELETE yok). Aylar sonra bile şunu
  yanıtlayabilirsiniz: *kim, hangi kanıtla, neye karar verdi ve kim itiraz etti?*
- **Kanıt > konsensüs.** Kararlar oyla değil; çapraz-doğrulama, kanıt ve araç-başarısı
  **skoruyla** verilir. Hassas / üretim / düşük-güven işler otomatik tamamlanmaz,
  insana yükseltilir.

## 3. Nasıl çalışır?

Deterministik dokuz-durumlu döngü:

```
PREFLIGHT → PLAN → CRITIQUE → SYNTHESIZE → EXECUTE → VERIFY → DECIDE → REPORT → MEMORY
```

- **PREFLIGHT** — risk sınıflaması + secret/PHI fail-safe gate.
- **PLAN / CRITIQUE / SYNTHESIZE** — Lead taslak yazar, Critic adversarial eleştirir,
  Lead uzlaştırır.
- **EXECUTE** — uzlaşılan işi bir yürütme güvenlik sınırı altında koşar.
- **VERIFY** — sonucu, yürütenden *farklı bir sağlayıcı* doğrular
  (üreten ≠ doğrulayan).
- **DECIDE** — oy değil, kanıt-ağırlıklı skor.
- **REPORT / MEMORY** — özet + yalnız-ekleme audit + distilasyon.

Değişmezler: üreten ≠ doğrulayan; duvar-saati ve ardışık-araç-hatası eşiğiyle sınırlı
bir kill switch (`konsey stop` her an manuel tetikler).

## 4. Mimari

```
                 council.local.toml  (git-ignored, Bootstrap üretir)
                          │   tek enjeksiyon noktası
                          ▼
                  ┌───────────────┐
                  │   config.py   │  Config dataclass · by_role() · verifier(exclude=)
                  └───────┬───────┘
                          │
  sağlayıcı-nötr adapter  │      gateway / PREFLIGHT
  (CLI başına bir sınıf)──┼────  (risk sınıfı + secret tarama)
                          │
                  ┌───────▼────────┐
                  │  9-durum graf  │  (LangGraph)
                  └───────┬────────┘
                          │
            kanıt-ağırlıklı karar
                          │
                 yalnız-ekleme audit (DuckDB)
                          │
              dashboard  ·  A2A (opsiyonel, varsayılan kapalı)
```

**Sağlayıcı değişimi tek bir roster satırını değiştirir — mimariyi asla.** Roller
(Lead / Critic / Researcher / Verifier / Distiller) jeneriktir ve sağlayıcılara koşum
zamanında `cfg.by_role()` ile `cfg.verifier(exclude=...)` üzerinden atanır; hiçbir
çekirdek modül marka adını, yolu, proje adını veya sahip kimliğini gömmez.

## 5. Kurulum

```bash
git clone <repo> konsey && cd konsey
./install.sh            # OS tespit eder, dep'leri pinler, Madde-0 Bootstrap'ı çalıştırır
konsey doctor           # KANITLAR: hangi sağlayıcı CLI'ları gerçekten PATH'te
```

Alternatif (izole ortam, sistem Python'ını kirletmez):

```bash
pipx install konsey-cli
```

**Dürüst notlar:**

- **Python ≥ 3.12 gereklidir** (kanıtlanmış, test edilmiş sürüm budur; 3.10/3.11
  *iddia edilmez*, yalnız doğrulanan belirtilir).
- En az **bir** sağlayıcı CLI'ı gerekir (`claude` / `codex` / `agy`); gerisi zarif
  şekilde devre dışı kalır (graceful degrade).
- **Çapraz-doğrulama ≥ 2 bağımsız sağlayıcı gerektirir.** Tek sağlayıcıyla Konsey
  *danışman modunda* çalışır: güven `0.6` ile tavanlanır ve çıktı "doğrulanmamış"
  damgalı olur. Üçüncü düğüm — `agy` (Google Antigravity) — **opsiyoneldir** ve
  kurulumu daha zordur; çoğu kurulum 1–2 sağlayıcı çalıştırır. Bu bir pazarlama iddiası
  değil, dürüst bir varsayılandır.

## 6. Kullanım

```bash
konsey run "X'i refactor et ve testlerin hâlâ geçtiğini kanıtla"
konsey run "Bu tasarım dokümanını denetle" --project myrepo --dry-run
konsey doctor                 # kanıt-temelli sağlık: hangi CLI çözülüyor, DB yaz/rollback
konsey audit                  # yalnız-ekleme kaydını gözden geçir (salt-okunur)
konsey init                   # kendini-yapılandıran Bootstrap'ı (yeniden) çalıştır
```

`council …`, `konsey …` komutunun **kullanımdan kalkan** ama tam çalışan alias'ıdır (yardım başlığı ve `--version` hangi adı çağırdıysanız onu yansıtır; terminalde `council` çağırınca `konsey`'e yönlendiren tek satırlık bir not basılır).

> Yukarıdaki tüm alt-komutlar (`init` / `doctor` / `run` / `status` / `audit` /
> `config` / `agents` / `enable` / `stop` / `uninstall`) bugün bağlı ve
> çalıştırılabilir — `konsey --help` ile doğrulayın. Hangi platformda neyin denendiği
> için bkz. [Olgunluk](#9-durum--olgunluk).

## 7. Yapılandırma

Makineye-özel her şey **`council.local.toml`** içinde yaşar (git-ignored, Bootstrap
üretir) ve `council/config.py` üzerinden — tek enjeksiyon noktası — akar. Depoda
makineye-özel hiçbir şey izlenmez.

Gerçek bir config'te secret bulunmaz, yalnız bildirimsel gerçekler vardır.
[`examples/council.local.example.toml`](./examples/council.local.example.toml)
dosyasından başlayın (kurgusal bir "Acme Labs" profili; gerçek bir kurulumdan
**türetilmez**):

```toml
owner = "operator"          # makine kullanıcı adınız DEĞİL — audit'e asla sızdırılmaz
org = "Acme Labs"
locale = "en"               # en | tr
data_regime = "standard"    # standard | kvkk | gdpr | hipaa
exec_sandbox = "off"        # off | read-only | workspace-write
autocapture_enabled = false # opt-in; varsayılan KAPALI

[[agents]]                  # jenerik rol → sağlayıcı; üreten asla tek doğrulayıcı değil
name = "claude"
cli  = "claude"
role = "lead"

[[projects]]                # proje adı tek başına asla phi anlamına gelmez
match = "infra/*"
risk  = "production"
```

Düzenleyici terim listeleri (klinik / kimlik-no regex'leri) **yalnız** opt-in rejim
eklentilerinde yaşar (`regimes/*.toml`, `data_regime` ile aktive olur) — asla çekirdek,
audit veya capture kodunda değil. Bkz.
[`examples/regimes/clinical.example.toml`](./examples/regimes/clinical.example.toml).

## 8. Anayasa

Orkestratör taşınabilir bir doktrini uygular —
[Konsey Anayasası](./constitution/), sürüm **7.0.0**, **CC-BY-4.0** lisanslı
(Apache-2.0 koddan ayrı). Bu, değiştirilemez kural setidir; tüm makine-gerçekleri
`council.local`'dan gelir, asla doktrin metninden değil.

Bağlayıcı maddeler kısaca: Bootstrap (Md. 0); kanıt > konsensüs ve üreten ≠ doğrulayan
(Md. 2); jenerik roller + danışman modu (Md. 3); fail-safe PHI / PII / secret gate
(Md. 4); kanıt-ağırlıklı kararlar (Md. 7); yalnız-ekleme audit (Md. 10/11).
Değiştirilemez çekirdek (Md. 2, 4, 5, EXECUTE güvenliği, karar tavanı/tabanı,
yalnız-ekleme) bir profil veya oturum tarafından *sıkılaştırılabilir*, asla
*gevşetilemez*.

## 9. Durum / olgunluk

**Dürüst, güncel durum — v0.1.0 MVP (Faz 0+1 tamam, Faz 2 sürüyor).**

- Çekirdek **uygulandı ve test edildi**: tam CLI (`init` / `doctor` / `run` /
  `status` / `audit` / `config` / `agents` / `enable` / `stop` / `uninstall`) ve
  arkasındaki modüller — `config` / `adapters` / `gateway` / `decide` / `graph`
  (9-durumlu döngü) / `audit` / `capture` / `dispatch`. Yapılandırma kontratı
  (`Config`, `RosterEntry`, `by_role()`, `verifier(exclude=)`, `available()`) tek
  enjeksiyon noktasıdır.
- **Test kanıtı: 92/92 geçer** (`python -m pytest`); config/bootstrap, risk gateway,
  secret tarama, yalnız-ekleme audit, adapter'lar ve kanıt-ağırlıklı decide kapsanır.
  Python 3.12'de (CI tabanı ve kanıtlanmış taban) doğrulandı. Daha yeni yorumlayıcıların
  (3.13/3.14) çalışması beklenir ama CI 3.12'ye sabitlenmiştir.
- **Doğrulanan platformlar.** macOS birincil geliştirme hedefidir. **Sıfırdan bir Linux
  kurulumu uçtan uca denetlendi** (Docker `python:3.12-slim`: install → init → doctor
  → run + `cron` scheduler kur/kaldır turu + pytest 92/92, hepsi yeşil); yalnız-macOS
  backend'leri Linux'ta hata fırlatmadan doğru biçimde no-op döndürdü. **Canlı bir arka
  plan daemon'ı ile henüz denenmedi: systemd kullanıcı timer'ları ve Windows Task
  Scheduler** — bu backend'ler mevcut ama çalışan bir scheduler'a karşı doğrulanmadı
  (bkz. [`KNOWN_ISSUES.md`](./KNOWN_ISSUES.md)).
- OS soyutlama katmanında **scheduler / notify / secret backend'leri** varsayılan
  olarak no-op (`null`) uygulamadır; çekirdek bunların hiçbiri olmadan çalışır. Arka
  plan otomasyonu opt-in ve **varsayılan KAPALI**.

Bu README, kodun bugün sağladığından fazlasını iddia etmez; makinenizdeki canlı,
kanıt-temelli durum için `konsey doctor` çalıştırın, ertelenen kalemler için
[`KNOWN_ISSUES.md`](./KNOWN_ISSUES.md).

## 10. Gizlilik & güvenlik

- **Telemetri yok. Tüm veri yerel.** Konsey, prompt'ları yalnız *sizin* kurup
  subprocess olarak çalıştırdığınız sağlayıcı CLI'larına yönlendirir — Konsey'in
  işlettiği bir sunucu yoktur.
- **Gateway bir güvenlik ağıdır, garanti değil.** Secret/PHI taraması kazara sızıntıyı
  azaltır; uyumluluk sertifikası vermez. Düzenleyici rejimler
  (`kvkk` / `gdpr` / `hipaa`) bir *tespit yardımıdır*, **uyumluluk garantisi DEĞİLDİR**
  — yasal sorumluluk operatöre aittir (Madde 4.3).
- **Yalnız-ekleme audit, kurcalama-*kanıtlayıcı*dır, kurcalama-*önleyici* değil.**
  Yalnız-ekleme uygulama katmanında zorlanır; aynı OS kullanıcısında koşan bir süreç
  dosyayı yine de yeniden yazabilir. OS-seviyesi değiştirilemezlik **garanti edilmez**
  (Madde 11.2). Hassas veri işlemeden önce [`SECURITY.md`](./SECURITY.md) okuyun.
- Hassas veri asla izin verilmeyen bir endpoint'e veya tüketici LLM endpoint'ine
  gönderilmez — bu koşulsuz bir bloktur, insan onayıyla bile aşılamaz (Madde 4.5).

## 11. Katkı

Katkılar memnuniyetle karşılanır. Katkı kapısı ([`CONTRIBUTING.md`](./CONTRIBUTING.md))
şunları gerektirir: secret yok, kurum/ürün adı yok, mutlak yol yok ve çıktısıyla birlikte
testler. Sağlayıcı eklemek bir adapter sınıfı / config satırıdır; düzenleyici rejim
eklemek bir eklenti dosyasıdır — çekirdek değişmez. Güvenlik sorunları herkese-açık
bir issue ile değil, **özel (private)** bildirim ile gider (`SECURITY.md`).

## 12. Lisans & atıf

- **Kod:** Apache-2.0 — bkz. [`LICENSE`](./LICENSE) ve [`NOTICE`](./NOTICE).
- **Anayasa / doktrin metni:** CC-BY-4.0 — bkz. [`constitution/`](./constitution/).
  Doktrin atıflanabilir ve atıfla uyarlanabilir.
