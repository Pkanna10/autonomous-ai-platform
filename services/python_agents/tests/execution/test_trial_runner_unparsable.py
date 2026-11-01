"""The trial runner's capture call: ``base_of`` and ``unparsable_source`` (N0, D62),
and the one re-edit an ``unparsable_source`` refusal earns (N0b).

Real git on a throwaway copy of the ``dedupe_repo`` fixture, plus a base file
``dedupe/loader.py`` that already imports ``importlib.import_module`` (as
mistune's plugin loader does). Fakes: ``FakeRun`` stands for
``procrun.run_once`` (no workload is launched; every call is recorded, and a
scripted crash tail can be replayed), ``WriteEditor`` and ``Attempts`` for
``ClaudeEditor`` (they write fixed bytes, one set per attempt); one test runs
the real ``ClaudeEditor`` on a ``ScriptedTransport`` (for the Anthropic API)
to read the retry's request body. The real ``GitWorkspace`` reads the base
blob, so the base the rule sees is git's.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from autonomous_ai_agents.clients.budget import Budget
from autonomous_ai_agents.clients.transport import ScriptedTransport
from autonomous_ai_agents.common.config import Settings, settings
from autonomous_ai_agents.common.models import (
    METRIC_CPU_TIME_S,
    METRIC_TESTS_PASSED,
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
    ViolationRule,
    Workload,
)
from autonomous_ai_agents.execution.combine import _unfit
from autonomous_ai_agents.execution.editor import ClaudeEditor
from autonomous_ai_agents.execution.git import GitError, GitWorkspace
from autonomous_ai_agents.execution.procrun import OutputCaps, RunSample
from autonomous_ai_agents.execution.protocols import (
    CodeEditor,
    EditResult,
    EditTask,
    TrialBrief,
)
from autonomous_ai_agents.execution.sandbox import SandboxPolicy
from autonomous_ai_agents.execution.trial_runner import GitTrialRunner
from autonomous_ai_agents.optimization.anticheat import DEFAULT_PROTECTED_PATTERNS

DEDUPE_REPO = Path(__file__).resolve().parents[1] / "fixtures" / "dedupe_repo"
PY, RUN_ID, TESTS = sys.executable, "run1", 11
UNITTEST = (PY, "-m", "unittest", "discover", "-s", "tests", "-t", ".")
LOADER = "dedupe/loader.py"
CORE, EXTRA = "dedupe/core.py", "dedupe/_extra.py"
BASE_CORE = (DEDUPE_REPO / CORE).read_bytes()
SIGNATURE = b"def unique_in_order(items: Iterable[int]) -> list[int]:"
DEF_LINE = BASE_CORE.split(b"\n").index(SIGNATURE) + 1
SLIP = BASE_CORE.replace(SIGNATURE, SIGNATURE[:-1])  # the colon dropped
FIXED = BASE_CORE + b"\n\nCACHE: dict[int, int] = {}\n"
UNPARSABLE = "unparsable_source"
KEPT = "first failure kept"
CRASH = (
    'Traceback (most recent call last):\n  File "/x/dedupe/main.py", line 3,'
    " in <module>\nNameError: name 'q' is not defined\n"
)
LOADER_PY = (
    b"from importlib import import_module\n\n\n"
    b"def load(name):\n    return import_module(name)\n"
)
_GIT_ENV = {
    "PATH": os.environ.get("PATH", os.defpath),
    "HOME": os.devnull,
    "LC_ALL": "C",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "Test User",
    "GIT_AUTHOR_EMAIL": "user@example.invalid",
    "GIT_COMMITTER_NAME": "Test User",
    "GIT_COMMITTER_EMAIL": "user@example.invalid",
}


def git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(cwd), *args], env=_GIT_ENV, capture_output=True, check=False
    )
    assert proc.returncode == 0, proc.stderr.decode(errors="replace")
    return proc.stdout.decode().strip()


@dataclass
class FakeRun:
    """``run_once``: records each launch; unittest prints ``TESTS`` passing tests;
    a workload launch pops one of ``crashes`` (a stderr tail) and exits 1."""

    calls: list[tuple[str, ...]] = field(default_factory=list)
    crashes: list[str] = field(default_factory=list)

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
        self.calls.append(tuple(argv))
        stderr = f"Ran {TESTS} tests in 0.010s\n\nOK\n" if "unittest" in argv else ""
        exit = 0
        if "unittest" not in argv and self.crashes:
            exit, stderr = 1, self.crashes.pop(0)
        return RunSample(
            wall_ns=10_000_000,
            utime=0.01,
            stime=0.0,
            maxrss_bytes=1 << 20,
            exit=exit,
            fs_isolated=True,
            net_isolated=True,
            stdout_sha256="1" * 64,
            stdout_head=b"",
            stdout_bytes=0,
            stderr_tail=stderr.encode(),
        )


@dataclass
class WriteEditor:
    """Writes ``files`` into the worktree and reports writing them."""

    files: Mapping[str, bytes]

    def edit(self, worktree: Path, task: EditTask, budget: Budget) -> EditResult:
        for rel, data in self.files.items():
            (worktree / rel).write_bytes(data)
        return EditResult(written={rel: len(data) for rel, data in self.files.items()})


@dataclass
class Attempts:
    """Writes one file set per attempt and records each task, how many launches
    had happened before it and the worktree's ``CORE`` as the attempt found it."""

    steps: Sequence[Mapping[str, bytes]]
    run: FakeRun
    tasks: list[EditTask] = field(default_factory=list)
    launches: list[int] = field(default_factory=list)
    found: list[bytes] = field(default_factory=list)

    def edit(self, worktree: Path, task: EditTask, budget: Budget) -> EditResult:
        self.tasks.append(task)
        self.launches.append(len(self.run.calls))
        self.found.append((worktree / CORE).read_bytes())
        step = self.steps[len(self.tasks) - 1]
        for rel, data in step.items():
            (worktree / rel).write_bytes(data)
        written = {rel: len(data) for rel, data in step.items()}
        return EditResult(written, cost_usd=0.01, tokens_used=10)


