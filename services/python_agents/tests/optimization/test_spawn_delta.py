"""The ``process_spawn`` spawn delta and the ``unparsable_source`` label (N0, D62).

``check_capture(..., base_of=)`` compares a modified file with its base: a
spawn-bearing statement the base already holds no longer refuses an edit, a
new one does (keyed on the finding, the enclosing function and the
statement's shape, inside the chain of its enclosing headers), uses of names
a spawn statement bound count as findings, and an added or changed statement
that refers to a function or class whose base body holds a finding is refused
(the one-level call check). A file the engine cannot
parse is refused as ``unparsable_source``, never as ``process_spawn``.

The E0a table (``.claude/handoff/step3/e0/e0-spawn.md``) is pinned on
verbatim excerpts of more_itertools 11.1.0 ``more.py`` (MIT) and mistune
3.3.4 ``plugins/__init__.py`` (BSD-3-Clause), the two files E0a found
locked. No fakes: the real rule on byte strings; ``base_of`` is a dict
lookup standing for the trial runner's ``git cat-file`` read.
"""

from __future__ import annotations

import ast
import sys
from collections.abc import Callable

import pytest

from autonomous_ai_agents.common.models import (
    METRIC_CPU_TIME_S,
    METRIC_PEAK_RSS_BYTES,
    METRIC_WALL_TIME_S,
    Violation,
    ViolationRule,
)
from autonomous_ai_agents.execution.editor import SYSTEM_PROMPT
from autonomous_ai_agents.execution.protocols import Change
from autonomous_ai_agents.optimization.anticheat import _spawn_problem, check_capture

RSS = frozenset({METRIC_PEAK_RSS_BYTES})
MODE = "100644"
MORE, PLUGINS, CORE = (
    "more_itertools/more.py",
    "src/mistune/plugins/__init__.py",
    "pkg/core.py",
)

# more_itertools 11.1.0, more_itertools/more.py: the imports callback_iter
# needs, split_when (a hot function of the E0a workload) and callback_iter
# (line 4078 holds the base __import__), docstrings dropped.
MORE_PY = b"""\
from queue import Empty, Queue
from threading import Lock


def split_when(iterable, pred, maxsplit=-1):
    if maxsplit == 0:
        yield list(iterable)
        return

    it = iter(iterable)
    try:
        cur_item = next(it)
    except StopIteration:
        return

    buf = [cur_item]
    for next_item in it:
        if pred(cur_item, next_item):
            yield buf
            if maxsplit == 1:
                yield [next_item, *it]
                return
            buf = []
            maxsplit -= 1

        buf.append(next_item)
        cur_item = next_item

    yield buf


class AbortThread(BaseException):
    pass


class callback_iter:
    def __init__(self, func, callback_kwd='callback', wait_seconds=0.1):
        self._func = func
        self._callback_kwd = callback_kwd
        self._aborted = False
        self._future = None
        self._wait_seconds = wait_seconds

        # Lazily import concurrent.future
        self._module = __import__('concurrent.futures').futures
        self._executor = self._module.ThreadPoolExecutor(max_workers=1)
        self._iterator = self._reader()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self._aborted = True
        self._executor.shutdown()

    def __iter__(self):
        return self

    def __next__(self):
        return next(self._iterator)

    @property
    def done(self):
        if self._future is None:
            return False
        return self._future.done()

    @property
    def result(self):
        if self._future:
            try:
                return self._future.result(timeout=0)
            except self._module.TimeoutError:
                pass

        raise RuntimeError('Function has not yet completed')

    def _reader(self):
        q = Queue()

        def callback(*args, **kwargs):
            if self._aborted:
                raise AbortThread('canceled by user')

            q.put((args, kwargs))

        self._future = self._executor.submit(
            self._func, **{self._callback_kwd: callback}
        )

        while True:
            try:
                item = q.get(timeout=self._wait_seconds)
            except Empty:
                pass
            else:
                q.task_done()
                yield item

            if self._future.done():
                break

        remaining = []
        while True:
            try:
                item = q.get_nowait()
            except Empty:
                break
            else:
                q.task_done()
                remaining.append(item)
        q.join()
        yield from remaining
"""

