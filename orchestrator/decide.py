"""Kanıt-ağırlıklı karar fonksiyonu (Anayasa Madde 7) — OYLAMA DEĞİL.

Konsensüs = sinyal. Karar gücü dış kanıt + çapraz-doğrulamadan gelir.
phi/production veya confidence<0.7 → insan onayı zorunlu.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Decision:
    confidence: float
    human_required: bool
    rationale: str


def decide(*, risk: str, n_providers_ok: int, n_evidence: int, n_crossverified: int,
           agreement: bool, unresolved_dissent: int, tool_failures: int) -> Decision:
    """
    - n_providers_ok: kaç bağımsız sağlayıcı çıktı üretti (SİNYAL, kanıt değil)
    - n_evidence: toplanan dış kanıt sayısı
    - n_crossverified: başka bir ajan/dış kaynakça doğrulanmış çıktı sayısı (gerçek ağırlık)
    - agreement: sağlayıcılar aynı sonuca mı vardı (yine sadece sinyal)
    - unresolved_dissent: çözülmemiş itiraz sayısı
    - tool_failures: araç hatası sayısı
    """
    score = 0.45
    score += min(n_crossverified, 3) * 0.15      # asıl ağırlık: dış doğrulama
    score += min(n_evidence, 3) * 0.05            # kanıt hacmi (ikincil)
    if agreement and n_providers_ok >= 2:
        score += 0.10                             # konsensüs yalnız küçük bonus (sinyal)
    score -= unresolved_dissent * 0.10
    score -= tool_failures * 0.15
    if n_crossverified == 0:
        score = min(score, 0.6)                   # dış doğrulama yoksa tavan: karar verme eşiğinin altı olabilir
    confidence = max(0.0, min(1.0, round(score, 2)))

    human = (risk in ("phi", "production")) or (confidence < 0.7)
    reasons = []
    if risk in ("phi", "production"):
        reasons.append(f"risk={risk} → insan onayı zorunlu (Md.7.3)")
    if confidence < 0.7:
        reasons.append(f"confidence={confidence} < 0.7 → insan onayı (Md.6.7)")
    if n_crossverified == 0:
        reasons.append("dış doğrulama yok → konsensüs tek başına karar değil (Md.7.2)")
    if not reasons:
        reasons.append("kanıt-ağırlıklı eşik sağlandı")
    return Decision(confidence=confidence, human_required=human, rationale="; ".join(reasons))
