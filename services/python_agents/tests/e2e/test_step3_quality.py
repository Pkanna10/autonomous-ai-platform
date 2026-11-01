"""Step 3 E2E (U26): the quality check and the noise rule, E3-F to E3-I.

Each scenario runs the real factory (``build_context(quality=...)``) on the
classify fixture (``tests/fixtures/step3_quality/repo``) in ``tmp_path``: real
git, preflight, baseline with the frozen labels, calibration, profiler, paired
trial runner, confirmation, combiner and publisher, the real launcher and
sandbox, under the Step 3 defaults. The workload prints one prediction per
line, about 0.5 s of counting loop; the labels are ``data/labels.txt``,
scored by the builtin ``accuracy`` (98.12 % at the base). Claude is a
``ScriptedTransport`` on the editor's chain (``role_transports``; E3-H's
labels edit adds ``ScriptedEditor``, a raw write past the editor tool, as
Step 2's E2E-B does). No API key, no network. Outcomes only: no timing is
asserted except E3-I's injected 2x drift, against a 0.75 margin.
"""

from __future__ import annotations

import dataclasses
import json
import os
import shutil
from collections.abc import Mapping, Sequence
from collections.abc import Set as AbstractSet
from pathlib import Path
from typing import Literal, cast

import pytest

from autonomous_ai_agents.clients.budget import Budget
from autonomous_ai_agents.clients.transport import LLMTransport, ScriptedTransport
from autonomous_ai_agents.common.config import Role, Settings, role_settings, settings
from autonomous_ai_agents.common.models import (
    METRIC_WALL_TIME_S as WALL,
)  # fmt: skip
from autonomous_ai_agents.common.models import (
    BuiltinMeasure,
    ChangeClass,
    DeliveryKind,
    Direction,
    Guardrail,
    GuardrailKind,
    Hypothesis,
    HypothesisSource,
    Measurement,
    Project,
    QualityCheck,
    Trial,
    TrialStatus,
    Verdict,
    VerdictOutcome,
    ViolationRule,
    Workload,
)
from autonomous_ai_agents.execution.fakes import ScriptedEditor
from autonomous_ai_agents.execution.procrun import OutputCaps, RunSample
from autonomous_ai_agents.execution.protocols import CodeEditor, EditResult, EditTask
from autonomous_ai_agents.execution.sandbox import SandboxPolicy
from autonomous_ai_agents.execution.trial_runner import EditorFactory
from autonomous_ai_agents.orchestrator.factory import (
    build_context,
    claude_editor_factory,
)
from autonomous_ai_agents.orchestrator.main import EngineRunResult, Orchestrator
from autonomous_ai_agents.orchestrator.state import EngineState
from autonomous_ai_agents.persistence.repository import Repository

from .conftest import FIXTURES, Isolation, LaunchLog, UserRepo, git

pytestmark = pytest.mark.slow

Json = dict[str, object]
FIXTURE = FIXTURES / "step3_quality"
RAW_EDITS = FIXTURE / "edits"  # ScriptedEditor's edit sets, by hypothesis title
EDITS = cast(dict[str, str], json.loads((FIXTURE / "edits.json").read_text("utf-8")))
MODEL, LABELS, SCORER = "classify/model.py", "data/labels.txt", "score.py"
TESTS = ("python", "-m", "unittest", "discover", "-s", "tests", "-t", ".")
METRIC = "quality:accuracy"
BASE, EXACT, LAX = 0.9812, 1.0, 0.8904  # 47 and 274 of 2,500 readings wrong
IMPROVED = "accuracy 98.1 % → 100.0 % (result improvement)"
BUILTIN = QualityCheck(name="accuracy", measure=BuiltinMeasure.accuracy,
                       labels=LABELS, frozen_paths=(LABELS,), max_drop=0.005)  # fmt: skip