# mistune 3.3.4, src/mistune/plugins/__init__.py, verbatim (the plugin loader).
PLUGINS_PY = b"""\
from importlib import import_module
from typing import TYPE_CHECKING, Dict, Protocol, Union, cast

if TYPE_CHECKING:
    from ..markdown import Markdown

_plugins = {
    "speedup": "mistune.plugins.speedup.speedup",
    "strikethrough": "mistune.plugins.formatting.strikethrough",
    "mark": "mistune.plugins.formatting.mark",
    "insert": "mistune.plugins.formatting.insert",
    "superscript": "mistune.plugins.formatting.superscript",
    "subscript": "mistune.plugins.formatting.subscript",
    "footnotes": "mistune.plugins.footnotes.footnotes",
    "table": "mistune.plugins.table.table",
    "url": "mistune.plugins.url.url",
    "abbr": "mistune.plugins.abbr.abbr",
    "def_list": "mistune.plugins.def_list.def_list",
    "math": "mistune.plugins.math.math",
    "ruby": "mistune.plugins.ruby.ruby",
    "task_lists": "mistune.plugins.task_lists.task_lists",
    "spoiler": "mistune.plugins.spoiler.spoiler",
}


class Plugin(Protocol):
    def __call__(self, md: "Markdown") -> None: ...


_cached_modules: Dict[str, Plugin] = {}

PluginRef = Union[str, Plugin]  # reference to register a plugin


def import_plugin(name: PluginRef) -> Plugin:
    if callable(name):
        return name

    if name in _cached_modules:
        return _cached_modules[name]

    if name in _plugins:
        module_path, func_name = _plugins[name].rsplit(".", 1)
    else:
        module_path, func_name = name.rsplit(".", 1)

    module = import_module(module_path)
    plugin = cast(Plugin, getattr(module, func_name))
    _cached_modules[name] = plugin
    return plugin
"""


def _rep(blob: bytes, old: bytes, new: bytes) -> bytes:
    assert blob.count(old) == 1, old
    return blob.replace(old, new)


def _modify(
    path: str,
    base: bytes | None,
    new: bytes,
    *,
    judged: frozenset[str] = RSS,
    base_of: Callable[[str], bytes | None] | None = None,
) -> tuple[Violation, ...]:
    """``check_capture`` on one modified file whose base content is ``base``."""
    change = Change("M", MODE, MODE, path)
    reader = base_of if base_of is not None else {path: base}.get
    return check_capture((change,), {path: 1}, {path: new}, judged, base_of=reader)


def _refused(found: tuple[Violation, ...], path: str) -> str:
    """Assert exactly one process_spawn violation on ``path``; its message."""
    assert [(v.rule, v.path) for v in found] == [(ViolationRule.process_spawn, path)]
    return found[0].message


def _unparsable(found: tuple[Violation, ...], path: str) -> str:
    """Assert exactly one unparsable_source violation on ``path``; its message."""
    assert [(v.rule, v.path) for v in found] == [
        (ViolationRule.unparsable_source, path)
    ]
    message = found[0].message
    assert message.startswith("unparsable_source: ")
    assert repr(path) in message and "process_spawn" not in message
    return message


# The E0a table: a base finding left untouched passes -----------------------


@pytest.mark.parametrize(
    "new",
    [
        pytest.param(MORE_PY + b"# harmless\n", id="trailing-comment"),
        pytest.param(
            _rep(
                MORE_PY,
                b"    buf = [cur_item]\n    for next_item in it:\n",
                b"    buf = [cur_item]\n    append = buf.append\n"
                b"    for next_item in it:\n",
            ).replace(
                b"        buf.append(next_item)\n", b"        append(next_item)\n"
            ),
            id="split_when-local-binding",
        ),
        pytest.param(
            b"import math\n\n"
            + MORE_PY.replace(b"maxsplit -= 1", b"maxsplit = maxsplit - 1"),
            id="line-shift-and-edit",
        ),
        pytest.param(
            _rep(
                MORE_PY,
                b"        self._func = func\n",
                b"        self._func = func\n        self._lock = Lock()\n",
            ),
            id="edit-inside-the-spawn-class",
        ),
        pytest.param(
            _rep(
                MORE_PY,
                b"def split_when(iterable, pred, maxsplit=-1):\n",
                b"def split_when(iterable, pred, maxsplit: int = -1):\n",
            ),
            id="signature-of-a-clean-function",
        ),
    ],
)
def test_more_itertools_edits_beside_the_base_import_pass(new: bytes) -> None:
    """
    GIVEN more.py with its base ``__import__`` in callback_iter (E0a: every
        edit of the file was refused, for every editor)
    WHEN a trivial or realistic edit leaves that statement as it is
    THEN check_capture reports nothing
    """
    assert _modify(MORE, MORE_PY, new) == ()


