"""Council Gateway — Anayasa Madde 5.1 & 8'in uygulayıcısı.

PREFLIGHT'ta: risk sınıflandırma + KVKK/PII/secret tarama + bütçe politikası.
phi/secret tespiti → konseye gitmez, insan onayı / local pipeline.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

# --- Risk sınıflandırma (COUNCIL.md §7 + Anayasa EK-A ile uyumlu) ---
# PHI-VERİ göstergeleri (gerçek hasta verisi/görüntü) → phi/blocked. Proje ADI tek başına DEĞİL.
PHI_DATA = re.compile(
    r"\b(hasta|patient|dicom|görüntü|mr\b|mr[ıi]\b|tomografi|tıbbi rapor|rapor metni|"
    r"teşhis|tanı|mrn|tc kimlik|protokol no|biyometrik|kesit|lezyon|anamnez|epikriz)\b",
    re.IGNORECASE,
)
# PHI-PROJE adları → tek başına phi tetiklemez; yalnız "gerçek veri gönderme" notu düşülür.
# Opsiyonel/kullanıcıya özel: gitignore'lu .env'de KONSEY_PHI_PROJECTS="proje1|proje2".
_phi_projects = os.getenv("KONSEY_PHI_PROJECTS", "").strip()
PHI_PROJECT = re.compile(rf"\b({_phi_projects})\b", re.IGNORECASE) if _phi_projects else None
PROD_HINTS = re.compile(
    r"\b(production|prod|canlı|deploy|railway|master'a push|veritaban|database|"
    r"migration|withdraw|emir ver|live trade|gerçek para|credential rotat)\b",
    re.IGNORECASE,
)
PII_HINTS = re.compile(r"\b(çalışan|personel|iletişim listesi|telefon|e-?posta listesi|özlük)\b", re.IGNORECASE)
PUBLIC_SIGNAL = re.compile(
    r"\b(public|açık kaynak|dökümantasyon|readme|mimari|architecture|karşılaştır|compare|"
    r"özetle|summarize|iyileştir|improve)\b", re.IGNORECASE,
)

# --- Secret / kimlik tarayıcıları (çıktı da, girdi de taranır) ---
SECRET_PATTERNS = {
    "api_key_generic": re.compile(r"\b(sk-[A-Za-z0-9]{20,}|rapi_[A-Za-z0-9]{16,}|AIza[0-9A-Za-z_\-]{30,}|gsk_[A-Za-z0-9]{20,})"),
    "bearer": re.compile(r"\bBearer\s+[A-Za-z0-9\._\-]{20,}"),
    "tc_kimlik": re.compile(r"\b[1-9][0-9]{10}\b"),            # 11 haneli TC (kaba)
    "private_key": re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "email": re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"),
    # modern formatlar — TEK KAYNAK: gate (capture) + mask + preflight/dispatch ortak kullanır (F3/F10)
    "anthropic": re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}"),
    "stripe": re.compile(r"\b(?:sk|pk|rk)_(?:live|test)_[A-Za-z0-9]{16,}"),
    "aws_akia": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "github_pat": re.compile(r"\bgh[posr]_[A-Za-z0-9]{20,}\b"),
    "slack": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    "openai_new": re.compile(r"\bsk-(?:proj|svcacct|admin)-[A-Za-z0-9_\-]{20,}\b"),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b"),
    "secret_kv": re.compile(r"(?i)\b(?:api[_-]?key|secret|token|password|passwd|pwd|client[_-]?secret)\b\s*[:=]\s*['\"]?(?!process\.env|import\.meta|your_|xxx+|<|\$\{|example|placeholder|none|null|true|false|redacted)[A-Za-z0-9_\-\.]{12,}"),
}

# Bütçe politikası — risk profiline göre (Madde 9)
BUDGET = {
    "public":     dict(max_iter=5,  max_wall_s=900,  max_cost=2.0,  human_required=False),
    "internal":   dict(max_iter=5,  max_wall_s=900,  max_cost=2.0,  human_required=False),
    "pii":        dict(max_iter=4,  max_wall_s=600,  max_cost=2.0,  human_required=False),
    "phi":        dict(max_iter=3,  max_wall_s=600,  max_cost=1.0,  human_required=True),
    "production": dict(max_iter=3,  max_wall_s=900,  max_cost=2.0,  human_required=True),
}


@dataclass
class GatewayResult:
    risk: str
    budget: dict
    blocked: bool = False
    block_reason: str = ""
    secrets_found: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def classify_risk(task: str, project_hint: str = "") -> str:
    blob = f"{task} {project_hint}"
    if PROD_HINTS.search(blob):
        risk = "production"
    elif PHI_DATA.search(blob):          # yalnız gerçek hasta-verisi göstergesi phi tetikler
        risk = "phi"
    elif PII_HINTS.search(blob):
        risk = "pii"
    else:
        risk = "internal"
    # Proje adı tek başına phi yapmaz; public sinyali varsa internal→public (EK-A ile hizalı)
    if risk == "internal" and PUBLIC_SIGNAL.search(blob):
        risk = "public"
    return risk


def scan_secrets(text: str) -> list[str]:
    found = []
    for name, pat in SECRET_PATTERNS.items():
        if pat.search(text or ""):
            found.append(name)
    return found


def preflight(task: str, project_hint: str = "") -> GatewayResult:
    risk = classify_risk(task, project_hint)
    budget = BUDGET[risk]
    secrets = scan_secrets(f"{task} {project_hint}")   # F10: project_hint de LLM'e gidiyor → o da taranır
    res = GatewayResult(risk=risk, budget=dict(budget), secrets_found=secrets)

    if risk == "phi":
        res.blocked = True
        res.block_reason = (
            "PHI sınıfı: hasta verisi tüketici LLM'e gönderilemez (Madde 13.1). "
            "Local pipeline (yerel model) + insan onayı gerekir."
        )
    if secrets:
        res.blocked = True
        res.block_reason = (res.block_reason + " | " if res.block_reason else "") + \
            f"Secret/kimlik tespit edildi: {secrets} (Madde 13.3) — maskelenmeden konseye gitmez."
    if risk in ("phi", "production"):
        res.notes.append("İnsan onayı zorunlu (Madde 7.3).")
    if PHI_PROJECT and PHI_PROJECT.search(f"{task} {project_hint}") and risk != "phi":
        res.notes.append("PHI projesi: tartışma serbest ama GERÇEK hasta verisi/görüntü konseye gönderilmez.")
    return res