EXTERNAL = QualityCheck(name="accuracy", scorer=("python3", SCORER),
                        frozen_paths=(SCORER, LABELS), direction=Direction.maximize,
                        max_drop=0.005)  # fmt: skip
FAKE = "aip-quality/1 accuracy=1.0"  # what the rewritten worktree scorer prints


class Launches(LaunchLog):
    """``LaunchLog`` (the real ``run_once``) plus probes on the same seam.

    ``clock`` (E3-I) replaces every sample's ``wall_ns`` (the engine's time
    objective, as the launcher reports it) and pins ``maxrss_bytes``, so
    the verdicts are exact: ``"drift"`` is 1 s until the first launch of a
    trial or its twin and 0.5 s from then on, a host that turned 2x faster
    after the baseline; ``"burst"`` is 0.5 s on the trial's own phase
    (``trial-*``) only, a transient one paired look cannot tell from a win.
    ``None`` keeps the real numbers. ``faked``: the trial phases whose
    worktree held the fake scorer right after a launch (E3-H's rewrite
    happened); ``scored``: where the user's scorer ran; ``copy_seen``: the
    phases launched while ``<run>/quality`` (the frozen copy) existed.
    """

    def __init__(self, clock: Literal["drift", "burst"] | None = None) -> None:
        super().__init__()
        self.clock, self.drifting = clock, False
        self.faked: set[str] = set()
        self.scored: list[str] = []  # the phase of every launch of score.py
        self.copy_seen: set[str] = set()

    def __call__(
        self, argv: Sequence[str], cwd: Path, env: Mapping[str, str],
        sandbox: SandboxPolicy, timeout_s: float, caps: OutputCaps, *,
        fresh_dirs: Sequence[Path] = (),
    ) -> RunSample:  # fmt: skip
        where = Path(os.path.realpath(cwd)).relative_to(settings.WORKTREE_ROOT)
        copy = settings.WORKTREE_ROOT / where.parts[0] / "quality"
        before = copy.exists()
        sample = super().__call__(argv, cwd, env, sandbox, timeout_s, caps,
                                  fresh_dirs=fresh_dirs)  # fmt: skip
        phase = self.launches[-1].phase
        if before or copy.exists():
            self.copy_seen.add(phase)
        if any(arg.endswith(f"/{SCORER}") for arg in argv):
            self.scored.append(phase)
        fake = Path(cwd, SCORER)
        if phase.startswith("trial-") and fake.is_file() and FAKE in fake.read_text():
            self.faked.add(phase)
        self.drifting = self.drifting or phase.startswith(("trial-", "twin-trial-"))
        if self.clock is None:
            return sample
        fast = self.drifting if self.clock == "drift" else phase.startswith("trial-")
        wall = 500_000_000 if fast else 1_000_000_000
        return dataclasses.replace(sample, wall_ns=wall, maxrss_bytes=50_000_000)


class _ByTitle:
    """``CodeEditor``: ``ScriptedEditor`` for a title with an edit set under
    ``RAW_EDITS``, else the scripted ``ClaudeEditor``."""

    def __init__(self, claude: CodeEditor) -> None:
        self.claude, self.raw = claude, ScriptedEditor(RAW_EDITS)

    def edit(self, worktree: Path, task: EditTask, budget: Budget) -> EditResult:
        raw = (RAW_EDITS / task.hypothesis.title).is_dir()
        return (self.raw if raw else self.claude).edit(worktree, task, budget)


def _by_title_editor(transport: LLMTransport) -> EditorFactory:
    claude = claude_editor_factory(transport, sleep=lambda _: None)

    def make(
        *, module_roots: AbstractSet[str], reserved_modules: AbstractSet[str]
    ) -> CodeEditor:
        return _ByTitle(claude(module_roots=module_roots, reserved_modules=reserved_modules))  # fmt: skip

    return make


