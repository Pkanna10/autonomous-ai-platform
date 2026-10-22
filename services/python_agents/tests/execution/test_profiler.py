"""The cProfile profiler: the shim, strict parsing, path mapping, skips, F0/F1, cleanup.

The shim (``_profile_shim``) runs in process for coverage and as a real
subprocess (also on Python 3.11 when it is installed) for its ``sys.path``
handling. The profiler runs on an injected ``run_once`` double and a git
double, so every launch, reset, fingerprint and cleanup step and their order
are asserted exactly, and every hostile profile document is written exactly
as a workload could write it. Real tests then profile the ``dedupe_repo``
fixture through the real launcher and real git: unsandboxed everywhere, and
under ``unshare`` plus Landlock on Linux (skipped unless the host can
sandbox; ``REQUIRE_NETWORK_SANDBOX=1`` or ``REQUIRE_FS_SANDBOX=1`` turns the
skip into a failure, as in ``test_procrun.py``).
"""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import NamedTuple

import pytest

from autonomous_ai_agents.common.config import IsolationMode, settings
from autonomous_ai_agents.common.errors import EngineError, RepoTamperedError
from autonomous_ai_agents.common.models import Hotspot, Project, Workload
from autonomous_ai_agents.execution import _profile_shim, launcher, profiler
from autonomous_ai_agents.execution.git import GitError
from autonomous_ai_agents.execution.procrun import (
    OutputCaps,
    RunFailure,
    RunSample,
    run_once,
)
from autonomous_ai_agents.execution.profiler import (
    GUARD_SKIPPED,
    MAX_SYMBOL_CHARS,
    PROFILE_NAME,
    PROFILE_TIMEOUT_FACTOR,
    SHIM_PATH,
    CProfiler,
    NotProfiledError,
    ProfileDoc,
    ProfileEntry,
    ProfileFormatError,
    checkout_file,
    clean_symbol,
    parse_profile,
    profiled_argv,
    project_file,
)
from autonomous_ai_agents.execution.protocols import (
    Profiler,
    ProfileResult,
    WorktreeHandle,
)
from autonomous_ai_agents.execution.sandbox import UNSHARE_ARGV, SandboxPolicy

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
DEDUPE_REPO = FIXTURES / "dedupe_repo"
PY = "/usr/bin/python3"
RUN_ID = "run1"
COMMIT = "c" * 40
OWN = _profile_shim.__file__
OUT = Path("/scratch/profile.json")
linux_only = pytest.mark.skipif(sys.platform != "linux", reason="Linux sandbox")


def entry(
    file: str,
    function: str = "work",
    *,
    line: int = 3,
    self_s: float = 0.5,
    cumulative_s: float = 0.6,
    primitive_calls: int = 1,
    total_calls: int = 1,
) -> dict[str, object]:
    return {
        "file": file,
        "line": line,
        "function": function,
        "primitive_calls": primitive_calls,
        "total_calls": total_calls,
        "self_s": self_s,
        "cumulative_s": cumulative_s,
    }


def document(*entries: Mapping[str, object], total_s: float = 1.0) -> bytes:
    return json.dumps(
        {"version": 1, "total_s": total_s, "entries": list(entries)}
    ).encode()


# ---------------------------------------------------------------------------
# The shim, in process
# ---------------------------------------------------------------------------

Stats = dict[tuple[str, int, str], tuple[int, int, float, float, object]]

STATS: Stats = {
    ("/wt/pkg/main.py", 1, "<module>"): (1, 1, 0.05, 0.9, {}),
    ("/wt/pkg/core.py", 6, "hot"): (2, 7, 0.75, 0.8, {}),
    ("~", 0, "<built-in method builtins.len>"): (5, 5, 0.1, 0.1, {}),
    ("<frozen importlib._bootstrap>", 1, "_load"): (2, 2, 0.04, 0.05, {}),
    (OWN, 10, "run"): (1, 1, 0.5, 1.0, {}),
    ("/wt/pkg/neg.py", 2, "neg"): (1, 1, -1e-9, -2e-9, {}),
}


def test_the_shim_lists_real_files_by_self_time_and_totals_everything_else() -> None:
    """
    GIVEN raw cProfile stats with a builtin, frozen code, the shim's own
        frame and a slightly negative timing
    WHEN the shim encodes them
    THEN it lists only real files, by self time, clamps negatives to zero,
        and its total counts every frame but its own
    """
    doc = json.loads(_profile_shim.encode(STATS, OWN))

    assert set(doc) == {"version", "total_s", "entries"}
    assert doc["version"] == _profile_shim.FORMAT_VERSION == 1
    assert doc["total_s"] == pytest.approx(0.94)
    assert doc["entries"] == [
        entry("/wt/pkg/core.py", "hot", line=6, self_s=0.75, cumulative_s=0.8,
              primitive_calls=2, total_calls=7),
        entry("/wt/pkg/main.py", "<module>", line=1, self_s=0.05, cumulative_s=0.9),
        entry("/wt/pkg/neg.py", "neg", line=2, self_s=0.0, cumulative_s=0.0),
    ]  # fmt: skip
    assert [list(e) for e in doc["entries"]] == [list(_profile_shim.ENTRY_KEYS)] * 3


def test_the_shim_output_round_trips_through_the_engine_parser() -> None:
    parsed = parse_profile(_profile_shim.encode(STATS, OWN))

    assert parsed.total_s == pytest.approx(0.94)
    assert parsed.entries[0] == ProfileEntry(
        file="/wt/pkg/core.py",
        line=6,
        function="hot",
        primitive_calls=2,
        total_calls=7,
        self_s=0.75,
        cumulative_s=0.8,
    )


def test_the_shim_caps_entries_names_paths_and_its_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    GIVEN more entries than the cap, a long function name, a path longer
        than the cap and non-ASCII paths that escape to six bytes a character
    WHEN the shim encodes them under small caps
    THEN it keeps the slowest entries that fit, truncates the name, skips
        the long path (its time still counts), and writes ASCII JSON no
        larger than the cap that decodes to the original names
    """
    monkeypatch.setattr(_profile_shim, "MAX_ENTRIES", 3)
    monkeypatch.setattr(_profile_shim, "MAX_FUNCTION_CHARS", 5)
    monkeypatch.setattr(_profile_shim, "MAX_FILE_CHARS", 12)
    stats: Stats = {
        (f"/w/{n}.py", n, "function"): (1, 1, n / 10, n / 10, {}) for n in range(5)
    }
    stats[("/w/" + "x" * 20 + ".py", 1, "f")] = (1, 1, 9.0, 9.0, {})

    doc = json.loads(_profile_shim.encode(stats, OWN))

    assert [e["file"] for e in doc["entries"]] == ["/w/4.py", "/w/3.py", "/w/2.py"]
    assert {e["function"] for e in doc["entries"]} == {"funct"}
    assert doc["total_s"] == pytest.approx(10.0)

    monkeypatch.setattr(_profile_shim, "MAX_ENTRIES", 1000)
    monkeypatch.setattr(_profile_shim, "MAX_FILE_CHARS", 4096)
    monkeypatch.setattr(_profile_shim, "MAX_DOC_BYTES", 3000)
    wide: Stats = {
        (f"/w/\u00e9{n}" + "\u00e9" * 60, 1, "f"): (1, 1, 1.0 + n, 1.0, {})
        for n in range(50)
    }

    data = _profile_shim.encode(wide, OWN)

    assert data.isascii() and len(data) <= 3000
    kept = json.loads(data)["entries"]
    assert 0 < len(kept) < 50
    assert kept[0]["file"] == "/w/\u00e949" + "\u00e9" * 60


class Seen(NamedTuple):
    name: str
    argv: list[str]
    path: list[str]


PROBE = """import json, pathlib, sys


def hot():
    return sum(i * i for i in range(3000))


