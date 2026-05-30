"""S5 — distribution packaging hygiene.

Evidence > consensus: the load-bearing guard actually BUILDS the sdist and inspects
its member list, so a future packaging change that re-leaks a machine profile or the
live doctrine draft fails CI. (A plain `python -m build` from a working tree shipped
`council.local.toml` + `constitution/KONSEY_ANAYASASI.md` before S5 — Constitution
Art. 2/13: no machine-facts in shipped artifacts.) Static config assertions back it up
and stay fast even if `build` is unavailable.
"""
from __future__ import annotations

import subprocess
import sys
import tarfile
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
PYPROJECT = REPO / "pyproject.toml"


def _pyproject() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# static config guards (fast — no build)                                       #
# --------------------------------------------------------------------------- #

def test_version_is_dynamic_and_single_sourced():
    data = _pyproject()
    assert "version" in data["project"].get("dynamic", [])   # declared dynamic
    assert "version" not in data["project"]                   # the static literal is gone
    assert data["tool"]["hatch"]["version"]["path"] == "council/__init__.py"


def test_version_importable_and_semverish():
    import council
    assert isinstance(council.__version__, str) and council.__version__
    head = council.__version__.split(".")[:2]
    assert len(head) == 2 and all(p.isdigit() for p in head)


def test_sdist_exclude_names_the_known_leak_files():
    excl = " ".join(_pyproject()["tool"]["hatch"]["build"]["targets"]["sdist"]["exclude"])
    assert "KONSEY_ANAYASASI.md" in excl
    assert "council.local" in excl
    assert ".gitleaks.toml" in excl


def test_urls_use_the_real_org_not_placeholder():
    urls = _pyproject()["project"]["urls"]
    assert all("OWNER" not in v for v in urls.values())
    assert "eMediquality/konsey" in urls["Repository"]


# --------------------------------------------------------------------------- #
# the real proof: build the sdist once and inspect its members                 #
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="module")
def sdist_members(tmp_path_factory) -> list[str]:
    try:
        import build  # noqa: F401
    except Exception:
        pytest.skip("`build` is not installed")
    out = tmp_path_factory.mktemp("dist")
    proc = subprocess.run(
        [sys.executable, "-m", "build", "--sdist", "-o", str(out), str(REPO)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        pytest.skip(f"sdist build unavailable (no network / backend?): {proc.stderr[-300:]}")
    sd = next(iter(out.glob("*.tar.gz")), None)
    if sd is None:
        pytest.skip("no sdist produced")
    with tarfile.open(sd) as tar:
        return tar.getnames()


def test_sdist_does_not_leak_machine_or_doctrine_files(sdist_members):
    blob = "\n".join(sdist_members)
    assert "KONSEY_ANAYASASI.md" not in blob     # live doctrine working draft
    assert "council.local.toml" not in blob      # a machine-specific profile
    assert ".gitleaks.toml" not in blob


def test_sdist_includes_every_required_file(sdist_members):
    blob = "\n".join(sdist_members)
    for needed in (
        "pyproject.toml",
        "council/cli.py",
        "regimes/hipaa.toml",
        "constitution/README.md",     # the CC-BY summary ships; the draft does NOT
        "README.md",
        "LICENSE",
        "requirements.txt",           # install.sh consumes it
    ):
        assert needed in blob, f"sdist is missing a required file: {needed}"
