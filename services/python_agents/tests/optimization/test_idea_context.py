"""The idea pipeline's code context, S0 (Wave 2, N1b; spec amendment D44, D50,
D51, D59, D62 and section 5).

``read_code_context`` reads the hot functions at the base commit through the
shared reader rules and decides what repository text may become model input:
no secret-like, protected, binary, non-UTF-8 or token-holding file; no
bidi-control or secret-shaped line; every invisible character escaped in both
the rendering and the grounding text; parse failures fall back to the head.
``anchor_of`` and ``amdahl_ceiling`` derive the engine's facts from a match,
``render_data_block`` builds the cached prefix. Every reader here is a dict
fake that records each read; nothing runs git or a model.
"""

from __future__ import annotations

import ast
import sys
from collections.abc import Mapping

import pytest

from autonomous_ai_agents.clients.structured import Fence
from autonomous_ai_agents.common.config import Settings
from autonomous_ai_agents.common.models import (
    CandidateModule,
    Direction,
    Hotspot,
    Objective,
    ObjectiveKind,
    Project,
    ProjectUnderstanding,
)
from autonomous_ai_agents.execution.git import GitError
from autonomous_ai_agents.optimization import idea_context
from autonomous_ai_agents.optimization.idea_context import (
    IdeaReadLimits,
    amdahl_ceiling,
    anchor_of,
    read_code_context,
    render_data_block,
)
from autonomous_ai_agents.optimization.idea_types import (
    Anchor,
    CodeContext,
    CodeDocument,
    FunctionSpan,
)

SHA = "0123456789abcdef0123456789abcdef01234567"
PROJECT = Project(id="p1", name="demo", root_path="/srv/demo")

CORE = '''"""Core."""
import re
from functools import lru_cache

WORDS = re.compile(r"\\w+")


def helper(x):
    return x + 1


class Index:
    def __init__(self, items):
        self.items = list(items)

    @staticmethod
    @lru_cache(maxsize=None)
    def key(item):
        return item.lower()

    def find(self, word):
        def match(item):
            return Index.key(item) == word

        return [i for i in self.items if match(i)]


def run(words):
    index = Index(words)
    return [index.find(w) for w in words]


def unrelated():
    return 0
'''


class _Reader:
    """A ``RepoReader`` over a dict; records every ``read_blob`` path."""

    def __init__(
        self, blobs: Mapping[str, bytes | str], *, fail: frozenset[str] = frozenset()
    ) -> None:
        self.blobs = {
            p: b if isinstance(b, bytes) else b.encode() for p, b in blobs.items()
        }
        self.fail = fail
        self.reads: list[str] = []

    def ls_tree(self, commit: str) -> tuple[str, ...]:
        assert commit == SHA
        return tuple(sorted(self.blobs))

    def read_blob(self, commit: str, path: str, *, limit: int | None = None) -> bytes:
        assert commit == SHA
        self.reads.append(path)
        if path in self.fail:
            raise GitError(f"cannot read {path}")
        data = self.blobs[path]
        return data if limit is None else data[:limit]


def _line(source: str, needle: str) -> int:
    """The 1-based line of the first line of ``source`` holding ``needle``."""
    return next(i for i, t in enumerate(source.split("\n"), 1) if needle in t)


def _spot(
    path: str,
    symbol: str,
    line: int | None,
    *,
    total: float = 1.0,
    self_s: float = 0.1,
    share: float = 0.05,
    workload: str = "w1",
    spot_id: str | None = None,
) -> Hotspot:
    return Hotspot(
        id=spot_id or f"{workload}:{path}:{symbol}",
        project_id=PROJECT.id,
        workload_id=workload,
        file_path=path,
        symbol=symbol,
        line_start=line,
        self_time_s=self_s,
        total_time_s=total,
        share=share,
    )


def _read(
    blobs: Mapping[str, bytes | str],
    spots: list[Hotspot],
    *,
    fence: Fence | None = None,
    protected: tuple[str, ...] = (),
    read_deny: tuple[str, ...] = (),
    fail: frozenset[str] = frozenset(),
    **limits: int,
) -> tuple[CodeContext, list[str], _Reader]:
    reader = _Reader(blobs, fail=fail)
    notes: list[str] = []
    context = read_code_context(
        reader,
        SHA,
        spots,
        fence=fence or Fence.new(),
        protected=protected,
        read_deny=read_deny,
        limits=IdeaReadLimits(**limits),
        notes=notes,
    )
    return context, notes, reader


def _doc(context: CodeContext, path: str) -> CodeDocument:
    return next(d for d in context.documents if d.path == path)


def _qualnames(document: CodeDocument) -> dict[str, FunctionSpan]:
    return {span.qualname: span for span in document.spans}


def _noted(notes: list[str], *parts: str) -> bool:
    return any(all(part in note for part in parts) for note in notes)


# --------------------------------------------------------------------------
# Selection, spans, whole files, headers, callers
# --------------------------------------------------------------------------


def test_limits_come_from_the_settings() -> None:
    cfg = Settings(IDEAS_HOT_FUNCTIONS=3, IDEAS_MAX_FILES=2)
    assert IdeaReadLimits.from_settings(cfg) == IdeaReadLimits(
        hot_functions=3,
        max_files=2,
        file_max_bytes=24 * 1024,
        code_max_bytes=64 * 1024,
        parse_max_bytes=512 * 1024,
    )
    assert IdeaReadLimits().header_max_lines == 60