hot()
seen = {"name": __name__, "argv": sys.argv, "path": sys.path}
pathlib.Path(__file__).with_name("seen.json").write_text(json.dumps(seen))
"""


def read_seen(where: Path) -> Seen:
    raw = json.loads((where / "seen.json").read_text())
    return Seen(raw["name"], raw["argv"], raw["path"])


@pytest.fixture
def isolated_sys(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """``sys.argv`` and ``sys.path`` as copies the test may change."""
    monkeypatch.setattr(sys, "argv", ["pytest"])
    monkeypatch.setattr(sys, "path", list(sys.path))
    return list(sys.path)


@pytest.fixture
def package(tmp_path: Path) -> Iterator[str]:
    """A uniquely named package with ``mod`` (the probe) in ``tmp_path``."""
    name = f"shimprobe_{uuid.uuid4().hex[:12]}"
    (tmp_path / name).mkdir()
    (tmp_path / name / "__init__.py").write_text("")
    (tmp_path / name / "mod.py").write_text(PROBE)
    yield name
    for module in [m for m in sys.modules if m.split(".")[0] == name]:
        del sys.modules[module]


@pytest.mark.usefixtures("isolated_sys")
def test_the_shim_runs_a_script_as_main_and_keeps_its_exit_code(
    tmp_path: Path,
) -> None:
    """
    GIVEN a script that records what it sees and then exits with status 3
    WHEN the shim runs it
    THEN it ran as __main__ with its own argv and its directory first on
        sys.path, the profile was written anyway, and SystemExit(3) passed
        through; the shim's own frames are not in it
    """
    script = tmp_path / "bench.py"
    script.write_text(PROBE + "raise SystemExit(3)\n")
    out = tmp_path / "out.json"

    with pytest.raises(SystemExit) as stopped:
        _profile_shim.main(
            ["shim", str(out), "script", str(script), "a1"], safe_path=False
        )

    assert stopped.value.code == 3
    seen = read_seen(tmp_path)
    assert (seen.name, seen.argv) == ("__main__", [str(script), "a1"])
    assert seen.path[0] == os.path.realpath(tmp_path)
    doc = parse_profile(out.read_bytes())
    assert [e.file for e in doc.entries if e.function == "hot"] == [str(script)]
    assert all(e.file != OWN for e in doc.entries)


def test_the_shim_runs_a_module_as_main_from_the_working_directory(
    tmp_path: Path,
    package: str,
    isolated_sys: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "out.json"

    _profile_shim.main(
        ["shim", str(out), "module", f"{package}.mod", "x"], safe_path=False
    )

    seen = read_seen(tmp_path / package)
    cwd = os.path.realpath(tmp_path)
    assert (seen.name, seen.argv) == ("__main__", [f"{cwd}/{package}/mod.py", "x"])
    assert seen.path == [cwd, *isolated_sys]
    hot = [e for e in parse_profile(out.read_bytes()).entries if e.function == "hot"]
    assert len(hot) == 1


@pytest.mark.parametrize("kind", ["module", "script"])
def test_the_shim_adds_nothing_to_sys_path_under_safe_path(
    tmp_path: Path,
    package: str,
    isolated_sys: list[str],
    kind: str,
) -> None:
    """
    GIVEN the interpreter runs with -P or -I (safe_path)
    WHEN the shim runs a module or a script
    THEN sys.path is exactly what the interpreter set up: neither the
        working directory nor the script's directory is added
    """
    sys.path.append(str(tmp_path))
    target = (
        f"{package}.mod" if kind == "module" else str(tmp_path / package / "mod.py")
    )

    _profile_shim.main(
        ["shim", str(tmp_path / "out.json"), kind, target], safe_path=True
    )

    assert read_seen(tmp_path / package).path == [*isolated_sys, str(tmp_path)]


@pytest.mark.usefixtures("isolated_sys")
def test_the_shim_writes_the_profile_even_when_the_target_raises(
    tmp_path: Path,
) -> None:
    script = tmp_path / "bench.py"
    script.write_text(PROBE + "raise ValueError('boom')\n")
    out = tmp_path / "out.json"

    with pytest.raises(ValueError, match="boom"):
        _profile_shim.main(["shim", str(out), "script", str(script)])

    assert any(e.function == "hot" for e in parse_profile(out.read_bytes()).entries)


CHDIR_PROBE = """import json, os, pathlib, sys


def hot():
    return sum(i * i for i in range(3000))


hot()
os.chdir("/")
seen = {"name": __name__, "argv": sys.argv, "path": sys.path, "file": __file__}
pathlib.Path(__file__).with_name("seen.json").write_text(json.dumps(seen))
"""


@pytest.mark.usefixtures("isolated_sys")
def test_a_relative_script_gets_an_absolute_file_as_under_cpython(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    GIVEN a script named relative to the working directory (``python
        bench.py``, the usual workload) that changes directory and then
        opens a file next to ``__file__``
    WHEN the shim runs it
    THEN ``__file__`` is absolute (as CPython >= 3.9 makes it), so the script
        works as it does natively, and its frames carry the absolute path
    """
    (tmp_path / "bench.py").write_text(CHDIR_PROBE)
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "out.json"

    _profile_shim.main(["shim", str(out), "script", "bench.py"], safe_path=False)

    raw = json.loads((tmp_path / "seen.json").read_text())
    script = os.path.join(os.path.realpath(tmp_path), "bench.py")
    assert (raw["name"], raw["file"], raw["path"][0]) == (
        "__main__",
        script,
        os.path.realpath(tmp_path),
    )
    hot = [e for e in parse_profile(out.read_bytes()).entries if e.function == "hot"]
    assert [e.file for e in hot] == [script]


@pytest.mark.parametrize("zipped", [False, True], ids=["directory", "zipapp"])
def test_a_directory_or_zip_target_is_on_sys_path_without_its_parent(
    tmp_path: Path, isolated_sys: list[str], zipped: bool
) -> None:
    """
    GIVEN a directory with a ``__main__.py`` and the same as a zipapp
    WHEN the shim runs it
    THEN sys.path starts with the target itself and nothing else is added,
        exactly as ``python <dir|zip>`` does: its parent is not importable
    """
    apps = tmp_path / "apps"
    (apps / "tool").mkdir(parents=True)
    seen = tmp_path / "seen.json"
    (apps / "tool" / "__main__.py").write_text(
        "import json, pathlib, sys\n"
        f"pathlib.Path({str(seen)!r}).write_text(json.dumps(sys.path))\n"
    )
    target = apps / "tool"
    if zipped:
        target = Path(shutil.make_archive(str(apps / "tool"), "zip", apps / "tool"))

    _profile_shim.main(
        ["shim", str(tmp_path / "out.json"), "script", str(target)], safe_path=False
    )

    assert json.loads(seen.read_text()) == [str(target), *isolated_sys]


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
    found = _profile_shim.interpreter_problem(version)

    if problem is None:
        assert found is None
    else:
        assert found is not None and problem in found


@pytest.mark.parametrize(
    ("flags", "expected"),
    [
        (SimpleNamespace(safe_path=True, isolated=0), True),
        (SimpleNamespace(safe_path=False, isolated=1), False),
        (SimpleNamespace(isolated=1), True),  # Python < 3.11: -I has no safe_path
        (SimpleNamespace(isolated=0), False),
    ],
)
def test_safe_path_falls_back_to_isolated_mode_before_python_3_11(
    flags: SimpleNamespace, expected: bool
) -> None:
    assert _profile_shim.path_is_safe(flags) is expected


def test_the_shim_parses_with_the_oldest_supported_grammar() -> None:
    """The shim runs in the workload's interpreter, which may be older than
    the engine's: its source must parse with the floor's grammar."""
    source = Path(_profile_shim.__file__).read_text()

    ast.parse(source, feature_version=_profile_shim.MIN_PYTHON[:2])
    assert _profile_shim.MIN_PYTHON == (3, 8)
    assert "from __future__ import annotations" in source


