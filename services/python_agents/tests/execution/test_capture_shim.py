"""The capture shim (emergence round 2, S4): the benchmark's package calls,
replayed with their repetition and each distinct input once.

Every test runs ``_capture_shim.main`` in process on a tiny package written
under ``tmp_path`` from ``tests/fixtures/capture_words`` (``wordpkg``:
``render`` lexes a text into characters and upper-cases each one; a memo
variant caches ``render`` by text across calls, a bounded one holds one
text, a real variant does less work on every input).
The bench renders three texts 20 times, each twice running. ``sys.path``, ``sys.argv`` and
``sys.modules`` are restored by the shim and by the fixtures; the real
interpreter launch is ``test_capture_measure.py``'s.
"""

from __future__ import annotations

import json
import os
import py_compile
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from autonomous_ai_agents.execution import _capture_shim
from autonomous_ai_agents.execution.measure import parse_capture

WORDS = Path(__file__).resolve().parents[1] / "fixtures" / "capture_words"
BASE, MEMO, BOUNDED, REAL, LRU, BENCH = (
    (WORDS / f"{name}.py").read_text()
    for name in ("base", "memo", "bounded", "real", "lru", "bench")
)


def repo(root: Path, core: str, bench: str = BENCH) -> Path:
    (root / "wordpkg").mkdir(parents=True)
    (root / "wordpkg" / "__init__.py").write_text("")
    (root / "wordpkg" / "core.py").write_text(core)
    (root / "bench.py").write_text(bench)
    return root