@pytest.mark.parametrize(
    "new",
    [
        pytest.param(PLUGINS_PY + b"# harmless\n", id="trailing-comment"),
        pytest.param(
            _rep(
                PLUGINS_PY,
                b'        module_path, func_name = _plugins[name].rsplit(".", 1)\n',
                b'        module_path, _, func_name = _plugins[name].rpartition(".")\n',
            ),
            id="rpartition",
        ),
    ],
)
def test_mistune_plugin_loader_edits_beside_the_base_import_pass(new: bytes) -> None:
    """
    GIVEN mistune's plugin loader, whose base imports importlib.import_module
    WHEN a trivial or realistic edit leaves the loader's statements as they are
    THEN check_capture reports nothing
    """
    assert _modify(PLUGINS, PLUGINS_PY, new) == ()


# The E0a table: what must still be refused ---------------------------------


def test_reusing_the_base_import_for_a_process_pool_is_refused() -> None:
    new = _rep(
        MORE_PY,
        b"        self._iterator = self._reader()\n",
        b"        self._iterator = self._reader()\n"
        b"        self._pool = self._module.ProcessPoolExecutor()\n",
    )

    message = _refused(_modify(MORE, MORE_PY, new), MORE)

    assert "line 48: uses .ProcessPoolExecutor" in message
    assert "uses spawn-bound ._module" in message
    assert "cpu_time_s or peak_rss_bytes is judged" in message


def test_editing_the_base_import_statement_is_refused() -> None:
    new = _rep(
        MORE_PY,
        b"__import__('concurrent.futures').futures",
        b"__import__('concurrent.futures.process').futures",
    )

    message = _refused(_modify(MORE, MORE_PY, new), MORE)

    assert "line 45: uses __import__" in message


def test_a_new_use_of_the_base_import_module_is_refused() -> None:
    new = PLUGINS_PY + b"\n_x = import_module('subprocess')\n"

    message = _refused(_modify(PLUGINS, PLUGINS_PY, new), PLUGINS)

    assert "uses spawn-bound import_module" in message


def test_a_new_call_through_a_kept_subprocess_import_is_refused() -> None:
    """
    GIVEN a base with ``import subprocess`` (the naive added-lines scan passes
        an added ``subprocess.Popen``, e0/scripts/naive_out.txt)
    WHEN an edit adds a call through that name
    THEN it is refused, naming the bound name and the new line
    """
    base = b"import subprocess\n\n\ndef hot(xs):\n    return sorted(xs)\n"
    new = base + b"\n\nsubprocess.Popen(['true'])\n"

    message = _refused(_modify(CORE, base, new), CORE)

    assert "line 8: uses spawn-bound subprocess" in message


def test_a_new_process_pool_import_in_a_clean_file_is_refused() -> None:
    base = b"def skip(src, pos):\n    return pos\n"
    new = base + b"\nfrom concurrent.futures import ProcessPoolExecutor\n"

    message = _refused(_modify(CORE, base, new), CORE)

    assert "imports concurrent.futures.ProcessPoolExecutor" in message


def test_threads_stay_allowed_beside_the_delta() -> None:
    base = b"def skip(src, pos):\n    return pos\n"
    new = (
        base
        + b"\nfrom concurrent.futures import ThreadPoolExecutor\nimport threading\n"
    )

    assert _modify(CORE, base, new) == ()


# The one-level call check --------------------------------------------------


