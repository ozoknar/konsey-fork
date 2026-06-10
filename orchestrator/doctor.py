"""konsey doctor — kurulum, sağlayıcı, auth, güvenlik ve telemetri durumunu gösterir.

Çıktı locale-farkında (i18n): sistem dili `tr` ise Türkçe, değilse İngilizce.
Kullanıcı "gerçekten kuruldu mu, hangi YZ ürünlerim hazır?" sorusunu tek bakışta yanıtlar.
"""
from __future__ import annotations

import os
import shutil

from . import telemetry
from .adapters import available, load_providers
from .i18n import t


def report() -> str:
    lines = [t("doctor.title"), "=" * 34]
    lines.append(t("doctor.security", level=os.getenv("KONSEY_SECURITY_LEVEL", "medium")))
    state = t("doctor.tel_on") if telemetry.enabled() else t("doctor.tel_off")
    lines.append(t("doctor.telemetry", state=state))
    lines.append("")
    lines.append(t("doctor.providers"))

    provs = load_providers()
    avail = available()
    for name, spec in provs.items():
        cmd0 = (spec.get("command") or ["?"])[0]
        auth_env = spec.get("auth_env")
        if not spec.get("enabled", True):
            status = t("doctor.disabled")
        elif shutil.which(cmd0) is None:
            status = t("doctor.no_cli", cmd=cmd0)
        elif auth_env and not os.getenv(auth_env):
            status = t("doctor.no_auth", env=auth_env)
        else:
            status = "✓ " + t("doctor.ready")
        lines.append(f"  {name:12s} [{spec.get('role', ''):10s}] {status}")

    n_ok = sum(1 for v in avail.values() if v)
    lines.append("")
    if n_ok == 0:
        lines.append("⚠ " + t("doctor.none"))
    elif n_ok == 1:
        lines.append("ℹ " + t("doctor.solo"))
    else:
        lines.append("✓ " + t("doctor.multi", n=n_ok))
    return "\n".join(lines)


def main() -> None:
    print(report())


if __name__ == "__main__":
    main()
