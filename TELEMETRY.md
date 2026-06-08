# Telemetri Mimarisi & Veri Modeli

> İstemci tarafı bu repodadır (`orchestrator/telemetry.py`). Backend (ingest + DB) ayrı
> bir servistir; bu doküman sözleşmeyi (event şeması) ve referans mimarisini tanımlar.

## İstemci → Backend sözleşmesi
İstemci, opt-in ise `KONSEY_TELEMETRY_ENDPOINT`'e tek bir JSON POST atar:

```json
{
  "event": "council_run",
  "install_id": "uuid-v4",
  "konsey_version": "0.1.0",
  "os": "Darwin",
  "py": "3.12.5",
  "status": "done",
  "risk_class": "internal",
  "providers_count": 2,
  "security_level": "medium",
  "duration_ms": 2400
}
```
İstemci `_ALLOWED` dışındaki hiçbir alanı göndermez; string alanlar secret-tarayıcıdan geçer.

## Referans backend (minimal)
```
[CLI istemci] --HTTPS POST--> [ingest API] --> [event tablosu] --> [agregat görünümler]
```
- **Ingest API:** stateless; doğrulama (allowlist şema), rate-limit, `install_id` hash'le.
- **Depolama:** append-only `events(install_id, event, ts, os, version, security_level,
  risk_class, providers_count, duration_ms, status)`. Ham içerik kolonu YOK.
- **Anonimlik:** `install_id` sunucuda tuzlanmış hash'lenir; ham UUID saklanmaz.
- **Saklama:** süreli (ör. 13 ay) + agregasyon sonrası satır-seviyesi silme.

## Gelir modeli (yön)
Toplanan **anonim agregat**, sloppy kişisel-veri toplamadan değer üretir:
1. **Açık-kaynak ücretsiz** çekirdek (benimsenme + güven).
2. **Konsey Cloud / Pro (abonelik):** hosted audit dashboard, ekip analizi, agregat
   benchmark ("ekibin konsey kullanım/başarı oranı"), gelişmiş preset yönetimi.
3. **Sektör benchmark raporları (B2B):** anonim agregat eğilimler (hangi görev tipleri,
   başarı/dissent oranları) — ham veri değil, istatistik.
4. **Enterprise:** self-hosted telemetri + SSO + SLA + özel guardrail preset'leri.

> İlke: gelir **agregat içgörüden** gelir, kullanıcının görev içeriğinden değil. Bu, ürünün
> "KVKK/güvenlik" konumlandırmasını korur ve veriyi hukuken satılabilir kılar.

## Yayın öncesi checklist (backend)
- [ ] Gerçek ingest endpoint + TLS
- [ ] `.env.example`'da gerçek `KONSEY_TELEMETRY_ENDPOINT`
- [ ] PRIVACY.md'de gerçek iletişim + (gerekirse) VERBİS
- [ ] Rate-limit + şema doğrulama + `install_id` tuzlu-hash
- [ ] Saklama/silme politikası + opt-out işleme
