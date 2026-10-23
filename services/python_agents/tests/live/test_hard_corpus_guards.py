"""Offline guards of the hard live corpus (``tests/fixtures/live_corpus_hard``).

Not ``live``: these run in the normal suite and spend nothing. They prove the
hard corpus measures what it claims before a dollar is spent on it:

- the manifest matches the directories: 3 ``multi``, 3 ``large``, 2 ``trap``
  and 2 ``memory`` repositories, two hypotheses each (one aimed), the memory
  repositories with a peak-RSS goal that ``start_loop`` passes as the run's
  objective;
- the memory repositories also carry a wall-time ``metric_bound`` guardrail
  (at most ``MEMORY_WALL_MAX_DROP`` slower), so a memory win cannot be bought
  with unbounded runtime;
- every repository's suite passes; its reference fix (``_solutions``, outside
  every repository) keeps stdout and the tests and gains at least 30 % (wall
  time; peak RSS for the memory repositories, from ``wait4`` of the child as
  the engine's launcher wrapper accounts it, inside the wall-time bound), over
  a baseline of at least 0.3 s (best of 3 for time, median of 3 for RSS, the
  compared copies measured in turn so contention hits both; ``slow``);
- a ``multi`` repository's full fix reaches its manifest ``fix_gain`` and every
  fix that leaves one hot spot in place falls short of it, so a delivered gain
  that reaches it means every hot spot was removed (``slow``);
- a ``trap``'s naive fix keeps the tests green and changes stdout, so only the
  equivalence judge can reject it;
- a ``large`` repository spans ten or more modules and 800 or more lines, and
  its cost sits in a module ``main.py`` does not import;
- no fix or hint of one is inside a repository.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path

import httpx2
import pytest
from e2e.conftest import Isolation

from autonomous_ai_agents.common.config import settings
from autonomous_ai_agents.common.models import (
    METRIC_PEAK_RSS_BYTES,
    METRIC_WALL_TIME_S,
    ChangeClass,
    Direction,
    GuardrailKind,
    Objective,
    ObjectiveKind,
)
from autonomous_ai_agents.execution.procrun import maxrss_scale
from autonomous_ai_agents.optimization.anticheat import check_path
from autonomous_ai_agents.optimization.judges import MemoryJudge, SpeedJudge

from . import corpus
from .conftest import TEST_COMMAND, TESTS_DIR, LiveRun, guardrails, restore_host_key
from .corpus import (
    ATTACK_CORPUS,
    CORPUS,
    HARD_CORPUS,
    HARD_DIR,
    HARD_MANIFEST,
    HARD_RUN_CAP_USD,
    HARD_SOLUTIONS_DIR,
    MEMORY_WALL_MAX_DROP,
    MIN_FIX_GAIN,
    MODES,
    CorpusRepo,
    blind_hypothesis,
    mode_hypotheses,
    parse_hard_manifest,
    start_loop,
)
from .test_corpus_guards import (
    BASELINE_FLOOR_S,
    HINT_WORDS,
    NAME,
    RUN_TIMEOUT_S,
    _env,
    _files,
    _suite_passes,
)

MEMORY_HINTS = ("memory", "rss", "stream", "lazily", "generator", "yield")
CATEGORIES = {"multi": 3, "large": 3, "trap": 2, "memory": 2}
LARGE_MIN_MODULES = 10
LARGE_MIN_LINES = 800  # package and tests together


def _ids(repos: Sequence[CorpusRepo]) -> list[str]:
    return [repo.name for repo in repos]


def _of(category: str) -> tuple[CorpusRepo, ...]:
    return tuple(repo for repo in HARD_CORPUS if repo.category == category)


MULTI, LARGE, TRAPS, MEMORY = (_of(c) for c in ("multi", "large", "trap", "memory"))


def _copy(repo: CorpusRepo, dest: Path) -> Path:
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


# The engine's launcher forks the workload from a small stdlib-only process,
# because a child's peak RSS starts at its parent's (exec keeps the high-water
# mark). Forking from pytest would floor every figure at pytest's own RSS, so
# the guard measures through the same kind of small wrapper: fork, exec,
# wait4, and the child's raw ru_maxrss on stderr.
_WRAPPER = """\
import os, sys
pid = os.fork()
if pid == 0:
    quiet = os.open(os.devnull, os.O_WRONLY)
    os.dup2(quiet, 2)
    os.execv(sys.argv[1], sys.argv[1:])
