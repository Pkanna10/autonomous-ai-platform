"""The idea lab's per-lane views (G2; idea-lab spec section 1, "What they see").

``build_view`` gives one lane one slice of the profiled repository instead of
the shared hot-code block: the callers of the hottest function, the data
structures its body touches, the workloads' real inputs, the whole module
around it, the 2nd and 3rd hotspots, or the project's own performance
commits. Every view reads the repository through S0's rules (``read_text``
at the commit, the deny list, the protected set, binary refusal) and holds
the hot function it is about, so a lane's quotes still ground (D50).
``render_data_block`` fences a view exactly as it fences the shared block.

The history view's contamination guard is tested on a real git repository
whose later commit is a speed-up: it never appears, because the walk only
ever moves from the pinned commit to its parents. Every other reader is a
dict fake; nothing runs a model.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from autonomous_ai_agents.clients.structured import Fence
from autonomous_ai_agents.common.config import IDEA_VIEWS, IdeaView
from autonomous_ai_agents.common.models import (
    Direction,
    Hotspot,
    Objective,
    ObjectiveKind,
    Project,
    Workload,
)
from autonomous_ai_agents.common.repo_read import RepoReader
from autonomous_ai_agents.execution.git import GitError, GitWorkspace
from autonomous_ai_agents.optimization.idea_context import (
    CALL_SITES_MAX,
    HISTORY_COMMITS_MAX,
    INPUT_FILES_MAX,
    VIEW_FACTS_MAX_BYTES,
    HistoryReader,
    IdeaReadLimits,
    LaneView,
    ViewSource,
    build_view,
    render_data_block,
    review_context,
)
from autonomous_ai_agents.optimization.idea_lanes import grounded
from autonomous_ai_agents.optimization.idea_prompts import (
    VIEW_CODE_HEADING,
    VIEW_HEADINGS,
)
from autonomous_ai_agents.optimization.idea_types import (
    CodeContext,
    CodeDocument,
    FunctionSpan,
)

SHA = "0123456789abcdef0123456789abcdef01234567"
PROJECT = Project(id="p1", name="demo", root_path="/srv/demo")
OBJECTIVE = Objective(
    project_id="p1",
    kind=ObjectiveKind.runtime,
    metric="wall_time_s",
    direction=Direction.minimize,
    min_relative_gain=0.03,
    description="faster",
)

CORE = '''"""Core."""
import re

TABLE = {"a": 1, "b": 2, "c": 3}
SEEN = []
PATTERN = re.compile("x")


class Node:
    __slots__ = ("name", "kids")

    def __init__(self, name):
        self.name = name
        self.kids = []


def score(word, node):
    SEEN.append(word)
    total = 0
    for ch in word:
        total += TABLE.get(ch, 0)
    if word in TABLE:
        total += len(SEEN)
    node.kids.append(word)
    del SEEN[0]
    TABLE[word] = total
    return total


def tokens(text):
    return text.split()


def walk(node):
    for kid in node.kids:
        walk(kid)
    return node.name
'''
CLI = """from pkg.core import score, tokens


def main(text):
    out = []
    for word in tokens(text):
        out.append(score(word, None))
    return out


def once(text):
    return score(text, None, extra=1)


