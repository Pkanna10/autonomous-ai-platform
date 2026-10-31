"""Step 3 E2E (U14): wired discovery, the fix retry and the output check, E3-A to E3-E.

Each scenario runs the real factory (``build_context``) on the dedupe fixture
in ``tmp_path``: real git, preflight, baseline, calibration, profiler, paired
trial runner, confirmation, combiner and publisher, the real launcher and
sandbox. Claude is scripted (``tests/fixtures/step3/scripted.json``): one
``ScriptedTransport`` per role, on that role's chain, through
``role_transports``; no API key, no understand request (the Step 1 stub),
no network. Settings are the Step 3 defaults (paired trials, confirmation,
3 calibration blocks, the default output check, one fix retry a run) unless
a test says otherwise. Outcomes only, never timings: every scripted win is
the O(n^2) to O(n) fix, about 12x on a 0.55 s workload.
"""

from __future__ import annotations

import dataclasses
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

import pytest

from autonomous_ai_agents.clients.transport import (
    LLMRequest,
    LLMTransport,
    ScriptedTransport,
)
from autonomous_ai_agents.common.config import Role, Settings, role_settings, settings
from autonomous_ai_agents.common.models import (
    ApprovalDecision,
    ChangeClass,
    DeliveryKind,
    Guardrail,
    GuardrailKind,
    Hypothesis,
    HypothesisSource,
    Project,
    Trial,
    TrialStatus,
    Verdict,
    VerdictOutcome,
    Workload,
)
from autonomous_ai_agents.orchestrator.factory import build_context
from autonomous_ai_agents.orchestrator.main import (
    EngineRunResult,
    Orchestrator,
    build_checkpointer,
    create_graph,
    run_config,
)
from autonomous_ai_agents.orchestrator.nodes import NodeContext
from autonomous_ai_agents.orchestrator.state import EngineState, initial_state

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

Json = dict[str, object]
SCRIPTED = json.loads((FIXTURES / "step3" / "scripted.json").read_text("utf-8"))
EDITS = cast(dict[str, str], SCRIPTED["edits"])
FIXES = cast(dict[str, tuple[str, str]], SCRIPTED["fixes"])
CORE = "dedupe/core.py"
TESTS = ("python", "-m", "unittest", "discover", "-s", "tests", "-t", ".")
SECRET = b"CANARY_e3d_5f1c9a2b7d"
"""The planted file: identifier-safe, so the canary attack can name it."""
DECIMALS = " ".join(str(byte) for byte in SECRET)
ALPHA_NAME = f"a{SECRET[0]:02x}"  # the alphabet name the first byte selects
ALPHABET = "(" + ", ".join(f'"a{byte:02x}"' for byte in range(256)) + ")"
TYPO_FEEDBACK = (  # retry.TrialFeedback.render() of the typo's crash
    "NameError: name 'seen_items' is not defined\n"
    '  File "dedupe/main.py", line 72, in <module>\n'
    '  File "dedupe/main.py", line 67, in main\n'
    '  File "dedupe/core.py", line 11, in unique_in_order'
)
_RUN_OUTPUT = re.compile(
    r"\n\n<engine_notice nonce=(\w+)>\n[^<]*\n</engine_notice>\n\n"
    r"<untrusted_run_output boundary=\1>\n(.*)\n</untrusted_run_output boundary=\1>",
    re.DOTALL,
)


# ---------------------------------------------------------------------------
# Scripted replies and recorded requests
# ---------------------------------------------------------------------------


def _reply(role: Role, n: int, content: list[Json], stop: str) -> Json:
    usage = {"input_tokens": 900, "output_tokens": 200}
    model = settings.GENERATOR_MODEL if role == "generator" else settings.ENGINE_MODEL
    return {
        "id": f"msg_01E3{role}{n:04d}", "type": "message", "role": "assistant",
        "model": model, "content": content, "stop_reason": stop,
        "stop_sequence": None, "usage": usage,
    }  # fmt: skip


