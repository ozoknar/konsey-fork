"""A2A istemcisi — konseyin uzak peer'lara (opsiyonel) erişimi.

Peer kaydı: a2a_peers.json. Bir peer disabled veya url boşsa çağrı INERT döner (graceful).
Hassas (phi/local) işler, yapılandırılmışsa özel bir peer'a DELEGE edilebilir.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PEERS = ROOT / "a2a_peers.json"


def _peers() -> dict:
    if not PEERS.exists():
        return {}
    return json.loads(PEERS.read_text(encoding="utf-8")).get("peers", {})


def list_peers() -> dict:
    return {k: {"enabled": v.get("enabled", False), "url": v.get("url", ""),
                "capabilities": v.get("capabilities", [])}
            for k, v in _peers().items()}


def _get(url: str, timeout: int = 10) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read())


def _post(url: str, payload: dict, timeout: int = 600) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def get_card(peer: str) -> dict:
    p = _peers().get(peer)
    if not p or not p.get("enabled") or not p.get("url"):
        return {"status": "inert", "reason": f"peer '{peer}' yapılandırılmamış/devre dışı"}
    try:
        return _get(p["url"].rstrip("/") + "/.well-known/agent-card.json")
    except urllib.error.URLError as e:
        return {"status": "unreachable", "reason": str(e)}


def delegate(peer: str, task: str, project_hint: str = "") -> dict:
    """Bir görevi uzak peer'a delege et (opsiyonel; ör. hassas iş → özel peer)."""
    p = _peers().get(peer)
    if not p or not p.get("enabled") or not p.get("url"):
        return {"status": "inert",
                "reason": f"peer '{peer}' yapılandırılmamış/devre dışı — endpoint açılınca a2a_peers.json'a gir"}
    try:
        return _post(p["url"].rstrip("/") + "/a2a/task", {"task": task, "project_hint": project_hint})
    except urllib.error.URLError as e:
        return {"status": "unreachable", "reason": str(e)}


if __name__ == "__main__":
    print(json.dumps(list_peers(), ensure_ascii=False, indent=2))