@pytest.mark.parametrize(
    "call",
    [
        b"    with callback_iter(pred) as it:\n        list(it)\n",
        b"    callback_iter(pred)._reader()\n",
        b"    pred.result\n    pred.result()\n",
    ],
    ids=["class", "method", "property-call"],
)
def test_calling_into_a_kept_spawn_statement_is_refused(call: bytes) -> None:
    """
    GIVEN more.py's callback_iter, whose base body holds the finding
    WHEN an edit of split_when adds a call into the class or one of its methods
    THEN it is refused: the kept statement becomes reachable from the hot path
    """
    new = _rep(MORE_PY, b"    yield buf\n\n\nclass", call + b"    yield buf\n\n\nclass")

    message = _refused(_modify(MORE, MORE_PY, new), MORE)

    assert "which holds a process spawn" in message


def test_a_call_into_a_spawning_helper_is_refused_and_a_kept_one_passes() -> None:
    base = (
        b"import subprocess\n\n\n"
        b"def helper():\n    return subprocess.run(['true'])\n\n\n"
        b"def hot(xs):\n    return sorted(xs)\n\n\n"
        b"def cold():\n    return helper()\n"
    )
    added = base.replace(
        b"    return sorted(xs)\n", b"    helper()\n    return sorted(xs)\n"
    )
    kept = base.replace(b"    return sorted(xs)\n", b"    return sorted(set(xs))\n")

    message = _refused(_modify(CORE, base, added), CORE)

    assert "line 9: references helper, which holds a process spawn" in message
    assert _modify(CORE, base, kept) == ()


HELPER_BASE = (
    b"import subprocess\n\n\n"
    b"def helper():\n    return subprocess.run(['true'])\n\n\n"
    b"def hot(xs):\n    return sorted(xs)\n"
)


@pytest.mark.parametrize(
    "new",
    [
        HELPER_BASE.replace(
            b"    return sorted(xs)\n",
            b"    h = helper\n    h()\n    return sorted(xs)\n",
        ),  # fmt: skip
        HELPER_BASE.replace(
            b"    return sorted(xs)\n",
            b"    list(map(helper, xs))\n    return sorted(xs)\n",
        ),  # fmt: skip
        HELPER_BASE.replace(b"def hot(xs):\n", b"def hot(xs, fn=helper):\n    fn()\n"),
        HELPER_BASE + b"\n\n@helper\ndef g():\n    pass\n",
        HELPER_BASE.replace(
            b"    return sorted(xs)\n",
            b"    import functools\n    functools.partial(helper)()\n    return sorted(xs)\n",
        ),  # fmt: skip
        HELPER_BASE.replace(
            b"    return sorted(xs)\n", b"    {0: helper}[0]()\n    return sorted(xs)\n"
        ),  # fmt: skip
        HELPER_BASE.replace(
            b"    return sorted(xs)\n",
            b"    f = lambda: helper()\n    f()\n    return sorted(xs)\n",
        ),  # fmt: skip
    ],
    ids=["alias", "map", "default-argument", "decorator", "partial", "dict", "lambda"],
)
def test_a_reference_to_a_spawning_helper_is_refused(new: bytes) -> None:
    """
    GIVEN ``helper``, whose base body runs a subprocess
    WHEN an edit refers to it without calling it by name (an alias, ``map``,
        a default argument, a decorator, ``functools.partial``, a dict, a lambda)
    THEN it is refused: the kept spawn becomes reachable all the same
    """
    message = _refused(_modify(CORE, HELPER_BASE, new), CORE)

    assert "references helper, which holds a process spawn" in message


def test_subclassing_a_spawning_class_is_refused() -> None:
    base = (
        b"import subprocess\n\n\nclass P:\n"
        b"    def __init__(self):\n        subprocess.run(['x'])\n"
    )
    new = base + b"\n\nclass Q(P):\n    pass\n\n\nQ()\n"

    message = _refused(_modify(CORE, base, new), CORE)

    assert "line 9: references P, which holds a process spawn" in message


