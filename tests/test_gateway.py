"""Gateway risk/PII/secret + güvenlik seviyesi testleri (saf stdlib)."""
import importlib.util
import sys
from pathlib import Path

_gw_path = Path(__file__).resolve().parent.parent / "orchestrator" / "gateway.py"
_spec = importlib.util.spec_from_file_location("gateway", _gw_path)
gw = importlib.util.module_from_spec(_spec)
sys.modules["gateway"] = gw  # py3.14 dataclass çözümü
_spec.loader.exec_module(gw)

PHI = "hastanın MR tomografi tanı raporunu özetle"
SECRET = "deploy with api_key=sk-proj-abcdef1234567890XYZ"


# --- Risk sınıflandırma (seviyeden bağımsız) ---
def test_risk_public():
    assert gw.preflight("improve the README architecture, açık kaynak").risk == "public"


def test_risk_production():
    assert gw.preflight("deploy to railway production master push").risk == "production"


def test_risk_internal():
    assert gw.preflight("refactor the orchestrator state machine").risk == "internal"


# --- strict: secret + PHI bloklar ---
def test_strict_blocks_phi():
    assert gw.preflight(PHI, level="strict").blocked


def test_strict_blocks_secret():
    r = gw.preflight(SECRET, level="strict")
    assert r.blocked and "secret_kv" in r.secrets_found


# --- medium: secret bloklar, PHI yalnız uyarır ---
def test_medium_blocks_secret():
    assert gw.preflight(SECRET, level="medium").blocked


def test_medium_warns_phi_not_block():
    r = gw.preflight(PHI, level="medium")
    assert not r.blocked
    assert any("PHI" in n for n in r.notes)


# --- weak: hiçbir şey bloklamaz ---
def test_weak_blocks_nothing():
    assert not gw.preflight(PHI, level="weak").blocked
    assert not gw.preflight(SECRET, level="weak").blocked


def test_tc_kimlik_detected_strict():
    r = gw.preflight("şu kişi 12345678901 kaydını sil", level="strict")
    assert r.blocked and "tc_kimlik" in r.secrets_found
