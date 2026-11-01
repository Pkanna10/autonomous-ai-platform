"""Quality rows and masks in every runner, and the editor's read-deny (U24, D37).

Real git, a scripted host. Fakes: ``Host`` stands for ``procrun.run_once``
(a workload "prints" the worktree's ``model.txt`` and records whether the
frozen labels and ``<run>/quality`` existed at its launch; the suite passes;
a scorer launch, cwd ``<run>/quality``, counts ``cat`` lines on its stdin
file); ``Edits`` for ``ClaudeEditor``; ``ScriptedTransport`` for the API.
The scorer is the real ``FrozenScorer``.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, field, replace
from pathlib import Path

import pytest

from autonomous_ai_agents.clients.budget import Budget
from autonomous_ai_agents.clients.transport import ScriptedTransport
from autonomous_ai_agents.common.config import Settings, settings
from autonomous_ai_agents.common.errors import EngineError
from autonomous_ai_agents.common.models import (
    METRIC_TESTS_PASSED,
    Baseline,
    BuiltinMeasure,
    ChangeClass,
    Direction,
    FrozenFile,
    Hypothesis,
    HypothesisSource,
    Measurement,
    OutputTolerance,
    Project,
    QualityCheck,
    RunStats,
    Trial,
    Workload,
)
from autonomous_ai_agents.execution import protocols
from autonomous_ai_agents.execution.combine import GitCombiner
from autonomous_ai_agents.execution.editor import ClaudeEditor
from autonomous_ai_agents.execution.editor_tools import WorktreeEditor
from autonomous_ai_agents.execution.git import GitError, GitWorkspace
from autonomous_ai_agents.execution.procrun import OutputCaps, RunSample
from autonomous_ai_agents.execution.profiler import CProfiler
from autonomous_ai_agents.execution.protocols import (
    CodeEditor,
    EditResult,
    EditTask,
    KeptChange,
    TrialBrief,
)
from autonomous_ai_agents.execution.quality import FrozenScorer
from autonomous_ai_agents.execution.retry import ClosureIndex
from autonomous_ai_agents.execution.sandbox import SandboxPolicy
from autonomous_ai_agents.execution.trial_runner import (
    GitBaselineRunner,
    GitTrialRunner,
    NoteTap,
    _stream_added,
)
from autonomous_ai_agents.optimization.anticheat import DEFAULT_PROTECTED_PATTERNS

PY, RUN, LABELS = sys.executable, "run1", "data/labels.txt"
BASE_MODEL, BETTER = "cat\ndog\ncat\nbird\n", "cat\ndog\ndog\nbird\n"
FILES = {
    "predict.py": "print(open('model.txt').read(), end='')\n",
    "model.txt": BASE_MODEL,
    LABELS: BETTER,  # the base model gets 3 of 4: accuracy 0.75
    "data/test.csv": "id,label\n1,cat\n2,dog\n3,dog\n4,bird\n",  # carries them
    "data/values.txt": "0.1000000002\n",
    "score.py": "pass\n",  # the host double scores
    "data/[x].txt": "cat\n",
}
FROZEN = (LABELS, "score.py")
ENV = {"PATH": os.defpath, "HOME": os.devnull, "GIT_CONFIG_GLOBAL": os.devnull}
ENV |= {"GIT_CONFIG_NOSYSTEM": "1", "LC_ALL": "C"}
ENV |= {f"GIT_{r}_{k}": v for r in ("AUTHOR", "COMMITTER") for k, v in
        (("NAME", "User"), ("EMAIL", "u@example.invalid"), ("DATE", "@1700000000 +0000"))}  # fmt: skip
ISOLATION = "network isolation was not applied (best_effort)"


def git(cwd: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(cwd), *args], env=ENV, capture_output=True)
    assert done.returncode == 0, done.stderr
    return done.stdout.decode().strip()


def sample(out: bytes, err: bytes = b"", notes: tuple[str, ...] = ()) -> RunSample:
    digest = hashlib.sha256(out).hexdigest()
    return RunSample(1_000_000, 0.001, 0.0, 1 << 20, 0, True, True, digest, out,
                     len(out), err, notes)  # fmt: skip


@dataclass
class Host:
    """``run_once``; ``launches``: (phase, how many ``frozen`` files were
    present, whether ``<run>/quality`` was); ``crash`` fails that many trial
    launches with a fixable ``NameError`` in ``predict.py``."""

    run_dir: Path
    vary: Callable[[bytes, int], bytes] = lambda out, n: out
    launches: list[tuple[str, int, bool]] = field(default_factory=list)
    scored: list[bytes] = field(default_factory=list)
    frozen: tuple[str, ...] = FROZEN
    crash: int = 0

    def __call__(
        self, argv: Sequence[str], cwd: Path, env: Mapping[str, str],
        sandbox: SandboxPolicy, timeout_s: float, caps: OutputCaps, *,
        fresh_dirs: Sequence[Path] = (),
    ) -> RunSample:  # fmt: skip
        phase = cwd.relative_to(self.run_dir).parts[0]
        if phase == "quality":  # the shim's argv[5] is the scorer's stdin file
            self.scored.append(data := Path(argv[5]).read_bytes())
            head = f"aip-quality/1 acc={data.count(b'cat')}\n".encode()
            return sample(head, notes=(ISOLATION,))
        present = sum((cwd / path).exists() for path in self.frozen)
        seen = (present, (self.run_dir / "quality").exists())
        if "unittest" in argv:
            self.launches.append((f"suite {phase}", *seen))
            return sample(b"", b"Ran 1 test in 0.001s\n\nOK\n")
        self.launches.append((phase, *seen))
        if phase.startswith("trial-") and self.crash:
            self.crash -= 1
            tail = (f'Traceback (most recent call last):\n  File "{cwd}/predict.py", line 1,'
                    " in <module>\n    print(open('model.txt').read(), end='')\n"
                    "NameError: name 'x' is not defined\n")  # fmt: skip
            return replace(sample(b""), exit=1, stderr_tail=tail.encode())
        return sample(self.vary((cwd / "model.txt").read_bytes(), len(self.launches)))

    def workloads(self) -> list[tuple[str, int, bool]]:
        return [launch for launch in self.launches if " " not in launch[0]]


@dataclass
class Rig:
    repo: Path
    base: str
    project: Project
    host: Host
    notes: list[str] = field(default_factory=list)
    tasks: list[EditTask] = field(default_factory=list)

    def workload(
        self, tolerance: OutputTolerance | None = None, *args: str
    ) -> Workload:
        return Workload(
            project_id=self.project.id, name="predict", warmup_runs=1,
            command=(PY, "predict.py", "data/test.csv", *args), timeout_s=60.0,
            output_tolerance=tolerance,
        )  # fmt: skip

    def modes(self) -> dict[str, object]:
        return {"network": "off", "fs": "off", "platform": "linux",
                "base_env": {"PATH": "/usr/bin"}, "run": self.host}  # fmt: skip

    def baseline_runner(self, scorer: FrozenScorer | None, **more: object) -> GitBaselineRunner:  # fmt: skip
        return GitBaselineRunner(
            self.project, on_note=self.notes.append, scorer=scorer, **self.modes(), **more,  # type: ignore[arg-type]
        )  # fmt: skip

    def trial(
        self, scorer: FrozenScorer | None, workloads: Sequence[Workload], *,
        text: str = BETTER, recorded: tuple[FrozenFile, ...] = (), paired: bool = True,
        path: str = "model.txt", retries: int = 0, then: str | None = None,
    ) -> Trial:  # fmt: skip
        def build(*, module_roots: AbstractSet[str], reserved_modules: AbstractSet[str]) -> CodeEditor:  # fmt: skip
            return Edits(text, self.tasks, path, then)

        hypothesis = Hypothesis(
            project_id=self.project.id, source=HypothesisSource.novel, title="fix",
            rationale="r", change_class=ChangeClass.efficiency, expected_gain=0.5,
            provability=0.9, risk=0.1,
        )  # fmt: skip
        rows = tuple(
            Measurement(workload_id=w.id, metric=METRIC_TESTS_PASSED,
                        stats=RunStats.from_samples((1.0,), unit="bool"),
                        samples=(1.0,), hardware={"tests_counted": 1})
            for w in workloads
        )  # fmt: skip
        baseline = Baseline(commit=self.base, measurements=rows, quality_files=recorded)
        return GitTrialRunner(
            self.project, editor=build, on_note=self.notes.append, scorer=scorer,
            paired=paired, fix_retries=retries, **self.modes(),  # type: ignore[arg-type]
        ).run(
            hypothesis, workloads, baseline, round=1, budget_usd=1.0,
            branch=f"{settings.TRIAL_BRANCH_PREFIX}trial-{RUN}-{hypothesis.id}",
            brief=TrialBrief(None, (), DEFAULT_PROTECTED_PATTERNS, retries, read_deny=("x.txt",)),
        )  # fmt: skip


@dataclass
class Edits:
    text: str
    tasks: list[EditTask]
    path: str = "model.txt"
    then: str | None = None  # a retry's text

    def edit(self, worktree: Path, task: EditTask, budget: Budget) -> EditResult:
        text = self.text if task.feedback is None or self.then is None else self.then
        self.tasks.append(task)
        (worktree / self.path).write_text(text)
        return EditResult({self.path: len(text)}, cost_usd=0.01, tokens_used=1)


@pytest.fixture
def rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Rig:
    root = Path(os.path.realpath(tmp_path))
    monkeypatch.setattr(settings, "WORKTREE_ROOT", root / "wt-root")
    repo = root / "user"
    for name, text in FILES.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text)
    git(root, "init", "-q", "-b", "main", str(repo))
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    project = Project(
        name="p", root_path=str(repo), test_command=(PY, "-m", "unittest")
    )
    return Rig(repo, git(repo, "rev-parse", "HEAD"), project, Host(root / "wt-root" / RUN))  # fmt: skip


def accuracy(labels: str = LABELS) -> FrozenScorer:
    check = QualityCheck(
        name="acc", measure=BuiltinMeasure.accuracy, labels=labels,
        frozen_paths=(labels, "score.py"),
    )  # fmt: skip
    return FrozenScorer(check)


def quality(rows: Sequence[Measurement]) -> list[tuple[float, str | None]]:
    return [(m.stats.mean, m.trial_id) for m in rows if m.metric == "quality:acc"]


def masked(host: Host, *phases: str) -> None:
    """Every workload launch ran without any frozen file and while no scorer
    copy existed; the suite saw them all."""
    seen = {launch[0] for launch in host.workloads()}
    assert seen == set(phases)
    assert all(not present and not scoring for _, present, scoring in host.workloads())
    suites = [present for name, present, _ in host.launches if name.startswith("suite")]
    assert all(present == len(host.frozen) for present in suites)


def test_the_baseline_freezes_scores_masks_and_warns_of_a_label_column(
    rig: Rig,
) -> None:
    runner = rig.baseline_runner(accuracy())
    rows = runner.measure([rig.workload()], run_id=RUN, commit=rig.base)
    assert quality(rows) == [(0.75, None)]
    [row] = [m for m in rows if m.metric == "quality:acc"]
    assert (row.stats.n, row.stats.unit, row.output_fingerprint) == (1, "score", None)
    masked(rig.host, "baseline")
    assert [f.path for f in runner.quality_files] == list(FROZEN)
    assert runner.label_leaks == ("data/test.csv column 2",)
    assert any(
        "data/test.csv column 2" in n and n.startswith("baseline: ") for n in rig.notes
    )


def test_the_label_scan_reads_each_named_regular_file_once_and_bounded(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Flags, files outside the repository, the frozen labels and repeats are
    skipped; every read is capped and a file past the cap is not scanned."""
    limits: list[tuple[str, int | None]] = []
    real = GitWorkspace.read_blob

    def read(ws: GitWorkspace, commit: str, path: str, *, limit: int | None = None) -> bytes:  # fmt: skip
        limits.append((path, limit))
        return real(ws, commit, path, limit=limit)

    monkeypatch.setattr(GitWorkspace, "read_blob", read)
    monkeypatch.setattr(settings, "QUALITY_MAX_FROZEN_BYTES", 30)  # test.csv: 34
    load = rig.workload(None, "-u", "../outside.csv", LABELS, "data/test.csv")
    runner = rig.baseline_runner(accuracy())
    runner.measure([load], run_id=RUN, commit=rig.base)
    assert runner.label_leaks == ()
    scanned = [path for path, _ in limits]
    assert scanned == [*FROZEN, "predict.py", "data/test.csv", LABELS]  # freeze first
    assert all(limit is not None and limit <= 31 for _, limit in limits)


