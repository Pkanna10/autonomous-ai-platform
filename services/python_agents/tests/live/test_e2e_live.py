"""Live E2E: the whole loop on the dedupe fixture with real Claude edits.

``build_context`` wires the real engine (preflight, understand, profiler,
baseline, trials edited by ``ClaudeEditor`` over the real
``AnthropicTransport``, combine, delivery) with the sandbox ``required``:
a host that cannot sandbox fails the test before the run starts, since the
loop runs code Claude wrote. The run is capped at ``MAX_COST_USD`` 3.0 and
offered two efficiency hypotheses.

A guard breach fails the test: a run that does not finish, spend over the
cap or a run ledger that does not match the wire, a change to the user's
repository or refs (the E2E "all three also assert" check), an unsandboxed
launch, or a violating trial that was committed, measured or delivered.
Whether Claude found and delivered a real speedup is recorded in the cost
summary, never asserted: a run with no win is a valid outcome.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from e2e.conftest import DEDUPE_REPO, Isolation, LaunchLog
from e2e.test_step2 import _check_repo_untouched

from autonomous_ai_agents.clients.transport import LLMTransport
from autonomous_ai_agents.common.config import Settings, settings
from autonomous_ai_agents.common.models import (
    ChangeClass,
    DeliveryKind,
    Hypothesis,
    HypothesisSource,
    Project,
    VerdictOutcome,
    Workload,
)
from autonomous_ai_agents.orchestrator.factory import build_context
from autonomous_ai_agents.orchestrator.main import Orchestrator

from .conftest import (
    TEST_COMMAND,
    StartLive,
    check_no_violating_trial_ran,
    check_sandboxed,
    check_spend,
    guardrails,
    make_repo,
)

pytestmark = pytest.mark.live

MAX_COST_USD = 3.0


def _no_factory(cfg: Settings) -> LLMTransport:
    raise AssertionError("the live E2E must use the captured transport")


def _candidates(project: Project) -> list[Hypothesis]:
    def make(title: str, rationale: str, gain: float) -> Hypothesis:
        return Hypothesis(
            project_id=project.id,
            source=HypothesisSource.playbook,
            title=title,
            rationale=rationale,
            change_class=ChangeClass.efficiency,
            expected_gain=gain,
            provability=0.9,
            risk=0.1,
        )

    return [
        make(
            "seen-set",
            "unique_in_order in dedupe/core.py checks membership in the result "
            "list for every item, which is quadratic. Keep a set of the values "
            "already seen next to the list, so each check is O(1) and the "
            "result keeps first-occurrence order.",
            0.8,
        ),
        make(
            "dict-fromkeys",
            "Replace the loop in unique_in_order with list(dict.fromkeys(items)), "
            "which keeps first-occurrence order in linear time.",
            0.6,
        ),
    ]


def test_live_whole_loop_on_the_dedupe_fixture(
    live: StartLive, live_root: Path, live_isolation: Isolation
) -> None:
    run = live(MAX_COST_USD)
    repo = make_repo(DEDUPE_REPO, live_root / "user")
    before = repo.snapshot()
    project = Project(
        name="dedupe", root_path=str(repo.path), test_command=TEST_COMMAND
    )
    workload = Workload(
        project_id=project.id, name="dedupe", command=("python", "-m", "dedupe.main")
    )
    candidates = _candidates(project)
    launches = LaunchLog()
    ctx = build_context(
        project,
        candidates=candidates,
        transport=run.transport(settings),
        transport_factory=_no_factory,
        network=live_isolation.mode,
        fs=live_isolation.mode,
        run=launches,
    )

    result = Orchestrator(context=ctx).run(
        project, [workload], [], guardrails(project), max_cost_usd=MAX_COST_USD
    )

    state = result.state
    assert result.status == "done", state["error"]
    check_spend(run, result)
    committed = {
        h.title
        for h in candidates
        for t in state["trials"]
        if t.hypothesis_id == h.id and t.commit is not None
    }
    _check_repo_untouched(repo, before, result, candidates, committed)
    check_sandboxed(launches, live_isolation)
    check_no_violating_trial_ran(result, repo)

    delivery = state["delivery"]
    assert delivery is not None
    titles = {h.id: h.title for h in candidates}
    outcomes = {titles[v.hypothesis_id]: v for v in state["verdicts"]}
    kept = sorted(t for t, v in outcomes.items() if v.outcome is VerdictOutcome.keep)
    gains = {t: v.gain for t, v in outcomes.items() if v.gain is not None}
    run.note(
        f"verdicts {{{', '.join(f'{t}: {v.outcome.value}' for t, v in outcomes.items())}}}; "
        f"gains {gains}; kept {kept or 'none'}"
    )
    shipped = delivery.kind is DeliveryKind.branch
    run.note(
        "speedup delivered on " + str(delivery.branch)
        if shipped
        else "no speedup delivered (report only)"
    )
    if state["understanding"] is None:
        run.note("understand fell back to the stub (no understanding)")
