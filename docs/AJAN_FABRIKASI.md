# Ajan Fabrikası (Agent Factory) Mimarisi

Konsey projesi, tek bir yapay zeka modelinin kör noktalarını gidermek ve doğrulanmamış sonuçların üretime girmesini engellemek amacıyla **otonom, proaktif ve kendi kendini denetleyen (self-correcting)** bir Yapay Zeka Organizasyonu (Ajan Fabrikası) olarak tasarlanmıştır.

Bu döküman, projenin deterministik 9-durumlu LangGraph orkestrasyonunun fabrika rollerine nasıl eşlendiğini ve sistemin çalışma prensiplerini açıklamaktadır.

---

## 1. Mimari Roller ve Eşleşme (Roster Mapping)

Konsey'in iş akışı boyunca her sağlayıcı (LLM CLI), anayasaya göre belirli bir fabrika rolünü üstlenir:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            ORGANİZASYON MÜDÜRÜ                              │
│         (Director: Preflight Risk Analizi & Görev Bölme / Planlama)         │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            KOORDİNATÖR AJAN                                 │
│        (Coordinator: LangGraph Orkestrasyonu & Durum Yönetimi)              │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       ▼
┌──────────────────────────────────────┼──────────────────────────────────────┐
│                                      │                                      │
▼                                      ▼                                      ▼
┌──────────────────────────┐ ┌──────────────────────────┐ ┌───────────────────┐
│        KEŞİF AJANI       │ │    İNŞAATÇI / CODERS     │ │    QA & GÜVENLİK  │
│   (Scout: İzolasyon &    │ │    (Builder: Git Work    │ │  (QA/Verifier:    │
│    Bağımlılık Taraması)  │ │     tree Üzerinde Yürütme)│ │   Doğrulama &     │
│                          │ │                          │ │   Sınır Kapısı)   │
└──────────────────────────┘ └──────────────────────────┘ └───────────────────┘
```

### A. Organizasyon Müdürü (Director Agent)
* **Konsey Eşleşmesi:** `preflight` ve `plan` (Lead) düğümleri.
* **Görevi:** Görevin risk sınıflandırmasını (public, internal, sensitive, production) yapar ve gizli bilgi/sır taramasını tetikler. Görevi asenkron parçalara ve ilk taslak planlara böler.

### B. Koordinatör Ajan (Project Manager / Coordinator)
* **Konsey Eşleşmesi:** `Config` sınıfı, `presets.py` ve LangGraph durum makinesi (`graph.py`).
* **Görevi:** İş adımlarının sırasını, paralel çalışma süreçlerini, bütçe/süreç limitlerini ve düğümler arası veri bütünlüğünü yönetir.

### C. Keşif ve Kaynak Ajanı (Scout/Explorer Agent)
* **Konsey Eşleşmesi:** `isolation.py` ve `doctor` alt komutu.
* **Görevi:** Çalışma klasöründeki bağımlılıkları, eksik kısımları ve sağlayıcı düğümlerine sızabilecek global host yapılandırmalarını tarayıp haritalandırır.

### D. Geliştirici/İnşaatçı Ajan (Builder/Coder Agent)
* **Konsey Eşleşmesi:** `execute.py` ve `worktree.py` (`konsey do` komut yürütücüsü).
* **Görevi:** Gerekli kodlamaları yapar, yeni istekleri izole bir git worktree alanında test ederek mevcut yapıya entegre eder.

### E. Kalite Kontrol ve Güvenlik Ajanı (QA & Security Agent)
* **Konsey Eşleşmesi:** `verify.py`, `decide.py` ve `exec_policy.py`.
* **Görevi:** Kod kalitesini, güvenlik açıklarını ve sistem kararlılığını test eder. **Üreten ≠ Doğrulayan** kuralını işleterek, kod geliştiren ajandan farklı bir sağlayıcı aracılığıyla çapraz-doğrulama yapar. Yıkıcı komutları bloke eder ve hata durumunda loglarla birlikte süreci geri çevirir.

---

## 2. Çekirdek Güvenlik ve Karar Mekanizmaları

### A. Çapraz Doğrulama (Cross-Verification)
* Kodlama yapan sağlayıcı (`claude` vb.) ile doğrulama yapan sağlayıcı (`codex` vb.) **asla aynı olamaz**.
* İki bağımsız sağlayıcı bulunmadığı durumlarda sistem otomatik olarak **Danışman Modu (Advisory Mode)** seviyesine düşer, karar güven skoru tavanlanır ve çıktı "doğrulanmamış" olarak işaretlenir.

### B. Kanıt-Ağırlıklı Karar (Evidence-Weighted Decision)
Kararlar basit bir çoğunluk oylaması yerine, kanıtların ağırlıklandırıldığı bir formülle alınır:
$$\text{Skor} = \text{Taban (0.45)} + \text{Çapraz Doğrulama Bonus (+0.15)} + \text{Kanıt Bonus (+0.05)} - \text{Muhalefet (-0.10)} - \text{Hata (-0.15)}$$

### C. Düğüm Yalıtımı ve Çevre Hijyeni (PR2 Node Isolation)
Ajanların host makinedeki global yapılandırma dosyalarından ve MCP sunucularından etkilenerek bağımsızlıklarını kaybetmesini engellemek için şu yalıtımlar zorunlu kılınmıştır:
* **Google/agy:** `HOME` dizini geçici temiz bir klasöre yönlendirilir.
* **Claude:** `--strict-mcp-config` ve `--setting-sources none` bayrakları ile host MCP'leri tamamen kapatılır.
* **Codex:** `CODEX_HOME` izole edilir, `-c project_doc_max_bytes=0`, `--ignore-user-config` ve `-C` bayrakları uygulanır.
