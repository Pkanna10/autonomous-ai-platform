"""X2-DT E2E (U7): stacked rounds on real git, mechanics only, E3-S1 and E3-S2.

Each scenario runs the real factory (``build_context``) with
``STACKED_ROUNDS`` on (so U6's wiring builds the ``GitStacker`` on the
combiner's ``GitWorkspace``) and ``SITE_STACKS="on"`` (O71 item 1: gain
order is X2-DT's combine), on the ``stages`` fixture (``stacked_repo.py``)
in ``tmp_path``: real git, preflight, baseline, profiler, paired trial
runner, combiner, stacker and publisher, the real launcher and sandbox. No
API call and no transport: the ideas are caller candidates and the editor
is ``ScriptedEditor`` (whole-file edit sets), as in Step 2's E2E.

Speed differences are set by the code (sleeps the stages read), never by
timing luck: every keep removes at least 400 ms of sleep (about 40 % of the
origin's wall time, more of a tip's), clear of the start-up spikes a loaded
host adds (``stacked_repo``). Settings beyond the arm's, to bound the wall
time and to fix each round's ideas:

- ``PORTFOLIO_ROUNDS=3``, so a keep does not end the run before round 3;
- no warm-up run (a sleep needs none; the timed runs stay at ``MIN_RUNS``);
- the confirmation off: its second look is a combine re-test of one change,
  which ``ghost-b`` is built to fail, and on E3-S1 it would only add a
  re-test per keep, off the stacking path;
- no calibration block (``NOISE_CALIBRATION_BLOCKS=0``): the judges' floors
  stay each side's own spread and the 2 % minimum. It saves 10 launches per
  base measured, and on E3-S2 it makes the outputs check (which runs after
  the calibration) the one reason the held tip can be refused. The real
  calibrator at a tip is left to a live run (the fakes cover the stacking
  path's call, U5a).

Scenarios:

- E3-S1: two adopted tips, then a round with no keep. Trial parents follow
  the adopted tips; round 2 holds a real textual conflict pair resolved by
  gain against score order, dry-merged on round 2's base; a protected-path
  edit on the second tip is rejected unexecuted; the delivery is one squash
  commit on the origin whose tree is the last adopted tip's, and the diff
  published is the one its re-test measured.
- E3-S2: a round whose combine does not hold, then a round whose held tip is
  refused (its outputs differ when measured as a base): the base never
  moves, each round's keeps are offered again, and the last round's combine
  on the origin is the delivery (no squash).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Iterator, Mapping, Sequence
from pathlib import Path

import pytest

from autonomous_ai_agents.clients.transport import LLMTransport
from autonomous_ai_agents.common.config import Settings, settings
from autonomous_ai_agents.common.models import (
    ChangeClass,
    DeliveryKind,
    EngineEvent,
    Guardrail,
    GuardrailKind,
    Hypothesis,
    HypothesisSource,
    Project,
    StackLedger,
    Trial,
    TrialStatus,
    Verdict,
    VerdictOutcome,
    ViolationRule,
    Workload,
)
from autonomous_ai_agents.execution.combine import DryMerge, GitCombiner
from autonomous_ai_agents.execution.fakes import ScriptedEditor
from autonomous_ai_agents.execution.git import GitWorkspace
from autonomous_ai_agents.execution.protocols import Combiner, KeptChange
from autonomous_ai_agents.execution.stacking import GitStacker
from autonomous_ai_agents.orchestrator import combine_node
from autonomous_ai_agents.orchestrator.combine_node import order_gain
from autonomous_ai_agents.orchestrator.factory import build_context
from autonomous_ai_agents.orchestrator.main import EngineRunResult, Orchestrator
from autonomous_ai_agents.orchestrator.nodes import NodeContext
from autonomous_ai_agents.orchestrator.stack_round import (
    DID_NOT_HOLD,
    HELD,
    NOTHING_KEPT,
    OUTPUTS_DIFFER,
)
from autonomous_ai_agents.orchestrator.stacking import STACKED_TIP
from autonomous_ai_agents.orchestrator.state import EngineState

from . import stacked_repo
from .conftest import (
    UNTOUCHED_REFS,
    Isolation,
    Launch,
    LaunchLog,
    RepoSnapshot,
    UserRepo,
    git,
)

pytestmark = pytest.mark.slow


# ---------------------------------------------------------------------------
# The user's repository, the context and the spies
# ---------------------------------------------------------------------------


RepoMaker = Callable[[Mapping[str, int]], UserRepo]


@pytest.fixture
def stages_repo(tmp_path: Path) -> RepoMaker:
    """``make(origin_ms)``: the user's ``stages`` repository with those
    sleeps, one base commit on ``main``, plus the refs no run may touch."""

    def make(origin_ms: Mapping[str, int]) -> UserRepo:
        repo = Path(tmp_path).resolve() / "user"
        stacked_repo.write_tree(repo, stacked_repo.repo_files(origin_ms))
        git(repo.parent, "init", "-q", "-b", "main", str(repo))
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "base")
        for ref, target in UNTOUCHED_REFS.items():
            git(repo, "update-ref", ref, target)
        return UserRepo(repo, git(repo, "rev-parse", "HEAD"))

    return make


@dataclasses.dataclass(frozen=True)
class DryCall:
    base: str
    trial_ids: frozenset[str]


@dataclasses.dataclass(frozen=True)
class Retested:
    base: str
    offered: tuple[str, ...]
    tip: str
    holds: bool


@dataclasses.dataclass
class Spies:
    """What the real combiner and stacker were asked (wrapped, never changed)."""

    dry: list[DryCall] = dataclasses.field(default_factory=list)
    retests: list[Retested] = dataclasses.field(default_factory=list)
    squashes: list[tuple[str, str, str]] = dataclasses.field(default_factory=list)


@pytest.fixture
def spies(monkeypatch: pytest.MonkeyPatch) -> Iterator[Spies]:
    """The combiner's dry merges, every combine re-test and every squash."""
    seen = Spies()
    real_dry, real_squash = GitCombiner.dry_merge, GitStacker.squash
    real_retest = combine_node._retest  # conftest's spy: it still reports

    def dry_merge(
        self: GitCombiner, project: Project, base: str, kept: Sequence[KeptChange]
    ) -> DryMerge:
        seen.dry.append(DryCall(base, frozenset(c.trial_id for c in kept)))
        return real_dry(self, project, base, kept)

    def squash(
        self: GitStacker, project: Project, base: str, tip: str, label: str
    ) -> str:
        made = real_squash(self, project, base, tip, label)
        seen.squashes.append((base, tip, made))
        return made

    def retest(
        combiner: Combiner,
        offered: Sequence[KeptChange],
        rules: combine_node.CombineRules,
        target: combine_node.CombineTarget,
    ) -> combine_node.Retest:
        result = real_retest(combiner, offered, rules, target)
        seen.retests.append(
            Retested(
                target.base_commit,
                tuple(c.trial_id for c in offered),
                result.measured.tip_commit,
                result.holds,
            )
        )
        return result

    monkeypatch.setattr(GitCombiner, "dry_merge", dry_merge)
    monkeypatch.setattr(GitStacker, "squash", squash)
    monkeypatch.setattr(combine_node, "_retest", retest)
    yield seen


