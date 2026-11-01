"""Step 2 E2E: the whole loop on the dedupe fixture, through the engine factory.

Every scenario builds the context with ``build_context`` (real preflight,
baseline, profiler, trial runner, combiner and publisher, the real launcher
and sandbox), runs ``Orchestrator.run`` on a git repository in ``tmp_path``
and asserts outcomes only, never timings (the h1 margin is about 8x):

- E2E-A, the real Claude path: a scripted understand reply, then
  ``ClaudeEditor`` over ``WorktreeEditor`` on a ``ScriptedTransport``; h1's
  transcript tries four writes the editor must refuse before its real edit;
  h3 sorts the result and only the equivalence judge catches it.
- E2E-B, the git-side defence: ``ScriptedEditor`` edit sets; h2 deletes a
  test, h6 adds a symlink, h5 conflicts with h1 at combine. On Postgres when
  ``TEST_DATABASE_URL`` is set.
- E2E-C, the budget: the trial floor is set so the second trial never starts.

All three also assert that the user's HEAD, index, status, config, hooks
and info are unchanged, that the refs created are exactly the committed
trials' refs plus the delivery ref, that no pre-existing ref moved, and that
no worktree or run directory is left; and that every phase that runs
repository code (preflight's probe, baseline, profile, trials, both combine
sides) launched with the scenario's isolation modes, and under ``required``
was reported isolated by the launcher. No scenario has an API key or makes
a network call.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

import pytest
from anthropic.types.beta import BetaMessage

from autonomous_ai_agents.clients.cost import response_cost
from autonomous_ai_agents.clients.transport import (
    LLMRequest,
    LLMTransport,
    ScriptedTransport,
)
from autonomous_ai_agents.common.config import Settings, settings
from autonomous_ai_agents.common.models import (
    METRIC_TESTS_PASSED,
    ChangeClass,
    DeliveryKind,
    EngineEvent,
    EventLevel,
    Guardrail,
    GuardrailKind,
    Hypothesis,
    HypothesisSource,
    JudgeOutcome,
    Project,
    Trial,
    TrialStatus,
    Verdict,
    VerdictOutcome,
    ViolationRule,
    Workload,
)
from autonomous_ai_agents.execution.fakes import ScriptedEditor
from autonomous_ai_agents.orchestrator.factory import build_context
from autonomous_ai_agents.orchestrator.main import EngineRunResult, Orchestrator
from autonomous_ai_agents.persistence.repository import Repository

from .conftest import (
    FIXTURES,
    Isolation,
    LaunchLog,
    RepoFactory,
    RepoSnapshot,
    UserRepo,
    git,
)

pytestmark = pytest.mark.slow

DEDUPE_EDITS = FIXTURES / "dedupe_edits"
TRANSCRIPT = FIXTURES / "transcripts" / "e2e_a_h1_attack_then_edit.json"
TEST_COMMAND = ("python", "-m", "unittest", "discover", "-s", "tests", "-t", ".")
CORE = "dedupe/core.py"
FIXTURE_TESTS = 11  # the dedupe fixture's unittest suite
LAUNCH_PHASES = {
    "preflight",
    "baseline",
    "profile",
    "trial-*",
    "combine",
    "combine-base",
}
"""Every phase that runs repository code; each scenario launches in all."""
ENGINE = "claude-opus-5-5"
H1_ATTACKS = {
    "toolu_01H1GitHook000000000000001": "git metadata",
    "toolu_01H1DotDot0000000000000002": "must be absolute",
    "toolu_01H1Symlink000000000000003": "symlink",
    "toolu_01H1Tests0000000000000004": "protected",
}
SLOW_LOOP = (
    "    result: list[int] = []\n"
    "    for item in items:\n"
    "        if item not in result:\n"
    "            result.append(item)\n"
    "    return result\n"
)
Json = dict[str, object]
STEP2_MODE = {
    "PAIRED_TRIALS": False,
    "CONFIRM_WINNERS": False,
    "NOISE_CALIBRATION_BLOCKS": 0,
}
"""The Step 2 loop, which this file verifies: the noise rule (D41) off."""


@pytest.fixture(autouse=True)
def step2_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin ``STEP2_MODE`` in the settings and the environment (the killed
    run's child process reads its settings from the environment)."""
    for key, value in STEP2_MODE.items():
        monkeypatch.setattr(settings, key, value)
        monkeypatch.setenv(key, str(value).lower())