@pytest.mark.parametrize(
    "argv",
    [
        ["shim"],
        ["shim", "/o.json", "script"],
        ["shim", "/o.json", "eval", "x"],
    ],
)
def test_the_shim_refuses_any_other_usage(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as stopped:
        _profile_shim.main(argv)

    assert isinstance(stopped.value.code, str)
    assert stopped.value.code.startswith("usage: _profile_shim.py OUT")


# ---------------------------------------------------------------------------
# The shim, as a real subprocess
# ---------------------------------------------------------------------------

SUBPROCESS_PROBE = """import json, os, sys


def hot():
    return sum(i * i for i in range(20000))


hot()
print(json.dumps({"path": sys.path, "name": __name__}))
raise SystemExit(7)
"""


OLD_INTERPRETERS = ["python3.8", "python3.9", "python3.10"]
"""Older than the engine's floor, but a workload may use them (the shim's)."""
FOUND = {
    name: shutil.which(name) for name in [*OLD_INTERPRETERS, "python3.11", "python3.12"]
}
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


@pytest.mark.parametrize("python", INTERPRETERS)
@pytest.mark.parametrize("mode", ["script", "module", "module-safe-path"])
def test_the_real_shim_drops_its_own_directory_from_sys_path(
    tmp_path: Path, python: str, mode: str
) -> None:
    """
    GIVEN the shim run by path, as the profiler runs it, from a working
        directory that is not the probe's
    WHEN it runs the probe as a script, as a module, and as a module under -P
    THEN the engine's package directory never reaches the probe's sys.path,
        sys.path[0] is the script's directory, the working directory, or
        (under -P) the first PYTHONPATH entry; the exit status passes
        through and the profile parses
    """
    lib, elsewhere = tmp_path / "lib", tmp_path / "elsewhere"
    lib.mkdir()
    elsewhere.mkdir()
    (lib / "shimprobe.py").write_text(SUBPROCESS_PROBE)
    out = tmp_path / "out.json"
    options = ["-P"] if mode == "module-safe-path" else []
    target = (
        ["script", str(lib / "shimprobe.py")]
        if mode == "script"
        else [
            "module",
            "shimprobe",
        ]
    )
    env = {"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(lib)}

    proc = subprocess.run(
        [python, *options, str(SHIM_PATH), str(out), *target],
        cwd=elsewhere,
        env=env,
        capture_output=True,
        timeout=60,
        check=False,
    )

    assert proc.returncode == 7, proc.stderr.decode(errors="replace")
    seen = json.loads(proc.stdout)
    first = {
        "script": os.path.realpath(lib),
        "module": os.path.realpath(elsewhere),
        "module-safe-path": str(lib),
    }[mode]
    assert seen["name"] == "__main__"
    assert seen["path"][0] == first
    assert str(SHIM_PATH.parent) not in seen["path"]
    assert os.path.realpath(elsewhere) not in seen["path"][1:]
    entries = parse_profile(out.read_bytes()).entries
    hot = [e for e in entries if e.function == "hot"]
    assert len(hot) == 1 and hot[0].file.endswith("shimprobe.py")
    # runpy's lazy import of pkgutil (and typing) runs before profiling starts
    lazy = ("pkgutil.py", "typing.py")
    assert not [
        e for e in entries if e.file.endswith(lazy) and e.function == "<module>"
    ]


# ---------------------------------------------------------------------------
# Strict parsing
# ---------------------------------------------------------------------------

GOOD = entry("/wt/pkg/core.py")


def changed(**changes: object) -> bytes:
    return document({**GOOD, **changes})


def without(key: str) -> bytes:
    return document({k: v for k, v in GOOD.items() if k != key})


def raw(text: str) -> bytes:
    return text.encode()


MALFORMED: list[tuple[str, bytes, str]] = [
    ("not ASCII", b'{"version": 1, "total_s": 1.0, "entries": []}\xff', "ASCII"),
    ("raw UTF-8", document(entry("/wt/caf\u00e9.py")).replace(b"\\u00e9", "\u00e9".encode()), "ASCII"),
    ("not JSON", b"profile", "not valid JSON"),
    ("trailing data", document() + b"{}", "not valid JSON"),
    ("deep nesting", b"[" * 100_000, "not valid JSON"),
    ("huge integer", raw('{"version": 1' + "0" * 5000 + "}"), "not valid JSON"),
    ("NaN", raw('{"version": 1, "total_s": NaN, "entries": []}'), "NaN"),
    ("Infinity", raw('{"version": 1, "total_s": Infinity, "entries": []}'), "Infinity"),
    ("-Infinity", changed(self_s=float("-inf")), "-Infinity"),
    ("overflow", raw('{"version": 1, "total_s": 1e999, "entries": []}'), "total_s"),
    ("repeated key", raw('{"version": 1, "version": 1, "total_s": 1.0, "entries": []}'), "repeated"),
    ("a list", b"[]", "top level"),
    ("missing key", raw('{"version": 1, "entries": []}'), "top level"),
    ("extra key", raw('{"version": 1, "total_s": 1.0, "entries": [], "x": 1}'), "top level"),
    ("version 2", raw('{"version": 2, "total_s": 1.0, "entries": []}'), "version"),
    ("version text", raw('{"version": "1", "total_s": 1.0, "entries": []}'), "version"),
    ("version bool", raw('{"version": true, "total_s": 1.0, "entries": []}'), "version"),
    ("version float", raw('{"version": 1.0, "total_s": 1.0, "entries": []}'), "version"),
    ("total int", raw('{"version": 1, "total_s": 1, "entries": []}'), "total_s"),
    ("total negative", raw('{"version": 1, "total_s": -1.0, "entries": []}'), "total_s"),
    ("total too large", raw('{"version": 1, "total_s": 1e8, "entries": []}'), "total_s"),
    ("entries object", raw('{"version": 1, "total_s": 1.0, "entries": {}}'), "entries"),
    ("entry list", raw('{"version": 1, "total_s": 1.0, "entries": [[]]}'), "entry 0"),
    ("entry missing key", without("line"), "entry 0"),
    ("entry extra key", changed(memory=1), "entry 0"),
    ("empty file", changed(file=""), "file"),
    ("file not text", changed(file=5), "file"),
    ("file too long", changed(file="/" + "x" * 4096), "file"),
    ("empty function", changed(function=""), "function"),
    ("function null", changed(function=None), "function"),
    ("function too long", changed(function="f" * 257), "function"),
    ("negative line", changed(line=-1), "line"),
    ("float line", changed(line=1.5), "line"),
    ("bool line", changed(line=True), "line"),
    ("huge line", changed(line=2**31), "line"),
    ("negative calls", changed(primitive_calls=-1), "primitive_calls"),
    ("bool calls", changed(total_calls=False), "total_calls"),
    ("too many calls", changed(total_calls=2**53 + 1), "total_calls"),
    ("more primitive than total", changed(primitive_calls=2, total_calls=1), "primitive"),
    ("int self time", changed(self_s=1), "self_s"),
    ("negative self time", changed(self_s=-0.5), "self_s"),
    ("too much self time", changed(self_s=1e8), "self_s"),
    ("text cumulative time", changed(cumulative_s="x"), "cumulative_s"),
    ("repeated entry", document(GOOD, {**GOOD, "self_s": 0.1}), "repeats"),
]  # fmt: skip


@pytest.mark.parametrize(
    ("payload", "reason"),
    [pytest.param(payload, reason, id=name) for name, payload, reason in MALFORMED],
)
def test_a_malformed_profile_is_refused(payload: bytes, reason: str) -> None:
    with pytest.raises(ProfileFormatError, match=re.escape(reason)):
        parse_profile(payload)


def test_a_profile_larger_than_the_cap_is_refused() -> None:
    payload = document() + b" " * _profile_shim.MAX_DOC_BYTES
    with pytest.raises(ProfileFormatError, match="larger than"):
        parse_profile(payload)


def test_too_many_entries_are_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_profile_shim, "MAX_ENTRIES", 2)
    entries = [entry(f"/wt/{n}.py") for n in range(3)]
    with pytest.raises(ProfileFormatError, match="more than 2 entries"):
        parse_profile(document(*entries))


def test_a_well_formed_profile_parses() -> None:
    assert parse_profile(document(total_s=0.0)) == ProfileDoc(total_s=0.0, entries=())
    edge = entry(
        "/wt/x.py",
        "f" * 256,
        line=0,
        self_s=0.0,
        cumulative_s=1e7,
        primitive_calls=0,
        total_calls=2**53,
    )
    [parsed] = parse_profile(document(edge)).entries
    assert parsed == ProfileEntry("/wt/x.py", 0, "f" * 256, 0, 2**53, 0.0, 1e7)


# ---------------------------------------------------------------------------
# The profiled argv
# ---------------------------------------------------------------------------

SHIM = str(SHIM_PATH)


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ((PY, "-m", "pkg.main", "5"), [PY, SHIM, str(OUT), "module", "pkg.main", "5"]),
        ((PY, "bench.py", "-m", "x"), [PY, SHIM, str(OUT), "script", "bench.py", "-m", "x"]),
        ((PY, "-X", "utf8", "-O", "-Wd", "bench.py"), [PY, "-X", "utf8", "-O", "-Wd", SHIM, str(OUT), "script", "bench.py"]),
        ((PY, "-W", "error", "-m", "pkg"), [PY, "-W", "error", SHIM, str(OUT), "module", "pkg"]),
        ((PY, "-Bm", "pkg.main"), [PY, "-B", SHIM, str(OUT), "module", "pkg.main"]),
        ((PY, "-mpkg.main", "x"), [PY, SHIM, str(OUT), "module", "pkg.main", "x"]),
        ((PY, "-uBmpkg"), [PY, "-uB", SHIM, str(OUT), "module", "pkg"]),
        ((PY, "-uXutf8", "b.py"), [PY, "-uXutf8", SHIM, str(OUT), "script", "b.py"]),
        ((PY, "--check-hash-based-pycs", "always", "b.py"), [PY, "--check-hash-based-pycs", "always", SHIM, str(OUT), "script", "b.py"]),
        ((PY, "-O", "--", "-odd.py", "a"), [PY, "-O", SHIM, str(OUT), "script", "-odd.py", "a"]),
        (("python3.11", "b.py"), ["python3.11", SHIM, str(OUT), "script", "b.py"]),
        (("/opt/pypy/bin/pypy3", "b.py"), ["/opt/pypy/bin/pypy3", SHIM, str(OUT), "script", "b.py"]),
        (("/usr/bin/python3.13t", "-m", "a"), ["/usr/bin/python3.13t", SHIM, str(OUT), "module", "a"]),
    ],
)  # fmt: skip
def test_a_python_command_runs_the_target_under_the_shim(
    command: tuple[str, ...], expected: list[str]
) -> None:
    assert profiled_argv(command, OUT) == expected


