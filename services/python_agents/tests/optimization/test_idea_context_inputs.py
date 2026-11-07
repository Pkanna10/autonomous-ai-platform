"""The input-shape view's protected inputs (G2b; idea-lab spec section 1, G2,
"Protected inputs are shown as a schema only", owner 2026-11-03).

An input file under a protected path (``DEFAULT_PROTECTED_PATTERNS`` plus the
run's ``protected`` and ``read_deny``, the set S0 uses) is shown as its
schema alone: sizes, the detected format, its types and nesting by position,
and distributions. No line, value, key or column name of it reaches the
lane: a lane that saw the benchmark's literal input could specialise for it
and pass every frozen judge. An input outside protected paths keeps its
five-line screened head, byte-identical, beside the same schema. Parsing uses
the standard library only, inside the sample cap; a parse failure fails closed
to the text shape, never to a head. Every reader is a dict fake; nothing runs
git or a model.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence

import pytest

from autonomous_ai_agents.clients.structured import Fence, data_line
from autonomous_ai_agents.common.models import (
    Direction,
    Hotspot,
    Objective,
    ObjectiveKind,
    Project,
    Workload,
)
from autonomous_ai_agents.execution.git import GitError
from autonomous_ai_agents.optimization import idea_context
from autonomous_ai_agents.optimization.idea_context import (
    IdeaReadLimits,
    LaneView,
    ViewSource,
    build_view,
    render_data_block,
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
CORE = "def score(rows):\n    return len(rows)\n"
HOT = Hotspot(
    id="h-score",
    project_id="p1",
    workload_id="w1",
    file_path="pkg/core.py",
    symbol="score",
    line_start=1,
    self_time_s=4.0,
    total_time_s=4.0,
    share=0.4,
)

# The fixtures' literals are words and numbers that appear nowhere else in a
# rendered block, so finding one anywhere is a leak.
CASES: dict[str, object] = {
    "zebrafield": [
        {"quokka": "marmalade", "weight": 98765},
        {"quokka": "tangerine", "weight": -4321.5},
    ],
    "flagvalue": True,
    "nothingness": None,
}
CASES_JSON = json.dumps(CASES, indent=2) + "\n"
TABLE = "pelican,walrus,narwhal\nalbatross,31337,2.718\nbarnacle,27182,-0.577\n"
TEXT = "persimmon quince\nkumquat rambutan durian\n\npersimmon quince\n"


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


def _run(
    inputs: Mapping[str, str],
    *,
    protected: Sequence[str] = (),
    read_deny: Sequence[str] = (),
) -> tuple[LaneView, list[str], str, _Reader]:
    """The input shape view over ``inputs`` (path to text), one workload
    naming each; returns the view, its notes, the rendered block and the
    reader."""
    reader = _Reader({"pkg/core.py": CORE, "bench/run.py": "x = 1\n", **inputs})
    workload = Workload(project_id="p1", name="bench", entrypoint="bench/run.py",
                        command=("python", "bench/run.py", *inputs))  # fmt: skip
    source = ViewSource(
        reader=reader, commit=SHA, hotspots=(HOT,), fence=Fence("f00df00df00df00d"),
        protected=tuple(protected), read_deny=tuple(read_deny),
        limits=IdeaReadLimits(), workloads=(workload,),
    )  # fmt: skip
    notes: list[str] = []
    view = build_view("input_shape", source, notes)
    assert view is not None, notes
    block = render_data_block(
        view.context, project=PROJECT, objective=OBJECTIVE, understanding=None,
        hotspots=(HOT,), fence=source.fence, notes=notes, view="input_shape",
        facts=view.facts,
    )  # fmt: skip
    return view, notes, block, reader


def _facts(view: LaneView, label: str) -> dict[str, dict[str, object]]:
    found: dict[str, dict[str, object]] = {}
    for fact in view.facts:
        head, _, body = fact.partition(": ")
        if head == label:
            value = json.loads(body)
            found[value["path"]] = value
    return found


def _literals(text: str, extra: Iterable[str] = ()) -> list[str]:
    """Every line of ``text`` with a letter or digit in it, and ``extra``."""
    lines = [line.strip().rstrip(",") for line in text.split("\n")]
    return [*(line for line in lines if any(c.isalnum() for c in line)), *extra]


def _assert_no_literal(literals: Iterable[str], *texts: object) -> None:
    shown = "\n".join(str(t) for t in texts)
    leaked = [literal for literal in literals if literal in shown]
    assert leaked == [], f"leaked: {leaked}"


# --------------------------------------------------------------------------
# No literal of a protected input is ever shown
# --------------------------------------------------------------------------


def test_a_protected_json_input_shows_its_schema_and_no_literal() -> None:
    """
    GIVEN a workload naming a JSON input under benchmarks/
    WHEN the input shape view is built and rendered
    THEN no line, key, string or number of it appears in the block, the
        facts or the notes; its size facts are kept, no head is shown, and
        its schema gives the format, the nesting by position and the types
    """
    view, notes, block, _ = _run({"benchmarks/cases.json": CASES_JSON})
    secrets = ["zebrafield", "quokka", "weight", "marmalade", "tangerine",
               "flagvalue", "nothingness", "98765", "4321.5"]  # fmt: skip
    _assert_no_literal(_literals(CASES_JSON, secrets), block, notes, view.facts)
    shown = _facts(view, "input file")["benchmarks/cases.json"]
    assert "head" not in shown
    assert shown["protected"] is True
    assert shown["bytes"] == len(CASES_JSON.encode())
    assert shown["lines"] == CASES_JSON.count("\n")
    schema = _facts(view, "input schema")["benchmarks/cases.json"]
    structure = "object{3}[array<object{2}[str,int]|object{2}[str,float]>,bool,null]"
    types = {"array": 1, "bool": 1, "float": 1, "int": 1, "null": 1, "object": 3,
             "str": 2}  # fmt: skip
    numbers = {"count": 2, "distinct": 2, "negative": 1, "zero": 0, "nonfinite": 0,
               "magnitude": [3, 4]}  # fmt: skip
    assert schema == {
        "path": "benchmarks/cases.json",
        "format": "json",
        "depth": 3,
        "types": types,
        "fields": {"min": 2, "max": 3, "mean": 2.3},
        "array_lengths": {"min": 2, "max": 2, "mean": 2.0},
        "string_lengths": {"min": 9, "max": 9, "mean": 9.0},
        "distinct_strings": 2,
        "numbers": numbers,
        "structure": structure,
        "characters": schema["characters"],
    }
    assert data_line(schema) in block


def test_a_protected_csv_input_shows_per_column_types_and_no_literal() -> None:
    """
    GIVEN a CSV input under tests/ whose first row reads as a header
    WHEN the input shape view is built
    THEN no cell or column name is shown; each column is listed by position
        with its value types, distinct count, lengths and magnitude
    """
    view, notes, block, _ = _run({"tests/data/table.csv": TABLE})
    cells = [c for row in TABLE.split("\n") for c in row.split(",") if c]
    _assert_no_literal(_literals(TABLE, cells), block, notes, view.facts)
    schema = _facts(view, "input schema")["tests/data/table.csv"]
    assert {k: schema[k] for k in ("format", "rows", "columns", "row_width",
                                   "columns_not_listed")} == {  # fmt: skip
        "format": "csv", "rows": 3, "columns": 3,
        "row_width": {"min": 3, "max": 3, "mean": 3.0}, "columns_not_listed": 0,
    }  # fmt: skip
    assert schema["per_column"] == [
        {"position": 1, "types": {"str": 3}, "distinct": 3,
         "lengths": {"min": 7, "max": 9, "mean": 8.0}, "magnitude": None},
        {"position": 2, "types": {"int": 2, "str": 1}, "distinct": 3,
         "lengths": {"min": 5, "max": 6, "mean": 5.3}, "magnitude": [4, 4]},
        {"position": 3, "types": {"float": 2, "str": 1}, "distinct": 3,
         "lengths": {"min": 5, "max": 7, "mean": 6.0}, "magnitude": [-1, 0]},
    ]  # fmt: skip


def test_a_protected_text_input_shows_its_text_shape_and_no_literal() -> None:
    """
    GIVEN a plain-text input under benchmark/
    WHEN the input shape view is built
    THEN no line or word is shown; tokens per line, distinct tokens and
        character classes are
    """
    view, notes, block, _ = _run({"benchmark/words.txt": TEXT})
    _assert_no_literal(_literals(TEXT, TEXT.split()), block, notes, view.facts)
    shown = _facts(view, "input file")["benchmark/words.txt"]
    assert "head" not in shown and shown["distinct_lines"] == 3
    schema = _facts(view, "input schema")["benchmark/words.txt"]
    assert schema == {
        "path": "benchmark/words.txt",
        "format": "text",
        "tokens_per_line": {"min": 0, "max": 3, "mean": 1.8},
        "distinct_tokens": 5,
        "characters": {"letter": sum(c.isalpha() for c in TEXT),
                       "number": 0, "space": sum(c.isspace() for c in TEXT),
                       "punctuation": 0, "symbol": 0, "other": 0},
    }  # fmt: skip


def test_nested_json_gives_its_depth_and_types_by_position() -> None:
    nested = {"a1": {"b2": {"c3": [[1, 2], [3]], "d4": "x"}}, "e5": []}
    view, _, _, _ = _run({"tests/nested.json": json.dumps(nested)})
    schema = _facts(view, "input schema")["tests/nested.json"]
    assert schema["depth"] == 5
    assert schema["structure"] == (
        "object{2}[object{1}[object{2}[array<array<int>>,str]],array<>]"
    )
    assert schema["types"] == {"array": 4, "int": 3, "object": 3, "str": 1}
    assert schema["array_lengths"] == {"min": 0, "max": 2, "mean": 1.2}


def test_a_malformed_protected_json_falls_back_to_the_text_shape() -> None:
    """
    GIVEN a protected .json input that does not parse
    WHEN the input shape view is built
    THEN it fails closed: its text shape, never a head, and a note naming
        the path and the format only
    """
    broken = '{"porcupine": "hedgehog",\n  "armadillo": [1, 2\n'
    view, notes, block, _ = _run({"tests/broken.json": broken})
    _assert_no_literal(_literals(broken, ["porcupine", "hedgehog", "armadillo"]),
                       block, notes, view.facts)  # fmt: skip
    assert "head" not in _facts(view, "input file")["tests/broken.json"]
    schema = _facts(view, "input schema")["tests/broken.json"]
    assert schema["format"] == "text"
    assert "tokens_per_line" in schema and "structure" not in schema
    note = ("view input_shape: tests/broken.json: not read as json (malformed or "
            "cut at the sample cap); its text shape is shown")  # fmt: skip
    assert note in notes


def test_a_path_protected_only_by_the_runs_patterns_is_covered() -> None:
    """
    GIVEN two inputs outside the default protected set: one matched only
        by the run's protected patterns, one only by its read-deny patterns
    WHEN the input shape view is built
    THEN the first is shown as its schema only; the second is never read
        (a frozen quality file), as before
    """
    view, notes, block, reader = _run(
        {"data/golden/cases.json": CASES_JSON, "data/expected.txt": TEXT},
        protected=("data/golden/*",), read_deny=("data/expected.txt",),
    )  # fmt: skip
    _assert_no_literal(_literals(CASES_JSON, ["zebrafield", "marmalade"]),
                       block, notes, view.facts)  # fmt: skip
    _assert_no_literal(_literals(TEXT), block, notes, view.facts)
    assert _facts(view, "input file")["data/golden/cases.json"]["protected"] is True
    assert "data/expected.txt" not in reader.reads
    assert "data/expected.txt" not in _facts(view, "input file")


# --------------------------------------------------------------------------
# An unprotected input keeps its head, byte for byte
# --------------------------------------------------------------------------


def test_an_unprotected_input_keeps_todays_fact_byte_for_byte() -> None:
    """
    GIVEN a text input outside every protected path
    WHEN the input shape view is built
    THEN its input-file fact is today's, byte for byte (golden), with the
        five-line screened head, and the same schema follows it
    """
    view, _, block, _ = _run({"data/words.txt": TEXT + "sk-ant-x\nsixth\nseventh\n"})
    golden = (
        'input file: {"path": "data/words.txt", "bytes": 82, "cut": false, '
        '"lines": 7, "blank_lines": 1, "distinct_lines": 6, "longest_line": 23, '
        '"mean_line": 10.7, "ascii": true, "head": ["persimmon quince", '
        '"kumquat rambutan durian", "", "persimmon quince", '
        '"(line withheld: secret-shaped)"]}'
    )
    files = [f for f in view.facts if f.startswith("input ")]
    assert files[0] == golden
    assert files[1].startswith('input schema: {"path": "data/words.txt", '
                               '"format": "text", ')  # fmt: skip
    assert golden in block


# --------------------------------------------------------------------------
# Formats, caps and fallbacks
# --------------------------------------------------------------------------


def test_json_lines_tsv_and_toml_are_detected() -> None:
    lines = '{"k": 1}\n\n{"k": 2.5, "j": null}\n'
    tsv = "a\tb\n1\t\n"
    toml = 'title = "x"\n[owner]\nborn = 1979-05-27T07:32:00Z\nday = 1979-05-27\n'
    view, notes, _, _ = _run({"tests/r.jsonl": lines, "tests/t.tsv": tsv,
                              "tests/c.toml": toml})  # fmt: skip
    schemas = _facts(view, "input schema")
    jsonl, tsv_schema, toml_schema = (schemas[f"tests/{name}"]
                                      for name in ("r.jsonl", "t.tsv", "c.toml"))  # fmt: skip
    assert (jsonl["format"], jsonl["records"], jsonl["depth"]) == ("jsonl", 2, 1)
    assert jsonl["structure"] == "object{1}[int]|object{2}[float,null]"
    assert tsv_schema["format"] == "tsv"
    assert tsv_schema["per_column"] == [
        {"position": 1, "types": {"int": 1, "str": 1}, "distinct": 2,
         "lengths": {"min": 1, "max": 1, "mean": 1.0}, "magnitude": [0, 0]},
        {"position": 2, "types": {"empty": 1, "str": 1}, "distinct": 2,
         "lengths": {"min": 0, "max": 1, "mean": 0.5}, "magnitude": None},
    ]  # fmt: skip
    assert toml_schema["format"] == "toml"
    assert toml_schema["structure"] == "object{2}[str,object{2}[datetime,date]]"
    assert not [n for n in notes if "not read as" in n]


def test_a_json_text_file_is_sniffed_and_a_failed_sniff_is_silent() -> None:
    view, notes, _, _ = _run({"tests/a.txt": "[1, 0, -0.0]", "tests/b.txt": "[nope"})
    schemas = _facts(view, "input schema")
    assert schemas["tests/a.txt"]["format"] == "json"
    assert schemas["tests/a.txt"]["structure"] == "array<int|float>"
    assert schemas["tests/a.txt"]["numbers"] == {
        "count": 3, "distinct": 2, "negative": 0, "zero": 2, "nonfinite": 0,
        "magnitude": [0, 0],
    }  # fmt: skip
    assert schemas["tests/b.txt"]["format"] == "text"
    assert not [n for n in notes if "not read as" in n]


def test_numbers_without_a_finite_magnitude_and_huge_integers() -> None:
    big = "9" * 400
    view, _, block, _ = _run({"tests/n.json": f"[NaN, Infinity, 0, {big}]"})
    numbers = _facts(view, "input schema")["tests/n.json"]["numbers"]
    assert numbers == {"count": 4, "distinct": 4, "negative": 0, "zero": 1,
                       "nonfinite": 2, "magnitude": [399, 399]}  # fmt: skip
    assert big not in block
    view, _, _, _ = _run({"tests/z.json": '{"q": [0, "x"]}'})
    assert _facts(view, "input schema")["tests/z.json"]["numbers"] == {
        "count": 1, "distinct": 1, "negative": 0, "zero": 1, "nonfinite": 0,
        "magnitude": None,
    }  # fmt: skip
    view, _, _, _ = _run({"tests/s.json": '"only"'})
    schema = _facts(view, "input schema")["tests/s.json"]
    assert (schema["depth"], schema["structure"], schema["numbers"]) == (0, "str", None)
    assert (schema["fields"], schema["array_lengths"]) == (None, None)


def test_signatures_are_capped_in_depth_positions_and_variants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(idea_context, "INPUT_SCHEMA_DEPTH", 2)
    deep = {"a": {"b": {"c": 1}}, "l": [[[1]]]}
    view, _, _, _ = _run({"tests/d.json": json.dumps(deep)})
    schema = _facts(view, "input schema")["tests/d.json"]
    assert schema["structure"] == "object{2}[object{1}[object{...}],array<array<...>>]"
    assert schema["depth"] == 4
    monkeypatch.undo()
    wide = {f"k{i}": i for i in range(idea_context.INPUT_SCHEMA_POSITIONS + 2)}
    mixed = [1, "s", None, True, 2.5]
    view, _, _, _ = _run({"tests/w.json": json.dumps(wide),
                          "tests/m.json": json.dumps(mixed)})  # fmt: skip
    schemas = _facts(view, "input schema")
    positions = ",".join(["int"] * idea_context.INPUT_SCHEMA_POSITIONS)
    count = idea_context.INPUT_SCHEMA_POSITIONS + 2
    assert schemas["tests/w.json"]["structure"] == f"object{{{count}}}[{positions},+2]"
    assert schemas["tests/m.json"]["structure"] == "array<int|str|null|...>"
    long = [{f"f{i}": [{"x": {"y": 1}}] for i in range(8)}]
    view, _, _, _ = _run({"tests/l.json": json.dumps(long)})
    structure = _facts(view, "input schema")["tests/l.json"]["structure"]
    assert isinstance(structure, str) and len(structure) == idea_context.FACT_TEXT_CHARS


def test_a_wide_ragged_csv_lists_at_most_the_column_cap() -> None:
    cap = idea_context.INPUT_SCHEMA_COLUMNS
    header = ",".join(f"h{i}" for i in range(cap + 3))
    table = f"{header}\n1,2\n\n3\n"
    view, _, _, _ = _run({"tests/wide.csv": table})
    schema = _facts(view, "input schema")["tests/wide.csv"]
    assert (schema["columns"], schema["columns_not_listed"]) == (cap + 3, 3)
    assert len(schema["per_column"]) == cap  # type: ignore[arg-type]
    assert schema["row_width"] == {"min": 0, "max": cap + 3, "mean": 3.5}
    assert schema["per_column"][2]["types"] == {"str": 1}  # type: ignore[index]
    view, _, _, _ = _run({"tests/empty.csv": "", "tests/f.csv": "0.0\ninf\n-1e3\n"})
    schemas = _facts(view, "input schema")
    assert schemas["tests/empty.csv"]["per_column"] == []
    assert schemas["tests/f.csv"]["per_column"] == [
        {"position": 1, "types": {"float": 3}, "distinct": 3,
         "lengths": {"min": 3, "max": 4, "mean": 3.3}, "magnitude": [3, 3]},
    ]  # fmt: skip


def test_a_bad_csv_and_cut_inputs_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    GIVEN a CSV with a stray quote, and inputs longer than the sample cap
    WHEN the input shape view is built
    THEN the bad CSV and the cut JSON fall back to the text shape (noted);
        the cut JSON lines and CSV drop their cut last line and still parse
    """
    monkeypatch.setattr(idea_context, "INPUT_SAMPLE_BYTES", 40)
    records = '{"k": 1}\n' * 6
    rows = "a,bc\n" + "1,2\n" * 12
    view, notes, _, _ = _run({
        "tests/bad.csv": 'a,"b\n', "tests/cut.json": json.dumps([1] * 40),
        "tests/cut.jsonl": records, "tests/cut.csv": rows,
    })  # fmt: skip
    schemas = _facts(view, "input schema")
    assert schemas["tests/bad.csv"]["format"] == "text"
    assert schemas["tests/cut.json"]["format"] == "text"
    assert schemas["tests/cut.jsonl"]["records"] == 4  # 40 bytes: 4 whole, 1 cut
    assert schemas["tests/cut.csv"]["rows"] == 9  # the cut 10th row dropped
    assert _facts(view, "input file")["tests/cut.json"]["cut"] is True
    for path, fmt in (("tests/bad.csv", "csv"), ("tests/cut.json", "json")):
        assert any(f"{path}: not read as {fmt}" in n for n in notes)


def test_a_binary_or_unreadable_protected_input_is_named_only() -> None:
    view, _, _, _ = _run({"tests/blob.json": "\0\1\2"})
    assert _facts(view, "input file") == {
        "tests/blob.json": {"path": "tests/blob.json", "kind": "binary"}
    }
    assert _facts(view, "input schema") == {}