_, status, usage = os.wait4(pid, 0)
sys.stderr.write(f"{os.waitstatus_to_exitcode(status)} {usage.ru_maxrss}\\n")
"""


def _measure(root: Path, repo: CorpusRepo) -> tuple[str, float, int]:
    """One workload run: stdout, wall seconds and the workload's peak RSS in
    bytes, from ``wait4`` in a small forking wrapper as the launcher does."""
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
    seconds = time.perf_counter() - start
    assert proc.returncode == 0, (repo.name, proc.stderr)
    code, maxrss = (int(field) for field in proc.stderr.split())
    assert code == 0, (repo.name, code)
    assert proc.stdout.strip(), "the workload printed nothing"
    return proc.stdout, seconds, maxrss * maxrss_scale(sys.platform)


def _runs(
    roots: Sequence[Path], repo: CorpusRepo, count: int = 3
) -> list[tuple[str, float, float]]:
    """``count`` runs of each copy in ``roots``, in turn (A B C A B C ...),
    so a burst of contention lands on every compared copy alike; per copy:
    the one stdout its runs printed, the best (lowest) seconds and the
    median peak RSS. The best time, not the median: the normal suite runs
    under xdist beside other tests, and contention only ever adds time, so
    the minimum is the closest to the uncontended cost on both sides of
    every gain these guards compare."""
    runs: list[list[tuple[str, float, int]]] = [[] for _ in roots]
    for _ in range(count):
        for index, root in enumerate(roots):
            runs[index].append(_measure(root, repo))
    out: list[tuple[str, float, float]] = []
    for found in runs:
        outputs = {text for text, _, _ in found}
        assert len(outputs) == 1, f"{repo.name}: the output changed between runs"
        seconds = min(s for _, s, _ in found)
        out.append((outputs.pop(), seconds, statistics.median(r for *_, r in found)))
    return out


def test_runs_measure_the_compared_copies_in_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Base and fix are never timed in separate batches (the flake behind a
    partial fix that once looked like the full one under xdist)."""
    order: list[str] = []
    timing = {"base": [3.0, 1.0, 2.0], "fixed": [0.5, 0.4, 0.6]}

    def fake(root: Path, repo: CorpusRepo) -> tuple[str, float, int]:
        order.append(root.name)
        return "same\n", timing[root.name].pop(0), len(order)

    monkeypatch.setattr(sys.modules[__name__], "_measure", fake)
    roots = [tmp_path / "base", tmp_path / "fixed"]
    (base, fixed) = _runs(roots, HARD_CORPUS[0])
    assert order == ["base", "fixed"] * 3
    assert base == ("same\n", 1.0, 3.0) and fixed == ("same\n", 0.4, 4.0)


# ---------------------------------------------------------------------------
# The manifest and the directories
# ---------------------------------------------------------------------------


def test_hard_manifest_lists_every_directory() -> None:
    dirs = {p.name for p in HARD_DIR.iterdir() if p.is_dir()} - {"_solutions"}
    dirs.discard("__pycache__")
    assert dirs == {repo.name for repo in HARD_CORPUS}
    assert len({r.name for r in HARD_CORPUS}) == len(HARD_CORPUS)
    assert len({r.package for r in HARD_CORPUS}) == len(HARD_CORPUS)
    others = {r.package for r in (*CORPUS, *ATTACK_CORPUS)}
    assert not others & {r.package for r in HARD_CORPUS}


def test_hard_corpus_has_its_categories_goals_and_cap() -> None:
    counts = {c: len(_of(c)) for c in CATEGORIES}
    assert counts == CATEGORIES and len(HARD_CORPUS) == 10
    assert HARD_RUN_CAP_USD == 5.0
    for repo in HARD_CORPUS:
        assert (repo.kind, repo.expected, repo.root) == ("slowdown", "win", HARD_DIR)
        assert repo.attack is None
        assert repo.goal == ("peak_memory" if repo.category == "memory" else "runtime")
        assert repo.metric == (
            METRIC_PEAK_RSS_BYTES if repo.category == "memory" else METRIC_WALL_TIME_S
        )
        if repo.category == "multi":
            assert repo.fix_gain > MIN_FIX_GAIN, repo.name
        else:
            assert repo.fix_gain == MIN_FIX_GAIN, repo.name
        assert repo.solution == HARD_SOLUTIONS_DIR / f"{repo.name}.patch"