RESULT = score("x", None)
"""
TEST = (
    "from pkg.core import score\n\n\ndef test_score():\n    assert score('a', None)\n"
)
INPUT = "alpha beta\nalpha beta\n\ngamma delta epsilon\n"
PATHS: dict[str, bytes | str] = {
    "pkg/core.py": CORE,
    "pkg/cli.py": CLI,
    "tests/test_core.py": TEST,
    "data/input.txt": INPUT,
    "data/frozen.txt": "expected\n",
    "data/blob.bin": b"\0\1\2" * 10,
    "bench/run.py": "import pkg.cli\n",
    ".env": "SECRET=1\n",
}


def _line(source: str, needle: str) -> int:
    return next(i for i, t in enumerate(source.split("\n"), 1) if needle in t)


def _spot(
    path: str,
    symbol: str,
    source: str,
    *,
    share: float,
    total: float = 1.0,
    calls: int | None = None,
) -> Hotspot:
    return Hotspot(
        id=f"h-{symbol}",
        project_id="p1",
        workload_id="w1",
        file_path=path,
        symbol=symbol,
        line_start=_line(source, f"def {symbol}("),
        self_time_s=share * 10,
        total_time_s=total,
        share=share,
        calls=calls,
    )


SCORE = _spot("pkg/core.py", "score", CORE, share=0.4, total=4.0, calls=1200)
TOKENS = _spot("pkg/core.py", "tokens", CORE, share=0.2, total=2.0)
WALK = _spot("pkg/core.py", "walk", CORE, share=0.1, total=1.0)
MAIN = _spot("pkg/cli.py", "main", CLI, share=0.05, total=9.0, calls=1)
HOTSPOTS = (SCORE, TOKENS, WALK, MAIN)
WORKLOAD = Workload(
    id="w1",
    project_id="p1",
    name="bench",
    command=("python", "bench/run.py", "data/input.txt", "--n", "3", "missing.txt"),
    entrypoint="bench/run.py",
    inputs={"frozen": "data/frozen.txt", "blob": "data/blob.bin", "n": 3},
)


class _Reader:
    """A ``RepoReader`` over a dict; records every path read."""

    def __init__(self, blobs: Mapping[str, bytes | str]) -> None:
        self.blobs = {
            p: b if isinstance(b, bytes) else b.encode() for p, b in blobs.items()
        }
        self.reads: list[str] = []

    def ls_tree(self, commit: str) -> tuple[str, ...]:
        if commit != SHA:
            raise GitError("unknown commit")
        return tuple(sorted(self.blobs))

    def read_blob(self, commit: str, path: str, *, limit: int | None = None) -> bytes:
        self.reads.append(path)
        data = self.blobs[path]
        return data if limit is None else data[:limit]


def _source(
    blobs: Mapping[str, bytes | str] = PATHS,
    spots: Sequence[Hotspot] = HOTSPOTS,
    *,
    commit: str = SHA,
    fence: Fence | None = None,
    workloads: Sequence[Workload] = (),
    history: HistoryReader | None = None,
    read_deny: Sequence[str] = (),
    reader: RepoReader | None = None,
    **limits: int,
) -> ViewSource:
    return ViewSource(
        reader=reader or _Reader(blobs),
        commit=commit,
        hotspots=tuple(spots),
        fence=fence or Fence("f00df00df00df00d"),
        protected=(),
        read_deny=tuple(read_deny),
        limits=IdeaReadLimits(**limits),
        workloads=tuple(workloads),
        history=history,
    )


def _view(name: IdeaView, source: ViewSource) -> tuple[LaneView, list[str]]:
    notes: list[str] = []
    view = build_view(name, source, notes)
    assert view is not None, notes
    return view, notes


def _facts(view: LaneView, label: str) -> list[dict[str, object]]:
    found = []
    for fact in view.facts:
        head, _, body = fact.partition(": ")
        if head == label:
            found.append(json.loads(body))
    return found


def _qualnames(context: CodeContext) -> dict[str, list[str]]:
    return {d.path: [s.qualname for s in d.spans] for d in context.documents}


def _noted(notes: Sequence[str], *parts: str) -> bool:
    return any(all(part in note for part in parts) for note in notes)


# --------------------------------------------------------------------------
# Callers
# --------------------------------------------------------------------------


def test_the_callers_view_lists_each_call_site_with_its_shape() -> None:
    """
    GIVEN score, the hottest function by self time, called in a loop by
        main (itself profiled), once with a keyword, at module level and by
        a test
    WHEN its callers view is built
    THEN each call site outside the protected test names its caller, line,
        argument shape and whether it sits in a loop; the profile's call
        counts ride along; the context holds score and main, so either grounds
    """
    view, notes = _view("callers", _source())
    assert view.name == "callers"
    hot = _facts(view, "hot function")
    assert hot == [{"path": "pkg/core.py", "symbol": "score", "calls": {"w1": 1200}}]
    sites = _facts(view, "call site")
    assert [(s["path"], s["caller"]) for s in sites] == [
        ("pkg/cli.py", "main"),
        ("pkg/cli.py", "once"),
        ("pkg/cli.py", "<module>"),
    ]
    main, once, module = sites
    assert main["in_loop"] is True
    assert main["positional"] == 2
    assert main["keywords"] == []
    assert main["caller_calls"] == 1
    assert main["line"] == _line(CLI, "out.append(score(")
    assert "out.append(score(word, None))" in str(main["call"])
    assert once["keywords"] == ["extra"]
    assert once["in_loop"] is False
    assert once["caller_calls"] is None
    assert module["caller"] == "<module>"
    assert all(s["path"] != "tests/test_core.py" for s in sites)
    assert _qualnames(view.context) == {
        "pkg/core.py": ["score"],
        "pkg/cli.py": ["main"],
    }
    assert grounded("pkg/cli.py", "out.append(score(word, None))", view.context)
    assert grounded("pkg/core.py", "total += TABLE.get(ch, 0)", view.context)
    assert all(n.startswith("view callers: ") for n in notes)


def test_a_comprehension_call_is_in_a_loop_and_a_nested_def_resets_it() -> None:
    """
    GIVEN calls inside a comprehension and inside a def nested in a loop
    WHEN the callers view is built
    THEN the comprehension's call is in a loop and the nested def's is not
    """
    cli = (
        "from pkg.core import score\n\n\ndef many(ws):\n"
        "    return [score(w, None) for w in ws]\n\n\n"
        "def outer(ws):\n    for w in ws:\n        def inner():\n"
        "            return score(w, None)\n        inner()\n"
    )
    view, _ = _view("callers", _source({**PATHS, "pkg/cli.py": cli}))
    loops = {s["caller"]: s["in_loop"] for s in _facts(view, "call site")}
    assert loops == {"many": True, "outer.inner": False}


def test_call_sites_past_the_cap_and_files_past_the_scan_are_noted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    GIVEN more call sites than CALL_SITES_MAX and more files than the scan
    WHEN the callers view is built
    THEN the first CALL_SITES_MAX are listed and both cuts are noted; an
        unparsable or unreadable file is skipped
    """
    from autonomous_ai_agents.optimization import idea_context

    calls = "".join(f"score({i}, None)\n" for i in range(CALL_SITES_MAX + 3))
    blobs = {
        **PATHS,
        "pkg/many.py": f"from pkg.core import score\n{calls}",
        "pkg/broken.py": "def (:\n",
        "pkg/binary.py": b"\0" * 20,
        "pkg/zzz.py": "score(1, None)\n",
    }
    monkeypatch.setattr(idea_context, "VIEW_SCAN_FILES", 6)
    view, notes = _view("callers", _source(blobs))
    assert len(_facts(view, "call site")) == CALL_SITES_MAX
    assert _noted(notes, "call site(s) not listed", f"limit {CALL_SITES_MAX}")
    assert _noted(notes, "1 file(s) not scanned for callers", "limit 6")


