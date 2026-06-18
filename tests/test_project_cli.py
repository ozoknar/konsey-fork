"""CLI wiring tests for `konsey project` (project mode subcommand).

Deterministic: the roster + provider availability are stubbed and the per-task
provider calls are faked, so the real argument parser, roster resolution, ledger
driver, and artifact writing are all exercised without a live LLM call.
"""
from __future__ import annotations

from dataclasses import replace

import council.cli as cli
import council.project as project
from council.config import ROLE_LEAD, ROLE_VERIFIER, RosterEntry, load_config


def _two_provider_cfg():
    return replace(
        load_config(),
        agents=[
            RosterEntry(name="claude", cli="claude", role=ROLE_LEAD, enabled=True),
            RosterEntry(name="codex", cli="codex", role=ROLE_VERIFIER, enabled=True),
        ],
    )


def _stub_providers(monkeypatch, *, available_map, verify_ok=True):
    monkeypatch.setattr(cli, "load_config", _two_provider_cfg)
    monkeypatch.setattr(cli, "available", lambda cfg: available_map)
    monkeypatch.setattr(project, "adapter_work_fn",
                        lambda cfg, agent, **kw: (lambda task: f"{agent} did {task.id}"))
    monkeypatch.setattr(project, "adapter_verify_fn",
                        lambda cfg, agent, **kw: (lambda task, produced: (verify_ok, "PASS" if verify_ok else "FAIL")))


def _run(tmp_path, *extra):
    args = cli.build_parser().parse_args(
        ["project", "ship the thing", "--tasks", "design;build;test",
         "--dir", str(tmp_path), "--name", "demo", *extra])
    return args.func(args)


def test_project_cli_happy_path(tmp_path, monkeypatch, capsys):
    _stub_providers(monkeypatch, available_map={"claude": True, "codex": True})
    rc = _run(tmp_path)
    assert rc == 0
    # artifacts written
    assert (tmp_path / "spec.md").read_text().startswith("# demo")
    tasks_md = (tmp_path / "tasks.md").read_text()
    assert tasks_md.count("- [x]") == 3          # all three tasks completed
    assert "claude->codex" in tasks_md           # producer != verifier recorded in the trail
    out = capsys.readouterr().out
    assert "worker=claude" in out and "verifier=codex" in out


def test_project_cli_refuses_without_two_providers(tmp_path, monkeypatch, capsys):
    # only the worker is available → cannot cross-verify → refuse (no self-certification)
    _stub_providers(monkeypatch, available_map={"claude": True, "codex": False})
    rc = _run(tmp_path)
    assert rc == 2
    assert not (tmp_path / "tasks.md").exists()


def test_project_cli_abandons_failed_task_nonzero_exit(tmp_path, monkeypatch):
    _stub_providers(monkeypatch, available_map={"claude": True, "codex": True}, verify_ok=False)
    rc = _run(tmp_path, "--max-attempts", "1")
    assert rc == 1                               # something abandoned → non-zero
    tasks_md = (tmp_path / "tasks.md").read_text()
    assert "- [x]" not in tasks_md              # nothing certified