def test_a_trials_editor_is_told_to_protect_and_never_read_the_frozen_files(
    rig: Rig,
) -> None:
    rig.trial(accuracy(), [rig.workload()], paired=False)
    [task] = rig.tasks
    assert task.brief.read_deny == ("x.txt", *FROZEN)
    assert task.brief.protected[-2:] == FROZEN and set(DEFAULT_PROTECTED_PATTERNS) <= set(task.brief.protected)  # fmt: skip


def test_without_a_quality_check_every_runner_is_step_2(rig: Rig) -> None:
    runner = rig.baseline_runner(None)
    rows = runner.measure([rig.workload()], run_id=RUN, commit=rig.base)
    trial = rig.trial(None, [rig.workload()])
    assert quality([*rows, *trial.measurements, *trial.base_measurements]) == []
    assert all(present == len(FROZEN) for _, present, _ in rig.host.launches)
    assert (runner.quality_files, runner.label_leaks) == ((), ())
    assert rig.tasks[0].brief.read_deny == ("x.txt",)


def test_the_calibration_masks_both_base_worktrees(rig: Rig) -> None:
    rig.baseline_runner(accuracy()).calibrate([rig.workload()], run_id=RUN, commit=rig.base, blocks=1)  # fmt: skip
    masked(rig.host, "calibrate", "twin-calibrate")


