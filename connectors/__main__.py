"""konsey-connectors girişi — etkin connector'ları çalıştır.

Tek etkin connector doğrudan; birden çok varsa her biri ayrı thread'de (sessizce
yok sayma yok). Hiç etkin yoksa net mesaj. `konsey-connectors <ad>` ile zorlanabilir.
"""
from __future__ import annotations

import sys
import threading

from . import config


def _run_one(name: str, spec: dict) -> None:
    if name == "telegram":
        from . import telegram
        telegram.run(allowed_chats=spec.get("allowed_chats"))
    elif name == "notion":
        from . import notion
        notion.run()
    elif name == "slack":
        from . import slack
        slack.run()
    elif name == "whatsapp":
        from . import whatsapp
        whatsapp.run()
    else:
        print(f"Bilinmeyen connector '{name}'. Bkz. CONNECTORS.md")


def main(argv: list[str] | None = None) -> None:
    argv = argv if argv is not None else sys.argv[1:]
    names = [argv[0]] if argv else config.enabled_connectors()
    if not names:
        print("Etkin connector yok. connectors.toml'u düzenleyin "
              "(enabled=true + auth_env ortam değişkeni).")
        return
    specs = config.load()
    if len(names) == 1:
        print(f"Connector başlatılıyor: {names[0]}")
        _run_one(names[0], specs.get(names[0], {}))
        return
    print(f"{len(names)} connector çalışıyor: {', '.join(names)}")
    threads = [threading.Thread(target=_run_one, args=(n, specs.get(n, {})), daemon=True)
               for n in names]
    for th in threads:
        th.start()
    for th in threads:
        th.join()


if __name__ == "__main__":
    main()