def test_hot_functions_are_chosen_by_cumulative_time_and_deduplicated() -> None:
    """
    GIVEN three files whose functions rank differently by self and cumulative
    time, one of them profiled in two workloads
    WHEN two hot functions are allowed
    THEN the two largest cumulative times are shown, hottest first, and the
    function profiled twice is one span holding both hotspot ids
    """
    blobs = {f"{n}.py": f"def f{n}():\n    return {i}\n" for i, n in enumerate("abc")}
    spots = [
        _spot("a.py", "fa", 1, total=1.0, self_s=0.9, share=0.9),
        _spot("b.py", "fb", 1, total=3.0, self_s=0.05),
        _spot("b.py", "fb", 1, total=2.5, workload="w2"),
        _spot("c.py", "fc", 1, total=2.0, self_s=0.5),
    ]
    context, _, reader = _read(blobs, spots, hot_functions=2)
    assert [d.path for d in context.documents] == ["b.py", "c.py"]
    assert "a.py" not in reader.reads
    span = _doc(context, "b.py").spans[0]
    assert span.qualname == "fb"
    assert set(span.hotspot_ids) == {"w1:b.py:fb", "w2:b.py:fb"}


def test_a_small_file_is_shown_whole_with_line_numbers() -> None:
    context, notes, _ = _read({"pkg/core.py": CORE}, [_spot("pkg/core.py", "run", 28)])
    document = _doc(context, "pkg/core.py")
    lines = CORE.rstrip("\n").split("\n")
    assert (document.start_line, document.end_line) == (1, len(lines))
    assert document.rendered == "\n".join(f"L{i}: {t}" for i, t in enumerate(lines, 1))
    assert document.raw == "\n".join(lines)
    assert _noted(notes, "code context: 1 file(s) shown", "pkg/core.py")


def test_spans_come_from_the_enclosing_def_at_the_profiled_line() -> None:
    """
    GIVEN a file over the whole-file size, hotspots on a nested function, on
    a decorated method (cProfile's line is the first decorator's) and one
    with no line whose symbol's last component names a method
    WHEN the context is read
    THEN each span is the enclosing ``def`` (innermost), decorators included,
    named by its qualified name
    """
    match_line = _line(CORE, "def match")
    key_line = _line(CORE, "@staticmethod")
    spots = [
        _spot("pkg/core.py", "match", match_line, total=3.0),
        _spot("pkg/core.py", "key", key_line, total=2.0),
        _spot("pkg/core.py", "Index.__init__", None, total=1.0),
    ]
    context, _, _ = _read({"pkg/core.py": CORE}, spots, file_max_bytes=200)
    spans = _qualnames(_doc(context, "pkg/core.py"))
    assert set(spans) == {"Index.find.match", "Index.key", "Index.__init__"}
    assert (
        spans["Index.find.match"].start_line,
        spans["Index.find.match"].end_line,
    ) == (
        match_line,
        match_line + 1,
    )
    assert spans["Index.key"].start_line == key_line
    assert spans["Index.key"].end_line == _line(CORE, "return item.lower()")
    assert spans["Index.__init__"].hotspot_ids == ("w1:pkg/core.py:Index.__init__",)
    rendered = _doc(context, "pkg/core.py").rendered
    assert f"L{_line(CORE, 'def find')}:" not in rendered  # only the nested def
    assert "not shown)" in rendered  # gaps are marked


def test_a_hot_span_holds_its_nested_functions_as_spans_without_hotspots() -> None:
    find_line = _line(CORE, "def find")
    spots = [_spot("pkg/core.py", "find", find_line)]
    context, _, _ = _read({"pkg/core.py": CORE}, spots, file_max_bytes=200)
    spans = _qualnames(_doc(context, "pkg/core.py"))
    assert set(spans) == {"Index.find", "Index.find.match"}
    assert spans["Index.find.match"].hotspot_ids == ()
    assert spans["Index.find"].hotspot_ids == ("w1:pkg/core.py:find",)


def test_a_listed_hotspot_whose_function_is_not_shown_is_no_span() -> None:
    spots = [
        _spot("pkg/core.py", "helper", _line(CORE, "def helper"), total=2.0),
        _spot("pkg/core.py", "unrelated", _line(CORE, "def unrelated")),
        _spot("pkg/core.py", "<module>", 1),
    ]
    context, _, _ = _read(
        {"pkg/core.py": CORE}, spots, file_max_bytes=200, hot_functions=1
    )
    document = _doc(context, "pkg/core.py")
    assert set(_qualnames(document)) == {"helper"}
    assert "def unrelated" not in document.rendered


def test_the_module_header_is_capped_at_sixty_lines() -> None:
    header = "".join(f"X{i} = {i}\n" for i in range(1, 71))
    source = header + "def hot():\n" + "    x = 1\n" * 80 + "    return x\n"
    spot = _spot("m.py", "hot", 71)
    context, _, _ = _read({"m.py": source}, [spot], file_max_bytes=1024)
    rendered = _doc(context, "m.py").rendered
    assert "L1: X1 = 1" in rendered and "L60: X60 = 60" in rendered
    assert "L61:" not in rendered and "L71: def hot():" in rendered
    assert "(lines 61-70 not shown)" in rendered
    shorter = IdeaReadLimits(header_max_lines=5)
    context = read_code_context(
        _Reader({"m.py": source}), SHA, [spot], fence=Fence.new(), protected=(),
        read_deny=(), limits=shorter.model_copy(update={"file_max_bytes": 1024}),
        notes=[],
    )  # fmt: skip
    assert "L6:" not in _doc(context, "m.py").rendered