# ---------------------------------------------------------------------------
# Scripted Claude replies
# ---------------------------------------------------------------------------


def _usage(fresh: int, written: int, read: int, output: int) -> Json:
    return {
        "input_tokens": fresh,
        "cache_creation_input_tokens": written,
        "cache_read_input_tokens": read,
        "cache_creation": {
            "ephemeral_5m_input_tokens": written,
            "ephemeral_1h_input_tokens": 0,
        },
        "output_tokens": output,
        "service_tier": "standard",
    }


def _message(name: str, content: list[Json], stop: str, usage: Json) -> Json:
    return {
        "id": f"msg_01E2E{name}",
        "type": "message",
        "role": "assistant",
        "model": ENGINE,
        "content": content,
        "stop_reason": stop,
        "stop_sequence": None,
        "usage": usage,
    }


def _understand_reply(workload: Workload, output: int = 240) -> Json:
    answer = {
        "language": "python",
        "summary": "dedupe: order-preserving de-duplication of integers.",
        "entrypoints": ["dedupe/main.py"],
        "workload_notes": [
            {"workload_id": workload.id, "note": "dedupes 15,000 integers"}
        ],
        "candidate_modules": [
            {"path": CORE, "reason": "unique_in_order scans a list per item"}
        ],
    }
    text: Json = {"type": "text", "text": json.dumps(answer)}
    return _message("Understand", [text], "end_turn", _usage(3100, 0, 0, output))


def _h1_replies() -> list[Json]:
    data = json.loads(TRANSCRIPT.read_text(encoding="utf-8"))
    return cast(list[Json], data["replies"])


def _h3_replies() -> list[Json]:
    """Sort the distinct values: same set, different order (tests still pass)."""
    edit: Json = {
        "type": "tool_use",
        "id": "toolu_01H3Sorted0000000000001",
        "name": "str_replace_based_edit_tool",
        "input": {
            "command": "str_replace",
            "path": "/repo/dedupe/core.py",
            "old_str": SLOW_LOOP,
            "new_str": "    return sorted(set(items))\n",
        },
    }
    done: Json = {
        "type": "text",
        "text": "unique_in_order now returns sorted(set(items)).",
    }
    return [
        _message("H3Edit", [edit], "tool_use", _usage(4, 2900, 0, 310)),
        _message("H3Done", [done], "end_turn", _usage(4, 380, 2900, 60)),
    ]


def _priced(replies: Sequence[Json]) -> float:
    total = 0.0
    for reply in replies:
        message = BetaMessage.model_validate(reply)
        usd, _ = response_cost(
            message.usage, settings.MODEL_PRICING, model=message.model
        )
        total += usd
    return total


def _tool_results(requests: Sequence[LLMRequest]) -> dict[str, Mapping[str, object]]:
    """Every tool_result block the editor sent back, by tool_use id."""
    found: dict[str, Mapping[str, object]] = {}
    for request in requests:
        for message in request.messages:
            content = message["content"]
            if message["role"] != "user" or isinstance(content, str):
                continue
            for raw in content:
                block = cast(Mapping[str, object], raw)
                if block["type"] == "tool_result":
                    found[str(block["tool_use_id"])] = block
    return found


def _no_real_transport(cfg: Settings) -> LLMTransport:
    raise AssertionError("an E2E scenario reached the real transport factory")


# ---------------------------------------------------------------------------
# Scenario builders and the shared checks
# ---------------------------------------------------------------------------


