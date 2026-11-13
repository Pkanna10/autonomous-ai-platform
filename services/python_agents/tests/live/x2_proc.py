"""O64-3 (U8a, record-only): what the host's ``/proc`` says around a look.

A ``ProcReader`` reads fixed files under one root (``/proc``; a test hands
it a synthetic tree): ``loadavg``, ``pressure/cpu``, the ``cpu`` line of
``stat``, ``uptime`` and each ``[pid]/stat``, once before and once after a
look (``x2_looks``), never during one. ``delta`` is the pair's difference:
the CPU tick deltas (iowait and steal among them), the CPU pressure stall
time, and the top three non-engine processes by ticks (a pid's ``stat``
before and after; a pid new after the look counts all its ticks; the engine
is this process and every descendant). ``machine`` is the per-run record:
the CPU model, clock and count from ``cpuinfo``, the memory from
``meminfo``, ``RUNNER_NAME`` and ``ImageVersion`` from the environment.

Every read is bounded (``FILE_CAP`` bytes, ``MAX_PIDS`` pids) and parsed
defensively: a file that is absent, unreadable or malformed (no
``pressure/cpu`` on an older kernel, a pid that ended between the listing
and its read) records as ``None`` or is skipped, never an error. The only
path component taken from a listing is a pid, and only when it is digits
(``_PID``). Nothing here feeds a decision.
"""

from __future__ import annotations

import os
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

PROC: Final = Path("/proc")
FILE_CAP: Final = 1 << 18  # cpuinfo on a large host is the largest read
MAX_PIDS: Final = 4096
TOP: Final = 3
CPU_FIELDS: Final = ("user", "nice", "system", "idle", "iowait", "irq", "softirq", "steal")  # fmt: skip
ENV_KEYS: Final = ("RUNNER_NAME", "ImageVersion")
_PID: Final = re.compile(r"[0-9]{1,10}")
_TEXT: Final = 64  # longest process name or environment value kept
_DEPTH: Final = 64  # longest parent chain followed


def _read(path: Path) -> str | None:
    try:
        with path.open("rb") as handle:
            return handle.read(FILE_CAP).decode("utf-8", "replace")
    except OSError:
        return None


def _shown(text: str) -> str:
    return "".join(c if c.isprintable() and c.isascii() else "?" for c in text[:_TEXT])


def parse_loadavg(text: str | None) -> dict[str, float] | None:
    try:
        one, five, fifteen, tasks = (text or "").split()[:4]
        running, total = tasks.split("/")
        return {"one": float(one), "five": float(five), "fifteen": float(fifteen),
                "running": float(running), "total": float(total)}  # fmt: skip
    except ValueError:
        return None


def parse_pressure(text: str | None) -> dict[str, dict[str, float]] | None:
    """``some`` and ``full`` lines: avg10, avg60, avg300 (%), total (us)."""
    out: dict[str, dict[str, float]] = {}
    for line in (text or "").splitlines():
        try:
            kind, *pairs = line.split()
            out[kind] = {k: float(v) for k, v in (p.split("=", 1) for p in pairs)}
        except ValueError:
            return None
    return out or None


def parse_cpu(text: str | None) -> dict[str, int] | None:
    """The aggregate ``cpu`` line's ticks, as many fields as the kernel has."""
    for line in (text or "").splitlines():
        if line.startswith("cpu "):
            try:
                return dict(zip(CPU_FIELDS, map(int, line.split()[1:]), strict=False))
            except ValueError:
                return None
    return None


def parse_uptime(text: str | None) -> float | None:
    try:
        return float((text or "").split()[0])
    except (ValueError, IndexError):
        return None


@dataclass(frozen=True)
class Proc:
    comm: str
    ppid: int
    ticks: int  # utime + stime
    start: int  # starttime: a reused pid has another


def parse_pid_stat(text: str | None) -> Proc | None:
    """``pid (comm) state ppid ...``: comm may hold spaces and parentheses."""
    text = text or ""
    left, right = text.find("("), text.rfind(")")
    rest = text[right + 1 :].split()
    try:
        if left < 0 or right < left:
            return None
        return Proc(_shown(text[left + 1 : right]), int(rest[1]),
                    int(rest[11]) + int(rest[12]), int(rest[19]))  # fmt: skip
    except (ValueError, IndexError):
        return None


