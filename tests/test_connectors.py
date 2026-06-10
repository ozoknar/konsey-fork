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


def test_notion_disabled_without_creds(monkeypatch, capsys):
    monkeypatch.delenv("NOTION_TOKEN", raising=False)
    monkeypatch.delenv("NOTION_DATABASE_ID", raising=False)
    from connectors import notion
    notion.run(token=None, database_id=None)      # cred yoksa graceful
    assert "devre dışı" in capsys.readouterr().out


def test_notion_title_extraction():
    from connectors import notion
    page = {"properties": {"Name": {"type": "title",
            "title": [{"plain_text": "iki sayıyı topla"}]}}}
    assert notion._title_of(page) == "iki sayıyı topla"
    assert notion._title_of({"properties": {"X": {"type": "rich_text"}}}) == ""   # başlık yok


def test_notion_seen_persists(monkeypatch, tmp_path):
    """İdempotentlik fix: seen seti diske yazılır → yeniden başlatmada spam yok."""
    from connectors import notion
    monkeypatch.setattr(notion, "_SEEN_FILE", tmp_path / "seen.json")
    notion._save_seen({"page-a", "page-b"})
    assert notion._load_seen() == {"page-a", "page-b"}


def test_slack_disabled_without_token(monkeypatch, capsys):
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    monkeypatch.delenv("SLACK_APP_TOKEN", raising=False)
    from connectors import slack
    slack.run(bot_token=None, app_token=None)
    assert "devre dışı" in capsys.readouterr().out


def test_whatsapp_disabled_without_creds(monkeypatch, capsys):
    for v in ("WHATSAPP_TOKEN", "WHATSAPP_PHONE_ID", "WHATSAPP_VERIFY_TOKEN", "WHATSAPP_APP_SECRET"):
        monkeypatch.delenv(v, raising=False)
    from connectors import whatsapp
    whatsapp.run()
    assert "devre dışı" in capsys.readouterr().out


def test_whatsapp_extract_messages_robust():
    """Güvenilmez/bozuk webhook JSON şekli çökertmemeli (council review [LOW])."""
    from connectors import whatsapp
    assert whatsapp._extract_messages("not a dict") == []
    assert whatsapp._extract_messages({"entry": "bad-shape"}) == []
    assert whatsapp._extract_messages({"entry": [{"changes": [{"value": {}}]}]}) == []
    good = {"entry": [{"changes": [{"value": {"messages": [
        {"from": "123", "text": {"body": "merhaba"}}]}}]}]}
    assert whatsapp._extract_messages(good) == [("123", "merhaba")]