def _project(repo: UserRepo) -> Project:
    return Project(name="dedupe", root_path=str(repo.path), test_command=TEST_COMMAND)


def _workload(project: Project) -> Workload:
    return Workload(
        project_id=project.id, name="dedupe", command=("python", "-m", "dedupe.main")
    )


def _guardrails(project: Project) -> list[Guardrail]:
    return [
        Guardrail(
            project_id=project.id,
            kind=GuardrailKind.tests_pass,
            description="the unittest suite passes",
        ),
        Guardrail(
            project_id=project.id,
            kind=GuardrailKind.output_equivalence,
            description="the workload prints the same digest",
        ),
    ]


def _candidate(project: Project, title: str, expected_gain: float) -> Hypothesis:
    return Hypothesis(
        project_id=project.id,
        source=HypothesisSource.playbook,
        title=title,
        rationale=f"{title}: a scripted dedupe rewrite",
        change_class=ChangeClass.efficiency,
        expected_gain=expected_gain,
        provability=0.9,
        risk=0.1,
    )


def _run(
    ctx_project: Project,
    workload: Workload,
    orchestrator: Orchestrator,
    *,
    max_cost_usd: float | None = None,
) -> EngineRunResult:
    return orchestrator.run(
        ctx_project,
        [workload],
        [],
        _guardrails(ctx_project),
        max_cost_usd=max_cost_usd,
    )


def _by_title(
    result: EngineRunResult, candidates: Sequence[Hypothesis]
) -> dict[str, Trial]:
    titles = {h.id: h.title for h in candidates}
    return {titles[t.hypothesis_id]: t for t in result.state["trials"]}


def _verdicts(
    result: EngineRunResult, candidates: Sequence[Hypothesis]
) -> dict[str, Verdict]:
    titles = {h.id: h.title for h in candidates}
    return {titles[v.hypothesis_id]: v for v in result.state["verdicts"]}


def _coded(result: EngineRunResult, code: str) -> list[EngineEvent]:
    return [e for e in result.state["events"] if e.data.get("code") == code]


def _check_repo_untouched(
    repo: UserRepo,
    before: RepoSnapshot,
    result: EngineRunResult,
    candidates: Sequence[Hypothesis],
    committed: set[str],
) -> None:
    """The "All three also assert" list of spec section 6."""
    state = result.state
    run = state["run_id"]
    after = repo.snapshot()
    assert (after.head, after.head_ref, after.index_sha256) == (
        before.head,
        before.head_ref,
        before.index_sha256,
    )
    assert (after.status, after.config) == (before.status, before.config)
    assert (after.hooks, after.info) == (before.hooks, before.info)
    titles = {h.id: h.title for h in candidates}
    trials = {t.hypothesis_id: t for t in state["trials"] if t.commit is not None}
    assert {titles[hypothesis] for hypothesis in trials} == committed
    expected = {
        f"refs/heads/engine/trial-{run}-{hypothesis}": trial.commit
        for hypothesis, trial in trials.items()
    }
    delivery = state["delivery"]
    assert delivery is not None
    if delivery.kind is DeliveryKind.branch:
        expected[f"refs/heads/engine/run-{run}"] = delivery.commit
    review = state["review_delivery"]  # Step 3 (D10): engine/review-<id>
    if review is not None:
        expected[f"refs/heads/engine/review-{run}"] = review.commit
    created = {ref: sha for ref, sha in after.refs.items() if ref not in before.refs}
    assert created == expected
    assert {ref: after.refs.get(ref) for ref in before.refs} == before.refs
    assert repo.worktrees() == [f"worktree {repo.path}"]
    assert not (settings.WORKTREE_ROOT / run).exists()


