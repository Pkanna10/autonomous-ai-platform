"""Offline guards of the discovery experiments (E3 sweep, E5 A/B, E8a).

No ``live`` marker, no network, no key: every check runs the production
wiring (``LiveRun.transport`` -> ``AnthropicTransport`` -> the capture) with
only the httpx wire swapped for a mock, or a pure function of the helpers.
"""

from __future__ import annotations

import ast
import contextlib
import json
import os
import re
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx2
import pytest
from e2e.conftest import Isolation

from autonomous_ai_agents.clients.budget import Budget
from autonomous_ai_agents.clients.cost import chain, count_margin, preflight_estimate
from autonomous_ai_agents.clients.structured import PROMPT_ALLOWANCE_TOKENS
from autonomous_ai_agents.clients.transport import ScriptedTransport
from autonomous_ai_agents.common.config import EFFORT_LEVELS, Settings, settings
from autonomous_ai_agents.common.models import (
    METRIC_WALL_TIME_S,
    CandidateModule,
    ChangeClass,
    Direction,
    Hotspot,
    Hypothesis,
    HypothesisSource,
    Objective,
    ObjectiveKind,
    ProjectUnderstanding,
    Technique,
    Trial,
    TrialStatus,
    new_id,
)
from autonomous_ai_agents.execution.editor import ClaudeEditor
from autonomous_ai_agents.execution.profiler import MAX_HOTSPOTS
from autonomous_ai_agents.optimization.generate import (
    GENERATE_MAX_TOKENS,
    generate_hypotheses,
)
from autonomous_ai_agents.orchestrator.factory import build_context
from autonomous_ai_agents.orchestrator.main import EngineRunResult
from autonomous_ai_agents.orchestrator.state import initial_state
from autonomous_ai_agents.orchestrator.understand import ClaudeUnderstander
from autonomous_ai_agents.research.playbook import (
    MATCH_MAX_TOKENS,
    load_playbook,
    match_techniques,
)

from . import corpus, discovery
from . import discovery_ab as ab
from . import discovery_escalation as esc
from . import discovery_grader as grader
from . import discovery_sweep as sweep
from .conftest import (
    _CELL_MAX,
    TESTS_DIR,
    LiveRun,
    _cell,
    guardrails,
    make_repo,
    redact_keys,
    restore_host_key,
    xdist_refusal,
)
from .corpus import (
    CORPUS,
    HARD_CORPUS,
    HARD_SOLUTIONS_DIR,
    SOLUTIONS_DIR,
    CorpusOutcome,
    CorpusRepo,
)
from .discovery import (
    BLIND_PROMPT_BOUND,
    CARDS_PROMPT_BOUND,
    FABLE,
    MATCH_PROMPT_BOUND,
    OPUS,
    PHASE_ONE_CAP_USD,
    PROBE_PROMPT_BOUND,
    SONNET,
    UNDERSTAND_PROMPT_BOUND,
    ArmResult,
    RepoFacts,
    carry,
    check_calls,
    check_untouched,
    generate_arm,
    model_settings,
    phase_one,
    read_phase_one,
    run_engine,
    start_phase_one,
)
from .discovery_corpus import DISCOVERY_CORPUS
from .discovery_io import (
    ResultsSink,
    cells,
    env_flag,
    json_line,
)

LIVE_DIR = TESTS_DIR / "live"
CAP_CEILING_USD = 150  # live-smoke's suite_cap_usd ceiling
# The suite needs at the default knobs (the sum of the caps the tests ask the
# ledger for); the Lead copies them into ci.yml.
# The sweep covers v1, the hard corpus and corpus v2 (37 repositories: 32
# slowdowns, 5 controls, the 2 v2 decoys among them).
SWEEP_NEED = 111.75  # 32 slowdowns x 3.15 + 5 controls x 2.05 + probe 0.70
SWEEP_FABLE_NEED = 128.55  # + 12 Fable runs x 1.40
# The recorded sweep on one arm (LIVE_SWEEP_ARMS=sonnet-5-5-medium,
# LIVE_SWEEP_RECORD=1, Fable off): 32 slowdowns x 0.65 + 5 controls x 0.40
# + probe 0.70. Recording sends no request, so it is the plain one-arm need.
SWEEP_RECORD_NEED = 23.5
AB_NEED = 140.0  # 2 reps x 25 repos x (0.80 + 2 x 1.00)
ESC_NEED = 42.9  # 15 first passes x 0.70 + 12 escalations x 2.70
SLOWDOWNS = tuple(r for r in CORPUS if r.kind == "slowdown")
CONTROLS = tuple(r for r in CORPUS if r.kind == "control")
V2_SLOWDOWNS = tuple(r for r in DISCOVERY_CORPUS if r.kind == "slowdown")
DECOYS = tuple(r for r in DISCOVERY_CORPUS if r.category == "decoy")
REQUIRED = Isolation("required", None)
Json = dict[str, Any]

# ---------------------------------------------------------------------------
# The mock wire and the inputs a phase 1 would produce
# ---------------------------------------------------------------------------

USAGE: Json = {
    "input_tokens": 1000,
    "output_tokens": 200,
    "cache_read_input_tokens": 0,
    "cache_creation_input_tokens": 0,
    "output_tokens_details": {"thinking_tokens": 50},
}