def _reply(n: int, content: list[Json], stop: str) -> Json:
    return {
        "id": f"msg_01E3Q{n:04d}", "type": "message", "role": "assistant",
        "model": settings.ENGINE_MODEL, "content": content, "stop_reason": stop,
        "stop_sequence": None, "usage": {"input_tokens": 900, "output_tokens": 200},
    }  # fmt: skip


def _tool(n: int, **command: str) -> Json:
    use: Json = {"type": "tool_use", "id": f"toolu_01E3Q{n:016d}",
           "name": "str_replace_based_edit_tool", "input": command}  # fmt: skip
    return _reply(n, [use], "tool_use")


def _edit(path: str, old: str, new: str, n: int, *, views: Sequence[str] = ()) -> list[Json]:  # fmt: skip
    """A view of each of ``views`` (tool ids ``n + 50``, ``n + 51``, ...), a
    str_replace on ``path`` (id ``n``), then the closing answer."""
    viewed = [_tool(n + 50 + i, command="view", path=f"/repo/{v}") for i, v in enumerate(views)]  # fmt: skip
    edit = _tool(n, command="str_replace", path=f"/repo/{path}", old_str=old, new_str=new)  # fmt: skip
    return [*viewed, edit, _reply(n + 100, [{"type": "text", "text": "Done."}], "end_turn")]  # fmt: skip


def _no_factory(cfg: Settings) -> LLMTransport:
    raise AssertionError("an E2E scenario reached the real transport factory")


def _repo(tmp_path: Path) -> UserRepo:
    """The classify fixture, committed on main in ``tmp_path``."""
    path = Path(os.path.realpath(tmp_path)) / "user"
    shutil.copytree(FIXTURE / "repo", path, ignore=shutil.ignore_patterns("__pycache__"))  # fmt: skip
    git(path.parent, "init", "-q", "-b", "main", str(path))
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "base")
    return UserRepo(path, git(path, "rev-parse", "HEAD"))


@dataclasses.dataclass(frozen=True)
class Scene:
    repo: UserRepo
    project: Project
    quality: QualityCheck
    editor: ScriptedTransport


def _run(
    tmp_path: Path, isolation: Isolation, launches: LaunchLog, edits: Sequence[Json],
    titles: Sequence[str], run_id: str, *, quality: QualityCheck = BUILTIN,
    raw: bool = False, repository: Repository | None = None,
) -> tuple[Scene, EngineRunResult]:  # fmt: skip
    """One run of efficiency ideas ``titles``, in that order, in one round."""
    # ``edits`` is one queue: the editor pops it trial by trial, so it must be
    # scripted in ``titles`` order (equal scores keep the input order,
    # ranking.py, and one round holds every title), skipping raw edit sets.
    repo = _repo(tmp_path)
    project = Project(name="classify", root_path=str(repo.path), test_command=TESTS)
    workload = Workload(project_id=project.id, name="classify",
                        command=("python", "-m", "classify.main"))  # fmt: skip
    editor = ScriptedTransport(edits, cfg=role_settings(settings, "editor"))
    roles: dict[Role, LLMTransport] = {} if raw else {"editor": editor}
    ideas = [
        Hypothesis(project_id=project.id, source=HypothesisSource.playbook,
                   title=title, rationale=f"{title}: a scripted classify rewrite",
                   change_class=ChangeClass.efficiency, expected_gain=0.8,
                   provability=0.9, risk=0.1)
        for title in titles
    ]  # fmt: skip
    ctx = build_context(
        project, candidates=ideas, role_transports=roles, transport_factory=_no_factory,
        editor=_by_title_editor(editor) if raw else None, quality=quality,
        network=isolation.mode, fs=isolation.mode, run=launches,
        sleep=lambda _: None, max_hypotheses_per_round=len(titles),
        repository=repository,
    )  # fmt: skip
    suite = Guardrail(project_id=project.id, kind=GuardrailKind.tests_pass,
                      description="the unittest suite passes")  # fmt: skip
    result = Orchestrator(context=ctx).run(project, [workload], [], [suite], run_id=run_id)  # fmt: skip
    assert result.status == "done", result.state["error"]
    assert editor.remaining == 0
    return Scene(repo, project, quality, editor), result