def _check_isolation(
    subtests: pytest.Subtests,
    isolation: Isolation,
    result: EngineRunResult,
    launches: LaunchLog,
) -> None:
    """Every phase launched with the scenario's modes, and every run was
    sandboxed; only the latter is skipped, and only where the host cannot."""
    assert launches.phases() == LAUNCH_PHASES
    for launch in launches.launches:
        assert (launch.network, launch.fs) == (isolation.mode, isolation.mode), launch
    with subtests.test("isolation"):
        if isolation.missing is not None:
            pytest.skip(f"isolation not asserted: {isolation.missing}")
        for launch in launches.launches:
            assert launch.net_isolated and launch.fs_isolated, launch
        (event,) = _coded(result, "isolation")
        assert event.level is EventLevel.info
        assert event.data["network"] == event.data["fs"] == "required"
        baseline = result.state["baseline"]
        assert baseline is not None
        rows = [*baseline.measurements]
        for trial in result.state["trials"]:
            rows.extend(trial.measurements)
        assert rows
        for row in rows:
            runs = row.hardware["runs"]
            assert row.hardware["fs_isolated_runs"] == runs, row
            assert row.hardware["net_isolated_runs"] == runs, row


def _judge(trial: Trial, name: str) -> JudgeOutcome:
    (result,) = [r for r in trial.judge_results if r.judge == name]
    return result.outcome


# ---------------------------------------------------------------------------
# E2E-A: the real Claude path
# ---------------------------------------------------------------------------


def test_e2e_a_real_claude_path(
    dedupe_repo: RepoFactory,
    isolation: Isolation,
    launches: LaunchLog,
    subtests: pytest.Subtests,
) -> None:
    """
    GIVEN the dedupe repo (with a dedupe/fast.py -> core.py symlink), a
          scripted understand reply, h1's attack-then-edit transcript and an
          h3 transcript that sorts the result, all through ClaudeEditor and
          WorktreeEditor on one ScriptedTransport
    WHEN the run goes through the factory's context
    THEN the four attacks get is_error results, h1 is kept, h3 is rejected
         by the equivalence judge, the real profiler finds unique_in_order,
         the combination holds with its tests run on the tip, the tip is the
         base plus h1, and the cost is the scripted usage priced, under the cap
    """
    repo = dedupe_repo(symlink=True)
    before = repo.snapshot()
    project = _project(repo)
    workload = _workload(project)
    h1, h3 = _candidate(project, "h1", 0.8), _candidate(project, "h3", 0.5)
    replies = [_understand_reply(workload), *_h1_replies(), *_h3_replies()]
    transport = ScriptedTransport(replies)
    ctx = build_context(
        project,
        candidates=[h1, h3],
        transport=transport,
        transport_factory=_no_real_transport,
        network=isolation.mode,
        fs=isolation.mode,
        run=launches,
        sleep=lambda _: None,
    )

    result = _run(project, workload, Orchestrator(context=ctx))

    assert result.status == "done", result.state["error"]
    state = result.state
    understanding = state["understanding"]
    assert understanding is not None and understanding.served_by_model == ENGINE
    assert [m.path for m in understanding.candidate_modules] == [CORE]
    assert any(
        h.file_path == CORE and "unique_in_order" in h.symbol for h in state["hotspots"]
    ), state["hotspots"]

    found = _tool_results(transport.requests)
    for tool_id, reason in H1_ATTACKS.items():
        assert found[tool_id]["is_error"] is True
        assert reason in str(found[tool_id]["content"])
    assert "is_error" not in found["toolu_01H1Replace00000000000005"]
    assert "is_error" not in found["toolu_01H3Sorted0000000000001"]

    trials, verdicts = _by_title(result, [h1, h3]), _verdicts(result, [h1, h3])
    assert verdicts["h1"].outcome is VerdictOutcome.keep
    assert verdicts["h3"].outcome is VerdictOutcome.reject
    assert trials["h3"].status is TrialStatus.measured
    assert _judge(trials["h3"], "equivalence") is JudgeOutcome.failed
    assert _judge(trials["h3"], "tests") is JudgeOutcome.passed
    assert verdicts["h3"].violations == ()
    for trial in (trials["h1"], trials["h3"]):
        (suite,) = [m for m in trial.measurements if m.metric == METRIC_TESTS_PASSED]
        assert suite.samples == (1.0,)
        assert suite.hardware["tests_counted"] == FIXTURE_TESTS

    combination = state["combination"]
    assert combination is not None and combination.holds
    assert combination.applied_trial_ids == (trials["h1"].id,)
    assert combination.fallback_trial_id is None
    tests = [r for r in combination.judge_results if r.judge == "tests"]
    assert [r.outcome for r in tests] == [JudgeOutcome.passed]
    delivery = state["delivery"]
    assert delivery is not None and delivery.kind is DeliveryKind.branch
    tip = delivery.commit
    assert tip is not None and tip == combination.tip_commit
    assert git(repo.path, "rev-parse", f"{tip}^") == repo.base
    assert git(repo.path, "diff", "--name-only", repo.base, tip) == CORE
    h1_commit = trials["h1"].commit
    assert h1_commit is not None
    assert git(repo.path, "rev-parse", f"{tip}^{{tree}}") == git(
        repo.path, "rev-parse", f"{h1_commit}^{{tree}}"
    )
    expected_core = (DEDUPE_EDITS / "h1" / "files" / CORE).read_text()
    assert git(repo.path, "show", f"{tip}:{CORE}") + "\n" == expected_core

    assert transport.remaining == 0
    assert state["cost_usd"] == pytest.approx(_priced(replies), rel=1e-9)
    assert state["cost_usd"] <= state["max_cost_usd"]
    _check_repo_untouched(repo, before, result, [h1, h3], {"h1", "h3"})
    _check_isolation(subtests, isolation, result, launches)


