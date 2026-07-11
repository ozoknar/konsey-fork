# AI Ar-Ge Raporu — karpathy/llm-council Değerlendirmesi ve Konsey'e Adaptasyonu

**Tarih:** 2026-07-11
**Proje:** Konsey (çok-ajan kanıt-temelli orchestrator, `~/Desktop/mm cc projeleri/konsey`)
**Kapsam:** Dış bir açık-kaynak projenin (karpathy/llm-council) mimari incelemesi, konseyin kendi karar mekanizması aracılığıyla değerlendirilmesi, seçilen fikrin dar-kapsamlı olarak implement edilmesi, test edilmesi ve canlı doğrulanması.
**Sonuç:** 1 yeni opt-in özellik (`parallel_plan_rank`, Faz 1) tasarlandı, kodlandı, test edildi (464→474 test), commit edildi (`0c676bf`). Faz 2 (skor entegrasyonu) kullanıcı onayına bağlı, uygulanmadı.

---

## 1. Motivasyon

Kullanıcı, Andrej Karpathy'nin `github.com/karpathy/llm-council` reposunun ("LLM Council works together to answer your hardest questions") konseye (bu projenin çok-ajan orchestrator'ı) katkısı olup olmayacağını sordu. Görev: dış projeyi incele, gerçek bir fark/katkı var mı belirle, varsa somut bir tavsiye ver.

## 2. Araştırma — karpathy/llm-council Mimarisi