@pytest.mark.parametrize(
    ("command", "reason"),
    [
        (("/bin/sh", "run.sh"), "'/bin/sh' is not a Python interpreter"),
        (("./bench.sh",), "is not a Python interpreter"),
        (("pytest", "-q"), "is not a Python interpreter"),
        ((PY, "-c", "print(1)"), "inline code (-c)"),
        ((PY, "-Bc", "x"), "inline code (-c)"),
        ((PY, "-"), "reads its program from stdin"),
        ((PY, "-x", "b.py"), "-x"),
        ((PY,), "names no script or module"),
        ((PY, "-O"), "names no script or module"),
        ((PY, "-W"), "names no script or module"),
        ((PY, "--"), "names no script or module"),
        ((PY, "-m"), "-m names no module"),
    ],
)
def test_other_commands_are_not_profiled(command: tuple[str, ...], reason: str) -> None:
    with pytest.raises(NotProfiledError, match=re.escape(reason)):
        profiled_argv(command, OUT)


# ---------------------------------------------------------------------------
# Paths and symbols
# ---------------------------------------------------------------------------


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A worktree with a tracked file, a tracked link to it, one escaping, a
    directory link escaping (``ext``) and an alias of the worktree outside."""
    wt = Path(os.path.realpath(tmp_path)) / "wt"
    (wt / "pkg").mkdir(parents=True)
    (wt / "pkg" / "core.py").write_text("")
    os.symlink("core.py", wt / "pkg" / "link.py")
    os.symlink(tmp_path / "outside.py", wt / "out.py")
    (tmp_path / "elsewhere" / "sub").mkdir(parents=True)
    (tmp_path / "elsewhere" / "pkg").mkdir()
    (tmp_path / "elsewhere" / "pkg" / "core.py").write_text("")
    os.symlink(tmp_path / "elsewhere" / "sub", wt / "ext")
    os.symlink(wt, tmp_path / "wtalias")
    return wt


TRACKED = frozenset(
    {"pkg/core.py", "pkg/link.py", "out.py", "bench.py", "a\\b.py", "~tmp.py"}
)


@pytest.mark.parametrize(
    ("file", "cwd", "expected"),
    [
        ("{wt}/pkg/core.py", ".", "pkg/core.py"),
        ("pkg/core.py", ".", "pkg/core.py"),
        ("core.py", "pkg", "pkg/core.py"),
        ("{wt}/pkg/link.py", ".", "pkg/core.py"),
        ("{wt}/pkg/../pkg/core.py", ".", "pkg/core.py"),
        ("{alias}/pkg/core.py", ".", "pkg/core.py"),
        ("{wt}/ext/../pkg/core.py", ".", None),
        ("ext/../pkg/core.py", ".", None),
        ("{wt}/untracked.py", ".", None),
        ("{wt}/out.py", ".", None),
        ("../outside.py", ".", None),
        ("{wt}", ".", None),
        ("/usr/lib/python3/json/__init__.py", ".", None),
        ("{wt}/a\\b.py", ".", None),
        ("{wt}/~tmp.py", ".", None),
        ("{wt}/pkg/core.py\0x", ".", None),
        ("{wt}/pkg/\udcff.py", ".", None),
    ],
)
def test_project_file_maps_only_tracked_files_inside_the_worktree(
    tree: Path, file: str, cwd: str, expected: str | None
) -> None:
    path = file.replace("{wt}", str(tree)).replace(
        "{alias}", str(tree.parent / "wtalias")
    )

    found = project_file(path, cwd=tree / cwd, worktree=tree, tracked=TRACKED)

    assert found == expected


@pytest.fixture
def checkout(tmp_path: Path) -> tuple[Path, Path]:
    """The user's checkout (real path) and a symlinked alias of it."""
    root = Path(os.path.realpath(tmp_path)) / "user"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "core.py").write_text("")
    editable = root / "build" / "__editable__" / "pkg"
    editable.mkdir(parents=True)
    os.symlink(root / "pkg" / "core.py", editable / "core.py")
    alias = Path(os.path.realpath(tmp_path)) / "alias"
    os.symlink(root, alias)
    return root, alias


@pytest.mark.parametrize(
    ("file", "found"),
    [
        ("{root}/pkg/core.py", True),
        ("{alias}/pkg/core.py", True),
        ("{root}/build/__editable__/pkg/core.py", True),
        ("pkg/core.py", True),
        ("{root}/.venv/lib/python3.13/site-packages/numpy/core.py", False),
        ("/elsewhere/pkg/core.py", False),
        ("{root}/pkg/core.py\0", False),
    ],
)
def test_checkout_file_finds_tracked_files_of_the_users_checkout(
    checkout: tuple[Path, Path], file: str, found: bool
) -> None:
    root, alias = checkout
    path = file.replace("{root}", str(root)).replace("{alias}", str(alias))

    named = checkout_file(
        path, cwd=root, roots=(alias, root), tracked=frozenset({"pkg/core.py"})
    )

    expected = os.path.normpath(os.path.join(root, path)) if found else None
    assert named == expected


@pytest.fixture
def linked(checkout: tuple[Path, Path]) -> Path:
    """Outside the checkout: a symlinked install (``flit install --symlink``)
    of its package and of an untracked file, and a link to unrelated code."""
    root, _ = checkout
    site = root.parent / "venv" / "site-packages"
    site.mkdir(parents=True)
    os.symlink(root / "pkg", site / "pkg")
    (root / "pkg" / "scratch.py").write_text("")
    os.symlink(root / "pkg" / "scratch.py", site / "scratch.py")
    (root.parent / "other").mkdir()
    (root.parent / "other" / "core.py").write_text("")
    os.symlink(root.parent / "other", site / "other")
    return site


@pytest.mark.parametrize(
    ("file", "found"),
    [
        ("{alias}/pkg/core.py", True),
        ("{site}/pkg/core.py", True),
        ("{site}/pkg/../pkg/core.py", True),
        ("{site}/scratch.py", False),
        ("{site}/other/core.py", False),
    ],
)
def test_checkout_file_follows_links_from_outside_into_the_checkout(
    checkout: tuple[Path, Path], linked: Path, file: str, found: bool
) -> None:
    """
    GIVEN roots that hold only the checkout's real path, an alias directory
        link outside it and a symlinked site-packages install of its package
    WHEN a frame reaches a tracked checkout file through either link
    THEN it is found (the frame's path is named); an untracked checkout file
        or a link to unrelated code is not
    """
    root, alias = checkout
    path = file.replace("{alias}", str(alias)).replace("{site}", str(linked))

    named = checkout_file(
        path, cwd=root, roots=(root, root), tracked=frozenset({"pkg/core.py"})
    )

    assert named == (os.path.normpath(path) if found else None)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("unique_in_order", "unique_in_order"),
        ("<module>", "<module>"),
        ("evil\x1b[31m\nname", "evil[31mname"),
        ("\u202eabc", "abc"),
        ("a\udcffb", "ab"),
        ("  padded  ", "padded"),
        ("\x00\x01", ""),
        ("f" * 300, "f" * MAX_SYMBOL_CHARS),
    ],
)
def test_clean_symbol_strips_control_characters_and_caps_length(
    text: str, expected: str
) -> None:
    assert clean_symbol(text) == expected