# ---------------------------------------------------------------------------
# E2E-B: the git-side defence
# ---------------------------------------------------------------------------


def test_e2e_b_git_side_defence(
    dedupe_repo: RepoFactory,
    isolation: Isolation,
    e2e_repository: Repository,
    launches: LaunchLog,
    subtests: pytest.Subtests,
) -> None:
    """
    GIVEN ScriptedEditor edit sets in one round of four: h1 (a set), h2 (a
          set and a deleted test), h6 (a symlink and a set) and h5
          (dict.fromkeys on the same lines, lower score)
    WHEN the run goes through the factory's context
    THEN h2 is rejected protected_path and h6 forbidden_file_mode, neither
         measured nor committed; h5 is kept, then skipped as a conflict; the
         combination of h1 holds and the delivery branch carries exactly one
         Engine-Trial commit; the lessons are stored with uuid hypothesis ids
    """
    repo = dedupe_repo()
    before = repo.snapshot()
    project = _project(repo)
    workload = _workload(project)
    candidates = [
        _candidate(project, "h1", 0.9),
        _candidate(project, "h2", 0.85),
        _candidate(project, "h6", 0.8),
        _candidate(project, "h5", 0.5),
    ]
    editor = ScriptedEditor(DEDUPE_EDITS)
    ctx = build_context(
        project,
        candidates=candidates,
        repository=e2e_repository,
        max_hypotheses_per_round=4,
        editor=lambda **_: editor,
        transport_factory=_no_real_transport,
        network=isolation.mode,
        fs=isolation.mode,
        run=launches,
    )

    result = _run(project, workload, Orchestrator(context=ctx))

    assert result.status == "done", result.state["error"]
    assert sorted(editor.calls) == ["h1", "h2", "h5", "h6"]
    trials, verdicts = _by_title(result, candidates), _verdicts(result, candidates)
    for title, rule in (
        ("h2", ViolationRule.protected_path),
        ("h6", ViolationRule.forbidden_file_mode),
    ):
        trial = trials[title]
        assert trial.status is TrialStatus.failed
        assert (trial.commit, trial.measurements) == (None, ())
        assert rule in {v.rule for v in trial.violations}
        assert verdicts[title].outcome is VerdictOutcome.reject
        assert rule in {v.rule for v in verdicts[title].violations}
    assert {v.path for v in trials["h2"].violations} >= {"tests/test_core.py"}
    assert {v.path for v in trials["h6"].violations} >= {"dedupe/fast.py"}
    assert verdicts["h1"].outcome is VerdictOutcome.keep
    assert verdicts["h5"].outcome is VerdictOutcome.keep

    combination = result.state["combination"]
    assert combination is not None and combination.holds
    assert combination.applied_trial_ids == (trials["h1"].id,)
    assert [(s.trial_id, s.reason) for s in combination.skipped] == [
        (trials["h5"].id, "conflict")
    ]
    delivery = result.state["delivery"]
    assert delivery is not None and delivery.kind is DeliveryKind.branch
    assert delivery.verdict_ids == (verdicts["h1"].id,)
    branch = f"refs/heads/engine/run-{result.state['run_id']}"
    messages = git(repo.path, "log", "--format=%B%x00", f"{repo.base}..{branch}")
    commits = [m for m in messages.split("\x00") if m.strip()]
    assert len(commits) == 1
    assert f"Engine-Trial: {trials['h1'].id}" in commits[0]

    lessons = e2e_repository.list_lessons(project.id)
    ids = {h.id for h in candidates}
    assert len(lessons) == 4
    for lesson in lessons:
        assert lesson.hypothesis_id in ids
        assert str(uuid.UUID(lesson.hypothesis_id)) == lesson.hypothesis_id
    run_id = result.state["run_id"]
    stored = e2e_repository.get_run(run_id)
    assert stored is not None and stored["delivery"] == delivery
    assert {t.id for t in e2e_repository.list_trials(run_id)} == {
        t.id for t in trials.values()
    }
    _check_repo_untouched(repo, before, result, candidates, {"h1", "h5"})
    _check_isolation(subtests, isolation, result, launches)


