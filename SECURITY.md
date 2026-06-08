# Güvenlik Politikası

## Açık bildirimi
Güvenlik açığı bulursanız lütfen **public issue açmayın**. Repo sahibine özel kanaldan
(e-posta/güvenli iletişim) bildirin. Düzeltme yayınlanana kadar detay paylaşılmaz.

## Tasarım ilkeleri
- **Secret yönetimi:** API key/token repoda tutulmaz. Yerelde `.env` (gitignore'lu) veya
  OS keychain (`bin/konsey-keychain.sh`). `.gitleaks.toml` ile taranır.
- **PII/PHI gateway:** `orchestrator/gateway.py` girdi/çıktıda secret + PII + sağlık-verisi
  desenlerini tarar; `phi`/secret tespitinde iş bloklanır (opsiyonel sıkı preset).
- **A2A:** Varsayılan `127.0.0.1` (localhost). Localhost dışına bind, kasıtlı yapılandırma
  ister; kimlik doğrulamasız public bind önerilmez.
- **Append-only audit:** Kararlar/kanıtlar değiştirilemez (denetlenebilirlik).

## Kapsam dışı
Üretilen runtime artefaktları (`council.duckdb`, `dashboard.html`, `logs/`, `sessions/`)
oturum verisi içerebilir; bunlar `.gitignore`'dadır ve yayınlanmaz.
