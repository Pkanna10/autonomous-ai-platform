"""U8a: ``x2_proc`` reads a synthetic ``/proc`` tree (``tmp_path``, handed
by path), bounded and defensive: an absent or malformed file is ``None``, a
vanished or unparsable pid is skipped, nothing raises. The engine is the
reader's own pid and its descendants; the top processes are the others by
tick delta. What only a GitHub runner proves (its real ``/proc``, PSI
present or not, ``RUNNER_NAME`` and ``ImageVersion``) is the live run's.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from . import x2_proc as xp

LOADAVG = "4.80 5.55 5.50 6/154 24288\n"
PRESSURE = ("some avg10=10.65 avg60=20.01 avg300=28.78 total=1000\n"
            "full avg10=0.00 avg60=0.00 avg300=0.00 total=0\n")  # fmt: skip
STAT = "cpu  100 2 30 400 50 0 6 7 0 0\ncpu0 1 2 3 4 5 6 7 8 0 0\nctxt 9\n"
CPUINFO = ("processor\t: 0\nmodel name\t: Intel(R) Xeon(R) \x1b Processor @ 2.10GHz\n"
           "cpu MHz\t\t: 2100.000\n\nprocessor\t: 1\nmodel name\t: same\n"
           "cpu MHz\t\t: 2095.5\nbogus line\ncpu MHz\t\t: fast\n")  # fmt: skip


def _pid_stat(
    pid: int, comm: str, ppid: int, utime: int, stime: int, start: int
) -> str:
    rest = ["S", str(ppid), *["0"] * 9, str(utime), str(stime), *["0"] * 6, str(start)]
    return f"{pid} ({comm}) {' '.join(rest)} 0 0\n"


def _tree(root: Path, procs: dict[int, tuple[str, int, int, int, int]], *,
          stat: str = STAT, pressure: str | None = PRESSURE) -> Path:  # fmt: skip
    root.mkdir(parents=True, exist_ok=True)
    (root / "loadavg").write_text(LOADAVG)
    (root / "stat").write_text(stat)
    (root / "uptime").write_text("5318.58 6496.11\n")
    if pressure is not None:
        (root / "pressure").mkdir(exist_ok=True)
        (root / "pressure" / "cpu").write_text(pressure)
    for pid, (comm, ppid, u, s, start) in procs.items():
        (root / str(pid)).mkdir(exist_ok=True)
        (root / str(pid) / "stat").write_text(_pid_stat(pid, comm, ppid, u, s, start))
    return root


def test_the_parsers_read_the_kernel_formats_and_refuse_the_rest() -> None:
    assert xp.parse_loadavg(LOADAVG) == {
        "one": 4.8, "five": 5.55, "fifteen": 5.5, "running": 6.0, "total": 154.0
    }  # fmt: skip
    for bad in (None, "", "1 2", "a b c 1/2 3", "1 2 3 4 5"):
        assert xp.parse_loadavg(bad) is None
    assert xp.parse_pressure(PRESSURE) == {
        "some": {"avg10": 10.65, "avg60": 20.01, "avg300": 28.78, "total": 1000.0},
        "full": {"avg10": 0.0, "avg60": 0.0, "avg300": 0.0, "total": 0.0},
    }
    for bad in (None, "", "some avg10", "some avg10=x", "\n"):
        assert xp.parse_pressure(bad) is None
    assert xp.parse_cpu(STAT) == {"user": 100, "nice": 2, "system": 30, "idle": 400,
                                  "iowait": 50, "irq": 0, "softirq": 6, "steal": 7}  # fmt: skip
    assert xp.parse_cpu("cpu  1 2 3 4\n") == {
        "user": 1,
        "nice": 2,
        "system": 3,
        "idle": 4,
    }
    for bad in (None, "", "cpu0 1 2\n", "cpu  1 x\n"):
        assert xp.parse_cpu(bad) is None
    assert xp.parse_uptime("12.5 3\n") == 12.5
    for bad in (None, "", "x"):
        assert xp.parse_uptime(bad) is None


def test_a_pid_stat_keeps_a_comm_with_spaces_and_parentheses() -> None:
    text = _pid_stat(7, "a (b) c", 3, 11, 4, 99)
    assert xp.parse_pid_stat(text) == xp.Proc("a (b) c", 3, 15, 99)
    assert xp.parse_pid_stat(_pid_stat(7, "\x07" + "x" * 80, 1, 0, 0, 1)) == xp.Proc(
        "?" + "x" * 63, 1, 0, 1
    )
    for bad in (None, "", "7 no parens S 1", "7 )x( S 1", "7 (x) S 1 2", "7 (x) S y"):
        assert xp.parse_pid_stat(bad) is None


def test_a_snapshot_skips_what_is_not_a_readable_pid(tmp_path: Path) -> None:
    root = _tree(
        tmp_path / "proc", {10: ("bash", 1, 5, 5, 100), 11: ("x", 10, 1, 0, 101)}
    )
    (root / "12").mkdir()  # vanished: no stat
    (root / "13").mkdir()
    (root / "13" / "stat").write_text("garbage\n")
    (root / "self").mkdir()  # not a pid
    (root / "99999999999").mkdir()  # 11 digits: not a pid
    ticks = iter([100.0, 101.0])
    snap = xp.ProcReader(root, pid=1, clock=lambda: next(ticks)).snapshot()
    assert snap.time == 100.0 and snap.seconds >= 0
    assert set(snap.procs) == {10, 11} and snap.procs[10] == xp.Proc("bash", 1, 10, 100)
    assert snap.uptime_s == 5318.58 and snap.loadavg is not None
    assert snap.summary() == {"loadavg": snap.loadavg, "pressure": snap.pressure,
                              "uptime_s": 5318.58}  # fmt: skip


def test_absent_files_record_as_absent(tmp_path: Path) -> None:
    snap = xp.ProcReader(tmp_path / "none", pid=1).snapshot()
    assert (snap.loadavg, snap.pressure, snap.cpu, snap.uptime_s) == (None,) * 4
    assert snap.procs == {}
    no_psi = xp.ProcReader(_tree(tmp_path / "p", {}, pressure=None), pid=1).snapshot()
    assert no_psi.pressure is None and no_psi.cpu is not None


def test_the_pid_listing_and_each_read_are_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    root = _tree(tmp_path / "proc", {n: ("p", 1, 1, 0, n) for n in range(20, 30)})
    monkeypatch.setattr(xp, "MAX_PIDS", 4)
    assert len(xp.ProcReader(root, pid=1).snapshot().procs) == 4
    monkeypatch.setattr(xp, "FILE_CAP", 10)
    assert xp._read(root / "loadavg") == LOADAVG[:10]


def test_the_delta_counts_ticks_stall_and_the_top_three_others(tmp_path: Path) -> None:
    engine = os.getpid()
    before = {engine: ("python", 1, 50, 0, 10), 30: ("git", engine, 1, 0, 11),
              40: ("Runner.Worker", 1, 100, 0, 12), 41: ("kworker", 2, 10, 0, 13),
              42: ("reused", 1, 500, 0, 14), 43: ("idle", 1, 3, 0, 15),
              44: ("ended", 1, 9, 0, 16)}  # fmt: skip
    after = {engine: ("python", 1, 90, 0, 10), 30: ("git", engine, 40, 0, 11),
             31: ("bwrap", 30, 70, 0, 20), 40: ("Runner.Worker", 1, 160, 0, 12),
             41: ("kworker", 2, 15, 0, 13), 42: ("reused", 1, 8, 0, 21),
             43: ("idle", 1, 3, 0, 15), 45: ("new", 1, 30, 0, 22)}  # fmt: skip
    later = STAT.replace("cpu  100 2 30 400 50 0 6 7", "cpu  160 2 40 410 55 0 6 9")
    psi = PRESSURE.replace("total=1000", "total=4000")
    a = xp.ProcReader(_tree(tmp_path / "a", before), pid=engine).snapshot()
    b = xp.ProcReader(_tree(tmp_path / "b", after, stat=later, pressure=psi), pid=engine).snapshot()  # fmt: skip
    got = xp.delta(a, b, engine)
    assert got["cpu_ticks"] == {"user": 60, "nice": 0, "system": 10, "idle": 10,
                                "iowait": 5, "irq": 0, "softirq": 0, "steal": 2}  # fmt: skip
    assert got["pressure_stall_us"] == {"some": 3000.0, "full": 0.0}
    assert got["top"] == [  # the engine, its git and the git's child left out
        {"pid": 40, "comm": "Runner.Worker", "ticks": 60, "new": False},
        {"pid": 45, "comm": "new", "ticks": 30, "new": True},
        {"pid": 42, "comm": "reused", "ticks": 8, "new": True},  # another start
    ]


def test_a_delta_with_a_side_absent_records_none(tmp_path: Path) -> None:
    full = xp.ProcReader(_tree(tmp_path / "a", {}), pid=1).snapshot()
    empty = xp.ProcReader(tmp_path / "none", pid=1).snapshot()
    for one, other in ((full, empty), (empty, full)):
        assert xp.delta(one, other, 1) == {"cpu_ticks": None, "pressure_stall_us": None, "top": []}  # fmt: skip
    odd = xp.ProcReader(_tree(tmp_path / "b", {}, pressure="some avg10=1\n"), pid=1).snapshot()  # fmt: skip
    assert xp.delta(full, odd, 1)["pressure_stall_us"] is None  # no total: no stall


def test_a_parent_loop_or_a_deep_chain_ends(tmp_path: Path) -> None:
    procs = {n: xp.Proc("p", n + 1, 0, 0) for n in range(100, 200)}  # 100 -> ... -> 200
    procs[300], procs[301] = xp.Proc("a", 301, 0, 0), xp.Proc("b", 300, 0, 0)
    engine = xp._engine(procs, 200)
    assert 199 in engine and 100 not in engine  # past the depth: not followed
    assert 300 not in engine and 301 not in engine


def test_the_machine_comes_from_cpuinfo_meminfo_and_the_environment(tmp_path: Path) -> None:  # fmt: skip
    root = tmp_path / "proc"
    root.mkdir()
    (root / "cpuinfo").write_text(CPUINFO)
    (root / "meminfo").write_text("MemFree: 1 kB\nMemTotal:       16472076 kB\n")
    environ = {"RUNNER_NAME": "GitHub Actions 12", "ImageVersion": "20261102.1\n"}
    assert xp.ProcReader(root, pid=1).machine(environ) == {
        "cpu_model": "Intel(R) Xeon(R) ? Processor @ 2.10GHz",
        "cpu_mhz": {"first": 2100.0, "min": 2095.5, "max": 2100.0}, "cpu_count": 2,
        "memory_bytes": 16472076 * 1024,
        "RUNNER_NAME": "GitHub Actions 12", "ImageVersion": "20261102.1?",
    }  # fmt: skip
    assert xp.ProcReader(tmp_path / "none", pid=1).machine({}) == {
        "cpu_model": None, "cpu_mhz": None, "cpu_count": None, "memory_bytes": None,
        "RUNNER_NAME": None, "ImageVersion": None,
    }  # fmt: skip