# ---------------------------------------------------------------------------
# E2E-C: the budget
# ---------------------------------------------------------------------------


def test_e2e_c_budget_stops_the_second_trial(
    dedupe_repo: RepoFactory,
    isolation: Isolation,
    launches: LaunchLog,
    subtests: pytest.Subtests,
) -> None:
    """
    GIVEN a cap every request of the first trial fits under, and the trial
          floor set to cap - cost(understand) - cost(trial 1) + 0.01 from the
          scripted usage and prices
    WHEN the run goes through the factory's context
    THEN the second trial never starts (its replies stay queued), a
         budget_exhausted warning is emitted, the router goes to combine and
         the run's cost stays within the cap
    """
    repo = dedupe_repo(symlink=True)
    before = repo.snapshot()
    project = _project(repo)
    workload = _workload(project)
    h1, h3 = _candidate(project, "h1", 0.8), _candidate(project, "h3", 0.5)
    understand, first, second = (
        [_understand_reply(workload)],
        _h1_replies(),
        _h3_replies(),
    )
    cap = 2.0
    floor = cap - _priced(understand) - _priced(first) + 0.01
    transport = ScriptedTransport([*understand, *first, *second])
    ctx = build_context(
        project,
        candidates=[h1, h3],
        transport=transport,
        transport_factory=_no_real_transport,
        min_trial_budget_usd=floor,
        network=isolation.mode,
        fs=isolation.mode,
        run=launches,
        sleep=lambda _: None,
    )

    result = _run(project, workload, Orchestrator(context=ctx), max_cost_usd=cap)

    assert result.status == "done", result.state["error"]
    state = result.state
    assert ctx.min_trial_budget_usd == floor
    assert transport.remaining == len(second)
    assert [t.hypothesis_id for t in state["trials"]] == [h1.id]
    assert _by_title(result, [h1, h3])["h1"].status is TrialStatus.measured
    (stopped,) = _coded(result, "budget_exhausted")
    assert stopped.level is EventLevel.warning
    assert stopped.data["not_started"] == 1
    assert state["budget_exhausted"] is True
    phases = [e.phase.value for e in state["events"]]
    assert phases.index("combine") > phases.index("verdicts")
    assert state["round"] == 1
    combination = state["combination"]
    assert combination is not None and combination.holds
    assert state["cost_usd"] == pytest.approx(
        _priced(understand) + _priced(first), rel=1e-9
    )
    assert state["cost_usd"] <= state["max_cost_usd"] == cap
    _check_repo_untouched(repo, before, result, [h1, h3], {"h1"})
    _check_isolation(subtests, isolation, result, launches)