@dataclasses.dataclass(frozen=True)
class Scene:
    repo: UserRepo
    before: RepoSnapshot  # taken before the context is built
    project: Project
    workload: Workload
    ctx: NodeContext
    editor: ScriptedEditor


def _stacked(monkeypatch: pytest.MonkeyPatch) -> None:
    """The X2-DT arm's settings, plus this file's (module docstring)."""
    monkeypatch.setattr(settings, "STACKED_ROUNDS", True)
    monkeypatch.setattr(settings, "SITE_STACKS", "on")
    monkeypatch.setattr(settings, "PORTFOLIO_ROUNDS", 3)
    monkeypatch.setattr(settings, "NOISE_CALIBRATION_BLOCKS", 0)
    monkeypatch.setattr(settings, "CONFIRM_WINNERS", False)


def _scene(
    repo: UserRepo,
    isolation: Isolation,
    launches: LaunchLog,
    edits: Path,
    titles: Sequence[str],
    *,
    per_round: int,
) -> Scene:
    """The factory's context on ``repo``: ``titles`` as caller candidates,
    best score first (``per_round`` a round, so each round's ideas are
    fixed), every edit by ``ScriptedEditor``."""
    before = repo.snapshot()
    project = Project(
        name="stages", root_path=str(repo.path), test_command=stacked_repo.TEST_COMMAND
    )
    workload = Workload(
        project_id=project.id,
        name="stages",
        command=stacked_repo.WORKLOAD,
        warmup_runs=0,
    )
    candidates = tuple(
        Hypothesis(
            project_id=project.id, source=HypothesisSource.playbook, title=title,
            rationale=f"{title}: a scripted stage edit",
            change_class=ChangeClass.efficiency,
            expected_gain=0.9 - 0.1 * rank, provability=0.9, risk=0.1,
        )
        for rank, title in enumerate(titles)
    )  # fmt: skip
    editor = ScriptedEditor(stacked_repo.write_edits(edits))
    ctx = build_context(
        project, candidates=candidates, max_hypotheses_per_round=per_round,
        editor=lambda **_: editor, transport_factory=_no_transport,
        network=isolation.mode, fs=isolation.mode, run=launches,
        sleep=lambda _: None,
    )  # fmt: skip
    assert ctx.stack_rounds and isinstance(ctx.stacker, GitStacker)
    return Scene(repo, before, project, workload, ctx, editor)