@dataclass
class Rig:
    repo: Path
    commit: str
    project: Project
    run: FakeRun
    hypothesis: Hypothesis

    def trial(self, files: Mapping[str, bytes]) -> Trial:
        return self.attempt(WriteEditor(files))

    def attempt(
        self,
        editor: CodeEditor,
        *,
        fix_retries: int = 0,
        left: int = 0,
        floor: float = 0.0,
        read_deny: tuple[str, ...] = (),
        budget: float = 1.0,
    ) -> Trial:
        def build(
            *, module_roots: AbstractSet[str], reserved_modules: AbstractSet[str]
        ) -> CodeEditor:
            return editor

        runner = GitTrialRunner(
            self.project,
            editor=build,
            network="required",
            fs="required",
            platform="linux",
            base_env={"PATH": "/usr/bin"},
            run=self.run,
            fix_retries=fix_retries,
            retry_floor_usd=floor,
        )
        hypothesis = self.hypothesis
        load = Workload(
            project_id=self.project.id,
            name="dedupe",
            command=(PY, "-m", "dedupe.main", "2000"),
            timeout_s=60.0,
            warmup_runs=0,
        )
        tests = Measurement(
            workload_id=load.id,
            metric=METRIC_TESTS_PASSED,
            stats=RunStats.from_samples((1.0,), unit="bool"),
            samples=(1.0,),
            hardware={"tests_counted": TESTS},
        )
        objective = Objective(  # CPU time judged: the spawn rule applies
            project_id=self.project.id,
            kind=ObjectiveKind.runtime,
            metric=METRIC_CPU_TIME_S,
            direction=Direction.minimize,
            description="less CPU",
        )
        baseline = Baseline(
            commit=self.commit, measurements=(tests,), objectives=(objective,)
        )
        return runner.run(
            hypothesis,
            [load],
            baseline,
            round=1,
            branch=f"{settings.TRIAL_BRANCH_PREFIX}trial-{RUN_ID}-{hypothesis.id}",
            budget_usd=budget,
            brief=TrialBrief(
                None,
                (),
                DEFAULT_PROTECTED_PATTERNS,
                fix_retries_left=left,
                read_deny=read_deny,
            ),
        )

    def own_ref(self) -> str | None:
        branch = f"refs/heads/{settings.TRIAL_BRANCH_PREFIX}trial-{RUN_ID}-{self.hypothesis.id}"  # fmt: skip
        found = git(self.repo, "for-each-ref", "--format=%(objectname)", branch)
        return found or None