@pytest.mark.parametrize("repo", HARD_CORPUS, ids=_ids(HARD_CORPUS))
def test_hard_repo_is_well_formed(repo: CorpusRepo) -> None:
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


def test_hard_manifest_round_trips_and_malformed_entries_are_refused() -> None:
    data = json.loads(HARD_MANIFEST.read_text(encoding="utf-8"))
    assert parse_hard_manifest(data) == HARD_CORPUS
    entry = data["repos"][0]
    bad: list[object] = [
        {"repos": None},
        {"repos": [{**entry, "kind": "slowdown"}]},
        {"repos": [{k: v for k, v in entry.items() if k != "goal"}]},
        {"repos": [{**entry, "category": "single"}]},
        {"repos": [{**entry, "goal": "energy"}]},
        {"repos": [{**entry, "fix_gain": "0.5"}]},
        {"repos": [{**entry, "fix_gain": True}]},
        {"repos": [{**entry, "fix_gain": 0}]},
        {"repos": [{**entry, "fix_gain": 1.0}]},
        {"repos": [{**entry, "hypotheses": entry["hypotheses"] * 2}]},
    ]
    for case in bad:
        with pytest.raises(ValueError, match="manifest"):
            parse_hard_manifest(case)
    other = parse_hard_manifest({"repos": [entry]}, root=Path("/elsewhere"))
    assert other[0].path == Path("/elsewhere") / entry["name"]


# ---------------------------------------------------------------------------
# What the engine is handed: objectives and the candidates of each mode
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("repo", HARD_CORPUS, ids=_ids(HARD_CORPUS))
def test_each_mode_offers_its_hypotheses(repo: CorpusRepo, tmp_path: Path) -> None:
    assert mode_hypotheses(repo, "aimed") == repo.hypotheses
    assert mode_hypotheses(repo, "blind") == (blind_hypothesis(repo.goal),)
    (decoy,) = mode_hypotheses(repo, "decoy")
    assert not decoy.aimed and decoy in repo.hypotheses
    project = repo.project(tmp_path)
    objectives = repo.objectives(project)
    shared = guardrails(project)
    found = repo.guardrails(project)
    assert [(g.kind, g.metric) for g in found[: len(shared)]] == [
        (g.kind, g.metric) for g in shared
    ]
    if repo.goal == "runtime":
        assert objectives == []  # the engine default: wall time, RSS bounded
        assert len(found) == len(shared)  # the engine adds the RSS bound
        return
    (bound,) = found[len(shared) :]
    assert (bound.kind, bound.metric, bound.direction, bound.max_drop) == (
        GuardrailKind.metric_bound,
        METRIC_WALL_TIME_S,
        Direction.minimize,
        MEMORY_WALL_MAX_DROP,
    )
    assert bound.project_id == project.id
    assert MEMORY_WALL_MAX_DROP == 1.0  # at most twice as slow
    (objective,) = objectives
    assert (objective.kind, objective.metric, objective.direction) == (
        ObjectiveKind.peak_memory,
        METRIC_PEAK_RSS_BYTES,
        Direction.minimize,
    )
    assert objective.project_id == project.id
    assert objective.min_relative_gain == settings.MIN_RELATIVE_GAIN
    assert MemoryJudge().applies_to(objective)
    assert not SpeedJudge().applies_to(objective)  # wall time is not judged
    assert blind_hypothesis(repo.goal).title == "shrink-peak-memory"


def _no_wire(request: httpx2.Request) -> httpx2.Response:
    raise AssertionError(f"building the loop sent {request.url}")


_RAN = object()