@dataclass(frozen=True)
class Snapshot:
    time: float  # the clock when the snapshot began
    seconds: float  # how long reading it took
    loadavg: dict[str, float] | None
    pressure: dict[str, dict[str, float]] | None
    cpu: dict[str, int] | None
    uptime_s: float | None
    procs: Mapping[int, Proc] = field(default_factory=dict)

    def summary(self) -> dict[str, object]:
        return {"loadavg": self.loadavg, "pressure": self.pressure,
                "uptime_s": self.uptime_s}  # fmt: skip


@dataclass(frozen=True)
class ProcReader:
    root: Path = PROC
    pid: int = field(default_factory=os.getpid)  # the engine's process
    clock: Callable[[], float] = time.time

    def _procs(self) -> dict[int, Proc]:
        names: list[str] = []
        try:
            with os.scandir(self.root) as entries:
                for entry in entries:
                    if _PID.fullmatch(entry.name):
                        names.append(entry.name)
                        if len(names) >= MAX_PIDS:
                            break
        except OSError:
            return {}
        found = {int(n): parse_pid_stat(_read(self.root / n / "stat")) for n in names}
        return {pid: p for pid, p in found.items() if p is not None}

    def snapshot(self) -> Snapshot:
        began, mono = self.clock(), time.monotonic()
        loadavg = parse_loadavg(_read(self.root / "loadavg"))
        pressure = parse_pressure(_read(self.root / "pressure" / "cpu"))
        cpu = parse_cpu(_read(self.root / "stat"))
        uptime = parse_uptime(_read(self.root / "uptime"))
        procs = self._procs()
        return Snapshot(began, time.monotonic() - mono, loadavg, pressure, cpu, uptime, procs)  # fmt: skip

    def machine(self, environ: Mapping[str, str]) -> dict[str, object]:
        info = (_read(self.root / "cpuinfo") or "").splitlines()
        values: dict[str, list[str]] = {}
        for line in info:
            key, sep, value = line.partition(":")
            if sep:
                values.setdefault(key.strip(), []).append(value.strip())
        clocks = []
        for mhz in values.get("cpu MHz", []):
            try:
                clocks.append(float(mhz))
            except ValueError:
                continue
        memory = None
        for line in (_read(self.root / "meminfo") or "").splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0] == "MemTotal:" and parts[1].isdigit():
                memory = int(parts[1]) * 1024
        model = values.get("model name", [None])[0]
        return {"cpu_model": None if model is None else _shown(model),
                "cpu_mhz": {"first": clocks[0], "min": min(clocks), "max": max(clocks)}
                if clocks else None,
                "cpu_count": len(values.get("processor", [])) or None,
                "memory_bytes": memory,
                **{k: None if k not in environ else _shown(environ[k]) for k in ENV_KEYS}}  # fmt: skip


def _engine(procs: Mapping[int, Proc], pid: int) -> set[int]:
    """``pid`` and every process whose parent chain reaches it."""
    out = {pid}
    for start in procs:
        chain: list[int] = []
        at = start
        while at not in out and at in procs and len(chain) < _DEPTH:
            chain.append(at)
            at = procs[at].ppid
        if at in out:
            out.update(chain)
    return out


def delta(before: Snapshot, after: Snapshot, pid: int) -> dict[str, object]:
    """The look's CPU tick deltas, pressure stall time and top processes."""
    b, a = before.cpu, after.cpu
    ticks = None if a is None or b is None else {k: a[k] - b[k] for k in a if k in b}
    stall: dict[str, float] | None = None
    if before.pressure is not None and after.pressure is not None:
        stall = {k: v["total"] - before.pressure[k]["total"]
                 for k, v in after.pressure.items()
                 if "total" in v and "total" in before.pressure.get(k, {})}  # fmt: skip
    engine = _engine({**before.procs, **after.procs}, pid)
    top: list[tuple[int, int, Proc, bool]] = []
    for p, proc in after.procs.items():
        if p in engine:
            continue
        old = before.procs.get(p)
        new = old is None or old.start != proc.start
        used = proc.ticks - (0 if old is None or new else old.ticks)
        if used > 0:
            top.append((used, p, proc, new))
    top.sort(key=lambda x: (-x[0], x[1]))
    return {"cpu_ticks": ticks, "pressure_stall_us": stall or None,
            "top": [{"pid": p, "comm": proc.comm, "ticks": used, "new": new}
                    for used, p, proc, new in top[:TOP]]}  # fmt: skip