# ---------------------------------------------------------------------------
# The profiler on doubles
# ---------------------------------------------------------------------------


def sample(
    *, exit: int = 0, stderr: bytes = b"", notes: tuple[str, ...] = ()
) -> RunSample:
    return RunSample(
        wall_ns=1_000_000,
        utime=0.1,
        stime=0.0,
        maxrss_bytes=1 << 20,
        exit=exit,
        fs_isolated=True,
        net_isolated=True,
        stdout_sha256="0" * 64,
        stdout_head=b"",
        stdout_bytes=0,
        stderr_tail=stderr,
        notes=notes,
    )


class Call(NamedTuple):
    argv: tuple[str, ...]
    cwd: Path
    env: Mapping[str, str]
    sandbox: SandboxPolicy
    timeout_s: float
    caps: OutputCaps
    fresh_dirs: tuple[Path, ...]


Respond = Callable[[Call], RunSample]


def out_path(call: Call) -> Path:
    return Path(call.argv[call.argv.index(SHIM) + 1])


def writes(*payloads: bytes | None, exit: int = 0, stderr: bytes = b"") -> Respond:
    """Each run writes the next payload (the last one forever); None: nothing."""
    queue = list(payloads)

    def respond(call: Call) -> RunSample:
        payload = queue.pop(0) if len(queue) > 1 else queue[0]
        if payload is not None:
            out_path(call).write_bytes(payload)
        return sample(exit=exit, stderr=stderr)

    return respond


@dataclass
class FakeRun:
    events: list[str]
    respond: Respond
    calls: list[Call] = field(default_factory=list)

    def __call__(
        self,
        argv: Sequence[str],
        cwd: Path,
        env: Mapping[str, str],
        sandbox: SandboxPolicy,
        timeout_s: float,
        caps: OutputCaps,
        *,
        fresh_dirs: Sequence[Path] = (),
    ) -> RunSample:
        call = Call(tuple(argv), cwd, env, sandbox, timeout_s, caps, tuple(fresh_dirs))
        self.calls.append(call)
        self.events.append("run")
        return self.respond(call)


@dataclass
class FakeGit:
    """Records every call; fingerprints come from ``prints`` in order."""

    events: list[str]
    tracked: tuple[str, ...] = ()
    prints: list[str] = field(default_factory=lambda: ["F0"])
    add_error: Exception | None = None
    reset_error: Exception | None = None
    added: list[tuple[Path, str]] = field(default_factory=list)

    def fingerprint(self) -> str:
        self.events.append("fingerprint")
        return self.prints.pop(0) if len(self.prints) > 1 else self.prints[0]

    def add_worktree(self, path: Path, commit: str) -> WorktreeHandle:
        self.events.append(f"add {path.name}")
        self.added.append((path, commit))
        if self.add_error is not None:
            raise self.add_error
        path.mkdir(parents=True)
        gitdir = path.parent / "admin"
        return WorktreeHandle(path=path, gitdir=gitdir, link_bytes=b"gitdir: x\n")

    def remove_worktree(self, target: WorktreeHandle | Path) -> None:
        path = target.path if isinstance(target, WorktreeHandle) else target
        self.events.append(f"remove {path.name}")
        if path.is_dir():
            shutil.rmtree(path)

    def prune(self) -> None:
        self.events.append("prune")

    def reset(self, handle: WorktreeHandle) -> None:
        self.events.append("reset")
        if self.reset_error is not None:
            raise self.reset_error

    def ls_tree(self, commit: str) -> tuple[str, ...]:
        self.events.append("ls_tree")
        return self.tracked


@dataclass
class Rig:
    root: Path
    project: Project
    events: list[str]
    git: FakeGit
    run: FakeRun

    @property
    def run_dir(self) -> Path:
        return self.root / "wt-root" / RUN_ID

    @property
    def worktree(self) -> Path:
        return self.run_dir / "profile"

    @property
    def scratch(self) -> Path:
        return self.run_dir / "_scratch" / "profile"

    @property
    def probe(self) -> Path:
        return self.run_dir / "_probe" / "profile"

    @property
    def user(self) -> Path:
        return Path(self.project.root_path)

    def file(self, rel: str) -> str:
        return str(self.worktree / rel)

    def profiler(self) -> CProfiler:
        return CProfiler(
            self.project,
            git=self.git,
            fingerprint=self.git.fingerprint,
            run=self.run,
            network="required",
            fs="required",
            platform="linux",
            base_env={"PATH": "/usr/bin"},
        )

    def workload(self, name: str = "bench", **changes: object) -> Workload:
        fields: dict[str, object] = {
            "project_id": self.project.id,
            "name": name,
            "command": (PY, "-m", "pkg.main"),
            "timeout_s": 42.0,
        }
        fields.update(changes)
        return Workload.model_validate(fields)

    def profile(self, *workloads: Workload) -> ProfileResult:
        return self.profiler().profile(workloads, run_id=RUN_ID, commit=COMMIT)


@pytest.fixture
def rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Rig:
    root = Path(os.path.realpath(tmp_path))
    (root / "wt-root").mkdir()
    (root / "user").mkdir()
    monkeypatch.setattr(settings, "WORKTREE_ROOT", root / "wt-root")
    events: list[str] = []
    git = FakeGit(events, tracked=("pkg/core.py", "pkg/main.py", "tests/t.py"))
    project = Project(name="demo", root_path=str(root / "user"))
    payload = document(entry(str(root / "wt-root" / RUN_ID / "profile/pkg/core.py")))
    return Rig(root, project, events, git, FakeRun(events, writes(payload)))


ONE_RUN = [
    "fingerprint",
    "add profile",
    "ls_tree",
    "reset",
    "run",
    "reset",
    "fingerprint",
    "remove profile",
    "prune",
]


def test_the_real_profiler_satisfies_the_protocol(rig: Rig) -> None:
    assert isinstance(rig.profiler(), Profiler)


def test_each_python_workload_runs_once_under_the_shim_in_the_profile_worktree(
    rig: Rig,
) -> None:
    """
    GIVEN one Python workload
    WHEN it is profiled at a commit
    THEN F0, the <run>/profile worktree at that commit, one reset run under
        the phase's sandbox with fresh scratch (the shim writing into the
        scratch root, the workload's timeout times the cProfile overhead
        allowance), a reset, F1 and the cleanup happen in that order, and
        nothing of the run is left
    """
    workload = rig.workload(working_dir="pkg")

    result = rig.profile(workload)

    assert rig.events == ONE_RUN
    assert rig.git.added == [(rig.worktree, COMMIT)]
    [call] = rig.run.calls
    out = rig.scratch / PROFILE_NAME
    assert call.argv == (PY, SHIM, str(out), "module", "pkg.main")
    assert (call.cwd, call.timeout_s) == (
        rig.worktree / "pkg",
        42.0 * PROFILE_TIMEOUT_FACTOR,
    )
    assert PROFILE_TIMEOUT_FACTOR == 3.0
    assert call.sandbox == SandboxPolicy(
        network="required",
        fs="required",
        writable=(rig.worktree, rig.scratch),
        probe_dir=rig.probe,
        platform="linux",
    )
    assert call.fresh_dirs == (rig.scratch, rig.scratch / "home", rig.scratch / "tmp")
    assert call.env["PYTHONPATH"] == str(rig.worktree)
    assert call.env["HOME"] == str(rig.scratch / "home")
    assert call.caps == OutputCaps.from_settings()
    assert result.notes == ()
    assert [(h.file_path, h.workload_id) for h in result.hotspots] == [
        ("pkg/core.py", workload.id)
    ]
    assert not rig.run_dir.exists()