def test_a_textual_caller_is_appended_within_the_cap_and_dropped_past_it() -> None:
    """
    GIVEN a hot function, a function that calls it by name and one that does not
    WHEN the code cap allows, and then when it is one byte short of the caller
    THEN the caller is shown (not as a span) and the other is not; past the
    cap the caller is dropped with a note
    """
    run_line = _line(CORE, "def run")
    spots = [_spot("pkg/core.py", "Index.find", _line(CORE, "def find"))]
    context, notes, _ = _read({"pkg/core.py": CORE}, spots, file_max_bytes=200)
    document = _doc(context, "pkg/core.py")
    assert f"L{run_line}: def run(words):" in document.rendered
    assert "def unrelated" not in document.rendered
    assert "run" not in _qualnames(document)
    assert _noted(notes, "1 textual caller(s) shown")
    cap = len(document.rendered.encode()) - 1
    context, notes, _ = _read(
        {"pkg/core.py": CORE}, spots, file_max_bytes=200, code_max_bytes=cap
    )
    assert "def run" not in _doc(context, "pkg/core.py").rendered
    assert _noted(notes, "1 textual caller(s) not shown", f"code limit {cap}")


def test_at_most_max_files_files_are_shown() -> None:
    blobs = {f"{n}.py": f"def f{n}():\n    return 1\n" for n in "abc"}
    spots = [_spot(f"{n}.py", f"f{n}", 1, total=3.0 - i) for i, n in enumerate("abc")]
    context, notes, reader = _read(blobs, spots, max_files=2)
    assert [d.path for d in context.documents] == ["a.py", "b.py"]
    assert "c.py" not in reader.reads
    assert _noted(notes, "1 file(s) not shown (file limit 2)", "c.py")


def test_a_hotspot_without_a_function_and_a_hot_span_past_the_cap() -> None:
    source = "X = [1, 2, 3]\nY = sum(X)\n"
    context, notes, _ = _read(
        {"script.py": source}, [_spot("script.py", "<module>", 1)]
    )
    assert context.documents == ()
    assert _noted(notes, "script.py", "no function found for hotspot '<module>'")
    assert _noted(notes, "script.py: not shown (no hot function could be shown)")
    spot = _spot("pkg/core.py", "find", _line(CORE, "def find"))
    context, notes, _ = _read(
        {"pkg/core.py": CORE}, [spot], file_max_bytes=200, code_max_bytes=100
    )
    assert context.documents == ()
    assert _noted(notes, "pkg/core.py: hot function Index.find not shown", "100")


def test_a_hotspot_named_twice_without_a_line_is_not_guessed() -> None:
    source = "class A:\n    def f(self):\n        return 1\n\nclass B:\n    def f(self):\n        return 2\n"
    context, notes, _ = _read({"two.py": source}, [_spot("two.py", "f", None)])
    assert context.documents == ()
    assert _noted(notes, "no function found for hotspot 'f'")


def test_the_whole_file_falls_back_to_excerpts_when_it_does_not_fit() -> None:
    spot = _spot("pkg/core.py", "helper", _line(CORE, "def helper"))
    context, _, _ = _read({"pkg/core.py": CORE}, [spot], code_max_bytes=400)
    core = _doc(context, "pkg/core.py")
    assert core.start_line == 1 and "def unrelated" not in core.rendered
    assert "L8: def helper(x):" in core.rendered
    assert len(core.rendered.encode()) <= 400


# --------------------------------------------------------------------------
# Exclusions: never read, never shown
# --------------------------------------------------------------------------


def test_secret_protected_and_frozen_files_are_never_read_or_shown() -> None:
    """
    GIVEN hotspots in a .env, a .pem, a tests/ file, a lockfile, a benchmark
    the preflight protected and a frozen quality file
    WHEN the context is read with the run's protected set and read-deny list
    THEN none of them is ever asked of the reader; only the real module shows
    """
    bad = (".env", "certs/key.pem", "tests/test_core.py", "uv.lock",
           "bench/run.py", "data/score.py")  # fmt: skip
    blobs = {path: "def f():\n    return 1\n" for path in bad}
    blobs["pkg/core.py"] = CORE
    spots = [_spot(path, "f", 1, total=5.0) for path in bad]
    spots.append(_spot("pkg/core.py", "helper", _line(CORE, "def helper")))
    context, notes, reader = _read(
        blobs, spots, protected=("bench/run.py",), read_deny=("data/score.py",)
    )
    assert reader.reads == ["pkg/core.py"]
    assert [d.path for d in context.documents] == ["pkg/core.py"]
    assert _noted(notes, "2 secret-like file(s) never read")
    for path in bad[2:]:
        assert _noted(notes, path, "protected")
    assert not _noted(notes, ".env") and not _noted(notes, "key.pem")