def test_e2e_c_the_default_floor_never_starts_a_trial_it_cannot_afford(
    dedupe_repo: RepoFactory,
    isolation: Isolation,
    launches: LaunchLog,
) -> None:
    """
    GIVEN the factory's default trial floor, and a cap that lets understand
          (a long reply) run and then leaves a little more than the floor,
          but less than the first editor request of a trial (system prompt,
          tools and brief priced)
    WHEN the run goes through the factory's context
    THEN no editor request is sent, no trial, verdict or lesson is recorded
         for h1 or h3, a budget_exhausted warning counts both, and the run
         delivers the report only
    """
    repo = dedupe_repo(symlink=True)
    before = repo.snapshot()
    project = _project(repo)
    workload = _workload(project)
    h1, h3 = _candidate(project, "h1", 0.8), _candidate(project, "h3", 0.5)
    understand = [_understand_reply(workload, output=7000)]
    transport = ScriptedTransport([*understand, *_h1_replies(), *_h3_replies()])
    ctx = build_context(
        project,
        candidates=[h1, h3],
        transport=transport,
        transport_factory=_no_real_transport,
        network=isolation.mode,
        fs=isolation.mode,
        run=launches,
        sleep=lambda _: None,
    )
    cap = _priced(understand) + ctx.min_trial_budget_usd + 0.03

    result = _run(project, workload, Orchestrator(context=ctx), max_cost_usd=cap)

    assert result.status == "done", result.state["error"]
    state = result.state
    assert len(transport.requests) == 1  # understand only
    assert state["trials"] == [] and state["verdicts"] == [] and state["lessons"] == []
    assert ctx.repository.list_lessons(project.id) == ()
    (stopped,) = _coded(result, "budget_exhausted")
    assert stopped.data["not_started"] == 2
    assert "first request does not fit" in stopped.message
    delivery = state["delivery"]
    assert delivery is not None and delivery.kind is DeliveryKind.report_only
    assert state["cost_usd"] == pytest.approx(_priced(understand), rel=1e-9)
    _check_repo_untouched(repo, before, result, [h1, h3], set())


_KILLED_RUN = """
import os, signal, sys
from pathlib import Path
from autonomous_ai_agents.common.models import (
    ChangeClass, Guardrail, GuardrailKind, Hypothesis, HypothesisSource, Project,
    Workload,
)
from autonomous_ai_agents.execution.fakes import ScriptedEditor
from autonomous_ai_agents.execution.procrun import run_once
from autonomous_ai_agents.orchestrator.factory import build_context
from autonomous_ai_agents.orchestrator.main import Orchestrator

repo, edits, mode, run_id = sys.argv[1:5]
project = Project(name="dedupe", root_path=repo, test_command=(
    "python", "-m", "unittest", "discover", "-s", "tests", "-t", "."))
workload = Workload(project_id=project.id, name="dedupe",
                    command=("python", "-m", "dedupe.main"))
h1 = Hypothesis(project_id=project.id, source=HypothesisSource.playbook, title="h1",
                rationale="a set", change_class=ChangeClass.efficiency,
                expected_gain=0.8, provability=0.9, risk=0.1)

def run(argv, cwd, *args, **kwargs):
    if "/trial-" in str(cwd):  # the first launch of the trial: kill -9
        os.kill(os.getpid(), signal.SIGKILL)
    return run_once(argv, cwd, *args, **kwargs)

editor = ScriptedEditor(Path(edits))
ctx = build_context(project, candidates=[h1], editor=lambda **_: editor,
                    network=mode, fs=mode, run=run)
guard = Guardrail(project_id=project.id, kind=GuardrailKind.tests_pass,
                  description="tests")
Orchestrator(context=ctx).run(project, [workload], [], [guard], run_id=run_id)
"""