class Wire:
    """Answers count_tokens with a fixed count and each message request with
    ``answer(body)``, served by the requested model; keeps every body."""

    def __init__(
        self, answer: Callable[[Json], str], usages: Sequence[Json] = ()
    ) -> None:
        self.answer, self.usages = answer, deque(usages)
        self.bodies: list[Json] = []
        self.counted: list[Json] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        body: Json = json.loads(request.read())
        if request.url.path.endswith("/count_tokens"):
            self.counted.append(body)
            return httpx2.Response(200, json={"input_tokens": 900}, request=request)
        self.bodies.append(body)
        usage = self.usages.popleft() if self.usages else USAGE
        message = {
            "id": f"msg_{len(self.bodies)}",
            "type": "message",
            "role": "assistant",
            "model": body["model"],
            "content": [{"type": "text", "text": self.answer(body)}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": usage,
        }
        return httpx2.Response(200, json=message, request=request)

    def run(self, cap: float = 5.0) -> LiveRun:
        return LiveRun("dry", cap, wire=httpx2.MockTransport(self))


def _schema_keys(body: Json) -> set[str]:
    return set(body["output_config"]["format"]["schema"]["properties"])


def _item(title: str, gain: float = 0.5, slug: str | None = None) -> Json:
    return {
        "title": title,
        "technique_slug": slug,
        "hotspots": [{"file_path": "blockhash/core.py", "symbol": "digest"}],
        "change_summary": f"Change for {title}.",
        "justification_summary": "The hotspot dominates the profile.",
        "change_class": "efficiency",
        "expected_gain": gain,
        "provability": 0.8,
        "risk": 0.1,
    }


def _ideas(count: int = 5, gain: float = 0.5) -> str:
    return json.dumps({"hypotheses": [_item(f"idea {i}", gain) for i in range(count)]})


def _all_hits(body: Json) -> str:
    text = body["messages"][0]["content"][0]["text"]
    ids = sorted(set(re.findall(r'"id": "(H\d+)"', text)))
    grades = [
        {
            "hypothesis_id": i,
            "targets_reference_root_cause": True,
            "root_cause": 1,
            "justification_summary": "j",
        }
        for i in ids
    ]
    return json.dumps({"grades": grades})


UNDERSTOOD = {
    "language": "python",
    "summary": "A small command-line workload.",
    "entrypoints": [],
    "workload_notes": [],
    "candidate_modules": [],
}


def _listed_hotspot(body: Json) -> Json:
    """The first profiler hotspot the request shows (its file and symbol)."""
    text = body["messages"][0]["content"][0]["text"]
    line = next(x for x in text.splitlines() if x.startswith('{"file_path"'))
    shown: Json = json.loads(line)
    return {"file_path": shown["file_path"], "symbol": shown["symbol"]}


def _answer(body: Json) -> str:
    keys = _schema_keys(body)
    if "language" in keys:
        return json.dumps(UNDERSTOOD)
    if "grades" in keys:
        return _all_hits(body)
    if "matches" in keys:
        slugs = ("set-membership-test", "process-pool-parallelism")
        found = [
            {
                "slug": s,
                "fit": 0.9,
                "justification_summary": "j",
                "unmet_preconditions": [],
            }
            for s in slugs
        ]
        return json.dumps({"matches": found})
    return _ideas()


@pytest.fixture
def dry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A real-path tmp dir, the dry-run key, ``WORKTREE_ROOT`` beside it."""
    root = Path(os.path.realpath(tmp_path))
    monkeypatch.setattr(settings, "WORKTREE_ROOT", root / "wt-root")
    restore_host_key(monkeypatch, "dry-run-key")
    return root


def _facts(root: Path, repo: CorpusRepo = CORPUS[0]) -> RepoFacts:
    project = repo.project(root)
    hotspot = Hotspot(
        project_id=project.id,
        workload_id="w1",
        file_path="blockhash/core.py",
        symbol="digest",
        self_time_s=1.0,
        total_time_s=1.0,
        share=0.9,
    )
    objective = Objective(
        project_id=project.id,
        kind=ObjectiveKind.runtime,
        metric=METRIC_WALL_TIME_S,
        direction=Direction.minimize,
        min_relative_gain=0.02,
        description="minimize wall time",
    )
    return RepoFacts(project, None, (hotspot,), objective)


def _no_wire(request: httpx2.Request) -> httpx2.Response:
    raise AssertionError(f"building the loop sent {request.url}")


# ---------------------------------------------------------------------------
# Knobs: strict parsing before any spend, settings copies
# ---------------------------------------------------------------------------


def test_arm_parsing_refuses_unknown_values_before_any_spend() -> None:
    labels = [arm.label for arm in sweep.ARMS]
    assert sweep.sweep_arms({}) == sweep.ARMS
    assert [a.label for a in sweep.sweep_arms({sweep.ARMS_ENV: labels[2]})] == [
        labels[2]
    ]
    two = f"{labels[3]},{labels[0]}"
    assert [a.label for a in sweep.sweep_arms({sweep.ARMS_ENV: two})] == [
        labels[3],
        labels[0],
    ]
    bad = ("", "opus", "opus-5-5-max", f"{labels[0]},{labels[0]}", f"{labels[0]},")
    for value in (*bad, "fable-5-1-medium", f" {labels[0]}", labels[0].upper()):
        with pytest.raises(ValueError, match=sweep.ARMS_ENV):
            sweep.sweep_arms({sweep.ARMS_ENV: value})
    assert env_flag({}, sweep.FABLE_ENV) is False
    assert sweep.sweep_plan({sweep.FABLE_ENV: "1"}).fable is True
    for value in ("yes", "true", " 1", "2"):
        with pytest.raises(ValueError, match=sweep.FABLE_ENV):
            sweep.sweep_plan({sweep.FABLE_ENV: value})
    assert ab.ab_plan({}) == ab.AbPlan(reps=2, run_cap=1.0)
    assert ab.AB_MAX_REPS == 2  # 3 would take the suite past the 150 USD ceiling
    for value in ("0", "3", "2.0", " 2", "", "two", "٢"):
        with pytest.raises(ValueError, match=ab.REPS_ENV):
            ab.ab_plan({ab.REPS_ENV: value})
    for value in ("0", "-1", "nan", "inf", "6", " 1", "1e9", "x"):
        with pytest.raises(ValueError, match=ab.RUN_CAP_ENV):
            ab.ab_plan({ab.RUN_CAP_ENV: value})
    assert ab.ab_plan({ab.REPS_ENV: "1", ab.RUN_CAP_ENV: "1.5"}) == ab.AbPlan(1, 1.5)


def test_each_live_module_parses_its_knobs_in_a_module_fixture() -> None:
    """Parsing in a module-scoped fixture fails at its setup, before the
    first test's ``live(...)`` admits any spend."""
    for stem, parse in (
        ("test_sweep_live", "sweep_plan(os.environ)"),
        ("test_ab_live", "ab_plan(os.environ)"),
        ("test_escalation_live", "ResultsSink(os.environ)"),
    ):
        source = (LIVE_DIR / f"{stem}.py").read_text(encoding="utf-8")
        assert '@pytest.fixture(scope="module")' in source, stem
        assert parse in source, stem


def test_every_arm_model_is_priced_and_accepts_its_effort() -> None:
    for arm in (*sweep.ARMS, sweep.FABLE_ARM, ab.AB_ARM):
        assert arm.model in settings.MODEL_PRICING, arm
        assert arm.effort in EFFORT_LEVELS[arm.model], arm
    assert {a.model for a in sweep.ARMS} == {OPUS, SONNET}
    assert sweep.FABLE_ARM.model == FABLE
    # The grader is under no comparison: no arm of any experiment uses it.
    arm_models = {a.model for a in (*sweep.ARMS, sweep.FABLE_ARM, ab.AB_ARM)}
    assert grader.GRADER_MODEL == "claude-opus-4-8" not in arm_models
    assert grader.GRADER_MODEL in settings.MODEL_PRICING
    assert grader.GRADER_EFFORT == "low" in EFFORT_LEVELS[grader.GRADER_MODEL]
    assert grader.GRADER_MAX_TOKENS == 4000


def test_model_settings_copies_validate_and_never_touch_the_global() -> None:
    before = settings.model_dump()
    cfg = model_settings(settings, SONNET, EDITOR_EFFORT="low")
    assert (cfg.ENGINE_MODEL, cfg.ENGINE_FALLBACKS, cfg.EDITOR_EFFORT) == (
        SONNET,
        False,
        "low",
    )
    assert chain(cfg) == (SONNET,)
    assert settings.model_dump() == before
    assert cfg.ANTHROPIC_API_KEY == settings.ANTHROPIC_API_KEY  # the key travels
    assert cfg.WORKTREE_ROOT == settings.WORKTREE_ROOT
    with pytest.raises(ValueError, match="MODEL_PRICING"):
        model_settings(settings, "claude-unknown-9")
    priced = {**settings.MODEL_PRICING, "claude-opus-4-6": settings.MODEL_PRICING[OPUS]}
    with pytest.raises(ValueError, match="EDITOR_EFFORT 'xhigh' is not accepted"):
        model_settings(
            settings, "claude-opus-4-6", EDITOR_EFFORT="xhigh", MODEL_PRICING=priced
        )


# ---------------------------------------------------------------------------
# Arms on the wire: each bills its own model only
# ---------------------------------------------------------------------------


def test_each_arm_bills_only_its_model_on_the_wire(dry: Path) -> None:
    facts = _facts(dry)
    for arm in (*sweep.ARMS, sweep.FABLE_ARM):
        wire = Wire(_answer)
        run = wire.run()
        budget = Budget(run.cap_usd)
        result = generate_arm(arm, run, budget, facts, n=sweep.SWEEP_N)
        (body,) = wire.bodies
        assert body["model"] == arm.model and "fallbacks" not in body
        assert body["output_config"]["effort"] == arm.effort
        assert body["max_tokens"] == GENERATE_MAX_TOKENS  # the shipped default
        assert {c["model"] for c in wire.counted} == {arm.model}
        assert result.models == (arm.model,) and result.answered
        assert len(result.hypotheses) == 5 and result.error is None
        assert result.thinking_tokens == 50 and result.tokens("output_tokens") == 200
        assert result.hypotheses[0].hotspot_ids == (facts.hotspots[0].id,)
        check_calls(run, budget, [result])


def test_a_refused_or_unusable_arm_is_recorded_and_fails_the_guard(dry: Path) -> None:
    facts = _facts(dry)
    arm = sweep.ARMS[2]
    unusable = Wire(lambda _body: "not json")
    run = unusable.run()
    result = generate_arm(arm, run, Budget(run.cap_usd), facts, n=5)
    assert result.answered and result.hypotheses == ()
    assert result.error is not None and "UnusableReplyError" in result.error
    refused_wire = Wire(_answer)
    run = refused_wire.run(cap=0.01)
    budget = Budget(run.cap_usd)
    refused = generate_arm(arm, run, budget, facts, n=5)
    assert refused_wire.bodies == [] and not refused.answered
    assert refused.error is not None and "BudgetExceeded" in refused.error
    with pytest.raises(AssertionError, match=arm.label):
        check_calls(run, budget, [refused])


def test_a_record_billed_to_another_model_fails_the_guard(dry: Path) -> None:
    run = Wire(_answer).run()
    budget = Budget(run.cap_usd)
    result = generate_arm(sweep.ARMS[3], run, budget, _facts(dry), n=5)
    check_calls(run, budget, [result])
    with pytest.raises(AssertionError, match=sweep.ARMS[3].label):
        check_calls(run, budget, [replace(result, models=(SONNET, OPUS))])
    with pytest.raises(AssertionError):
        check_calls(run, budget, [replace(result, models=(OPUS,))])


def test_the_retrieval_arm_matches_then_generates_from_the_cards(dry: Path) -> None:
    wire = Wire(_answer)
    run = wire.run()
    budget = Budget(run.cap_usd)
    result = ab.retrieval_arm(run, budget, _facts(dry), playbook=load_playbook())
    match, generate = wire.bodies
    assert "matches" in _schema_keys(match) and "hypotheses" in _schema_keys(generate)
    for body in (match, generate):
        assert body["model"] == SONNET and body["output_config"]["effort"] == "medium"
    assert generate["max_tokens"] == ab.AB_GENERATE_MAX_TOKENS
    assert [m.slug for m in result.matches] == [
        "set-membership-test",
        "process-pool-parallelism",
    ]
    system = generate["system"][0]["text"]
    assert "set-membership-test" in system and "process-pool-parallelism" in system
    assert "deque-for-fifo-queue" not in system  # only the matched cards
    assert len(result.hypotheses) == ab.AB_N
    blind = ab.blind_arm(run, budget, _facts(dry))
    assert (
        "No playbook techniques" in wire.bodies[-1]["messages"][0]["content"][0]["text"]
    )
    assert len(blind.hypotheses) == ab.AB_N
    assert wire.bodies[-1]["max_tokens"] == ab.AB_GENERATE_MAX_TOKENS
    check_calls(run, budget, [result, blind])


# ---------------------------------------------------------------------------
# The grader
# ---------------------------------------------------------------------------


def _generated(dry: Path, texts: Sequence[str]) -> ArmResult:
    reply = json.dumps({"hypotheses": [_item(t) for t in texts]})
    run = Wire(lambda _body: reply).run()
    return generate_arm(sweep.ARMS[0], run, Budget(5.0), _facts(dry), n=5)


def test_the_grader_request_names_no_arm_and_uses_the_fixed_seed_shuffle(
    dry: Path,
) -> None:
    titles = ["Opus idea", "claude-sonnet-5-5 idea", "plain idea", "FABLE idea", "x"]
    produced = _generated(dry, titles)
    repo = SLOWDOWNS[0]
    patches = grader.reference_patches(repo)
    wire = Wire(_answer)
    run = wire.run()
    grade = grader.grade(run, Budget(5.0), repo, patches, produced.hypotheses)
    (body,) = wire.bodies
    assert body["model"] == grader.GRADER_MODEL and "fallbacks" not in body
    assert body["output_config"]["effort"] == "low"
    shown = {k: v for k, v in body.items() if k != "model"}  # all but the grader's id
    text = json.dumps(shown).casefold()
    for arm in (*sweep.ARMS, sweep.FABLE_ARM):
        assert arm.label not in text and arm.model not in text
    for word in ("opus", "sonnet", "fable", "haiku", "claude", "mythos"):
        assert word not in text, word
    user = body["messages"][0]["content"][0]["text"]
    order = grader.shuffled(5, repo.name)
    assert order == grader.shuffled(5, repo.name) and sorted(order) == list(range(5))
    assert order != list(range(5))  # the seed really shuffles this one
    assert repo.name == "tagfilter" and order == [1, 0, 2, 3, 4]  # any process
    positions = [user.index(f'"id": "H{k + 1}"') for k in range(5)]
    assert positions == sorted(positions)
    for k, index in enumerate(order):
        line = next(x for x in user.splitlines() if f'"id": "H{k + 1}"' in x)
        expected = grader.scrub(produced.hypotheses[index].title)
        assert json.loads(line)["title"] == expected
    assert patches[0].text.splitlines()[0] in user
    assert grade.hits == (True,) * 5 and grade.answered
    assert grade.models == (grader.GRADER_MODEL,) and grade.causes == (1,) * 5


def test_grades_map_back_to_the_model_order_and_drop_unknown_ids(dry: Path) -> None:
    produced = _generated(dry, ["a", "b", "c", "d", "e"])
    repo = SLOWDOWNS[1]
    order = grader.shuffled(5, repo.name)
    first_shown = order.index(0) + 1  # the id the model's best idea got

    def answer(_body: Json) -> str:
        grades = [
            {
                "hypothesis_id": f"H{first_shown}",
                "targets_reference_root_cause": True,
                "root_cause": 1,
                "justification_summary": "j",
            },
            {
                "hypothesis_id": "H9",
                "targets_reference_root_cause": True,
                "root_cause": 1,
                "justification_summary": "unknown id",
            },
            {
                "hypothesis_id": f"H{first_shown}",
                "targets_reference_root_cause": False,
                "root_cause": None,
                "justification_summary": "a repeat is ignored",
            },
        ]
        return json.dumps({"grades": grades})

    run = Wire(answer).run()
    patches = grader.reference_patches(repo)
    grade = grader.grade(run, Budget(5.0), repo, patches, produced.hypotheses)
    assert grade.hits[0] is True and grade.hits[1:] == (None,) * 4
    assert grade.causes == (1, None, None, None, None)
    assert grade.hit_at(1) is True and grade.hit_at(5) is True
    none = grader.grade(run, Budget(5.0), repo, patches, ())
    assert none.hits == () and none.hit_at(1) is False and none.cost_usd == 0
    broken = Wire(lambda _b: "{").run()
    failed = grader.grade(broken, Budget(5.0), repo, patches, produced.hypotheses)
    assert failed.answered and failed.error is not None and failed.hit_at(5) is None


def test_reference_patches_come_only_from_the_solutions_dirs(tmp_path: Path) -> None:
    for repo in (*SLOWDOWNS, *HARD_CORPUS):
        patches = grader.reference_patches(repo)
        assert patches, repo.name
        folder = SOLUTIONS_DIR if repo.root == corpus.CORPUS_DIR else HARD_SOLUTIONS_DIR
        for patch in patches:
            assert (folder / patch.name).is_file() and "naive" not in patch.name
            assert patch.text.startswith("diff --git") or "--- " in patch.text
    parts = grader.reference_patches(HARD_CORPUS[0])
    assert [p.name for p in parts] == [
        f"{HARD_CORPUS[0].name}.part{k}.patch" for k in range(1, len(parts) + 1)
    ]
    for control in CONTROLS:
        assert grader.reference_patches(control) == ()
    # A repository outside the corpus roots, or a patch inside the repository
    # itself, is never read; a planted link in a solutions dir is refused.
    fake = replace(SLOWDOWNS[0], root=tmp_path)
    (tmp_path / fake.name).mkdir()
    (tmp_path / fake.name / f"{fake.name}.patch").write_text("diff --git a b\n")
    with pytest.raises(ValueError, match="_solutions"):
        grader.reference_patches(fake)
    solutions = tmp_path / "_solutions"
    solutions.mkdir()
    allowed = (solutions,)
    with pytest.raises(FileNotFoundError):
        grader.reference_patches(fake, allowed=allowed)
    (solutions / f"{fake.name}.patch").symlink_to(SOLUTIONS_DIR / f"{fake.name}.patch")
    with pytest.raises(ValueError, match="link"):
        grader.reference_patches(fake, allowed=allowed)
    (solutions / f"{fake.name}.patch").unlink()
    (solutions / f"{fake.name}.patch").write_bytes(b"x" * (grader.MAX_PATCH_BYTES + 1))
    with pytest.raises(ValueError, match="bytes"):
        grader.reference_patches(fake, allowed=allowed)


def test_scrub_removes_every_model_name() -> None:
    text = grader.scrub("Claude Opus-5-5 and sonnet, FABLE, haiku and mythos")
    assert not re.search(r"(?i)claude|opus|sonnet|fable|haiku|mythos", text)


# ---------------------------------------------------------------------------
# Phase 1 and the hand-over to phase 2
# ---------------------------------------------------------------------------


def test_phase_one_starts_a_zero_candidate_loop_and_reads_its_state(dry: Path) -> None:
    run = LiveRun("dry", 0.6, wire=httpx2.MockTransport(_no_wire))
    cfg = model_settings(settings, SONNET)
    loop = start_phase_one(CORPUS[0], run, dry / "phase", REQUIRED, cfg)
    assert loop.candidates == () and loop.context.candidates == ()
    assert loop.cap_usd == PHASE_ONE_CAP_USD and loop.mode == "blind"
    assert loop.user.path == dry / "phase" / "user"
    assert run.capture.exchanges == []
    state = initial_state(loop.project, [loop.workload], [], guardrails(loop.project))
    facts = _facts(dry)
    state["objectives"] = [facts.objective]
    state["hotspots"] = list(facts.hotspots)
    phase = read_phase_one(loop, run, EngineRunResult("r", "done", state, None))
    assert phase.facts.objective == facts.objective
    assert phase.facts.hotspots == facts.hotspots and phase.cost_usd == 0
    state["objectives"] = []
    with pytest.raises(ValueError, match="objective"):
        read_phase_one(loop, run, EngineRunResult("r", "done", state, None))


@pytest.mark.slow
def test_phase_one_runs_on_the_real_engine_and_hands_over_to_phase_two(
    dry: Path,
) -> None:
    """Phase 1 for real (git, the sandbox, baseline, cProfile) with only the
    wire mocked; then a blind arm on its facts and the phase-2 hand-over."""

    def answer(body: Json) -> str:
        if "hypotheses" in _schema_keys(body):
            item = {**_item("idea"), "hotspots": [_listed_hotspot(body)]}
            return json.dumps({"hypotheses": [item]})
        return _answer(body)

    wire = Wire(answer)
    repo = CONTROLS[0]
    run = wire.run(cap=sweep.sweep_plan({}).cap_for(repo))
    phase = phase_one(
        repo, run, dry / "phase", REQUIRED, model_settings(settings, SONNET)
    )
    (understand,) = wire.bodies
    assert understand["model"] == SONNET and "fallbacks" not in understand
    facts = phase.facts
    assert (
        facts.understanding is not None
        and facts.understanding.served_by_model == SONNET
    )
    assert facts.hotspots and facts.objective.metric == METRIC_WALL_TIME_S
    assert 0 < phase.cost_usd == run.spent_usd <= PHASE_ONE_CAP_USD
    with pytest.raises(ValueError, match="first spend"):
        phase_one(repo, run, dry / "again", REQUIRED, model_settings(settings, SONNET))
    budget = Budget(run.cap_usd, run.spent_usd)
    arm = generate_arm(sweep.ARMS[0], run, budget, facts, n=sweep.SWEEP_N)
    assert arm.hypotheses[0].hotspot_ids == (facts.hotspots[0].id,)
    check_calls(run, budget, [arm])
    check_untouched(phase)
    two = LiveRun("dry", 1.0, wire=httpx2.MockTransport(_no_wire))
    loop = corpus.start_loop(
        repo, two, dry / "two", REQUIRED, mode="blind", candidates=carry(arm.hypotheses)
    )
    assert [h.hotspot_ids for h in loop.context.candidates] == [()]


def test_phase_one_hypotheses_reach_phase_two_with_hotspot_ids_cleared(
    dry: Path,
) -> None:
    """Only efficiency ideas are handed over: an idea on a behaviour card (a
    distractor) is upgraded to behaviour by the generator and would pause
    the run at the approval gate."""
    items = [_item(t) for t in ("a", "b", "c")]
    items.append(_item("vectorise", slug="numpy-vectorization"))
    reply = json.dumps({"hypotheses": items})
    run = Wire(lambda _body: reply).run()
    playbook = load_playbook()
    produced = generate_arm(
        ab.AB_ARM, run, Budget(5.0), _facts(dry), n=5, techniques=playbook
    )
    assert produced.hypotheses[3].change_class.value == "behaviour"
    assert all(h.hotspot_ids for h in produced.hypotheses)
    row = ab.ab_row(SLOWDOWNS[0], 1, "B", produced, None, frozenset())
    assert (row.candidates, row.dropped) == (3, 1)
    run = LiveRun("dry", 1.0, wire=httpx2.MockTransport(_no_wire))
    cfg = ab.ab_settings(settings)
    loop = corpus.start_loop(
        SLOWDOWNS[0],
        run,
        dry,
        REQUIRED,
        mode="blind",
        cfg=cfg,
        candidates=carry(produced.hypotheses),
    )
    assert [h.title for h in loop.context.candidates] == ["a", "b", "c"]
    for hypothesis in loop.context.candidates:
        assert hypothesis.hotspot_ids == () and hypothesis.project_id == loop.project.id
    assert run.capture.exchanges == []


def test_start_loop_with_settings_wires_that_chain_editor_and_trial_budget(
    dry: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}
    real = build_context

    def spy(*args: Any, **kwargs: Any) -> Any:
        seen.update(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(corpus, "build_context", spy)
    run = LiveRun("dry", 1.0, wire=httpx2.MockTransport(_no_wire))
    cfg = esc.first_settings(settings)
    corpus.start_loop(SLOWDOWNS[0], run, dry, REQUIRED, cfg=cfg)
    assert seen["transport"].chain == (SONNET,)
    editor = seen["editor"](module_roots=frozenset(), reserved_modules=frozenset())
    assert isinstance(editor, ClaudeEditor)
    assert editor._wiring.config is cfg and editor._wiring.effort == "low"
    assert seen["min_trial_budget_usd"] == corpus.settings_trial_budget(cfg)
    seen.clear()
    corpus.start_loop(SLOWDOWNS[0], run, dry / "plain", REQUIRED)
    assert seen["editor"] is None and seen["min_trial_budget_usd"] is None
    assert seen["transport"].chain == chain(settings)


# ---------------------------------------------------------------------------
# Escalation
# ---------------------------------------------------------------------------


def _outcome(repo: CorpusRepo, delivered: bool, cost: float = 0.05) -> CorpusOutcome:
    return CorpusOutcome(
        repo=repo.name,
        kind=repo.kind,
        expected=repo.expected,
        status="done",
        engine_model=SONNET,
        served_models=(SONNET,),
        kept=("x",) if delivered else (),
        delivered=delivered,
        aimed_kept=delivered,
        gain_pct=50.0 if delivered else None,
        best_trial_gain_pct=None,
        cost_usd=cost,
        cap_usd=1.0,
        trials=2,
        violations=(),
        guard="ok",
    )


def test_escalation_reruns_exactly_the_failed_slowdowns_with_the_right_settings() -> (
    None
):
    before = settings.model_dump()
    failing = {SLOWDOWNS[1].name, SLOWDOWNS[4].name, CONTROLS[0].name}
    rows = []
    calls: list[tuple[str, str, Settings, float]] = []
    for repo in esc.ESCALATION_REPOS:

        def run_pass(
            stage: esc.Stage, cfg: Settings, cap: float, repo: CorpusRepo = repo
        ) -> CorpusOutcome:
            calls.append((repo.name, stage, cfg, cap))
            won = stage == "escalated" or repo.name not in failing
            return _outcome(repo, won)

        rows.append(esc.run_escalation(repo, run_pass, settings))
    escalated = [
        (name, cfg, cap) for name, stage, cfg, cap in calls if stage != "first"
    ]
    assert {name for name, _, _ in escalated} == {SLOWDOWNS[1].name, SLOWDOWNS[4].name}
    for _, cfg, cap in escalated:
        assert (cfg.ENGINE_MODEL, cfg.EDITOR_EFFORT, cap) == (
            OPUS,
            "high",
            esc.ESCALATED_CAP_USD,
        )
        assert chain(cfg) == (OPUS,)  # fallbacks off, like every other arm
    firsts = [(cfg, cap) for _, stage, cfg, cap in calls if stage == "first"]
    assert len(firsts) == len(CORPUS)
    for cfg, cap in firsts:
        assert (cfg.ENGINE_MODEL, cfg.EDITOR_EFFORT) == (SONNET, "low")
        assert chain(cfg) == (SONNET,) and cap == esc.FIRST_CAP_USD
    assert settings.model_dump() == before
    assert sum(row.final_win for row in rows) == len(CORPUS) - 1  # the control
    assert esc.needs_escalation(CONTROLS[0], _outcome(CONTROLS[0], False)) is False
    text = esc.render_escalation(rows)
    assert "First pass (Sonnet 5.5, editor effort low): 10/12" in text
    assert "After escalation (Opus 5.5, editor effort high): 12/12" in text
    assert "U22 baseline" in text and "0.1000" in text and "0.0450" in text
    assert "full re-run (understand, baseline, profile)" in text
    assert "production escalation would re-run only the editor" in text


# ---------------------------------------------------------------------------
# McNemar, the A/B rows and summary
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("b", "c", "p"),
    [
        (0, 0, 1.0),
        (0, 3, 0.25),
        (3, 0, 0.25),
        (0, 5, 0.0625),
        (1, 6, 0.125),
        (2, 8, 0.109375),
        (3, 3, 1.0),
        (5, 15, 0.041389465332031250),
    ],
)
def test_mcnemar_exact_matches_known_values(b: int, c: int, p: float) -> None:
    assert ab.mcnemar_exact(b, c) == pytest.approx(p, rel=1e-12)


def test_mcnemar_refuses_negative_counts() -> None:
    with pytest.raises(ValueError):
        ab.mcnemar_exact(-1, 2)


def _ab_rows(dry: Path) -> list[ab.AbRow]:
    produced = _generated(dry, ["a"])
    matched = replace(produced, matches=())
    rows: list[ab.AbRow] = []
    wins = {  # (repo index, rep): (A win, B win)
        (0, 1): (False, True),
        (1, 1): (False, True),
        (2, 1): (False, True),
        (3, 1): (True, False),
        (4, 1): (True, True),
    }
    for (index, rep), (a_win, b_win) in wins.items():
        repo = SLOWDOWNS[index]
        for label, won in (("A", a_win), ("B", b_win)):
            rows.append(
                ab.ab_row(repo, rep, label, matched, _outcome(repo, won), frozenset())
            )
    control = CONTROLS[0]
    rows.append(ab.ab_row(control, 1, "A", produced, _outcome(control, True), set()))
    rows.append(ab.ab_row(control, 1, "B", produced, None, frozenset()))
    return rows


def test_a_retrieval_win_claims_the_playbook_not_the_papers(dry: Path) -> None:
    """B's cards come from the playbook: a win there says nothing yet about
    cards extracted from papers."""
    produced = _generated(dry, ["a"])
    rows = [
        ab.ab_row(repo, 1, label, produced, _outcome(repo, label == "B"), ())
        for repo in SLOWDOWNS[:3]
        for label in ("A", "B")
    ]
    assert ab.discordant(rows)[1:] == (0, 3)
    text = ab.render_ab(rows)
    assert "c - b = 3: B beats A by at least 3" in text
    assert "retrieved playbook cards help" in text
    assert "paper-derived cards are untested" in text


def test_ab_summary_counts_discordant_pairs_and_prints_the_rule(dry: Path) -> None:
    produced = _generated(dry, ["a"])
    unpaired = ab.ab_row(
        SLOWDOWNS[5], 1, "A", produced, _outcome(SLOWDOWNS[5], True), ()
    )
    won = _outcome(SLOWDOWNS[6], True)
    breach = replace(won, guard="breach: AssertionError: x")
    rows = [
        *_ab_rows(dry),
        unpaired,  # its B never ran: not a pair
        ab.ab_row(SLOWDOWNS[6], 1, "A", produced, _outcome(SLOWDOWNS[6], False), ()),
        ab.ab_row(SLOWDOWNS[6], 1, "B", produced, breach, ()),  # a breach: not a pair
    ]
    pairs, b, c = ab.discordant(rows)
    assert (b, c) == (1, 3) and len(pairs) == 5
    assert (SLOWDOWNS[6].name, 1) not in pairs and (SLOWDOWNS[5].name, 1) not in pairs
    text = ab.render_ab(rows)
    assert "excluded 2 slowdown task(s)" in text
    assert "cards reach only the generator" in text and "top-5" in text
    assert "b = 1, c = 3" in text and "p = 0.6250" in text
    assert "B must beat A by at least 3 discordant tasks" in text
    assert "c - b = 2: B does not beat A by 3" in text
    assert "retrieved playbook cards did not help" in text
    assert "Control false-win rate: A 1/1" in text
    more = [*rows, *(r for r in _ab_rows(dry)[:6] if r.arm == "B")]
    assert ab.discordant(more)[1:] == (1, 3)  # a task counts once per (repo, rep)


def test_ab_row_records_matched_slugs_and_distractors(dry: Path) -> None:
    run = Wire(_answer).run()
    retrieved = ab.retrieval_arm(
        run, Budget(5.0), _facts(dry), playbook=load_playbook()
    )
    distractors = ab.load_distractors()
    assert "process-pool-parallelism" in distractors
    row = ab.ab_row(
        SLOWDOWNS[0], 2, "B", retrieved, _outcome(SLOWDOWNS[0], True), distractors
    )
    assert row.matched == ("set-membership-test", "process-pool-parallelism")
    assert row.distractor_matched is True and row.win and row.rep == 2
    blind = ab.ab_row(SLOWDOWNS[0], 2, "A", retrieved, None, distractors)
    assert blind.distractor_matched is None and blind.status == "no_hypotheses"
    assert "E5" in json_line(row.record())


def test_load_distractors_is_strict(tmp_path: Path) -> None:
    path = tmp_path / "d.json"
    for bad in (
        '{"version": 2, "slugs": []}',
        '{"version": 1}',
        '{"version": 1, "slugs": [1]}',
    ):
        path.write_text(bad)
        with pytest.raises(ValueError):
            ab.load_distractors(path)


# ---------------------------------------------------------------------------
# Sweep rows, the cache probe, summaries
# ---------------------------------------------------------------------------


def test_sweep_rows_record_hits_and_a_controls_big_gain_claim(dry: Path) -> None:
    produced = _generated(dry, ["a", "b"])
    grade = grader.Grade(
        hits=(False, True),
        cost_usd=0.01,
        answered=True,
        error=None,
        causes=(None, 2),
        parts=3,
    )
    row = sweep.sweep_row(SLOWDOWNS[0], produced, grade, 0.03)
    assert (row.hit_at_1, row.hit_at_5, row.big_gain_claim) == (False, True, None)
    assert (row.root_causes_hit, row.root_causes) == ((2,), 3)
    failed = replace(grade, error="UnusableReplyError: x")
    ungraded = sweep.sweep_row(SLOWDOWNS[1], produced, failed, 0.03)
    assert (ungraded.hit_at_1, ungraded.hit_at_5) == (None, None)
    text = sweep.render_sweep([row, ungraded], [])
    assert "0/1 (0.0%) | 1/1 (100.0%)" in text  # the ungraded row is not a miss
    assert "| 1 |" in text.splitlines()[-1]  # one ungraded slowdown, reported
    assert row.n_hypotheses == 2 and row.thinking_tokens == 50
    big = sweep.sweep_row(CONTROLS[0], produced, None, 0.03)
    assert (big.hit_at_1, big.hit_at_5, big.big_gain_claim) == (None, None, True)
    small = replace(
        produced,
        hypotheses=tuple(
            h.model_copy(update={"expected_gain": 0.1}) for h in produced.hypotheses
        ),
    )
    assert sweep.sweep_row(CONTROLS[0], small, None, 0.0).big_gain_claim is False
    record = json.loads(json_line(row.record()))
    assert record["experiment"] == "E3-sweep" and record["arm"] == row.arm


def test_cache_probe_reads_cache_read_input_tokens(dry: Path) -> None:
    second = {**USAGE, "cache_read_input_tokens": 15000}
    first = {**USAGE, "cache_creation_input_tokens": 15000}
    wire = Wire(_answer, usages=[first, second])
    run = wire.run(cap=sweep.CACHE_PROBE_CAP_USD)
    probe = sweep.cache_probe(run, CORPUS[0])
    one, two = wire.bodies
    assert one["system"] == two["system"] and one["model"] == two["model"] == SONNET
    assert "set-membership-test" in one["system"][0]["text"]  # the whole playbook
    assert (probe.first_cache_write, probe.second_cache_read) == (15000, 15000)
    assert probe.hit and probe.answered
    assert "cache hit\\: yes" in sweep.render_sweep([], [probe])


# ---------------------------------------------------------------------------
# The recorded sweep (LIVE_SWEEP_RECORD=1): hand-label and replay material
# ---------------------------------------------------------------------------

ONE_ARM = {sweep.ARMS_ENV: "sonnet-5-5-medium"}
KEY = "sk-ant-api03-" + "k" * 24  # key-shaped: the redaction must catch it


def _token_free(bodies: Sequence[Json]) -> list[str]:
    """The bodies with each request's fresh boundary token blanked."""
    return [
        re.sub(r"\b[0-9a-f]{16}\b", "TOKEN", json.dumps(b, sort_keys=True))
        for b in bodies
    ]


def _recorded(facts: RepoFacts, reply: str) -> sweep.Generated:
    run = Wire(lambda _body: reply).run()
    plan = replace(sweep.sweep_plan(ONE_ARM), record=True)
    return sweep.sweep_generate(plan, plan.arms[0], run, Budget(5.0), facts)


def test_the_sweep_record_flag_is_strict_and_off_by_default() -> None:
    assert sweep.RECORD_ENV == "LIVE_SWEEP_RECORD"
    assert sweep.sweep_plan({}).record is False
    assert sweep.sweep_plan({sweep.RECORD_ENV: "0"}).record is False
    assert sweep.sweep_plan({sweep.RECORD_ENV: "1"}).record is True
    for value in ("yes", "true", " 1", "2"):
        with pytest.raises(ValueError, match=sweep.RECORD_ENV):
            sweep.sweep_plan({sweep.RECORD_ENV: value})


def test_the_one_arm_recorded_sweep_needs_the_sum_of_its_caps() -> None:
    plan = sweep.sweep_plan({**ONE_ARM, sweep.RECORD_ENV: "1"})
    assert [a.label for a in plan.arms] == ["sonnet-5-5-medium"]
    assert plan.record and not plan.fable
    phase = _worst(UNDERSTAND_PROMPT_BOUND, settings.UNDERSTAND_MAX_TOKENS, (SONNET,))
    arm = _worst(BLIND_PROMPT_BOUND, GENERATE_MAX_TOKENS, (SONNET,))
    grading = _worst(
        grader.GRADER_PROMPT_BOUND, grader.GRADER_MAX_TOKENS, (grader.GRADER_MODEL,)
    )
    for repo in sweep.SWEEP_REPOS:
        _rounded(
            phase + arm + (0 if repo.kind == "control" else grading), plan.cap_for(repo)
        )
    need = sum(plan.cap_for(r) for r in sweep.SWEEP_REPOS) + sweep.CACHE_PROBE_CAP_USD
    assert sweep.sweep_need(plan) == pytest.approx(need)
    assert sweep.sweep_need(plan) == pytest.approx(SWEEP_RECORD_NEED)
    # recording sends no request of its own: the flag leaves every cap alone
    plain = replace(plan, record=False)
    assert sweep.sweep_need(plain) == sweep.sweep_need(plan)
    assert all(plain.cap_for(r) == plan.cap_for(r) for r in sweep.SWEEP_REPOS)
    assert SWEEP_RECORD_NEED <= CAP_CEILING_USD


def test_recording_sends_exactly_the_requests_of_the_plain_sweep(
    dry: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    facts = _facts(dry)
    repo = SLOWDOWNS[0]
    patches = grader.reference_patches(repo)
    plain_plan = sweep.sweep_plan(ONE_ARM)
    seen: list[tuple[sweep.Generated, Wire, LiveRun]] = []
    for plan in (plain_plan, replace(plain_plan, record=True)):
        wire = Wire(_answer)
        run = wire.run()
        budget = Budget(run.cap_usd)
        made = sweep.sweep_generate(plan, plan.arms[0], run, budget, facts)
        assert sweep.grade_arm(run, budget, repo, patches, made.result) is not None
        check_calls(run, budget, [made.result], answered=1)
        seen.append((made, wire, run))
    (plain, plain_wire, plain_run), (recorded, wire, run) = seen
    assert plain.replies == () and recorded.replies == (_ideas(),)
    assert len(wire.bodies) == len(plain_wire.bodies) == 2  # generate, grade
    assert _token_free(wire.bodies) == _token_free(plain_wire.bodies)
    assert _token_free(wire.counted) == _token_free(plain_wire.counted)
    assert len(run.records) == len(plain_run.records) == 2
    assert run.spent_usd == pytest.approx(plain_run.spent_usd)
    titles = [h.title for h in recorded.result.hypotheses]
    assert titles == [h.title for h in plain.result.hypotheses]
    # with the flag off the sweep calls generate_arm itself, unchanged
    calls: list[tuple[object, ...]] = []

    def fake(*args: object, **kwargs: object) -> ArmResult:
        calls.append((*args, kwargs))
        return plain.result

    monkeypatch.setattr(sweep, "generate_arm", fake)
    budget = Budget(1.0)
    again = sweep.sweep_generate(plain_plan, plain_plan.arms[0], run, budget, facts)
    assert again == sweep.Generated(plain.result)
    assert calls == [
        (plain_plan.arms[0], run, budget, facts, {"n": sweep.SWEEP_N, "base": settings})
    ]


def test_a_recorded_trace_keeps_each_idea_its_grade_and_the_redacted_reply(
    dry: Path,
) -> None:
    facts = _facts(dry)
    items = [
        _item(f"idea {KEY}"),
        {**_item("b"), "change_summary": "s" * 590},
        _item("c"),
    ]
    reply = json.dumps({"hypotheses": items})
    made = _recorded(facts, reply)
    repo = SLOWDOWNS[0]  # tagfilter: one reference part
    patches = grader.reference_patches(repo)
    graded = grader.Grade(
        hits=(True, False, None),
        cost_usd=0.01,
        answered=True,
        error=None,
        causes=(1, None, None),
        parts=1,
    )
    trace = sweep.sweep_trace(repo, made, graded, patches, facts.hotspots)
    first, second, third = trace.hypotheses
    assert (first.index, first.grader, first.part) == (1, "hit", 1)
    assert KEY not in first.title and "[redacted]" in first.title
    assert first.hotspots == ("blockhash/core.py:digest",)
    assert (first.change_class, first.expected_gain) == ("efficiency", 0.5)
    assert first.rationale == redact_keys(made.result.hypotheses[0].rationale)
    assert KEY not in first.rationale
    assert len(second.rationale) == sweep.RATIONALE_CHARS
    assert (second.index, second.grader, second.part) == (2, "miss", None)
    assert (third.grader, third.part) == ("ungraded", None)
    text = "".join(trace.reply_chunks)
    assert text == redact_keys(reply) and KEY not in text
    assert all(len(chunk) <= corpus.JSON_TEXT_MAX for chunk in trace.reply_chunks)
    assert (trace.reply_chars, trace.reply_truncated, trace.replies) == (
        len(text),
        False,
        1,
    )
    (part,) = trace.reference_parts
    assert (part.part, part.name, part.files) == (
        1,
        "tagfilter.patch",
        ("tagfilter/core.py",),
    )
    assert part.symbols == ("matches", "count_by_kind")
    assert (part.removed, part.added) == (2, 3)
    assert part.removed_lines == (
        "def matches(tags: list[str], allowed: list[str]) -> bool:",
        "if matches(tags, allowed):",
    )
    # the JSON line keeps the whole reply: no chunk is cut by the sink's cap
    row = sweep.sweep_row(repo, made.result, graded, 0.03)
    assert not set(row.record()) & set(trace.record())
    data = json.loads(json_line({**row.record(), **trace.record()}))
    assert "".join(data["reply_chunks"]) == text
    assert data["hypotheses"][0]["grader"] == "hit"
    # a failed grade leaves every idea ungraded; a control is never graded
    failed = replace(graded, error="UnusableReplyError: x", hits=(None,) * 3)
    trace = sweep.sweep_trace(repo, made, failed, patches, facts.hotspots)
    assert {h.grader for h in trace.hypotheses} == {"ungraded"}
    trace = sweep.sweep_trace(CONTROLS[0], made, None, (), facts.hotspots)
    assert {h.grader for h in trace.hypotheses} == {"control"}
    assert trace.reference_parts == ()
    # a reply longer than the cap is cut, and says so
    long = _recorded(facts, reply + " " * sweep.REPLY_CHARS)
    trace = sweep.sweep_trace(repo, long, graded, patches, facts.hotspots)
    assert trace.reply_truncated
    assert trace.reply_chars == len(redact_keys(reply)) + sweep.REPLY_CHARS
    assert len("".join(trace.reply_chunks)) == sweep.REPLY_CHARS
    # an unusable reply is kept too (an eval replays it), with no idea
    broken = _recorded(facts, f"not json {KEY}")
    assert broken.result.error is not None and broken.result.hypotheses == ()
    trace = sweep.sweep_trace(repo, broken, graded, patches, facts.hotspots)
    assert trace.reply_chunks == ("not json [redacted]",) and trace.hypotheses == ()


def _grade(*hits: bool) -> grader.Grade:
    return grader.Grade(
        hits=hits,
        cost_usd=0.01,
        answered=True,
        error=None,
        causes=tuple(1 if h else None for h in hits),
        parts=1,
        reply='{"grades": []}',
    )


def test_corpus_v2_is_graded_on_its_reference_fix_and_a_decoy_is_a_control(
    dry: Path,
) -> None:
    """L4 sweeps v1 + v2: a v2 slowdown is graded against its own reference
    fix (never the textbook idea beside it), a decoy is a control (no grade,
    a control's cap, its big-gain claim recorded), and both record and
    replay as the v1 rows do."""
    assert len(V2_SLOWDOWNS) == 10 and len(DECOYS) == 2
    one = sweep.sweep_plan(ONE_ARM)
    for repo in V2_SLOWDOWNS:
        patches = grader.reference_patches(repo)
        assert [p.name for p in patches] == [f"{repo.name}.patch"], repo.name
        assert patches[0].text == repo.solution.read_text(encoding="utf-8")
        assert one.cap_for(repo) == one.cap_for(SLOWDOWNS[0]), repo.name
    for repo in DECOYS:
        assert (repo.kind, repo.expected) == ("control", "none")
        assert grader.reference_patches(repo) == ()
        assert one.cap_for(repo) == one.cap_for(CONTROLS[0]), repo.name
    produced = _generated(dry, ["a", "b"])  # each claims a 50 % gain
    decoy = sweep.sweep_row(DECOYS[0], produced, None, 0.03)
    assert (decoy.kind, decoy.category, decoy.big_gain_claim) == (
        "control",
        "decoy",
        True,
    )
    assert (decoy.hit_at_1, decoy.hit_at_5, decoy.root_causes) == (None, None, 0)
    slow = sweep.sweep_row(V2_SLOWDOWNS[0], produced, _grade(False, True), 0.03)
    assert (slow.category, slow.hit_at_1, slow.hit_at_5) == (
        V2_SLOWDOWNS[0].category,
        False,
        True,
    )
    # the recorded lines replay: a decoy as a control, a v2 slowdown by its grade
    facts = _facts(dry)
    made = _recorded(facts, json.dumps({"hypotheses": [_item("a")]}))
    trace = sweep.sweep_trace(DECOYS[0], made, None, (), facts.hotspots)
    assert {h.grader for h in trace.hypotheses} == {"control"}
    assert sweep.reference_notes(DECOYS[0].name, trace.reference_parts) == [
        f"SWEEP {DECOYS[0].name} ref: none (a control, not graded)"
    ]
    row = sweep.sweep_row(DECOYS[0], made.result, None, 0.0)
    case = sweep.eval_case(json.loads(json_line({**row.record(), **trace.record()})))
    assert (case.repo, case.kind, case.labels, case.grader_reply) == (
        DECOYS[0].name,
        "control",
        {},
        None,
    )
    repo = V2_SLOWDOWNS[0]
    patches = grader.reference_patches(repo)
    graded = _grade(True)
    trace = sweep.sweep_trace(repo, made, graded, patches, facts.hotspots)
    (part,) = trace.reference_parts
    assert part.name == f"{repo.name}.patch" and part.files and part.symbols
    row = sweep.sweep_row(repo, made.result, graded, 0.0)
    case = sweep.eval_case(json.loads(json_line({**row.record(), **trace.record()})))
    assert case.kind == "slowdown" and case.grader_reply == graded.reply
    assert [(k, v.hit, v.part) for k, v in case.labels.items()] == [("a", True, 1)]


def test_the_sweep_summary_reports_each_category_and_corpus_v2_pooled(
    dry: Path,
) -> None:
    """L4's v2 pre-check is blind hit@1 on corpus v2: the summary gives each
    arm a line per category and one for v2's slowdowns and decoys pooled."""
    produced = _generated(dry, ["a"])
    deep = next(r for r in V2_SLOWDOWNS if r.category == "deep")
    small = next(r for r in V2_SLOWDOWNS if r.category == "small")
    rows = [
        sweep.sweep_row(SLOWDOWNS[0], produced, _grade(True), 0.0),
        sweep.sweep_row(HARD_CORPUS[0], produced, _grade(True), 0.0),
        sweep.sweep_row(deep, produced, _grade(True), 0.0),
        sweep.sweep_row(small, produced, _grade(False), 0.0),
        sweep.sweep_row(DECOYS[0], produced, None, 0.0),
    ]
    other = sweep.sweep_row(deep, replace(produced, arm=sweep.ARMS[1]), None, 0.0)
    text = sweep.render_sweep([*rows, other], [])
    lines = text.splitlines()
    head = lines.index(
        "| arm | set | hit at 1 rate | hit at 5 rate | cost per repo USD "
        "| cost per hit USD | control big-gain claims | ungraded slowdowns |"
    )
    arm, cost = sweep.ARMS[0].label, f"{produced.cost_usd:.4f}"
    twice = f"{2 * produced.cost_usd:.4f}"  # two graded v2 slowdowns, one hit
    one = "1/1 (100.0%)"
    assert lines[head + 2 : head + 9] == [
        cells([arm, "single", one, one, cost, cost, "0/0 (n/a)", 0]),
        cells([arm, HARD_CORPUS[0].category, one, one, cost, cost, "0/0 (n/a)", 0]),
        cells([arm, "deep", one, one, cost, cost, "0/0 (n/a)", 0]),
        cells([arm, "small", "0/1 (0.0%)", "0/1 (0.0%)", cost, "n/a", "0/0 (n/a)", 0]),
        cells([arm, "decoy", "0/0 (n/a)", "0/0 (n/a)", cost, "n/a", one, 0]),
        cells([arm, "corpus v2", "1/2 (50.0%)", "1/2 (50.0%)", cost, twice, one, 0]),
        cells(
            [sweep.ARMS[1].label, "deep", "0/0 (n/a)", "0/0 (n/a)", cost, "n/a"]
            + ["0/0 (n/a)", 1]
        ),
    ]
    assert lines[head + 9] == cells(
        [sweep.ARMS[1].label, "corpus v2", "0/0 (n/a)", "0/0 (n/a)", cost, "n/a"]
        + ["0/0 (n/a)", 1]
    )
    # v1 alone (no v2 row): the categories, no pooled v2 line
    alone = sweep.render_sweep(rows[:2], [])
    assert "corpus v2" not in alone and f"| {arm} | single |" in alone


def test_reference_parts_summarise_every_part_the_grader_numbers() -> None:
    for repo in (r for r in sweep.SWEEP_REPOS if r.kind != "control"):
        patches = grader.reference_patches(repo)
        parts = sweep.reference_parts(patches)
        assert [p.part for p in parts] == list(range(1, len(patches) + 1))
        for part, patch in zip(parts, patches, strict=True):
            assert part.name == patch.name and part.files, repo.name
            assert part.removed_lines or part.added_lines, repo.name
            assert part.symbols, repo.name  # every fix sits in a def or class
            assert all(f"b/{f}" in patch.text for f in part.files)
    # an add-only fix: a changed decorator belongs to the def it decorates
    (stairs,) = sweep.reference_parts(
        grader.reference_patches(next(r for r in SLOWDOWNS if r.name == "stairways"))
    )
    assert (stairs.removed, stairs.added, stairs.symbols) == (0, 3, ("ways",))
    assert stairs.added_lines == ("import functools", "@functools.cache")
    assert sweep.reference_notes("stairways", [stairs]) == [
        "SWEEP stairways ref 1/1: stairways/core.py ways -0+3 | "
        "+ import functools / @functools.cache"
    ]
    multi = next(r for r in HARD_CORPUS if r.name == "deliveryround")
    first, second, third = sweep.reference_parts(grader.reference_patches(multi))
    assert first.symbols == ("main",) and first.files == ("deliveryround/main.py",)
    assert "a, b = find_stop(stops, start), find_stop(stops, end)" in (
        first.removed_lines
    )
    assert second.symbols == ("distance_so_far",)
    assert third.symbols == ("pending_views",)
    assert third.removed_lines == ("pending = sorted([*pending, offer])",)
    added_only = grader.ReferencePatch(
        "x.patch",
        "--- a/x.py\n+++ b/x.py\n@@ -1,2 +1,3 @@ class Box:\n     def get(self):\n"
        "+        cache = {}\n         return 1\n",
    )
    (part,) = sweep.reference_parts([added_only])
    assert (part.removed, part.added, part.symbols) == (0, 1, ("get",))
    assert part.removed_lines == () and part.added_lines == ("cache = {}",)


def test_the_recorded_sweep_notes_each_idea_and_each_reference_part_once(
    dry: Path,
) -> None:
    facts = _facts(dry)
    title = "t" * 120  # the generator's longest title
    made = _recorded(
        facts, json.dumps({"hypotheses": [_item("first idea"), _item(title)]})
    )
    graded = grader.Grade(
        hits=(True, False),
        cost_usd=0.01,
        answered=True,
        error=None,
        causes=(1, None),
        parts=1,
    )
    results = dry / "results.jsonl"
    plan = sweep.sweep_plan({**ONE_ARM, sweep.RECORD_ENV: "1"})
    recorder = sweep.SweepRecorder(
        plan, ResultsSink({corpus.RESULTS_ENV: str(results)})
    )
    run = LiveRun("dry", 1.0, wire=httpx2.MockTransport(_no_wire))
    repo = SLOWDOWNS[0]
    patches = grader.reference_patches(repo)
    row = sweep.sweep_row(repo, made.result, graded, 0.03)
    (trace,) = sweep.sweep_traces(plan, repo, [made], [graded], patches, facts.hotspots)
    recorder.record([row], run, [trace])
    recorder.record([row], run, [trace])  # a second run of the repo (Fable)
    arm = "sonnet-5-5-medium"
    ref, plain, one, two, again, *rest = run.notes
    assert ref.startswith(
        "SWEEP tagfilter ref 1/1: tagfilter/core.py matches, count_by_kind -2+3 | "
        "def matches(tags: list[str], allowed: list[str]) -> bool: / "
        "if matches(tags, allowed):"
    )
    assert plain.startswith(f"sweep tagfilter {arm}: 2 hypotheses")
    assert one == f"SWEEP tagfilter {arm} #1: first idea | grader: hit parts 1"
    # the longest corpus name, arm label and title still fit whole
    assert two == f"SWEEP tagfilter {arm} #2: {title} | grader: miss parts none"
    assert (again, rest) == (plain, [one, two])  # the reference is noted once
    assert sweep.NOTE_CHARS == _CELL_MAX
    for note in run.notes:  # the cost table never cuts a note
        assert len(note) <= sweep.NOTE_CHARS
        assert _cell(note).count("…") == note.count("…")
    longest = max((*sweep.SWEEP_REPOS,), key=lambda r: len(r.name)).name
    widest = max((*sweep.ARMS, sweep.FABLE_ARM), key=lambda a: len(a.label)).label
    head = f"SWEEP {longest} {widest} #{sweep.SWEEP_N}: {title}"
    assert len(head + " | grader: ungraded parts none") <= sweep.NOTE_CHARS
    # a name past any corpus one: the title gives way, the verdict stays
    cut = sweep.hypothesis_notes("r" * 60, arm, trace, None)[1]
    assert len(cut) == sweep.NOTE_CHARS
    assert cut.endswith("… | grader: miss parts none")
    lines = [json.loads(x) for x in results.read_text().splitlines()]
    assert [x["hypotheses"][1]["grader"] for x in lines] == ["miss", "miss"]
    # a multi-part reference: one note per part; a control: one note, no parts
    multi = next(r for r in HARD_CORPUS if r.name == "deliveryround")
    notes = sweep.reference_notes(
        multi.name, sweep.reference_parts(grader.reference_patches(multi))
    )
    assert [n.split(":", 1)[0] for n in notes] == [
        f"SWEEP deliveryround ref {k}/3" for k in (1, 2, 3)
    ]
    assert sweep.reference_notes("blockhash", ()) == [
        "SWEEP blockhash ref: none (a control, not graded)"
    ]
    control = sweep.sweep_trace(CONTROLS[0], made, None, (), facts.hotspots)
    lines_of = sweep.hypothesis_notes("blockhash", arm, control, None)
    assert lines_of[0].endswith("| grader: control parts none")
    failed = replace(made, result=replace(made.result, hypotheses=(), error="E: x"))
    empty = sweep.sweep_trace(repo, failed, None, patches, facts.hotspots)
    assert sweep.hypothesis_notes("tagfilter", arm, empty, f"E: {KEY}") == [
        f"SWEEP tagfilter {arm}: no hypotheses | E: [redacted]"
    ]


def test_the_plain_sweep_records_and_notes_exactly_as_before(dry: Path) -> None:
    results = dry / "results.jsonl"
    plan = sweep.sweep_plan(ONE_ARM)
    recorder = sweep.SweepRecorder(
        plan, ResultsSink({corpus.RESULTS_ENV: str(results)})
    )
    run = LiveRun("dry", 1.0, wire=httpx2.MockTransport(_no_wire))
    produced = _generated(dry, ["a", "b"])
    row = sweep.sweep_row(SLOWDOWNS[0], produced, None, 0.0)
    made = sweep.Generated(produced)
    patches = grader.reference_patches(SLOWDOWNS[0])
    traces = sweep.sweep_traces(
        plan, SLOWDOWNS[0], [made], [None], patches, _facts(dry).hotspots
    )
    assert traces == []
    recorder.record([row], run, traces)
    recorder.record([row], run)
    assert (
        run.notes == [f"sweep {row.repo} {row.arm}: 2 hypotheses, hit@1 -, hit@5 -"] * 2
    )
    assert [json.loads(x) for x in results.read_text().splitlines()] == [
        json.loads(json_line(row.record()))
    ] * 2
    with pytest.raises(ValueError, match="trace"):
        recorder.record(
            [row, row], run, [sweep.sweep_trace(SLOWDOWNS[0], made, None, patches, ())]
        )


def test_the_live_sweep_generates_and_traces_through_the_record_switch() -> None:
    called = {
        node.func.id
        for node in ast.walk(_tree("test_sweep_live"))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert {"sweep_generate", "sweep_traces"} <= called
    assert "generate_arm" not in called  # every arm goes through the switch


def _hostile_outcome() -> CorpusOutcome:
    return replace(
        _outcome(SLOWDOWNS[0], True),
        repo="evil|name\n## injected <script>[x](https://e.example) `c` @here",
        guard="breach: AssertionError: x\n| forged | row |",
    )


def _check_inert(text: str) -> None:
    body = text.split("\n", 1)[1]
    assert "<script>" not in body and "\n## injected" not in body
    assert "\n| forged" not in body
    assert not re.search(r"(?<!\\)[\[\]`@]", body)  # no live link, code or mention
    assert "evil\\|name" in body


def test_summaries_sanitise_hostile_text_like_the_corpus_summary(dry: Path) -> None:
    hostile = _hostile_outcome().repo
    produced = replace(
        _generated(dry, ["a"]), error="UnusableReplyError: <img src=x> | [l](u)"
    )
    row = replace(sweep.sweep_row(SLOWDOWNS[0], produced, None, 0.0), repo=hostile)
    _check_inert(sweep.render_sweep([row], []))
    ab_row = replace(_ab_rows(dry)[0], repo=hostile, guard=_hostile_outcome().guard)
    _check_inert(ab.render_ab([ab_row]))
    first = _hostile_outcome()
    escalation = esc.EscalationRow(first.repo, "slowdown", first, None)
    _check_inert(esc.render_escalation([escalation]))


def test_results_lines_are_capped_json_and_a_relative_path_is_refused(
    tmp_path: Path,
) -> None:
    line = json_line({"a": "x" * 2000, "b": float("nan"), "c": ("y" * 900,)})
    data = json.loads(line)
    assert len(data["a"]) == corpus.JSON_TEXT_MAX and data["b"] is None
    assert len(data["c"][0]) == corpus.JSON_TEXT_MAX
    with pytest.raises(ValueError, match="absolute"):
        ResultsSink({corpus.RESULTS_ENV: "results.jsonl"})
    with pytest.raises(ValueError, match="no directory"):
        ResultsSink({corpus.RESULTS_ENV: str(tmp_path / "missing" / "r.jsonl")})
    target = tmp_path / "r.jsonl"
    sink = ResultsSink({corpus.RESULTS_ENV: str(target)})
    sink.write({"k": 1})
    sink.write({"k": 2})
    assert [json.loads(x)["k"] for x in target.read_text().splitlines()] == [1, 2]
    ResultsSink({}).write({"k": 3})  # unset: nothing written


def test_run_engine_records_then_reraises_a_breach(
    dry: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = LiveRun("dry", 1.0, wire=httpx2.MockTransport(_no_wire))
    loop = corpus.start_loop(SLOWDOWNS[0], run, dry, REQUIRED)
    state = initial_state(loop.project, [loop.workload], [], guardrails(loop.project))
    failed = EngineRunResult("r", "failed", state, None)
    monkeypatch.setattr(corpus.Loop, "run", lambda self: failed)
    recorded: list[tuple[CorpusOutcome, EngineRunResult | None]] = []
    with pytest.raises(AssertionError):
        run_engine(
            loop,
            run,
            REQUIRED,
            model=SONNET,
            record=lambda o, r: recorded.append((o, r)),
        )
    ((outcome, handed),) = recorded
    assert handed is failed  # the recorder sees the state, breach or not
    assert outcome.guard.startswith("breach: AssertionError")
    assert outcome.engine_model == SONNET and outcome.status == "failed"


# ---------------------------------------------------------------------------
# The live modules: marked, one process, and their suite needs
# ---------------------------------------------------------------------------

LIVE_MODULES = ("test_sweep_live", "test_ab_live", "test_escalation_live")


def _tree(stem: str) -> ast.Module:
    return ast.parse((LIVE_DIR / f"{stem}.py").read_text(encoding="utf-8"))


def _live_args(stem: str) -> set[str]:
    return {
        ast.unparse(node.args[0])
        for node in ast.walk(_tree(stem))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "live"
    }


def test_every_live_module_is_marked_live_and_refused_under_xdist() -> None:
    for stem in LIVE_MODULES:
        tree = _tree(stem)
        marks = [
            ast.unparse(node.value)
            for node in tree.body
            if isinstance(node, ast.Assign)
            and [ast.unparse(t) for t in node.targets] == ["pytestmark"]
        ]
        assert marks == ["pytest.mark.live"], stem
        tests = [
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
        ]
        assert tests, stem
        for test in tests:  # the live fixture admits the spend and refuses xdist
            assert "live" in [a.arg for a in test.args.args], (stem, test.name)
    assert xdist_refusal({"PYTEST_XDIST_WORKER": "gw0"}) is not None


def _worst(bound: int, max_tokens: int, models: Sequence[str]) -> float:
    """What ``call()`` checks for a request whose byte-bound count is at most
    ``bound``: the count plus its margin plus the allowance, over ``models``."""
    prompt = bound + count_margin(bound) + PROMPT_ALLOWANCE_TOKENS
    return preflight_estimate(prompt, max_tokens, models, settings.MODEL_PRICING)


def _rounded(total: float, cap: float) -> None:
    assert total <= cap < total + 0.05 + 1e-9, (total, cap)


def test_each_shared_run_cap_holds_every_worst_case_request() -> None:
    """No request in a run can be refused: each run's cap is the sum of the
    worst cases of every request it may send, rounded up to 0.05 USD."""
    phase = _worst(UNDERSTAND_PROMPT_BOUND, settings.UNDERSTAND_MAX_TOKENS, (SONNET,))
    _rounded(phase, PHASE_ONE_CAP_USD)
    grading = _worst(
        grader.GRADER_PROMPT_BOUND, grader.GRADER_MAX_TOKENS, (grader.GRADER_MODEL,)
    )
    plan = sweep.sweep_plan({})
    for repo in sweep.SWEEP_REPOS:
        total = phase + sum(
            _worst(BLIND_PROMPT_BOUND, GENERATE_MAX_TOKENS, (a.model,))
            for a in plan.arms
        )
        if repo.kind != "control":
            total += len(plan.arms) * grading
        _rounded(total, plan.cap_for(repo))
    one = sweep.sweep_plan({sweep.ARMS_ENV: "sonnet-5-5-medium"})
    assert (
        one.cap_for(SLOWDOWNS[0])
        < plan.cap_for(CONTROLS[0])
        < plan.cap_for(SLOWDOWNS[0])
    )
    fable = _worst(BLIND_PROMPT_BOUND, GENERATE_MAX_TOKENS, (FABLE,)) + grading
    _rounded(fable, sweep.FABLE_RUN_CAP_USD)
    probe = 2 * _worst(PROBE_PROMPT_BOUND, GENERATE_MAX_TOKENS, (SONNET,))
    _rounded(probe, sweep.CACHE_PROBE_CAP_USD)
    generation = (
        phase
        + _worst(BLIND_PROMPT_BOUND, ab.AB_GENERATE_MAX_TOKENS, (SONNET,))
        + _worst(MATCH_PROMPT_BOUND, MATCH_MAX_TOKENS, (SONNET,))
        + _worst(CARDS_PROMPT_BOUND, ab.AB_GENERATE_MAX_TOKENS, (SONNET,))
    )
    _rounded(generation, ab.AB_GEN_CAP_USD)
    # E8a: a whole run has no prompt bound (the editor's conversation grows),
    # so its worst case is the one measured on U22's Opus runs (the sum of
    # every request's worst case), scaled from U22's chain to the pass's.
    u22 = esc.U22_WORST_PER_RUN_USD
    assert u22 == pytest.approx(49.65 / 15)
    reference = _worst(
        esc.EDITOR_PROMPT_REFERENCE, settings.EDITOR_MAX_TOKENS, esc.U22_CHAIN
    )
    derived = {}
    for name, cfg in (
        ("first", esc.first_settings(settings)),
        ("escalated", esc.escalated_settings(settings)),
    ):
        mine = _worst(esc.EDITOR_PROMPT_REFERENCE, cfg.EDITOR_MAX_TOKENS, chain(cfg))
        derived[name] = u22 * mine / reference
    _rounded(derived["first"], esc.FIRST_CAP_USD)
    # Opus at high effort is no U22 run: the escalated pass gets twice its
    # derived cap (the scaled figure, rounded up, doubled).
    assert esc.ESCALATED_CAP_USD == 2 * esc.pass_cap(esc.escalated_settings(settings))
    assert esc.ESCALATED_CAP_USD >= 2 * derived["escalated"]


def test_each_suite_needs_the_sum_of_its_caps() -> None:
    assert _live_args("test_sweep_live") == {
        "sweep.plan.cap_for(repo)",
        "FABLE_RUN_CAP_USD",
        "CACHE_PROBE_CAP_USD",
    }
    assert _live_args("test_ab_live") == {"AB_GEN_CAP_USD", "ab.plan.run_cap"}
    assert _live_args("test_escalation_live") == {"cap"}
    assert sweep.SWEEP_REPOS == (*CORPUS, *HARD_CORPUS, *DISCOVERY_CORPUS)
    assert len({r.name for r in sweep.SWEEP_REPOS}) == len(sweep.SWEEP_REPOS) == 37
    assert sweep.FABLE_REPOS == SLOWDOWNS  # Fable stays on the 12 v1 slowdowns
    plan = sweep.sweep_plan({})
    need = sum(plan.cap_for(r) for r in sweep.SWEEP_REPOS) + sweep.CACHE_PROBE_CAP_USD
    assert sweep.sweep_need(plan) == pytest.approx(need) == pytest.approx(SWEEP_NEED)
    with_fable = sweep.sweep_need(sweep.sweep_plan({sweep.FABLE_ENV: "1"}))
    fable = len(SLOWDOWNS) * sweep.FABLE_RUN_CAP_USD
    assert with_fable == pytest.approx(need + fable) == pytest.approx(SWEEP_FABLE_NEED)
    reps = ab.ab_plan({})
    expected = reps.reps * len(ab.AB_REPOS) * (ab.AB_GEN_CAP_USD + 2 * reps.run_cap)
    assert ab.ab_need(reps) == pytest.approx(expected) == pytest.approx(AB_NEED)
    first = len(CORPUS) * esc.FIRST_CAP_USD
    worst = first + len(SLOWDOWNS) * esc.ESCALATED_CAP_USD
    assert esc.escalation_need() == pytest.approx(worst) == pytest.approx(ESC_NEED)
    for need_usd in (SWEEP_NEED, SWEEP_FABLE_NEED, AB_NEED, ESC_NEED):
        assert need_usd <= CAP_CEILING_USD


@pytest.mark.parametrize(
    "repo", (*CORPUS, *HARD_CORPUS, *DISCOVERY_CORPUS), ids=lambda r: r.name
)
def test_each_prompt_bound_holds_on_every_corpus_repository(
    repo: CorpusRepo, tmp_path: Path
) -> None:
    """The bounds the caps assume, against the real requests built with the
    largest facts the engine lets this repository produce (30 hotspots on
    its longest-named functions, every understanding field at its cap). The
    count is the byte bound plus the allowance: no token covers less than a
    byte, so the API's count cannot exceed it."""
    facts = _largest_facts(repo)
    playbook = load_playbook()
    cards = sorted(playbook, key=lambda t: -len(t.model_dump_json()))[: ab.AB_K]
    measured = {
        "blind": _count(lambda t: _generate(t, facts, ())),
        "cards": _count(lambda t: _generate(t, facts, cards)),
        "probe": _count(
            lambda t: _generate(
                t, replace(facts, understanding=None, hotspots=()), playbook
            )
        ),
        "match": _count(
            lambda t: match_techniques(
                t,
                Budget(9.0),
                understanding=facts.understanding,
                hotspots=facts.hotspots,
                techniques=playbook,
                sleep=_no_sleep,
            )
        ),
    }
    assert measured["blind"] <= BLIND_PROMPT_BOUND
    assert measured["cards"] <= CARDS_PROMPT_BOUND
    assert measured["probe"] <= PROBE_PROMPT_BOUND
    assert measured["match"] <= MATCH_PROMPT_BOUND
    user = make_repo(repo.path, Path(os.path.realpath(tmp_path)) / "user")
    project = repo.project(user.path)
    scripted = ScriptedTransport([_reply("{}")])
    with contextlib.suppress(
        Exception
    ):  # the reply is unusable: only the request counts
        ClaudeUnderstander(scripted, sleep=_no_sleep).understand(
            project, [repo.workload(project)], commit=user.base, budget=Budget(9.0)
        )
    assert scripted.count_input_tokens(scripted.requests[0]) <= UNDERSTAND_PROMPT_BOUND
    patches = grader.reference_patches(repo)
    if patches:
        widest = [_widest_hypothesis(facts) for _ in range(sweep.SWEEP_N)]
        request = grader.grader_request(repo, patches, widest)
        assert (
            ScriptedTransport([]).count_input_tokens(request)
            <= grader.GRADER_PROMPT_BOUND
        )


def _no_sleep(_seconds: float) -> None:
    return None


def _reply(text: str) -> Json:
    return {
        "id": "m",
        "type": "message",
        "role": "assistant",
        "model": SONNET,
        "content": [{"type": "text", "text": text}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }


def _count(send: Callable[[ScriptedTransport], object]) -> int:
    scripted = ScriptedTransport([_reply('{"hypotheses": [], "matches": []}')])
    with contextlib.suppress(
        Exception
    ):  # the reply is unusable: only the request counts
        send(scripted)
    return scripted.count_input_tokens(scripted.requests[0])


def _generate(
    transport: ScriptedTransport, facts: RepoFacts, techniques: Sequence[Technique]
) -> object:
    return generate_hypotheses(
        transport,
        Budget(9.0),
        project=facts.project,
        understanding=facts.understanding,
        hotspots=facts.hotspots,
        objective=facts.objective,
        techniques=techniques,
        n=sweep.SWEEP_N,
        sleep=_no_sleep,
    )


def _largest_facts(repo: CorpusRepo) -> RepoFacts:
    project = repo.project(repo.path)
    files = sorted(p for p in repo.path.rglob("*.py") if "__pycache__" not in p.parts)
    paths = [f.relative_to(repo.path).as_posix() for f in files]
    symbols = sorted(
        (
            (path, node.name)
            for path, f in zip(paths, files, strict=True)
            for node in ast.walk(ast.parse(f.read_text(encoding="utf-8")))
            if isinstance(node, ast.FunctionDef | ast.ClassDef)
        ),
        key=lambda pair: -len(pair[0]) - len(pair[1]),
    )[:MAX_HOTSPOTS]
    spots = tuple(
        Hotspot(
            project_id=project.id,
            workload_id=new_id(),
            file_path=path,
            symbol=name,
            line_start=10_000,
            line_end=20_000,
            self_time_s=123.456789,
            total_time_s=123.456789,
            share=0.1234,
            calls=12_345_678,
        )
        for path, name in symbols
    )
    understanding = ProjectUnderstanding(
        language="python",
        summary="s" * 1500,
        entrypoints=tuple((paths * 20)[:20]),
        workload_notes={new_id(): "n" * 500},
        candidate_modules=tuple(
            CandidateModule(path=p, reason="r" * 500) for p in (paths * 10)[:10]
        ),
        served_by_model=SONNET,
    )
    objective = _facts(repo.path, repo).objective.model_copy(
        update={"project_id": project.id, "description": "minimize peak memory"}
    )
    return RepoFacts(project, understanding, spots, objective)


def _widest_hypothesis(facts: RepoFacts) -> Hypothesis:
    return Hypothesis(
        project_id=facts.project.id,
        source=HypothesisSource.novel,
        title="t" * 120,
        rationale="c" * 600 + "\nWhy it should win: " + "j" * 600,
        change_class=ChangeClass.efficiency,
        expected_gain=0.5,
        provability=0.5,
        risk=0.1,
    )


def test_the_recorders_write_lines_notes_and_one_summary(
    dry: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    results, summary = dry / "results.jsonl", dry / "summary.md"
    environ = {corpus.RESULTS_ENV: str(results), corpus.SUMMARY_ENV: str(summary)}
    run = LiveRun("dry", 1.0, wire=httpx2.MockTransport(_no_wire))
    produced = _generated(dry, ["a"])
    row = sweep.sweep_row(SLOWDOWNS[0], produced, None, 0.0)
    recorders = (
        sweep.SweepRecorder(sweep.sweep_plan({}), ResultsSink(environ)),
        ab.AbRecorder(ab.ab_plan({}), ResultsSink(environ), frozenset()),
        esc.EscalationRecorder(ResultsSink(environ)),
    )
    echoed: list[str] = []
    for recorder in recorders:
        recorder.finish(echoed.append)  # nothing recorded: no summary
    assert not summary.exists() and echoed == []
    sweep_rec, ab_rec, esc_rec = recorders
    assert isinstance(sweep_rec, sweep.SweepRecorder)
    assert isinstance(ab_rec, ab.AbRecorder)
    assert isinstance(esc_rec, esc.EscalationRecorder)
    sweep_rec.record([row], run)
    probe = sweep.Probe(SONNET, "medium", 10, 0, 0.01, True, None)
    sweep_rec.record_probe(probe, run)
    ab_rec.record(SLOWDOWNS[0], 1, "A", produced, None, run=run)
    outcome = _outcome(SLOWDOWNS[0], False)
    esc_rec.record_pass("first", outcome, run=run)
    esc_rec.add(esc.EscalationRow(outcome.repo, "slowdown", outcome, None))
    for recorder in recorders:
        recorder.finish(echoed.append)
    kinds = [json.loads(x)["experiment"] for x in results.read_text().splitlines()]
    assert kinds == ["E3-sweep", "E3-cache-probe", "E5-ab", "E8a-escalation"]
    text = summary.read_text()
    for title in ("(E3)", "(E5)", "(E8a)"):
        assert title in text
    assert "cache hit\\: no" in text
    # each summary goes to the job summary and, line by line, to the log
    assert sum(line.endswith("written to the job summary") for line in echoed) == 3
    assert [line for line in echoed if not line.endswith("job summary")] == (
        text.splitlines()
    )
    assert len(run.notes) == 4
    echoed.clear()
    esc_rec.finish(echoed.append)  # no summary path: echoed line by line
    esc.EscalationRecorder(ResultsSink({})).finish(echoed.append)
    assert echoed[0].endswith("job summary")
    lines: list[str] = []
    recorder = esc.EscalationRecorder(ResultsSink({}))
    recorder.add(esc.EscalationRow(outcome.repo, "slowdown", outcome, outcome))
    recorder.finish(lines.append)
    assert lines[0] == "## Editor escalation (E8a)"
    for empty in (
        sweep.render_sweep([], []),
        ab.render_ab([]),
        esc.render_escalation([]),
    ):
        assert "finished" in empty


def test_grade_arm_skips_a_control_and_grades_a_slowdown(dry: Path) -> None:
    produced = _generated(dry, ["a"])
    run = Wire(_answer).run()
    budget = Budget(run.cap_usd)
    assert sweep.grade_arm(run, budget, CONTROLS[0], (), produced) is None
    patches = grader.reference_patches(SLOWDOWNS[0])
    graded = sweep.grade_arm(run, budget, SLOWDOWNS[0], patches, produced)
    assert graded is not None and graded.sent and graded.hits == (True,)


def test_thinking_tokens_are_unknown_when_a_reply_omits_them(dry: Path) -> None:
    usage = {k: v for k, v in USAGE.items() if k != "output_tokens_details"}
    run = Wire(_answer, usages=[usage]).run()
    result = generate_arm(sweep.ARMS[0], run, Budget(5.0), _facts(dry), n=5)
    assert result.answered and result.thinking_tokens is None


def test_run_engine_records_a_clean_run(
    dry: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The success path of the recording (the guards themselves are proved in
    test_corpus_guards on scripted results)."""
    run = LiveRun("dry", 1.0, wire=httpx2.MockTransport(_no_wire))
    loop = corpus.start_loop(SLOWDOWNS[0], run, dry, REQUIRED)
    state = initial_state(loop.project, [loop.workload], [], guardrails(loop.project))
    done = EngineRunResult("r", "done", state, None)
    monkeypatch.setattr(corpus.Loop, "run", lambda self: done)
    monkeypatch.setattr(discovery, "check_loop_guards", lambda *a: None)
    recorded: list[tuple[CorpusOutcome, EngineRunResult | None]] = []
    outcome = run_engine(
        loop, run, REQUIRED, model=OPUS, record=lambda o, r: recorded.append((o, r))
    )
    assert recorded == [(outcome, done)] and outcome.guard == "ok"
    assert outcome.engine_model == OPUS and outcome.status == "done"


CAP_STOP = (
    "the editor stopped (budget): the run's cost cap stopped the edit: spent "
    "0.900000 USD + estimate 0.200000 USD exceeds the cap of 1.000000 USD"
)


@pytest.mark.parametrize(
    ("exhausted", "error", "flags"),
    [
        (False, None, (False, False)),
        (True, None, (True, False)),
        (False, CAP_STOP, (False, True)),
        (False, "BudgetExceeded: recorded spend over the cap", (False, True)),
        (
            False,
            "the editor stopped (error): the Claude API is unavailable",
            (False, False),
        ),
    ],
)
def test_a_cap_bound_loss_is_told_apart_from_a_real_loss(
    dry: Path, exhausted: bool, error: str | None, flags: tuple[bool, bool]
) -> None:
    run = LiveRun("dry", 1.0, wire=httpx2.MockTransport(_no_wire))
    loop = corpus.start_loop(SLOWDOWNS[0], run, dry, REQUIRED)
    state = initial_state(loop.project, [loop.workload], [], guardrails(loop.project))
    state["budget_exhausted"] = exhausted
    state["trials"] = [
        Trial(
            hypothesis_id=loop.candidates[0].id,
            round=1,
            status=TrialStatus.failed,
            error=error,
        )
    ]
    result = EngineRunResult("r", "done", state, None)
    assert discovery.budget_flags(result) == discovery.BudgetFlags(*flags)
    assert discovery.budget_flags(None) == discovery.BudgetFlags(None, False)
    outcome = _outcome(SLOWDOWNS[0], False)
    row = ab.ab_row(SLOWDOWNS[0], 1, "A", _generated(dry, ["a"]), outcome, (), result)
    assert (row.budget_exhausted, row.trial_budget_error) == flags
    record = esc.pass_record("first", outcome, result)
    assert (record["budget_exhausted"], record["trial_budget_error"]) == flags
    none = esc.pass_record("first", outcome, None)
    assert (none["budget_exhausted"], none["trial_budget_error"]) == (None, False)
    assert "cap hit" in ab.render_ab([row])
