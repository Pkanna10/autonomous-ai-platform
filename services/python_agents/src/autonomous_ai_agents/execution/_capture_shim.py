"""The engine's capture shim (emergence round 2, S4, VER-1): the benchmark's
own package calls, replayed with their repetition and each distinct input once.

The runners run it by absolute path, as ``_opcount_shim`` (same sandbox,
launcher, output channel and contract: Python 3.8 grammar and runtime, the
standard library only)::

    python [options] _capture_shim.py OUT ROOT (module NAME | script PATH) [ARG ...]

One launch, three steps; nothing is written but OUT:

1. Capture. A finder first on ``sys.meta_path`` wraps, in every module
   imported from a file under ROOT, the public functions that module
   defines, a function decorated there included (a callable, not a class,
   whose ``__wrapped__`` chain ends in one, such as ``functools.lru_cache``
   on it; the cache methods stay on the wrapper). A wrapped function called directly from the target's own file,
   outside any other wrapped call (a depth counter), is a point: its call
   is recorded in memory when every argument is plain (``plain``: str,
   bytes, int, float, bool, None, and lists, tuples and str-keyed dicts of
   them); a point with any other argument is skipped with every call it
   recorded. The target runs as ``__main__``, unprofiled, with the
   recursion limit doubled for the wrappers' frames.
2. Replay, after the target returns. Before each leg every module under
   ROOT is dropped from ``sys.modules`` and imported again unwrapped, so
   nothing the benchmark or an earlier leg filled survives. The
   ``sequence`` leg calls every recorded call in the benchmark's order (its
   repetition kept); then one leg per point calls each distinct input of
   that point once. A leg runs under cProfile and counts every call it saw
   but this file's own frames; a replayed call that raises is counted, a
   returned generator is drained.
3. OUT, ASCII JSON of at most ``MAX_DOC_BYTES``::

    {"version": 1, "corpus": "<sha256 of the recorded calls>",
     "sequence": <int>, "skipped": <int>, "points": [{"point":
     "<module.function>", "calls": <int>, "distinct": <int>,
     "counted": <int>, "raised": <int>}, ...]}

No literal leaves the process: OUT holds counts, names and one hash. Past
``MAX_POINTS`` points the next ones are skipped; a corpus past
``MAX_CORPUS_BYTES`` or ``MAX_CALLS`` calls records no point at all (one
more skipped). A target that raises or exits non-zero writes no OUT and its
exit passes through. The workload controls this interpreter, so the engine
treats OUT as untrusted (``measure.parse_capture``).
"""

from __future__ import annotations

import sys

MIN_PYTHON = (3, 8)
"""The oldest workload interpreter the shim runs on."""


def interpreter_problem(version: tuple[int, ...]) -> str | None:
    """Why the shim cannot run on Python ``version``, or ``None``."""
    if tuple(version[:2]) >= MIN_PYTHON:
        return None
    return f"the engine's capture needs Python 3.8 or later; this is Python {version[0]}.{version[1]}"  # fmt: skip


def path_is_safe() -> bool:
    """-P, -I or PYTHONSAFEPATH: the script's directory is not on ``sys.path``
    (before 3.11 only -I)."""
    return bool(getattr(sys.flags, "safe_path", sys.flags.isolated))


if __name__ == "__main__":
    _PROBLEM = interpreter_problem(sys.version_info[:2])
    if _PROBLEM is not None:
        raise SystemExit(_PROBLEM)
    if not path_is_safe():  # sys.path[0] is this file's directory
        del sys.path[0]

import base64  # noqa: E402
import cProfile  # noqa: E402
import functools  # noqa: E402
import hashlib  # noqa: E402
import importlib  # noqa: E402
import importlib.machinery  # noqa: E402
import importlib.util  # noqa: E402
import inspect  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import pkgutil  # noqa: E402
import runpy  # noqa: E402
import types  # noqa: E402
from typing import TYPE_CHECKING, cast  # noqa: E402

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    Fn = Callable[..., object]

VERSION, MAX_DOC_BYTES, MAX_POINTS, MAX_DEPTH, MAX_NAME_CHARS = 1, 4096, 8, 32, 192
MAX_CORPUS_BYTES, MAX_CALLS = 8 * 1024 * 1024, 200_000
DOC_KEYS = ("version", "corpus", "sequence", "skipped", "points")
POINT_KEYS = ("point", "calls", "distinct", "counted", "raised")
CACHE_METHODS = ("cache_info", "cache_clear", "cache_parameters")  # functools' memo
USAGE = "usage: _capture_shim.py OUT ROOT (module NAME | script PATH) [ARG ...]"


class UnplainError(Exception):
    """An argument the corpus cannot hold."""


