"""Connector framework testleri — config + gate köprüsü (ağ yok)."""
import sys
from pathlib import Path


_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root))


def test_config_load_graceful_without_file():
    from connectors import config
    assert isinstance(config.load(), dict)        # connectors.toml yoksa boş, crash değil
    assert isinstance(config.enabled_connectors(), list)


def test_run_council_blocks_phi_without_llm(monkeypatch):
    """PHI strict'te bloklanır → council/LLM çağrılmadan insan-onayı mesajı döner."""
    monkeypatch.setenv("KONSEY_SECURITY_LEVEL", "strict")
    from connectors.base import run_council
    out = run_council("hastanın MR tomografi tanı raporunu özetle")
    assert "onay" in out.lower() or "çalıştırılmadı" in out.lower()


def test_telegram_disabled_without_token(monkeypatch, capsys):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    from connectors import telegram
    telegram.run(token=None)                      # token yoksa graceful, döngüye girmez
    assert "devre dışı" in capsys.readouterr().out