def test_a_path_holding_a_token_or_an_unprintable_character_is_never_read() -> None:
    fence = Fence.new(others=("feedfacecafebeef",))
    paths = ("pkg/FEEDFACECAFEBEEF.py", f"pkg/{fence.token}.py", "pkg/a\u202eb.py")
    blobs = {path: "def f():\n    return 1\n" for path in paths}
    spots = [_spot(path, "f", 1) for path in paths]
    context, notes, reader = _read(blobs, spots, fence=fence)
    assert reader.reads == [] and context.documents == ()
    assert _noted(notes, "3 file(s) withheld: the path holds a boundary token")
    assert not any(fence.token in note for note in notes)


def test_untracked_and_unreadable_files_are_noted() -> None:
    spots = [_spot("gone.py", "f", 1, total=2.0), _spot("bad.py", "f", 1)]
    context, notes, _ = _read(
        {"bad.py": "def f():\n    return 1\n"}, spots, fail=frozenset({"bad.py"})
    )
    assert context.documents == ()
    assert _noted(notes, "gone.py: not tracked at the base commit")
    assert _noted(notes, "bad.py: unreadable in git")


def test_an_unreadable_file_list_shows_nothing() -> None:
    class _NoTree(_Reader):
        def ls_tree(self, commit: str) -> tuple[str, ...]:
            raise GitError("no tree")

    notes: list[str] = []
    context = read_code_context(
        _NoTree({"a.py": "def f():\n    return 1\n"}), SHA, [_spot("a.py", "f", 1)],
        fence=Fence.new(), protected=(), read_deny=(), limits=IdeaReadLimits(),
        notes=notes,
    )  # fmt: skip
    assert context.documents == ()
    assert notes == ["code context: the base commit's file list is unreadable in git"]
    assert context.notes == tuple(notes)


def test_binary_non_utf8_and_token_holding_files_are_withheld() -> None:
    fence = Fence.new(others=("0badc0de0badc0de",))
    blobs: dict[str, bytes | str] = {
        "bin.py": b"def f():\n    return 1\n\0",
        "latin.py": b"def f():\n    return '\xe9'\n",
        "tok.py": f"def f():\n    return '{fence.token}'\n",
        "other.py": "def f():\n    return '0BADC0DE0BADC0DE'\n",
    }
    spots = [_spot(path, "f", 1) for path in blobs]
    context, notes, _ = _read(blobs, spots, fence=fence)
    assert context.documents == ()
    assert _noted(notes, "bin.py: not shown (binary)")
    assert _noted(notes, "latin.py: not shown (not UTF-8)")
    assert _noted(notes, "tok.py: withheld (it holds a boundary token)")
    assert _noted(notes, "other.py: withheld (it holds a boundary token)")


# --------------------------------------------------------------------------
# Escaping and withholding lines
# --------------------------------------------------------------------------


def test_invisible_characters_are_escaped_in_both_texts() -> None:
    """
    GIVEN a comment of tag characters, a ZWJ inside a string, U+061C, U+180E,
    a word joiner and a stray C1 control
    WHEN the file is shown
    THEN each is a visible ``\\u{XXXX}`` escape in the rendering and in the
    grounding text, the raw character survives in neither, and tabs stay
    """
    source = (
        "def hot():\n"
        "    # hidden \U000e0041\U000e0042 tag\n"
        '    s = "a\u200db"\n'
        '    t = "x\u061cy\u180ez\u2060w\x85\u2028v"\n'
        "    return s +\tt\n"
    )
    context, notes, _ = _read({"inv.py": source}, [_spot("inv.py", "hot", 1)])
    document = _doc(context, "inv.py")
    for text in (document.rendered, document.raw):
        for escape in ("\\u{E0041}", "\\u{E0042}", "\\u{200D}", "\\u{061C}",
                       "\\u{180E}", "\\u{2060}", "\\u{0085}", "\\u{2028}"):  # fmt: skip
            assert escape in text
        for char in "\U000e0041\u200d\u061c\u180e\u2060\x85\u2028":
            assert char not in text
        assert "s +\tt" in text
    assert _noted(notes, "inv.py: invisible character(s) on line(s) 2-4")


def test_a_bidi_override_line_is_withheld_with_its_line_number() -> None:
    source = "def hot():\n    ok = 1\n    x = 1  # \u202e evil\n    return x\n"
    context, notes, _ = _read({"bidi.py": source}, [_spot("bidi.py", "hot", 1)])
    document = _doc(context, "bidi.py")
    assert "L3: (line withheld: a bidi control)" in document.rendered
    assert document.raw.split("\n")[2] == ""
    assert "evil" not in document.rendered + document.raw
    assert _noted(notes, "bidi.py: line(s) 3 withheld", "Trojan-Source")


def test_secret_shaped_lines_are_withheld_and_never_quoted_in_notes() -> None:
    source = (
        "def hot():\n"
        '    key = """-----BEGIN RSA PRIVATE KEY-----\n'
        "MIIEowIBAAKCAQEAsecretbody\n"
        '-----END RSA PRIVATE KEY-----"""\n'
        '    aws = "AKIAABCDEFGHIJKLMNOP"\n'
        '    tok = "ghp_abc" + "sk-ant-x" + "xoxb-1" + "github_pat_9"\n'
        "    return key\n"
    )
    context, notes, _ = _read({"keys.py": source}, [_spot("keys.py", "hot", 1)])
    document = _doc(context, "keys.py")
    for secret in ("MIIEowIBAAKCAQEAsecretbody", "AKIAABCDEFGHIJKLMNOP", "ghp_abc",
                   "sk-ant-x", "xoxb-1", "github_pat_9", "BEGIN RSA"):  # fmt: skip
        assert secret not in document.rendered + document.raw
        assert not any(secret in note for note in notes)
    assert "L2: (line withheld: secret-shaped)" in document.rendered
    assert "L3: (line withheld: secret-shaped)" in document.rendered
    assert "L7:     return key" in document.rendered
    assert _noted(notes, "keys.py: line(s) 2-6 withheld (secret-shaped)")