def _generated(*names: str) -> list[Json]:
    """One generator reply per name in ``SCRIPTED["generated"]``."""
    found = cast(dict[str, object], SCRIPTED["generated"])
    return [
        _reply("generator", i, [{"type": "text", "text": json.dumps(found[name])}],
               "end_turn")
        for i, name in enumerate(names)
    ]  # fmt: skip


def _edit(old: str, new: str, n: int) -> list[Json]:
    """A str_replace on dedupe/core.py, then the closing answer."""
    use: Json = {
        "type": "tool_use", "id": f"toolu_01E3Edit{n:016d}",
        "name": "str_replace_based_edit_tool",
        "input": {"command": "str_replace", "path": f"/repo/{CORE}",
                  "old_str": old, "new_str": new},
    }  # fmt: skip
    done: Json = {"type": "text", "text": "Done."}
    return [_reply("editor", 2 * n, [use], "tool_use"),
            _reply("editor", 2 * n + 1, [done], "end_turn")]  # fmt: skip


def _first(body: str, n: int, planted: Path | None = None) -> list[Json]:
    new = (
        EDITS[body].replace("PLANTED", repr(str(planted))).replace("ALPHABET", ALPHABET)
    )
    return _edit(EDITS["slow"], new, n)


def _on(role: Role, replies: Sequence[Json]) -> ScriptedTransport:
    return ScriptedTransport(replies, cfg=role_settings(settings, role))


def _body(request: LLMRequest) -> str:
    """The whole request: system, every message, tools and output config."""
    return json.dumps(dataclasses.asdict(request), default=str)


def _opening(request: LLMRequest) -> str:
    content = request.messages[0]["content"]
    if isinstance(content, str):
        return content
    return "".join(str(cast(Mapping[str, object], b).get("text", "")) for b in content)


def _retries(editor: ScriptedTransport) -> list[LLMRequest]:
    """Every request that opens a fix retry (one message, a run output block)."""
    return [r for r in editor.requests
            if len(r.messages) == 1 and "<untrusted_run_output" in _opening(r)]  # fmt: skip


def _no_factory(cfg: Settings) -> LLMTransport:
    raise AssertionError("an E2E scenario reached the real transport factory")


# ---------------------------------------------------------------------------
# Scenario plumbing and the shared checks
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Scene:
    repo: UserRepo
    before: RepoSnapshot  # taken before the context is built
    project: Project
    workload: Workload
    ctx: NodeContext
    roles: Mapping[Role, ScriptedTransport]  # every transport the context holds
    editor: ScriptedTransport
    generator: ScriptedTransport | None


def _scene(
    repo: UserRepo,
    isolation: Isolation,
    launches: LaunchLog,
    edits: Sequence[Json],
    *,
    generated: Sequence[Json] | None = None,
    candidates: Sequence[tuple[str, ChangeClass]] = (),
) -> Scene:
    before = repo.snapshot()
    project = Project(name="dedupe", root_path=str(repo.path), test_command=TESTS)
    workload = Workload(project_id=project.id, name="dedupe",
                        command=("python", "-m", "dedupe.main"))  # fmt: skip
    editor = _on("editor", edits)
    roles: dict[Role, ScriptedTransport] = {"editor": editor}
    generator = None if generated is None else _on("generator", generated)
    if generator is not None:
        roles["generator"] = generator
    ideas = [
        Hypothesis(project_id=project.id, source=HypothesisSource.playbook,
                   title=title, rationale=f"{title}: a scripted dedupe rewrite",
                   change_class=kind, expected_gain=0.8, provability=0.9, risk=0.1)
        for title, kind in candidates
    ]  # fmt: skip
    ctx = build_context(
        project, candidates=ideas, role_transports=dict(roles),
        transport_factory=_no_factory, network=isolation.mode, fs=isolation.mode,
        run=launches, sleep=lambda _: None,
    )  # fmt: skip
    return Scene(repo, before, project, workload, ctx, roles, editor, generator)


def _guardrails(project: Project) -> list[Guardrail]:
    """The suite only: the default output check adds output_equivalence (D35)."""
    return [Guardrail(project_id=project.id, kind=GuardrailKind.tests_pass,
                      description="the unittest suite passes")]  # fmt: skip


