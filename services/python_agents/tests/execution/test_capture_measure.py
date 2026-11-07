"""The capture launch (emergence round 2, S4): its document, its rows and the
runners' ``shadow`` switch.

``parse_capture`` reads the shim's document strictly (the workload controls
the interpreter); ``capture_workload`` turns one launch into
``shadow_calls`` rows (the ``sequence`` leg, then one per point) and never
fails a trial: a launch that fails or writes no usable document is a note
and no row. With ``shadow`` a runner adds one capture launch per workload and
side after the counted runs; off (the default, ``SHADOW_VERIFY=off``)
nothing launches and every row is as before. Fakes: ``Clock`` stands for
``procrun.run_once`` (it answers the timed runs and the suite and writes
``doc(phase)`` for each capture launch), ``Edits`` for ``ClaudeEditor``; the
last tests run the real shim through the real ``run_once`` and real git,
isolation off, on ``wordpkg`` (``tests/fixtures/capture_words``).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from autonomous_ai_agents.clients.budget import Budget
from autonomous_ai_agents.common.config import IsolationMode, Settings, settings
from autonomous_ai_agents.common.models import (
    METRIC_TESTS_PASSED,
    METRIC_WALL_TIME_S,
    Baseline,
    ChangeClass,
    Direction,
    Hypothesis,
    HypothesisSource,
    Measurement,
    Objective,
    ObjectiveKind,
    Project,
    RunStats,
    Trial,
    TrialStatus,
    Workload,
)
from autonomous_ai_agents.execution import _capture_shim
from autonomous_ai_agents.execution.measure import (
    CAPTURE_SHIM,
    METRIC_SHADOW_CALLS,
    SHADOW_LEG_KEY,
    CountFormatError,
    capture_argv,
    parse_capture,
)
from autonomous_ai_agents.execution.procrun import OutputCaps, RunSample, run_once
from autonomous_ai_agents.execution.protocols import (
    CodeEditor,
    EditResult,
    EditTask,
    TrialBrief,
)
from autonomous_ai_agents.execution.sandbox import SandboxPolicy
from autonomous_ai_agents.execution.trial_runner import (
    GitBaselineRunner,
    GitTrialRunner,
)
from autonomous_ai_agents.optimization.anticheat import DEFAULT_PROTECTED_PATTERNS
from autonomous_ai_agents.optimization.idea_types import ShadowLabel
from autonomous_ai_agents.optimization.shadow_verify import shadow_reading

PY, TESTS = sys.executable, 1
WORDS = Path(__file__).resolve().parents[1] / "fixtures" / "capture_words"
BASE, MEMO, BOUNDED, REAL, LRU, BENCH = (
    (WORDS / f"{name}.py").read_text()
    for name in ("base", "memo", "bounded", "real", "lru", "bench")
)
CORE = "wordpkg/core.py"
SAME = BASE + "# same code, another commit\n"
ENV = {"PATH": os.defpath, "HOME": os.devnull, "GIT_CONFIG_GLOBAL": os.devnull}
ENV |= {"GIT_CONFIG_NOSYSTEM": "1", "LC_ALL": "C"}
ENV |= {f"GIT_{r}_{k}": v for r in ("AUTHOR", "COMMITTER") for k, v in
        (("NAME", "User"), ("EMAIL", "u@example.invalid"), ("DATE", "@1700000000 +0000"))}  # fmt: skip
CORPUS = "ab" * 32


def doc(sequence: int = 900, render: int = 300, **extra: object) -> dict[str, object]:
    point = {"point": "wordpkg.core.render", "calls": 120, "distinct": 3,
             "counted": render, "raised": 0}  # fmt: skip
    return {"version": 1, "corpus": CORPUS, "sequence": sequence, "skipped": 0,
            "points": [point], **extra}  # fmt: skip


def raw(value: object) -> bytes:
    return json.dumps(value).encode()


# ---------------------------------------------------------------------------
# parse_capture
# ---------------------------------------------------------------------------


def test_the_shims_document_parses_into_its_legs() -> None:
    captured = parse_capture(raw(doc()))

    assert (captured.corpus, captured.sequence, captured.skipped) == (CORPUS, 900, 0)
    [point] = captured.points
    assert (point.point, point.calls, point.distinct, point.counted, point.raised) == (
        "wordpkg.core.render", 120, 3, 300, 0,
    )  # fmt: skip


def _point(**change: object) -> dict[str, object]:
    found = doc()["points"]
    assert isinstance(found, list)
    return {**doc(), "points": [{**found[0], **change}]}


@pytest.mark.parametrize(
    ("data", "why"),
    [
        (b"x" * (_capture_shim.MAX_DOC_BYTES + 1), "larger than"),
        (b"{}" + "é".encode(), "not ASCII"),
        (b"{", "not valid JSON"),
        (b'{"version": 1, "version": 1}', "repeated key"),
        (b'{"version": NaN}', "not a number"),
        (raw({**doc(), "extra": 1}), "exactly"),
        (raw([1]), "exactly"),
        (raw({**doc(), "version": 2}), "version"),
        (raw({**doc(), "corpus": "AB" * 32}), "corpus"),
        (raw({**doc(), "sequence": -1}), "sequence"),
        (raw({**doc(), "skipped": True}), "skipped"),
        (raw({**doc(), "points": {}}), "points"),
        (raw({**doc(), "points": [_point()["points"][0]] * 9}), "points"),  # type: ignore[index]
        (raw({**doc(), "points": [1]}), "a point"),
        (raw(_point(raised=None)), "raised"),
        (raw(_point(point="render")), "module.function"),
        (raw(_point(point="a.b\n")), "module.function"),
        (raw(_point(point=7)), "module.function"),
        (
            raw(_point(point="m." + "x" * _capture_shim.MAX_NAME_CHARS)),
            "module.function",
        ),
        (raw(_point(distinct=121)), "distinct"),
        (raw(_point(raised=4)), "raised"),
    ],
)
def test_a_document_the_engine_cannot_trust_is_refused(data: bytes, why: str) -> None:
    with pytest.raises(CountFormatError, match=why):
        parse_capture(data)


def test_the_shims_own_cap_holds_its_largest_document() -> None:
    names = [f"m{'x' * (_capture_shim.MAX_NAME_CHARS - 4)}.f{i}" for i in range(_capture_shim.MAX_POINTS)]  # fmt: skip
    big = {"version": 1, "corpus": CORPUS, "sequence": 2**53, "skipped": 2**53,
           "points": [{"point": n, "calls": 2**53, "distinct": 2**53, "counted": 2**53,
                       "raised": 2**53} for n in names]}  # fmt: skip
    assert len(raw(big)) <= _capture_shim.MAX_DOC_BYTES
    assert len(parse_capture(raw(big)).points) == _capture_shim.MAX_POINTS


def test_the_capture_argv_puts_the_shim_and_the_root_before_the_target(tmp_path: Path) -> None:  # fmt: skip
    argv = capture_argv((PY, "-X", "utf8", "bench.py", "a"), tmp_path / "o.json", tmp_path)  # fmt: skip

    assert argv == [PY, "-X", "utf8", str(CAPTURE_SHIM), str(tmp_path / "o.json"),
                    str(tmp_path), "script", "bench.py", "a"]  # fmt: skip


# ---------------------------------------------------------------------------
# The runners, on fakes
# ---------------------------------------------------------------------------


def git(cwd: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(cwd), *args], env=ENV, capture_output=True)
    assert done.returncode == 0, done.stderr
    return done.stdout.decode().strip()


@dataclass
class Clock:
    """``run_once``: ``calls`` records each launch as ``<kind> <phase>`` (kind
    ``run``, ``suite`` or ``capture``); a capture launch writes ``doc(phase)``
    into its OUT, or exits 1 when it gives ``None``."""

    run_dir: Path
    doc: Callable[[str], bytes | None] = lambda phase: raw(doc())
    calls: list[str] = field(default_factory=list)

    def __call__(
        self, argv: Sequence[str], cwd: Path, env: Mapping[str, str],
        sandbox: SandboxPolicy, timeout_s: float, caps: OutputCaps, *,
        fresh_dirs: Sequence[Path] = (),
    ) -> RunSample:  # fmt: skip
        phase = cwd.relative_to(self.run_dir).parts[0]
        exit, err = 0, b""
        if "unittest" in argv:
            self.calls.append(f"suite {phase}")
            err = f"Ran {TESTS} tests in 0.010s\n\nOK\n".encode()
        elif str(CAPTURE_SHIM) in argv:
            self.calls.append(f"capture {phase}")
            written = self.doc(phase)
            if written is None:
                exit, err = 1, b"RecursionError: too deep\n"
            else:
                Path(argv[argv.index(str(CAPTURE_SHIM)) + 1]).write_bytes(written)
        else:
            self.calls.append(f"run {phase}")
        return RunSample(100_000_000, 0.1, 0.0, 1 << 20, exit, True, True, "1" * 64, b"", 0, err)  # fmt: skip


@dataclass
class Edits:
    text: str

    def edit(self, worktree: Path, task: EditTask, budget: Budget) -> EditResult:
        (worktree / CORE).write_text(self.text)
        return EditResult({CORE: len(self.text.encode())}, cost_usd=0.01, tokens_used=10)  # fmt: skip


@dataclass
class Rig:
    repo: Path
    base: str
    project: Project
    clock: Clock
    notes: list[str] = field(default_factory=list)
    network: IsolationMode = "required"
    run: object = None

    def workload(self) -> Workload:
        return Workload(project_id=self.project.id, name="words", warmup_runs=0, runs=5,
                        command=(PY, "bench.py"), timeout_s=60.0)  # fmt: skip

    def options(self) -> dict[str, object]:
        return {"network": self.network, "fs": self.network, "platform": "linux",
                "base_env": {"PATH": "/usr/bin"},
                "run": self.clock if self.run is None else self.run,
                "on_note": self.notes.append}  # fmt: skip

    def trial(self, text: str, **runner: bool) -> tuple[Trial, Hypothesis]:
        def build(*, module_roots: AbstractSet[str], reserved_modules: AbstractSet[str]) -> CodeEditor:  # fmt: skip
            return Edits(text)

        hypothesis = Hypothesis(
            project_id=self.project.id, source=HypothesisSource.novel, title="memo",
            rationale="r", change_class=ChangeClass.efficiency, expected_gain=0.5,
            provability=0.9, risk=0.1,
        )  # fmt: skip
        workloads = [self.workload()]
        trial = GitTrialRunner(self.project, editor=build, **self.options(), **runner).run(  # type: ignore[arg-type]
            hypothesis, workloads, self.baseline(workloads), round=1, budget_usd=1.0,
            branch=f"{settings.TRIAL_BRANCH_PREFIX}trial-run1-{hypothesis.id}",
            brief=TrialBrief(None, (), DEFAULT_PROTECTED_PATTERNS, fix_retries_left=1),
        )  # fmt: skip
        return trial, hypothesis

    def baseline(self, workloads: Sequence[Workload]) -> Baseline:
        rows = tuple(Measurement(workload_id=w.id, metric=METRIC_TESTS_PASSED,
                                 stats=RunStats.from_samples((1.0,), unit="bool"),
                                 samples=(1.0,), hardware={"tests_counted": TESTS})
                     for w in workloads)  # fmt: skip
        objective = Objective(project_id=self.project.id, kind=ObjectiveKind.runtime,
                              description="x", metric=METRIC_WALL_TIME_S,
                              direction=Direction.minimize)  # fmt: skip
        return Baseline(commit=self.base, measurements=rows, objectives=(objective,))


@pytest.fixture
def rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Rig:
    root = Path(os.path.realpath(tmp_path))
    monkeypatch.setattr(settings, "WORKTREE_ROOT", root / "wt-root")
    repo = root / "user"
    (repo / "wordpkg").mkdir(parents=True)
    (repo / "wordpkg" / "__init__.py").write_text("")
    (repo / "wordpkg" / "core.py").write_text(BASE)
    (repo / "bench.py").write_text(BENCH)
    (repo / "tests").mkdir()
    (repo / "tests" / "__init__.py").write_text("")
    (repo / "tests" / "test_core.py").write_text(
        "import unittest\nfrom wordpkg.core import render\n\n\n"
        "class T(unittest.TestCase):\n    def test_render(self):\n"
        "        self.assertEqual(render('ab', '-'), 'A-B')\n"
    )  # fmt: skip
    git(root, "init", "-q", "-b", "main", str(repo))
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    unittest = (PY, "-m", "unittest", "discover", "-s", "tests", "-t", ".")
    project = Project(name="words", root_path=str(repo), test_command=unittest)
    return Rig(repo, git(repo, "rev-parse", "HEAD"), project, Clock(root / "wt-root" / "run1"))  # fmt: skip


def shadow_rows(rows: Sequence[Measurement]) -> list[tuple[object, float]]:
    return [(m.hardware[SHADOW_LEG_KEY], m.samples[0]) for m in rows
            if m.metric == METRIC_SHADOW_CALLS]  # fmt: skip


def others(rows: Sequence[Measurement]) -> list[tuple[str, tuple[float, ...]]]:
    return [(m.metric, m.samples) for m in rows if m.metric != METRIC_SHADOW_CALLS]


def test_a_paired_trial_captures_the_twin_and_itself_after_the_suite(rig: Rig) -> None:
    """
    GIVEN a paired trial with ``shadow`` whose twin's legs count 900 / 300 and
        its own 400 / 320
    WHEN it runs
    THEN one capture launch on the twin, then one on the trial, after the
        suite; the twin's rows are base rows with no trial id, the trial's
        carry its id; the reading is ``repetition_fit``
    """
    rig.clock.doc = lambda p: raw(doc() if p.startswith("twin-") else doc(400, 320))

    trial, hypothesis = rig.trial(SAME, paired=True, shadow=True)

    a, b = f"twin-trial-{hypothesis.id}", f"trial-{hypothesis.id}"
    assert rig.clock.calls[-3:] == [f"suite {b}", f"capture {a}", f"capture {b}"]
    assert trial.status is TrialStatus.measured
    assert shadow_rows(trial.base_measurements) == [("sequence", 900.0), ("wordpkg.core.render", 300.0)]  # fmt: skip
    assert shadow_rows(trial.measurements) == [("sequence", 400.0), ("wordpkg.core.render", 320.0)]  # fmt: skip
    assert {m.trial_id for m in trial.measurements if m.metric == METRIC_SHADOW_CALLS} == {trial.id}  # fmt: skip
    assert {m.trial_id for m in trial.base_measurements if m.metric == METRIC_SHADOW_CALLS} == {None}  # fmt: skip
    reading = shadow_reading(trial.base_measurements, trial.measurements)
    assert reading.label is ShadowLabel.repetition_fit


def test_the_baseline_runner_captures_the_base(rig: Rig) -> None:
    runner = GitBaselineRunner(rig.project, **rig.options(), shadow=True)  # type: ignore[arg-type]

    rows = runner.measure([rig.workload()], run_id="run1", commit=rig.base)

    assert rig.clock.calls[-2:] == ["suite baseline", "capture baseline"]
    assert shadow_rows(rows) == [("sequence", 900.0), ("wordpkg.core.render", 300.0)]


@pytest.mark.parametrize("failing", ["twin-", "trial-"])
def test_a_failed_capture_is_a_note_and_leaves_every_other_row_as_off(
    rig: Rig, failing: str
) -> None:
    """Condition (a) of the correctness judge [87]: a capture launch that
    dies reads ``uncapturable`` and the trial's other rows, which the frozen
    judges read, are those of a run with the setting off."""
    rig.clock.doc = lambda p: None if p.startswith(failing) else raw(doc())

    off, _ = rig.trial(SAME, paired=True, shadow=False)
    on, hypothesis = rig.trial(SAME, paired=True, shadow=True)

    assert on.status is TrialStatus.measured and on.error is None
    assert others(on.measurements) == others(off.measurements)
    assert others(on.base_measurements) == others(off.base_measurements)
    assert shadow_reading(on.base_measurements, on.measurements).label is ShadowLabel.uncapturable  # fmt: skip
    side = "A" if failing == "twin-" else "B"
    prefix = f"trial for hypothesis {hypothesis.id}: workload 'words' {side} is not captured: "
    assert any(n.startswith(prefix) and "exit status 1" in n for n in rig.notes)


@pytest.mark.parametrize(
    ("written", "why"),
    [(b"", "is not valid JSON"), (raw({**doc(), "version": 9}), "version must be")],
)
def test_an_unusable_document_is_a_note_and_no_row(rig: Rig, written: bytes, why: str) -> None:  # fmt: skip
    rig.clock.doc = lambda p: written

    trial, _ = rig.trial(SAME, shadow=True)

    assert shadow_rows(trial.measurements) == []
    assert any(
        "is not captured: the capture output" in n and why in n for n in rig.notes
    )


def test_a_command_the_shim_cannot_run_is_a_note(rig: Rig) -> None:
    workload = rig.workload().model_copy(update={"command": ("make", "bench")})
    runner = GitBaselineRunner(rig.project, **rig.options(), shadow=True)  # type: ignore[arg-type]

    rows = runner.measure([workload], run_id="run1", commit=rig.base)

    assert shadow_rows(rows) == [] and not any(c.startswith("capture") for c in rig.clock.calls)  # fmt: skip
    assert any("is not captured:" in n for n in rig.notes)


@pytest.mark.parametrize("mode", ["off", "record"])
def test_shadow_defaults_to_the_shadow_verify_setting(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    monkeypatch.setattr(settings, "SHADOW_VERIFY", mode)

    trial, _ = rig.trial(SAME, paired=True)

    launched = [c for c in rig.clock.calls if c.startswith("capture")]
    assert len(launched) == (2 if mode == "record" else 0)
    assert bool(shadow_rows(trial.measurements)) is (mode == "record")


def test_the_setting_is_off_by_default_and_closed() -> None:
    assert Settings(_env_file=None).SHADOW_VERIFY == "off"
    with pytest.raises(ValueError, match="SHADOW_VERIFY"):
        Settings(_env_file=None, SHADOW_VERIFY="on")


# ---------------------------------------------------------------------------
# The real shim, run_once and git
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform != "linux", reason="isolation off is Linux's")
@pytest.mark.parametrize(
    ("text", "label"),
    [
        (SAME, ShadowLabel.no_count_gain),
        (MEMO, ShadowLabel.repetition_fit),
        (BOUNDED, ShadowLabel.repetition_fit),
        (LRU, ShadowLabel.repetition_fit),
        (REAL, ShadowLabel.clear),
    ],
)
def test_real_captures_read_a_memo_as_repetition_and_a_real_cut_as_clear(
    rig: Rig, text: str, label: ShadowLabel
) -> None:
    """
    GIVEN the real shim, ``run_once`` and git on ``wordpkg``
    WHEN a paired trial is captured on both sides
    THEN the twin's rows are the same on every trial (the base A/A), an
        unchanged package reads no count gain with both sides equal, both
        memos and ``functools.lru_cache`` on the point itself (review R4: not
        ``corpus_mismatch``) read ``repetition_fit`` and the real cut ``clear``
    """
    rig.network, rig.run = "off", run_once

    trial, _ = rig.trial(text, paired=True, shadow=True)

    reading = shadow_reading(trial.base_measurements, trial.measurements)
    assert reading.label is label, (reading, rig.notes)
    assert shadow_rows(trial.base_measurements)[0][1] > 0
    if text == SAME:
        assert shadow_rows(trial.base_measurements) == shadow_rows(trial.measurements)
    shutil.rmtree(rig.clock.run_dir, ignore_errors=True)