def _no_transport(cfg: Settings) -> LLMTransport:
    raise AssertionError("an E2E scenario reached the real transport factory")


def _run(scene: Scene, run_id: str) -> EngineRunResult:
    """Three rounds; the caller checks the outcome (``_check_done``)."""
    guardrails = [
        Guardrail(project_id=scene.project.id, kind=GuardrailKind.tests_pass,
                  description="the unittest suite passes")
    ]  # fmt: skip
    return Orchestrator(context=scene.ctx).run(
        scene.project, [scene.workload], [], guardrails, run_id=run_id, max_rounds=3
    )


def _check_done(result: EngineRunResult) -> None:
    assert result.status == "done", result.state["error"]
    assert result.state["error"] is None


def _by_title(state: EngineState) -> tuple[dict[str, Trial], dict[str, Verdict]]:
    titles = {h.id: h.title for h in [*state["hypotheses"], *state["parked"]]}
    return (
        {titles[t.hypothesis_id]: t for t in state["trials"]},
        {titles[v.hypothesis_id]: v for v in state["verdicts"]},
    )


def _ledger(state: EngineState) -> StackLedger:
    ledger = state["stack"]
    assert ledger is not None
    return ledger


def _coded(state: EngineState, code: str) -> list[EngineEvent]:
    return [e for e in state["events"] if e.data.get("code") == code]


def _tree(repo: UserRepo, commit: str) -> str:
    return git(repo.path, "rev-parse", f"{commit}^{{tree}}")


def _parent(repo: UserRepo, commit: str) -> str:
    return git(repo.path, "rev-parse", f"{commit}^")


def _count(repo: UserRepo, base: str, tip: str) -> int:
    """Commits on ``tip`` that ``base`` lacks."""
    return int(git(repo.path, "rev-list", "--count", f"{base}..{tip}"))


def _file(repo: UserRepo, commit: str, path: str) -> str:
    """``path``'s text at ``commit`` (``git`` strips the last newline)."""
    return git(repo.path, "show", f"{commit}:{path}") + "\n"


def _launched(launches: LaunchLog, trial: Trial) -> list[Launch]:
    """The launches in ``trial``'s phases (``trial-<hyp>``, ``twin-trial-<hyp>``)."""
    return [x for x in launches.launches if x.phase.endswith(trial.hypothesis_id)]


def _check_trial(repo: UserRepo, trial: Trial, base: str, launches: LaunchLog) -> None:
    """A measured trial started from ``base``: its commit is a child of it,
    and ``_launched`` finds its launches (the positive control of
    ``_check_unexecuted``'s filter: a phase rename cannot make that pass
    vacuously)."""
    assert trial.base_commit == base
    assert trial.status is TrialStatus.measured, trial.error
    assert trial.commit is not None and _parent(repo, trial.commit) == base
    phases = {x.phase for x in _launched(launches, trial)}
    assert phases == {f"trial-{trial.hypothesis_id}",
                      f"twin-trial-{trial.hypothesis_id}"}, phases  # fmt: skip


