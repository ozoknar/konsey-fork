# Gizlilik & Telemetri

## Özet
Konsey **varsayılan olarak hiçbir veri göndermez**. Telemetri tamamen **opt-in**'dir:
yalnız kurulumda açıkça kabul ederseniz, **anonim kullanım metadata**'sı toplanır.
Kabul etmeseniz de araç **tam işlevle** çalışır.

## Veri sorumlusu
**Emediquality Bilişim Teknolojileri A.Ş.** (KVKK kapsamında veri sorumlusu).
İletişim / talepler (veri sorumlusu): **drhakankilic@gmail.com**

## Toplanan veriler (yalnız `KONSEY_TELEMETRY=on` ise)
Tamamı **anonim metadata** — kişi veya cihaz tanımlamaz:

| Alan | Örnek | Not |
|---|---|---|
| `install_id` | rastgele UUID | Kuruluma özel, kişiye değil. İstediğinizde silebilirsiniz (`.konsey_id`) |
| `event` / `command` | `council_run`, `recent` | Hangi özelliğin kullanıldığı |
| `duration_ms`, `exit_code`, `error_type` | `2400`, `0` | Performans + hata teşhisi |
| `risk_class` | `internal` | Sınıf etiketi (içerik DEĞİL) |
| `providers_count`, `security_level` | `2`, `medium` | Yapılandırma profili |
| `konsey_version`, `os`, `py` | `0.1.0`, `Darwin`, `3.12` | Sürüm/ortam |

## ASLA toplanmayanlar
- Görev metni, prompt, model çıktısı
- Dosya içeriği, dosya yolları, repo adları
- PII, sağlık verisi (PHI), API key / secret / token
- İsim, e-posta, IP-tabanlı kimlik

> **Çift güvenlik ağı:** Telemetri istemcisi yalnız izin listesindeki (`_ALLOWED`) alanları
> gönderir; ek olarak her string alan gateway secret-tarayıcısından geçer ve eşleşirse
> `[redacted]` olur (`orchestrator/telemetry.py`).

## Rıza ve kontrol
- **Açmak:** kurulumda sorulur, veya `.env`'de `KONSEY_TELEMETRY=on`.
- **Kapatmak:** `KONSEY_TELEMETRY=off` (varsayılan). Anında durur.
- **Silmek:** `.konsey_id` dosyasını silin → bağ kopar.
- **Endpoint:** `KONSEY_TELEMETRY_ENDPOINT` boşsa hiçbir şey gönderilmez.

## Hukuki
Toplanan anonim agregat veriler ürün iyileştirme ve istatistik amaçlıdır (bkz.
[TELEMETRY.md](./TELEMETRY.md)). KVKK/GDPR uyumu için rıza opt-in, veri anonim ve
minimal tutulur. Yayın öncesi gerçek iletişim adresi ve (gerekiyorsa) VERBİS kaydı eklenmelidir.