def test_a_paired_trial_scores_both_sides_under_one_mask(rig: Rig) -> None:
    trial = rig.trial(accuracy(), [rig.workload()])
    assert quality(trial.base_measurements) == [(0.75, None)]
    assert quality(trial.measurements) == [(1.0, trial.id)]
    hyp = trial.hypothesis_id
    masked(rig.host, f"trial-{hyp}", f"twin-trial-{hyp}")


def test_a_resumed_trial_freezes_against_the_recorded_files(rig: Rig) -> None:
    """A fresh scorer (a resumed run) freezes at the trial with the
    baseline's recorded files, so a changed one is refused."""
    runner = rig.baseline_runner(accuracy())
    runner.measure([rig.workload()], run_id=RUN, commit=rig.base)
    recorded = runner.quality_files
    trial = rig.trial(accuracy(), [rig.workload()], recorded=recorded, paired=False)
    assert quality(trial.measurements) == [(1.0, trial.id)]
    forged = (recorded[0].model_copy(update={"sha256": "0" * 64}),)
    with pytest.raises(EngineError, match="changed since the baseline"):
        rig.trial(accuracy(), [rig.workload()], recorded=forged)


def test_the_combine_scores_and_masks_both_sides(rig: Rig) -> None:
    git(rig.repo, "checkout", "-q", "-b", "kept")
    (rig.repo / "model.txt").write_text(BETTER)
    git(rig.repo, "commit", "-qam", "kept")
    commit = git(rig.repo, "rev-parse", "HEAD")
    git(rig.repo, "checkout", "-q", "main")
    kept = KeptChange("t1", "h1", "v1", commit, 1.0, 0.1)
    runner = rig.baseline_runner(accuracy())
    runner.measure([rig.workload()], run_id=RUN, commit=rig.base)
    rig.host.launches.clear()
    measured = GitCombiner(scorer=accuracy(), **rig.modes()).combine(  # type: ignore[arg-type]
        RUN, rig.project, rig.base, [kept], [rig.workload()], baseline_count=1,
        quality_files=runner.quality_files,
    )  # fmt: skip
    assert quality(measured.baseline) == [(0.75, None)]
    assert quality(measured.combined) == [(1.0, None)]
    masked(rig.host, "combine", "combine-base")
    forged = (runner.quality_files[0].model_copy(update={"sha256": "0" * 64}),)
    with pytest.raises(EngineError, match="changed since the baseline"):
        GitCombiner(scorer=accuracy(), **rig.modes()).combine(  # type: ignore[arg-type]
            RUN, rig.project, rig.base, [kept], [rig.workload()], quality_files=forged
        )


