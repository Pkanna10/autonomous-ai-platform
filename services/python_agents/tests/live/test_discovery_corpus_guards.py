"""Offline guards of hard corpus v2 (``tests/fixtures/live_corpus_discovery``).

Not ``live``: these run in the normal suite and spend nothing. They prove that
v2 measures what it claims before L5a spends on it:

- the manifest matches the directories: two repositories in each of the six
  groups, the decoys controls, the slowdowns with a ``fix_gain`` (5-15 % for
  ``small``, above that for the rest), two hypotheses each (one aimed);
- every suite passes; every reference fix (``_solutions``, outside every
  repository) keeps stdout and the tests and reaches its ``fix_gain``, over a
  baseline of at least 0.3 s; the textbook first idea keeps them too and falls
  short of it; a ``small`` fix stays small; a decoy's tempting idea gains
  nothing measurable (``slow``);
- each group's shape, from the profile the engine ranks by (project frames by
  self time): ``deep``'s dominant frame is a builtin three or more calls below
  ``main``; no ``spread`` hotspot holds 10 % and the fix changes six or more
  functions; ``misleading``'s fix is at hotspot rank 3 or lower; a decoy's
  project code holds at most 5 % of the self time (``slow``);
- no fix or hint of one is inside a repository.

Gains are child CPU time (``wait4`` rusage, best of the runs, the compared
copies measured in turn): the workloads are single-threaded, so it tracks wall
time, and it ignores the time a loaded runner (xdist, other jobs) keeps a
process waiting, which wall time would add to one side at random.
"""

from __future__ import annotations

import ast
import json
import math
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import httpx2
import pytest

from autonomous_ai_agents.optimization.anticheat import check_path

from .conftest import TEST_COMMAND, LiveRun
from .corpus import (
    ATTACK_CORPUS,
    CORPUS,
    HARD_CORPUS,
    MIN_FIX_GAIN,
    blind_hypothesis,
    mode_hypotheses,
    outcome_of,
    render_summary,
)
from .discovery import ArmResult
from .discovery_ab import AB_ARM, ab_row
from .discovery_corpus import (
    DISCOVERY_CORPUS,
    DISCOVERY_DIR,
    DISCOVERY_MANIFEST,
    DISCOVERY_SOLUTIONS_DIR,
    GROUPS,
    TEXTBOOK_GROUPS,
    DiscoveryRepo,
    of_group,
    parse_discovery_manifest,
)
from .discovery_grader import SOLUTION_DIRS, reference_patches
from .discovery_sweep import sweep_row
from .test_corpus_guards import (
    BASELINE_FLOOR_S,
    HINT_WORDS,
    NAME,
    RUN_TIMEOUT_S,
    _env,
    _files,
    _no_wire,
    _suite_passes,
)

PER_GROUP = 2
SMALL_BAND = (0.05, 0.15)  # a small fix's design gain (research section 8)
SMALL_MAX_GAIN = 0.25  # what a small fix may measure, with noise
DECOY_MAX_GAIN = 0.05  # a decoy's tempting idea; the engine's floor is 0.02
DECOY_PROJECT_SHARE = 0.05  # the self time a decoy's own code may hold
DEEP_MIN_SHARE = 0.4  # the dominant builtin frame of a deep repository
DEEP_MIN_DEPTH = 3  # calls from main down to it
SPREAD_MAX_SHARE = 0.10
SPREAD_MIN_FUNCTIONS = 6
MISLEADING_MIN_RANK = 3
RUNS = 3  # per copy, for the large gains
QUIET_RUNS = 9  # per copy, for small gains and decoys

SLOWDOWNS = tuple(repo for repo in DISCOVERY_CORPUS if repo.category != "decoy")
DEEP, SPREAD, MISLEADING, DECOYS = (
    of_group(g) for g in ("deep", "spread", "misleading", "decoy")
)


def _ids(repos: Sequence[DiscoveryRepo]) -> list[str]:
    return [repo.name for repo in repos]


def _copy(repo: DiscoveryRepo, dest: Path) -> Path:
    shutil.copytree(repo.path, dest, ignore=shutil.ignore_patterns("__pycache__"))
    return dest