Kaynak (`gh api` ile doğrudan GitHub'dan çekildi — README.md + `backend/council.py` + `backend/config.py` + `backend/openrouter.py` tam okundu):

- **Yazarın kendi ifadesi:** "%99 vibe-coded, bir Cumartesi hack'i, desteklemeyeceğim, kütüphaneler artık geride kaldı, LLM'ine istediğin gibi değiştirt." — bilinçli olarak minimal, üretim-kalite bir sistem değil.
- **Mimari:** OpenRouter API üzerinden 4 model (gpt-5.1, gemini-3-pro, claude-sonnet-4.5, grok-4), tool erişimi yok (saf metin-içeri/metin-dışarı), audit/DB/izolasyon kavramı yok.
- **3 aşama:**
  1. **Stage 1 (First opinions):** Soru tüm modellere paralel gider, ham cevaplar toplanır.
  2. **Stage 2 (Review):** Her model, diğerlerinin cevaplarını **anonimleştirilmiş** ("Response A/B/C", model kimliği gizli) halde görür, `FINAL RANKING:` formatlı bir sıralama üretir. Amaç: kayırma/favori-model-tanıma riskini azaltmak.
  3. **Stage 3 (Final response):** Ayrı, sabit bir "Chairman" model tüm cevap+sıralamaları görüp tek bir nihai sentez üretir.
- **Ek:** `calculate_aggregate_rankings()` — modellerin aldığı sıra pozisyonlarının **basit ortalamasını** alıp en-iyiden-en-kötüye sıralıyor (ağırlıklı/Borda değil, naif).
- **Frontend:** Basit React/Vite, Stage-1 cevaplarını yan-yana tab-view'de gösteriyor.
- **Eylem yeteneği:** Yok — salt sohbet aracı, kararı "uygulayan" bir mekanizma içermiyor.

## 3. Değerlendirme — Konseyin Kendisine Sunuldu

Kanıtsız-iş-yasağı kuralı gereği ("konsey kuralı sadece konsey düğümleri için değil, orchestrator için de geçerli") bu karar tahminle değil, **konseyin kendi 9-durumlu döngüsü** üzerinden verildi.

**Çağrı:** `konsey run --project "konsey" --json "<KANIT bloklu görev>"` (proje dizini: bu repo, düğümler read-only tool ile `graph.py`/`decide.py`/`config.py`'yi kendileri okuyup teyit etti).

**Sonuç (session `28d9a879`):**
- `providers_ok = 3` (claude+codex+google tam quorum)
- `decision.confidence = 0.85`
- `decision.human_required = false`
- Codex'in bağımsız doğrulama turu (VERDICT: PASS) 3 iddiayı kod okuyarak teyit etti: 9-durum graph, `decide.py`'nin kanıt-ağırlıklı formülü, `providers_ok==3` quorum kuralı.

**Karar özeti:**
1. **Anonimleştirilmiş çapraz-sıralama (Stage 2 fikri):** Değerli — konseyde gerçek bir boşluğa denk geliyor (`parallel_plan` açıkken üretilen planlar hiç karşılaştırılmıyor). **Kritik çekince:** llm-council'ın sıralaması bir *tercih/popülerlik* sinyali; konsey *kanıt-öncelikli*. Doğrudan `decide.py`'nin skoruna bağlamak kanıt-primacy'sini sulandırır.
2. **Yan-yana karşılaştırma UI'ı:** Sınırlı değer, ayrı canlı frontend gereksiz karmaşıklık — reddedildi. Mevcut audit dashboard'una küçük bir blok olarak eklenmesi önerildi (bu öneri implementasyon sırasında geçersiz çıktı, bkz. §6).
3. **Geri kalan her şey** (OpenRouter soyutlaması, tool'suz mimari, tek-Chairman, audit/izolasyon yokluğu): konseyin kasıtlı olarak zaten aştığı/reddettiği tasarım tercihleri — taşınmaya değmez.
4. **Tavsiye: UYGULA — dar ve iki fazlı.**
   - **Faz 1:** `parallel_plan_rank` (opt-in, varsayılan KAPALI). Sadece **gözlemsel** — `decide.py`'ye hiç dokunmadan, REPORT'a yaz. Düşük risk, geri alınabilir.
   - **Faz 2:** Faz 1 gerçek kullanımda iyi sinyal verirse, `consensus_bonus`'a **sınırlı+şartlı** bağlama — ama bu kanıt-öncelikli karar motoruna tercih sinyali sokmak demek, **kullanıcı onayı olmadan yapılmaz.**

## 4. Kullanıcı Kararı ve Ek Talimat

Kullanıcı Faz 1'in uygulanmasını onayladı ve ek bir metodoloji talebinde bulundu: bundan sonraki gerçek konsey çağrıları **"double" (çift) yapılsın** — ana/mevcut konsey davranışı vs Faz-1-değiştirilmiş konsey davranışı paralel çalıştırılıp kullanıcıya karşılaştırma sunulsun; kullanıcı "Faz 2'ye geç" diyene kadar skor entegrasyonuna geçilmesin.

## 5. Implementasyon (Faz 1)

**Değişen dosyalar (commit `0c676bf`, 12 dosya, +395/-6 satır):**

| Dosya | Değişiklik |
|---|---|
| `council/config.py` | Yeni alan: `parallel_plan_rank: bool = False` (opt-in) + TOML yükleme satırı |
| `council/graph.py` | Yeni node `rank_plans` (`plan` → `rank_plans` → `critique`); `_parse_plan_ranking()` (llm-council'ın `FINAL RANKING:` desenine uyarlanmış parser); `_aggregate_plan_rankings()` (**Borda count** — llm-council'ın naif ortalamasının konseyin kendi değerlendirmesinde eleştirilen yerine); `S` TypedDict'e `plan_ranking: dict`; `report()`'a danışma-amaçlı gösterim bloğu |
| `council/prompts.py` | `PROMPT_KEYS`'e `rank_plans` eklendi |
| `council/locales/en.json` + `tr.json` | `prompts.rank_plans` + `report.plan_ranking_heading`/`report.plan_ranking_item` |
| `tests/test_rank_plans.py` (YENİ) | 10 test: opt-in gating (flag kapalıyken no-op, tek adayken no-op), anonimleştirme doğruluğu, Borda agregasyon doğruluğu, **`decide.py`'de `plan_ranking` referansı OLMADIĞINI doğrulayan statik regresyon guard'ı** |
| `README.md`, `README.tr.md`, `examples/council.local.example.toml` | Yeni flag'in dokümantasyonu |
| `CHANGELOG.md` | Tam provenance kaydı (konsey session ID, karar gerekçesi) |
| `KNOWN_ISSUES.md` | Bkz. §6 — yan-bulgu kaydı |

**Mimari garanti:** `decide.py`'ye kod olarak hiç dokunulmadı; `test_decide_module_has_no_static_reference_to_plan_ranking` testi bunu statik olarak doğruluyor (dosya kaynağında `"plan_ranking"` string'i aranıyor, bulunmaması gerekiyor).

**Test sonucu:** 464 → 474 test, tümü geçti. `ruff check` temiz (yeni kodda; repoda önceden var olan 5 stil hatası — `test_adapters_isolation.py`'de noktalı virgül kullanımı — bu değişiklikle ilgisiz, dokunulmadı).

## 6. Yan-Bulgu — Dashboard Stub

Implementasyon sırasında konseyin kendi tavsiyesindeki bir varsayımın yanlış olduğu keşfedildi: `council/dashboard.py` **tamamen boş bir stub** (`"""Serverless single-file HTML audit dashboard (read-only).\n\nTODO Phase 2.\n"""` — 5 satır, hiç fonksiyon yok). `konsey audit --open` komutu bu yüzden fiilen çalışmıyor (hata veriyor). Konseyin kendi değerlendirmesi "mevcut dashboard'a ekle" derken bu dosyayı okumamıştı (read-only tool taraması bu dosyayı kapsamamış).

**Sonuç:** Faz 1'in "dashboard'a ekle" kısmı yapılmadı — dashboard'un kendisi inşa edilmeden bir şey eklenemez. `KNOWN_ISSUES.md`'ye dürüstçe kaydedildi, ayrı bir Phase 2 işi olarak bekliyor.

## 7. Canlı Doğrulama — "Double Call" Denemesi ve Metodoloji Dersi

Kullanıcının istediği karşılaştırma denendi: aynı llm-council-değerlendirme görevi, izole bir geçici `KONSEY_HOME` altında **2 lead'li** (`claude`+`codex` role=lead) + `parallel_plan=true` + `parallel_plan_rank=true` config ile tekrar çalıştırıldı.

**Teknik sonuç — mekanizma doğru çalıştı:**
- 2 plan üretildi, isimsizleştirildi (`Plan A`=claude, `Plan B`=codex — ama rankerlara hiç açıklanmadı).
- 3 sağlayıcı da (claude, codex, google) sıralama yaptı.
- Borda agregasyonu doğru hesaplandı: **Plan B (codex) 5 puan / Plan A (claude) 4 puan**, `ranked_by=3` her ikisi için.

**Ama genel güven 0.85'ten 0.45'e düştü — kök neden Faz 1 değil, test kurgusunun kendisiydi:**
`KONSEY_HOME` ortam değişkeni sadece config dosyasının konumunu değil, düğümlerin kanıt-okuma kökünü de belirliyor. Geçici bir scratch dizinine işaret edince:
- Claude "bu oturumda araç kullanmam kısıtlandı" dedi (plain-text zorlaması — `adapters.py`'deki mevcut `claude` profilinin `prompt_prefix` tasarımı).
- Codex "council/graph.py workspace'te yoktu, `rg --files` bulamadı" dedi.

İkisi de gerçek kodu okuyamadan konuştu ve bazı ayrıntıları uydurdu (olmayan `parallel_plan_candidates`/`peer_rankings` alan adları gibi — gerçek alan adı `plan_ranking`). **Konseyin kendi VERIFY+DECIDE mekanizması bunu doğru yakaladı:** VERIFY `VERDICT: FAIL` döndü (yanlış alan adlarını + "dashboard zaten var" yanlış iddiasını somut olarak işaretledi), bir dissent kaydedildi, nihai güven 0.7 eşiğinin altına (0.45) düştü — yani sistem "bu karara güvenme" dedi, ki doğruydu.

**Ders:** Konseyi izole bir config ile "double call" olarak karşılaştırmak için `KONSEY_HOME` override yerine gerçek `council.local.toml`'u geçici yedekleyip-değiştirip-geri-yükleme gibi daha temiz bir yöntem gerekiyor (riskli ama doğru kanıt üretir) — ya da `konsey run`'a config dosyasını council_home'dan bağımsızlaştıran bir `--config` bayrağı eklenmesi ayrı bir küçük iyileştirme adayı.

## 8. Mevcut Durum

- ✅ Faz 1 kodlandı, test edildi, commit edildi (`0c676bf`), gerçek `council.local.toml` **dokunulmadan** orijinal haline döndürüldü (yalnızca varsayılan `parallel_plan_rank=false` ile çalışıyor, hiçbir davranış değişmedi).
- ✅ Faz 1'in çekirdek mekanizması (anonimleştirme + Borda) canlı bir çalıştırmada doğru çalıştığı kanıtlandı.
- ❌ **Faz 2 (skor entegrasyonu) — kullanıcı tarafından İPTAL EDİLDİ (2026-07-11).** `consensus_bonus`'a bağlama hiç yapılmayacak; `plan_ranking` kalıcı olarak sadece REPORT-only/danışma amaçlı kalacak. `decide.py` bu alana bir daha asla dokunmamalı — mimari karar kesinleşti.
- ⏳ "Double call" karşılaştırma yöntemi düzeltilmeli (KONSEY_HOME yerine güvenli bir alternatif) — bir sonraki denemede ele alınacak.
- ⏳ `council/dashboard.py` — ayrı, önceden bilinmeyen bir Phase 2 açığı olarak `KNOWN_ISSUES.md`'de kayıtlı.
- 📌 PR: bu commit henüz `prfork` remote'una push edilmedi (sadece local, `master` = PR #29 branch'i, origin'in 13 commit ilerisinde).

## 9. Kaynaklar

- `github.com/karpathy/llm-council` (README + `backend/{council,config,openrouter}.py`, `gh api` ile çekildi)
- Konsey run oturumu: `28d9a879-bc24-4b3a-9518-98e3ab5fc9f7` (ilk değerlendirme, güven 0.85)
- Commit: `0c676bfef80661c23368bd9acfc53cf990330f00`
- `tests/test_rank_plans.py`, `CHANGELOG.md`, `KNOWN_ISSUES.md` (bu repo içinde)