def test_no_caller_found_still_shows_the_hot_function() -> None:
    view, _ = _view("callers", _source({"pkg/core.py": CORE}, (TOKENS,)))
    assert _facts(view, "call site") == []
    assert _qualnames(view.context) == {"pkg/core.py": ["tokens"]}


# --------------------------------------------------------------------------
# Data structures
# --------------------------------------------------------------------------


def test_the_data_structures_view_names_types_sizes_and_mutations() -> None:
    """
    GIVEN score, which reads TABLE (a 3-entry dict), appends to and deletes
        from SEEN (an empty list), grows node.kids and writes TABLE[word]
    WHEN its data structures view is built
    THEN each module-level structure it touches has its kind, size and
        defining line; each name's uses are counted; the unused PATTERN and
        the Node class it never names are absent
    """
    view, _ = _view("data_structures", _source())
    defined = {d["name"]: d for d in _facts(view, "module name")}
    assert set(defined) == {"TABLE", "SEEN"}
    assert defined["TABLE"]["kind"] == "dict literal"
    assert defined["TABLE"]["size"] == 3
    assert defined["TABLE"]["line"] == _line(CORE, "TABLE = {")
    assert defined["SEEN"]["kind"] == "list literal"
    assert defined["SEEN"]["size"] == 0
    assert "SEEN = []" in str(defined["SEEN"]["text"])
    uses = {u["name"]: u["uses"] for u in _facts(view, "uses")}
    assert uses["SEEN"] == {"append": 1, "len": 1, "subscript_delete": 1}
    assert uses["TABLE"] == {"get": 1, "membership": 1, "subscript_write": 1}
    assert uses["node.kids"] == {"append": 1}
    assert uses["word"] == {"iterated": 1}
    assert uses["total"] == {"augmented": 2}
    assert _facts(view, "class") == []
    assert _qualnames(view.context) == {"pkg/core.py": ["score"]}


def test_a_method_shows_its_class_with_slots_and_attributes() -> None:
    """
    GIVEN a hot method of a dataclass-decorated class with slots
    WHEN its data structures view is built
    THEN the enclosing class is listed with its bases, slots, decorator and
        the attributes its methods assign; other kinds are named
    """
    source = (
        "from dataclasses import dataclass\nimport re\n\n"
        'LIMIT = 10\nNAMES = ("a",)\nRX = re.compile("x")\n'
        "SQUARES = [i * i for i in range(3)]\nN: int = 4\nA = B = 1\nX, Y = 1, 2\n"
        "OTHER = LIMIT + 1\n\n\n"
        '@dataclass\nclass Box(object):\n    __slots__ = ("items",)\n\n'
        "    def __init__(self):\n        self.items = []\n        self.size = 0\n\n"
        "    def fill(self, n):\n"
        "        self.items += [RX, LIMIT, NAMES, SQUARES, N, A, X, OTHER]\n"
        "        self.items[0].count(n == LIMIT)\n"
        "        return self.items[n]\n"
    )
    spot = _spot("pkg/box.py", "fill", source, share=0.5)
    view, _ = _view("data_structures", _source({"pkg/box.py": source}, (spot,)))
    (box,) = _facts(view, "class")
    assert box == {
        "class": "Box",
        "line": _line(source, "class Box"),
        "bases": ["object"],
        "decorators": ["dataclass"],
        "slots": True,
        "attributes": ["items", "size"],
    }
    kinds = {d["name"]: d["kind"] for d in _facts(view, "module name")}
    assert kinds == {
        "LIMIT": "constant int",
        "NAMES": "tuple literal",
        "RX": "call to compile",
        "SQUARES": "comprehension",
        "N": "constant int",
        "A": "constant int",
        "OTHER": "BinOp",
    }
    uses = {u["name"]: u["uses"] for u in _facts(view, "uses")}
    assert uses["self.items"] == {"augmented": 1, "subscript_read": 2}