def _by_title(state: EngineState) -> tuple[dict[str, Trial], dict[str, Verdict]]:
    titles = {h.id: h.title for h in state["hypotheses"]}
    return ({titles[t.hypothesis_id]: t for t in state["trials"]},
            {titles[v.hypothesis_id]: v for v in state["verdicts"]})  # fmt: skip


def _mean(rows: Sequence[Measurement], metric: str) -> float:
    (row,) = [m for m in rows if m.metric == metric]
    return row.stats.mean


def _guardrail_alone(verdict: Verdict) -> None:
    """Rejected by the guardrail judge alone, on the quality bound."""
    failed = {r.judge: r.reason for r in verdict.judge_results if r.outcome.value == "failed"}  # fmt: skip
    assert verdict.outcome is VerdictOutcome.reject and list(failed) == ["guardrail"]
    assert METRIC in failed["guardrail"], failed


def _unexecuted(trial: Trial, rule: ViolationRule, path: str, launches: LaunchLog) -> None:  # fmt: skip
    """Rejected at capture: no commit, the rule on ``path``, nothing launched."""
    assert trial.commit is None and trial.status is TrialStatus.failed, trial.error
    assert (rule, path) in {(v.rule, v.path) for v in trial.violations}, (
        trial.violations,
        trial.error,
    )
    assert not [x for x in launches.launches if x.phase.endswith(trial.hypothesis_id)]


def _check_clean(scene: Scene, state: EngineState, isolation: Isolation, launches: LaunchLog) -> None:  # fmt: skip
    """Exactly the committed trials' refs and, when shipped, the review
    branch were added (never ``engine/run-<id>``: no scenario has a keep that
    holds); the user's tree untouched, every worktree and the run directory
    gone, every launch sandboxed as asked; quality mode ran (the frozen
    labels recorded and protected, no equivalence guardrail)."""
    repo, run = scene.repo, state["run_id"]
    assert git(repo.path, "rev-parse", "HEAD") == repo.base
    assert git(repo.path, "status", "--porcelain", "--ignored") == ""
    created = {f"refs/heads/engine/trial-{run}-{t.hypothesis_id}": t.commit
               for t in state["trials"] if t.commit is not None}  # fmt: skip
    shipped = state["review_delivery"]
    if shipped is not None:
        created[f"refs/heads/engine/review-{run}"] = str(shipped.commit)
    assert repo.refs() == {"refs/heads/main": repo.base, **created}
    assert repo.worktrees() == [f"worktree {repo.path}"]
    assert not (settings.WORKTREE_ROOT / run).exists()
    for launch in launches.launches:
        assert (launch.network, launch.fs) == (isolation.mode, isolation.mode)
        if isolation.missing is None:
            assert launch.net_isolated and launch.fs_isolated, launch
    baseline, check = state["baseline"], scene.quality
    assert baseline is not None
    calibrated = baseline.calibration.blocks if baseline.calibration else 0
    assert calibrated == settings.NOISE_CALIBRATION_BLOCKS
    assert [f.path for f in baseline.quality_files] == list(check.frozen_paths)
    assert set(check.frozen_paths) <= set(state["extra_protected"])
    kinds = {g.kind for g in state["guardrails"]}
    assert GuardrailKind.output_equivalence not in kinds
    assert METRIC in {g.metric for g in state["guardrails"]}
    assert _mean(baseline.measurements, METRIC) == pytest.approx(BASE, abs=1e-9)