def test_an_unclosed_private_key_withholds_the_rest_of_the_file() -> None:
    source = "def hot():\n    k = '''-----BEGIN PRIVATE KEY-----\nAAAA\nBBBB\n"
    context, _, _ = _read({"k.py": source}, [_spot("k.py", "hot", 1)])
    document = _doc(context, "k.py")
    assert "AAAA" not in document.raw and "BBBB" not in document.raw


def test_an_empty_file_is_not_shown() -> None:
    context, notes, _ = _read({"empty.py": ""}, [_spot("empty.py", "f", 1)])
    assert context.documents == ()
    assert _noted(notes, "empty.py: not shown (empty)")


def test_line_endings_are_read_as_python_reads_them() -> None:
    crlf = "def hot():\r\n    return 1\r\n"
    context, _, _ = _read({"crlf.py": crlf}, [_spot("crlf.py", "hot", 1)])
    assert _doc(context, "crlf.py").rendered == "L1: def hot():\nL2:     return 1"
    lone = "X = 1\rdef hot():\n    return 1\n"
    context, notes, _ = _read({"cr.py": lone}, [_spot("cr.py", "hot", 2)])
    document = _doc(context, "cr.py")
    assert document.spans[0].start_line == 2
    assert "L2: def hot():" in document.rendered
    assert _noted(notes, "cr.py: lone carriage returns read as line breaks")


# --------------------------------------------------------------------------
# Parse failures fall back to the head
# --------------------------------------------------------------------------

_SPAWN = 'def hot():\n    return __import__("concurrent.futures")\n'


@pytest.mark.parametrize(
    ("source", "why"),
    [
        ("def hot(:\n    return 1\n", "SyntaxError"),
        ("def hot():\n    return 1\nx=(" + "1+" * 10000 + "1)\n", "RecursionError"),
        ("def hot():\n    return 1\nx=" + "-" * 200_000 + "1\n", "MemoryError"),
        ("def hot():\n    return 1\n" + "#" * 8100 + "\0\n", ""),
    ],
    ids=["syntax", "deep", "memory", "nul-past-the-sniff"],
)
def test_an_unparsable_file_is_shown_as_its_head(source: str, why: str) -> None:
    context, notes, _ = _read({"u.py": source}, [_spot("u.py", "hot", 1, total=2.0)])
    document = _doc(context, "u.py")
    assert document.start_line == 1
    assert len(document.raw.encode()) <= 24 * 1024
    assert document.rendered.startswith("L1: def hot(")
    assert "\nL2:     return 1" in document.rendered
    (span,) = document.spans
    assert (span.qualname, span.start_line, span.end_line) == (
        "hot",
        1,
        document.end_line,
    )
    assert span.hotspot_ids == ("w1:u.py:hot",)
    assert document.spawn_findings == ()
    assert _noted(notes, "u.py: shown as its first", "could not be parsed", why)


def test_a_value_error_from_the_parser_is_unparsable_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(*args: object, **kwargs: object) -> ast.Module:
        raise ValueError("source code string cannot contain null bytes")

    monkeypatch.setattr(idea_context, "_ast_parse", refuse)
    context, notes, _ = _read({"v.py": _SPAWN}, [_spot("v.py", "hot", 1)])
    assert _doc(context, "v.py").spans[0].qualname == "hot"
    assert _noted(notes, "v.py: shown as its first 2 line(s)", "ValueError")


def test_pep_695_syntax_parses_only_where_the_engine_can() -> None:
    source = "type Alias = int\n\n\ndef hot():\n    return 1\n"
    context, notes, _ = _read({"t.py": source}, [_spot("t.py", "hot", 4)])
    span = _doc(context, "t.py").spans[0]
    if sys.version_info >= (3, 12):
        assert (span.start_line, span.end_line) == (4, 5)
        assert not _noted(notes, "could not be parsed")
    else:  # the 3.11 CI engine
        assert (span.start_line, span.end_line) == (1, 5)
        assert _noted(notes, "t.py: shown as its first", "could not be parsed")


def test_a_file_past_the_parse_cap_is_shown_as_its_head() -> None:
    source = "def hot():\n    return 1\n" + "y = 2\n" * 400
    context, notes, reader = _read(
        {"long.py": source},
        [_spot("long.py", "hot", 1)],
        file_max_bytes=1024,
        parse_max_bytes=2000,
    )
    document = _doc(context, "long.py")
    assert len(document.raw.encode()) <= 1024
    assert document.raw.endswith("y = 2")  # whole lines only
    assert _noted(notes, "long.py: shown as its first", "longer than 2000 bytes")
    assert reader.reads == ["long.py"]


