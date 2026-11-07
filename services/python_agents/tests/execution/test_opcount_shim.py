"""The operation-count shim (G6a): counts, the workload left intact, strict parsing.

The shim (``_opcount_shim``) runs in process for coverage and as a real
subprocess on every workload interpreter the host has (CPython 3.8 to 3.14,
each skipped when missing) for what only a fresh interpreter shows: the
counts are deterministic (A/A: the same code in two worktrees gives the same
counts), a change that removes calls counts fewer, and the workload's stdout
and exit status are exactly what it gives without the shim. The engine's
strict parser (``measure.parse_counts``) reads every document a workload
could write.
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from autonomous_ai_agents.execution import _opcount_shim
from autonomous_ai_agents.execution.measure import (
    OPCOUNT_SHIM,
    CountFormatError,
    OpCounts,
    parse_counts,
)

OWN = _opcount_shim.__file__

Stats = dict[tuple[str, int, str], tuple[int, int, float, float, object]]


# ---------------------------------------------------------------------------
# The shim, in process
# ---------------------------------------------------------------------------


def test_encode_sums_python_and_c_calls_without_the_shims_own_frames() -> None:
    """
    GIVEN cProfile stats with Python frames, C builtins (file ``~``), frozen
        importlib frames and one frame of the shim itself
    WHEN they are encoded
    THEN every call counts once, by total calls (recursion included), C calls
        apart, and the shim's own frame not at all
    """
    stats: Stats = {
        ("/wt/pkg/core.py", 6, "hot"): (2, 7, 0.75, 0.8, {}),
        ("/wt/pkg/main.py", 1, "<module>"): (1, 1, 0.05, 0.9, {}),
        ("<frozen importlib._bootstrap>", 1, "_load"): (2, 2, 0.04, 0.05, {}),
        ("~", 0, "<built-in method builtins.len>"): (5, 5, 0.1, 0.1, {}),
        ("~", 0, "<method 'append' of 'list' objects>"): (3, 30, 0.1, 0.1, {}),
        (OWN, 10, "run"): (1, 1000, 0.5, 1.0, {}),
    }

    doc = json.loads(_opcount_shim.encode(stats, OWN))

    assert doc == {"version": 1, "python_calls": 10, "c_calls": 35}
    assert list(doc) == list(_opcount_shim.DOC_KEYS)


PROBE = """import json, pathlib, sys


def hot(n):
    return [abs(i) for i in range(n)]


hot(300)
seen = {"name": __name__, "argv": sys.argv}
pathlib.Path(__file__).with_name("seen.json").write_text(json.dumps(seen))
"""


def test_the_shim_runs_a_script_as_main_counts_it_and_keeps_its_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    GIVEN a script that records what it sees and then exits with status 3
    WHEN the shim runs it in process
    THEN it ran as __main__ with its own argv, OUT was written anyway (the
        script's 300 ``abs`` calls among the C calls) and SystemExit(3)
        passed through
    """
    monkeypatch.setattr(sys, "argv", ["pytest"])
    monkeypatch.setattr(sys, "path", list(sys.path))
    script = tmp_path / "bench.py"
    script.write_text(PROBE + "raise SystemExit(3)\n")
    out = tmp_path / "out.json"

    with pytest.raises(SystemExit) as stopped:
        _opcount_shim.main(
            ["shim", str(out), "script", str(script), "a1"], safe_path=False
        )

    assert stopped.value.code == 3
    seen = json.loads((tmp_path / "seen.json").read_text())
    assert (seen["name"], seen["argv"]) == ("__main__", [str(script), "a1"])
    counts = parse_counts(out.read_bytes())
    assert counts.c_calls >= 300 and counts.python_calls >= 2
    assert counts.total == counts.python_calls + counts.c_calls


def test_the_shim_runs_a_module_from_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    name = f"opcountprobe_{os.getpid()}_{id(tmp_path)}"
    (tmp_path / f"{name}.py").write_text(PROBE)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["pytest"])
    monkeypatch.setattr(sys, "path", list(sys.path))
    out = tmp_path / "out.json"

    try:
        _opcount_shim.main(["shim", str(out), "module", name, "x"], safe_path=False)
    finally:
        sys.modules.pop(name, None)

    seen = json.loads((tmp_path / "seen.json").read_text())
    assert seen["name"] == "__main__"
    assert seen["argv"] == [str(Path(os.path.realpath(tmp_path)) / f"{name}.py"), "x"]
    assert sys.path[0] == os.path.realpath(tmp_path)
    assert parse_counts(out.read_bytes()).c_calls >= 300