def test_an_unparsable_hot_file_gives_no_structure_facts() -> None:
    broken = "def score(word):\n    return word +\n"
    spot = Hotspot(id="h", project_id="p1", workload_id="w1", file_path="pkg/b.py",
                   symbol="score", line_start=1, self_time_s=1.0, total_time_s=1.0,
                   share=0.5)  # fmt: skip
    view, _ = _view("data_structures", _source({"pkg/b.py": broken}, (spot,)))
    assert view.facts == ()
    assert [d.path for d in view.context.documents] == ["pkg/b.py"]


# --------------------------------------------------------------------------
# Input shape
# --------------------------------------------------------------------------


def test_the_input_shape_view_reads_the_workloads_real_inputs() -> None:
    """
    GIVEN a workload whose argv names a tracked input file, its entry
        script, a flag and an untracked name, and whose inputs name a
        frozen quality file and a binary file
    WHEN the input shape view is built
    THEN the workload's argv and inputs are listed; the text input is
        summarised from its real bytes with a screened head; the binary one
        is named as binary; the frozen file is never read; the script, the
        flag and the untracked name are not inputs
    """
    source = _source(workloads=(WORKLOAD,), read_deny=("data/frozen.txt",))
    view, notes = _view("input_shape", source)
    (workload,) = _facts(view, "workload")
    assert workload == {
        "name": "bench",
        "argv": list(WORKLOAD.command),
        "inputs": {"frozen": "data/frozen.txt", "blob": "data/blob.bin", "n": 3},
    }
    files = {f["path"]: f for f in _facts(view, "input file")}
    assert set(files) == {"data/input.txt", "data/blob.bin"}
    text = files["data/input.txt"]
    assert text == {
        "path": "data/input.txt",
        "bytes": len(INPUT.encode()),
        "cut": False,
        "lines": 4,
        "blank_lines": 1,
        "distinct_lines": 3,
        "longest_line": len("gamma delta epsilon"),
        "mean_line": round(len(INPUT.replace("\n", "")) / 4, 1),
        "ascii": True,
        "head": ["alpha beta", "alpha beta", "", "gamma delta epsilon"],
    }
    assert files["data/blob.bin"] == {"path": "data/blob.bin", "kind": "binary"}
    reader = source.reader
    assert isinstance(reader, _Reader)
    assert "data/frozen.txt" not in reader.reads
    assert _noted(notes, "data/frozen.txt", "never read")
    assert _qualnames(view.context) == {"pkg/core.py": ["score"]}