def test_a_head_cut_at_the_cap_leaves_no_split_character() -> None:
    cap = 1024
    source = "(" + "a" * (cap - 2) + "\u00e9" * 10  # one line; the é straddles the cap
    context, _, _ = _read(
        {"cut.py": source}, [_spot("cut.py", "hot", 1)], file_max_bytes=cap
    )
    document = _doc(context, "cut.py")
    assert document.raw == "(" + "a" * (cap - 2)
    assert "\ufffd" not in document.rendered


# --------------------------------------------------------------------------
# Caps on the rendered text, spawn findings, totals
# --------------------------------------------------------------------------


def test_the_code_cap_counts_the_rendered_prefixes() -> None:
    """
    GIVEN two small files whose raw text fits the cap but whose rendering
    (with the ``L123: `` prefixes) does not
    WHEN the context is read
    THEN the cooler file is dropped and the shown rendering fits the cap
    """
    blobs = {
        n: f"def f{i}():\n    return {i}\n" for i, n in enumerate(("a.py", "b.py"))
    }
    spots = [_spot("a.py", "f0", 1, total=2.0), _spot("b.py", "f1", 1)]
    raw = sum(len(b.encode()) for b in blobs.values())
    context, notes, _ = _read(blobs, spots, code_max_bytes=raw + 4)
    assert [d.path for d in context.documents] == ["a.py"]
    assert sum(len(d.rendered.encode()) for d in context.documents) <= raw + 4
    assert _noted(notes, "b.py: hot function f1 not shown", f"code limit {raw + 4}")


def test_spawn_findings_are_listed_per_shown_file() -> None:
    blobs = {"more.py": _SPAWN, "clean.py": "def ok():\n    return 1\n"}
    spots = [_spot("more.py", "hot", 1, total=2.0), _spot("clean.py", "ok", 1)]
    context, _, _ = _read(blobs, spots)
    assert _doc(context, "more.py").spawn_findings == ("line 2: uses __import__",)
    assert _doc(context, "clean.py").spawn_findings == ()


def test_at_most_five_spawn_findings_are_rendered_per_document() -> None:
    source = (
        "def hot():\n"
        + "".join(f"    x{i} = __import__('m{i}')\n" for i in range(7))
        + "    return 1\n"
    )
    spots = [_spot("many.py", "hot", 1)]
    fence = Fence.new()
    context, _, _ = _read({"many.py": source}, spots, fence=fence)
    assert len(_doc(context, "many.py").spawn_findings) == 7
    text, _ = _block(context, spots, fence)
    assert "line 6: uses __import__; 2 more; an edit may not touch" in text
    assert "line 7: uses" not in text


def test_totals_by_workload_are_recovered_from_self_time_over_share() -> None:
    spots = [
        _spot("a.py", "f", 1, self_s=0.0, share=0.0),
        _spot("a.py", "g", 3, self_s=0.5, share=0.25),
        _spot("a.py", "f", 1, self_s=0.0, share=0.0, workload="w2"),
    ]
    blobs = {"a.py": "def f():\n    return 1\ndef g():\n    return 2\n"}
    context, _, _ = _read(blobs, spots)
    assert context.totals_by_workload == {"w1": 2.0}


# --------------------------------------------------------------------------
# anchor_of and amdahl_ceiling
# --------------------------------------------------------------------------


def _core_context() -> CodeContext:
    spots = [
        _spot("pkg/core.py", "find", _line(CORE, "def find"), total=2.0),
        _spot("pkg/core.py", "helper", _line(CORE, "def helper"), total=1.0),
    ]
    context, _, _ = _read({"pkg/core.py": CORE}, spots, file_max_bytes=200)
    return context


def test_anchor_of_returns_the_innermost_hot_function_holding_the_quote() -> None:
    context = _core_context()
    find, match = _line(CORE, "def find"), _line(CORE, "return Index.key")
    path = "pkg/core.py"
    assert anchor_of(path, (match, match), context) == Anchor(
        path=path, qualname="Index.find.match"
    )
    last = _line(CORE, "return [i for i")
    assert anchor_of(path, (find, last), context) == Anchor(
        path=path, qualname="Index.find"
    )
    assert anchor_of(path, (2, 3), context) is None  # the module header
    assert (
        anchor_of(path, (_line(CORE, "def run"), _line(CORE, "def run")), context)
        is None
    )
    assert anchor_of("pkg/other.py", (match, match), context) is None


def test_anchor_of_in_an_unparsed_head_is_the_files_hotspot() -> None:
    source = "def hot(:\n    return 1\n\ndef cold():\n    return 2\n"
    context, _, _ = _read({"u.py": source}, [_spot("u.py", "hot", 1)])
    assert anchor_of("u.py", (4, 5), context) == Anchor(path="u.py", qualname="hot")


def _module_and_f(path: str, f_line: int) -> list[Hotspot]:
    """cProfile's ``<module>`` row (line 1, the whole run) and a cheap ``f``."""
    return [
        _spot(path, "<module>", 1, total=10.0, self_s=9.0, share=0.9),
        _spot(path, "f", f_line, total=0.5, self_s=0.5, share=0.05),
    ]


