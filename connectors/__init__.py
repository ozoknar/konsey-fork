"""Konsey connectors — platform mesaj kanalları (opt-in, config-driven).

Her connector gelen mesajı alır → risk-gate (preflight) → izinliyse council çalıştırır → yanıtlar.
Gate authoritative: phi/production/secret otomatik kanaldan ÇIKMAZ, insan onayına yönlendirilir.
Sağlayıcılar gibi opt-in: connectors.toml'da enabled + auth_env yoksa connector devre dışı.
"""