def _review_tip(scene: Scene, state: EngineState, path: str) -> str:
    """The review branch's ``path``; both reports label it (refs: _check_clean)."""
    shipped, delivery = state["review_delivery"], state["delivery"]
    assert shipped is not None and shipped.branch == f"engine/review-{state['run_id']}"
    assert delivery is not None and delivery.kind is DeliveryKind.report_only
    for report in (delivery.report_markdown, shipped.report_markdown):
        assert IMPROVED in report, report
    changed = git(scene.repo.path, "diff", "--name-only", scene.repo.base, str(shipped.commit))  # fmt: skip
    assert changed == path
    return git(scene.repo.path, "show", f"{shipped.commit}:{path}") + "\n"


def _result(editor: ScriptedTransport, n: int) -> Json:
    """The tool_result of tool id ``n``; each later request resends it alike."""
    found = [block for request in editor.requests for message in request.messages
             if message["role"] == "user" and not isinstance(message["content"], str)
             for block in cast(list[Json], message["content"])
             if block.get("tool_use_id") == f"toolu_01E3Q{n:016d}"]  # fmt: skip
    assert found and all(block == found[0] for block in found), found
    return found[0]


def _with(path: str, old: str, new: str) -> str:
    return (FIXTURE / "repo" / path).read_text("utf-8").replace(old, new)


# ---------------------------------------------------------------------------
# E3-F and E3-G: a better result goes to review, a worse one is rejected
# ---------------------------------------------------------------------------


def test_e3_f_g_a_better_result_goes_to_review_and_a_worse_one_is_rejected(
    tmp_path: Path, isolation: Isolation, e2e_repository: Repository
) -> None:
    """
    GIVEN the builtin accuracy check over the frozen labels (max_drop 0.005)
          and two efficiency ideas: the exact threshold (faster, 100 %) and a
          lax one (faster, 89.04 %); Step 3 defaults; Postgres when set
    WHEN the run goes through the factory's context
    THEN the exact one is a confirmed review on engine/review-<id> labelled
         "result improvement", never on a run branch; the lax one is
         rejected by the guardrail judge alone
    """
    launches = Launches()
    edits = [*_edit(MODEL, EDITS["slow"], EDITS["exact"], 0),
             *_edit(MODEL, EDITS["slow"], EDITS["lax"], 1)]  # fmt: skip
    scene, result = _run(tmp_path, isolation, launches, edits, ["exact", "lax"],
                         "e3-f", repository=e2e_repository)  # fmt: skip

    trials, verdicts = _by_title(result.state)
    assert _mean(trials["exact"].measurements, METRIC) == EXACT
    assert _mean(trials["exact"].base_measurements, METRIC) == pytest.approx(BASE)
    better = verdicts["exact"]
    assert (better.outcome, better.confirmations) == (VerdictOutcome.review, 2)
    assert any(r.output_changed for r in better.judge_results)
    assert _review_tip(scene, result.state, MODEL) == _with(MODEL, EDITS["slow"], EDITS["exact"])  # fmt: skip
    assert _mean(trials["lax"].measurements, METRIC) == pytest.approx(LAX)
    _guardrail_alone(verdicts["lax"])
    _check_clean(scene, result.state, isolation, launches)
    run, state = result.state["run_id"], result.state  # read back (Postgres if set)
    stored = e2e_repository.get_run(run)
    assert stored is not None and stored["review_delivery"] == state["review_delivery"]
    base = stored["baseline"]
    assert base is not None and base == state["baseline"]
    assert [(f.path, f.size) for f in base.quality_files] == [(LABELS, 5000)]
    listed = {v.trial_id: v for v in e2e_repository.list_verdicts(run)}
    assert listed[trials["exact"].id].confirmations == 2
    saved = {t.id: t for t in e2e_repository.list_trials(run)}
    assert (
        saved[trials["exact"].id].base_measurements == trials["exact"].base_measurements
    )
    lessons = e2e_repository.list_lessons(scene.project.id)
    assert VerdictOutcome.review in {lesson.outcome for lesson in lessons}