def test_a_bare_name_refers_to_a_holder_in_its_own_scope_chain_only() -> None:
    """
    GIVEN a method ``result`` of a class whose base body holds a finding
    WHEN an edit elsewhere reads a local variable that is also named ``result``
    THEN it passes: a bare name never reaches a method; ``x.result`` still does
    """
    base = (
        b"import subprocess\n\n\nclass Job:\n    def result(self):\n"
        b"        return subprocess.run(['x'])\n\n\n"
        b"def hot(xs):\n    return sorted(xs)\n"
    )
    local = base.replace(
        b"    return sorted(xs)\n", b"    result = sorted(xs)\n    return result\n"
    )
    attribute = base.replace(
        b"    return sorted(xs)\n", b"    xs.result\n    return sorted(xs)\n"
    )

    assert _modify(CORE, base, local) == ()
    assert "references result" in _refused(_modify(CORE, base, attribute), CORE)


def test_dunder_methods_are_reached_through_their_class_only() -> None:
    """
    GIVEN a class whose ``__init__`` holds a finding
    WHEN an edit adds ``super().__init__()`` in another class, or calls the class
    THEN only the call of the class is refused (a dunder name is not a holder)
    """
    base = (
        b"class Pool:\n    def __init__(self):\n"
        b"        self.m = __import__('json')\n\n\n"
        b"class Other:\n    def __init__(self):\n        self.x = 1\n"
    )
    dunder = base.replace(
        b"        self.x = 1\n", b"        super().__init__()\n        self.x = 1\n"
    )
    direct = base + b"\n\nPOOL = Pool()\n"

    assert _modify(CORE, base, dunder) == ()
    assert "references Pool" in _refused(_modify(CORE, base, direct), CORE)


# Keys: the enclosing function, swaps and statement shapes ------------------


def test_moving_a_spawn_statement_to_another_function_is_refused() -> None:
    """
    GIVEN a spawn statement in ``a``
    WHEN an edit deletes it there and adds the same statement in ``b``
    THEN it is refused: the key holds the enclosing function, so the swap does
        not cancel in the multiset
    """
    base = (
        b"import subprocess\n\n\ndef a():\n    subprocess.run(['x'])\n    return 1\n\n\n"
        b"def b():\n    return 2\n"
    )
    new = (
        b"import subprocess\n\n\ndef a():\n    return 1\n\n\n"
        b"def b():\n    subprocess.run(['x'])\n    return 2\n"
    )

    message = _refused(_modify(CORE, base, new), CORE)

    assert "line 9: uses spawn-bound subprocess" in message


def test_a_second_copy_of_a_spawn_statement_is_refused() -> None:
    base = b"import os\n\n\ndef a():\n    os.system('x')\n"
    new = b"import os\n\n\ndef a():\n    os.system('x')\n    os.system('x')\n"

    assert "line 6: uses os.system" in _refused(_modify(CORE, base, new), CORE)


def test_a_finding_in_a_compound_header_is_keyed_on_the_header() -> None:
    base = b"import concurrent.futures as cf\n\n\ndef run(xs):\n    return xs\n"
    new = base + b"\n\nwith cf.ProcessPoolExecutor() as pool:\n    pass\n"
    body_edit = (
        b"import os\n\n\nif os.fork():\n    x = 1\n",
        b"import os\n\n\nif os.fork():\n    x = 2\n",
    )

    message = _refused(_modify(CORE, base, new), CORE)

    assert "line 8: uses .ProcessPoolExecutor" in message
    assert _modify(CORE, *body_edit) == ()


GUARDED = (
    b"import subprocess\n\n\n"
    b"def hot(xs, parallel=False):\n"
    b"    if parallel:\n        subprocess.run(['x'])\n"
    b"    return sorted(xs)\n\n\n"
    b"def cold(xs):\n    return xs\n"
)