def _check_unexecuted(trial: Trial, base: str, launches: LaunchLog) -> None:
    """Rejected at capture on ``base``: protected path, no commit, no launch."""
    assert trial.base_commit == base
    assert trial.status is TrialStatus.failed and trial.commit is None
    assert (ViolationRule.protected_path, stacked_repo.SUITE) in {
        (v.rule, v.path) for v in trial.violations
    }, trial.violations
    assert _launched(launches, trial) == []


def _measured_as_bases(repo: UserRepo, launches: LaunchLog) -> set[str]:
    """Every commit the baseline runner measured (its ``baseline`` phase),
    from the launch log and git alone: no run state is read."""
    heads = {x.commit for x in launches.launches if x.phase == "baseline"}
    return {git(repo.path, "rev-parse", "--verify", f"{h}^{{commit}}") for h in heads}


def _only_the_held_tip_measured(repo: UserRepo, launches: LaunchLog) -> set[str]:
    """E3-S2: the commits other than the origin measured as a base, each of
    them mask-b alone on the origin, so round 2's held tip. Round 1's tip
    (ghost-b alone) did not hold, so it is never measured as a base: a round
    adopted on a combine that did not hold fails here, before any run state
    is read (this runs even when the run stopped)."""
    mask_b = stacked_repo.EDITS["mask-b"]["stages/b.py"]
    others = _measured_as_bases(repo, launches) - {repo.base}
    for commit in others:
        assert _file(repo, commit, "stages/b.py") == mask_b, (
            f"{commit} was measured as a base without mask-b: a tip whose round "
            "combine did not hold was adopted"
        )
        assert _count(repo, repo.base, commit) == 1, commit
    return others


def _check_clean(
    scene: Scene, state: EngineState, isolation: Isolation, launches: LaunchLog
) -> None:
    """The engine never touched the default branch or the user's checkout:
    HEAD, index, status, config, hooks and info unchanged; the refs created
    are exactly the committed trials' and ``engine/run-<id>`` at the
    delivery; no pre-existing ref moved (``main`` included); no worktree or
    run directory left; every launch sandboxed as the scenario asked."""
    repo, run, before = scene.repo, state["run_id"], scene.before
    after = repo.snapshot()
    assert dataclasses.replace(after, refs={}) == dataclasses.replace(before, refs={})
    assert after.refs["refs/heads/main"] == repo.base == after.head
    expected: dict[str, str | None] = {
        f"refs/heads/engine/trial-{run}-{t.hypothesis_id}": t.commit
        for t in state["trials"]
        if t.commit is not None
    }
    delivery = state["delivery"]
    assert delivery is not None and delivery.kind is DeliveryKind.branch
    expected[f"refs/heads/engine/run-{run}"] = delivery.commit
    created = {ref: sha for ref, sha in after.refs.items() if ref not in before.refs}
    assert created == expected
    assert {ref: after.refs.get(ref) for ref in before.refs} == before.refs
    assert repo.worktrees() == [f"worktree {repo.path}"]
    assert not (settings.WORKTREE_ROOT / run).exists()
    for launch in launches.launches:
        assert (launch.network, launch.fs) == (isolation.mode, isolation.mode)
        if isolation.missing is None:
            assert launch.net_isolated and launch.fs_isolated, launch


# ---------------------------------------------------------------------------
# E3-S1: tips adopted, gain order on a round base, the squash delivered
# ---------------------------------------------------------------------------