def plain(value: object, depth: int = 0) -> object:
    """``value`` as tagged JSON: bytes ``{"b": base64}``, a tuple ``{"t":
    [...]}``, a dict ``{"d": [[key, value], ...]}``; ``UnplainError`` otherwise."""
    kind = type(value)
    if value is None or kind in (bool, int, float, str):
        return value
    if depth >= MAX_DEPTH:
        raise UnplainError("nested too deep")
    if isinstance(value, bytes) and kind is bytes:
        return {"b": base64.b64encode(value).decode("ascii")}
    if isinstance(value, (list, tuple)) and kind in (list, tuple):
        items = [plain(item, depth + 1) for item in value]
        return items if kind is list else {"t": items}
    if isinstance(value, dict) and kind is dict and all(type(k) is str for k in value):
        return {"d": [[k, plain(v, depth + 1)] for k, v in value.items()]}
    raise UnplainError(kind.__name__)


def unplain(value: object) -> object:
    """``plain``'s inverse, a fresh copy on every call."""
    if isinstance(value, list):
        return [unplain(item) for item in value]
    if isinstance(value, dict):
        tag, inner = next(iter(value.items()))
        if tag == "b":
            return base64.b64decode(inner)
        if tag == "t":
            return tuple(unplain(item) for item in inner)
        return {k: unplain(v) for k, v in inner}
    return value


def defined_function(value: object) -> object:
    """``value`` when a function, a class or not callable, else the end of its
    ``__wrapped__`` chain (``None`` for a loop or a chain that raises)."""
    if (
        type(value) is types.FunctionType
        or isinstance(value, type)
        or not callable(value)
    ):
        return value
    try:
        return inspect.unwrap(value)
    except Exception:  # the workload's own attribute: a loop or a raise
        return None


def _call(fn: Fn, args: list[object], kwargs: dict[str, object]) -> int:
    """One replayed call: 1 when it raised, else 0 (a generator drained;
    ``type`` and ``is``, so the check itself is no counted call)."""
    try:
        result = fn(*args, **kwargs)
        if type(result) is types.GeneratorType:
            for _ in result:
                pass
    except Exception:  # the trial's own error, counted on its side
        return 1
    return 0


class Capture:
    """The points, the distinct inputs and the calls of one target run."""

    def __init__(self, root: str) -> None:
        self.root = os.path.join(os.path.realpath(root), "")
        self.target, self.depth, self.on, self.full = "", 0, True, False
        self.points: list[str] = []
        self.skipped: set[str] = set()
        self.inputs: dict[str, int] = {}
        self.calls: list[tuple[str, int]] = []
        self.size = 0
        self._direct: dict[str, bool] = {}

    def under(self, path: str) -> bool:
        return os.path.realpath(path).startswith(self.root)

    def patch(self, module: types.ModuleType) -> None:
        """Wrap ``module``'s public functions defined in it (an ASCII name of
        at most ``MAX_NAME_CHARS``)."""
        name = module.__name__
        for attr, value in list(vars(module).items()):
            point = f"{name}.{attr}"
            if (
                attr.startswith("_")
                or not point.isascii()
                or len(point) > MAX_NAME_CHARS
            ):
                continue
            origin = defined_function(value)
            if type(origin) is types.FunctionType and origin.__module__ == name:
                setattr(module, attr, self.wrap(point, cast("Fn", value)))

    def wrap(self, point: str, fn: Fn) -> Fn:
        @functools.wraps(fn)
        def wrapper(*args: object, **kwargs: object) -> object:
            if self.depth or not self.on:
                return fn(*args, **kwargs)
            caller = sys._getframe(1).f_code.co_filename
            direct = self._direct.get(caller)
            if direct is None:
                direct = self._direct[caller] = os.path.realpath(caller) == self.target
            if direct:
                self.record(point, args, kwargs)
            self.depth += 1
            try:
                return fn(*args, **kwargs)
            finally:
                self.depth -= 1

        for method in CACHE_METHODS:
            if hasattr(fn, method):
                setattr(wrapper, method, getattr(fn, method))
        return wrapper

    def record(self, point: str, args: tuple[object, ...], kwargs: dict[str, object]) -> None:  # fmt: skip
        full = point not in self.points and len(self.points) >= MAX_POINTS
        if point in self.skipped or full:
            self.skipped.add(point)
            return
        try:
            key = json.dumps([plain(list(args)), plain(dict(sorted(kwargs.items())))])
        except (UnplainError, RecursionError, ValueError):
            self.skipped.add(point)
            return
        if point not in self.points:
            self.points.append(point)
        if key not in self.inputs:
            self.inputs[key] = len(self.inputs)
            self.size += len(key)
        self.calls.append((point, self.inputs[key]))
        if self.size > MAX_CORPUS_BYTES or len(self.calls) >= MAX_CALLS:
            self.on = False
            self.full = True

    def _fresh(self) -> None:
        """Drop every module under the root from ``sys.modules``."""
        for name, module in list(sys.modules.items()):
            file = getattr(module, "__file__", None)
            if isinstance(file, str) and self.under(file):
                del sys.modules[name]

    def leg(self, calls: Sequence[tuple[str, int]], keys: Sequence[str]) -> tuple[int, int]:  # fmt: skip
        """One leg in fresh modules: (the calls cProfile saw, the raised)."""
        self._fresh()
        found: dict[str, Fn] = {}
        for point in dict.fromkeys(p for p, _ in calls):
            module, _, attr = point.rpartition(".")
            found[point] = getattr(importlib.import_module(module), attr)
        ready: list[tuple[Fn, list[object], dict[str, object]]] = []
        for point, index in calls:
            args, kwargs = json.loads(keys[index])
            ready.append((found[point], cast("list[object]", unplain(args)),
                          cast("dict[str, object]", unplain(kwargs))))  # fmt: skip
        profiler, raised = cProfile.Profile(), 0
        profiler.enable()
        for fn, args, kwargs in ready:
            raised += _call(fn, args, kwargs)
        profiler.disable()
        profiler.create_stats()
        stats = profiler.stats  # cProfile's own: (file, line, name) -> (calls, ...)
        return sum(row[1] for key, row in stats.items() if key[0] != __file__), raised

    def document(self) -> bytes:
        """OUT: the corpus hash, the sequence leg, then each point's leg."""
        calls = [] if self.full else [c for c in self.calls if c[0] not in self.skipped]
        keys = sorted(self.inputs, key=self.inputs.__getitem__)
        corpus = hashlib.sha256(json.dumps([[p, keys[i]] for p, i in calls]).encode()).hexdigest()  # fmt: skip
        sequence = self.leg(calls, keys)[0] if calls else 0
        points = []
        for point in dict.fromkeys(p for p, _ in calls):
            mine = [c for c in calls if c[0] == point]
            once = list(dict.fromkeys(mine))
            counted, raised = self.leg(once, keys)
            points.append({"point": point, "calls": len(mine), "distinct": len(once),
                           "counted": counted, "raised": raised})  # fmt: skip
        self._fresh()
        doc = {"version": VERSION, "corpus": corpus, "sequence": sequence,
               "skipped": len(self.skipped) + int(self.full), "points": points}  # fmt: skip
        return json.dumps(doc).encode("ascii")


