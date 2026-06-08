"""Konsey orchestrator paketi.

İçe aktarıldığında kök dizindeki `.env`'i (varsa) ortama yükler — harici bağımlılık yok.
Var olan ortam değişkenleri ezilmez (setdefault).
"""
import os as _os
from pathlib import Path as _Path

_envf = _Path(__file__).resolve().parent.parent / ".env"
if _envf.exists():
    for _line in _envf.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            _os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))