@pytest.mark.parametrize(
    "source",
    ["def f(x):\n    return x + 1\n", "@cache\ndef f(x):\n    return x + 1\n"],
    ids=["def-on-line-1", "decorator-on-line-1"],
)
def test_a_module_hotspot_never_lands_in_a_function_on_line_one(source: str) -> None:
    """
    GIVEN a file whose line 1 starts a function, with cProfile's ``<module>``
    row at line 1 (the whole run) and the function's own row
    WHEN the context is read and the function anchors an idea
    THEN the span holds only the function's hotspot, and the ceiling is the
    function's own share, never the module's (D51)
    """
    spots = _module_and_f("s.py", 1)
    context, _, _ = _read({"s.py": source}, spots)
    (span,) = _doc(context, "s.py").spans
    assert (span.qualname, span.hotspot_ids) == ("f", ("w1:s.py:f",))
    last = len(source.split("\n")) - 1
    anchor = anchor_of("s.py", (last, last), context)
    assert anchor == Anchor(path="s.py", qualname="f")
    assert amdahl_ceiling(anchor, [spots[0]], context, profile=spots) == pytest.approx(
        0.05
    )


def test_a_module_hotspot_never_names_an_unparsed_head() -> None:
    source = "def f(:\n    return 1\n"
    spots = _module_and_f("u.py", 1)
    context, _, _ = _read({"u.py": source}, spots)
    (span,) = _doc(context, "u.py").spans
    assert (span.qualname, span.hotspot_ids) == ("f", ("w1:u.py:f",))
    alone, _, _ = _read({"u.py": source}, spots[:1])
    assert _doc(alone, "u.py").spans == ()
    assert anchor_of("u.py", (2, 2), alone) is None


def test_anchor_of_needs_a_span_with_hotspots() -> None:
    span = FunctionSpan(path="a.py", qualname="f", start_line=1, end_line=5)
    document = CodeDocument(
        path="a.py", start_line=1, end_line=5, rendered="", raw="", spans=(span,)
    )
    assert anchor_of("a.py", (2, 3), CodeContext(documents=(document,))) is None


def _ceiling_context() -> CodeContext:
    spans = (
        FunctionSpan(path="a.py", qualname="hot", start_line=1, end_line=9,
                     hotspot_ids=("h1", "h2")),
        FunctionSpan(path="a.py", qualname="hot.inner", start_line=2, end_line=4),
        FunctionSpan(path="a.py", qualname="ghost", start_line=5, end_line=6,
                     hotspot_ids=("missing",)),
    )  # fmt: skip
    document = CodeDocument(
        path="a.py", start_line=1, end_line=9, rendered="", raw="", spans=spans
    )
    return CodeContext(
        documents=(document,), totals_by_workload={"w1": 10.0, "w2": 4.0}
    )


def test_amdahl_ceiling_is_the_anchors_own_share_largest_over_workloads() -> None:
    context = _ceiling_context()
    profile = [
        _spot("a.py", "hot", 1, total=3.0, spot_id="h1"),
        _spot("a.py", "hot", 1, total=2.0, workload="w2", spot_id="h2"),
        _spot("a.py", "main", 20, total=10.0, spot_id="entry"),
    ]
    anchor = Anchor(path="a.py", qualname="hot")
    # the idea lists only the entry point: the anchor's share still counts
    assert amdahl_ceiling(anchor, [profile[2]], context, profile=profile) == 0.5
    one = [profile[0]]
    assert amdahl_ceiling(anchor, [], context, profile=one) == pytest.approx(0.3)


def test_amdahl_ceiling_of_a_nested_anchor_is_its_enclosing_hot_share() -> None:
    """
    GIVEN an anchor nested in a hot span (it has no hotspot of its own)
    WHEN the idea lists only the entry point at 100 % (or nothing)
    THEN the ceiling is the enclosing hot span's own share: the idea's list
    passes nothing (section 5, D51)
    """
    context = _ceiling_context()
    profile = [
        _spot("a.py", "hot", 1, total=3.0, spot_id="h1"),
        _spot("a.py", "hot", 1, total=2.0, workload="w2", spot_id="h2"),
        _spot("a.py", "main", 20, total=10.0, spot_id="entry"),
    ]
    inner = Anchor(path="a.py", qualname="hot.inner")
    entry = [profile[2]]
    assert amdahl_ceiling(inner, entry, context, profile=profile) == 0.5
    assert amdahl_ceiling(inner, [], context, profile=profile) == 0.5
    ghost = Anchor(path="a.py", qualname="ghost")  # own ids not in the profile
    assert amdahl_ceiling(ghost, entry, context, profile=profile) == 0.5


def test_amdahl_ceiling_without_a_hotspot_is_the_smallest_listed_share() -> None:
    context = _ceiling_context()
    listed = [
        _spot("a.py", "hot", 1, total=3.0, spot_id="h1"),
        _spot("a.py", "other", 7, total=1.0, spot_id="o1"),
        _spot("b.py", "far", 1, total=0.1, spot_id="b1"),
        _spot("a.py", "lost", 7, total=0.5, workload="w9", spot_id="x9"),
    ]
    # a hand-built context whose hot spans resolve to nothing in the profile
    inner = Anchor(path="a.py", qualname="hot.inner")
    assert amdahl_ceiling(inner, listed, context, profile=[]) == pytest.approx(0.1)
    ghost = Anchor(path="a.py", qualname="ghost")
    assert amdahl_ceiling(ghost, listed, context, profile=[]) == pytest.approx(0.1)
    assert amdahl_ceiling(inner, listed[2:], context, profile=[]) is None
    assert amdahl_ceiling(None, listed, context, profile=listed) is None
    unknown = Anchor(path="a.py", qualname="nowhere")
    assert amdahl_ceiling(unknown, listed, context, profile=listed) is None