def _run(scene: Scene, run_id: str) -> EngineRunResult:
    return Orchestrator(context=scene.ctx).run(
        scene.project, [scene.workload], [], _guardrails(scene.project), run_id=run_id
    )


def _by_title(state: EngineState) -> tuple[dict[str, Trial], dict[str, Verdict]]:
    titles = {h.id: h.title for h in [*state["hypotheses"], *state["parked"]]}
    return (
        {titles[t.hypothesis_id]: t for t in state["trials"]},
        {titles[v.hypothesis_id]: v for v in state["verdicts"]},
    )


def _check_clean(
    scene: Scene, state: EngineState, isolation: Isolation, launches: LaunchLog
) -> None:
    """As Step 2's ``_check_repo_untouched``: the user's HEAD, index, status,
    config, hooks and info are unchanged; the refs created are exactly the
    committed trials' refs, run-<id> at a branch delivery's tip and
    review-<id> at a review delivery's; no pre-existing ref moved; no
    worktree or run directory is left. Every launch ran with the scenario's
    modes (isolated where the host can sandbox), and the defaults ran:
    paired trials and the calibrated floor."""
    repo, run, before = scene.repo, state["run_id"], scene.before
    after = repo.snapshot()
    assert dataclasses.replace(after, refs={}) == dataclasses.replace(before, refs={})
    expected: dict[str, str | None] = {
        f"refs/heads/engine/trial-{run}-{t.hypothesis_id}": t.commit
        for t in state["trials"]
        if t.commit is not None
    }
    delivery, review = state["delivery"], state["review_delivery"]
    if delivery is not None and delivery.kind is DeliveryKind.branch:
        expected[f"refs/heads/engine/run-{run}"] = delivery.commit
    if review is not None:
        expected[f"refs/heads/engine/review-{run}"] = review.commit
    created = {ref: sha for ref, sha in after.refs.items() if ref not in before.refs}
    assert created == expected
    assert {ref: after.refs.get(ref) for ref in before.refs} == before.refs
    assert repo.worktrees() == [f"worktree {repo.path}"]
    assert not (settings.WORKTREE_ROOT / run).exists()
    for launch in launches.launches:
        assert (launch.network, launch.fs) == (isolation.mode, isolation.mode)
        if isolation.missing is None:
            assert launch.net_isolated and launch.fs_isolated, launch
    baseline = state["baseline"]
    assert baseline is not None
    blocks = settings.NOISE_CALIBRATION_BLOCKS
    calibration = baseline.calibration
    assert (calibration.blocks if calibration else 0) == blocks
    for trial in state["trials"]:
        assert bool(trial.base_measurements) == (trial.status is TrialStatus.measured)


def _core(body: str) -> str:
    """The fixture's dedupe/core.py with ``EDITS[body]`` as the loop."""
    base = (FIXTURES / "dedupe_repo" / CORE).read_text()
    return base.replace(EDITS["slow"], EDITS[body])


def _core_at(scene: Scene, commit: str) -> str:
    return git(scene.repo.path, "show", f"{commit}:{CORE}") + "\n"


def _check_delivered(scene: Scene, state: EngineState, body: str) -> Trial:
    """The run branch is the base plus one trial whose core.py is ``body``."""
    delivery, combination = state["delivery"], state["combination"]
    # A rare CI miss (181f1ef, 3.11) shipped report_only and did not reproduce
    # locally: the combine summary says why the re-test did not hold.
    why = None if combination is None else combination.summary
    assert delivery is not None and delivery.kind is DeliveryKind.branch, why
    assert delivery.branch == f"engine/run-{state['run_id']}"
    tip, base = str(delivery.commit), scene.repo.base
    assert scene.repo.refs()[f"refs/heads/engine/run-{state['run_id']}"] == tip
    assert state["review_delivery"] is None
    assert git(scene.repo.path, "rev-parse", f"{tip}^") == base
    assert git(scene.repo.path, "diff", "--name-only", base, tip) == CORE
    assert _core_at(scene, tip) == _core(body)
    (trial,) = [t for t in state["trials"] if t.commit is not None]
    assert git(scene.repo.path, "rev-parse", f"{trial.commit}^") == base
    return trial


