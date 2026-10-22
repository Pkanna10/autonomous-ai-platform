"""The engine's cProfile shim: profile one Python workload and write a JSON summary.

The profiler runs it by absolute path, inside the sandbox and in the
workload's own interpreter, which may be older than the engine's: the source
keeps to the Python 3.8 grammar and runtime (``MIN_PYTHON``; annotations stay
unevaluated) and the standard library; Python 3.7 exits with a message
naming the floor (``interpreter_problem``), and anything older cannot even
compile the file (a ``SyntaxError``, so a note too)::

    python [the workload's options] _profile_shim.py OUT module NAME [ARG ...]
    python [the workload's options] _profile_shim.py OUT script PATH [ARG ...]

Run as a script, it first drops its own directory (the engine's package)
from ``sys.path``, before any other import can resolve there. It then sets
up what ``python -m NAME`` or ``python PATH`` would have (the working
directory or the script's real directory first on ``sys.path``, nothing
under ``-P`` or ``-I``; a directory or zip target is put there by ``runpy``
itself, as CPython does; ``sys.argv``), runs the target as ``__main__``
under ``cProfile`` and, even when the target raises or exits, writes OUT
(``encode``). A ``SystemExit`` passes through, so the exit status is the
workload's. A script's ``__file__``, its frames and ``sys.argv[0]`` carry its
absolute path (CPython makes ``__file__`` absolute; ``runpy`` sets
``argv[0]`` to the path it runs). ``pkgutil``, which ``runpy`` imports
lazily, is imported before profiling starts, so its imports are not
profiled; the target's own imports are.

OUT is ASCII JSON, at most ``MAX_DOC_BYTES``::

    {"version": 1, "total_s": <self time of every frame but the shim's>,
     "entries": [{"file", "line", "function", "primitive_calls",
                  "total_calls", "self_s", "cumulative_s"}, ...]}

Entries are frames with a real file (not builtins, not ``<frozen ...>``
code), slowest self time first, at most ``MAX_ENTRIES``; a file longer than
``MAX_FILE_CHARS`` is left out and a function name cut to
``MAX_FUNCTION_CHARS``. The workload controls this interpreter, so the
engine treats every byte of OUT as an untrusted hint (``profiler``); it
never unmarshals pstats data.
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
        f"the engine's profiler needs Python {need} or later;"
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
    # sys.path[0] is this file's directory unless safe_path is set.
    if not path_is_safe(sys.flags):
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
MAX_DOC_BYTES = 1 << 20
MAX_ENTRIES = 1000
MAX_FILE_CHARS = 4096
MAX_FUNCTION_CHARS = 256
DOC_KEYS = ("version", "total_s", "entries")
ENTRY_KEYS = (
    "file",
    "line",
    "function",
    "primitive_calls",
    "total_calls",
    "self_s",
    "cumulative_s",
)
USAGE = "usage: _profile_shim.py OUT (module NAME | script PATH) [ARG ...]"

if TYPE_CHECKING:  # subscripted builtins at run time need Python 3.9
    Label = tuple[str, int, str]
    Row = tuple[int, int, float, float, object]


def encode(stats: Mapping[Label, Row], own_file: str) -> bytes:
    """The JSON summary of ``cProfile.Profile.stats``, without ``own_file``."""
    total, rows = 0.0, []
    for (file, line, function), row in stats.items():
        if file == own_file:
            continue
        primitive, calls, raw_self, cumulative, _ = row
        self_s = max(0.0, float(raw_self))
        total += self_s
        if file != "~" and not file.startswith("<") and len(file) <= MAX_FILE_CHARS:
            cut = function[:MAX_FUNCTION_CHARS]
            later = max(0.0, float(cumulative))
            rows.append((-self_s, file, line, cut, primitive, calls, later))
    rows.sort()
    head = f'{{"version": {FORMAT_VERSION}, "total_s": {json.dumps(total)}, '
    parts: list[str] = []
    size = len(head) + len('"entries": []}')
    for minus_self, file, line, function, primitive, calls, later in rows[:MAX_ENTRIES]:
        part = json.dumps(  # in ENTRY_KEYS order (a test checks it)
            {
                "file": file,
                "line": line,
                "function": function,
                "primitive_calls": primitive,
                "total_calls": calls,
                "self_s": -minus_self,
                "cumulative_s": later,
            }
        )
        size += len(part) + 2
        if size > MAX_DOC_BYTES:
            break
        parts.append(part)
    return (head + '"entries": [' + ", ".join(parts) + "]}").encode("ascii")


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
