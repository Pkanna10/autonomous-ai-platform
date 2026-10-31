"""The offline discovery eval (Step 3, U12, D20): recorded replies, replayed.

``tests/fixtures/discovery_eval/seed.json`` holds, per (repository, arm), the
generator's recorded reply, the hypotheses the sweep kept from it, a label
per hypothesis (the grader's verdict) and the grader's recorded reply. Wave 1
ships a synthetic seed; L4's ``sweep-record`` run replaces it (V6) through
``discovery_sweep.eval_case``. No network, no key: every model call is a
``ScriptedTransport`` replaying a recorded reply, through the generator role's
real adapter (``ClaudeHypothesisGenerator``), ``rank_generated`` and the
hypotheses node's slice (``NodeContext.max_hypotheses_per_round``).
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Sequence

import pytest
from live import discovery_grader as grader
from live import discovery_sweep as sweep
from live.corpus import CORPUS, HARD_CORPUS, CorpusRepo
from live.discovery import ArmResult, RepoFacts
from live.discovery_io import json_line
from pydantic import ValidationError

from autonomous_ai_agents.clients.budget import Budget
from autonomous_ai_agents.clients.transport import ScriptedTransport
from autonomous_ai_agents.common.config import role_chain, role_settings, settings
from autonomous_ai_agents.common.models import Hypothesis
from autonomous_ai_agents.orchestrator.nodes import NodeContext

SEED = sweep.load_seed()
GEN_CFG = role_settings(settings, "generator")
GRADER_CFG = grader.grader_settings(settings)
REPOS = {r.name: r for r in (*CORPUS, *HARD_CORPUS)}
SLOWDOWNS = tuple(c for c in SEED.cases if c.kind == "slowdown")


def _replayed(case: sweep.EvalCase) -> tuple[RepoFacts, tuple[Hypothesis, ...]]:
    facts = sweep.eval_facts(case, GEN_CFG)
    return facts, sweep.replay_generation(case, facts, config=GEN_CFG)


def _regrade(
    case: sweep.EvalCase, hypotheses: Sequence[Hypothesis]
) -> grader.Grade | None:
    """The recorded grader reply replayed (None: the grader never answered)."""
    if case.grader_reply is None:
        return None
    model = role_chain(GRADER_CFG, "engine")[0]
    transport = ScriptedTransport(
        [sweep.scripted_reply(case.grader_reply, model)], cfg=GRADER_CFG
    )
    patches = grader.reference_patches(REPOS[case.repo])
    return grader.grade_with(
        transport,
        Budget(sweep.REPLAY_CAP_USD),
        case.repo,
        patches,
        hypotheses,
        config=GRADER_CFG,
        sleep=lambda _s: None,
    )


def test_the_seed_is_the_generator_roles_arm_sliced_as_the_node_slices() -> None:
    default = {f.name: f.default for f in dataclasses.fields(NodeContext)}
    assert SEED.k == default["max_hypotheses_per_round"] == 3
    (arm,) = [a for a in sweep.ARMS if a.label == SEED.arm]
    assert (arm.model, arm.effort) == (GEN_CFG.GENERATOR_MODEL, "medium")
    assert arm.effort == GEN_CFG.GENERATOR_EFFORT
    assert {c.kind for c in SEED.cases} == {"slowdown", "control"}
    assert all(c.repo in REPOS and REPOS[c.repo].kind == c.kind for c in SEED.cases)
    assert len(SLOWDOWNS) >= 3


def test_each_recorded_reply_replays_to_the_same_hypotheses() -> None:
    for case in SEED.cases:
        facts, replayed = _replayed(case)
        assert sweep.ideas_of(replayed, facts.hotspots) == case.hypotheses, case.repo
    # the generator really parses the reply: one duplicate title is dropped
    raw = {c.repo: len(json.loads(c.reply)["hypotheses"]) for c in SEED.cases}
    assert any(raw[c.repo] > len(c.hypotheses) for c in SEED.cases)


def test_hit_at_k_after_ranking_and_the_slice_holds_the_recorded_value() -> None:
    # the baseline is what the recorded hypotheses' labels give at k, in the
    # model's order: it cannot be lowered without changing the labels
    assert sweep.recorded_hits(SEED) == SEED.baseline_hits >= 1
    assert sweep.eval_hits(SEED, config=GEN_CFG) >= SEED.baseline_hits  # D20's gate
    # exact: rank_generated with no lessons keeps the model's order, so the
    # replay gives what the labels give at every k (a reordering, a wider or
    # narrower slice fails here whatever the seed holds)
    assert sweep.eval_hits(SEED, config=GEN_CFG) == sweep.recorded_hits(SEED)
    for k in (1, SEED.k, sweep.SWEEP_N):
        found = sweep.eval_hits(SEED, config=GEN_CFG, k=k)
        assert found == sweep.recorded_hits(SEED, k=k), k


def test_an_unknown_label_key_fails_with_refresh_in_live_smoke() -> None:
    case = SLOWDOWNS[0]
    _facts, replayed = _replayed(case)
    first = sweep.label_key(replayed[0].title)
    missing = case.model_copy(
        update={"labels": {k: v for k, v in case.labels.items() if k != first}}
    )
    with pytest.raises(ValueError, match="refresh in live-smoke") as caught:
        sweep.hit_at(missing, replayed, SEED.k)
    assert first in str(caught.value)
    stray = case.model_copy(
        update={"labels": {**case.labels, "an idea no reply holds": case.labels[first]}}
    )
    with pytest.raises(ValueError, match="refresh in live-smoke"):
        sweep.hit_at(stray, replayed, SEED.k)
    # a stale seed fails the whole eval the same way
    seed = SEED.model_copy(update={"cases": (missing, *SEED.cases[1:])})
    with pytest.raises(ValueError, match="refresh in live-smoke"):
        sweep.eval_hits(seed, config=GEN_CFG)


def test_grader_replies_replay_through_grade_with_to_the_labels() -> None:
    replayed_grades = 0
    for case in SLOWDOWNS:
        _facts, replayed = _replayed(case)
        graded = _regrade(case, replayed)
        if graded is None:  # the grader errored when recorded: nothing to replay
            continue
        replayed_grades += 1
        labels = [case.labels[sweep.label_key(h.title)] for h in replayed]
        assert graded.error is None and graded.answered, case.repo
        assert graded.hits == tuple(x.hit for x in labels), case.repo
        assert graded.causes == tuple(x.part for x in labels), case.repo
        assert graded.reply == case.grader_reply
        assert graded.parts == len(grader.reference_patches(REPOS[case.repo]))
    assert replayed_grades >= 1
    assert _regrade(SLOWDOWNS[0].model_copy(update={"grader_reply": None}), ()) is None
    # an unusable recorded grader reply is an error, never a grade
    broken = SLOWDOWNS[0].model_copy(update={"grader_reply": "{"})
    graded = _regrade(broken, _replayed(broken)[1])
    assert graded is not None and graded.error is not None
    assert graded.answered and graded.hit_at(1) is None
    nothing = grader.grade_with(
        ScriptedTransport([], cfg=GRADER_CFG),
        Budget(1.0),
        "tagfilter",
        (),
        (),
        config=GRADER_CFG,
    )
    assert (nothing.sent, nothing.hits, nothing.reply) == (False, (), None)


def test_grade_with_reports_what_its_transport_was_billed() -> None:
    """An answer priced past the budget raises after it is recorded: the
    grade says it was answered and what was spent, never 0."""
    case = SLOWDOWNS[0]
    _facts, replayed = _replayed(case)
    assert case.grader_reply is not None
    model = role_chain(GRADER_CFG, "engine")[0]
    dear = {
        **sweep.scripted_reply(case.grader_reply, model),
        "usage": {"input_tokens": 1000, "output_tokens": 10_000_000},
    }
    budget = Budget(sweep.REPLAY_CAP_USD)
    graded = grader.grade_with(
        ScriptedTransport([dear], cfg=GRADER_CFG),
        budget,
        case.repo,
        grader.reference_patches(REPOS[case.repo]),
        replayed,
        config=GRADER_CFG,
        sleep=lambda _s: None,
    )
    assert graded.error is not None and "BudgetExceeded" in graded.error
    assert graded.answered and graded.models == ()
    assert graded.cost_usd == budget.spent_usd > sweep.REPLAY_CAP_USD


def _trace_line(case: sweep.EvalCase, repo: CorpusRepo) -> dict[str, object]:
    facts, replayed = _replayed(case)
    (arm,) = [a for a in sweep.ARMS if a.label == SEED.arm]
    result = ArmResult(arm, replayed, 0.0, (), (), 0.0, None)
    made = sweep.Generated(result, (case.reply,))
    patches = grader.reference_patches(repo)
    graded = None if case.grader_reply is None else _regrade(case, replayed)
    trace = sweep.sweep_trace(repo, made, graded, patches, facts.hotspots)
    row = sweep.sweep_row(repo, result, graded, 0.0)
    line: dict[str, object] = json.loads(json_line({**row.record(), **trace.record()}))
    return line


def test_a_recorded_sweep_line_becomes_the_case_it_was_recorded_from() -> None:
    for case in SEED.cases:
        line = _trace_line(case, REPOS[case.repo])
        assert sweep.eval_case(line) == case, case.repo
    # a cut reply cannot be replayed: the line is refused
    line = _trace_line(SLOWDOWNS[0], REPOS[SLOWDOWNS[0].repo])
    cut: tuple[dict[str, object], ...] = (
        {"reply_truncated": True},
        {"grader_reply_chars": 1},
    )
    for flag in cut:
        with pytest.raises(ValueError, match="cut.*refresh in live-smoke"):
            sweep.eval_case({**line, **flag})
    # an arm that never answered usably cannot replay either
    unanswered: tuple[dict[str, object], ...] = (
        {"replies": 0},
        {"error": "UnusableReplyError: not json"},
        {"reply_chunks": []},
    )
    for flag in unanswered:
        with pytest.raises(ValueError, match="no usable reply.*refresh in live-smoke"):
            sweep.eval_case({**line, **flag})


def test_a_bad_hand_committed_seed_fails_at_load() -> None:
    data = SEED.model_dump(mode="json")
    sweep.EvalSeed.model_validate(data)  # the committed seed loads
    slow = next(i for i, c in enumerate(data["cases"]) if c["kind"] == "slowdown")
    control = next(i for i, c in enumerate(data["cases"]) if c["kind"] == "control")
    first = sweep.label_key(data["cases"][slow]["hypotheses"][0]["title"])
    label = data["cases"][slow]["labels"][first]
    bad_cases = (
        (
            slow,
            {
                "labels": {
                    k: v for k, v in data["cases"][slow]["labels"].items() if k != first
                }
            },
        ),
        (slow, {"labels": {**data["cases"][slow]["labels"], "stray idea": label}}),
        (control, {"labels": {first: label}}),
        (control, {"grader_reply": '{"grades": []}'}),
    )
    for index, change in bad_cases:
        cases = list(data["cases"])
        cases[index] = {**cases[index], **change}
        with pytest.raises(ValidationError, match="refresh in live-smoke"):
            sweep.EvalSeed.model_validate({**data, "cases": cases})
    for baseline in (SEED.baseline_hits - 1, SEED.baseline_hits + 1):
        with pytest.raises(ValidationError, match="refresh in live-smoke"):
            sweep.EvalSeed.model_validate({**data, "baseline_hits": baseline})