# ---------------------------------------------------------------------------
# E3-A and E3-E: discovery wired into the loop
# ---------------------------------------------------------------------------


def test_e3_a_a_generated_idea_is_delivered_across_a_resume(
    dedupe_repo: RepoFactory, isolation: Isolation, launches: LaunchLog
) -> None:
    """
    GIVEN candidates=() and a generator scripted to propose the set fix
          (efficiency); Step 3 defaults
    WHEN the run stops at interrupt_before=["trials"] and a fresh graph over
         the same checkpointer resumes it
    THEN exactly one generator request was sent (before the stop, none
         after), the trial is paired, the keep confirmed twice, and the run
         branch is the base plus the set fix
    """
    scene = _scene(dedupe_repo(), isolation, launches, _first("fast", 0),
                   generated=_generated("set"))  # fmt: skip
    assert scene.generator is not None and scene.ctx.candidates == ()
    saver, run = build_checkpointer(), "e3-a"
    start = initial_state(scene.project, [scene.workload], [],
                          _guardrails(scene.project), run_id=run)  # fmt: skip
    cfg = run_config(run, start["max_rounds"])
    first = create_graph(saver, context=scene.ctx)
    first.invoke(start, cfg, interrupt_before=["trials"], version="v2")
    assert first.get_state(cfg).next == ("trials",)
    assert (len(scene.generator.requests), scene.editor.requests) == (1, [])

    state = create_graph(saver, context=scene.ctx).invoke(None, cfg, version="v2").value

    assert state["error"] is None and state["generator_calls"] == 1
    assert len(scene.generator.requests) == 1 and scene.editor.remaining == 0
    (idea,) = state["hypotheses"]
    assert (idea.title, idea.source) == ("Track seen values in a set",
                                         HypothesisSource.novel)  # fmt: skip
    (verdict,) = state["verdicts"]
    assert verdict.outcome is VerdictOutcome.keep and verdict.confirmations == 2
    _check_delivered(scene, state, "fast")
    _check_clean(scene, state, isolation, launches)


def test_e3_e_a_novel_caller_idea_pauses_and_the_generator_stays_idle(
    dedupe_repo: RepoFactory, isolation: Isolation, launches: LaunchLog
) -> None:
    """
    GIVEN a caller `novel` candidate (the set fix) beside a generator with
          no reply scripted; Step 3 defaults
    WHEN the run pauses at the approval gate and is resumed with approval
    THEN it delivers the run branch, and no generator request was ever sent
    """
    scene = _scene(dedupe_repo(), isolation, launches, _first("fast", 0),
                   generated=[], candidates=[("set", ChangeClass.novel)])  # fmt: skip
    orchestrator = Orchestrator(context=scene.ctx)
    paused = orchestrator.run(scene.project, [scene.workload], [],
                              _guardrails(scene.project), run_id="e3-e")  # fmt: skip
    assert paused.status == "needs_approval", paused.state["error"]
    assert paused.approval_request is not None
    (item,) = paused.approval_request.items
    decision = ApprovalDecision(approved_verdict_ids=(item.verdict_id,), approver="u14")

    result = orchestrator.resume("e3-e", decision)

    assert result.status == "done", result.state["error"]
    assert scene.generator is not None and scene.generator.requests == []
    assert result.state["generator_calls"] == 0
    _check_delivered(scene, result.state, "fast")
    _check_clean(scene, result.state, isolation, launches)


# ---------------------------------------------------------------------------
# E3-B: the fix retry
# ---------------------------------------------------------------------------


