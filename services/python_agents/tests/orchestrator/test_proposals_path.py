"""G3: the proposals path (idea-lab spec 1, O32).

A tagged idea (``idea_types.is_proposal``) runs only here: it is parked as a
proposal, reported for a human in its own section and never trialled,
combined, delivered, learnt from or counted. Fed through the normal path
anyway (a caller candidate, a pooled idea, a forged ``proposed`` hypothesis,
a trial in the round) it is parked, skipped or rejected; a checkpoint
round-trip keeps its tags.

Swap points: ``_Generator`` stands for the idea pipeline (it returns built
hypotheses with the pipeline's tags); the trial runner is the conftest's
``StubTrialRunner`` (scripted by title) and the repository its
``InMemoryRepository``; the graph is the real one on ``build_checkpointer``.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, cast

import pytest

from autonomous_ai_agents.clients.budget import Budget
from autonomous_ai_agents.common.models import (
    EngineEvent,
    Guardrail,
    Hypothesis,
    HypothesisStatus,
    Objective,
    Project,
    Trial,
    Verdict,
    VerdictOutcome,
    Workload,
)
from autonomous_ai_agents.optimization.idea_types import is_proposal
from autonomous_ai_agents.optimization.sources import GenerateResult
from autonomous_ai_agents.orchestrator.main import EngineGraph, run_config
from autonomous_ai_agents.orchestrator.nodes import (
    NodeContext,
    NodeDelta,
    make_nodes,
    make_router,
)
from autonomous_ai_agents.orchestrator.serde import dump_state, load_state
from autonomous_ai_agents.orchestrator.state import EngineState, initial_state

ContextFactory = Callable[..., NodeContext]
GraphFactory = Callable[..., EngineGraph]
DEPENDENCY_TAGS = ("lane:relax_dependency", "proposal:new_dependency")
SECTION = "**Proposals for a human (rule-relaxing; never trialled or delivered)**"


class _Generator:
    def __init__(self, hypotheses: Sequence[Hypothesis]) -> None:
        self.hypotheses = tuple(hypotheses)
        self.calls = 0

    def generate(self, **kwargs: Any) -> GenerateResult:
        self.calls += 1
        cast(Budget, kwargs["budget"]).record(0.01, 10)
        return GenerateResult(hypotheses=self.hypotheses if self.calls == 1 else ())


def _proposal(base: Hypothesis, title: str, *tags: str) -> Hypothesis:
    return base.model_copy(
        update={"id": f"prop-{len(title)}", "title": title,
                "tags": tags or DEPENDENCY_TAGS}
    )  # fmt: skip


def _apply(state: EngineState, delta: NodeDelta) -> EngineState:
    merged: dict[str, Any] = dict(state)
    for key, value in delta.items():
        reducer = key in ("events", "trials", "verdicts", "lessons")
        merged[key] = [*merged[key], *cast(list[Any], value)] if reducer else value
    return cast(EngineState, merged)


def _codes(state: EngineState) -> list[object]:
    return [e.data.get("code") for e in state["events"]]


@pytest.fixture
def state(
    sample_project: Project,
    sample_workload: Workload,
    sample_objective: Objective,
    sample_guardrails: tuple[Guardrail, ...],
) -> EngineState:
    return initial_state(
        sample_project, [sample_workload], [sample_objective], sample_guardrails,
        run_id="run-g3", max_rounds=3, max_cost_usd=10.0,
    )  # fmt: skip


def _run(ctx: NodeContext, state: EngineState, *names: str) -> EngineState:
    nodes = make_nodes(ctx)
    for name in names:
        state = _apply(state, nodes[name](state))
    return state


_TO_HYPOTHESES = ("connect", "understand", "define", "baseline", "profile",
                  "research", "hypotheses")  # fmt: skip


def test_a_generated_proposal_is_parked_for_a_human_never_pooled(
    make_context: ContextFactory, state: EngineState, h1_cache: Hypothesis
) -> None:
    """
    GIVEN a generator returning a tagged idea, the H1 idea and a second one
          of another relaxing lane with its ``proposal:`` tag lost
    WHEN the hypotheses node runs
    THEN both tagged ideas are parked as proposals (reason names the rule),
         neither is ranked into the round or pooled, H1 is ranked
    """
    tagged = _proposal(h1_cache, "Use a compiled tokenizer package")
    orphan = _proposal(h1_cache, "Emit tokens unordered", "lane:relax_output_order")
    generator = _Generator([tagged, h1_cache, orphan])
    ctx = make_context(generator=generator, generator_n=6)

    after = _run(ctx, state, *_TO_HYPOTHESES)

    assert [h.id for h in after["hypotheses"]] == [h1_cache.id]
    assert after["candidate_pool"] == []
    assert [h.id for h in after["parked"]] == [tagged.id, orphan.id]
    reasons = [h.parked_reason for h in after["parked"]]
    assert reasons == [
        "proposal (G3): relaxes new_dependency; never trialled or delivered",
        "proposal (G3): relaxes output_order; never trialled or delivered",
    ]
    assert all(
        h.tags == p.tags for h, p in zip(after["parked"], (tagged, orphan), strict=True)
    )
    (generated,) = [e for e in after["events"] if e.data.get("code") == "generated"]
    assert generated.data["proposals"] == 2 and generated.data["kept"] == 1


def test_a_tagged_caller_candidate_is_parked_once_and_never_routes(
    make_context: ContextFactory, state: EngineState, h1_cache: Hypothesis
) -> None:
    """
    GIVEN a tagged caller candidate and a tagged pooled idea (the normal path)
    WHEN the hypotheses node runs twice and the router is asked
    THEN each is parked once as a proposal and never ranked; with nothing
         else left the router goes to combine, not back to hypotheses
    """
    tagged = _proposal(h1_cache, "Change the public parse API", "proposal:api_change")
    pooled = _proposal(h1_cache, "Precompute at install", "lane:relax_precompute")
    state["candidate_pool"] = [pooled]
    ctx = make_context([tagged])
    nodes, router = make_nodes(ctx), make_router(ctx)

    first = _run(ctx, state, *_TO_HYPOTHESES)
    second = _apply(first, nodes["hypotheses"](first))

    assert first["hypotheses"] == [] and first["candidate_pool"] == []
    assert sorted(h.id for h in second["parked"]) == sorted([tagged.id, pooled.id])
    assert all(is_proposal(h) for h in second["parked"])
    assert second["hypotheses"] == []
    assert router(second) == "combine"


def test_a_forged_proposed_proposal_is_never_trialled(
    make_context: ContextFactory, state: EngineState, h1_cache: Hypothesis
) -> None:
    """A tagged hypothesis put straight into the round as ``proposed`` (a
    forged state) is skipped by the trials node with a warning; H1 runs."""
    ctx = make_context([h1_cache])
    after = _run(ctx, state, *_TO_HYPOTHESES)
    forged = _proposal(h1_cache, "Use a compiled tokenizer package").model_copy(
        update={"status": HypothesisStatus.proposed}
    )
    after["hypotheses"] = [*after["hypotheses"], forged]

    trialled = _run(ctx, after, "trials")

    assert [t.hypothesis_id for t in trialled["round_trials"]] == [h1_cache.id]
    (skipped,) = [e for e in trialled["events"]
                  if e.data.get("code") == "proposal_quarantined"]  # fmt: skip
    assert skipped.data["skipped"] == 1 and forged.title in skipped.message


def test_a_tagged_trial_whose_equivalence_judge_passes_is_rejected(
    make_context: ContextFactory, state: EngineState, h1_cache: Hypothesis
) -> None:
    """
    GIVEN H1's trial judged (every judge passed, outputs identical), its
          hypothesis then swapped for a tagged copy (the same id)
    WHEN verdicts, combine, deliver and learn run
    THEN the verdict is a reject naming the contradiction; nothing is kept,
         combined or delivered on a branch, and no lesson is learnt
    """
    ctx = make_context([h1_cache], default_output_check=True)
    judged = _run(ctx, state, *_TO_HYPOTHESES, "trials", "judges")
    (trial,) = judged["round_trials"]
    equivalence = next(r for r in trial.judge_results if r.judge == "equivalence")
    assert equivalence.outcome.value == "passed"
    tagged = h1_cache.model_copy(update={"tags": DEPENDENCY_TAGS})
    judged["hypotheses"] = [
        tagged.model_copy(update={"status": h.status}) for h in judged["hypotheses"]
    ]

    final = _run(ctx, judged, "verdicts", "combine", "deliver", "learn")

    (verdict,) = final["verdicts"]
    assert verdict.outcome is VerdictOutcome.reject
    assert "contradictory" in verdict.summary
    assert final["kept_verdict_ids"] == [] and final["lessons"] == []
    delivery = final["delivery"]
    assert delivery is not None and delivery.branch is None


def test_a_forged_keep_of_a_proposal_is_never_combined_or_learnt(
    make_context: ContextFactory, state: EngineState, h1_cache: Hypothesis
) -> None:
    """Defence in depth: a ``keep`` (or ``review``) verdict for a tagged
    hypothesis that reached the state anyway is left out of the run set, the
    review set and the lessons."""
    ctx = make_context([h1_cache])
    judged = _run(ctx, state, *_TO_HYPOTHESES, "trials", "judges", "verdicts")
    (verdict,) = judged["verdicts"]
    assert verdict.outcome is VerdictOutcome.keep
    tagged = h1_cache.model_copy(update={"tags": ("proposal:output_order",)})
    judged["hypotheses"] = [tagged]
    review = verdict.model_copy(update={"id": "v-review", "trial_id": "t-review",
                                        "outcome": VerdictOutcome.review})  # fmt: skip
    judged["verdicts"] = [verdict, review]

    final = _run(ctx, judged, "combine", "deliver", "learn")

    assert final["kept_verdict_ids"] == [] and final["lessons"] == []
    combined = [e for e in final["events"] if e.phase.value == "combine"]
    assert combined[-1].data == {"kept": 0}


def test_a_forged_keep_of_a_proposal_never_ends_exploration(
    make_context: ContextFactory, state: EngineState, h1_cache: Hypothesis
) -> None:
    """
    GIVEN a keep verdict for a tagged hypothesis that reached the state anyway,
        the round at portfolio_rounds, and an untagged idea still in the pool
    WHEN the router decides after the verdicts
    THEN the forged keep does not count as a keep (it could never be
        delivered): exploration goes on to the pooled idea, not to combine
    """
    ctx = make_context([h1_cache])
    judged = _run(ctx, state, *_TO_HYPOTHESES, "trials", "judges", "verdicts")
    (verdict,) = judged["verdicts"]
    assert verdict.outcome is VerdictOutcome.keep
    judged["hypotheses"] = [
        h1_cache.model_copy(update={"tags": ("proposal:output_order",)})
    ]
    judged["candidate_pool"] = [
        h1_cache.model_copy(update={"id": "pool-1", "title": "Cache the parsed header"})
    ]
    judged["round"] = ctx.portfolio_rounds

    assert make_router(ctx)(judged) == "hypotheses"


def test_the_report_lists_proposals_in_their_own_section(
    make_context: ContextFactory, state: EngineState, h1_cache: Hypothesis
) -> None:
    tagged = _proposal(h1_cache, "Use a compiled | tokenizer package")
    generator = _Generator([tagged, h1_cache])
    ctx = make_context(generator=generator, generator_n=6)
    after = _run(ctx, state, *_TO_HYPOTHESES, "trials", "judges", "verdicts",
                 "combine", "deliver")  # fmt: skip
    delivery = after["delivery"]
    assert delivery is not None
    report = delivery.report_markdown
    head, _, section = report.partition(SECTION)
    assert section, report
    assert (
        "\n- Use a compiled \\| tokenizer package (relaxes new_dependency; lane "
        "relax_dependency): Cache frozen-encoder embeddings\\: scripted" in section
    )
    assert "Use a compiled" not in head
    assert "**Parked ideas and suggestions**" not in report


def test_a_checkpoint_round_trip_keeps_a_proposals_tags(
    state: EngineState, h1_cache: Hypothesis
) -> None:
    tagged = _proposal(h1_cache, "Use a compiled tokenizer package")
    state["parked"] = [tagged.model_copy(update={"parked_reason": "proposal"})]
    state["candidate_pool"] = [tagged]

    again = load_state(dump_state(state))

    assert again["parked"][0].tags == DEPENDENCY_TAGS
    assert all(is_proposal(h) for h in (*again["parked"], *again["candidate_pool"]))


def test_the_graph_parks_a_proposal_through_its_checkpoints(
    make_context: ContextFactory,
    engine_graph: GraphFactory,
    state: EngineState,
    h1_cache: Hypothesis,
) -> None:
    """
    GIVEN a generator returning a tagged idea and H1, on the real graph with
          a checkpointer
    WHEN the run completes
    THEN H1 alone is trialled and kept on engine/run-<id>; the proposal is
         parked with its tags in the checkpointed state, has no trial, no
         verdict and no lesson, and the report lists it in its section
    """
    tagged = _proposal(h1_cache, "Use a compiled tokenizer package")
    ctx = make_context(generator=_Generator([tagged, h1_cache]), generator_n=6)
    graph = engine_graph(ctx)
    cfg = run_config("run-g3", 3)

    final = graph.invoke(state, cfg, version="v2").value

    assert [t.hypothesis_id for t in final["trials"]] == [h1_cache.id]
    assert [v.hypothesis_id for v in final["verdicts"]] == [h1_cache.id]
    assert all(lesson.hypothesis_id == h1_cache.id for lesson in final["lessons"])
    delivery = final["delivery"]
    assert delivery is not None and delivery.branch == "engine/run-run-g3"
    assert SECTION in delivery.report_markdown
    stored = graph.get_state(cfg).values
    (parked,) = cast(list[Hypothesis], stored["parked"])
    assert parked.id == tagged.id and parked.tags == DEPENDENCY_TAGS
    trials = cast(list[Trial], stored["trials"])
    verdicts = cast(list[Verdict], stored["verdicts"])
    assert tagged.id not in {t.hypothesis_id for t in trials}
    assert tagged.id not in {v.hypothesis_id for v in verdicts}
    events = cast(list[EngineEvent], stored["events"])
    assert any(e.data.get("code") == "generated" for e in events)