@pytest.fixture
def rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Rig:
    root = Path(os.path.realpath(tmp_path))
    wt_root = root / "wt-root"
    wt_root.mkdir()
    monkeypatch.setattr(settings, "WORKTREE_ROOT", wt_root)
    repo = root / "user"
    shutil.copytree(DEDUPE_REPO, repo, ignore=shutil.ignore_patterns("__pycache__"))
    (repo / LOADER).write_bytes(LOADER_PY)
    git(root, "init", "-q", "-b", "main", str(repo))
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    project = Project(name="dedupe", root_path=str(repo), test_command=UNITTEST)
    hypothesis = Hypothesis(
        project_id=project.id,
        source=HypothesisSource.playbook,
        title="h1",
        rationale="use a set for membership",
        change_class=ChangeClass.efficiency,
        expected_gain=0.5,
        provability=0.9,
        risk=0.1,
    )
    return Rig(repo, git(repo, "rev-parse", "HEAD"), project, FakeRun(), hypothesis)


def _never_run(rig: Rig, trial: Trial) -> None:
    assert trial.status is TrialStatus.failed
    assert (trial.commit, trial.measurements) == (None, ())
    assert rig.run.calls == []


def test_an_edit_beside_a_base_spawn_finding_is_measured(rig: Rig) -> None:
    """
    GIVEN a base file that already imports importlib.import_module, CPU judged
    WHEN the trial edits that file without touching the loader's statements
    THEN the runner hands check_capture the file's base, so the trial is measured
    """
    trial = rig.trial({LOADER: LOADER_PY + b"\n\nCACHE = {}\n"})

    assert (trial.status, trial.violations) == (TrialStatus.measured, ())
    assert rig.run.calls


def test_a_new_use_of_the_base_import_is_refused_before_it_runs(rig: Rig) -> None:
    trial = rig.trial({LOADER: LOADER_PY + b"\n\nPROC = import_module('subprocess')\n"})

    assert [v.rule for v in trial.violations] == [ViolationRule.process_spawn]
    assert "uses spawn-bound import_module" in trial.violations[0].message
    _never_run(rig, trial)


def test_an_edit_that_does_not_parse_is_unparsable_source(rig: Rig) -> None:
    """
    GIVEN an editor slip: dedupe/core.py rewritten with a missing colon
    WHEN the trial is captured with CPU time judged
    THEN its one violation is unparsable_source naming the file, the line and
        the parser's message, it is not process_spawn, and nothing ran
    """
    trial = rig.trial({"dedupe/core.py": b"def unique(xs)\n    return xs\n"})

    [violation] = trial.violations
    assert (violation.rule, violation.path) == (
        ViolationRule.unparsable_source,
        "dedupe/core.py",
    )
    assert "'dedupe/core.py'" in violation.message
    assert "(line 1: " in violation.message
    assert "process_spawn" not in str(trial.error)
    assert "unparsable_source" in str(trial.error)
    _never_run(rig, trial)


