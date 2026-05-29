"""Scheduler backend tests (Constitution Article 15.3).

These run WITHOUT a live daemon: the systemd / schtasks / cron / launchd backends
separate pure *rendering* (string/argv builders) from *registration* (the
``subprocess`` calls). The tests assert against the rendered artifacts and, where a
register/unregister round-trip is exercised, ``subprocess.run`` is monkeypatched so
no real ``systemctl`` / ``schtasks`` / ``launchctl`` / ``crontab`` is ever invoked.

What is guaranteed here:
  * single tick-contract — every backend schedules the SAME command (``_TICK_ARGS``);
  * label/path come from the profile, not a hard-coded institution tag, and a hostile
    label can't inject path/shell separators (``sanitize_label``);
  * register is idempotent (re-running leaves exactly one entry);
  * unregister is reversible (removes exactly this backend's own artifact);
  * NullScheduler is a pure no-op (installs nothing, "removes" trivially).
"""
from __future__ import annotations

import types

import pytest

from council.platform import scheduler as S
from council.platform.scheduler import (
    DEFAULT_INTERVAL_S,
    DEFAULT_LABEL,
    CronScheduler,
    LaunchdScheduler,
    NullScheduler,
    SchtasksScheduler,
    SystemdScheduler,
    get_scheduler,
    label_from_config,
    sanitize_label,
)

# The one tick-contract every backend must schedule (Art. 15.3).
TICK_SUFFIX = "-m council.dispatch tick"


# --------------------------------------------------------------------------- #
# label resolution / sanitization — label comes from the profile, safely.      #
# --------------------------------------------------------------------------- #

def test_default_label_is_institution_neutral():
    # No org / machine name baked in (Art. 15.3 — sabit kurum-etiketi yasak).
    assert DEFAULT_LABEL == "council-tick"


@pytest.mark.parametrize("raw,expected", [
    ("my-council", "my-council"),
    ("Node_01.tick", "Node_01.tick"),
    ("", DEFAULT_LABEL),
    (None, DEFAULT_LABEL),
    ("   ", DEFAULT_LABEL),
    ("a/b/c", "abc"),                       # path separators stripped
    ("rm -rf ~; tick", "rm-rftick"),        # shell metacharacters stripped
    ("../../etc/passwd", "etcpasswd"),      # traversal stripped, edges trimmed
    ("$(whoami)", "whoami"),
    ("...", DEFAULT_LABEL),                 # only-separators → default
])
def test_sanitize_label(raw, expected):
    assert sanitize_label(raw) == expected


def test_label_from_config_reads_profile_attr():
    cfg = types.SimpleNamespace(scheduler_label="prof-label")
    assert label_from_config(cfg) == "prof-label"


def test_label_from_config_defaults_when_absent():
    assert label_from_config(types.SimpleNamespace()) == DEFAULT_LABEL
    assert label_from_config(None) == DEFAULT_LABEL


def test_get_scheduler_threads_label_from_cfg():
    cfg = types.SimpleNamespace(scheduler_label="from-cfg", council_home="/tmp/x")
    sch = get_scheduler("systemd", cfg=cfg)
    assert isinstance(sch, SystemdScheduler)
    assert sch.label == "from-cfg"


def test_get_scheduler_explicit_label_wins_over_cfg():
    cfg = types.SimpleNamespace(scheduler_label="from-cfg")
    sch = get_scheduler("schtasks", label="explicit", cfg=cfg)
    assert sch.label == "explicit"


def test_get_scheduler_unknown_is_null():
    assert isinstance(get_scheduler("does-not-exist"), NullScheduler)
    assert isinstance(get_scheduler(None), NullScheduler)


# --------------------------------------------------------------------------- #
# NullScheduler — pure no-op (default OFF, Art. 0.7 / 14).                      #
# --------------------------------------------------------------------------- #

def test_null_scheduler_is_noop():
    n = NullScheduler()
    assert n.install() is False              # installs nothing
    assert n.register() is False             # register alias agrees
    assert n.uninstall() is True             # "removal" trivially succeeds
    assert n.unregister() is True
    assert n.is_installed() is False


def test_null_scheduler_ignores_label():
    # NullScheduler schedules nothing, so a label must not change its behavior.
    n = get_scheduler("null", label="whatever")
    assert isinstance(n, NullScheduler)
    assert n.install(interval_s=60) is False


# --------------------------------------------------------------------------- #
# systemd — render .service / .timer without a daemon.                          #
# --------------------------------------------------------------------------- #

