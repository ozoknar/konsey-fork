# Agent Adapters — Vendor-Neutral Düğüm Kaydı

> İlke: Hiçbir ajan ismi orkestratör mantığına sertçe gömülmez. Düğümler bu kayıt üzerinden
> çağrılır. Sağlayıcı değişimi = bu dosya/adapter değişir, mimari değil (`orchestrator/adapters.py`).

Konsey en az **1** sağlayıcıyla çalışır (varsayılan; `KONSEY_PROVIDERS_MIN`). Tam çapraz-doğrulama
için **≥2 bağımsız sağlayıcı** önerilir. Aşağıdaki 3 düğüm referans yapılandırmasıdır; biri/ikisi
yoksa konsey kalanlarla yürür ve raporda not düşer.

## CLAUDE_NODE — Architect / Writer / Lead Orchestrator
- **provider:** anthropic
- **runtime:** Claude Code (interaktif `/konsey`) veya `claude -p` (headless)
- **role:** mimari, çok-dosyalı reasoning, sentez, final implementation, oturum yönetimi
- **invoke:** doğrudan (orkestratör = Claude)
- **status:** referans-aktif

## CODEX_NODE — Critic / Sandbox
- **provider:** openai
- **runtime:** Codex CLI (`codex exec`) veya Claude Code `codex` plugin
- **role:** adversarial review, edge-case, güvenlik analizi, izole sandbox denemesi
- **invoke:** `codex:rescue` skill ya da `codex exec` — orkestratör Codex'e görev devreder
- **write_scope:** yok (üretim yazımı yetkisi yok)
- **status:** opsiyonel (kuruluysa otomatik algılanır)

## GOOGLE_NODE — Researcher / 3. göz
- **provider:** google
- **runtime:** Antigravity CLI (`agy -p`) headless; güvenli mod `agy --sandbox -p`
- **role:** geniş-bağlam araştırma, divergent fikir üretimi, kaynak doğrulama
- **write_scope:** yok — research-only (`--sandbox` önerilir)
- **status:** opsiyonel (kuruluysa otomatik algılanır)

## JUROR_NODE — Tie-Breaker (opsiyonel)
- **provider:** anthropic | google (ucuz model: Haiku / Flash)
- **role:** anlaşmazlıkta kanıtları sıralar; **karar vermez**, insan onayına hazırlar
- **status:** on-demand

---

## Geçerli konsey kontrolü
`orchestrator/adapters.py:available()` her sağlayıcının çağrılabilirliğini kontrol eder.
Aktif sağlayıcı sayısı `KONSEY_PROVIDERS_MIN`'in altındaysa orkestratör durur ve bildirir.

## A2A — ajan-ilişkisi protokolü (yerel + opsiyonel peer)
A2A bu konseyi dışarıdan çağrılabilir kılar. Varsayılan **localhost'a bağlı** (güvenli);
cross-machine köprü değildir.
- **Kimlik:** `a2a/agent-card.json` (risk_profile_max=internal).
- **Sun:** `bin/konsey-a2a-serve` → `127.0.0.1:8787`. A2A üstünden yalnız ≤internal otomatik çalışır.
- **İstemci:** `orchestrator/a2a_client.py` — `a2a_peers.json`'daki peer'lara erişir (varsayılan boş).
