"""The child-process tripwire end to end (D62, N0c): real launcher runs.

``procrun.run_once`` runs the real launcher (``python -I -S launcher.py``)
with each workload, under ``unshare`` (PID namespace: the launcher is PID 1)
and without a wrapper (no PID namespace: the launcher is the child
subreaper), so the ``RunSample`` carries what the launcher read: the
workload's ``cutime + cstime`` after a ``WNOWAIT`` wait (10 ms ticks; each
child here burns 100 ms of CPU and must read at least D1's 50 ms, 2x
margin over the two floored ticks a read can lose) and the strays it
killed and reaped. Nothing is faked; the sandboxed mode skips when the host
cannot sandbox, unless ``REQUIRE_NETWORK_SANDBOX=1`` or
``REQUIRE_FS_SANDBOX=1`` (CI sets both). darwin's null child CPU (D3) runs on
the macOS job only; the group-leftover stray runs on both platforms.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from autonomous_ai_agents.common.config import IsolationMode
from autonomous_ai_agents.execution.procrun import OutputCaps, RunSample, run_once
from autonomous_ai_agents.execution.sandbox import (
    UNSHARE_ARGV,
    SandboxPolicy,
    child_env,
)

CAPS = OutputCaps(max_output_bytes=1 << 20, head_bytes=200, stderr_tail_bytes=2000)
BUSY = (
    "import time\nt = time.process_time()\nwhile time.process_time() - t < 0.1: pass\n"
)
CHILD = "".join(f"    {line}\n" for line in BUSY.splitlines())  # BUSY, indented
WORKLOADS = {
    "clean": BUSY,
    "fork": f"import os\nif (pid := os.fork()) == 0:\n{CHILD}    os._exit(0)\nos.waitpid(pid, 0)\n",
    "subprocess": f"import subprocess, sys\nsubprocess.run([sys.executable, '-c', {BUSY!r}], check=True)\n",
    "pool": (
        "import multiprocessing as mp, time\n"
        "def burn(_):\n"
        "    t = time.process_time()\n"
        "    while time.process_time() - t < 0.1: pass\n"
        "if __name__ == '__main__':\n"
        "    mp.set_start_method('fork')\n"
        "    with mp.Pool(2) as pool: pool.map(burn, range(2), chunksize=1)\n"
    ),
    "live-orphan": "import os, time\nif os.fork() == 0:\n    time.sleep(30)\n",
    "exited-orphan": (
        f"import os, time\nif os.fork() == 0:\n{CHILD}    os._exit(0)\ntime.sleep(0.5)\n"
    ),
}  # fmt: skip
linux_only = pytest.mark.skipif(sys.platform != "linux", reason="Linux /proc")
darwin_only = pytest.mark.skipif(sys.platform != "darwin", reason="macOS job")


def _require() -> bool:
    flags = ("REQUIRE_NETWORK_SANDBOX", "REQUIRE_FS_SANDBOX")
    return "1" in (os.environ.get(flag) for flag in flags)


def _sandbox(network: IsolationMode) -> None:
    """Skip (or fail under REQUIRE_*) when ``network`` needs an unshare that fails."""
    if network == "off":
        return
    ok = (
        shutil.which("unshare") is not None
        and (
            subprocess.run([*UNSHARE_ARGV, "true"], capture_output=True, check=False)
        ).returncode
        == 0
    )
    if not ok:
        if _require():
            pytest.fail("sandbox required but unshare is unavailable")
        pytest.skip("unshare is unavailable")


def run(tmp_path: Path, code: str, network: IsolationMode, python: str = sys.executable) -> RunSample:  # fmt: skip
    root = Path(os.path.realpath(tmp_path))
    wt, scratch, probe = root / "wt", root / "scratch", root / "probe"
    for path in (wt, scratch, probe):
        path.mkdir()
    policy = SandboxPolicy(
        network=network, fs="off", writable=(wt, scratch), probe_dir=probe,
        platform=sys.platform,
    )  # fmt: skip
    env = child_env(home=scratch, tmpdir=scratch, worktree=wt)
    argv = [sys.executable, "-c", code]
    return run_once(argv, wt, env, policy, 60.0, CAPS, python=python)


@linux_only
@pytest.mark.parametrize("network", ["required", "off"])
@pytest.mark.parametrize(
    ("name", "low", "high", "strays"),
    [
        ("clean", 0.0, 0.0, 0),
        ("fork", 0.05, 10.0, 0),
        ("subprocess", 0.05, 10.0, 0),
        ("pool", 0.1, 10.0, 0),
        ("live-orphan", 0.0, 0.05, 1),
        ("exited-orphan", 0.05, 10.0, 1),
    ],
)
def test_the_launcher_reports_child_cpu_and_strays(
    tmp_path: Path,
    network: IsolationMode,
    name: str,
    low: float,
    high: float,
    strays: int,
) -> None:
    """
    GIVEN a workload that forks, uses subprocess, a fork-start Pool of two
        workers, leaves a sleeping or an exited child behind, or spawns nothing
        (every child burns 100 ms of CPU)
    WHEN it runs with a PID namespace and without one
    THEN the child CPU covers every child the launcher could account for
        (a waited-for one through cutime, a stray through its reap), the
        strays are exact, and the clean workload reads exactly 0.0 and 0;
        the sleeping orphan is killed at once, not waited for
    """
    _sandbox(network)
    started = time.monotonic()

    sample = run(tmp_path, WORKLOADS[name], network)

    assert sample.exit == 0, sample.stderr_tail
    assert sample.strays == strays
    assert sample.child_cpu_s is not None
    assert low <= sample.child_cpu_s <= high
    assert time.monotonic() - started < 20.0


SIGIGN = {
    "fork": (
        "import os, signal, time\nsignal.signal(signal.SIGCHLD, signal.SIG_IGN)\n"
        f"if os.fork() == 0:\n{CHILD}    os._exit(0)\ntime.sleep(0.5)\n"
    ),
    "subprocess": (
        "import signal, subprocess, sys\nsignal.signal(signal.SIGCHLD, signal.SIG_IGN)\n"
        f"subprocess.run([sys.executable, '-c', {BUSY!r}])\n"
    ),
}


@linux_only
@pytest.mark.parametrize("network", ["required", "off"])
@pytest.mark.parametrize("name", sorted(SIGIGN))
def test_known_gap_children_auto_reaped_under_sigchld_ignored_read_clean(
    tmp_path: Path, network: IsolationMode, name: str
) -> None:
    """
    GIVEN a workload that sets SIGCHLD to SIG_IGN, then forks or runs a
        subprocess whose child burns 100 ms of CPU
    WHEN it runs with a PID namespace and without one
    THEN both signals read clean (child CPU 0.0, no strays): the kernel
        auto-reaps such a child, so its time never reaches the workload's
        cutime/cstime and it is gone before the drain. This PINS A KNOWN GAP
        (launcher docstring, D62): the static spawn rule (N0) is the defence
        here. A third signal that closes it must flip this test to assert
        the run is caught, never delete it.
    """
    _sandbox(network)

    sample = run(tmp_path, SIGIGN[name], network)

    assert sample.exit == 0, sample.stderr_tail
    assert (sample.child_cpu_s, sample.strays) == (0.0, 0)


LEFTOVER = """#!{python} -I
import os, sys, time
if os.fork() == 0:
    if os.fork() == 0:
        null = os.open(os.devnull, os.O_RDWR)
        for fd in (0, 1, 2):
            os.dup2(null, fd)
        time.sleep(30)
    os._exit(0)
os.wait()
os.execv({python!r}, [{python!r}, *sys.argv[1:]])
"""


def test_a_process_left_in_the_group_counts_as_a_stray(tmp_path: Path) -> None:
    """
    GIVEN a stand-in interpreter that double-forks a sleeper into the run's
        process group before it execs the real launcher (so the sleeper is no
        descendant the launcher can drain)
    WHEN the run finishes
    THEN procrun finds the group still populated after the wrapper's reap,
        counts one stray and kills it (on darwin the only stray signal, D3)
    """
    script = tmp_path / "leftover-python"
    script.write_text(LEFTOVER.format(python=sys.executable))
    script.chmod(0o755)

    sample = run(tmp_path, "pass", "off", python=str(script))

    assert (sample.exit, sample.strays) == (0, 1)


@darwin_only
def test_darwin_reports_a_null_child_cpu(tmp_path: Path) -> None:
    """
    GIVEN darwin, where no child-CPU route is proven yet (D3)
    WHEN a forking workload runs
    THEN the child CPU is null and a waited-for child is no stray
    """
    sample = run(tmp_path, WORKLOADS["fork"], "off")

    assert (sample.exit, sample.child_cpu_s, sample.strays) == (0, None, 0)