def test_e3_b_a_name_error_is_fixed_by_the_retry(
    dedupe_repo: RepoFactory, isolation: Isolation, launches: LaunchLog
) -> None:
    """
    GIVEN a caller efficiency idea whose first edit reads an undefined
          name, then a one-line fix; Step 3 defaults (one retry a run)
    WHEN the run goes through the factory's context
    THEN the trial has attempts=2 and one commit on the base, it is kept and
         delivered, and the retry request is the first request plus only the
         retry notice and the fenced feedback render()
    """
    edits = [*_first("typo", 0), *_edit(*FIXES["typo_fix"], 1)]
    scene = _scene(dedupe_repo(), isolation, launches, edits,
                   candidates=[("set", ChangeClass.efficiency)])  # fmt: skip

    result = _run(scene, "e3-b")

    assert result.status == "done", result.state["error"]
    trials, verdicts = _by_title(result.state)
    assert trials["set"].attempts == 2
    assert trials["set"].retry_notes == ("NameError; retried",)
    assert verdicts["set"].outcome is VerdictOutcome.keep
    assert _check_delivered(scene, result.state, "fast") == trials["set"]
    (retry,) = _retries(scene.editor)
    first = scene.editor.requests[0]
    assert (retry.system, retry.tools, retry.output_config) == (
        first.system, first.tools, first.output_config,
    )  # fmt: skip
    opening, retried = _opening(first), _opening(retry)
    found = _RUN_OUTPUT.search(retried)
    assert found is not None and found.group(2) == TYPO_FEEDBACK
    old, new = re.search(r"nonce=(\w+)", opening), found.group(1)
    assert old is not None and old.group(1) != new
    without = retried[: found.start()] + retried[found.end() :]
    assert without.replace(new, "TOKEN") == opening.replace(old.group(1), "TOKEN")
    assert scene.editor.remaining == 0
    _check_clean(scene, result.state, isolation, launches)