def test_hotspots_carry_self_time_share_calls_and_the_project(rig: Rig) -> None:
    """
    GIVEN a profile with project files, a stdlib frame, the shim's own
        frame, a zero-time frame, an untracked file, a control-character
        symbol and a module-level frame (line 0)
    WHEN it becomes hotspots
    THEN only tracked worktree files with time remain, ranked by self time,
        with share = self time / total, the cumulative time, the total
        call count, a cleaned symbol, and no line for line 0
    """
    rig.run.respond = writes(
        document(
            entry(rig.file("pkg/main.py"), "<module>", line=0, self_s=0.1,
                  cumulative_s=1.0),
            entry(rig.file("pkg/core.py"), "unique_in_order", line=6, self_s=0.6,
                  cumulative_s=0.7, primitive_calls=1, total_calls=3),
            entry("/usr/lib/python3.13/json/decoder.py", "decode", self_s=0.2),
            entry(SHIM, "run", self_s=0.05),
            entry(rig.file("pkg/core.py"), "idle", line=20, self_s=0.0),
            entry(rig.file("pkg/new.py"), "untracked", self_s=0.04),
            entry(rig.file("pkg/core.py"), "evil\x1b[0m", line=30, self_s=0.01),
            entry(rig.file("pkg/core.py"), "\x1b\x07", line=40, self_s=0.01),
            total_s=2.0,
        )
    )  # fmt: skip
    workload = rig.workload()

    result = rig.profile(workload)

    assert result.hotspots == tuple(
        Hotspot(
            id=hotspot.id,
            project_id=rig.project.id,
            workload_id=workload.id,
            file_path=file_path,
            symbol=symbol,
            line_start=line,
            self_time_s=self_s,
            total_time_s=total,
            share=share,
            calls=calls,
        )
        for hotspot, (file_path, symbol, line, self_s, total, share, calls) in zip(
            result.hotspots,
            [
                ("pkg/core.py", "unique_in_order", 6, 0.6, 0.7, 0.3, 3),
                ("pkg/main.py", "<module>", None, 0.1, 1.0, 0.05, 1),
                ("pkg/core.py", "evil[0m", 30, 0.01, 0.6, 0.005, 1),
            ],
            strict=True,
        )
    )


def test_a_forged_small_total_cannot_inflate_shares(rig: Rig) -> None:
    rig.run.respond = writes(
        document(
            entry(rig.file("pkg/core.py"), "a", self_s=0.75),
            entry(rig.file("pkg/main.py"), "b", self_s=0.25),
            total_s=0.0,
        )
    )

    shares = [h.share for h in rig.profile(rig.workload()).hotspots]

    assert shares == [0.75, 0.25]