class _Loader:
    """A module's own loader, then ``Capture.patch`` on what it ran."""

    def __init__(self, inner: importlib.machinery.SourceFileLoader, capture: Capture) -> None:  # fmt: skip
        self._inner, self._capture = inner, capture

    def __getattr__(self, name: str) -> object:
        return getattr(self._inner, name)

    def create_module(self, spec: importlib.machinery.ModuleSpec) -> types.ModuleType | None:  # fmt: skip
        return self._inner.create_module(spec)

    def exec_module(self, module: types.ModuleType) -> None:
        self._inner.exec_module(module)
        self._capture.patch(module)


class _Finder:
    """``PathFinder``'s spec, its loader wrapped, for a module under the root."""

    def __init__(self, capture: Capture) -> None:
        self.capture = capture

    def find_spec(self, name: str, path: Sequence[str] | None = None,
                  target: object = None) -> importlib.machinery.ModuleSpec | None:  # fmt: skip
        spec = importlib.machinery.PathFinder.find_spec(name, path)
        if spec is None or spec.origin is None or not self.capture.under(spec.origin):
            return None
        if not isinstance(spec.loader, importlib.machinery.SourceFileLoader):
            return None
        spec.loader = _Loader(spec.loader, self.capture)  # type: ignore[assignment]
        return spec


def main(argv: Sequence[str], *, safe_path: bool | None = None) -> None:
    """Capture and replay the target (module docstring); write ``argv[1]``;
    ``safe_path`` defaults to the interpreter's."""
    if len(argv) < 5 or argv[3] not in ("module", "script"):
        raise SystemExit(USAGE)
    out, capture, kind, target = argv[1], Capture(argv[2]), argv[3], argv[4]
    keep = path_is_safe() if safe_path is None else safe_path
    sys.argv[:] = [target, *argv[5:]]
    finder, limit = _Finder(capture), sys.getrecursionlimit()
    sys.meta_path.insert(0, finder)
    try:
        if kind == "module":
            if not keep:
                sys.path.insert(0, os.getcwd())
            spec = importlib.util.find_spec(target)
            capture.target = (
                os.path.realpath(spec.origin) if spec and spec.origin else ""
            )
            run = functools.partial(runpy.run_module, target, run_name="__main__", alter_sys=True)  # fmt: skip
        else:
            path = os.path.abspath(target)
            if pkgutil.get_importer(path) is None and not keep:  # runpy's test: a file
                sys.path.insert(0, os.path.dirname(os.path.realpath(path)))
            main_file = (
                os.path.join(path, "__main__.py") if os.path.isdir(path) else path
            )
            capture.target = os.path.realpath(main_file)
            run = functools.partial(runpy.run_path, path, run_name="__main__")
        sys.setrecursionlimit(2 * limit + 50)
        try:
            run()
        except SystemExit as stop:
            if stop.code not in (None, 0):
                raise
    finally:
        sys.setrecursionlimit(limit)
        sys.meta_path.remove(finder)
        capture.on = False
    data = capture.document()
    with open(out, "wb") as file:
        file.write(data)


if __name__ == "__main__":
    main(sys.argv)