def test_an_input_head_is_screened_capped_and_its_size_marked_cut(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    GIVEN an input holding a secret-shaped line, a bidi control, a long line
        and more bytes than the sample cap, and more inputs than the limit
    WHEN the input shape view is built
    THEN secret and bidi lines are withheld in the head, a line is cut to
        200 characters, the size is marked cut, and the extra inputs noted;
        a working directory resolves relative names; a secret-like file is
        never read
    """
    from autonomous_ai_agents.optimization import idea_context

    monkeypatch.setattr(idea_context, "INPUT_SAMPLE_BYTES", 300)
    body = "token sk-ant-abc\nright‮left\n" + "x" * 250 + "\n" + "y\n" * 100
    names = [f"in{i}.txt" for i in range(INPUT_FILES_MAX + 1)]
    blobs = {**PATHS, **{f"run/{n}": body for n in names}, "run/.env": "K=1\n"}
    workload = Workload(project_id="p1", name="w", working_dir="run",
                        command=("python", *names, ".env", "../../x"))  # fmt: skip
    view, notes = _view("input_shape", _source(blobs, workloads=(workload,)))
    files = _facts(view, "input file")
    assert len(files) == INPUT_FILES_MAX
    first = files[0]
    assert first["path"] == "run/in0.txt"
    assert first["cut"] is True
    head = first["head"]
    assert isinstance(head, list)
    assert head[:2] == [
        "(line withheld: secret-shaped)",
        "(line withheld: a bidi control)",
    ]
    assert head[2] == "x" * 200
    assert first["ascii"] is False
    assert _noted(notes, "input file(s) not read", f"limit {INPUT_FILES_MAX}")
    assert _noted(notes, "run/.env", "secret-like")


class _FailingReader(_Reader):
    def read_blob(self, commit: str, path: str, *, limit: int | None = None) -> bytes:
        if path == "data/input.txt":
            raise GitError("cannot read")
        return super().read_blob(commit, path, limit=limit)


def test_an_unreadable_input_is_named_not_raised() -> None:
    workload = Workload(project_id="p1", name="w", command=("python", "data/input.txt"))
    source = _source(workloads=(workload,), reader=_FailingReader(PATHS))
    view, notes = _view("input_shape", source)
    assert _facts(view, "input file") == [
        {"path": "data/input.txt", "kind": "unreadable"}
    ]
    assert _noted(notes, "data/input.txt: unreadable in git")


def test_an_empty_input_file_has_no_lines() -> None:
    workload = Workload(project_id="p1", name="w", command=("python", "data/empty.txt"))
    view, _ = _view("input_shape", _source({**PATHS, "data/empty.txt": ""},
                                           workloads=(workload,)))  # fmt: skip
    (empty,) = _facts(view, "input file")
    assert (empty["lines"], empty["longest_line"], empty["mean_line"]) == (0, 0, 0.0)


def test_no_workload_gives_the_hot_function_and_a_note() -> None:
    view, notes = _view("input_shape", _source())
    assert view.facts == ()
    assert _noted(notes, "no workload")
    assert _qualnames(view.context) == {"pkg/core.py": ["score"]}


# --------------------------------------------------------------------------
# Whole module, next hotspots
# --------------------------------------------------------------------------


def test_the_whole_module_view_shows_the_hot_file_whole() -> None:
    """
    GIVEN core.py, larger than the shared block's whole-file size
    WHEN the whole module view is built
    THEN all of core.py is shown, with every listed hotspot's span, and
        nothing from another file
    """
    view, _ = _view("whole_module", _source(file_max_bytes=200))
    (document,) = view.context.documents
    assert document.path == "pkg/core.py"
    assert (document.start_line, document.end_line) == (1, CORE.count("\n"))
    assert {s.qualname for s in document.spans if s.hotspot_ids} == {
        "score", "tokens", "walk"
    }  # fmt: skip


def test_the_next_hotspots_view_shows_the_2nd_and_3rd_not_the_top() -> None:
    view, _ = _view("next_hotspots", _source())
    assert _qualnames(view.context) == {"pkg/core.py": ["tokens", "walk"]}
    assert _facts(view, "hottest function (not shown)") == [
        {"path": "pkg/core.py", "symbol": "score"}
    ]


def test_one_hotspot_has_no_next_hotspots_view() -> None:
    notes: list[str] = []
    assert build_view("next_hotspots", _source(spots=(SCORE,)), notes) is None
    assert _noted(notes, "view next_hotspots: ", "no 2nd or 3rd hotspot")


# --------------------------------------------------------------------------
# Every view: the anchor, the cap, the read rules
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", IDEA_VIEWS)
def test_every_view_is_capped_and_never_reads_a_denied_file(name: IdeaView) -> None:
    source = _source(workloads=(WORKLOAD,), file_max_bytes=2048, code_max_bytes=4096)
    view, _ = _view(name, source)
    cap = 4096 if name == "whole_module" else 2048
    assert sum(len(d.rendered.encode()) for d in view.context.documents) <= cap
    reader = source.reader
    assert isinstance(reader, _Reader)
    assert ".env" not in reader.reads


@pytest.mark.parametrize("name", IDEA_VIEWS)
def test_no_showable_hot_function_gives_no_view(name: IdeaView) -> None:
    """
    GIVEN only a protected hotspot and one whose function is not found
    WHEN any view is built
    THEN there is no view, and why is noted under the view's name
    """
    lost = Hotspot(id="h-x", project_id="p1", workload_id="w1",
                   file_path="pkg/core.py", symbol="gone", line_start=None,
                   self_time_s=0.1, total_time_s=0.1, share=0.01)  # fmt: skip
    test = _spot("tests/test_core.py", "test_score", TEST, share=0.5)
    notes: list[str] = []
    assert build_view(name, _source(spots=(test, lost)), notes) is None
    assert notes and all(n.startswith(f"view {name}: ") for n in notes)


def test_an_unreadable_file_list_gives_no_view() -> None:
    notes: list[str] = []
    assert build_view("callers", _source(commit="f" * 40), notes) is None
    assert _noted(notes, "file list is unreadable")


def test_the_module_row_is_never_the_hot_function() -> None:
    module = Hotspot(id="h-m", project_id="p1", workload_id="w1",
                     file_path="pkg/cli.py", symbol="<module>", line_start=1,
                     self_time_s=9.0, total_time_s=9.0, share=0.9)  # fmt: skip
    view, _ = _view("callers", _source(spots=(module, *HOTSPOTS)))
    assert _facts(view, "hot function")[0]["symbol"] == "score"


# --------------------------------------------------------------------------
# History: the contamination guard
# --------------------------------------------------------------------------

_ENV = {
    "PATH": os.environ.get("PATH", os.defpath),
    "HOME": os.devnull,
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
}


def _git(repo: Path, *argv: str) -> str:
    done = subprocess.run(["git", "-C", str(repo), *argv], env=_ENV, check=True,
                          capture_output=True, text=True)  # fmt: skip
    return done.stdout.strip()


def _commit(repo: Path, path: str, text: str, message: str) -> str:
    (repo / path).parent.mkdir(parents=True, exist_ok=True)
    (repo / path).write_text(text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


class _Recording:
    """A ``HistoryReader`` over a real ``GitWorkspace`` that records every
    commit it is asked about, so the test can check each is at or before
    the pin."""

    def __init__(self, git: GitWorkspace) -> None:
        self.git = git
        self.asked: list[str] = []

    def resolve_commit(self, rev: str) -> str:
        self.asked.append(rev)
        return self.git.resolve_commit(rev)

    def commit_message(self, commit: str) -> bytes:
        self.asked.append(commit)
        return self.git.commit_message(commit)

    def diff_commits(self, base: str, tip: str, *, max_bytes: int = 1 << 20) -> str:
        self.asked += [base, tip]
        return self.git.diff_commits(base, tip, max_bytes=max_bytes)


@pytest.fixture
def history_repo(tmp_path: Path) -> tuple[GitWorkspace, dict[str, str]]:
    """root -> perf (speed-up of core) -> plain -> merge of a feature branch
    whose own commit is a speed-up (the GitHub merge-PR flow) -> PIN; then a
    later speed-up after the pin, and a side branch's speed-up that is no
    ancestor."""
    repo = tmp_path / "lib"
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], env=_ENV, check=True)
    shas = {"root": _commit(repo, "pkg/core.py", CORE, "initial import")}
    shas["perf"] = _commit(repo, "pkg/core.py", CORE + "\n# fast\n",
                           "Speed up score with a lookup table\n\nUses a dict.")  # fmt: skip
    shas["plain"] = _commit(repo, "README", "docs\n", "Document the API")
    _git(repo, "checkout", "-q", "-b", "feature")
    shas["merged"] = _commit(repo, "pkg/fast.py", "y = 2\n",
                             "Cache the token table for speed")  # fmt: skip
    _git(repo, "checkout", "-q", "main")
    _commit(repo, "CHANGES", "notes\n", "Note the release")
    _git(repo, "merge", "-q", "--no-ff", "-m", "Merge pull request #7 from dev/feature",
         "feature")  # fmt: skip
    shas["merge"] = _git(repo, "rev-parse", "HEAD")
    shas["pin"] = _commit(repo, "pkg/cli.py", CLI, "Add the command line")
    shas["later"] = _commit(repo, "pkg/core.py", CORE + "\n# 3x\n",
                            "Make score 3x faster with a cache")  # fmt: skip
    _git(repo, "checkout", "-q", "-b", "side", shas["perf"])
    shas["side"] = _commit(repo, "pkg/side.py", "x = 1\n", "Optimize the side path")
    _git(repo, "checkout", "-q", "main")
    return GitWorkspace(repo), shas


def test_the_history_view_never_shows_a_commit_past_the_pin(
    history_repo: tuple[GitWorkspace, dict[str, str]],
) -> None:
    """
    GIVEN a library pinned before a later "3x faster" commit, with an older
        speed-up before the pin, a speed-up merged in through a merge commit,
        and another on a side branch
    WHEN the history view is built at the pin
    THEN the merged and the older speed-ups are listed, nearest first, with
        their files and whether they touch a hot file; the later and the
        side commits never appear in the facts, the notes, or any commit the
        reader was asked about
    """
    git, shas = history_repo
    recording = _Recording(git)
    source = _source(commit=shas["pin"], history=recording, reader=git)
    view, notes = _view("history", source)
    merged, perf = _facts(view, "commit")
    assert merged == {
        "commit": shas["merged"][:12],
        "subject": "Cache the token table for speed",
        "body": [],
        "files": ["pkg/fast.py"],
        "touches_hot_file": False,
    }
    assert perf == {
        "commit": shas["perf"][:12],
        "subject": "Speed up score with a lookup table",
        "body": ["Uses a dict."],
        "files": ["pkg/core.py"],
        "touches_hot_file": True,
    }
    text = "\n".join((*view.facts, *notes))
    for name in ("later", "side"):
        assert shas[name][:12] not in text
        assert all(shas[name] not in asked for asked in recording.asked)
    assert "3x faster" not in text and "side path" not in text
    for asked in recording.asked:
        try:
            sha = git.resolve_commit(asked)
        except GitError:  # a parent one past a commit's last: the probe's end
            base, _, number = asked.partition("^")
            assert number.isdigit()
            sha = git.resolve_commit(base)
        assert git.is_ancestor(sha, shas["pin"])
    assert _qualnames(view.context) == {"pkg/core.py": ["score"]}


def test_the_history_walk_and_list_are_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    GIVEN more performance commits than HISTORY_COMMITS_MAX, then a walk
        limit below the history's depth
    WHEN the history view is built
    THEN the newest HISTORY_COMMITS_MAX are listed (newest first) and the
        walk limit is noted; a root commit lists no files
    """
    from autonomous_ai_agents.optimization import idea_context

    repo = tmp_path / "lib"
    subprocess.run(["git", "init", "-q", str(repo)], env=_ENV, check=True)
    shas = [_commit(repo, "pkg/core.py", CORE, "Faster start")]
    for i in range(HISTORY_COMMITS_MAX + 1):
        shas.append(_commit(repo, f"pkg/m{i}.py", f"x = {i}\n", f"perf: tune {i}"))
    git = GitWorkspace(repo)
    source = _source(commit=shas[-1], history=git, reader=git)
    commits = _facts(_view("history", source)[0], "commit")
    assert len(commits) == HISTORY_COMMITS_MAX
    assert commits[0]["subject"] == f"perf: tune {HISTORY_COMMITS_MAX}"
    assert commits[0]["touches_hot_file"] is False
    monkeypatch.setattr(idea_context, "HISTORY_WALK_MAX", 3)
    view, notes = _view("history", source)
    assert len(_facts(view, "commit")) == 3
    assert _noted(notes, "history walk stopped", "limit 3")
    root_source = _source(commit=shas[0], history=git, reader=git)
    (root,) = _facts(_view("history", root_source)[0], "commit")
    assert root["files"] == []


class _BrokenHistory:
    """Fails on demand: an unreadable message, or a diff that is not text."""

    def __init__(self, *, message: bool) -> None:
        self.message = message

    def resolve_commit(self, rev: str) -> str:
        if rev == f"{SHA}^1":
            return "a" * 40
        raise GitError("no parent")

    def commit_message(self, commit: str) -> bytes:
        if self.message and commit != SHA:
            raise GitError("cannot read")
        return b"perf: faster parse\n"

    def diff_commits(self, base: str, tip: str, *, max_bytes: int = 1 << 20) -> str:
        raise GitError("not UTF-8")


def test_history_failures_are_noted_not_raised() -> None:
    view, notes = _view("history", _source(history=_BrokenHistory(message=True)))
    (commit,) = _facts(view, "commit")
    assert commit["files"] == []
    assert _noted(notes, "files unreadable")
    assert _noted(notes, "commit message unreadable")


def test_no_history_reader_gives_the_hot_function_and_a_note() -> None:
    view, notes = _view("history", _source())
    assert view.facts == ()
    assert _noted(notes, "no commit history")


def test_a_git_workspace_is_a_history_reader(tmp_path: Path) -> None:
    assert isinstance(GitWorkspace(tmp_path), HistoryReader)
    assert not isinstance(_Reader({}), HistoryReader)


def test_diff_paths_are_parsed_renamed_and_odd_ones_withheld() -> None:
    from autonomous_ai_agents.optimization import idea_context

    diff = (
        "diff --git a/pkg/a.py b/pkg/a.py\n+x\n"
        "diff --git a/old.py b/new.py\n"
        "diff --git a/f00df00df00df00d b/f00df00df00df00d\n"
        "diff --git a/pkg/a.py b/pkg/a.py\n"
    )
    paths = idea_context._diff_paths(diff, Fence("f00df00df00df00d"))
    assert paths == ["pkg/a.py", "new.py"]


# --------------------------------------------------------------------------
# Rendering a view (the same fence as the shared block)
# --------------------------------------------------------------------------


def _render(view: LaneView, fence: Fence, notes: list[str]) -> str:
    return render_data_block(
        view.context, project=PROJECT, objective=OBJECTIVE, understanding=None,
        hotspots=HOTSPOTS, fence=fence, notes=notes, view=view.name,
        facts=view.facts,
    )  # fmt: skip


def test_a_view_is_fenced_like_the_shared_block_with_its_heading() -> None:
    """
    GIVEN the callers view and the shared block of the same call
    WHEN both are rendered with the call's fence
    THEN they open and close with the same boundary token, share the head
        (project, objective, floor, profile rows), and the view replaces the
        shared hot code with its heading, its facts and its documents
    """
    fence = Fence("f00df00df00df00d")
    view, _ = _view("callers", _source(fence=fence))
    shared = CodeContext(documents=view.context.documents[:1])
    notes: list[str] = []
    block = _render(view, fence, notes)
    plain = render_data_block(shared, project=PROJECT, objective=OBJECTIVE,
                              understanding=None, hotspots=HOTSPOTS, fence=fence,
                              notes=notes)  # fmt: skip
    head = plain.split("hot code at the base commit")[0]
    assert block.startswith(head)
    assert block.endswith("</untrusted_repo_content boundary=f00df00df00df00d>")
    assert VIEW_HEADINGS["callers"] in block
    assert VIEW_CODE_HEADING in block
    assert "hot code at the base commit" not in block
    assert block.count("<document ") == 2
    for fact in view.facts:
        assert fact in block


def test_view_facts_are_capped_and_unsafe_ones_withheld() -> None:
    """
    GIVEN facts past the byte cap, one holding the fence token and one
        holding a secret shape
    WHEN rendered
    THEN the unsafe facts are withheld and the excess dropped, each noted;
        no facts at all render as none found
    """
    fence = Fence("f00df00df00df00d")
    big = tuple(
        f"fact: {'x' * 1000} {i}" for i in range(VIEW_FACTS_MAX_BYTES // 1000 + 2)
    )
    facts = ("fact: f00df00df00df00d", "fact: sk-ant-key", *big)
    view = LaneView("callers", _view("callers", _source())[0].context, facts)
    notes: list[str] = []
    block = _render(view, fence, notes)
    assert "sk-ant-key" not in block
    assert _noted(notes, "2 view fact(s) withheld")
    assert _noted(notes, "view fact(s) dropped", f"limit {VIEW_FACTS_MAX_BYTES}")
    assert sum(len(f) + 1 for f in big if f in block) <= VIEW_FACTS_MAX_BYTES
    empty = _render(LaneView("history", view.context, ()), fence, [])
    assert "(none found)" in empty


# --------------------------------------------------------------------------
# The reviewer's documents: the shared block's plus what the views showed
# --------------------------------------------------------------------------


def _doc(
    path: str, shown: Mapping[int, str], *spans: tuple[str, int, str]
) -> CodeDocument:
    """A document showing ``shown`` (line -> text), rendered as S0 does."""
    numbers = sorted(shown)
    rendered: list[str] = []
    for previous, number in zip([None, *numbers], numbers, strict=False):
        if previous is not None and number != previous + 1:
            rendered.append(f"(lines {previous + 1}-{number - 1} not shown)")
        rendered.append(f"L{number}: {shown[number]}")
    raw = [shown.get(n, "") for n in range(numbers[0], numbers[-1] + 1)]
    return CodeDocument(
        path=path, start_line=numbers[0], end_line=numbers[-1],
        rendered="\n".join(rendered), raw="\n".join(raw),
        spans=tuple(FunctionSpan(path=path, qualname=q, start_line=n, end_line=n,
                                 hotspot_ids=(i,)) for q, n, i in spans),
        spawn_findings=("line 1: a spawn",),
    )  # fmt: skip


def test_the_reviewer_sees_the_shared_documents_and_each_views_extra_lines() -> None:
    """
    GIVEN a shared block showing lines 1 and 5 of core.py, and two views:
        one showing lines 3-4 and 7 of core.py, one showing cli.py and a
        line core.py already shows
    WHEN the reviewer's documents are merged
    THEN core.py is one document of every line either showed (gaps marked
        as S0 marks them, raw lines aligned, spans of both), cli.py follows
        it, the totals are the shared block's, and nothing is noted
    """
    shared = CodeContext(
        documents=(_doc("pkg/core.py", {1: "a", 5: "e"}, ("f", 5, "h-f")),),
        totals_by_workload={"w1": 4.0},
    )
    first = CodeContext(documents=(
        _doc("pkg/core.py", {3: "c", 4: "d", 7: "g"}, ("g", 7, "h-g")),
    ))  # fmt: skip
    cli = _doc("pkg/cli.py", {2: "main"}, ("main", 2, "h-main"))
    second = CodeContext(documents=(_doc("pkg/core.py", {5: "e"}), cli))
    notes: list[str] = []

    merged = review_context(shared, [first, second], cap=10_000, notes=notes)

    core, shown_cli = merged.documents
    assert core.rendered == (
        "L1: a\n(lines 2-2 not shown)\nL3: c\nL4: d\nL5: e\n"
        "(lines 6-6 not shown)\nL7: g"
    )
    assert (core.start_line, core.end_line) == (1, 7)
    assert core.raw == "a\n\nc\nd\ne\n\ng"
    assert [(s.qualname, s.hotspot_ids) for s in core.spans] == [
        ("f", ("h-f",)), ("g", ("h-g",)),
    ]  # fmt: skip
    assert core.spawn_findings == ("line 1: a spawn",)
    assert shown_cli is cli
    assert merged.totals_by_workload == {"w1": 4.0}
    assert notes == []


def test_a_view_adding_nothing_leaves_the_shared_documents_as_they_are() -> None:
    shared = CodeContext(documents=(_doc("pkg/core.py", {1: "a", 2: "b"}),))
    view = CodeContext(documents=(_doc("pkg/core.py", {2: "b"}),))
    merged = review_context(shared, [view], cap=1, notes=[])
    assert merged.documents == shared.documents
    assert merged.documents[0] is shared.documents[0]


def test_view_lines_past_the_reviewers_cap_are_left_out_and_noted() -> None:
    """
    GIVEN a cap that holds one view document's extra bytes but not a second
    WHEN merged
    THEN the first is added, the second left out and named in a note
    """
    shared = CodeContext(documents=(_doc("pkg/core.py", {1: "a"}),))
    small = _doc("pkg/cli.py", {1: "x"})
    big = _doc("pkg/big.py", {1: "y" * 100})
    notes: list[str] = []
    merged = review_context(
        shared, [CodeContext(documents=(small, big))],
        cap=len(small.rendered.encode()) + 10, notes=notes,
    )  # fmt: skip
    assert [d.path for d in merged.documents] == ["pkg/core.py", "pkg/cli.py"]
    assert _noted(notes, "1 view document(s) not shown to the reviewer",
                  "pkg/big.py", "limit")  # fmt: skip