# ---------------------------------------------------------------------------
# E3-H: the frozen labels cannot be edited, named, read or viewed
# ---------------------------------------------------------------------------


def test_e3_h_the_labels_are_protected_named_masked_hidden_and_a_table_is_review_only(
    tmp_path: Path, isolation: Isolation
) -> None:
    """
    GIVEN the builtin check and four ideas: a raw write to the labels
          (ScriptedEditor), code opening data/labels.txt by name, code opening
          it spelled in parts, and an editor that views the labels (refused)
          and then prints a literal table of their values
    WHEN the run goes through the factory's context
    THEN the first two are rejected unexecuted (protected_path, then U27's
         quality_data_reference tripwire, a78275a), the third runs and fails
         at the mask (FileNotFoundError, no retry), the view returns the
         refusal and no label, and the table is a review, never kept
    """
    launches = Launches()
    labels = (FIXTURE / "repo" / LABELS).read_text("utf-8")
    # One string, not a list literal: compiling 2,500 list items adds ~2 MB
    # of peak RSS (+15 % on CPython 3.11), past the memory guardrail
    table = f"    return list({''.join(labels.split())!r})\n"
    edits = [*_edit(MODEL, EDITS["list"], EDITS["named"], 0),
             *_edit(MODEL, EDITS["list"], EDITS["parts"], 1),
             *_edit(MODEL, EDITS["list"], table, 2, views=("data", LABELS))]  # fmt: skip
    titles = ["edit-labels", "named", "parts", "table"]
    scene, result = _run(tmp_path, isolation, launches, edits, titles, "e3-h", raw=True)  # fmt: skip

    trials, verdicts = _by_title(result.state)
    _unexecuted(trials["edit-labels"], ViolationRule.protected_path, LABELS, launches)
    _unexecuted(trials["named"], ViolationRule.quality_data_reference, MODEL, launches)
    parts = trials["parts"]
    assert parts.commit is not None and parts.status is TrialStatus.failed
    assert "FileNotFoundError" in str(parts.error) and parts.attempts == 1
    assert [x for x in launches.launches if x.phase == f"trial-{parts.hypothesis_id}"]
    assert all(verdicts[t].outcome is VerdictOutcome.reject for t in titles[:3])
    listed, viewed = _result(scene.editor, 52), _result(scene.editor, 53)
    assert listed.get("is_error") is not True and "labels.txt" not in json.dumps(listed)
    text = json.dumps(viewed["content"])
    assert viewed.get("is_error") is True and "evaluation data, off limits" in text
    assert "0\\n1" not in text and "1\\n0" not in text, text
    baked = verdicts["table"]
    assert (baked.outcome, baked.confirmations) == (VerdictOutcome.review, 2)
    assert _review_tip(scene, result.state, MODEL) == _with(MODEL, EDITS["list"], table)
    _check_clean(scene, result.state, isolation, launches)


def test_e3_h_a_rewritten_worktree_scorer_does_not_score(
    tmp_path: Path, isolation: Isolation
) -> None:
    """
    GIVEN the user's scorer (python3 score.py) frozen with the labels, and
          code that rewrites the worktree's score.py at run time to print a
          perfect score, then predicts with the lax threshold (89.04 %)
    WHEN the run goes through the factory's context
    THEN the fake was written in the trial's worktree, every scoring ran in
         the engine's quality phase, the trial scored the frozen copy's
         89.04 %, and the guardrail judge rejected it
    """
    launches = Launches()
    edits = _edit(MODEL, EDITS["list"], EDITS["rewrite"], 0)
    scene, result = _run(tmp_path, isolation, launches, edits, ["rewrite"], "e3-hs",
                         quality=EXTERNAL)  # fmt: skip

    (trial,), (verdict,) = result.state["trials"], result.state["verdicts"]
    assert launches.faked == {f"trial-{trial.hypothesis_id}"}
    assert launches.scored and set(launches.scored) == {"quality"}
    assert launches.copy_seen == {"quality"}  # the copy never outlives a scoring
    assert _mean(trial.measurements, METRIC) == pytest.approx(LAX)
    _guardrail_alone(verdict)
    _check_clean(scene, result.state, isolation, launches)