def test_a_directory_target_is_left_to_runpy_as_under_cpython(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A directory with ``__main__.py`` is put on ``sys.path`` by ``runpy``
    itself, never its parent by the shim (CPython's ``python DIR``)."""
    app = tmp_path / "app"
    app.mkdir()
    (app / "__main__.py").write_text(PROBE)
    before = list(sys.path)
    monkeypatch.setattr(sys, "argv", ["pytest"])
    monkeypatch.setattr(sys, "path", list(sys.path))

    _opcount_shim.main(
        ["shim", str(tmp_path / "o.json"), "script", str(app)], safe_path=False
    )

    assert sys.path == before
    assert json.loads((app / "seen.json").read_text())["name"] == "__main__"
    assert parse_counts((tmp_path / "o.json").read_bytes()).c_calls >= 300


def test_under_safe_path_the_shim_adds_nothing_to_sys_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = tmp_path / "bench.py"
    script.write_text(PROBE)
    before = list(sys.path)
    monkeypatch.setattr(sys, "argv", ["pytest"])
    monkeypatch.setattr(sys, "path", list(sys.path))

    _opcount_shim.main(
        ["shim", str(tmp_path / "o.json"), "script", str(script)], safe_path=True
    )

    assert sys.path == before


@pytest.mark.parametrize(
    ("version", "problem"),
    [
        ((3, 7, 17), "needs Python 3.8 or later; this is Python 3.7"),
        ((3, 8, 0), None),
        ((3, 14, 0), None),
    ],
)
def test_the_shim_names_an_interpreter_older_than_its_floor(
    version: tuple[int, int, int], problem: str | None
) -> None:
    found = _opcount_shim.interpreter_problem(version)

    if problem is None:
        assert found is None
    else:
        assert found is not None and problem in found


@pytest.mark.parametrize(
    ("flags", "expected"),
    [
        (SimpleNamespace(safe_path=True, isolated=0), True),
        (SimpleNamespace(safe_path=False, isolated=1), False),
        (SimpleNamespace(isolated=1), True),
        (SimpleNamespace(isolated=0), False),
    ],
)
def test_safe_path_falls_back_to_isolated_mode_before_python_3_11(
    flags: SimpleNamespace, expected: bool
) -> None:
    assert _opcount_shim.path_is_safe(flags) is expected


def test_the_shim_parses_with_the_oldest_supported_grammar() -> None:
    source = Path(OWN).read_text()

    ast.parse(source, feature_version=_opcount_shim.MIN_PYTHON[:2])
    assert _opcount_shim.MIN_PYTHON == (3, 8)
    assert "from __future__ import annotations" in source
    assert OPCOUNT_SHIM == Path(OWN).resolve()


@pytest.mark.parametrize(
    "argv",
    [["shim"], ["shim", "/o.json", "script"], ["shim", "/o.json", "eval", "x"]],
)
def test_the_shim_refuses_any_other_usage(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as stopped:
        _opcount_shim.main(argv)

    assert isinstance(stopped.value.code, str)
    assert stopped.value.code.startswith("usage: _opcount_shim.py OUT")


# ---------------------------------------------------------------------------
# The shim, as a real subprocess on every workload interpreter
# ---------------------------------------------------------------------------

NAMES = [f"python3.{minor}" for minor in range(8, 15)]
FOUND = {name: shutil.which(name) for name in NAMES}
INTERPRETERS = [
    pytest.param(sys.executable, id="engine-python"),
    *(
        pytest.param(
            path or name,
            id=name,
            marks=pytest.mark.skipif(path is None, reason=f"{name} not installed"),
        )
        for name, path in FOUND.items()
    ),
]

WORKLOAD = """import json, sys


def step(i):
    return {"i": i, "sq": i * i, "s": str(i)}


def run(n):
    rows = [step(i) for i in range(n)]
    {CHANGE}
    return rows


rows = run(int(sys.argv[1]))
sys.stdout.write(json.dumps(rows[-3:]) + "\\n")
sys.stderr.write("done\\n")
raise SystemExit(5)
"""
EXTRA_CALLS = "for r in rows: len(r)"
"""The base's extra work: one ``len`` call per row (a C function; a loop, not
a comprehension, which is a call of its own before 3.12), output unchanged."""
NO_EXTRA = "pass"


def plant(where: Path, change: str) -> Path:
    where.mkdir(parents=True)
    script = where / "bench.py"
    script.write_text(WORKLOAD.replace("{CHANGE}", change))
    return script


def run(python: str, argv: list[str], cwd: Path) -> subprocess.CompletedProcess[bytes]:
    env = {"PATH": os.defpath, "PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run(
        [python, *argv], cwd=cwd, env=env, capture_output=True, timeout=120, check=False
    )


def counted(python: str, script: Path, out: Path) -> tuple[OpCounts, bytes, int]:
    done = run(python, [str(OPCOUNT_SHIM), str(out), "script", str(script), "400"], script.parent)  # fmt: skip
    return parse_counts(out.read_bytes()), done.stdout, done.returncode


@pytest.mark.parametrize("python", INTERPRETERS)
def test_identical_code_counts_identically_and_fewer_calls_count_fewer(
    tmp_path: Path, python: str
) -> None:
    """
    GIVEN the same workload in two worktrees of different names (A/A) and a
        trial that drops one call per row
    WHEN each runs once under the shim in a fresh interpreter
    THEN the A/A counts are identical, call for call, and the trial counts
        exactly 400 C calls fewer (the dropped ``len`` calls), Python calls
        unchanged
    """
    base = plant(tmp_path / "trial-abc", EXTRA_CALLS)
    twin = plant(tmp_path / "twin-trial-abc", EXTRA_CALLS)
    trial = plant(tmp_path / "trial-xyz", NO_EXTRA)

    a, _, _ = counted(python, base, tmp_path / "a.json")
    a2, _, _ = counted(python, twin, tmp_path / "a2.json")
    b, _, _ = counted(python, trial, tmp_path / "b.json")

    assert a2 == a
    assert a.python_calls > 400 and a.c_calls > 400
    assert (a.python_calls - b.python_calls, a.c_calls - b.c_calls) == (0, 400)
    assert b.total < a.total


@pytest.mark.parametrize("python", INTERPRETERS)
def test_the_shim_keeps_the_workloads_stdout_and_exit_status(
    tmp_path: Path, python: str
) -> None:
    """
    GIVEN a workload that writes stdout and stderr and exits with status 5
    WHEN it runs plain and under the shim
    THEN stdout is byte for byte the same, the exit status is 5 both times,
        and the shim adds nothing to stderr
    """
    script = plant(tmp_path / "w", EXTRA_CALLS)

    plain = run(python, [str(script), "400"], script.parent)
    counts, stdout, status = counted(python, script, tmp_path / "o.json")
    shimmed = run(python, [str(OPCOUNT_SHIM), str(tmp_path / "p.json"), "script", str(script), "400"], script.parent)  # fmt: skip

    assert plain.returncode == status == shimmed.returncode == 5
    assert plain.stdout == stdout == shimmed.stdout
    assert plain.stdout.startswith(b'[{"i": 397')
    assert plain.stderr == shimmed.stderr == b"done\n"
    assert counts.total > 0


# ---------------------------------------------------------------------------
# Strict parsing
# ---------------------------------------------------------------------------


def doc(**fields: object) -> bytes:
    base: dict[str, object] = {"version": 1, "python_calls": 10, "c_calls": 20}
    return json.dumps({**base, **fields}).encode()


MALFORMED: list[tuple[str, bytes, str]] = [
    ("not ASCII", doc() + b"\xff", "ASCII"),
    ("not JSON", b"counts", "not valid JSON"),
    ("trailing data", doc() + b"{}", "not valid JSON"),
    ("deep nesting", b"[" * 4000, "not valid JSON"),
    ("long integer", doc(c_calls=10**4000), "c_calls"),
    ("NaN", b'{"version": 1, "python_calls": NaN, "c_calls": 1}', "NaN"),
    ("repeated key", b'{"version": 1, "version": 1, "python_calls": 1, "c_calls": 1}', "repeated"),
    ("a list", b"[]", "exactly version"),
    ("missing key", b'{"version": 1, "python_calls": 1}', "exactly version"),
    ("extra key", doc(entries=[]), "exactly version"),
    ("version 2", doc(version=2), "version"),
    ("version text", doc(version="1"), "version"),
    ("version bool", doc(version=True), "version"),
    ("negative calls", doc(python_calls=-1), "python_calls"),
    ("float calls", doc(c_calls=1.0), "c_calls"),
    ("bool calls", doc(c_calls=True), "c_calls"),
    ("too many calls", doc(python_calls=2**53 + 1), "python_calls"),
    ("text calls", doc(python_calls="9"), "python_calls"),
]  # fmt: skip


@pytest.mark.parametrize(
    ("payload", "reason"),
    [pytest.param(payload, reason, id=name) for name, payload, reason in MALFORMED],
)
def test_a_malformed_count_document_is_refused(payload: bytes, reason: str) -> None:
    with pytest.raises(CountFormatError, match=reason):
        parse_counts(payload)


def test_a_count_document_larger_than_the_cap_is_refused() -> None:
    padded = doc()[:-1] + b" " * _opcount_shim.MAX_DOC_BYTES + b"}"

    with pytest.raises(CountFormatError, match="larger than"):
        parse_counts(padded)


def test_a_well_formed_count_document_parses() -> None:
    counts = parse_counts(doc(python_calls=0, c_calls=2**53))

    assert counts == OpCounts(python_calls=0, c_calls=2**53)
    assert counts.total == 2**53