def test_amdahl_ceiling_is_clipped_to_one() -> None:
    context = _ceiling_context()
    profile = [_spot("a.py", "hot", 1, total=50.0, spot_id="h1")]
    anchor = Anchor(path="a.py", qualname="hot")
    assert amdahl_ceiling(anchor, [], context, profile=profile) == 1.0


# --------------------------------------------------------------------------
# render_data_block
# --------------------------------------------------------------------------


def _objective(**values: object) -> Objective:
    fields: dict[str, object] = {
        "project_id": PROJECT.id, "kind": ObjectiveKind.runtime,
        "metric": "wall_time_s", "direction": Direction.minimize,
        "min_relative_gain": 0.043, "description": "minimize run time",
    }  # fmt: skip
    return Objective.model_validate({**fields, **values})


def _understanding(summary: str = "a word index") -> ProjectUnderstanding:
    return ProjectUnderstanding(
        language="python",
        summary=summary,
        candidate_modules=(CandidateModule(path="pkg/core.py", reason="hot"),),
        served_by_model="claude-opus-5-5",
    )


def _block(
    context: CodeContext,
    spots: list[Hotspot],
    fence: Fence,
    *,
    project: Project = PROJECT,
    objective: Objective | None = None,
    understanding: ProjectUnderstanding | None = None,
) -> tuple[str, list[str]]:
    notes: list[str] = []
    text = render_data_block(
        context,
        project=project,
        objective=objective or _objective(),
        understanding=understanding or _understanding(),
        hotspots=spots,
        fence=fence,
        notes=notes,
    )
    return text, notes


def test_render_data_block_is_byte_stable_and_in_the_stated_order() -> None:
    blobs = {"pkg/core.py": CORE, "more.py": _SPAWN}
    spots = [
        _spot("pkg/core.py", "find", _line(CORE, "def find"), total=1.2,
              self_s=0.5, share=0.25),
        _spot("more.py", "hot", 1, total=0.4),
    ]  # fmt: skip
    fence = Fence.new()
    context, _, _ = _read(blobs, spots, fence=fence, file_max_bytes=200)
    first, notes = _block(context, spots, fence)
    again, again_notes = _block(context, spots, fence)
    assert (first, notes) == (again, again_notes) and notes == []
    token = fence.token
    lines = first.split("\n")
    assert lines[0] == fence.opening()
    assert lines[1] == f"<untrusted_repo_content boundary={token}>"
    assert lines[-1] == f"</untrusted_repo_content boundary={token}>"
    order = ["project: ", "objective: ", "noise floor: a gain below 4.3 % ",
             "project understanding: ", "profiler hotspots (", "hot code at the base",
             "<documents>", '<document path="pkg/core.py"', '<document path="more.py"',
             "</documents>"]  # fmt: skip
    found = [first.index(marker) for marker in order]
    assert found == sorted(found)
    assert '"min_relative_gain": 0.043' in first
    assert 'reason="hot functions: Index.find (cumulative 60 %)"' in first
    assert 'spawn_finding="line 2: uses __import__; an edit may not touch' in first
    assert "an edit must leave that statement" in first
    assert _doc(context, "more.py").rendered in first
    other, _ = _block(context, spots, Fence.new())
    assert other != first


def test_render_data_block_without_spawn_findings_has_no_spawn_sentence() -> None:
    spots = [_spot("a.py", "f", 1, self_s=0.0, share=0.0)]
    fence = Fence.new()
    context, _, _ = _read({"a.py": "def f():\n    return 1\n"}, spots, fence=fence)
    text, _ = _block(context, spots, fence)
    assert "spawn_finding" not in text and "an edit must leave" not in text
    assert 'reason="hot functions: f"' in text  # no total to share against


def test_render_data_block_withholds_text_holding_a_live_token() -> None:
    fence = Fence.new(others=("abad1deaabad1dea",))
    spots = [_spot("a.py", "f", 1)]
    context, _, _ = _read({"a.py": "def f():\n    return 1\n"}, spots, fence=fence)
    forged = CodeDocument(
        path="b.py", start_line=1, end_line=1, rendered="L1: x", raw="x",
        spans=(FunctionSpan(path="b.py", qualname="ABAD1DEAABAD1DEA", start_line=1,
                            end_line=1, hotspot_ids=("w1:a.py:f",)),),
    )  # fmt: skip
    context = context.model_copy(update={"documents": (*context.documents, forged)})
    text, notes = _block(
        context,
        spots,
        fence,
        project=PROJECT.model_copy(update={"name": f"x{fence.token}"}),
        objective=_objective(description="see abad1deaabad1dea"),
        understanding=_understanding(summary=fence.token),
    )
    assert text.count(fence.token) == 3  # the opening line and the two tags
    assert "abad1dea" not in text.casefold()
    assert 'project: {"name": "(withheld)", "language": "python"}' in text
    assert '"description": "(withheld)"' in text
    assert "no project understanding is available" in text
    assert '<document path="a.py"' in text and '"b.py"' not in text
    assert _noted(notes, "the project name withheld")
    assert _noted(notes, "the objective description withheld")
    assert _noted(notes, "1 document(s) withheld: they hold a boundary token")
