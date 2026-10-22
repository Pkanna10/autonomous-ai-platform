"""The engine's cProfile shim: profile one Python workload and write a JSON summary.

The profiler runs it by absolute path, inside the sandbox and in the
workload's own interpreter (Python 3.11+, standard library only)::

    python [the workload's options] _profile_shim.py OUT module NAME [ARG ...]
    python [the workload's options] _profile_shim.py OUT script PATH [ARG ...]

Run as a script, it first drops its own directory (the engine's package)
from ``sys.path``, before any other import can resolve there. It then sets
up what ``python -m NAME`` or ``python PATH`` would have (the working
directory or the script's directory first on ``sys.path``, nothing under
``-P`` or ``-I``; ``sys.argv``), runs the target as ``__main__`` under
``cProfile`` and, even when the target raises or exits, writes OUT
(``encode``). A ``SystemExit`` passes through, so the exit status is the
workload's. A directory or zip target also gets its parent on ``sys.path``.

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

import sys

if __name__ == "__main__":
    # sys.path[0] is this file's directory unless -P or -I set safe_path.
    if not sys.flags.safe_path:
        del sys.path[0]

import cProfile  # noqa: E402
import functools  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import runpy  # noqa: E402
from collections.abc import Mapping, Sequence  # noqa: E402

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
        values = (file, line, function, primitive, calls, -minus_self, later)
        part = json.dumps(dict(zip(ENTRY_KEYS, values, strict=True)))
        size += len(part) + 2
        if size > MAX_DOC_BYTES:
            break
        parts.append(part)
    return (head + '"entries": [' + ", ".join(parts) + "]}").encode("ascii")


def main(argv: Sequence[str], *, safe_path: bool = sys.flags.safe_path) -> None:
    """Run ``argv[3]`` as ``__main__`` under cProfile and write ``argv[1]``."""
    if len(argv) < 4 or argv[2] not in ("module", "script"):
        raise SystemExit(USAGE)
    out, kind, target, args = argv[1], argv[2], argv[3], list(argv[4:])
    sys.argv[:] = [target, *args]
    if kind == "module":
        first = os.getcwd()
        run = functools.partial(
            runpy.run_module, target, run_name="__main__", alter_sys=True
        )
    else:
        first = os.path.dirname(os.path.realpath(target))
        run = functools.partial(runpy.run_path, target, run_name="__main__")
    if not safe_path:
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
