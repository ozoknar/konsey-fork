"""Config-driven sağlayıcı katmanı testleri: defaults, role seçimi, exclude."""
import importlib.util
import sys
import types
from pathlib import Path

_root = Path(__file__).resolve().parent.parent


def _load_adapters():
    pkg = types.ModuleType("orchestrator")
    pkg.__path__ = [str(_root / "orchestrator")]
    sys.modules["orchestrator"] = pkg
    spec = importlib.util.spec_from_file_location(
        "orchestrator.adapters", _root / "orchestrator" / "adapters.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules["orchestrator.adapters"] = m
    spec.loader.exec_module(m)
    return m


def test_defaults_cover_core_roles():
    a = _load_adapters()
    roles = {s.get("role") for s in a.load_providers().values()}
    assert {"architect", "critic", "researcher"} <= roles


def test_pick_by_role():
    a = _load_adapters()
    avail = {"claude": True, "codex": True, "google": True}
    assert a.pick("critic", avail) == "codex"
    assert a.pick("researcher", avail) == "google"
    assert a.pick("architect", avail) == "claude"


def test_pick_excludes_producer():
    a = _load_adapters()
    avail = {"claude": True, "codex": True, "google": True}
    # researcher (google) hariç tut → researcher rolü yine google; exclude → fallback farklı
    assert a.pick("researcher", avail, exclude=("google",)) != "google"


def test_pick_none_when_unavailable():
    a = _load_adapters()
    assert a.pick("critic", {"claude": False, "codex": False, "google": False}) is None