@pytest.fixture(autouse=True)
def clean(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(sys, "argv", ["pytest"])
    monkeypatch.setattr(sys, "path", list(sys.path))
    before = list(sys.meta_path)
    yield
    for name in [n for n in sys.modules if n.split(".")[0] in ("wordpkg", "capprobe")]:
        del sys.modules[name]
    assert sys.meta_path == before


def capture(root: Path, *rest: str) -> dict[str, object]:
    out = root.parent / f"{root.name}.json"
    _capture_shim.main(["shim", str(out), str(root), "script", str(root / "bench.py"), *rest],
                       safe_path=False)  # fmt: skip
    doc: dict[str, object] = json.loads(out.read_bytes())
    return doc


def points(doc: dict[str, object]) -> dict[str, dict[str, object]]:
    found = doc["points"]
    assert isinstance(found, list)
    return {str(p["point"]): p for p in found}


def test_the_benchmarks_direct_plain_calls_are_captured_and_replayed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """
    GIVEN the bench calling ``render`` 120 times (each text twice running) on 3 texts, ``lex`` once and
        ``shout`` once, where ``render`` itself calls ``lex`` and ``shout``
    WHEN the shim runs it
    THEN the bench ran as itself (its print is there), each of the three is a
        point with its direct calls only (the depth counter keeps ``render``'s
        own ``lex`` and ``shout`` calls out), ``render`` has 3 distinct inputs,
        the document parses strictly, and nothing raised
    """
    doc = capture(repo(tmp_path / "base", BASE))

    assert capsys.readouterr().out == "X\n"
    found = points(doc)
    assert list(found) == [
        "wordpkg.core.render",
        "wordpkg.core.lex",
        "wordpkg.core.shout",
    ]
    render = found["wordpkg.core.render"]
    assert (render["calls"], render["distinct"], render["raised"]) == (120, 3, 0)
    assert (
        found["wordpkg.core.lex"]["calls"],
        found["wordpkg.core.lex"]["distinct"],
    ) == (1, 1)
    captured = parse_capture(json.dumps(doc).encode())
    assert captured.skipped == 0 and len(captured.corpus) == 64
    assert captured.sequence > sum(p.counted for p in captured.points) > 0


def test_counts_are_deterministic_and_the_corpus_hash_follows_the_inputs(
    tmp_path: Path,
) -> None:
    first = capture(repo(tmp_path / "a", BASE))
    again = capture(repo(tmp_path / "b", BASE))
    other = capture(repo(tmp_path / "c", BASE, BENCH.replace('"gamma"', '"delta"')))

    assert first == again
    assert other["corpus"] != first["corpus"]


def test_a_memo_cuts_the_repeated_sequence_and_not_the_distinct_once_legs(
    tmp_path: Path,
) -> None:
    """
    GIVEN the base, a whole-input memo, the memo bounded to one entry, and a
        real cut on every input
    WHEN each is captured
    THEN both memos cut the sequence leg (the bench repeats its texts) while
        the distinct-once ``render`` leg is not cut (a fresh import before
        each leg, so the memo the benchmark filled is gone); the real cut
        cuts both by the same share
    """
    seq = {name: capture(repo(tmp_path / name, core))
           for name, core in (("base", BASE), ("memo", MEMO), ("bounded", BOUNDED), ("real", REAL))}  # fmt: skip
    distinct = {name: points(doc)["wordpkg.core.render"]["counted"] for name, doc in seq.items()}  # fmt: skip
    sequence = {name: doc["sequence"] for name, doc in seq.items()}

    for memo in ("memo", "bounded"):
        assert sequence[memo] < 0.75 * sequence["base"]  # type: ignore[operator]
        assert distinct[memo] >= distinct["base"]  # type: ignore[operator]
    cut_seq = 1 - sequence["real"] / sequence["base"]  # type: ignore[operator]
    cut_distinct = 1 - distinct["real"] / distinct["base"]  # type: ignore[operator]
    assert cut_seq > 0.3 and cut_distinct == pytest.approx(cut_seq, abs=0.02)


def test_a_memo_decorated_on_the_point_keeps_the_point_and_its_cache_methods(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """
    GIVEN ``functools.lru_cache`` on ``render`` itself (VER-1's cross-call
        whole-input memo in its most direct form; review R4) and a bench that
        also reads and clears the cache, from its own file and from the package
    WHEN the shim runs it
    THEN ``render`` is still a point with its 120 calls on 3 inputs (wrapped
        under its own name, the lru wrapper called inside), the cache methods
        work through the wrapper, the sequence leg is cut and the
        distinct-once leg is not (a fresh, empty cache each leg)
    """
    reset = "import wordpkg.core as c\nc.reset()\n"
    base = capture(repo(tmp_path / "base", BASE + "\n\ndef reset():\n    pass\n", BENCH + reset))  # fmt: skip
    core = LRU + "\n\ndef reset():\n    render.cache_clear()\n"
    bench = BENCH + (
        "import wordpkg.core as c\n"
        "print(render.cache_info().hits, c.render.cache_parameters()['maxsize'])\n"
        + reset
        + "print(render.cache_info().currsize)\n"
    )
    capsys.readouterr()

    doc = capture(repo(tmp_path / "lru", core, bench))

    assert capsys.readouterr().out == "X\n117 None\n0\n"
    found = points(doc)
    assert list(found) == [
        f"wordpkg.core.{f}" for f in ("render", "lex", "shout", "reset")
    ]
    render = found["wordpkg.core.render"]
    assert (render["calls"], render["distinct"], render["raised"]) == (120, 3, 0)
    assert doc["corpus"] == base["corpus"]
    assert doc["sequence"] < 0.75 * base["sequence"]  # type: ignore[operator]
    assert render["counted"] >= points(base)["wordpkg.core.render"]["counted"]  # type: ignore[operator]


def test_a_class_or_a_wrapper_chain_that_cannot_be_followed_is_not_wrapped(
    tmp_path: Path,
) -> None:
    """A class whose ``__wrapped__`` ends in a module function stays a class
    (wrapping it would break ``isinstance``), and a callable whose
    ``__wrapped__`` loops or raises is left alone: neither is a point."""
    core = BASE + (
        "\n\nclass Box:\n    __wrapped__ = lex\n\n\n"
        "class _Odd:\n    def __init__(self, loop):\n        self.loop = loop\n\n"
        "    def __call__(self, x):\n        return x\n\n"
        "    @property\n    def __wrapped__(self):\n"
        "        if self.loop:\n            return self\n"
        "        raise RuntimeError('no chain')\n\n\n"
        "loop, broken = _Odd(True), _Odd(False)\n"
    )
    bench = ("import wordpkg.core as c\nassert isinstance(c.Box(), c.Box)\n"
             "c.loop(1)\nc.broken(1)\nc.lex('q')\n")  # fmt: skip

    doc = capture(repo(tmp_path / "base", core, bench))

    assert list(points(doc)) == ["wordpkg.core.lex"]


def test_a_point_with_an_argument_that_is_not_plain_is_skipped(tmp_path: Path) -> None:
    """A ``render`` call with a complex number drops the point and every call
    it recorded before (the sequence then holds the other points only)."""
    bench = BENCH.replace(
        'lex("direct")',
        'lex("direct")\ntry:\n    render(3j)\nexcept TypeError:\n    pass',
    )

    doc = capture(repo(tmp_path / "base", BASE, bench))

    assert doc["skipped"] == 1
    assert list(points(doc)) == ["wordpkg.core.lex", "wordpkg.core.shout"]
    alone = capture(repo(tmp_path / "alone", BASE, 'import wordpkg.core as c\nc.lex("direct")\nc.shout("x")\n'))  # fmt: skip
    assert doc["sequence"] == alone["sequence"]


@pytest.mark.parametrize("bad", [{1: "int key"}, {1, 2}, object(), True.__class__])
def test_every_plain_type_round_trips_and_others_are_refused(bad: object) -> None:
    value = [None, True, 3, 2.5, "s", b"\x00\xff", (1, [2]), {"k": (b"v",)}]
    assert _capture_shim.unplain(_capture_shim.plain(value)) == value
    with pytest.raises(_capture_shim.UnplainError):
        _capture_shim.plain(bad)
    with pytest.raises(_capture_shim.UnplainError):
        _capture_shim.plain(_nest(_capture_shim.MAX_DEPTH + 1))


def _nest(depth: int) -> list[object]:
    value: list[object] = []
    for _ in range(depth):
        value = [value]
    return value


def test_a_replayed_call_that_raises_is_counted_and_a_generator_is_drained(
    tmp_path: Path,
) -> None:
    core = (
        BASE
        + """

def fail(text):
    raise ValueError(text)


def chars(text):
    for ch in text:
        yield shout(ch)
"""
    )
    bench = (
        BENCH
        + """
for text in ("a", "b", "a"):
    try:
        wordpkg.core.fail(text)
    except ValueError:
        pass
list(wordpkg.core.chars("abc"))
"""
    )
    found = points(capture(repo(tmp_path / "base", core, bench)))

    assert (
        found["wordpkg.core.fail"]["calls"],
        found["wordpkg.core.fail"]["raised"],
    ) == (3, 2)
    one = capture(repo(tmp_path / "one", core, bench.replace('"abc"', '"a"')))
    many = found["wordpkg.core.chars"]["counted"]
    few = points(one)["wordpkg.core.chars"]["counted"]
    assert isinstance(many, int) and isinstance(few, int) and many > few


def test_past_the_point_cap_the_extra_points_are_skipped(tmp_path: Path) -> None:
    core = BASE + "".join(f"\n\ndef f{i}(x):\n    return x\n" for i in range(10))
    bench = "import wordpkg.core as c\n" + "".join(f"c.f{i}({i})\n" for i in range(10))

    doc = capture(repo(tmp_path / "base", core, bench))

    assert list(points(doc)) == [
        f"wordpkg.core.f{i}" for i in range(_capture_shim.MAX_POINTS)
    ]
    assert doc["skipped"] == 10 - _capture_shim.MAX_POINTS


def test_a_corpus_past_its_cap_records_no_point(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_capture_shim, "MAX_CORPUS_BYTES", 100)

    doc = capture(
        repo(tmp_path / "base", BASE, BENCH.replace('"beta"', '"' + "b" * 200 + '"'))
    )

    assert (doc["points"], doc["sequence"], doc["skipped"]) == ([], 0, 1)


def test_a_failing_target_writes_nothing_and_its_exit_passes_through(
    tmp_path: Path,
) -> None:
    root = repo(tmp_path / "base", BASE, BENCH + "raise SystemExit(4)\n")

    with pytest.raises(SystemExit) as stopped:
        capture(root)

    assert stopped.value.code == 4
    assert not (tmp_path / "base.json").exists()


def test_a_target_that_exits_zero_is_still_replayed(tmp_path: Path) -> None:
    doc = capture(repo(tmp_path / "base", BASE, BENCH + "raise SystemExit(0)\n"))

    assert "wordpkg.core.render" in points(doc)


def test_a_module_target_is_its_own_direct_caller(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = repo(tmp_path / "base", BASE)
    (root / "wordpkg" / "main.py").write_text(BENCH)
    monkeypatch.chdir(root)
    out = tmp_path / "out.json"

    _capture_shim.main(["shim", str(out), str(root), "module", "wordpkg.main"], safe_path=False)  # fmt: skip

    assert sys.path[0] == os.path.realpath(root)
    assert "wordpkg.core.render" in points(json.loads(out.read_bytes()))


def test_a_directory_target_runs_its_main_file(tmp_path: Path) -> None:
    root = repo(tmp_path / "base", BASE)
    (root / "app").mkdir()
    (root / "app" / "__main__.py").write_text(f"import sys\nsys.path.insert(0, {str(root)!r})\n" + BENCH)  # fmt: skip
    out = tmp_path / "out.json"

    _capture_shim.main(["shim", str(out), str(root), "script", str(root / "app")], safe_path=True)  # fmt: skip

    assert "wordpkg.core.render" in points(json.loads(out.read_bytes()))


def test_modules_outside_the_root_and_private_or_foreign_names_are_left_alone(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    (outside / "capprobe").mkdir(parents=True)
    (outside / "capprobe" / "__init__.py").write_text("def hello(x):\n    return x\n")
    core = "from os.path import join\n\n\ndef _hidden(x):\n    return x\n" + BASE
    bench = f"import sys\nsys.path.insert(0, {str(outside)!r})\nimport capprobe\n" + (
        "import wordpkg.core as c\ncapprobe.hello(1)\nc._hidden(1)\nc.join('a', 'b')\nc.lex('q')\n"
    )

    doc = capture(repo(tmp_path / "base", core, bench))

    assert list(points(doc)) == ["wordpkg.core.lex"]


def test_the_usage_and_the_interpreter_floor() -> None:
    with pytest.raises(SystemExit) as stopped:
        _capture_shim.main(["shim", "out", "root", "binary", "x"])
    assert stopped.value.code == _capture_shim.USAGE
    assert _capture_shim.interpreter_problem((3, 8)) is None
    assert "3.8 or later" in str(_capture_shim.interpreter_problem((3, 7)))


def test_a_sourceless_module_and_long_or_non_ascii_names_are_not_wrapped(
    tmp_path: Path,
) -> None:
    """Only a source module is wrapped (``SourceFileLoader``), and only a
    point the engine's parser accepts: an ASCII name of at most
    ``MAX_NAME_CHARS``."""
    root = tmp_path / "base"
    long = "f" * _capture_shim.MAX_NAME_CHARS
    core = BASE + f"\n\ndef café(x):\n    return x\n\n\ndef {long}(x):\n    return x\n"
    repo(root, core, "import wordpkg.core as c\nimport capprobe\n"
         f"c.café(1)\nc.{long}(1)\ncapprobe.hello(1)\nc.lex('q')\n")  # fmt: skip
    source = root / "capprobe.py"
    source.write_text("def hello(x):\n    return x\n")
    py_compile.compile(str(source), cfile=str(root / "capprobe.pyc"))
    source.unlink()

    doc = capture(root)

    assert list(points(doc)) == ["wordpkg.core.lex"]


def test_a_module_target_under_safe_path_adds_nothing_to_sys_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = repo(tmp_path / "base", BASE)
    (root / "wordpkg" / "main.py").write_text(BENCH)
    sys.path.insert(0, str(root))
    before = list(sys.path)
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "out.json"

    _capture_shim.main(["shim", str(out), str(root), "module", "wordpkg.main"], safe_path=True)  # fmt: skip

    assert sys.path == before
    assert "wordpkg.core.render" in points(json.loads(out.read_bytes()))


def test_the_safe_path_default_is_the_interpreters(tmp_path: Path) -> None:
    root = repo(tmp_path / "base", BASE)
    out = tmp_path / "out.json"

    _capture_shim.main(["shim", str(out), str(root), "script", str(root / "bench.py")])

    assert _capture_shim.path_is_safe() is bool(getattr(sys.flags, "safe_path", 0))
    assert sys.path[0] == os.path.realpath(root)
    assert "wordpkg.core.render" in points(json.loads(out.read_bytes()))