def test_a_base_read_that_fails_fails_the_trial_before_it_runs(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    GIVEN a base blob git cannot hand over (past MAX_OUTPUT_BYTES)
    WHEN the spawn rule reads the modified file's base
    THEN the trial fails as uncapturable, and nothing ran
    """
    real = GitWorkspace.read_blob

    def read(
        self: GitWorkspace, commit: str, path: str, *, limit: int | None = None
    ) -> bytes:
        if path == LOADER and limit is None:
            raise GitError("git cat-file failed: output past the limit")
        return real(self, commit, path, limit=limit)

    monkeypatch.setattr(GitWorkspace, "read_blob", read)

    trial = rig.trial({LOADER: LOADER_PY + b"# harmless\n"})

    assert "the change could not be captured" in str(trial.error)
    assert "output past the limit" in str(trial.error)
    _never_run(rig, trial)


# --------------------------------------------------------------------------
# N0b: one re-edit for an unparsable_source refusal, within the run's retry.
# --------------------------------------------------------------------------


def _feedback_names_the_slip(feedback: str | None) -> None:
    assert feedback is not None
    assert f"'{CORE}'" in feedback
    assert f"(line {DEF_LINE}: expected ':')" in feedback
    assert "nothing in it was scanned or run" in feedback


def test_an_unparsable_edit_gets_one_re_edit_and_runs_only_once_it_parses(
    rig: Rig,
) -> None:
    """
    GIVEN a first edit that drops a colon in dedupe/core.py (and adds a file)
    WHEN the run still has its fix retry
    THEN the editor gets one fresh request whose feedback names the file, the
        line and the parser's message; it finds its slip still in the worktree;
        nothing ran before the re-edit parsed; the result is one measured
        commit on the base holding both attempts' writes
    """
    editor = Attempts([{CORE: SLIP, EXTRA: b"X = 1\n"}, {CORE: FIXED}], rig.run)

    trial = rig.attempt(editor, fix_retries=1, left=1)

    assert (trial.status, trial.error, trial.violations) == (
        TrialStatus.measured,
        None,
        (),
    )
    assert trial.attempts == 2
    assert trial.retry_notes == (f"{UNPARSABLE}; retried",)
    first, second = editor.tasks
    assert first.feedback is None and second.boundary != first.boundary
    _feedback_names_the_slip(second.feedback)
    assert editor.found == [BASE_CORE, SLIP]  # D14: the change is still there
    assert editor.launches == [0, 0]  # nothing ran before the re-edit
    assert rig.run.calls  # the parsed re-edit ran
    assert set(trial.touched_paths) == {CORE, EXTRA}
    assert trial.commit is not None and rig.own_ref() == trial.commit
    assert _unfit(GitWorkspace(rig.repo), rig.commit, trial.commit) is None
    assert trial.cost_usd == pytest.approx(0.02) and trial.tokens_used == 20


def test_a_re_edit_that_still_does_not_parse_is_never_run(rig: Rig) -> None:
    editor = Attempts([{CORE: SLIP}, {EXTRA: b"X = 1\n"}], rig.run)

    trial = rig.attempt(editor, fix_retries=1, left=1)

    _never_run(rig, trial)
    assert trial.attempts == 2 and len(editor.tasks) == 2
    [violation] = trial.violations  # the first failure's
    assert (violation.rule, violation.path) == (ViolationRule.unparsable_source, CORE)
    assert set(trial.touched_paths) == {CORE}
    (note,) = trial.retry_notes
    assert note.startswith(f"{UNPARSABLE}; retry: the change breaks 1 anti-cheat")
    assert note.endswith(KEPT)
    assert rig.own_ref() is None
    assert trial.cost_usd == pytest.approx(0.02)


@pytest.mark.parametrize(
    ("retry", "note"),
    [
        ({"fix_retries": 1, "left": 0}, f"{UNPARSABLE}; not retried: the run's fix retry is spent"),
        ({"fix_retries": 1, "left": 1, "floor": 5.0}, "below the retry floor of 5.000000 USD"),
        ({"fix_retries": 0, "left": 1}, None),
    ],
    ids=["spent", "unaffordable", "off"],
)  # fmt: skip
def test_a_re_edit_not_allowed_keeps_the_refusal(
    rig: Rig, retry: dict[str, float], note: str | None
) -> None:
    editor = Attempts([{CORE: SLIP}, {CORE: FIXED}], rig.run)

    trial = rig.attempt(editor, **retry)  # type: ignore[arg-type]

    _never_run(rig, trial)
    assert trial.attempts == 1 and len(editor.tasks) == 1
    assert [v.rule for v in trial.violations] == [ViolationRule.unparsable_source]
    assert len(trial.retry_notes) == (note is not None)
    assert all(note is not None and note in n for n in trial.retry_notes)


@pytest.mark.parametrize(
    ("files", "read_deny"),
    [
        ({CORE: SLIP, "tests/test_extra.py": b"pass\n"}, ()),
        ({"dedupe/secrets.py": b"def f(\n"}, ()),
        ({CORE: SLIP}, (CORE,)),
    ],
    ids=["another-rule", "deny-listed", "read-deny"],
)
def test_no_re_edit_beside_another_rule_or_on_a_file_the_editor_may_not_read(
    rig: Rig, files: Mapping[str, bytes], read_deny: tuple[str, ...]
) -> None:
    """
    GIVEN an unparsable file next to another anti-cheat refusal, or on a path
        the editor may not read (READ_DENY_PATTERNS, the brief's read_deny)
    WHEN the run still has its fix retry
    THEN no re-edit is asked, nothing is noted, and nothing ran
    """
    editor = Attempts([files, {CORE: FIXED}], rig.run)

    trial = rig.attempt(editor, fix_retries=1, left=1, read_deny=read_deny)

    _never_run(rig, trial)
    assert ViolationRule.unparsable_source in {v.rule for v in trial.violations}
    assert (trial.attempts, trial.retry_notes, len(editor.tasks)) == (1, (), 1)


def test_a_re_edit_that_crashes_keeps_the_refusal_and_drops_its_commit(
    rig: Rig,
) -> None:
    """
    GIVEN a re-edit that parses, is committed and measured, then crashes
        with a fixable error
    WHEN the trial ends
    THEN it is not retried again (one fix retry a trial); the first failure
        is kept, so the own ref the re-edit moved is gone again
    """
    rig.run.crashes = [CRASH]
    editor = Attempts([{CORE: SLIP}, {CORE: FIXED}], rig.run)

    trial = rig.attempt(editor, fix_retries=1, left=1)

    assert trial.status is TrialStatus.failed and trial.attempts == 2
    assert (trial.commit, trial.measurements) == (None, ())
    assert [v.rule for v in trial.violations] == [ViolationRule.unparsable_source]
    assert trial.retry_notes == (f"{UNPARSABLE}; retry: NameError, {KEPT}",)
    assert len(editor.tasks) == 2 and rig.run.calls
    assert rig.own_ref() is None


def test_a_crashing_re_edit_puts_a_prior_own_ref_back_before_dropping_it(
    rig: Rig,
) -> None:
    """A re-run of a trial whose own ref exists (a resume): the re-edit moved
    the ref from the earlier commit, and the kept refusal drops it as a
    non-retried refusal does."""
    earlier = rig.attempt(WriteEditor({CORE: FIXED}))
    assert earlier.commit is not None and rig.own_ref() == earlier.commit
    rig.run.crashes = [CRASH]
    editor = Attempts([{CORE: SLIP}, {CORE: FIXED + b"# again\n"}], rig.run)

    trial = rig.attempt(editor, fix_retries=1, left=1)

    assert trial.retry_notes == (f"{UNPARSABLE}; retry: NameError, {KEPT}",)
    assert trial.commit is None and rig.own_ref() is None


CFG = Settings.model_validate(
    {"ENGINE_MODEL": "claude-opus-5-5", "ENGINE_FALLBACKS": False, "LLM_MAX_RETRIES": 0}
)


def _reply(stop: str, *content: dict[str, object]) -> dict[str, object]:
    return {"id": "m", "type": "message", "role": "assistant", "model": CFG.ENGINE_MODEL,
            "content": list(content), "stop_reason": stop, "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 10}}  # fmt: skip


def _replace(old: bytes, new: bytes) -> dict[str, object]:
    command = {"command": "str_replace", "path": f"/repo/{CORE}",
               "old_str": old.decode(), "new_str": new.decode()}  # fmt: skip
    return _reply("tool_use", {"type": "tool_use", "id": "t",
                               "name": "str_replace_based_edit_tool", "input": command})  # fmt: skip


def test_the_real_editor_gets_the_parse_error_fenced_as_run_output(rig: Rig) -> None:
    done = _reply("end_turn", {"type": "text", "text": "Done."})
    replies = [_replace(SIGNATURE, SIGNATURE[:-1]), done,
               _replace(SIGNATURE[:-1] + b"\n", SIGNATURE + b"  # fixed\n"), done]  # fmt: skip
    transport = ScriptedTransport(replies, cfg=CFG)
    editor = ClaudeEditor(transport, config=CFG, sleep=lambda _: None)

    trial = rig.attempt(editor, fix_retries=1, left=1, budget=5.0)

    assert trial.status is TrialStatus.measured and trial.attempts == 2
    retry = json.dumps(transport.requests[2].messages[0])
    assert "<untrusted_run_output boundary=" in retry
    _feedback_names_the_slip(json.loads(retry)["content"][0]["text"])
    assert "</untrusted_run_output" not in json.dumps(transport.requests[0].messages[0])
