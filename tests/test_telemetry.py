"""Telemetri güvenlik testleri: opt-in + allowlist + secret redaksiyon."""
import importlib.util
import os
import sys
import types
from pathlib import Path

_root = Path(__file__).resolve().parent.parent


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, _root / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# gateway'i 'orchestrator.gateway' olarak yükle ki telemetry'nin 'from .gateway' importu çözülsün
pkg = types.ModuleType("orchestrator")
pkg.__path__ = [str(_root / "orchestrator")]
sys.modules["orchestrator"] = pkg
gw = _load("orchestrator.gateway", "orchestrator/gateway.py")
tel = _load("orchestrator.telemetry", "orchestrator/telemetry.py")


def test_disabled_by_default(monkeypatch=None):
    os.environ.pop("KONSEY_TELEMETRY", None)
    assert tel.enabled() is False


def test_enabled_only_on_explicit_consent():
    os.environ["KONSEY_TELEMETRY"] = "on"
    assert tel.enabled() is True
    os.environ["KONSEY_TELEMETRY"] = "off"
    assert tel.enabled() is False


def test_safe_redacts_secret():
    assert tel._safe("api_key=sk-proj-abcdef1234567890XYZ") == "[redacted]"


def test_safe_truncates_long_string():
    assert len(tel._safe("x" * 500)) <= 64


def test_safe_keeps_numbers():
    assert tel._safe(42) == 42


def test_emit_noop_without_consent():
    os.environ["KONSEY_TELEMETRY"] = "off"
    # rıza yoksa endpoint olsa bile no-op; istisna fırlatmamalı
    os.environ["KONSEY_TELEMETRY_ENDPOINT"] = "http://127.0.0.1:1/nope"
    tel.emit("council_run", status="done", task="GİZLİ İÇERİK")  # task allowlist'te değil → atılır
    os.environ.pop("KONSEY_TELEMETRY_ENDPOINT", None)