def test_hotspots_are_capped_per_workload_and_in_all(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    GIVEN two workloads with five hotspots each
    WHEN the caps are three per workload and four in all
    THEN each workload keeps its three slowest, and the four largest shares
        survive across both, largest first
    """
    monkeypatch.setattr(profiler, "HOTSPOTS_PER_WORKLOAD", 3)
    monkeypatch.setattr(profiler, "MAX_HOTSPOTS", 4)
    rig.git.tracked = tuple(f"m{n}.py" for n in range(10))
    first = [entry(rig.file(f"m{n}.py"), f"a{n}", self_s=n / 25) for n in range(5)]
    second = [entry(rig.file(f"m{n}.py"), f"b{n}", self_s=n / 19) for n in range(5, 10)]
    rig.run.respond = writes(document(*first), document(*second))

    result = rig.profile(rig.workload("one"), rig.workload("two"))

    assert [h.symbol for h in result.hotspots] == ["b9", "b8", "b7", "a4"]


def test_commands_that_cannot_be_profiled_are_notes_and_never_run(rig: Rig) -> None:
    """
    GIVEN a shell workload, an inline -c workload and a Python workload
    WHEN they are profiled
    THEN only the Python one runs; the other two are profile_skipped notes
        naming the workload and the reason
    """
    shell = rig.workload("shell", command=("/bin/sh", "bench.sh"))
    inline = rig.workload("inline", command=(PY, "-c", "print(1)"))

    result = rig.profile(shell, inline, rig.workload("py"))

    assert result.notes == (
        "workload 'shell' is not profiled: '/bin/sh' is not a Python interpreter"
        + GUARD_SKIPPED,
        "workload 'inline' is not profiled: inline code (-c) has no file to profile"
        + GUARD_SKIPPED,
    )
    assert GUARD_SKIPPED == (
        "; the editable-install check did not run for it, so make sure the"
        " project is not installed with -e"
    )
    assert len(rig.run.calls) == 1
    assert len(result.hotspots) == 1


def test_nothing_to_profile_touches_no_git_at_all(rig: Rig) -> None:
    shell = rig.workload("shell", command=("/bin/sh", "bench.sh"))

    assert rig.profile() == ProfileResult(hotspots=(), notes=())
    result = rig.profile(shell)

    assert result.hotspots == ()
    assert len(result.notes) == 1
    assert rig.events == []
    assert not rig.run_dir.exists()


def test_a_failed_run_is_a_note_and_the_next_workload_still_runs(rig: Rig) -> None:
    """
    GIVEN a first workload that exits 1 with a traceback and a second one
        that succeeds
    WHEN they are profiled
    THEN the first is a note quoting the last stderr line, the second still
        gives its hotspot, and the worktree is reset after each run
    """
    payload = document(entry(rig.file("pkg/core.py")))
    outcomes = iter([sample(exit=1, stderr=b"Traceback\nValueError: boom\n"), sample()])

    def respond(call: Call) -> RunSample:
        out_path(call).write_bytes(payload)
        return next(outcomes)

    rig.run.respond = respond

    result = rig.profile(rig.workload("bad"), rig.workload("good"))

    assert result.notes == (
        "workload 'bad' is not profiled: the profile run: the command ended with"
        " exit status 1: ValueError: boom" + GUARD_SKIPPED,
    )
    assert len(result.hotspots) == 1
    assert rig.events == [
        "fingerprint",
        "add profile",
        "ls_tree",
        "reset",
        "run",
        "reset",
        "run",
        "reset",
        "fingerprint",
        "remove profile",
        "prune",
    ]


def test_a_run_failure_and_every_run_note_become_notes(rig: Rig) -> None:
    def respond(call: Call) -> RunSample:
        if len(rig.run.calls) == 1:
            raise RunFailure("timed out after 42 s", ("the group drained late",))
        out_path(call).write_bytes(document(entry(rig.file("pkg/core.py"))))
        return sample(notes=("network isolation was not applied",))

    rig.run.respond = respond

    result = rig.profile(rig.workload("slow"), rig.workload("weak"))

    assert result.notes == (
        "workload 'slow': the profile run: the group drained late",
        "workload 'slow' is not profiled: the profile run: timed out after 42 s"
        + GUARD_SKIPPED,
        "workload 'weak': the profile run: network isolation was not applied",
    )
    assert len(result.hotspots) == 1


def plant_link(call: Call) -> RunSample:
    target = call.sandbox.writable[1] / "elsewhere.json"
    target.write_bytes(document())
    os.symlink(target, out_path(call))
    return sample()


@pytest.mark.parametrize(
    ("respond", "reason"),
    [
        (writes(None), "the profile output is missing"),
        (writes(b"{"), "the profile output is not valid JSON"),
        (writes(b" " * (_profile_shim.MAX_DOC_BYTES + 1)), "is larger than"),
        (plant_link, "the profile output cannot be opened"),
        (writes(document(entry("/wt/x.py", line=-1))), "entry 0: line must be"),
    ],
)
def test_unusable_profile_output_is_a_note(
    rig: Rig, respond: Respond, reason: str
) -> None:
    rig.run.respond = respond

    result = rig.profile(rig.workload())

    assert result.hotspots == ()
    [note] = result.notes
    assert note.startswith("workload 'bench' is not profiled: ")
    assert reason in note and note.endswith(GUARD_SKIPPED)


def test_an_editable_install_raises_naming_the_path_after_f1_and_cleanup(
    rig: Rig,
) -> None:
    """
    GIVEN a profile whose hot frame is a tracked file of the user's
        checkout, not of the profile worktree (an editable install)
    WHEN it is profiled with a second workload queued
    THEN F1 is still taken, the run is cleaned up, the second workload never
        runs, and EngineError names the checkout path
    """
    checkout = str(rig.user / "pkg" / "core.py")
    rig.run.respond = writes(document(entry(checkout, "unique_in_order")))

    with pytest.raises(EngineError, match=re.escape(checkout)) as raised:
        rig.profile(rig.workload("one"), rig.workload("two"))

    assert "editable install" in str(raised.value)
    assert not isinstance(raised.value, RepoTamperedError)
    assert rig.events == ONE_RUN
    assert not rig.run_dir.exists()


def test_a_symlinked_install_of_the_checkout_raises_naming_the_frame(
    rig: Rig,
) -> None:
    """
    GIVEN a hot frame in site-packages whose package directory is a link
        into the user's checkout (``flit install --symlink``)
    WHEN it is profiled
    THEN EngineError names the site-packages path: the frame ran checkout code
    """
    (rig.user / "pkg").mkdir()
    (rig.user / "pkg" / "core.py").write_text("")
    site = rig.root / "venv" / "site-packages"
    site.mkdir(parents=True)
    os.symlink(rig.user / "pkg", site / "pkg")
    frame = str(site / "pkg" / "core.py")
    rig.run.respond = writes(document(entry(frame, "unique_in_order")))

    with pytest.raises(EngineError, match=re.escape(frame)):
        rig.profile(rig.workload())

    assert not rig.run_dir.exists()


def test_untracked_checkout_files_such_as_a_venv_are_not_an_editable_install(
    rig: Rig,
) -> None:
    venv = str(rig.user / ".venv" / "lib" / "site-packages" / "numpy" / "core.py")
    rig.run.respond = writes(document(entry(venv, self_s=0.9)))

    result = rig.profile(rig.workload())

    assert result == ProfileResult(hotspots=(), notes=())


def test_a_hostile_checkout_path_is_quoted_in_the_error(rig: Rig) -> None:
    (rig.user / "pkg").mkdir()
    rig.git.tracked = ("pkg/\x1b]0;x\x07.py",)
    rig.run.respond = writes(document(entry(str(rig.user / "pkg/\x1b]0;x\x07.py"))))

    with pytest.raises(EngineError) as raised:
        rig.profile(rig.workload())

    message = str(raised.value)
    assert "\x1b" not in message and "\x07" not in message
    assert str(rig.user / "pkg/?]0;x?.py") in message


def test_the_shims_own_frames_never_count_when_the_engine_profiles_itself(
    rig: Rig,
) -> None:
    """
    GIVEN the engine's own checkout as the project, so the shim is a tracked
        file of it, and a profile holding a shim frame
    WHEN it is profiled
    THEN the shim frame is neither a hotspot nor an editable install
    """
    rig.project = Project(name="engine", root_path=str(SHIM_PATH.parent))
    rig.git.tracked = (SHIM_PATH.name,)
    rig.run.respond = writes(document(entry(SHIM, "main", self_s=0.9)))

    assert rig.profile(rig.workload()) == ProfileResult(hotspots=(), notes=())


def test_tampering_raises_repo_tampered_and_cleans_up(rig: Rig) -> None:
    rig.git.prints = ["F0", "F1"]

    with pytest.raises(RepoTamperedError, match="changed while the profiler ran"):
        rig.profile(rig.workload())

    assert rig.events == ONE_RUN
    assert not rig.run_dir.exists()


def test_tampering_wins_over_an_editable_install(rig: Rig) -> None:
    rig.git.prints = ["F0", "F1"]
    checkout = str(rig.user / "pkg" / "core.py")
    rig.run.respond = writes(document(entry(checkout)))

    with pytest.raises(RepoTamperedError):
        rig.profile(rig.workload())


def test_a_reset_failure_propagates_after_cleanup_without_f1(rig: Rig) -> None:
    rig.git.reset_error = RepoTamperedError("the .git link changed")

    with pytest.raises(RepoTamperedError, match="the .git link changed"):
        rig.profile(rig.workload())

    assert rig.events == [
        "fingerprint",
        "add profile",
        "ls_tree",
        "reset",
        "remove profile",
        "prune",
    ]
    assert not rig.run_dir.exists()


def test_a_failed_worktree_add_still_cleans_up(rig: Rig) -> None:
    rig.git.add_error = GitError("worktree add failed")

    with pytest.raises(GitError, match="worktree add failed"):
        rig.profile(rig.workload())

    assert rig.events == ["fingerprint", "add profile", "remove profile", "prune"]
    assert not rig.run_dir.exists()


def test_cleanup_unlinks_a_planted_scratch_link_and_keeps_a_busy_run_dir(
    rig: Rig, tmp_path: Path
) -> None:
    """
    GIVEN another phase's worktree in <run> and a run that replaces the
        scratch root with a link to a directory outside (possible with
        fs=off)
    WHEN the profile is cleaned up
    THEN the link is unlinked (its target untouched), the profile's own
        dirs are gone and <run> stays for its other owner
    """
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep")
    (rig.run_dir / "baseline").mkdir(parents=True)

    def respond(call: Call) -> RunSample:
        scratch = call.sandbox.writable[1]
        shutil.rmtree(scratch)
        os.symlink(outside, scratch)
        return sample()

    rig.run.respond = respond

    result = rig.profile(rig.workload())

    assert result.notes == (
        "workload 'bench' is not profiled: the profile output is missing"
        + GUARD_SKIPPED,
    )
    assert (outside / "keep.txt").read_text() == "keep"
    assert sorted(os.listdir(rig.run_dir)) == ["baseline"]


def test_cleanup_unlinks_a_planted_link_in_place_of_the_scratch_parent(
    rig: Rig, tmp_path: Path
) -> None:
    """
    GIVEN a run that replaces <run>/_scratch (the parent of the scratch
        root) with a link to a directory outside (possible with fs=off)
    WHEN the profile is cleaned up
    THEN the link is unlinked without following it, <run>/_probe is still
        removed, and nothing of the run is left
    """
    outside = tmp_path / "outside"
    (outside / "profile").mkdir(parents=True)
    (outside / "profile" / "keep.txt").write_text("keep")

    def respond(call: Call) -> RunSample:
        parent = call.sandbox.writable[1].parent
        shutil.rmtree(parent)
        os.symlink(outside, parent)
        return sample()

    rig.run.respond = respond

    result = rig.profile(rig.workload())

    [note] = result.notes
    assert note.startswith("workload 'bench' is not profiled: the profile output")
    assert (outside / "profile" / "keep.txt").read_text() == "keep"
    assert rig.events[-2:] == ["remove profile", "prune"]
    assert not rig.run_dir.exists()


def test_a_dir_that_cannot_be_removed_safely_is_an_engine_error_after_cleanup(
    rig: Rig, tmp_path: Path
) -> None:
    """
    GIVEN a run that moves <run> outside WORKTREE_ROOT and leaves a link in
        its place, so neither scratch nor probe is inside WORKTREE_ROOT
    WHEN the profile is cleaned up
    THEN every step is still attempted (both dirs, prune), nothing outside
        is removed through the link, and EngineError names both dirs
    """
    outside = tmp_path / "moved"

    def respond(call: Call) -> RunSample:
        shutil.move(rig.run_dir, outside)
        os.symlink(outside, rig.run_dir)
        return sample()

    rig.run.respond = respond

    with pytest.raises(EngineError, match="could not clean up") as raised:
        rig.profile(rig.workload())

    message = str(raised.value)
    assert str(rig.scratch) in message and str(rig.probe) in message
    assert rig.events[-2:] == ["remove profile", "prune"]
    assert (outside / "_scratch" / "profile").is_dir()
    assert (outside / "_probe" / "profile").is_dir()


def test_cleanup_never_removes_an_empty_dir_through_a_planted_run_link(
    rig: Rig, tmp_path: Path
) -> None:
    outside = tmp_path / "moved"

    def respond(call: Call) -> RunSample:
        shutil.rmtree(rig.run_dir)
        for name in ("_scratch", "_probe"):
            (outside / name).mkdir(parents=True)
        os.symlink(outside, rig.run_dir)
        return sample()

    rig.run.respond = respond

    with pytest.raises(EngineError, match="could not clean up"):
        rig.profile(rig.workload())

    assert sorted(os.listdir(outside)) == ["_probe", "_scratch"]


def test_a_cleanup_problem_never_hides_the_error_already_raised(rig: Rig) -> None:
    rig.git.prints = ["F0", "F1"]

    def respond(call: Call) -> RunSample:
        shutil.move(rig.run_dir, rig.root / "moved")
        os.symlink(rig.root / "moved", rig.run_dir)
        return sample()

    rig.run.respond = respond

    with pytest.raises(RepoTamperedError):
        rig.profile(rig.workload())


@pytest.mark.parametrize("run_id", ["", "../x", "a/b", "x..y", "-x", "x.lock"])
def test_an_unsafe_run_id_is_refused_before_anything_runs(
    rig: Rig, run_id: str
) -> None:
    with pytest.raises(ValueError, match="run_id"):
        rig.profiler().profile([rig.workload()], run_id=run_id, commit=COMMIT)

    assert rig.events == []


def test_a_git_double_needs_its_own_fingerprint(rig: Rig) -> None:
    with pytest.raises(ValueError, match="fingerprint"):
        CProfiler(rig.project, git=rig.git)


# ---------------------------------------------------------------------------
# Real git, the real launcher, the dedupe fixture
# ---------------------------------------------------------------------------

_GIT_ENV: dict[str, str] = {
    "PATH": os.environ.get("PATH", os.defpath),
    "HOME": os.devnull,
    "LC_ALL": "C",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "Test User",
    "GIT_AUTHOR_EMAIL": "user@example.invalid",
    "GIT_COMMITTER_NAME": "Test User",
    "GIT_COMMITTER_EMAIL": "user@example.invalid",
    "GIT_AUTHOR_DATE": "@1700000000 +0000",
    "GIT_COMMITTER_DATE": "@1700000000 +0000",
}

CHECKOUT_BENCH = """import sys

sys.path.insert(0, {root!r})
from dedupe.core import unique_in_order

print(len(unique_in_order([i % 300 for i in range(3000)])))
"""


def git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(cwd), *args],
        env=_GIT_ENV,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr.decode(errors="replace")
    return proc.stdout.decode().strip()


@dataclass
class Real:
    repo: Path
    wt_root: Path
    commit: str
    project: Project

    def workload(self, *command: str) -> Workload:
        return Workload(
            project_id=self.project.id,
            name="dedupe",
            command=(sys.executable, *command),
            timeout_s=120.0,
        )

    def state(self) -> tuple[str, ...]:
        """What the user sees: HEAD, refs, status and the worktree list."""
        return (
            git(self.repo, "rev-parse", "HEAD"),
            git(self.repo, "for-each-ref"),
            git(self.repo, "status", "--porcelain", "--ignored"),
            git(self.repo, "worktree", "list", "--porcelain"),
        )


@pytest.fixture
def real(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Real:
    root = Path(os.path.realpath(tmp_path))
    wt_root = root / "wt-root"
    wt_root.mkdir()
    monkeypatch.setattr(settings, "WORKTREE_ROOT", wt_root)
    repo = root / "user"
    shutil.copytree(DEDUPE_REPO, repo, ignore=shutil.ignore_patterns("__pycache__"))
    (repo / "bench_checkout.py").write_text(CHECKOUT_BENCH.format(root=str(repo)))
    site = root / "site"
    site.mkdir()
    os.symlink(repo / "dedupe", site / "dedupe")
    (repo / "bench_linked.py").write_text(CHECKOUT_BENCH.format(root=str(site)))
    git(root, "init", "-q", "-b", "main", str(repo))
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    project = Project(name="dedupe", root_path=str(repo))
    return Real(repo, wt_root, git(repo, "rev-parse", "HEAD"), project)


def profile_dedupe(real: Real, mode: IsolationMode) -> None:
    before = real.state()
    workload = real.workload("-m", "dedupe.main")

    result = CProfiler(real.project, network=mode, fs=mode).profile(
        [workload], run_id=RUN_ID, commit=real.commit
    )

    top = result.hotspots[0]
    assert (top.file_path, top.symbol, top.line_start) == (
        "dedupe/core.py",
        "unique_in_order",
        6,
    )
    assert (top.calls, top.workload_id, top.project_id) == (
        1,
        workload.id,
        real.project.id,
    )
    assert top.share > 0.5
    assert {h.file_path for h in result.hotspots} <= {
        "dedupe/core.py",
        "dedupe/main.py",
        "dedupe/__init__.py",
    }
    assert result.notes == ()
    assert real.state() == before
    assert not (real.wt_root / RUN_ID).exists()


def test_real_profile_finds_the_dedupe_hotspot_and_leaves_nothing(real: Real) -> None:
    """
    GIVEN the dedupe fixture committed in a user repo
    WHEN `python -m dedupe.main` is profiled through the real launcher
        (isolation off: this runs on every platform)
    THEN the top hotspot is unique_in_order in dedupe/core.py with most of
        the time, every hotspot is a fixture file, there are no notes, and
        the user's repo and WORKTREE_ROOT/<run> are as before
    """
    profile_dedupe(real, "off")


def _require() -> bool:
    return "1" in (
        os.environ.get("REQUIRE_NETWORK_SANDBOX"),
        os.environ.get("REQUIRE_FS_SANDBOX"),
    )


def _linux_sandbox_problem() -> str | None:
    if shutil.which("unshare") is None:
        return "unshare is not installed"
    probe = subprocess.run(
        [*UNSHARE_ARGV, "true"], capture_output=True, timeout=30, check=False
    )
    if probe.returncode != 0:
        detail = probe.stderr.decode(errors="replace")
        return f"{' '.join(UNSHARE_ARGV)} true failed: {detail}"
    try:
        launcher.default_ops().syscall(444, (None, 0, 1))
    except OSError as error:
        return f"Landlock is unavailable: {error}"
    return None


@pytest.fixture(scope="module")
def linux_sandbox() -> None:
    """Skip (or fail under REQUIRE_*) when this Linux host cannot sandbox."""
    problem = _linux_sandbox_problem()
    if problem is not None:
        if _require():
            pytest.fail(f"sandbox required but unavailable: {problem}")
        pytest.skip(problem)


@linux_only
@pytest.mark.usefixtures("linux_sandbox")
def test_real_sandboxed_profile_finds_the_dedupe_hotspot(real: Real) -> None:
    """
    GIVEN both isolation modes required
    WHEN the dedupe workload is profiled under unshare and Landlock
    THEN the shim could write its profile into the scratch root, the same
        hotspot is found with no notes (both modes applied), and nothing is
        left behind
    """
    profile_dedupe(real, "required")


@pytest.mark.parametrize(
    ("bench", "where"),
    [("bench_checkout.py", "user"), ("bench_linked.py", "site")],
    ids=["sys-path-entry", "symlinked-install"],
)
def test_real_editable_install_is_refused_naming_the_checkout_file(
    real: Real, bench: str, where: str
) -> None:
    """
    GIVEN a workload that puts the user's checkout first on sys.path (what an
        editable install does), or a directory outside it whose package is a
        link into it (a symlinked install), before importing the hot module
    WHEN it is profiled
    THEN EngineError names the dedupe/core.py frame it ran, and the user's
        repo and WORKTREE_ROOT/<run> are as before
    """
    before = real.state()
    workload = real.workload(bench)
    frame = str(real.repo.parent / where / "dedupe/core.py")

    with pytest.raises(EngineError, match=re.escape(frame)):
        CProfiler(real.project, network="off", fs="off").profile(
            [workload], run_id=RUN_ID, commit=real.commit
        )

    assert real.state() == before
    assert not (real.wt_root / RUN_ID).exists()


@dataclass
class TamperingRun:
    """The real ``run_once``, plus a branch created in the user's repo."""

    repo: Path

    def __call__(
        self,
        argv: Sequence[str],
        cwd: Path,
        env: Mapping[str, str],
        sandbox: SandboxPolicy,
        timeout_s: float,
        caps: OutputCaps,
        *,
        fresh_dirs: Sequence[Path] = (),
    ) -> RunSample:
        git(self.repo, "branch", "planted")
        return run_once(argv, cwd, env, sandbox, timeout_s, caps, fresh_dirs=fresh_dirs)


def test_real_tampering_during_the_profile_raises_and_cleans_up(real: Real) -> None:
    """
    GIVEN a run that creates a branch in the user's repo (what sandboxed
        code must never manage)
    WHEN the dedupe workload is profiled on the real git workspace
    THEN F1 differs from F0: RepoTamperedError, and the profile worktree and
        its dirs are still removed
    """
    profiler_ = CProfiler(
        real.project, network="off", fs="off", run=TamperingRun(real.repo)
    )

    with pytest.raises(RepoTamperedError):
        profiler_.profile(
            [real.workload("-m", "dedupe.main")], run_id=RUN_ID, commit=real.commit
        )

    assert git(real.repo, "worktree", "list", "--porcelain").count("worktree ") == 1
    assert not (real.wt_root / RUN_ID).exists()
