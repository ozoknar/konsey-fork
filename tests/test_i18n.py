"""i18n testleri — locale-farkında en/tr seçimi."""
import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root))


def _load():
    import importlib
    from orchestrator import i18n
    importlib.reload(i18n)
    return i18n


def test_default_english(monkeypatch):
    for v in ("KONSEY_LANG", "LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.setenv(v, "en_US.UTF-8")
    i18n = _load()
    assert i18n.current_lang() == "en"
    assert "Doctor" in i18n.t("doctor.title") and "kurulum" not in i18n.t("doctor.title")


def test_turkish_when_locale_tr(monkeypatch):
    monkeypatch.setenv("KONSEY_LANG", "tr_TR.UTF-8")
    i18n = _load()
    assert i18n.current_lang() == "tr"
    assert "kurulum" in i18n.t("doctor.title")


def test_format_args(monkeypatch):
    monkeypatch.setenv("KONSEY_LANG", "en")
    i18n = _load()
    assert "3" in i18n.t("doctor.multi", n=3)