def test_e3_s1_stacked_rounds_deliver_the_last_tip_squashed_on_the_origin(
    stages_repo: RepoMaker,
    isolation: Isolation,
    launches: LaunchLog,
    spies: Spies,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """
    GIVEN the X2-DT settings and two ideas a round, best score first:
          skip-a and edit-test-1, then halve-b and drop-b (the same line;
          halve-b scores higher, drop-b gains more), then slow-b and
          edit-test-2
    WHEN the run goes through the factory's context
    THEN round 1's trials start from the origin, round 2's from round 1's
         adopted tip and round 3's from round 2's; round 2's combine applies
         drop-b and skips halve-b blocked by it, after a dry merge on round
         2's base; edit-test-2 is rejected unexecuted on the second tip;
         round 3 keeps nothing, so the last adopted tip is squashed onto the
         origin: the run branch is that one commit, with the tip's tree, the
         commit the delivery re-test measured, and its published diff is
         the tip's diff from the origin; the default branch is untouched
    """
    _stacked(monkeypatch)
    titles = ("skip-a", "edit-test-1", "halve-b", "drop-b", "slow-b", "edit-test-2")
    repo = stages_repo(stacked_repo.S1_MS)
    scene = _scene(repo, isolation, launches, tmp_path / "edits", titles,
                   per_round=2)  # fmt: skip

    result = _run(scene, "e3-s1")

    _check_done(result)
    state, repo, origin = result.state, scene.repo, scene.repo.base
    trials, verdicts = _by_title(state)
    assert sorted(scene.editor.calls) == sorted(titles)
    ledger = _ledger(state)
    first, second, last = ledger.rounds
    assert (first.base_commit, first.adopted, first.reason) == (origin, True, HELD)
    tip1 = first.next_base
    assert (second.base_commit, second.adopted, second.reason) == (tip1, True, HELD)
    tip2 = second.next_base
    assert (last.base_commit, last.adopted, last.reason) == (tip2, False, NOTHING_KEPT)
    assert last.combination is None and last.tip_commit is None
    assert last.offered_trial_ids == ()
    assert len({origin, tip1, tip2}) == 3

    # Trial parents: each round's trials are children of its base, which
    # moved exactly when a held tip was adopted.
    _check_trial(repo, trials["skip-a"], origin, launches)
    _check_unexecuted(trials["edit-test-1"], origin, launches)
    _check_trial(repo, trials["halve-b"], tip1, launches)
    _check_trial(repo, trials["drop-b"], tip1, launches)
    _check_trial(repo, trials["slow-b"], tip2, launches)
    _check_unexecuted(trials["edit-test-2"], tip2, launches)
    for title in ("skip-a", "halve-b", "drop-b"):
        assert verdicts[title].outcome is VerdictOutcome.keep, verdicts[title]
    for title in ("edit-test-1", "edit-test-2"):
        assert verdicts[title].outcome is VerdictOutcome.reject, verdicts[title]
    # A loss is never kept; reject or inconclusive is the judges' read of
    # the spread on that host, not a stacking fact.
    assert verdicts["slow-b"].outcome is not VerdictOutcome.keep, verdicts["slow-b"]
    assert first.offered_trial_ids == (trials["skip-a"].id,)
    assert first.combination is not None and first.combination.tip_commit == tip1
    assert _parent(repo, tip1) == origin
    assert set(second.offered_trial_ids) == {trials["halve-b"].id, trials["drop-b"].id}
    assert second.combination is not None and second.combination.tip_commit == tip2
    assert _parent(repo, tip2) == tip1
    # Each tip was measured and profiled as a base before use (no
    # calibration block: no floor), and no other commit was.
    assert first.floor is None and second.floor is None
    for tip in (tip1, tip2):
        assert {"baseline", "profile"} <= {
            x.phase for x in launches.launches if x.commit == tip[:10]
        }
    assert _measured_as_bases(repo, launches) == {origin, tip1, tip2}
    assert [e.data["base"] for e in _coded(state, "stack_round")] == [
        origin, tip1, tip2,
    ]  # fmt: skip
    assert _coded(state, "stack_refused") == []

    # Gain order on round 2's base (O71): the higher gain wins the conflict,
    # against score order, recorded with its blocker.
    halve, drop = trials["halve-b"].id, trials["drop-b"].id
    scores = {h.title: h.score for h in state["hypotheses"]}
    assert scores["halve-b"] > scores["drop-b"]
    gain_halve, gain_drop = (order_gain(verdicts[t]) for t in ("halve-b", "drop-b"))
    assert gain_halve is not None and gain_drop is not None
    assert gain_drop > gain_halve
    combined = second.combination
    assert combined.holds and combined.applied_trial_ids == (drop,)
    assert combined.conflicts == (tuple(sorted((halve, drop))),)
    assert [(s.trial_id, s.reason, s.blocked_by) for s in combined.skipped] == [
        (halve, "conflict", drop)
    ]
    keeps = {k.trial_id: k for k in combined.keeps}
    assert keeps[drop].delivered and not keeps[halve].delivered
    assert keeps[halve].blocked_by == drop
    (r2_event,) = [e for e in _coded(state, "stack_round") if e.data["round"] == 2]
    assert r2_event.data["site_stacks"] == "on"
    assert halve[:8] in str(r2_event.data["skips"])
    # The dry merge ran on each round's base: the origin in round 1 only.
    assert spies.dry == [
        DryCall(origin, frozenset({trials["skip-a"].id})),
        DryCall(tip1, frozenset({halve, drop})),
    ]

    # Delivery at the original base: one squash commit, the last tip's tree.
    ((squash_base, squash_tip, squash),) = spies.squashes
    assert (squash_base, squash_tip) == (origin, tip2)
    assert _parent(repo, squash) == origin and _tree(repo, squash) == _tree(repo, tip2)
    delivery = state["delivery"]
    assert delivery is not None and delivery.kind is DeliveryKind.branch
    tip = str(delivery.commit)
    assert delivery.branch == f"engine/run-{state['run_id']}"
    assert repo.refs()[f"refs/heads/engine/run-{state['run_id']}"] == tip
    assert _parent(repo, tip) == origin
    assert _count(repo, origin, tip) == 1
    assert _tree(repo, tip) == _tree(repo, tip2)
    for name in ("a", "b"):
        assert _file(repo, tip, f"stages/{name}.py") == stacked_repo.stage(name, "0")

    # The published diff is the measured tip's: the delivery re-test (the
    # last re-test, from the origin, of the squash alone) measured this very
    # commit, ran there, and its diff from the origin is the published one.
    assert spies.retests[-1] == Retested(origin, (STACKED_TIP,), tip, True)
    raw = ledger.delivery
    assert raw is not None and raw.holds and raw.tip_commit == tip
    assert ledger.all_rounds_held is True and ledger.delivery_seconds is not None
    assert f"combine@{tip[:10]}" in {f"{x.phase}@{x.commit}" for x in launches.launches}
    workspace = GitWorkspace(repo.path)
    assert delivery.combined_diff == workspace.diff_commits(origin, tip2)
    assert delivery.combined_diff == workspace.diff_commits(origin, tip)
    combination = state["combination"]
    assert combination is not None and combination.holds
    assert (combination.base_commit, combination.tip_commit) == (origin, tip)
    assert combination.applied_trial_ids == (trials["skip-a"].id, drop)
    assert delivery.verdict_ids == (verdicts["skip-a"].id, verdicts["drop-b"].id)
    (delivered,) = _coded(state, "stack_delivery")
    assert delivered.data["retest"] is True and delivered.data["squash"] == squash
    assert (delivered.data["tip"], delivered.data["rounds"]) == (tip2, 2)
    baseline = state["baseline"]
    assert state["base_commit"] == origin
    assert baseline is not None and baseline.commit == origin
    _check_clean(scene, state, isolation, launches)


# ---------------------------------------------------------------------------
# E3-S2: the base moves only on adoption
# ---------------------------------------------------------------------------


def test_e3_s2_a_combine_that_fails_or_a_refused_tip_leaves_the_base(
    stages_repo: RepoMaker,
    isolation: Isolation,
    launches: LaunchLog,
    spies: Spies,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """
    GIVEN the X2-DT settings and one idea a round:
          ghost-b (a keep whose outputs differ in every combine re-test),
          mask-b (the same line, a higher gain, outputs that differ only
          when measured as a base), edit-test-1
    WHEN the run goes through the factory's context
    THEN round 1's combine does not hold (the equivalence judge); round 2's
         holds with mask-b alone (ghost-b blocked by it) and that tip is
         refused (its outputs differ from the original base): the base stays
         the origin, every trial starts there, each round offers the earlier
         keeps again, and the last round's combine on the origin is the
         delivery, with no squash and no second re-test
    """
    _stacked(monkeypatch)
    titles = ("ghost-b", "mask-b", "edit-test-1")
    repo = stages_repo(stacked_repo.S2_MS)
    scene = _scene(repo, isolation, launches, tmp_path / "edits", titles,
                   per_round=1)  # fmt: skip

    try:
        result = _run(scene, "e3-s2")
    finally:  # also when the run stops: read from the launches and git alone
        measured = _only_the_held_tip_measured(scene.repo, launches)

    _check_done(result)
    state, repo, origin = result.state, scene.repo, scene.repo.base
    trials, verdicts = _by_title(state)
    ghost, mask = trials["ghost-b"].id, trials["mask-b"].id
    _check_trial(repo, trials["ghost-b"], origin, launches)
    _check_trial(repo, trials["mask-b"], origin, launches)
    _check_unexecuted(trials["edit-test-1"], origin, launches)
    assert verdicts["ghost-b"].outcome is VerdictOutcome.keep
    assert verdicts["mask-b"].outcome is VerdictOutcome.keep

    ledger = _ledger(state)
    first, second, last = ledger.rounds
    assert [r.base_commit for r in ledger.rounds] == [origin] * 3
    assert first.offered_trial_ids == (ghost,)
    assert first.combination is not None and not first.combination.holds
    # Round 1 failed on its outputs alone: the equivalence judge, which
    # enforces the output_equivalence guardrail. Not on speed, and not on
    # the "guardrail" judge, which reads the metric bounds (peak RSS here).
    judged = [
        (j.judge, j.outcome.value, j.reason) for j in first.combination.judge_results
    ]
    assert {name for name, outcome, _ in judged if outcome == "failed"} == {
        "equivalence"
    }, judged
    assert not first.adopted and first.tip_commit is None
    assert first.reason == DID_NOT_HOLD
    assert set(second.offered_trial_ids) == {ghost, mask}
    assert second.combination is not None and second.combination.holds
    assert second.combination.applied_trial_ids == (mask,)
    assert second.combination.fallback_trial_id is None
    assert [
        (k.trial_id, k.reason, k.blocked_by) for k in second.combination.skipped
    ] == [(ghost, "conflict", mask)]
    refused = second.combination.tip_commit
    assert refused is not None and second.tip_commit == refused
    assert measured == {refused}
    assert not second.adopted and second.floor is None
    assert second.reason.startswith(OUTPUTS_DIFFER + ": "), second.reason
    (event,) = _coded(state, "stack_refused")
    assert (event.data["round"], event.data["tip"]) == (2, refused)
    assert set(last.offered_trial_ids) == {ghost, mask}
    assert last.combination is not None and last.combination.holds
    assert last.combination.applied_trial_ids == (mask,)
    assert ledger.all_rounds_held is False and ledger.delivery is None
    # The refused tip was measured as a base, then never used as one.
    assert f"baseline@{refused[:10]}" in {
        f"{x.phase}@{x.commit}" for x in launches.launches
    }
    assert {x.base for x in spies.dry} == {origin}
    assert {x.base for x in spies.retests} == {origin}
    assert spies.squashes == []
    baseline = state["baseline"]
    assert state["base_commit"] == origin
    assert baseline is not None and baseline.commit == origin

    # The last round's combine on the origin is the delivery.
    delivery, combination = state["delivery"], state["combination"]
    assert delivery is not None and combination is not None and combination.holds
    assert combination == last.combination
    tip = str(delivery.commit)
    assert tip == combination.tip_commit
    assert git(repo.path, "merge-base", origin, tip) == origin
    assert _parent(repo, tip) == origin and _count(repo, origin, tip) == 1
    assert combination.applied_trial_ids == (mask,)
    assert delivery.verdict_ids == (verdicts["mask-b"].id,)
    (delivered,) = _coded(state, "stack_delivery")
    assert delivered.data["retest"] is False and delivered.data["tip"] == tip
    _check_clean(scene, state, isolation, launches)