@pytest.mark.parametrize(
    ("base", "new"),
    [
        (GUARDED, GUARDED.replace(b"parallel=False", b"parallel=True")),
        (GUARDED, GUARDED.replace(b"    if parallel:\n", b"    if True:\n")),
        (
            GUARDED,
            GUARDED.replace(
                b"    if parallel:\n        subprocess.run(['x'])\n",
                b"    subprocess.run(['x'])\n",
            ),
        ),
        (
            b"def hot(xs):\n    try:\n        pass\n    except ImportError:\n"
            b"        import multiprocessing\n    return sorted(xs)\n",
            b"def hot(xs):\n    import multiprocessing\n    try:\n        pass\n"
            b"    except ImportError:\n        pass\n    return sorted(xs)\n",
        ),
        (
            b"import os\n\n\nclass C:\n    def go(self):\n        os.system('x')\n",
            b"import os\n\n\n@dataclass\nclass C:\n    def go(self):\n        os.system('x')\n",  # fmt: skip
        ),
    ],
    ids=[
        "default-flipped",
        "guard-flipped",
        "moved-out-of-the-guard",
        "moved-out-of-except",
        "class-decorated",
    ],  # fmt: skip
)
def test_an_edit_of_a_header_around_a_kept_spawn_is_refused(
    base: bytes, new: bytes
) -> None:
    """
    GIVEN a kept spawn statement under a guard, a dead ``except`` or a def
    WHEN an edit changes the def's signature, the guard, or moves the statement
        out of its block, with no call added anywhere
    THEN it is refused: the key holds the chain of enclosing headers, so the
        kept statement no longer matches its base
    """
    assert "may start processes" in _refused(_modify(CORE, base, new), CORE)


def test_an_edit_of_a_header_without_a_finding_passes() -> None:
    new = GUARDED.replace(b"def cold(xs):\n", b"def cold(xs, flag=True):\n").replace(
        b"    return sorted(xs)\n", b"    xs = list(xs)\n    return sorted(xs)\n"
    )

    assert _modify(CORE, GUARDED, new) == ()


def test_a_huge_hex_literal_does_not_break_the_statement_key() -> None:
    """A decimal ``repr`` of this constant would exceed the int-to-str limit."""
    base = b"import os\nos.fork()\n"
    new = base + b"X = 0x" + b"f" * 5000 + b"\n"

    assert _modify(CORE, base, new) == ()


# Names a spawn statement bound ---------------------------------------------


@pytest.mark.parametrize(
    ("binding", "use"),
    [
        (b"run = subprocess.run\n", b"run(['x'])\n"),
        (b"p = __import__('subprocess')\nq = p\n", b"q.Popen(['x'])\n"),
        (b"launch = os.posix_spawn\n", b"launch('x', ['x'], {})\n"),
        (b"for sp in [subprocess]:\n    pass\n", b"sp.run(['x'])\n"),
        (b"with __import__('pty') as tty:\n    pass\n", b"tty.spawn('x')\n"),
        (b"if (mod := __import__('pty')):\n    pass\n", b"mod.spawn('x')\n"),
        (b"mods = [m for m in [subprocess]]\n", b"m.run(['x'])\n"),
        (b"ann: object = subprocess\n", b"ann.run(['x'])\n"),
        (b"aug = []\naug += [subprocess]\n", b"aug[0].run(['x'])\n"),
        (b"a, (b, *c) = 1, (subprocess, 2)\n", b"c.run(['x'])\n"),
        (b"box = {}\nbox['k'] = subprocess\n", b"box['k'].run(['x'])\n"),
        (b"def f():\n    global g\n    g = subprocess\n", b"g.run(['x'])\n"),
    ],
    ids=[
        "alias",
        "chain",
        "os-alias",
        "for",
        "with",
        "walrus",
        "comprehension",
        "annotated",
        "augmented",
        "unpacking",
        "subscript",
        "global",
    ],  # fmt: skip
)
def test_a_new_use_of_a_spawn_bound_name_is_refused(binding: bytes, use: bytes) -> None:
    base = b"import os\nimport subprocess\n" + binding
    new = base + use

    assert "uses spawn-bound" in _refused(_modify(CORE, base, new), CORE)


def test_rebinding_and_targets_that_bind_nothing_keep_the_scan_sound() -> None:
    """
    GIVEN a name bound twice from spawn sources, a bare annotation, a ``with``
        without ``as`` and a subscript of a call as a target
    WHEN an edit adds a call through the rebound name, or an unrelated statement
    THEN the call is refused and the unrelated statement passes
    """
    base = (
        b"import subprocess\nrun = subprocess\nrun = subprocess.run\ny: int\n"
        b"with open('f'):\n    pass\nf()[0] = subprocess\n"
    )

    assert "uses spawn-bound run" in _refused(
        _modify(CORE, base, base + b"run(['x'])\n"), CORE
    )
    assert _modify(CORE, base, base + b"z = f()\ny = 1\n") == ()