# ---------------------------------------------------------------------------
# E3-I: A/A under drift
# ---------------------------------------------------------------------------


Case = tuple[bool, Literal["drift", "burst"], VerdictOutcome, float, str]
E3I: dict[str, Case] = {  # step3, clock, outcome, verdict gain, summary start
    "step2-drift": (False, "drift", VerdictOutcome.keep, 0.5, "keep: all judges passed"),
    "step3-drift": (True, "drift", VerdictOutcome.inconclusive, 0.0, "inconclusive: judge speed inconclusive"),
    "step3-burst": (True, "burst", VerdictOutcome.inconclusive, 0.5, "inconclusive: did not confirm"),
}  # fmt: skip


@pytest.mark.parametrize("case", list(E3I))
def test_e3_i_a_comment_only_trial_under_drift_is_not_kept(
    tmp_path: Path, isolation: Isolation, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    """
    GIVEN the builtin check, a comment-only idea, and a synthetic clock
          (Launches.clock): "drift", 1 s until the first trial or twin launch
          and 0.5 s after; "burst", 0.5 s on the trial's own launches only
    WHEN the run goes through the factory's context: Step 2's path (no
         pairing, confirmation or calibration) or the Step 3 defaults
    THEN Step 2's path keeps the drift as a 50 % win against the run
         baseline; Step 3's speed judge reads the paired A rows, sees no
         gain and is inconclusive on the first look (floor 2 %, calibrated);
         the burst wins the paired look by 50 % and fails confirmation:
         0 of 1 winner(s) confirmed, inconclusive "did not confirm"
    """
    step3, clock, outcome, gain, reason = E3I[case]
    if not step3:
        for key, value in {"PAIRED_TRIALS": False, "CONFIRM_WINNERS": False,
                           "NOISE_CALIBRATION_BLOCKS": 0}.items():  # fmt: skip
            monkeypatch.setattr(settings, key, value)
    launches = Launches(clock=clock)
    edits = _edit(MODEL, EDITS["slow"], EDITS["comment"], 0)
    scene, result = _run(tmp_path, isolation, launches, edits, ["comment"], f"e3-i-{case}")  # fmt: skip

    (trial,), (verdict,) = result.state["trials"], result.state["verdicts"]
    baseline = result.state["baseline"]
    assert baseline is not None
    assert (_mean(baseline.measurements, WALL), _mean(trial.measurements, WALL)) == (1.0, 0.5)  # fmt: skip
    (speed,) = [r for r in verdict.judge_results if r.judge == "speed"]
    paired = trial.base_measurements if step3 else baseline.measurements
    (reference,) = [m for m in paired if m.metric == WALL]
    assert speed.baseline == reference.stats  # the A rows under Step 3 (D41 a)
    assert (speed.noise_floor, verdict.gain, verdict.outcome) == (0.02, gain, outcome)
    assert verdict.summary.startswith(reason), verdict.summary
    assert not any(r.output_changed for r in verdict.judge_results)
    confirmed = [e.message for e in result.state["events"] if e.message.startswith("confirmation:")]  # fmt: skip
    if step3:
        assert baseline.calibration is not None and baseline.calibration.floor == 0.02
        assert reference.stats.mean == (0.5 if clock == "drift" else 1.0)
        assert verdict.confirmations == 1 and result.state["review_delivery"] is None
        delivery = result.state["delivery"]
        assert delivery is not None and delivery.kind is DeliveryKind.report_only
        assert confirmed == (["confirmation: 0 of 1 winner(s) confirmed on a second look"] if clock == "burst" else [])  # fmt: skip
    _check_clean(scene, result.state, isolation, launches)