class _Recorded:
    """Stands in for ``Orchestrator`` in ``Loop.run``: records what it is
    handed instead of running the engine."""

    calls: list[tuple[object, ...]] = []

    def __init__(self, *, context: object) -> None:
        self.context = context

    def run(self, *args: object, **kwargs: object) -> object:
        self.calls.append((self.context, *args, kwargs))
        return _RAN


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(
    "repo", (MEMORY[0], LARGE[0]), ids=[MEMORY[0].name, LARGE[0].name]
)
def test_start_loop_hands_the_engine_the_mode_and_the_goal(
    repo: CorpusRepo, mode: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The production wiring (``build_context`` on the captured transport,
    the ``required`` sandbox); only the wire is a mock and the engine run is
    recorded instead of started."""
    root = Path(os.path.realpath(tmp_path))
    monkeypatch.setattr(settings, "WORKTREE_ROOT", root / "wt-root")
    restore_host_key(monkeypatch, "dry-run-key")
    run = LiveRun("dry", HARD_RUN_CAP_USD, wire=httpx2.MockTransport(_no_wire))
    chosen = next(m for m in MODES if m == mode)
    loop = start_loop(repo, run, root, Isolation("required", None), mode=chosen)
    assert loop.mode == mode and loop.cap_usd == HARD_RUN_CAP_USD
    titles = [h.title for h in loop.candidates]
    assert titles == [s.title for s in mode_hypotheses(repo, chosen)]
    assert tuple(loop.context.candidates) == loop.candidates
    assert {h.change_class for h in loop.candidates} == {ChangeClass.efficiency}
    monkeypatch.setattr(corpus, "Orchestrator", _Recorded)
    _Recorded.calls = []
    ran: object = loop.run()
    assert ran is _RAN
    ((context, project, workloads, objectives, handed, kwargs),) = _Recorded.calls
    assert context is loop.context and project == loop.project
    assert workloads == [loop.workload]
    assert isinstance(objectives, list)

    def shape(found: Sequence[Objective]) -> list[tuple[object, ...]]:
        return [(o.project_id, o.kind, o.metric, o.direction) for o in found]

    assert shape(objectives) == shape(repo.objectives(loop.project))
    assert len(objectives) == (repo.goal == "peak_memory")
    assert isinstance(handed, list)
    assert [(g.kind, g.metric, g.max_drop) for g in handed] == [
        (g.kind, g.metric, g.max_drop) for g in repo.guardrails(loop.project)
    ]
    assert len(handed) == 2 + (repo.goal == "peak_memory")
    assert kwargs == {"max_cost_usd": HARD_RUN_CAP_USD}
    assert run.capture.exchanges == [] and run.records == []


def test_the_hard_live_module_mirrors_the_benchmark_corpus() -> None:
    source = (TESTS_DIR / "live" / "test_hard_corpus_live.py").read_text(
        encoding="utf-8"
    )
    assert "pytestmark = pytest.mark.live" in source
    assert "live(HARD_RUN_CAP_USD)" in source
    assert '"repo", HARD_CORPUS' in source
    assert "check_loop_guards(loop, run, slot.result, live_isolation)" in source


# ---------------------------------------------------------------------------
# The repositories run: suites pass, fixes win, traps are real
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("repo", HARD_CORPUS, ids=_ids(HARD_CORPUS))
def test_hard_repo_suite_passes(repo: CorpusRepo, tmp_path: Path) -> None:
    _suite_passes(_copy(repo, tmp_path / repo.name))


@pytest.mark.slow
@pytest.mark.parametrize("repo", HARD_CORPUS, ids=_ids(HARD_CORPUS))
def test_reference_fix_keeps_output_and_tests_and_gains(
    repo: CorpusRepo, tmp_path: Path
) -> None:
    base = _copy(repo, tmp_path / "base")
    fixed = _copy(repo, tmp_path / "fixed")
    _apply(fixed, repo.solution)
    assert _files(fixed) == [fixed / p.relative_to(base) for p in _files(base)]
    (before, slow, base_rss), (after, quick, fixed_rss) = _runs([base, fixed], repo)
    assert before == after, f"{repo.name}: the fix changed the output"
    _suite_passes(fixed)
    assert slow >= BASELINE_FLOOR_S, f"{repo.name}: baseline {slow:.2f}s"
    if repo.goal == "peak_memory":
        assert fixed_rss < 48 * 2**20, "the wrapper's own RSS leaked into the figure"
        gain = 1 - fixed_rss / base_rss
        detail = f"{base_rss / 2**20:.1f} MiB -> {fixed_rss / 2**20:.1f} MiB"
        slower = quick / slow - 1  # what the wall-time guardrail judges
        assert slower <= MEMORY_WALL_MAX_DROP / 2, (repo.name, slow, quick)
    else:
        gain = 1 - quick / slow
        detail = f"{slow:.2f}s -> {quick:.2f}s"
    assert gain >= max(MIN_FIX_GAIN, repo.fix_gain), f"{repo.name}: {detail}"


def _parts(repo: CorpusRepo) -> list[Path]:
    return sorted(HARD_SOLUTIONS_DIR.glob(f"{repo.name}.part*.patch"))


@pytest.mark.slow
@pytest.mark.parametrize("repo", MULTI, ids=_ids(MULTI))
def test_a_fix_that_leaves_one_hot_spot_falls_short(
    repo: CorpusRepo, tmp_path: Path
) -> None:
    """So a delivered gain of ``fix_gain`` means every hot spot was removed."""
    parts = _parts(repo)
    assert len(parts) in (2, 3), repo.name
    roots = [_copy(repo, tmp_path / "base")]
    for left in range(len(parts)):
        partial = _copy(repo, tmp_path / f"without-{left + 1}")
        for index, patch in enumerate(parts):
            if index != left:
                _apply(partial, patch)
        roots.append(partial)
    (expected, slow, _), *partials = _runs(roots, repo)
    for left, (output, quick, _) in enumerate(partials):
        assert output == expected, (repo.name, parts[left].name)
        gain = 1 - quick / slow
        assert gain < repo.fix_gain, (repo.name, parts[left].name, gain)


@pytest.mark.parametrize("repo", TRAPS, ids=_ids(TRAPS))
def test_a_trap_naive_fix_keeps_the_tests_and_changes_stdout(
    repo: CorpusRepo, tmp_path: Path
) -> None:
    base = _copy(repo, tmp_path / "base")
    naive = _copy(repo, tmp_path / "naive")
    _apply(naive, HARD_SOLUTIONS_DIR / f"{repo.name}.naive.patch")
    _suite_passes(naive)  # the tests cannot tell: only equivalence can
    before, _, _ = _measure(base, repo)
    after, _, _ = _measure(naive, repo)
    assert before != after, f"{repo.name}: the naive fix keeps stdout"
    assert len(before.splitlines()) == len(after.splitlines())


# ---------------------------------------------------------------------------
# Larger repositories and what the engine sees: no fix, no hint
# ---------------------------------------------------------------------------


def _changed_files(patch: Path) -> set[str]:
    text = patch.read_text(encoding="utf-8")
    return set(re.findall(r"^\+\+\+ b/(\S+)$", text, re.MULTILINE))


@pytest.mark.parametrize("repo", LARGE, ids=_ids(LARGE))
def test_a_large_repo_hides_its_cost_away_from_main(repo: CorpusRepo) -> None:
    modules = [p for p in _files(repo.path / repo.package) if p.suffix == ".py"]
    assert len(modules) >= LARGE_MIN_MODULES, repo.name
    lines = sum(
        len(p.read_text(encoding="utf-8").splitlines())
        for p in _files(repo.path)
        if p.suffix == ".py"
    )
    assert LARGE_MIN_LINES <= lines <= 2000, (repo.name, lines)
    main = (repo.path / repo.package / "main.py").read_text(encoding="utf-8")
    imported = set(re.findall(rf"^from {repo.package}\.(\w+) import", main, re.M))
    for changed in _changed_files(repo.solution):
        module = Path(changed).stem
        assert module != "main" and module not in imported, (repo.name, changed)


def test_solutions_live_outside_the_hard_repositories() -> None:
    expected = {f"{r.name}.patch" for r in HARD_CORPUS}
    expected |= {f"{r.name}.naive.patch" for r in TRAPS}
    expected |= {p.name for r in MULTI for p in _parts(r)}
    assert {p.name for p in HARD_SOLUTIONS_DIR.iterdir()} == expected
    for repo in MULTI:
        parts = _parts(repo)
        assert [p.name for p in parts] == [
            f"{repo.name}.part{k}.patch" for k in range(1, len(parts) + 1)
        ]
        full = _changed_files(repo.solution)
        assert set().union(*(_changed_files(p) for p in parts)) == full
    for repo in HARD_CORPUS:
        assert not repo.path.is_relative_to(HARD_SOLUTIONS_DIR)
        for path in _files(repo.path):
            assert path.suffix not in {".patch", ".diff", ".orig", ".rej"}, path
            assert path.name != ".env" and not path.name.endswith(".pem"), path


@pytest.mark.parametrize("repo", HARD_CORPUS, ids=_ids(HARD_CORPUS))
def test_hard_repo_carries_no_hint_of_the_fix(repo: CorpusRepo) -> None:
    for path in _files(repo.path):
        text = path.read_text(encoding="utf-8").casefold()
        found = [w for w in (*HINT_WORDS, *MEMORY_HINTS) if w in text]
        assert not found, (path, found)
        assert "ignore" not in text and "editor" not in text, path  # no injection
