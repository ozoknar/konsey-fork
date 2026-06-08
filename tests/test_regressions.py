"""Regresyon guard'ları — adapter refactor + concurrency sonrası kırılmayı yakala."""
import sys
from pathlib import Path

import pytest

_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root))


def test_capture_imports():
    """adapters refactor'unda ClaudeAdapter kaldırıldı → capture ona bağlı KALMAMALI."""
    pytest.importorskip("duckdb")
    import orchestrator.capture  # noqa: F401  (ImportError fırlatırsa regresyon)


def test_lead_never_none_even_with_zero_providers():
    """_lead 0 sağlayıcıda bile None döndürmemeli (ADAPTERS fallback)."""
    pytest.importorskip("langgraph")
    from orchestrator import graph
    assert graph._lead({"x": False, "y": False}) is not None


def test_audit_has_lock_retry():
    """Cross-process lock fix: audit._connect retry helper'ı var olmalı."""
    pytest.importorskip("duckdb")
    from orchestrator import audit
    assert hasattr(audit, "_connect")


def test_bridge_dir_configurable(tmp_path, monkeypatch):
    """Dispatch köprü dizini KONSEY_BRIDGE_DIR ile yapılandırılabilmeli (hardcoded değil)."""
    pytest.importorskip("langgraph")
    import importlib
    monkeypatch.setenv("KONSEY_BRIDGE_DIR", str(tmp_path / "br"))
    from orchestrator import dispatch
    importlib.reload(dispatch)
    assert str(tmp_path / "br") in str(dispatch.BRIDGE)
