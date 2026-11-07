"""The engine's operation-count shim (G6a): count the calls of one Python workload run.

The runners run it by absolute path, the way the profiler runs
``_profile_shim`` (same sandbox, launcher and output channel, the workload's
own interpreter and options), and it has the same contract, kept to the
Python 3.8 grammar and runtime and the standard library::

    python [the workload's options] _opcount_shim.py OUT module NAME [ARG ...]
    python [the workload's options] _opcount_shim.py OUT script PATH [ARG ...]

Run as a script, it first drops its own directory from ``sys.path``, sets up
what ``python -m NAME`` or ``python PATH`` would have, runs the target as
``__main__`` under ``cProfile`` and, even when the target raises or exits,
writes OUT (``encode``). A ``SystemExit`` passes through, so the exit status
is the workload's; it prints nothing, so stdout and stderr are the
workload's too. ``pkgutil`` is imported before counting starts.

What it counts, and why: every call cProfile sees while the target runs,
Python function calls (frame starts and generator or coroutine resumptions)
and C calls (builtin and extension functions and methods; calling a type,
``dict(x)``, is not one) apart. These are the counts
CPython 3.8 to 3.14 all expose at C speed (cProfile's overhead, the reason
the counted run is off by default); its timer does not touch them, so one
run per side is deterministic for deterministic code. Allocations are not
counted: no CPython in that range has a cumulative allocation counter
(``tracemalloc`` keeps live and peak bytes, ``sys.getallocatedblocks`` live
blocks, and the gc counters changed with 3.13's and 3.14's collectors).
Bytecode steps are not counted: ``sys.settrace`` opcode events cost 50-100x
and ``sys.monitoring`` exists from 3.12 only. Counts compare within one
interpreter version only: 3.12 moved cProfile onto ``sys.monitoring`` (it
then sees every thread, older versions the main thread), and comprehension
inlining changed what a call is.

OUT is ASCII JSON, at most ``MAX_DOC_BYTES``::

    {"version": 1, "python_calls": <int>, "c_calls": <int>}

The workload controls this interpreter, so the engine treats OUT as
untrusted (``measure.parse_counts``).
"""

from __future__ import annotations

import sys

MIN_PYTHON = (3, 8)
"""The oldest workload interpreter the shim runs on."""


def interpreter_problem(version: tuple[int, ...]) -> str | None:
    """Why the shim cannot run on Python ``version``, or ``None``."""
    if tuple(version[:2]) >= MIN_PYTHON:
        return None
    need = f"{MIN_PYTHON[0]}.{MIN_PYTHON[1]}"
    return (
        f"the engine's operation count needs Python {need} or later;"
        f" this is Python {version[0]}.{version[1]}"
    )


def path_is_safe(flags: object) -> bool:
    """``sys.flags.safe_path`` (-P, -I, PYTHONSAFEPATH); before Python 3.11
    only -I (``isolated``) kept the script's directory off ``sys.path``."""
    return bool(getattr(flags, "safe_path", getattr(flags, "isolated", 0)))


if __name__ == "__main__":
    _PROBLEM = interpreter_problem(sys.version_info[:2])
    if _PROBLEM is not None:
        raise SystemExit(_PROBLEM)
    if not path_is_safe(sys.flags):  # sys.path[0] is this file's directory
        del sys.path[0]

import cProfile  # noqa: E402
import functools  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import pkgutil  # noqa: E402
import runpy  # noqa: E402
from typing import TYPE_CHECKING  # noqa: E402

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

FORMAT_VERSION = 1
MAX_DOC_BYTES = 4096
DOC_KEYS = ("version", "python_calls", "c_calls")
USAGE = "usage: _opcount_shim.py OUT (module NAME | script PATH) [ARG ...]"
C_FILE = "~"
"""cProfile's file name for a C function."""

if TYPE_CHECKING:  # subscripted builtins at run time need Python 3.9
    Label = tuple[str, int, str]
    Row = tuple[int, int, float, float, object]


def encode(stats: Mapping[Label, Row], own_file: str) -> bytes:
    """The counts of ``cProfile.Profile.stats`` (total calls, recursion
    included), without ``own_file``'s frames."""
    python = c = 0
    for (file, _, _), row in stats.items():
        if file == own_file:
            continue
        if file == C_FILE:
            c += row[1]
        else:
            python += row[1]
    doc = {"version": FORMAT_VERSION, "python_calls": python, "c_calls": c}
    return json.dumps(doc).encode("ascii")


def main(argv: Sequence[str], *, safe_path: bool | None = None) -> None:
    """Run ``argv[3]`` as ``__main__`` under cProfile and write ``argv[1]``;
    ``safe_path`` defaults to the interpreter's."""
    if len(argv) < 4 or argv[2] not in ("module", "script"):
        raise SystemExit(USAGE)
    out, kind, target, args = argv[1], argv[2], argv[3], list(argv[4:])
    keep_path = path_is_safe(sys.flags) if safe_path is None else safe_path
    sys.argv[:] = [target, *args]
    first: str | None = None
    if kind == "module":
        first = os.getcwd()
        run = functools.partial(
            runpy.run_module, target, run_name="__main__", alter_sys=True
        )
    else:
        path = os.path.abspath(target)
        if pkgutil.get_importer(path) is None:  # runpy's test: a plain file
            first = os.path.dirname(os.path.realpath(path))
        run = functools.partial(runpy.run_path, path, run_name="__main__")
    if first is not None and not keep_path:
        sys.path.insert(0, first)
    profiler = cProfile.Profile()
    try:
        profiler.runcall(run)
    finally:
        profiler.create_stats()
        with open(out, "wb") as file:
            file.write(encode(profiler.stats, __file__))


if __name__ == "__main__":
    main(sys.argv)