CLASS_BOUND = (
    b"class Runner:\n    _mod = __import__('subprocess')\n\n"
    b"    def go(self):\n        return 1\n\n    def other(self):\n        return 2\n"
)


@pytest.mark.parametrize(
    "new",
    [
        CLASS_BOUND.replace(
            b"        return 1\n", b"        self._mod.run(['x'])\n        return 1\n"
        ),  # fmt: skip
        CLASS_BOUND + b"\nRunner._mod.run(['x'])\n",
    ],
    ids=["through-self", "through-the-class"],
)
def test_a_class_attribute_bound_by_a_spawn_is_spawn_bound(new: bytes) -> None:
    """
    GIVEN a class body that binds ``_mod`` from ``__import__``
    WHEN an edit reads it as an attribute, through ``self`` or the class
    THEN it is refused like a bound ``self._mod``; an unrelated edit passes
    """
    assert "uses spawn-bound ._mod" in _refused(_modify(CORE, CLASS_BOUND, new), CORE)
    unrelated = CLASS_BOUND.replace(b"        return 2\n", b"        return 3\n")
    assert _modify(CORE, CLASS_BOUND, unrelated) == ()


def test_a_local_spawn_binding_does_not_taint_other_functions() -> None:
    """
    GIVEN ``result`` bound from a subprocess call inside ``f`` only
    WHEN an edit of ``g`` uses a local of the same name
    THEN it passes, and a new use of ``result`` inside ``f`` is refused
    """
    base = (
        b"import subprocess\n\n\ndef f():\n"
        b"    result = subprocess.run(['x'])\n    return result\n\n\n"
        b"def g():\n    return 1\n"
    )
    other = base.replace(b"    return 1\n", b"    result = 2\n    return result\n")
    same = base.replace(
        b"    return result\n", b"    print(result)\n    return result\n"
    )

    assert _modify(CORE, base, other) == ()
    assert "uses spawn-bound result" in _refused(_modify(CORE, base, same), CORE)


def test_a_star_import_of_a_spawn_module_scans_the_whole_file() -> None:
    """Names a star import binds are unknown, so nothing in the base is kept."""
    base = b"from subprocess import *\n\n\ndef hot():\n    return 1\n"
    new = base + b"\nPopen(['x'])\n"

    message = _refused(_modify(CORE, base, new), CORE)

    assert "line 1: imports subprocess.*" in message


# Which base is read ----------------------------------------------------------


def test_an_added_file_is_scanned_whole_and_its_base_is_never_read() -> None:
    reads: list[str] = []

    def base_of(path: str) -> bytes | None:
        reads.append(path)
        return b"import subprocess\n"

    change = Change("A", "000000", MODE, CORE)
    found = check_capture(
        (change,), {CORE: 1}, {CORE: b"import subprocess\n"}, RSS, base_of=base_of
    )

    assert "imports subprocess" in _refused(found, CORE)
    assert reads == []


@pytest.mark.parametrize(
    "base",
    [None, b"x = (\n", b"import os\nos.fork()\n"],
    ids=["none", "unparsable", "other"],
)
def test_a_missing_or_unparsable_base_fails_closed_to_the_whole_file(
    base: bytes | None,
) -> None:
    new = b"import subprocess\n"

    assert "imports subprocess" in _refused(_modify(CORE, base, new), CORE)


def test_without_base_of_every_finding_counts_as_before() -> None:
    change = Change("M", MODE, MODE, MORE)

    found = check_capture((change,), {MORE: 1}, {MORE: MORE_PY + b"#\n"}, RSS)

    assert "uses __import__" in _refused(found, MORE)


def test_base_of_is_read_only_while_cpu_or_rss_is_judged() -> None:
    reads: list[str] = []

    def base_of(path: str) -> bytes | None:
        reads.append(path)
        return MORE_PY

    wall = frozenset({METRIC_WALL_TIME_S})
    assert _modify(MORE, None, MORE_PY + b"#\n", judged=wall, base_of=base_of) == ()
    assert reads == []
    cpu = frozenset({METRIC_CPU_TIME_S})
    assert _modify(MORE, None, MORE_PY + b"#\n", judged=cpu, base_of=base_of) == ()
    assert reads == [MORE]