def test_systemd_render_units_single_tick_contract(tmp_path):
    # tmp_path is already a real (resolved) path → no /tmp→/private/tmp surprise.
    home = tmp_path.resolve()
    sch = SystemdScheduler(label="council-tick")
    service = sch.render_service(python="/usr/bin/python3", council_home=str(home))
    timer = sch.render_timer(interval_s=120)

    # Single tick-contract: the service ExecStart is python + the canonical args.
    assert f"ExecStart=/usr/bin/python3 {TICK_SUFFIX}" in service
    assert "Type=oneshot" in service
    assert f"WorkingDirectory={home}" in service
    # Timer re-arms on the configured interval.
    assert "OnBootSec=120" in timer
    assert "OnUnitActiveSec=120" in timer
    assert "WantedBy=timers.target" in timer


def test_systemd_label_drives_unit_filenames():
    sch = SystemdScheduler(label="node7-tick")
    assert sch.service_path().name == "node7-tick.service"
    assert sch.timer_path().name == "node7-tick.timer"


def test_systemd_timer_floor_interval():
    sch = SystemdScheduler(label="x")
    timer = sch.render_timer(interval_s=0)   # never schedule a 0s timer
    assert "OnUnitActiveSec=1" in timer


def test_systemd_register_idempotent_and_reversible(tmp_path, monkeypatch):
    calls: list[list[str]] = []

    def fake_run(argv, *a, **k):
        calls.append(list(argv))
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(S.subprocess, "run", fake_run)
    sch = SystemdScheduler(label="rt-tick")
    monkeypatch.setattr(sch, "_dir", lambda: tmp_path)

    assert sch.register(python="/usr/bin/python3", council_home=str(tmp_path)) is True
    assert sch.is_installed() is True
    first = sch.timer_path().read_text(encoding="utf-8")

    # Idempotent: a second register leaves exactly one timer with identical content.
    assert sch.register(python="/usr/bin/python3", council_home=str(tmp_path)) is True
    assert sch.timer_path().read_text(encoding="utf-8") == first
    assert sorted(p.name for p in tmp_path.iterdir()) == ["rt-tick.service", "rt-tick.timer"]

    # Reversible: unregister removes exactly this backend's own units.
    assert sch.unregister() is True
    assert not sch.timer_path().exists()
    assert not sch.service_path().exists()
    assert sch.is_installed() is False

    # systemctl was actually driven (daemon-reload + enable/disable), never raised.
    assert any("daemon-reload" in c for c in calls)
    assert any("enable" in c and "rt-tick.timer" in c for c in calls)
    assert any("disable" in c and "rt-tick.timer" in c for c in calls)


# --------------------------------------------------------------------------- #
# schtasks — render argv without Windows.                                       #
# --------------------------------------------------------------------------- #

def test_schtasks_render_create_argv_single_tick_contract():
    sch = SchtasksScheduler(label="CouncilTick")
    argv = sch.render_create_argv(python=r"C:\Py\python.exe", interval_s=300)
    assert argv[:3] == ["schtasks", "/Create", "/F"]      # /F → idempotent overwrite
    assert "/SC" in argv and argv[argv.index("/SC") + 1] == "MINUTE"
    assert argv[argv.index("/MO") + 1] == "5"             # 300s → 5 min
    assert argv[argv.index("/TN") + 1] == "CouncilTick"   # label drives task name
    tr = argv[argv.index("/TR") + 1]
    assert tr == f'"C:\\Py\\python.exe" {TICK_SUFFIX}'    # single tick-contract


def test_schtasks_interval_floor_one_minute():
    sch = SchtasksScheduler(label="t")
    argv = sch.render_create_argv(python="py", interval_s=10)   # <1 min → floor at 1
    assert argv[argv.index("/MO") + 1] == "1"


def test_schtasks_delete_and_query_argv_reverse_exactly():
    sch = SchtasksScheduler(label="MyTask")
    assert sch.render_delete_argv() == ["schtasks", "/Delete", "/F", "/TN", "MyTask"]
    assert sch.render_query_argv() == ["schtasks", "/Query", "/TN", "MyTask"]