def test_the_profile_run_is_masked_from_the_scorer(rig: Rig) -> None:
    CProfiler(rig.project, scorer=accuracy(), **rig.modes()).profile(  # type: ignore[arg-type]
        [rig.workload()], run_id=RUN, commit=rig.base
    )
    masked(rig.host, "profile")


def test_the_retry_closure_never_reads_a_frozen_file(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``score.py`` is tracked Python, so the closure would read it: frozen,
    it stays out (D13 sources reach the editor as feedback)."""
    sources: list[set[str]] = []
    real = ClosureIndex.build

    def build(diff: str, found: Mapping[str, str], **more: object) -> object:
        sources.append(set(found))
        return real(diff, found, **more)  # type: ignore[arg-type]

    monkeypatch.setattr(ClosureIndex, "build", build)
    rig.host.crash = 1
    trial = rig.trial(accuracy(), [rig.workload()], paired=False, retries=1)
    assert trial.attempts == 2 and sources == [{"predict.py"}]


def test_frozen_paths_show_literally_and_match_escaped(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A path ``glob.escape`` changes: unreachable, since ``QualityCheck`` and
    ``TrialBrief`` refuse ``[`` (the latter bypassed here), so this pins the
    defence in depth: the brief shows it as written, the diff check matches
    it literally, and a trial writing it is rejected unexecuted."""
    monkeypatch.setattr(protocols, "literal_project_file", lambda field, value: value)
    path = "data/[x].txt"
    check = QualityCheck.model_construct(
        name="acc", measure=BuiltinMeasure.accuracy, labels=path, frozen_paths=(path,),
        scorer=(), direction=Direction.maximize,
    )  # fmt: skip
    trial = rig.trial(FrozenScorer(check), [rig.workload()], path=path, paired=False)
    assert rig.tasks[0].brief.protected[-1] == path
    assert [v.rule.value for v in trial.violations] == ["protected_path"]
    assert rig.host.launches == []


NAMES_LABELS = "rows = open('data/labels.txt').read()  # not x.txt\nprint(open('model.txt').read(), end='')\n"  # fmt: skip


def test_a_trial_naming_a_frozen_file_is_rejected_unexecuted(rig: Rig) -> None:
    """D37's tripwire at the call site, on the first attempt and before any
    launch: an added line of ``predict.py`` names the labels."""
    trial = rig.trial(
        accuracy(), [rig.workload()], path="predict.py", text=NAMES_LABELS
    )
    assert [(v.rule.value, v.path, v.pattern) for v in trial.violations] == [
        ("quality_data_reference", "predict.py", LABELS)
    ]
    assert trial.status.value == "failed" and trial.commit is None
    assert rig.host.launches == []


def test_a_line_the_base_already_has_is_context_not_a_reference(rig: Rig) -> None:
    """The base of a modified file reaches the check: its unchanged line
    naming the labels is context, so the trial is measured."""
    named = "# the scorer reads data/labels.txt\n"
    (rig.repo / "predict.py").write_text(named + FILES["predict.py"])
    git(rig.repo, "commit", "-qam", "comment")
    rig.base = git(rig.repo, "rev-parse", "HEAD")
    text = named + "print(open('model.txt').read(), end='')  # faster\n"
    trial = rig.trial(accuracy(), [rig.workload()], path="predict.py", text=text, paired=False)  # fmt: skip
    assert trial.violations == () and trial.status.value == "measured"


def test_a_line_moved_within_its_file_is_added_as_git_shows_it(rig: Rig) -> None:
    """The fast path cannot tell a moved line (the new file holds it as often
    as the base); git's ``-U0`` patch shows it as added, so the move is
    refused unexecuted. A kept line whose neighbours change is context in
    git's patch and is not flagged: a tripwire, not closure; the review
    branch's diff is the backstop (D37)."""
    train = "def train():\n    rows = open('data/labels.txt').read()\n    return rows\n\ndef predict():\n    return 1\n"  # fmt: skip
    moved = "def train():\n    return 0\n\ndef predict():\n    rows = open('data/labels.txt').read()\n    return rows\n"  # fmt: skip
    (rig.repo / "predict.py").write_text(train)
    git(rig.repo, "commit", "-qam", "train")
    rig.base = git(rig.repo, "rev-parse", "HEAD")
    trial = rig.trial(accuracy(), [rig.workload()], path="predict.py", text=moved, paired=False)  # fmt: skip
    assert [v.rule.value for v in trial.violations] == ["quality_data_reference"]
    assert rig.host.launches == []


def test_a_patch_that_cannot_be_read_fails_the_trial_unexecuted(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    named = "# the scorer reads data/labels.txt\n"
    (rig.repo / "predict.py").write_text(named + FILES["predict.py"])
    git(rig.repo, "commit", "-qam", "comment")
    rig.base = git(rig.repo, "rev-parse", "HEAD")
    real = GitWorkspace._git

    def broken(ws: GitWorkspace, where: object, *args: str, **more: object) -> tuple[int, bytes]:  # fmt: skip
        if "-U0" in args:
            raise GitError("git diff failed (exit 128): boom")
        return real(ws, where, *args, **more)  # type: ignore[arg-type]

    monkeypatch.setattr(GitWorkspace, "_git", broken)
    text = named + "print(open('model.txt').read(), end='')  # faster\n"
    trial = rig.trial(accuracy(), [rig.workload()], path="predict.py", text=text, paired=False)  # fmt: skip
    assert trial.status.value == "failed" and "could not be captured" in str(
        trial.error
    )
    assert rig.host.launches == []


FIRST = "print(open('model.txt').read(), end='')  # first\n"


def test_a_retry_keeping_a_base_reference_line_is_measured(rig: Rig) -> None:
    """The retry's check reads the base too: a line the base already has
    naming the labels stays context, so the retried trial is measured."""
    named = "# the scorer reads data/labels.txt\n"
    (rig.repo / "predict.py").write_text(named + FILES["predict.py"])
    git(rig.repo, "commit", "-qam", "comment")
    rig.base = git(rig.repo, "rev-parse", "HEAD")
    rig.host.crash = 1
    trial = rig.trial(accuracy(), [rig.workload()], path="predict.py", text=named + FIRST,
                      paired=False, retries=1, then=named + FILES["predict.py"] + "# fixed\n")  # fmt: skip
    assert trial.attempts == 2 and trial.status.value == "measured"


def test_a_step_2_rule_and_the_tripwire_are_both_recorded(rig: Rig) -> None:
    trial = rig.trial(accuracy(), [rig.workload()], path="test_predict.py", text=NAMES_LABELS)  # fmt: skip
    assert {v.rule.value for v in trial.violations} == {"protected_path", "quality_data_reference"}  # fmt: skip
    assert rig.host.launches == []


@pytest.mark.parametrize("name", ["--output=x.py", "*.py"])
def test_the_patch_stream_reads_one_staged_file_literally_and_writes_nothing(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    """``--`` keeps the pathspec a path (``:(literal)<name>`` would name the
    staged blob of a file called ``(literal)<name>`` as a revision),
    ``:(literal)`` keeps an option-like or glob name one file, ``--cached``
    reads the index, not the worktree, and the patch only streams (``_git``
    keeps none of it)."""
    for path in (name, "x.py", "b.py", f"(literal){name}"):
        (rig.repo / path).write_text("old\n")
    git(rig.repo, "add", "-A")
    git(rig.repo, "commit", "-qm", "odd names")
    base = git(rig.repo, "rev-parse", "HEAD")
    ws = GitWorkspace(rig.repo)
    handle = ws.add_worktree(settings.WORKTREE_ROOT / RUN / "odd", base)
    for path in (name, "b.py"):
        (handle.path / path).write_text("staged = 'data/labels.txt'\n")
    ws.stage_all(handle)
    (handle.path / name).write_text("worktree only\n")
    before = sorted(p.name for p in handle.path.iterdir())
    kept: list[bytes] = []
    real = GitWorkspace._git

    def spy(ws: GitWorkspace, where: object, *args: str, **more: object) -> tuple[int, bytes]:  # fmt: skip
        code, out = real(ws, where, *args, **more)  # type: ignore[arg-type]
        if "-U0" in args:
            kept.append(out)
        return code, out

    monkeypatch.setattr(GitWorkspace, "_git", spy)
    chunks: list[bytes] = []
    _stream_added(ws, handle, base, name, chunks.append)
    patch = b"".join(chunks)
    assert patch.count(b"diff --git") == 1 and f"+++ b/{name}".encode() in patch
    assert b"+staged = 'data/labels.txt'" in patch and b"worktree only" not in patch
    assert kept == [b""] and sorted(p.name for p in handle.path.iterdir()) == before
    assert (handle.path / "x.py").read_text() == "old\n"


def test_a_retry_naming_a_frozen_file_is_rejected_unexecuted(rig: Rig) -> None:
    """The retry's union diff is checked too: its edit names the labels, so
    it never runs and the first failure is kept, noted."""
    rig.host.crash = 1
    fixed = "print(open('model.txt').read(), end='')  # data/labels.txt\n"
    trial = rig.trial(accuracy(), [rig.workload()], path="predict.py", text=FIRST,
                      paired=False, retries=1, then=fixed)  # fmt: skip
    assert [t.feedback is not None for t in rig.tasks] == [False, True]
    assert len(rig.host.workloads()) == 1  # the first attempt's crash only
    assert trial.attempts == 2 and trial.status.value == "failed"
    assert any("quality_data_reference" in note for note in trial.retry_notes)


def test_without_a_quality_check_naming_a_file_is_step_2(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No scorer: the same edit is measured, and no base blob is read for it."""
    reads: list[str] = []
    real = GitWorkspace.read_blob

    def read(ws: GitWorkspace, commit: str, path: str, *, limit: int | None = None) -> bytes:  # fmt: skip
        reads.append(path)
        return real(ws, commit, path, limit=limit)

    monkeypatch.setattr(GitWorkspace, "read_blob", read)
    trial = rig.trial(None, [rig.workload()], path="predict.py", text=NAMES_LABELS, paired=False)  # fmt: skip
    assert trial.violations == () and trial.status.value == "measured"
    assert "predict.py" not in reads


def test_an_unscoreable_output_gives_no_row_and_never_its_bytes(rig: Rig) -> None:
    rig.host.vary = lambda out, n: b"SECRET-1\nSECRET-2\nSECRET-3\n"
    rows = rig.baseline_runner(accuracy()).measure([rig.workload()], run_id=RUN, commit=rig.base)  # fmt: skip
    assert quality(rows) == []
    assert any("the output has 3 lines and the labels 4" in note for note in rig.notes)
    shown = "".join(rig.notes) + "".join(m.model_dump_json() for m in rows)
    assert "SECRET" not in shown


class Spy(FrozenScorer):
    keys: list[str | None]

    def score(self, output: bytes | None, fingerprint: str | None) -> float:
        self.keys = [*getattr(self, "keys", []), fingerprint]
        return super().score(output, fingerprint)


def test_outputs_equal_within_a_tolerance_are_scored_on_their_own_bytes(
    rig: Rig,
) -> None:
    """The cache key is the exact ``raw_fingerprint``: a canonical key would
    hand the trial the twin's 0.0; runs agreeing only within the tolerance
    have none and are scored uncached."""
    (rig.repo / "model.txt").write_text("0.1000000001\n")
    git(rig.repo, "commit", "-qam", "floats")
    rig.base = git(rig.repo, "rev-parse", "HEAD")
    workload = rig.workload(OutputTolerance(float_digits=6))
    spy = Spy(accuracy("data/values.txt").check)
    trial = rig.trial(spy, [workload], text="0.1000000002\n")
    assert quality(trial.base_measurements) == [(0.0, None)]
    assert quality(trial.measurements) == [(1.0, trial.id)]
    twin, own = trial.base_measurements[0], trial.measurements[0]
    assert twin.output_fingerprint == own.output_fingerprint
    assert spy.keys == [twin.raw_fingerprint, own.raw_fingerprint]
    assert twin.raw_fingerprint != own.raw_fingerprint
    rig.host.vary = lambda out, n: out.replace(b"2\n", b"2%d\n" % (n % 2))
    again = rig.trial(spy, [workload], text="0.1000000002\n", paired=False)
    assert again.measurements[0].raw_fingerprint is None and spy.keys[-1] is None
    assert quality(again.measurements) == [(0.0, again.id)]  # its first run's bytes


def test_an_external_scorer_runs_only_between_launches_and_notes_once(rig: Rig) -> None:
    check = QualityCheck(name="acc", scorer=(PY, "score.py"), frozen_paths=("score.py", LABELS),
                         direction=Direction.maximize)  # fmt: skip
    tap = NoteTap(rig.host)
    scorer = FrozenScorer(check, run=tap, network="off", fs="off")
    loads = [rig.workload(), rig.workload()]  # the second runs after a scoring
    rows = rig.baseline_runner(scorer, scorer_notes=tap).measure(loads, run_id=RUN, commit=rig.base)  # fmt: skip
    assert quality(rows) == [(2.0, None)] * 2
    assert rig.host.scored == [BASE_MODEL.encode()] * 4  # twice each: determinism
    masked(rig.host, "baseline")
    assert rig.notes.count(f"baseline: the quality scorer: {ISOLATION}") == 1
    assert not (rig.host.run_dir / "quality").exists()


# ---- the editor's read-deny ------------------------------------------------


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    for name, text in {**FILES, "data/[x].txt": "x\n", "data/x.txt": "y\n"}.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text)
    return tmp_path


def test_an_nfd_frozen_path_is_refused_when_asked_in_nfc(tree: Path) -> None:
    """git keeps a path's bytes, so a frozen path may be NFD while requests
    are NFC-normalised; APFS would open either spelling."""
    nfd = unicodedata.normalize("NFD", "data/étiquettes.txt")
    (tree / nfd).write_text("bird\n")
    for deny, protect in ((nfd, ()), ("x.txt", (nfd,))):
        files = WorktreeEditor(tree, protected=protect, read_deny=(deny,))
        nfc = "/repo/" + unicodedata.normalize("NFC", nfd)
        viewed = files.execute({"command": "view", "path": nfc})
        written = files.execute({"command": "create", "path": nfc, "file_text": "x"})
        assert written.is_error
        if deny == nfd:
            assert (
                "bird" not in viewed.content
                and viewed.is_error
                and viewed.content.endswith("evaluation data, off limits")
            )
            listing = files.execute({"command": "view", "path": "/repo/data"}).content
            assert "tiquettes" not in listing
        else:
            assert "is protected" in written.content


def test_a_read_denied_file_is_refused_and_unlisted_its_directory_readable(tree: Path) -> None:  # fmt: skip
    files = WorktreeEditor(tree, protected=(), read_deny=(LABELS, "data/[x].txt"))
    for path in (
        "/repo/data/labels.txt",
        "/repo/DATA/Labels.TXT",
        "/repo/data/[x].txt",
    ):
        for command in (
            {"command": "view"},
            {"command": "str_replace", "old_str": "cat"},
        ):
            outcome = files.execute({**command, "path": path})
            assert outcome.is_error and outcome.content.endswith(
                "evaluation data, off limits"
            )
            assert "bird" not in outcome.content
    assert not files.execute({"command": "view", "path": "/repo/data/x.txt"}).is_error
    for listing in ("/repo", "/repo/data"):
        shown = files.execute({"command": "view", "path": listing}).content
        assert "test.csv" in shown and "labels.txt" not in shown and "[x]" not in shown
    assert files.written == {}


def test_the_editor_hands_the_briefs_read_deny_to_its_tools(tree: Path) -> None:
    def use(n: int, **command: object) -> dict[str, object]:
        block = {"type": "tool_use", "id": f"toolu_{n}", "input": command,
                 "name": "str_replace_based_edit_tool"}  # fmt: skip
        usage = {"input_tokens": 4, "output_tokens": 5}
        return {"id": "m", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
                "content": [block], "stop_reason": "tool_use", "usage": usage}  # fmt: skip

    cfg = Settings.model_validate(
        {"ENGINE_MODEL": "claude-opus-5-5", "LLM_MAX_RETRIES": 0}
    )
    view = use(1, command="view", path="/repo/data/labels.txt")
    transport = ScriptedTransport([view], cfg=cfg)
    brief = TrialBrief(None, (), (), read_deny=(LABELS,))
    hypothesis = Hypothesis(project_id="p", source=HypothesisSource.novel, title="t",
                            rationale="r", change_class=ChangeClass.efficiency,
                            expected_gain=0.1, provability=0.5, risk=0.1)  # fmt: skip
    task = EditTask(hypothesis, brief, "9f3c2a7b1e4d6085")
    ClaudeEditor(transport, config=cfg, sleep=lambda s: None).edit(
        tree, task, Budget(5.0)
    )
    sent = str(transport.requests[1].messages[-1]["content"])
    assert "evaluation data, off limits" in sent and "bird" not in sent


def test_a_briefs_read_deny_holds_literal_project_files_only() -> None:
    assert TrialBrief(None, (), ()).read_deny == ()
    for bad in ("data/*.txt", "../labels.txt", "/abs.txt", "./labels.txt"):
        with pytest.raises(ValueError, match="read_deny"):
            TrialBrief(None, (), (), read_deny=(bad,))