def test_spawn_problem_without_a_base_lists_every_finding() -> None:
    whole = str(_spawn_problem(PLUGINS_PY))
    assert whole.startswith(
        "may start processes (line 1: imports importlib.import_module; "
    )
    assert whole.count("; ") == 2  # at most three findings are listed
    assert _spawn_problem(PLUGINS_PY + b"#\n", PLUGINS_PY) is None
    assert _spawn_problem(b"x = 1\n") is None
    assert "cannot parse it" in str(_spawn_problem(b"def broken(:\n"))


# unparsable_source -----------------------------------------------------------

ENGINE = f"Python {sys.version_info.major}.{sys.version_info.minor}"


def test_a_syntax_error_is_unparsable_source_with_file_line_and_message() -> None:
    base = b"def skip(src, pos):\n    return pos\n"
    new = b"def skip(src, pos)\n    return pos\n"

    message = _unparsable(_modify(CORE, base, new), CORE)

    assert f"{ENGINE} cannot parse it (line 1: " in message
    assert "expected ':'" in message or "invalid syntax" in message
    assert "nothing in it was scanned or run" in message


def test_a_late_nul_byte_names_its_line() -> None:
    new = b"x = 1\n" + b"#" * 9000 + b"\n\x00\n"

    message = _unparsable(_modify(CORE, b"x = 1\n", new), CORE)

    assert "(line 3: source code string cannot contain null bytes)" in message


@pytest.mark.parametrize(
    "new",
    [b"x = " + b"-" * 200_000 + b"1\n", b"x = " + b"+".join([b"1"] * 100_000) + b"\n"],
    ids=["unary", "binary"],
)
def test_a_deep_expression_is_unparsable_source(new: bytes) -> None:
    message = _unparsable(_modify(CORE, b"x = 1\n", new), CORE)

    assert "too deeply nested or too large to parse" in message


def test_a_file_too_large_to_parse_is_unparsable_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``MemoryError`` from the parser stands for a file too large to parse."""

    real = ast.parse

    def parse(
        source: str | bytes, filename: str = "<unknown>", mode: str = "exec"
    ) -> ast.AST:
        if source == b"x = 2\n":
            raise MemoryError
        return real(source, filename, mode)

    monkeypatch.setattr(ast, "parse", parse)

    message = _unparsable(_modify(CORE, b"x = 1\n", b"x = 2\n"), CORE)

    assert "too deeply nested or too large to parse" in message


def test_the_parser_message_is_escaped_and_capped() -> None:
    message = _unparsable(_modify(CORE, b"x = 1\n", "x = 1 €\n".encode()), CORE)

    assert "\\u20ac" in message and "€" not in message
    assert len(message) < 400
    assert message.isascii()


def test_unparsable_source_applies_only_while_cpu_or_rss_is_judged() -> None:
    wall = frozenset({METRIC_WALL_TIME_S})

    assert _modify(CORE, b"x = 1\n", b"x = (\n", judged=wall) == ()


def test_unparsable_source_is_reported_beside_other_rules_once() -> None:
    change = Change("M", MODE, MODE, CORE)

    found = check_capture(
        (change,), {}, {CORE: b"x = (\n"}, RSS, base_of=lambda _: None
    )

    assert [v.rule for v in found] == [
        ViolationRule.unrecorded_write,
        ViolationRule.unparsable_source,
    ]


# The editor is told the rule -----------------------------------------------


def test_the_editor_prompt_names_the_refused_families() -> None:
    for family in (
        "multiprocessing",
        "subprocess",
        "concurrent.futures.process",
        "os.fork",
        "os.system",
        "pty",
        "joblib",
        "loky",
        "importlib.import_module",
        "__import__",
    ):
        assert family in SYSTEM_PROMPT, family
    assert "refused" in SYSTEM_PROMPT
    assert "refers to a function or class already using them" in SYSTEM_PROMPT
    assert "the signature, guard or block around such code" in SYSTEM_PROMPT


def test_every_e0a_case_parses_as_python() -> None:
    """The excerpts stay valid Python on the engine (a guard on the fixtures)."""
    ast.parse(MORE_PY)
    ast.parse(PLUGINS_PY)