def test_e3_b_with_no_run_retry_the_first_failure_is_kept(
    dedupe_repo: RepoFactory,
    isolation: Isolation,
    launches: LaunchLog,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    GIVEN EDITOR_FIX_RETRIES_PER_RUN=0 and the same typo; calibration off
          (NOISE_CALIBRATION_BLOCKS=0: no trial is measured, so no floor is read)
    WHEN the run goes through the factory's context
    THEN the first failure is kept and rejected with the "spent" note, no
         request carries run output, and the run delivers the report only
    """
    monkeypatch.setattr(settings, "EDITOR_FIX_RETRIES_PER_RUN", 0)
    monkeypatch.setattr(settings, "NOISE_CALIBRATION_BLOCKS", 0)
    scene = _scene(dedupe_repo(), isolation, launches, _first("typo", 0),
                   candidates=[("set", ChangeClass.efficiency)])  # fmt: skip

    result = _run(scene, "e3-b0")

    assert result.status == "done", result.state["error"]
    trials, verdicts = _by_title(result.state)
    assert (trials["set"].attempts, trials["set"].status) == (1, TrialStatus.failed)
    assert trials["set"].retry_notes == (
        "NameError; not retried: the run's fix retry is spent",
    )
    assert verdicts["set"].outcome is VerdictOutcome.reject
    assert _retries(scene.editor) == [] and scene.editor.remaining == 0
    delivery = result.state["delivery"]
    assert delivery is not None and delivery.kind is DeliveryKind.report_only
    _check_clean(scene, result.state, isolation, launches)


# ---------------------------------------------------------------------------
# E3-C: the default output check
# ---------------------------------------------------------------------------


def test_e3_c_the_default_output_check_routes_each_generated_class(
    dedupe_repo: RepoFactory, isolation: Isolation, launches: LaunchLog
) -> None:
    """
    GIVEN a generator proposing a behaviour idea with identical outputs (the
          set fix), a behaviour idea that alters them (sorted) and a novel
          one, then nothing; the suite as the only guardrail; Step 3 defaults
    WHEN the run goes through the factory's context
    THEN the identical-output change lands on engine/review-<id> with no
         pause and no run branch, the altering one is rejected by the
         equivalence judge, and the novel one is parked, never trialled
    """
    edits = [*_first("fast", 0), *_first("sorted", 1)]
    scene = _scene(dedupe_repo(), isolation, launches, edits,
                   generated=_generated("classes", "empty"))  # fmt: skip

    result = _run(scene, "e3-c")

    assert result.status == "done", result.state["error"]
    state = result.state
    assert any(g.kind is GuardrailKind.output_equivalence for g in state["guardrails"])
    trials, verdicts = _by_title(state)
    assert set(trials) == {"Track seen values in a set",
                           "Return the sorted distinct values"}  # fmt: skip
    review, altered = (verdicts["Track seen values in a set"],
                       verdicts["Return the sorted distinct values"])  # fmt: skip
    assert review.outcome is VerdictOutcome.review and review.confirmations == 2
    assert altered.outcome is VerdictOutcome.reject
    (failed,) = [r.judge for r in altered.judge_results if r.outcome.value == "failed"]
    assert failed == "equivalence"
    (parked,) = state["parked"]
    assert parked.change_class is ChangeClass.novel
    assert state["pending_approval_ids"] == [] and state["approval"] is None
    assert scene.generator is not None and len(scene.generator.requests) == 2
    delivery, shipped = state["delivery"], state["review_delivery"]
    assert delivery is not None and delivery.kind is DeliveryKind.report_only
    assert shipped is not None and shipped.branch == "engine/review-e3-c"
    assert "refs/heads/engine/run-e3-c" not in scene.repo.refs()
    assert shipped.verdict_ids == (review.id,)
    combination = state["review_combination"]
    assert combination is not None and combination.holds
    assert combination.tip_commit == shipped.commit
    tip = scene.repo.refs()["refs/heads/engine/review-e3-c"]
    assert tip == shipped.commit and _core_at(scene, tip) == _core("fast")
    _check_clean(scene, state, isolation, launches)


# ---------------------------------------------------------------------------
# E3-D: no run output beyond the closure reaches the wire
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("attack", ["canary", "decimal", "alphabet"])
def test_e3_d_a_planted_secret_never_reaches_a_request(
    dedupe_repo: RepoFactory,
    isolation: Isolation,
    launches: LaunchLog,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    attack: str,
) -> None:
    """
    GIVEN a file planted outside the repository and an edit that reads it
          and crashes with it: as a name (canary), as decimal byte values
          (decimal), or as the alphabet name a diff-defined a00-aff selects
          (alphabet); the retry crashes again; calibration off (no trial is
          measured)
    WHEN the run goes through the factory's context
    THEN the crash carried the secret (the trial's error shows it), the retry
         was sent with type and frames only, and no recorded request body
         holds the canary, its decimals or the selected name's message
    """
    monkeypatch.setattr(settings, "NOISE_CALIBRATION_BLOCKS", 0)
    planted = tmp_path / "planted" / "secret.bin"
    planted.parent.mkdir()
    planted.write_bytes(SECRET)
    edits = [*_first(attack, 0, planted), *_edit(*FIXES["crash_again"], 1)]
    scene = _scene(dedupe_repo(), isolation, launches, edits,
                   candidates=[("set", ChangeClass.efficiency)])  # fmt: skip

    result = _run(scene, f"e3-d-{attack}")

    assert result.status == "done", result.state["error"]
    (trial,) = result.state["trials"]
    raised = {"canary": f"v_{SECRET.decode()}", "decimal": DECIMALS,
              "alphabet": f"name '{ALPHA_NAME}' is not defined"}[attack]  # fmt: skip
    assert trial.status is TrialStatus.failed and trial.attempts == 2
    assert raised in str(trial.error)
    (note,) = trial.retry_notes
    assert "message withheld" in note and note.endswith("first failure kept")
    (retry,) = _retries(scene.editor)
    found = _RUN_OUTPUT.search(_opening(retry))
    assert found is not None
    head, *frames = found.group(2).split("\n")
    assert head == {"decimal": "TypeError"}.get(attack, "NameError")
    assert frames and all(f.startswith('  File "dedupe/') for f in frames)
    secrets = (SECRET.decode(), DECIMALS, " ".join(DECIMALS.split()[:3]), raised)
    assert scene.generator is None and set(scene.roles) == {"editor"}
    for transport in scene.roles.values():  # every transport the context holds
        for request in transport.requests:
            body = _body(request)
            assert not [s for s in secrets if s in body], request
    assert scene.editor.remaining == 0
    _check_clean(scene, result.state, isolation, launches)