def test_e2e_d_a_run_killed_in_a_trial_is_recovered_by_the_next_run(
    dedupe_repo: RepoFactory,
    isolation: Isolation,
    launches: LaunchLog,
    engine_settings: Path,
) -> None:
    """
    GIVEN a run killed with -9 in the middle of its trial: its worktree, the
          registration in the user's .git/worktrees, its scratch and probe
          dirs and its committed trial ref are left
    WHEN the next run (a new run id) goes through the factory's context
    THEN connect recovers the killed run's worktree, registration and dirs
         and says so; afterwards git lists only the main worktree and
         WORKTREE_ROOT holds nothing; the killed trial's ref is the only
         thing kept (for review, as every committed trial's ref)
    """
    repo = dedupe_repo()
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in ("ANTHROPIC_API_KEY", "WORKTREE_ROOT")
    }
    env["WORKTREE_ROOT"] = str(engine_settings)
    killed = "killed-run"
    child = subprocess.run(
        [sys.executable, "-c", _KILLED_RUN, str(repo.path), str(DEDUPE_EDITS),
         isolation.mode, killed],
        env=env, capture_output=True, check=False, timeout=600,
    )  # fmt: skip
    assert child.returncode == -signal.SIGKILL, child.stderr.decode(errors="replace")
    assert len(repo.worktrees()) == 2
    assert (engine_settings / killed).is_dir()
    before = repo.snapshot()
    assert any(
        ref.startswith(f"refs/heads/engine/trial-{killed}-") for ref in before.refs
    )
    project = _project(repo)
    workload = _workload(project)
    ctx = build_context(
        project,
        candidates=[_candidate(project, "h1", 0.8)],
        editor=lambda **_: ScriptedEditor(DEDUPE_EDITS),
        network=isolation.mode,
        fs=isolation.mode,
        run=launches,
    )

    result = _run(project, workload, Orchestrator(context=ctx))

    assert result.status == "done", result.state["error"]
    notes = [e.message for e in _coded(result, "preflight_note")]
    assert any(killed in note and "trial-" in note for note in notes), notes
    assert repo.worktrees() == [f"worktree {repo.path}"]
    assert os.listdir(engine_settings) == []
    admin = repo.common_dir() / "worktrees"
    assert not admin.exists() or os.listdir(admin) == []
    _check_repo_untouched(repo, before, result, ctx.candidates, {"h1"})


# ---------------------------------------------------------------------------
# The checks themselves
# ---------------------------------------------------------------------------


def test_the_repo_snapshot_sees_hooks_and_info(dedupe_repo: RepoFactory) -> None:
    """
    GIVEN the user's repository and its snapshot
    WHEN a hook is written, a hook made executable, or a symlink added to info
    THEN the snapshot's hooks or info differ (what _check_repo_untouched
         compares), while HEAD, index, status, config and refs do not
    """
    repo = dedupe_repo()
    before = repo.snapshot()
    hooks, info = repo.common_dir() / "hooks", repo.common_dir() / "info"

    (hooks / "pre-commit").write_text("#!/bin/sh\nexit 0\n")
    written = repo.snapshot()
    (hooks / "pre-commit").chmod(0o755)
    executable = repo.snapshot()
    (info / "attributes").symlink_to("exclude")
    linked = repo.snapshot()

    assert len({before.hooks, written.hooks, executable.hooks}) == 3
    assert executable.info == before.info != linked.info
    for after in (written, executable, linked):
        assert (after.head, after.index_sha256, after.status, after.config) == (
            before.head,
            before.index_sha256,
            before.status,
            before.config,
        )
        assert after.refs == before.refs
