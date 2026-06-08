"""Gateway risk/PII/secret sınıflandırma testleri.

Saf stdlib (re + dataclasses) — venv/bağımlılık gerekmez. Sandbox doğrulamasının port'u.
"""
import importlib.util
import sys
from pathlib import Path

_gw_path = Path(__file__).resolve().parent.parent / "orchestrator" / "gateway.py"
_spec = importlib.util.spec_from_file_location("gateway", _gw_path)
gw = importlib.util.module_from_spec(_spec)
sys.modules["gateway"] = gw  # py3.14 dataclass çözümü için kayıt
_spec.loader.exec_module(gw)


def test_phi_blocks():
    r = gw.preflight("hastanın MR tomografi tanı raporunu özetle")
    assert r.risk == "phi"
    assert r.blocked


def test_secret_kv_blocks():
    r = gw.preflight("deploy with api_key=sk-proj-abcdef1234567890XYZ")
    assert r.blocked
    assert "secret_kv" in r.secrets_found


def test_tc_kimlik_detected():
    r = gw.preflight("şu kişi 12345678901 kaydını sil")
    assert r.blocked
    assert "tc_kimlik" in r.secrets_found


def test_public_not_blocked():
    r = gw.preflight("improve the README architecture docs, açık kaynak")
    assert r.risk == "public"
    assert not r.blocked


def test_production_classified():
    r = gw.preflight("deploy to railway production master push")
    assert r.risk == "production"
    assert not r.blocked


def test_internal_clean():
    r = gw.preflight("refactor the orchestrator state machine")
    assert r.risk == "internal"
    assert not r.blocked