def _apply(root: Path, patch: Path) -> None:
    proc = subprocess.run(
        ["git", "apply", "--whitespace=error", "-"],
        cwd=root,
        input=patch.read_text(encoding="utf-8"),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, (patch.name, proc.stderr)


def _textbook(repo: DiscoveryRepo) -> Path:
    patch = repo.textbook
    assert patch is not None, repo.name
    return patch


# ---------------------------------------------------------------------------
# Measuring: stdout, wall and child CPU seconds
# ---------------------------------------------------------------------------

# Fork and exec from a small stdlib-only process and report the child's own
# rusage, so pytest's CPU time never enters the figure.
_WRAPPER = """\
import os, sys
pid = os.fork()
if pid == 0:
    quiet = os.open(os.devnull, os.O_WRONLY)
    os.dup2(quiet, 2)
    os.execv(sys.argv[1], sys.argv[1:])
_, status, usage = os.wait4(pid, 0)
cpu = usage.ru_utime + usage.ru_stime
sys.stderr.write(f"{os.waitstatus_to_exitcode(status)} {cpu!r}\\n")
"""


def _measure(root: Path, repo: DiscoveryRepo) -> tuple[str, float, float]:
    argv = [sys.executable, "-I", "-S", "-c", _WRAPPER, sys.executable]
    argv += ["-m", f"{repo.package}.main"]
    start = time.perf_counter()
    proc = subprocess.run(
        argv,
        cwd=root,
        env=_env(root),
        capture_output=True,
        text=True,
        timeout=RUN_TIMEOUT_S,
        check=False,
    )
    wall = time.perf_counter() - start
    assert proc.returncode == 0, (repo.name, proc.stderr)
    code, cpu = proc.stderr.split()
    assert code == "0", (repo.name, code)
    assert proc.stdout.strip(), "the workload printed nothing"
    return proc.stdout, wall, float(cpu)


@dataclass(frozen=True)
class Timed:
    output: str
    wall: float  # best seconds
    cpu: float  # best child CPU seconds


def _runs(roots: Sequence[Path], repo: DiscoveryRepo, count: int) -> list[Timed]:
    """``count`` runs of each copy, in turn (A B C A B C ...), so a burst of
    contention lands on every compared copy alike; the one stdout of each
    copy's runs and its best wall and CPU seconds."""
    found: list[list[tuple[str, float, float]]] = [[] for _ in roots]
    for _ in range(count):
        for index, root in enumerate(roots):
            found[index].append(_measure(root, repo))
    out: list[Timed] = []
    for runs in found:
        outputs = {text for text, _, _ in runs}
        assert len(outputs) == 1, f"{repo.name}: the output changed between runs"
        out.append(
            Timed(outputs.pop(), min(r[1] for r in runs), min(r[2] for r in runs))
        )
    return out


def _gain(base: Timed, other: Timed) -> float:
    return 1 - other.cpu / base.cpu


def _decoy_bound(base: Timed, twin: Timed) -> float:
    """What a decoy's tempting idea may measure: DECOY_MAX_GAIN, or twice the
    A/A gap between the base and its unchanged twin when contention is wider."""
    return max(DECOY_MAX_GAIN, 2 * abs(_gain(base, twin)))


def test_runs_measure_the_compared_copies_in_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    order: list[str] = []
    cpu = {"base": [3.0, 1.0], "fixed": [0.5, 0.4]}

    def fake(root: Path, repo: DiscoveryRepo) -> tuple[str, float, float]:
        order.append(root.name)
        return "same\n", 9.0 - len(order), cpu[root.name].pop(0)

    monkeypatch.setattr(sys.modules[__name__], "_measure", fake)
    roots = [tmp_path / "base", tmp_path / "fixed"]
    base, fixed = _runs(roots, DISCOVERY_CORPUS[0], 2)
    assert order == ["base", "fixed"] * 2
    assert base == Timed("same\n", 6.0, 1.0) and fixed == Timed("same\n", 5.0, 0.4)
    assert _gain(base, fixed) == pytest.approx(0.6)


def test_a_decoy_bound_widens_only_by_the_measured_noise() -> None:
    """The engine's own rule (a gain must clear twice the A/A gap): on a quiet
    machine the bound is DECOY_MAX_GAIN, under contention twice the gap the
    base's twin measured in the same interleaved runs, whichever way it went."""
    base = Timed("same\n", 1.0, 1.0)
    assert _decoy_bound(base, Timed("same\n", 1.0, 0.99)) == DECOY_MAX_GAIN
    assert _decoy_bound(base, Timed("same\n", 1.0, 0.96)) == pytest.approx(0.08)
    assert _decoy_bound(base, Timed("same\n", 1.0, 1.04)) == pytest.approx(0.08)


@pytest.mark.parametrize("repo", DECOYS[:1], ids=_ids(DECOYS[:1]))
def test_measure_reports_the_child_cpu_time(
    repo: DiscoveryRepo, tmp_path: Path
) -> None:
    output, wall, cpu = _measure(_copy(repo, tmp_path / repo.name), repo)
    assert output.endswith("\n")
    assert 0 < cpu <= wall + 0.05  # one single-threaded child, not pytest


# ---------------------------------------------------------------------------
# The profile the engine ranks by, and the functions a patch changes
# ---------------------------------------------------------------------------

_PROFILER = """\
import cProfile, json, os, pstats, runpy, sys
out, package = sys.argv[1], sys.argv[2]
profile = cProfile.Profile()
sys.stdout = open(os.devnull, "w")
profile.enable()
runpy.run_module(package + ".main", run_name="__main__")
profile.disable()
rows = [
    [list(key), self_s, [list(caller) for caller in callers]]
    for key, (_, _, self_s, _, callers) in pstats.Stats(profile).stats.items()
]
with open(out, "w") as handle:
    json.dump(rows, handle)
"""

Key = tuple[str, int, str]  # file, first line, function


@dataclass(frozen=True)
class Frame:
    key: Key
    self_s: float
    callers: frozenset[Key]


def _key(value: object) -> Key:
    assert isinstance(value, list) and len(value) == 3, value
    file, line, name = value
    assert isinstance(file, str) and isinstance(line, int) and isinstance(name, str)
    return file, line, name


def _profile(root: Path, repo: DiscoveryRepo) -> list[Frame]:
    """Every frame of one cProfile run of the workload in ``root``."""
    out = root.parent / f"{root.name}.profile.json"
    argv = [sys.executable, "-c", _PROFILER, str(out), repo.package]
    proc = subprocess.run(
        argv,
        cwd=root,
        env=_env(root),
        capture_output=True,
        text=True,
        timeout=RUN_TIMEOUT_S * 2,
        check=False,
    )
    assert proc.returncode == 0, (repo.name, proc.stderr)
    rows = json.loads(out.read_text(encoding="utf-8"))
    assert isinstance(rows, list)
    frames: list[Frame] = []
    for row in rows:
        assert isinstance(row, list) and len(row) == 3, row
        key, self_s, callers = row
        assert isinstance(self_s, float | int) and isinstance(callers, list)
        frames.append(Frame(_key(key), float(self_s), frozenset(map(_key, callers))))
    return frames


def _project(frame: Frame, root: Path) -> str | None:
    """The frame's file relative to ``root`` when it is project code."""
    path = Path(frame.key[0])
    if not path.is_absolute() or not path.is_relative_to(root):
        return None
    return path.relative_to(root).as_posix()


def _total(frames: Sequence[Frame]) -> float:
    return math.fsum(frame.self_s for frame in frames)


def _hotspots(frames: Sequence[Frame], root: Path) -> list[tuple[Frame, str]]:
    """The project frames by self time, largest first, as the engine ranks
    them (``execution/profiler.py``)."""
    out: list[tuple[Frame, str]] = []
    for frame in sorted(frames, key=lambda f: (-f.self_s, f.key)):
        rel = _project(frame, root)
        if rel is not None and frame.self_s > 0:
            out.append((frame, rel))
    return out


def _depth(frames: Sequence[Frame], start: Key, target: Key) -> int | None:
    """The fewest calls from ``start`` down to ``target``."""
    below: dict[Key, set[Key]] = {}
    for frame in frames:
        for caller in frame.callers:
            below.setdefault(caller, set()).add(frame.key)
    seen, layer, depth = {start}, {start}, 0
    while layer:
        if target in layer:
            return depth
        layer = {k for key in layer for k in below.get(key, ()) if k not in seen}
        seen |= layer
        depth += 1
    return None


Function = tuple[str, str, int]  # file, name, first line


def _function_at(source: str, file: str, line: int) -> Function | None:
    """The innermost function of ``source`` whose lines hold ``line``."""
    found: Function | None = None
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            last = node.end_lineno or node.lineno
            inner = found is None or node.lineno > found[2]
            if node.lineno <= line <= last and inner:
                found = (file, node.name, node.lineno)
    return found


_HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+\d+(?:,\d+)? @@")


def _changed_lines(patch: str) -> dict[str, set[int]]:
    """Per file, the old lines a unified diff removes or inserts after."""
    changed: dict[str, set[int]] = {}
    file, old = "", 0
    for text in patch.splitlines():
        if text.startswith("--- "):
            continue
        if text.startswith("+++ b/"):
            file = text[len("+++ b/") :]
            continue
        if text.startswith("diff --git"):
            continue
        if found := _HUNK.match(text):
            old = int(found.group(1))
            continue
        if text.startswith("-"):
            changed.setdefault(file, set()).add(old)
            old += 1
        elif text.startswith("+"):
            changed.setdefault(file, set()).add(max(old - 1, 1))
        elif text.startswith(" "):
            old += 1
    return changed


def _changed_functions(root: Path, patch: Path) -> set[Function]:
    found: set[Function] = set()
    for file, lines in _changed_lines(patch.read_text(encoding="utf-8")).items():
        source = (root / file).read_text(encoding="utf-8")
        for line in lines:
            if (function := _function_at(source, file, line)) is not None:
                found.add(function)
    return found


_SAMPLE = """\
def first():
    return 1


def second():
    def inner():
        return 2
    return inner()
"""


def test_changed_functions_maps_hunks_to_the_innermost_function(
    tmp_path: Path,
) -> None:
    (tmp_path / "m.py").write_text(_SAMPLE, encoding="utf-8")
    patch = tmp_path / "x.patch"
    patch.write_text(
        "diff --git a/m.py b/m.py\n--- a/m.py\n+++ b/m.py\n"
        "@@ -1,2 +1,2 @@\n def first():\n-    return 1\n+    return 3\n"
        "@@ -6,3 +6,4 @@\n     def inner():\n         return 2\n+    pass\n"
        "     return inner()\n",
        encoding="utf-8",
    )
    assert _changed_lines(patch.read_text(encoding="utf-8")) == {"m.py": {2, 7}}
    assert _changed_functions(tmp_path, patch) == {
        ("m.py", "first", 1),
        ("m.py", "inner", 6),
    }
    assert _function_at(_SAMPLE, "m.py", 4) is None  # between functions


def test_depth_and_hotspots_follow_the_call_graph(tmp_path: Path) -> None:
    root = tmp_path / "r"
    main: Key = (str(root / "p" / "main.py"), 1, "main")
    mid: Key = (str(root / "p" / "a.py"), 3, "mid")
    builtin: Key = ("~", 0, "<built-in method builtins.sorted>")
    frames = [
        Frame(main, 0.1, frozenset()),
        Frame(mid, 0.2, frozenset({main})),
        Frame(builtin, 0.7, frozenset({mid})),
    ]
    assert _depth(frames, main, builtin) == 2
    assert _depth(frames, builtin, main) is None
    assert [rel for _, rel in _hotspots(frames, root)] == ["p/a.py", "p/main.py"]
    assert _total(frames) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# The manifest and the directories
# ---------------------------------------------------------------------------


def test_discovery_manifest_lists_every_directory() -> None:
    dirs = {p.name for p in DISCOVERY_DIR.iterdir() if p.is_dir()}
    dirs -= {"_solutions", "__pycache__"}
    assert dirs == {repo.name for repo in DISCOVERY_CORPUS}
    assert len({r.name for r in DISCOVERY_CORPUS}) == len(DISCOVERY_CORPUS)
    assert len({r.package for r in DISCOVERY_CORPUS}) == len(DISCOVERY_CORPUS)
    others = {r.package for r in (*CORPUS, *ATTACK_CORPUS, *HARD_CORPUS)}
    assert not others & {r.package for r in DISCOVERY_CORPUS}


def _manifest_groups() -> dict[str, str]:
    data = json.loads(DISCOVERY_MANIFEST.read_text(encoding="utf-8"))
    return {entry["name"]: entry["category"] for entry in data["repos"]}


def test_discovery_corpus_has_its_groups_kinds_and_gains() -> None:
    assert [len(of_group(g)) for g in GROUPS] == [PER_GROUP] * len(GROUPS)
    assert len(DISCOVERY_CORPUS) == 12 and len(SLOWDOWNS) == 10
    low, high = SMALL_BAND
    groups = _manifest_groups()
    for repo in DISCOVERY_CORPUS:
        assert repo.root == DISCOVERY_DIR and repo.attack is None
        assert (repo.goal, repo.category) == ("runtime", groups[repo.name])
        assert repo.solution == DISCOVERY_SOLUTIONS_DIR / f"{repo.name}.patch"
        if repo.category == "decoy":
            assert (repo.kind, repo.expected) == ("control", "none")
            assert repo.fix_gain == MIN_FIX_GAIN  # unused: a control has no fix
        else:
            assert (repo.kind, repo.expected) == ("slowdown", "win")
        if repo.category == "small":
            assert low <= repo.fix_gain <= high, repo.name
            assert repo.textbook is None
        else:
            assert repo.fix_gain > high, repo.name
            assert repo.textbook == (
                DISCOVERY_SOLUTIONS_DIR / f"{repo.name}.textbook.patch"
            )
    assert TEXTBOOK_GROUPS == set(GROUPS) - {"small"}


@pytest.mark.parametrize("repo", DISCOVERY_CORPUS, ids=_ids(DISCOVERY_CORPUS))
def test_discovery_repo_is_well_formed(repo: DiscoveryRepo) -> None:
    assert NAME.fullmatch(repo.name) and NAME.fullmatch(repo.package)
    assert repo.package not in sys.stdlib_module_names
    assert repo.workload_argv == ("python", "-m", f"{repo.package}.main")
    assert repo.test_argv == TEST_COMMAND
    assert (repo.path / "README.md").is_file()
    assert (repo.path / repo.package / "main.py").is_file()
    assert (repo.path / "tests" / "__init__.py").is_file()
    for path in _files(repo.path / repo.package):  # the code to improve is editable
        assert check_path(path.relative_to(repo.path).as_posix()) is None, path
    titles = [h.title for h in repo.hypotheses]
    assert len(set(titles)) == 2
    assert [h.aimed for h in repo.hypotheses].count(True) == 1
    for spec in repo.hypotheses:
        assert NAME.fullmatch(spec.title.replace("-", "_")), spec.title
        assert spec.rationale.strip() and "\n" not in spec.rationale


def test_discovery_manifest_round_trips_and_malformed_entries_are_refused() -> None:
    data = json.loads(DISCOVERY_MANIFEST.read_text(encoding="utf-8"))
    assert parse_discovery_manifest(data) == DISCOVERY_CORPUS
    entry = data["repos"][0]
    decoy = next(e for e in data["repos"] if e["category"] == "decoy")
    bad: list[object] = [
        {"repos": None},
        {"repos": ["booklist"]},
        {"repos": [{**entry, "category": "multi"}]},
        {"repos": [{k: v for k, v in entry.items() if k != "category"}]},
        {"repos": [{k: v for k, v in entry.items() if k != "fix_gain"}]},
        {"repos": [{**entry, "goal": "runtime"}]},
        {"repos": [{**entry, "fix_gain": "0.5"}]},
        {"repos": [{**entry, "fix_gain": True}]},
        {"repos": [{**entry, "fix_gain": 0}]},
        {"repos": [{**entry, "fix_gain": 1.0}]},
        {"repos": [{**entry, "name": " "}]},
        {"repos": [{**entry, "hypotheses": entry["hypotheses"][:1]}]},
        {"repos": [{**decoy, "fix_gain": 0.5}]},
    ]
    for case in bad:
        with pytest.raises(ValueError, match="manifest"):
            parse_discovery_manifest(case)
    (other,) = parse_discovery_manifest({"repos": [decoy]}, root=Path("/elsewhere"))
    assert other.path == Path("/elsewhere") / decoy["name"]
    assert (other.kind, other.category) == ("control", "decoy")


def test_every_recorder_carries_the_v2_group() -> None:
    """The group is the repository's ``category``, so the corpus outcome, the
    sweep row and the A/B row record it as they record a v1 category, and the
    summary prints one line per group (L4's v2 hit@1, L5a's P vs A per group)."""
    groups = _manifest_groups()
    run = LiveRun("dry", 1.0, wire=httpx2.MockTransport(_no_wire))
    arm = ArmResult(AB_ARM, (), 0.0, (), (), 0.0, None)
    outcomes = []
    for repo in DISCOVERY_CORPUS:
        outcome = outcome_of(repo, run, None, guard="ok", mode="blind")
        assert outcome.category == groups[repo.name]
        assert sweep_row(repo, arm, None, 0.0).category == groups[repo.name]
        row = ab_row(repo, 1, "A", arm, outcome, frozenset())
        assert row.category == groups[repo.name]
        outcomes.append(outcome)
    summary = render_summary("v2", outcomes)
    for group in GROUPS:
        assert f"Category {group}: delivered 0/{PER_GROUP};" in summary
    assert run.capture.exchanges == []


def test_the_grader_reads_each_v2_reference_fix_and_nothing_else() -> None:
    """L4 grades v2 ideas against ``<name>.patch`` alone: never the textbook
    idea, and nothing for a decoy."""
    assert DISCOVERY_SOLUTIONS_DIR in SOLUTION_DIRS
    for repo in DISCOVERY_CORPUS:
        patches = reference_patches(repo)
        if repo.kind == "control":
            assert patches == ()
            continue
        assert [p.name for p in patches] == [f"{repo.name}.patch"]
        assert patches[0].text == repo.solution.read_text(encoding="utf-8")


@pytest.mark.parametrize("repo", DISCOVERY_CORPUS, ids=_ids(DISCOVERY_CORPUS))
def test_each_mode_offers_its_hypotheses(repo: DiscoveryRepo) -> None:
    assert mode_hypotheses(repo, "aimed") == repo.hypotheses
    assert mode_hypotheses(repo, "blind") == (blind_hypothesis("runtime"),)
    (decoy,) = mode_hypotheses(repo, "decoy")
    assert not decoy.aimed and decoy in repo.hypotheses
    assert mode_hypotheses(repo, "wired") == ()


def test_solutions_live_outside_the_repositories() -> None:
    expected = {f"{r.name}.patch" for r in SLOWDOWNS}
    expected |= {f"{r.name}.textbook.patch" for r in DISCOVERY_CORPUS if r.textbook}
    assert {p.name for p in DISCOVERY_SOLUTIONS_DIR.iterdir()} == expected
    for repo in DISCOVERY_CORPUS:
        assert not repo.path.is_relative_to(DISCOVERY_SOLUTIONS_DIR)
        for path in _files(repo.path):
            assert path.suffix not in {".patch", ".diff", ".orig", ".rej"}, path
            assert path.name != ".env" and not path.name.endswith(".pem"), path


@pytest.mark.parametrize("repo", DISCOVERY_CORPUS, ids=_ids(DISCOVERY_CORPUS))
def test_discovery_repo_carries_no_hint_of_the_fix(repo: DiscoveryRepo) -> None:
    for path in _files(repo.path):
        text = path.read_text(encoding="utf-8").casefold()
        found = [word for word in HINT_WORDS if word in text]
        assert not found, (path, found)
        assert "ignore" not in text and "editor" not in text, path  # no injection


# ---------------------------------------------------------------------------
# The repositories run: suites pass, fixes win, textbook ideas fall short
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("repo", DISCOVERY_CORPUS, ids=_ids(DISCOVERY_CORPUS))
def test_discovery_repo_suite_passes(repo: DiscoveryRepo, tmp_path: Path) -> None:
    _suite_passes(_copy(repo, tmp_path / repo.name))


@pytest.mark.slow
@pytest.mark.parametrize("repo", SLOWDOWNS, ids=_ids(SLOWDOWNS))
def test_reference_fix_reaches_its_gain_and_the_textbook_falls_short(
    repo: DiscoveryRepo, tmp_path: Path
) -> None:
    base = _copy(repo, tmp_path / "base")
    fixed = _copy(repo, tmp_path / "fixed")
    _apply(fixed, repo.solution)
    roots = [base, fixed]
    if repo.textbook is not None:
        roots.append(_copy(repo, tmp_path / "textbook"))
        _apply(roots[-1], repo.textbook)
    for root in roots[1:]:
        assert _files(root) == [root / p.relative_to(base) for p in _files(base)]
        _suite_passes(root)
    count = QUIET_RUNS if repo.category == "small" else RUNS
    before, *after = _runs(roots, repo, count)
    assert before.wall >= BASELINE_FLOOR_S, f"{repo.name}: {before.wall:.2f}s"
    for other in after:
        assert other.output == before.output, f"{repo.name}: the output changed"
    gain = _gain(before, after[0])
    assert gain >= repo.fix_gain, (repo.name, before.cpu, after[0].cpu)
    if repo.category == "small":
        assert gain <= SMALL_MAX_GAIN, (repo.name, gain)
    else:
        textbook = _gain(before, after[1])
        assert textbook < repo.fix_gain, (repo.name, textbook, repo.fix_gain)


@pytest.mark.slow
@pytest.mark.parametrize("repo", DECOYS, ids=_ids(DECOYS))
def test_a_decoy_tempting_idea_gains_nothing(
    repo: DiscoveryRepo, tmp_path: Path
) -> None:
    base = _copy(repo, tmp_path / "base")
    twin = _copy(repo, tmp_path / "twin")  # the A/A noise of these same runs
    tempting = _copy(repo, tmp_path / "tempting")
    _apply(tempting, _textbook(repo))
    _suite_passes(tempting)
    before, again, after = _runs([base, twin, tempting], repo, QUIET_RUNS)
    assert before.wall >= BASELINE_FLOOR_S, f"{repo.name}: {before.wall:.2f}s"
    assert after.output == before.output, f"{repo.name}: the output changed"
    gain = _gain(before, after)  # a slower tempting idea gains nothing either
    bound = _decoy_bound(before, again)
    assert gain <= bound, (repo.name, before.cpu, again.cpu, after.cpu)


# ---------------------------------------------------------------------------
# Each group's shape, in the profile the engine ranks by
# ---------------------------------------------------------------------------


def _main_key(frames: Sequence[Frame], root: Path, repo: DiscoveryRepo) -> Key:
    main = f"{repo.package}/main.py"
    (key,) = (f.key for f in frames if _project(f, root) == main and f.key[2] == "main")
    return key


@pytest.mark.slow
@pytest.mark.parametrize("repo", DEEP, ids=_ids(DEEP))
def test_a_deep_cost_is_a_builtin_far_below_main(
    repo: DiscoveryRepo, tmp_path: Path
) -> None:
    root = _copy(repo, tmp_path / repo.name)
    frames = _profile(root, repo)
    top = max(frames, key=lambda f: f.self_s)
    assert _project(top, root) is None, top.key  # a builtin or the stdlib
    assert top.self_s / _total(frames) >= DEEP_MIN_SHARE, top
    depth = _depth(frames, _main_key(frames, root, repo), top.key)
    assert depth is not None and depth >= DEEP_MIN_DEPTH, (top.key, depth)


@pytest.mark.slow
@pytest.mark.parametrize("repo", SPREAD, ids=_ids(SPREAD))
def test_a_spread_cost_has_no_dominant_hotspot(
    repo: DiscoveryRepo, tmp_path: Path
) -> None:
    root = _copy(repo, tmp_path / repo.name)
    frames = _profile(root, repo)
    (top, rel), *_ = _hotspots(frames, root)
    share = top.self_s / _total(frames)
    assert share < SPREAD_MAX_SHARE, (rel, top.key, share)
    changed = _changed_functions(root, repo.solution)
    assert len(changed) >= SPREAD_MIN_FUNCTIONS, sorted(changed)


@pytest.mark.slow
@pytest.mark.parametrize("repo", MISLEADING, ids=_ids(MISLEADING))
def test_a_misleading_fix_sits_below_the_top_hotspots(
    repo: DiscoveryRepo, tmp_path: Path
) -> None:
    root = _copy(repo, tmp_path / repo.name)
    changed = _changed_functions(root, repo.solution)
    assert changed, repo.name
    ranked = _hotspots(_profile(root, repo), root)
    ranks: list[int] = []
    for rank, (frame, rel) in enumerate(ranked, 1):
        source = (root / rel).read_text(encoding="utf-8")
        if _function_at(source, rel, frame.key[1]) in changed:
            ranks.append(rank)
    assert ranks and min(ranks) >= MISLEADING_MIN_RANK, (repo.name, ranks)


@pytest.mark.slow
@pytest.mark.parametrize("repo", DECOYS, ids=_ids(DECOYS))
def test_a_decoy_spends_its_time_outside_the_project(
    repo: DiscoveryRepo, tmp_path: Path
) -> None:
    root = _copy(repo, tmp_path / repo.name)
    frames = _profile(root, repo)
    own = math.fsum(f.self_s for f, _ in _hotspots(frames, root))
    assert own / _total(frames) <= DECOY_PROJECT_SHARE, (repo.name, own)
