"""Çekirdek tam-akış testi — PLAN→MEMORY, sahte adapter (LLM yok, gerçek DB temp)."""
import sys
from pathlib import Path

import pytest

_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root))


def test_graph_full_flow_with_fake_adapters(monkeypatch, tmp_path):
    pytest.importorskip("langgraph")
    pytest.importorskip("duckdb")
    monkeypatch.setenv("KONSEY_DB", str(tmp_path / "t.duckdb"))
    monkeypatch.setenv("KONSEY_SECURITY_LEVEL", "medium")

    from orchestrator import graph
    from orchestrator.adapters import AgentResult

    class _Fake:
        def run(self, prompt, timeout=180):
            return AgentResult("fake", "VERDICT: PASS\nplan ok", 0, 0.0, True, "h")

    fakes = {"fakelead": _Fake(), "fakeres": _Fake()}
    monkeypatch.setattr(graph, "ADAPTERS", fakes)
    monkeypatch.setattr(graph, "available", lambda: {"fakelead": True, "fakeres": True})
    monkeypatch.setattr(
        graph, "pick",
        lambda role, avail=None, exclude=(): next((n for n in fakes if n not in exclude), None))

    final = graph.build().invoke({"task": "iki sayıyı topla", "project_hint": ""},
                                 config={"recursion_limit": 60})
    assert final.get("report")               # rapor üretildi
    assert "decision" in final               # karar var
    assert final.get("providers_ok", 0) >= 1  # sahte sağlayıcılar çalıştı
