# AI Ar-Ge Raporu — Complete-Agentic-AI-Course ve "End-to-End Agentic AI Pipeline" Makalesi

**Tarih:** 2026-08-01
**Proje:** Konsey (çok-ajan kanıt-temelli orchestrator)
**Kapsam:** İki dış kaynağın (bir eğitim reposu + bir mimari makale) hafif/manuel incelemesi ve Konsey'in mevcut koduyla karşılaştırılması.
**Sonuç:** Somut bir uygulama fikri henüz yok — bu rapor bir **gözlem/bulgu kaydı**dır, 2026-07-11 raporundaki gibi konseyin kendi 9-durumlu karar döngüsünden geçirilmiş resmi bir "UYGULA" kararı değildir (bkz. §4 Metodolojik Not).

---

## 1. Motivasyon

Kullanıcı iki dış kaynağı paylaştı ve konseye kıyasla değerlendirilmesini istedi:
1. `github.com/entbappy/Complete-Agentic-AI-Course`
2. `machinelearningmastery.com/the-end-to-end-agentic-ai-pipeline/`

## 2. İnceleme 1 — Complete-Agentic-AI-Course

WebFetch ile repo sayfası incelendi (GitHub MCP kapsamı bu session'da yalnızca `ozoknar/*` ile sınırlı olduğundan `add_repo` başarısız oldu — cross-tier kısıtlama; bu yüzden salt okunur WebFetch kullanıldı).

**Bulgu:** Bu bir **eğitim/kurs deposu**, üretim sistemi değil. LangChain, LangGraph, Pydantic üzerine öğretici kod örnekleri (tek-ajan, çoklu-ajan araştırma sistemi, async programlama, mülakat hazırlığı notları) + birkaç demo proje (TripMate AI, BappyGPT, AgentWriter-AI). 70 yıldız, 23 commit — küçük ölçekli, tutorial amaçlı.

**Değerlendirme:** Konsey ile doğrudan karşılaştırılabilir bir rakip değil. Konsey zaten LangGraph üzerine kurulu; kurs bu framework'ü öğretiyor. `LangChain-Multi-Agent-Research-System` alt klasörü ilerde ilham için tekrar bakılabilir ama şu an somut bir taşınabilir fikir tespit edilmedi.

## 3. İnceleme 2 — "The End-to-End Agentic AI Pipeline" (MachineLearningMastery)

WebFetch ile makale özetlendi. Makale bir ürün değil, genel bir **mimari rehber**: üretimde çalışan ajanların 7 katmanlı bir pipeline'a ihtiyacı olduğunu öne sürüyor:

1. **Perception** — heterojen girdileri (metin/webhook/dosya) normalize eden katman.
2. **Memory** — iki katmanlı: **Working Memory** (oturum-ömürlü) + **Episodic Memory** (vektör-tabanlı, anlam-benzerliğiyle sorgulanan uzun-vadeli).
3. **Reasoning & Planning** — yan etkisiz, sadece plan nesnesi üretir.
4. **Tool Execution** — girdi doğrulama + timeout budget + **idempotency** (tekrar eden çağrılar cache'den döner).
5. **Orchestration** — adım sırası, durum koşulları, adım limitleri (LangGraph/CrewAI gibi framework'lerle).
6. **Guardrails** — allow-list, maliyet tavanı, geri-dönülemez işlem için insan onayı, prompt-injection savunması.
7. **Observability** — yapılandırılmış, zaman damgalı, trace-level loglama.

Çekirdek döngü: `Goal → Perception → Reasoning → Planning → Action → Observation → Memory Update`, Guardrails+Observability bu döngüyü saran wrapper katmanlar olarak tanımlanıyor.

## 4. Konsey ile Karşılaştırma

Konsey kodu (`council/graph.py`, `execute.py`, `learn.py`, `gateway.py`, `audit.py`, `exec_policy.py`) grep ve doğrudan okuma ile taranarak makaledeki 7 katmanla eşleştirildi:

| Makale katmanı | Konsey karşılığı | Durum |
|---|---|---|
| Guardrails | PREFLIGHT + `exec_policy.py` + secret-scrub + allow-list | Konsey daha katı (fail-closed) |
| Reasoning/Planning | PLAN → CRITIQUE → SYNTHESIZE | Konsey daha güçlü — adversarial critique makalede yok |
| Action/Tool Execution | EXECUTE (worktree izolasyonu, timeout `execute.py:85`) | Var; **idempotency/cache yok** |
| Observation/Verify | VERIFY (producer≠verifier) | Konsey daha katı — makale bunu ayrı katman yapmamış |
| Observability | `audit.py` (append-only DuckDB) | Konsey daha denetlenebilir |
| Memory | `learn.py` (`.prometheus/LESSONS.md`, düz metin, opt-in `learn_from_repo`) | **Zayıf nokta** — vektör-tabanlı episodic memory yok, working/episodic ayrımı yok |
| Perception | Yok | **Eksik** — çoklu-kaynak (webhook/dosya/metin) girdi normalizasyon katmanı yok |

**Sonuç:** Makale Konsey'e "üstün" bir sistem değil (zaten karşılaştırılabilir bir ürün de değil), ama Konsey'in gerçekten zayıf olduğu üç somut noktaya işaret ediyor:
1. `execute.py`'de tool-call **idempotency** yok — tekrarlı ağ hatalarında güvenli değil.
2. `learn.py` düz-metin, **vektör-tabanlı episodic memory** yok.
3. Ayrı bir **Perception/normalizasyon** katmanı yok (bugüne kadar ihtiyaç da doğmadı — Konsey'in girdisi zaten tek bir görev metni).

## 5. Metodolojik Not — 2026-07-11 Raporundan Farkı

2026-07-11 tarihli rapor (`AR-GE-RAPORU-2026-07-11-llm-council-adaptasyonu.md`), konseyin kendi `konsey run` çağrısıyla, gerçek 3-sağlayıcı quorum'u ve `decide.py`'nin kanıt-ağırlıklı formülünden geçirilerek resmi bir "UYGULA" kararına varmıştı. **Bu rapor öyle değil** — sohbet içi manuel araştırma (WebFetch + grep + kod okuma), konseyin kendi karar mekanizması çağrılmadı. Bu nedenle burada bir implementasyon kararı **yok**; yalnızca ileride değerlendirilebilecek üç aday bulgu kaydedildi (§4).

## 6. Öneri / Sıradaki Adım

Kullanıcı isterse bu üç bulgudan biri (en ucuz ve en somut olanı: `execute.py`'ye idempotency eklemek) için konseyin kendi `konsey run` döngüsünden geçirilmiş resmi bir değerlendirme + dar kapsamlı implementasyon başlatılabilir — 2026-07-11 raporundaki Faz 1/Faz 2 metodolojisiyle aynı disiplinde.

## 7. Kaynaklar

- `github.com/entbappy/Complete-Agentic-AI-Course` (WebFetch ile görüntülendi)
- `https://machinelearningmastery.com/the-end-to-end-agentic-ai-pipeline/` (WebFetch ile görüntülendi)
- Konsey kodu: `council/graph.py`, `council/execute.py`, `council/learn.py`, `council/gateway.py`, `council/audit.py` (bu repo, doğrudan okundu)