def test_schtasks_register_unregister_drive_subprocess(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(argv, *a, **k):
        calls.append(list(argv))
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(S.subprocess, "run", fake_run)
    sch = SchtasksScheduler(label="RegTask")

    assert sch.register(python="py", interval_s=600) is True
    assert sch.unregister() is True
    assert sch.is_installed() is True        # fake returncode 0 → query "found"

    assert calls[0][:3] == ["schtasks", "/Create", "/F"]
    assert ["schtasks", "/Delete", "/F", "/TN", "RegTask"] in calls
    assert ["schtasks", "/Query", "/TN", "RegTask"] in calls


# --------------------------------------------------------------------------- #
# cron — render the single guarded line; round-trip on a fake crontab.          #
# --------------------------------------------------------------------------- #

def test_cron_render_line_single_tick_contract_and_marker(tmp_path):
    home = tmp_path.resolve()
    sch = CronScheduler(label="council-tick")
    line = sch.render_line(python="/usr/bin/python3", council_home=str(home), interval_s=300)
    assert line.startswith(f"*/5 * * * * cd {home} && /usr/bin/python3 ")
    assert TICK_SUFFIX in line
    assert "# council-tick (managed; do not edit)" in line


def test_cron_marker_uses_label():
    sch = CronScheduler(label="node9")
    assert "# node9 (managed; do not edit)" in sch.render_line(python="py")


def test_cron_round_trip_idempotent_and_preserves_other_lines(monkeypatch):
    # Fake crontab living in a list; crontab -l prints it, crontab - replaces it.
    store: dict[str, list[str]] = {"lines": ["0 9 * * * /usr/bin/backup  # user's own job"]}

    def fake_run(argv, *a, **k):
        if argv[:2] == ["crontab", "-l"]:
            return types.SimpleNamespace(returncode=0, stdout="\n".join(store["lines"]) + "\n", stderr="")
        if argv[:2] == ["crontab", "-"]:
            store["lines"] = (k.get("input", "")).splitlines()
            store["lines"] = [ln for ln in store["lines"] if ln.strip()]
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")
        return types.SimpleNamespace(returncode=1, stdout="", stderr="")

    monkeypatch.setattr(S.subprocess, "run", fake_run)
    sch = CronScheduler(label="rt")

    assert sch.is_installed() is False
    assert sch.install(python="/usr/bin/python3", council_home="/tmp/h") is True
    assert sch.is_installed() is True
    managed = [ln for ln in store["lines"] if sch._MARKER in ln]
    assert len(managed) == 1

    # Idempotent: a second install still leaves exactly one managed line.
    assert sch.install(python="/usr/bin/python3", council_home="/tmp/h") is True
    assert len([ln for ln in store["lines"] if sch._MARKER in ln]) == 1

    # Reversible: uninstall removes our line but keeps the user's pre-existing job.
    assert sch.uninstall() is True
    assert sch.is_installed() is False
    assert any("/usr/bin/backup" in ln for ln in store["lines"])


def test_cron_no_crontab_binary_degrades_not_raises(monkeypatch):
    def boom(*a, **k):
        raise FileNotFoundError("crontab")

    monkeypatch.setattr(S.subprocess, "run", boom)
    sch = CronScheduler(label="x")
    # Best-effort: never raises, just reports failure / not-installed.
    assert sch.is_installed() is False
    assert sch.install(python="py") is False
    assert sch.uninstall() is False


# --------------------------------------------------------------------------- #
# launchd — render plist without launchctl (macOS backend, render is portable). #
# --------------------------------------------------------------------------- #

def test_launchd_render_plist_label_and_tick_contract():
    sch = LaunchdScheduler(label="council-tick")
    plist = sch.render_plist(python="/usr/bin/python3", council_home="/tmp/h", interval_s=300)
    assert "<string>com.council-tick</string>" in plist     # reverse-DNS-ish label
    assert "<key>StartInterval</key><integer>300</integer>" in plist
    assert "<string>/usr/bin/python3</string>" in plist
    for arg in ("-m", "council.dispatch", "tick"):
        assert f"<string>{arg}</string>" in plist           # single tick-contract


def test_launchd_label_drives_plist_filename():
    sch = LaunchdScheduler(label="node3")
    assert sch._plist_path().name == "com.node3.plist"


# --------------------------------------------------------------------------- #
# cross-backend invariant — they all schedule the identical command.            #
# --------------------------------------------------------------------------- #

def test_all_backends_share_one_tick_contract():
    py = "/usr/bin/python3"
    systemd = SystemdScheduler(label="x").render_service(python=py, council_home="/tmp")
    schtasks_tr = SchtasksScheduler(label="x").render_command(python=py)
    cron = CronScheduler(label="x").render_line(python=py, council_home="/tmp")
    launchd = LaunchdScheduler(label="x").render_plist(python=py, council_home="/tmp")

    assert TICK_SUFFIX in systemd
    assert TICK_SUFFIX in schtasks_tr
    assert TICK_SUFFIX in cron
    for arg in ("-m", "council.dispatch", "tick"):
        assert f"<string>{arg}</string>" in launchd


def test_default_interval_constant_is_reasonable():
    # Sanity: the documented default is a positive number of seconds.
    assert isinstance(DEFAULT_INTERVAL_S, int) and DEFAULT_INTERVAL_S > 0
