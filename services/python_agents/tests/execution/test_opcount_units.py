"""Per-unit counts (emergence round 1, S1): the opcount shim's OUT v2.

A counted run given units (``--unit PATH::FUNCTION``, at most ``MAX_UNITS``)
writes version 2: the same two totals as version 1 (so the op-count judge's
input is unchanged) plus, per unit, its own calls, the calls its frames made
(cProfile's caller edges) and its top callees by edge, C methods included,
so ``re.Pattern.match`` is attributed to the function that called it.
Without units the shim writes version 1 byte for byte. ``parse_counts``
reads both strictly; ``count_workload`` turns the units into
``unit_calls`` rows, never ``op_calls`` rows (judge R4: the frozen shadow
judge sums every ``op_calls`` row). Fakes: ``FakeRun`` (``test_opcount_measure``)
stands for ``procrun.run_once``; the subprocess tests run the real shim on
the engine's interpreter and on python3.11 (CI's) when installed.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from autonomous_ai_agents.common.models import Workload
from autonomous_ai_agents.execution import _opcount_shim
from autonomous_ai_agents.execution.measure import (
    CALLEE_KEY,
    METRIC_OP_CALLS,
    METRIC_UNIT_CALLS,
    OPCOUNT_NAME,
    OPCOUNT_SHIM,
    OUT_CALLS_KEY,
    UNIT_KEY,
    CountFormatError,
    OpCounts,
    Phase,
    UnitCount,
    count_workload,
    is_unit,
    parse_counts,
)
from autonomous_ai_agents.execution.procrun import OutputCaps, RunSample
from autonomous_ai_agents.execution.sandbox import SandboxPolicy

OWN = _opcount_shim.__file__
MATCH = "<method 'match' of 're.Pattern' objects>"
LEN = "<built-in method builtins.len>"
PY = "/usr/bin/python3"
CAPS = OutputCaps(max_output_bytes=1 << 20, head_bytes=16, stderr_tail_bytes=4096)


@dataclass
class FakeRun:
    """``run_once`` (as ``test_opcount_measure``'s): records each launch and
    leaves ``write`` in the shim's OUT."""

    write: bytes = b'{"version": 1, "python_calls": 70, "c_calls": 30}'
    calls: list[tuple[str, ...]] = field(default_factory=list)

    def __call__(
        self, argv: Sequence[str], cwd: Path, env: Mapping[str, str],
        sandbox: SandboxPolicy, timeout_s: float, caps: OutputCaps, *,
        fresh_dirs: Sequence[Path] = (),
    ) -> RunSample:  # fmt: skip
        self.calls.append(tuple(argv))
        Path(argv[argv.index(str(OPCOUNT_SHIM)) + 1]).write_bytes(self.write)
        return RunSample(1, 0.1, 0.0, 1 << 20, 0, True, False, "1" * 64, b"", 0, b"", ())  # fmt: skip


@pytest.fixture
def area(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = Path(os.path.realpath(tmp_path))
    dirs = (root / "wt", root / "scratch", root / "probe")
    for path in dirs:
        path.mkdir()
    return dirs


def phase_of(area: tuple[Path, Path, Path], run: FakeRun) -> Phase:
    wt, scratch, probe = area
    policy = SandboxPolicy(network="off", fs="off", writable=(wt, scratch), probe_dir=probe, platform=sys.platform)  # fmt: skip
    env = {"PATH": os.defpath, "PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1"}
    return Phase(policy, env, lambda: None, CAPS, run, ())


def workload() -> Workload:
    return Workload(project_id="p1", name="bench", command=(PY, "-O", "bench.py", "7"),
                    timeout_s=40.0, working_dir="sub")  # fmt: skip


Stats = dict[tuple[str, int, str], tuple[int, int, float, float, object]]


def stats() -> Stats:
    lex = ("/wt/pkg/lexer.py", 10, "get_tokens")
    other = ("/wt/pkg/other.py", 3, "get_tokens")  # same name, another file
    helper = ("/wt/pkg/lexer.py", 40, "helper")
    return {
        lex: (2, 3, 0.5, 0.9, {("/wt/pkg/main.py", 1, "<module>"): (3, 2, 0.5, 0.9)}),
        other: (1, 1, 0.1, 0.1, {}),
        helper: (5, 7, 0.1, 0.1, {lex: (6, 5, 0.1, 0.1), other: (1, 1, 0.0, 0.0)}),
        ("~", 0, MATCH): (
            40,
            40,
            0.2,
            0.2,
            {lex: (30, 30, 0.1, 0.1), helper: (10, 10, 0.1, 0.1)},
        ),  # fmt: skip
        ("~", 0, LEN): (9, 9, 0.0, 0.0, {lex: (9, 9, 0.0, 0.0)}),
        (OWN, 5, "main"): (1, 1, 0.0, 0.0, {lex: (99, 99, 0.0, 0.0)}),
    }


# ---------------------------------------------------------------------------
# Encoding, in process
# ---------------------------------------------------------------------------


def test_without_units_the_document_is_version_1_byte_for_byte() -> None:
    plain = _opcount_shim.encode(stats(), OWN)

    assert plain == _opcount_shim.encode(stats(), OWN, ())
    assert plain == b'{"version": 1, "python_calls": 11, "c_calls": 49}'


def test_a_unit_counts_its_calls_its_caller_edges_and_its_top_callees() -> None:
    """
    GIVEN stats where ``pkg/lexer.py::get_tokens`` calls ``helper`` 6 times,
        ``re.Pattern.match`` 30 times and ``len`` 9 times, a same-named
        function in another file, and the shim's own frame calling it
    WHEN it is encoded with that unit and one that matches nothing
    THEN version 2 keeps the totals, the unit holds its own 3 calls, 45
        calls made from its frames and its callees by edge (most first),
        never another file's function nor the shim's frames
    """
    doc = json.loads(
        _opcount_shim.encode(stats(), OWN, ("pkg/lexer.py::get_tokens", "x.py::nope"))
    )

    assert list(doc) == list(_opcount_shim.UNITS_DOC_KEYS)
    assert (doc["version"], doc["python_calls"], doc["c_calls"]) == (2, 11, 49)
    found, none = doc["units"]
    assert list(found) == list(_opcount_shim.UNIT_KEYS)
    assert found == {"unit": "pkg/lexer.py::get_tokens", "calls": 3, "out": 45,
                     "callees": [[MATCH, 30], [LEN, 9], ["helper", 6]]}  # fmt: skip
    assert none == {"unit": "x.py::nope", "calls": 0, "out": 0, "callees": []}


def test_a_unit_named_by_its_whole_path_and_the_top_callees_are_capped() -> None:
    many: Stats = {("/wt/a.py", 1, "f"): (1, 1, 0.0, 0.0, {})}
    for i in range(8):
        many[("~", 0, f"<c{i}>")] = (i + 1, i + 1, 0.0, 0.0, {("/wt/a.py", 1, "f"): (i + 1, i + 1, 0.0, 0.0)})  # fmt: skip

    [unit] = json.loads(_opcount_shim.encode(many, OWN, ("/wt/a.py::f",)))["units"]

    assert unit["out"] == 36 and len(unit["callees"]) == _opcount_shim.MAX_CALLEES == 5
    assert unit["callees"][0] == ["<c7>", 8]


def test_units_past_the_cap_are_dropped_and_long_names_cut() -> None:
    long = "n" * 500
    big: Stats = {("/wt/a.py", 1, "f"): (1, 1, 0.0, 0.0, {}),
                  ("~", 0, long): (1, 1, 0.0, 0.0, {("/wt/a.py", 1, "f"): (1, 1, 0.0, 0.0)})}  # fmt: skip
    units = tuple(f"a.py::f{'x' * i}" for i in range(6))

    doc = json.loads(_opcount_shim.encode(big, OWN, ("a.py::f", *units)))

    assert len(doc["units"]) == _opcount_shim.MAX_UNITS == 4
    assert doc["units"][0]["callees"] == [["n" * _opcount_shim.MAX_NAME_CHARS, 1]]


def test_a_document_over_the_cap_drops_every_callee_list_and_stays_under_it() -> None:
    """Workload-controlled names (non-ASCII escapes cost six bytes a
    character) cannot push the document past its cap: the callee lists go."""
    wide: Stats = {("/wt/a.py", 1, "f"): (1, 1, 0.0, 0.0, {})}
    for i in range(5):
        wide[("/wt/b.py", i, f"{i}" + "é" * 200)] = (1, 1, 0.0, 0.0, {("/wt/a.py", 1, "f"): (1, 1, 0.0, 0.0)})  # fmt: skip

    data = _opcount_shim.encode(wide, OWN, ("a.py::f",) * 4)

    assert len(data) <= _opcount_shim.MAX_DOC_BYTES
    doc = json.loads(data)
    assert [u["callees"] for u in doc["units"]] == [[]] * 4
    assert [u["out"] for u in doc["units"]] == [5] * 4


# ---------------------------------------------------------------------------
# The shim's usage
# ---------------------------------------------------------------------------

PROBE = """import re

PAT = re.compile("a")


def lex(text):
    out = []
    for i in range(len(text)):  # a loop: before 3.12 a comprehension is a frame
        out.append(PAT.match(text, i))
    return out


def run():
    for _ in range(4):
        lex("abcabc")
    PAT.match("a")


run()
"""


def test_the_shim_counts_the_units_it_is_given_in_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "argv", ["pytest"])
    monkeypatch.setattr(sys, "path", list(sys.path))
    script = tmp_path / "bench.py"
    script.write_text(PROBE)
    out = tmp_path / "out.json"

    _opcount_shim.main(
        ["shim", str(out), "--unit", "bench.py::lex", "--unit", "bench.py::run",
         "script", str(script)], safe_path=False,
    )  # fmt: skip

    counts = parse_counts(out.read_bytes())
    lex, run = counts.units
    assert (lex.unit, lex.calls) == ("bench.py::lex", 4)
    assert dict(lex.callees)[MATCH] == 24  # 4 lexings x 6 positions, not run's 1
    assert (run.calls, dict(run.callees)["lex"], dict(run.callees)[MATCH]) == (1, 4, 1)


@pytest.mark.parametrize(
    "argv",
    [["shim", "/o.json", "--unit"], ["shim", "/o.json", "--unit", "a.py::f"],
     ["shim", "/o.json", "--unit", "a.py::f", "eval", "x"]],
)  # fmt: skip
def test_the_shim_refuses_a_unit_with_no_target(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as stopped:
        _opcount_shim.main(argv)

    assert str(stopped.value.code).startswith("usage: _opcount_shim.py OUT [--unit")


# ---------------------------------------------------------------------------
# The real shim, as a subprocess (the engine's interpreter and CI's 3.11)
# ---------------------------------------------------------------------------

PY311 = shutil.which("python3.11") or (
    "/root/.local/share/uv/python/cpython-3.11-linux-x86_64-gnu/bin/python3.11"
)
INTERPRETERS = [
    pytest.param(sys.executable, id="engine-python"),
    pytest.param(PY311, id="python3.11",
                 marks=pytest.mark.skipif(not os.path.exists(PY311), reason="no 3.11")),
]  # fmt: skip


def shimmed(python: str, script: Path, out: Path, *units: str) -> OpCounts:
    flags = [x for u in units for x in ("--unit", u)]
    env = {"PATH": os.defpath, "PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1"}
    subprocess.run([python, "-I", str(OPCOUNT_SHIM), str(out), *flags, "script", str(script)],
                   cwd=script.parent, env=env, capture_output=True, timeout=120, check=True)  # fmt: skip
    return parse_counts(out.read_bytes())


@pytest.mark.parametrize("python", INTERPRETERS)
def test_units_change_no_total_and_attribute_pooled_c_calls_to_their_caller(
    tmp_path: Path, python: str
) -> None:
    """
    GIVEN a workload whose ``lex`` matches one compiled pattern 24 times and
        whose ``run`` matches it once more
    WHEN it is counted without units and with ``lex`` and ``run``
    THEN both runs count the same totals, and the 25 pooled
        ``re.Pattern.match`` calls split 24 to ``lex`` and 1 to ``run``
    """
    script = tmp_path / "w" / "bench.py"
    script.parent.mkdir()
    script.write_text(PROBE)

    plain = shimmed(python, script, tmp_path / "a.json")
    units = shimmed(
        python, script, tmp_path / "b.json", "bench.py::lex", "bench.py::run"
    )

    assert (plain.python_calls, plain.c_calls) == (units.python_calls, units.c_calls)
    assert plain.units == () and json.loads((tmp_path / "a.json").read_text())["version"] == 1  # fmt: skip
    lex, run = units.units
    assert (lex.calls, lex.out, dict(lex.callees)[MATCH]) == (4, 4 + 24 + 24, 24)
    assert dict(run.callees)[MATCH] == 1


# ---------------------------------------------------------------------------
# Strict parsing of version 2
# ---------------------------------------------------------------------------


def v2(units: object = None, **top: object) -> bytes:
    one = {"unit": "a.py::f", "calls": 3, "out": 9, "callees": [["g", 6], [MATCH, 3]]}
    doc = {"version": 2, "python_calls": 10, "c_calls": 20,
           "units": [one] if units is None else units, **top}  # fmt: skip
    return json.dumps(doc).encode()


def test_a_version_2_document_reads_with_its_units() -> None:
    counts = parse_counts(v2())

    assert (counts.python_calls, counts.c_calls) == (10, 20)
    assert counts.units == (UnitCount("a.py::f", 3, 9, (("g", 6), (MATCH, 3))),)


UNIT = {"unit": "a.py::f", "calls": 1, "out": 1, "callees": []}
MALFORMED: list[tuple[str, bytes, str]] = [
    ("version 1 with units", v2(version=1), "version must be the integer 2"),
    ("units not a list", v2(units={}), "units must be a list"),
    ("too many units", v2(units=[UNIT] * 5), "at most 4"),
    ("unit not an object", v2(units=[[]]), "exactly unit"),
    ("unit extra key", v2(units=[{**UNIT, "x": 1}]), "exactly unit"),
    ("unit name not text", v2(units=[{**UNIT, "unit": 3}]), "unit name"),
    ("unit name not a unit", v2(units=[{**UNIT, "unit": "f"}]), "unit name"),
    ("negative calls", v2(units=[{**UNIT, "calls": -1}]), "calls"),
    ("bool out", v2(units=[{**UNIT, "out": True}]), "out"),
    ("callees not a list", v2(units=[{**UNIT, "callees": {}}]), "callees"),
    ("too many callees", v2(units=[{**UNIT, "callees": [["g", 1]] * 6}]), "callees"),
    ("callee not a pair", v2(units=[{**UNIT, "callees": [["g"]]}]), "callee"),
    ("callee name not text", v2(units=[{**UNIT, "callees": [[1, 1]]}]), "callee"),
    ("callee name too long", v2(units=[{**UNIT, "callees": [["g" * 97, 1]]}]), "callee"),
    ("callee name unprintable", v2(units=[{**UNIT, "callees": [["g\n", 1]]}]), "callee"),
    ("callee count", v2(units=[{**UNIT, "callees": [["g", 1.5]]}]), "callee"),
]  # fmt: skip


@pytest.mark.parametrize(
    ("payload", "reason"),
    [pytest.param(payload, reason, id=name) for name, payload, reason in MALFORMED],
)
def test_a_malformed_version_2_document_is_refused(payload: bytes, reason: str) -> None:
    with pytest.raises(CountFormatError, match=reason):
        parse_counts(payload)


@pytest.mark.parametrize(
    ("spec", "ok"),
    [("pkg/lexer.py::get_tokens", True), ("a.py::<lambda>", True), ("f", False),
     ("a.py::", False), ("::f", False), ("a b.py::f", False), ("a.py::f::g", False),
     ("a.py::fé", False), ("p" * 300 + "::f", False)],
)  # fmt: skip
def test_what_names_a_unit(spec: str, ok: bool) -> None:
    assert is_unit(spec) is ok


# ---------------------------------------------------------------------------
# The counted run with units
# ---------------------------------------------------------------------------


def test_a_counted_run_with_units_adds_unit_rows_and_leaves_the_op_calls_row(
    area: tuple[Path, Path, Path],
) -> None:
    """
    GIVEN a counted run given two units, whose shim writes version 2
    WHEN it is counted
    THEN the units ride the one launch (``--unit`` flags before the kind),
        the ``op_calls`` row is the one version 1 gives, and each unit gives
        a ``unit_calls`` row (its calls, the calls its frames made) and one
        row per callee edge, all carrying the trial id
    """
    (area[0] / "sub").mkdir()
    one = {"unit": "a.py::f", "calls": 3, "out": 9, "callees": [["g", 6]]}
    two = {"unit": "a.py::h", "calls": 0, "out": 0, "callees": []}
    run = FakeRun(write=v2(units=[one, two], python_calls=70, c_calls=30))
    plain_run = FakeRun()

    bench = workload()
    counted = count_workload(phase_of(area, run), bench, trial_id="t1",
                             units=("a.py::f", "a.py::h"))  # fmt: skip
    plain = count_workload(phase_of(area, plain_run), bench, trial_id="t1")

    [argv] = run.calls
    out = str(area[1] / OPCOUNT_NAME)
    assert argv == (PY, "-O", str(OPCOUNT_SHIM), out, "--unit", "a.py::f",
                    "--unit", "a.py::h", "script", "bench.py", "7")  # fmt: skip
    [op] = [r for r in counted.rows if r.metric == METRIC_OP_CALLS]
    [op_plain] = plain.rows
    assert op.model_dump(exclude={"id", "measured_at"}) == op_plain.model_dump(exclude={"id", "measured_at"})  # fmt: skip
    units = [r for r in counted.rows if r.metric == METRIC_UNIT_CALLS]
    assert [(r.samples, r.hardware.get(UNIT_KEY), r.hardware.get(OUT_CALLS_KEY),
             r.hardware.get(CALLEE_KEY), r.trial_id) for r in units] == [
        ((3.0,), "a.py::f", 9, None, "t1"),
        ((6.0,), "a.py::f", None, "g", "t1"),
        ((0.0,), "a.py::h", 0, None, "t1"),
    ]  # fmt: skip
    assert all(r.stats.unit == "calls" and r.stats.n == 1 for r in units)


def test_a_unit_that_is_not_one_is_refused_before_any_launch(
    area: tuple[Path, Path, Path],
) -> None:
    run = FakeRun()

    with pytest.raises(ValueError, match="not a unit"):
        count_workload(phase_of(area, run), workload(), units=("a.py::f", "x y"))

    assert run.calls == []
