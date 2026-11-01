"""Wave 2 idea-pipeline contracts (N1a; spec amendment sections 3.1, 3.3, 3.4).

The settings and roles with their bounds, the retention guard (D63),
``Hypothesis.tags`` (D57), ``ViolationRule.unparsable_source`` (D62), the
Protocol's five keywords (D44), ``GenerateResult`` events and stats (D65),
``NodeContext.portfolio_rounds`` (D54) and the pipeline's own types. With
``IDEA_PIPELINE`` off every default reproduces today's engine (D43).
"""

from __future__ import annotations

import inspect
import json
import secrets
import sys
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import get_args

import httpx2
import pytest
from pydantic import ValidationError

from autonomous_ai_agents.clients.budget import Budget
from autonomous_ai_agents.clients.cost import chain
from autonomous_ai_agents.clients.transport import ScriptedTransport
from autonomous_ai_agents.common.config import (
    PORTFOLIO_ROUNDS_MAX,
    RETENTION_REQUIRED_MODELS,
    Role,
    Settings,
    role_chain,
    role_settings,
)
from autonomous_ai_agents.common.models import (
    MAX_HYPOTHESIS_TAGS,
    ChangeClass,
    Direction,
    EventLevel,
    Hotspot,
    Hypothesis,
    HypothesisSource,
    Objective,
    ObjectiveKind,
    Project,
    ProjectUnderstanding,
    ViolationRule,
    Workload,
)
from autonomous_ai_agents.execution.profiler import MAX_HOTSPOTS
from autonomous_ai_agents.optimization import idea_types
from autonomous_ai_agents.optimization.hypothesis_source import (
    ClaudeHypothesisGenerator,
)
from autonomous_ai_agents.optimization.idea_types import (
    LENS_LANES,
    MORPH_DIMENSIONS,
    Anchor,
    CodeContext,
    CodeDocument,
    FunctionSpan,
    GenerateEvent,
    IdeaCandidate,
    IdeaStats,
    Lane,
    Mechanism,
    MorphCell,
    ReviewReason,
    ReviewVerdict,
    Tier,
    Typicality,
)
from autonomous_ai_agents.optimization.sources import (
    GenerateResult,
    HypothesisGenerator,
)
from autonomous_ai_agents.orchestrator.nodes import NodeContext
from autonomous_ai_agents.research import playbook as playbook_module
from autonomous_ai_agents.research.playbook import StableTokens

# The live harness is the package ``tests/live``. Under --import-mode=importlib
# it is importable only once pytest has collected a module inside ``tests/``'s
# packages, and tests/common is collected first, so the tests directory goes
# on the path here (what the default prepend mode does for tests/conftest.py).
_TESTS = str(Path(__file__).resolve().parents[1])
if _TESTS not in sys.path:
    sys.path.insert(0, _TESTS)

from live import discovery_sweep as sweep  # noqa: E402
from live.conftest import LiveRun  # noqa: E402
from live.corpus import CORPUS, HARD_CORPUS  # noqa: E402
from live.discovery import (  # noqa: E402
    FABLE,
    SONNET,
    Arm,
    ArmResult,
    RepoFacts,
    Work,
    arm_settings,
    harness_repository,
)
from live.oss import OSS_CORPUS  # noqa: E402
from live.oss_v2 import OSS_CORPUS_V2  # noqa: E402

OPUS = "claude-opus-5-5"
ContextFactory = Callable[..., NodeContext]


def _settings(**values: object) -> Settings:
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Settings: defaults, bounds, roles
# ---------------------------------------------------------------------------


def test_the_idea_pipeline_defaults_are_the_specs() -> None:
    """
    GIVEN no environment
    WHEN the settings load
    THEN every new knob holds section 3.1's default, the pipeline is off and
         today's discovery share is unchanged (D43)
    """
    cfg = _settings()

    assert cfg.IDEA_PIPELINE is False
    assert cfg.DISCOVERY_MAX_SHARE == 0.25
    assert cfg.IDEAS_DISCOVERY_MAX_SHARE == 0.40
    assert cfg.PORTFOLIO_ROUNDS == 0
    assert (cfg.IDEAS_LANE_MODEL, cfg.IDEAS_LANE_EFFORT) == (SONNET, "medium")
    assert (cfg.IDEAS_LANE_MAX_TOKENS, cfg.IDEAS_LANE_N) == (12000, 6)
    assert cfg.IDEAS_LENSES == LENS_LANES
    assert cfg.IDEAS_LANE_WORKERS == 4
    assert (cfg.IDEAS_LEAP_MODEL, cfg.IDEAS_LEAP_EFFORT) == (OPUS, "high")
    assert (cfg.IDEAS_LEAP_MAX_TOKENS, cfg.IDEAS_LEAP_N) == (12000, 3)
    assert (cfg.IDEAS_REVIEWER_MODEL, cfg.IDEAS_REVIEWER_EFFORT) == (OPUS, "high")
    assert cfg.IDEAS_REVIEWER_MAX_TOKENS == 16000
    assert (cfg.IDEAS_REVIEW, cfg.IDEAS_REVIEW_MAX_IDEAS) == (True, 16)
    assert (cfg.IDEAS_HOT_FUNCTIONS, cfg.IDEAS_MAX_FILES) == (8, 8)
    assert cfg.IDEAS_FILE_MAX_BYTES == 24 * 1024
    assert cfg.IDEAS_CODE_MAX_BYTES == 64 * 1024
    assert cfg.IDEAS_PARSE_MAX_BYTES == 512 * 1024
    assert cfg.IDEAS_AMDAHL_MULTIPLIER == 1.0
    assert (cfg.IDEAS_PORTFOLIO_MIN, cfg.IDEAS_PORTFOLIO_MAX) == (3, 5)
    assert cfg.ALLOW_RETENTION_MODELS is False


@pytest.mark.parametrize(
    "values",
    [
        {"PORTFOLIO_ROUNDS": -1},
        {"PORTFOLIO_ROUNDS": 4},
        {"IDEAS_DISCOVERY_MAX_SHARE": 0.0},
        {"IDEAS_DISCOVERY_MAX_SHARE": 1.0},
        {"IDEAS_DISCOVERY_MAX_SHARE": float("nan")},
        {"IDEAS_DISCOVERY_MAX_SHARE": float("inf")},
        {"IDEAS_LANE_MAX_TOKENS": 0},
        {"IDEAS_LEAP_MAX_TOKENS": 0},
        {"IDEAS_REVIEWER_MAX_TOKENS": 0},
        {"IDEAS_LANE_N": 0},
        {"IDEAS_LANE_N": 11},
        {"IDEAS_LEAP_N": -1},
        {"IDEAS_LEAP_N": 6},
        {"IDEAS_LANE_WORKERS": 0},
        {"IDEAS_LANE_WORKERS": 9},
        {"IDEAS_LENSES": ()},
        {"IDEAS_LENSES": ("far", "far")},
        {"IDEAS_LENSES": ("obvious",)},
        {"IDEAS_LENSES": ("eliminate", "leap")},
        {"IDEAS_LENSES": ("sideways",)},
        {"IDEAS_REVIEW_MAX_IDEAS": 49},
        {"IDEAS_HOT_FUNCTIONS": 0},
        {"IDEAS_HOT_FUNCTIONS": 31},
        {"IDEAS_MAX_FILES": 0},
        {"IDEAS_MAX_FILES": 21},
        {"IDEAS_FILE_MAX_BYTES": 1023},
        {"IDEAS_CODE_MAX_BYTES": 24 * 1024 - 1},
        {"IDEAS_PARSE_MAX_BYTES": 24 * 1024 - 1},
        {"IDEAS_FILE_MAX_BYTES": 70 * 1024},  # past the default code budget
        {"IDEAS_AMDAHL_MULTIPLIER": 0.99},
        {"IDEAS_AMDAHL_MULTIPLIER": float("inf")},
        {"IDEAS_AMDAHL_MULTIPLIER": float("nan")},
        {"IDEAS_PORTFOLIO_MIN": 0},
        {"IDEAS_PORTFOLIO_MAX": 11},
        {"IDEAS_PORTFOLIO_MIN": 4, "IDEAS_PORTFOLIO_MAX": 3},
    ],
)
def test_out_of_range_idea_knobs_are_refused(values: dict[str, object]) -> None:
    """
    GIVEN an idea knob outside section 3.1's range (a lens list with a repeat,
          ``obvious``, ``leap`` or no lens; min above max; four portfolio
          rounds; byte caps out of order)
    WHEN the settings load
    THEN validation fails
    """
    with pytest.raises(ValidationError):
        _settings(**values)


def test_the_bounds_of_the_idea_knobs_are_accepted() -> None:
    """
    GIVEN each idea knob at the edge of its range
    WHEN the settings load
    THEN it is kept; a lens subset keeps its order; blank efforts are unset
    """
    cfg = _settings(
        PORTFOLIO_ROUNDS=PORTFOLIO_ROUNDS_MAX,
        IDEAS_LANE_N=10,
        IDEAS_LEAP_N=0,
        IDEAS_LANE_WORKERS=8,
        IDEAS_LENSES=("far", "eliminate"),
        IDEAS_REVIEW_MAX_IDEAS=48,
        IDEAS_HOT_FUNCTIONS=30,
        IDEAS_MAX_FILES=20,
        IDEAS_FILE_MAX_BYTES=1024,
        IDEAS_CODE_MAX_BYTES=1024,
        IDEAS_PARSE_MAX_BYTES=1024,
        IDEAS_AMDAHL_MULTIPLIER=1.5,
        IDEAS_PORTFOLIO_MIN=10,
        IDEAS_PORTFOLIO_MAX=10,
        IDEAS_LANE_EFFORT="",
        IDEAS_LEAP_EFFORT=" ",
        IDEAS_REVIEWER_EFFORT="",
        IDEAS_REVIEW=False,
    )

    assert cfg.PORTFOLIO_ROUNDS == PORTFOLIO_ROUNDS_MAX == 3
    assert cfg.IDEAS_LENSES == (Lane.far, Lane.eliminate)
    assert (cfg.IDEAS_LANE_EFFORT, cfg.IDEAS_LEAP_EFFORT) == (None, None)
    assert cfg.IDEAS_REVIEWER_EFFORT is None
    assert cfg.IDEAS_LEAP_N == 0 and cfg.IDEAS_REVIEW is False
    assert (cfg.IDEAS_PORTFOLIO_MIN, cfg.IDEAS_PORTFOLIO_MAX) == (10, 10)


def test_the_lenses_read_from_the_environment_as_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IDEAS_LENSES", '["recombine", "assume_less"]')
    assert Settings(_env_file=None).IDEAS_LENSES == (
        Lane.recombine,
        Lane.assume_less,
    )


def test_the_hot_function_bound_is_the_profilers_hotspot_cap() -> None:
    """D44: selection is among the hotspots the profiler emits (30 at most)."""
    assert MAX_HOTSPOTS == 30
    _settings(IDEAS_HOT_FUNCTIONS=MAX_HOTSPOTS)
    with pytest.raises(ValidationError):
        _settings(IDEAS_HOT_FUNCTIONS=MAX_HOTSPOTS + 1)


@pytest.mark.parametrize(
    ("values", "match"),
    [
        ({"IDEAS_DISCOVERY_MAX_SHARE": 0.2}, "IDEAS_DISCOVERY_MAX_SHARE"),
        ({"DISCOVERY_MAX_SHARE": 0.5}, "IDEAS_DISCOVERY_MAX_SHARE"),
        ({"IDEAS_REVIEW_MAX_IDEAS": 4}, "IDEAS_REVIEW_MAX_IDEAS"),
        ({"GENERATOR_N": 20}, "IDEAS_REVIEW_MAX_IDEAS"),
    ],
)
def test_with_the_pipeline_on_its_knobs_must_cover_todays(
    values: dict[str, object], match: str
) -> None:
    """
    GIVEN IDEA_PIPELINE on and the pipeline's share below today's, or a
          reviewer cap below GENERATOR_N (S1's survivors must all fit, D64)
    WHEN the settings load
    THEN validation fails naming the pipeline knob; with the pipeline off the
         same values load, so no setting valid today becomes invalid (D43)
    """
    with pytest.raises(ValidationError, match=match):
        _settings(IDEA_PIPELINE=True, **values)
    assert _settings(**values).IDEA_PIPELINE is False


def test_with_the_pipeline_on_the_edges_of_the_cross_checks_are_accepted() -> None:
    cfg = _settings(
        IDEA_PIPELINE=True,
        DISCOVERY_MAX_SHARE=0.3,
        IDEAS_DISCOVERY_MAX_SHARE=0.3,
        GENERATOR_N=16,
        IDEAS_REVIEW_MAX_IDEAS=16,
    )
    assert cfg.IDEA_PIPELINE is True
    assert cfg.IDEAS_DISCOVERY_MAX_SHARE == cfg.DISCOVERY_MAX_SHARE == 0.3


@pytest.mark.parametrize(
    "key", ["IDEAS_LANE_MODEL", "IDEAS_LEAP_MODEL", "IDEAS_REVIEWER_MODEL"]
)
def test_an_unpriced_pipeline_model_is_refused_once_it_may_bill(key: str) -> None:
    """
    GIVEN a pipeline role model with no MODEL_PRICING entry
    WHEN the settings load with IDEA_PIPELINE on, or the role's copy is built
    THEN validation fails naming the model; with the pipeline off the role
         bills nothing, so the base settings load (a price table valid today
         stays valid, D43)
    """
    effort = key.replace("_MODEL", "_EFFORT")  # no documented levels either
    values = {key: "claude-unpriced-1", effort: None}
    with pytest.raises(ValidationError, match="no price for claude-unpriced-1"):
        _settings(IDEA_PIPELINE=True, **values)
    base = _settings(**values)
    role = {"IDEAS_LANE_MODEL": "lane", "IDEAS_LEAP_MODEL": "leap"}.get(key, "reviewer")
    with pytest.raises(ValidationError, match="no price for claude-unpriced-1"):
        role_settings(base, role)  # type: ignore[arg-type]


def test_a_price_table_for_todays_roles_only_still_loads() -> None:
    """Today's roles priced, Opus 5.5 (the leap and reviewer default) not."""
    rate = {"input": 1.0, "output": 2.0, "cache_write": 1.25, "cache_read": 0.1}
    prices = {m: rate for m in ("claude-x-1", "claude-haiku-5-5", SONNET)}
    values = {"MODEL_PRICING": prices, "ENGINE_MODEL": "claude-x-1",
              "ENGINE_FALLBACK_MODELS": ()}  # fmt: skip
    assert _settings(**values).ENGINE_MODEL == "claude-x-1"
    with pytest.raises(ValidationError, match="claude-opus-5-5"):
        _settings(IDEA_PIPELINE=True, **values)


@pytest.mark.parametrize(
    ("values", "match"),
    [
        ({"IDEAS_LANE_EFFORT": "xhigh", "IDEAS_LANE_MODEL": "claude-opus-4-6"},
         "IDEAS_LANE_EFFORT"),
        ({"IDEAS_LEAP_EFFORT": "max", "IDEAS_LEAP_MODEL": "claude-opus-4-5"},
         "IDEAS_LEAP_EFFORT"),
        ({"IDEAS_REVIEWER_EFFORT": "xhigh", "IDEAS_REVIEWER_MODEL": "claude-opus-4-6"},
         "IDEAS_REVIEWER_EFFORT"),
    ],
)  # fmt: skip
def test_an_effort_the_role_chain_rejects_is_refused(
    values: dict[str, object], match: str
) -> None:
    """
    GIVEN a pipeline effort its role's model does not accept (or an id the
          effort docs do not list)
    WHEN the settings load
    THEN validation fails naming the setting
    """
    prices = dict(_settings().MODEL_PRICING)
    for model in ("claude-opus-4-6", "claude-opus-4-5"):
        prices[model] = prices[OPUS]
    with pytest.raises(ValidationError, match=match):
        _settings(MODEL_PRICING=prices, **values)


def test_the_three_pipeline_roles_run_alone_on_their_own_models() -> None:
    """
    GIVEN fallbacks on for the engine
    WHEN the lane, leap and reviewer chains and settings copies are built
    THEN each role is its model alone (no fallbacks), each copy's cost chain
         is its role chain, and Role names all seven roles
    """
    base = _settings(
        ENGINE_FALLBACKS=True,
        IDEAS_LANE_MODEL="claude-haiku-5-5",
        IDEAS_LEAP_MODEL=SONNET,
    )
    assert get_args(Role) == (
        "engine", "editor", "generator", "matcher", "lane", "leap", "reviewer"
    )  # fmt: skip
    expected = {"lane": ("claude-haiku-5-5",), "leap": (SONNET,), "reviewer": (OPUS,)}
    for role, models in expected.items():
        assert role_chain(base, role) == models  # type: ignore[arg-type]
        copy = role_settings(base, role)  # type: ignore[arg-type]
        assert chain(copy) == models
        assert copy.ENGINE_FALLBACKS is False
    assert role_chain(base, "engine") == (OPUS, "claude-opus-4-8")


# ---------------------------------------------------------------------------
# The retention guard (D63)
# ---------------------------------------------------------------------------

RETENTION_KEYS = [
    ("ENGINE_MODEL", "engine"),
    ("EDITOR_MODEL", "editor"),
    ("GENERATOR_MODEL", "generator"),
    ("MATCHER_MODEL", "matcher"),
    ("IDEAS_LANE_MODEL", "lane"),
    ("IDEAS_LEAP_MODEL", "leap"),
    ("IDEAS_REVIEWER_MODEL", "reviewer"),
]


def test_the_retention_set_is_every_30_day_retention_model() -> None:
    # The advisor-tool docs (2026-10-26) list Fable 5, Fable 5.1, Mythos 5 and
    # Mythos 5.1 as the models that require 30-day retention; an unpriced one
    # is refused anyway, but the guard must not depend on that.
    assert RETENTION_REQUIRED_MODELS == frozenset(
        {"claude-fable-5-1", "claude-fable-5", "claude-mythos-5-1", "claude-mythos-5"}
    )
    assert FABLE in RETENTION_REQUIRED_MODELS


@pytest.mark.parametrize(("key", "role"), RETENTION_KEYS)
def test_a_retention_model_is_refused_in_every_repository_text_role(
    key: str, role: str
) -> None:
    """
    GIVEN Fable 5.1 (30-day retention) as one role's model, the flag unset
    WHEN the settings load
    THEN validation fails naming the role, the model and the flag; with
         ALLOW_RETENTION_MODELS on the same settings load
    """
    with pytest.raises(ValidationError, match=f"{role}.*{FABLE}.*ALLOW_RETENTION"):
        _settings(**{key: FABLE})
    cfg = _settings(ALLOW_RETENTION_MODELS=True, **{key: FABLE})
    assert FABLE in role_chain(cfg, role)  # type: ignore[arg-type]


@pytest.mark.parametrize("fallbacks", [True, False])
def test_a_retention_model_among_the_engine_fallbacks_is_refused(
    fallbacks: bool,
) -> None:
    """The fallback chain is checked whether or not it is sent (fail closed)."""
    values = {"ENGINE_FALLBACKS": fallbacks, "ENGINE_FALLBACK_MODELS": (FABLE,)}
    with pytest.raises(ValidationError, match="ALLOW_RETENTION_MODELS"):
        _settings(**values)
    _settings(ALLOW_RETENTION_MODELS=True, **values)


def test_the_triage_model_is_not_a_repository_text_role() -> None:
    assert _settings(TRIAGE_MODEL=FABLE).TRIAGE_MODEL == FABLE


def test_a_role_copy_keeps_the_flag_and_is_validated_again() -> None:
    base = _settings(ALLOW_RETENTION_MODELS=True, IDEAS_LEAP_MODEL=FABLE)
    leap = role_settings(base, "leap")
    assert (leap.ENGINE_MODEL, leap.ALLOW_RETENTION_MODELS) == (FABLE, True)
    with pytest.raises(ValidationError, match="ALLOW_RETENTION_MODELS"):
        role_settings(base, "leap", ALLOW_RETENTION_MODELS=False)


# ---------------------------------------------------------------------------
# The live harness's Fable settings (D63: the one helper that builds them)
# ---------------------------------------------------------------------------

FABLE_ARM = Arm("fable-5-1-medium", FABLE, "medium")
SONNET_ARM = Arm("sonnet-5-5-medium", SONNET, "medium")


def test_every_harness_repository_counts_and_nothing_else_does() -> None:
    projects = [
        *(repo.project(_root(repo.name)) for repo in (*CORPUS, *HARD_CORPUS)),
        *(repo.project(_root(repo.name)) for repo in (*OSS_CORPUS, *OSS_CORPUS_V2)),
    ]
    assert len(projects) == len({p.name for p in projects}) > 30
    for project in projects:
        assert harness_repository(project), project.name
    assert not harness_repository(Project(name="vlm-bridge", root_path="/w/vlm"))


def _root(name: str) -> Path:
    return Path("/tmp/harness") / name


def test_a_fable_arm_on_a_harness_repository_sets_the_flag() -> None:
    """
    GIVEN the Fable arm and a corpus repository's project
    WHEN the arm's settings copy is built
    THEN it bills Fable alone with ALLOW_RETENTION_MODELS on
    """
    project = CORPUS[0].project(_root(CORPUS[0].name))
    cfg = arm_settings(FABLE_ARM, _settings(), project)
    assert chain(cfg) == (FABLE,)
    assert cfg.ALLOW_RETENTION_MODELS is True


def test_a_fable_arm_elsewhere_or_unnamed_is_refused_before_any_spend() -> None:
    private = Project(name="vlm-bridge", root_path="/w/vlm")
    with pytest.raises(ValueError, match="vlm-bridge"):
        arm_settings(FABLE_ARM, _settings(), private)
    with pytest.raises(ValueError, match="no repository"):
        arm_settings(FABLE_ARM, _settings())


def test_any_other_arm_never_sets_the_flag() -> None:
    private = Project(name="vlm-bridge", root_path="/w/vlm")
    for project in (None, private):
        cfg = arm_settings(SONNET_ARM, _settings(), project)
        assert chain(cfg) == (SONNET,)
        assert cfg.ALLOW_RETENTION_MODELS is False


def _no_wire(request: httpx2.Request) -> httpx2.Response:
    raise AssertionError(f"the guard sent {request.url}")


def _repo_facts(project: Project) -> RepoFacts:
    objective = Objective(
        project_id=project.id,
        kind=ObjectiveKind.runtime,
        metric="wall_time_s",
        direction=Direction.minimize,
        min_relative_gain=0.02,
        description="minimize wall time",
    )
    return RepoFacts(project, None, (), objective)


def test_the_recorded_sweep_hands_its_fable_arm_the_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    GIVEN a recorded sweep (LIVE_SWEEP_RECORD=1) and the sweep's Fable arm
    WHEN the arm generates on a corpus repository, then on a private one
    THEN run_arm gets each repository, so the corpus copy carries
         ALLOW_RETENTION_MODELS and the private one is refused before a request
    """
    seen: list[Project | None] = []

    def spy(
        arm: Arm,
        run: LiveRun,
        base: Settings,
        work: Work,
        *,
        project: Project | None = None,
    ) -> ArmResult:
        seen.append(project)
        return ArmResult(arm, (), 0.0, (), (), 0.0, None)

    monkeypatch.setattr(sweep, "run_arm", spy)
    plan = replace(sweep.sweep_plan({}), record=True)
    run = LiveRun("dry", 1.0, wire=httpx2.MockTransport(_no_wire))
    corpus = _repo_facts(CORPUS[0].project(_root(CORPUS[0].name)))
    private = _repo_facts(Project(name="vlm-bridge", root_path="/w/vlm"))
    base = _settings()
    for facts in (corpus, private):
        sweep.sweep_generate(plan, sweep.FABLE_ARM, run, Budget(1.0), facts, base=base)
    assert seen == [corpus.project, private.project]
    cfg = arm_settings(sweep.FABLE_ARM, base, seen[0])
    assert (chain(cfg), cfg.ALLOW_RETENTION_MODELS) == ((FABLE,), True)
    with pytest.raises(ValueError, match="vlm-bridge"):
        arm_settings(sweep.FABLE_ARM, base, seen[1])
    assert run.records == [] and run.capture.messages() == []


# ---------------------------------------------------------------------------
# Models: Hypothesis.tags (D57), the unparsable_source rule (D62)
# ---------------------------------------------------------------------------


def _hypothesis(**values: object) -> Hypothesis:
    return Hypothesis(
        project_id="p",
        source=HypothesisSource.novel,
        title="t",
        rationale="r",
        change_class=ChangeClass.efficiency,
        expected_gain=0.1,
        provability=0.5,
        risk=0.5,
        **values,
    )


TAGS = (
    "lane:recombine",
    "review:feasible",
    "claimed_tier:transformational",
    "claimed_mechanism:precompute_or_cache",
    "claimed_cell:work:eliminate",
    "claimed_typicality:rare",
    "claimed_cell:memory:cache_across_calls",
    "x:a.b-c_1",
)


def test_tags_default_to_none_and_round_trip() -> None:
    """
    GIVEN a hypothesis built as today, then one with every D57 tag shape
    WHEN read and round-tripped through JSON
    THEN the default is empty (Step 2) and the tags come back equal
    """
    assert _hypothesis().tags == ()
    tagged = _hypothesis(tags=TAGS)
    assert Hypothesis.model_validate_json(tagged.model_dump_json()) == tagged
    assert json.loads(_hypothesis().model_dump_json())["tags"] == []


def test_tags_round_trip_through_the_checkpoint_serde(
    sample_project: Project, sample_workload: Workload, sample_objective: Objective
) -> None:
    from autonomous_ai_agents.orchestrator.serde import dump_state, load_state
    from autonomous_ai_agents.orchestrator.state import initial_state

    state = initial_state(sample_project, [sample_workload], [sample_objective], ())
    tagged = _hypothesis(tags=TAGS[:3]).model_copy(
        update={"project_id": sample_project.id}
    )
    state["hypotheses"] = [tagged]
    state["candidate_pool"] = [tagged]
    state["parked"] = [tagged.model_copy(update={"parked_reason": "needs approval"})]
    loaded = load_state(json.loads(json.dumps(dump_state(state), allow_nan=False)))
    assert loaded["hypotheses"][0].tags == TAGS[:3]
    assert loaded == state


@pytest.mark.parametrize(
    "tag",
    [
        "lane: far",  # a space
        "lanefar",  # no colon
        "Lane:far",  # upper case
        "lane:Far",
        ":far",  # an empty key
        "lane:",  # an empty value
        "lane:far\n",  # a trailing line break
        "lane:" + "a" * 65,  # a value past 64 characters
        "lane:far<",
        "lane:" + "\u00e9",
    ],
)
def test_a_malformed_tag_is_refused(tag: str) -> None:
    with pytest.raises(ValidationError):
        _hypothesis(tags=(tag,))


def test_at_most_24_tags() -> None:
    assert MAX_HYPOTHESIS_TAGS == 24
    tags = tuple(f"t:{i}" for i in range(MAX_HYPOTHESIS_TAGS))
    assert len(_hypothesis(tags=tags).tags) == 24
    with pytest.raises(ValidationError):
        _hypothesis(tags=(*tags, "t:24"))
    assert _hypothesis(tags=("t:" + "a" * 64,)).tags == ("t:" + "a" * 64,)


def test_unparsable_source_is_a_rule_of_its_own() -> None:
    rule = ViolationRule("unparsable_source")
    assert rule is ViolationRule.unparsable_source
    assert rule.value != ViolationRule.process_spawn.value


# ---------------------------------------------------------------------------
# The Protocol's five keywords (D44) and GenerateResult (D65)
# ---------------------------------------------------------------------------


def test_the_protocol_takes_five_defaulted_keyword_only_facts() -> None:
    params = inspect.signature(HypothesisGenerator.generate).parameters
    expected = {
        "commit": None,
        "run_id": None,
        "call_index": 0,
        "protected": (),
        "read_deny": (),
    }
    assert set(expected) <= set(params)
    for name, default in expected.items():
        assert params[name].kind is inspect.Parameter.KEYWORD_ONLY, name
        assert params[name].default == default, name


def test_generate_result_defaults_carry_no_events_and_no_stats() -> None:
    result = GenerateResult()
    assert (result.hypotheses, result.notes) == ((), ())
    assert (result.events, result.stats) == ((), None)


def _reply(payload: dict[str, object]) -> dict[str, object]:
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": SONNET,
        "content": [{"type": "text", "text": json.dumps(payload)}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }


IDEA: dict[str, object] = {
    "title": "Use a set",
    "technique_slug": None,
    "hotspots": [{"file_path": "dedupe/core.py", "symbol": "unique"}],
    "change_summary": "Keep a set of seen values.",
    "justification_summary": "The hotspot scans a list per item.",
    "change_class": "efficiency",
    "expected_gain": 0.5,
    "provability": 0.9,
    "risk": 0.1,
}


def _today(
    monkeypatch: pytest.MonkeyPatch, **facts: object
) -> tuple[GenerateResult, ScriptedTransport]:
    monkeypatch.setattr(secrets, "token_hex", lambda _n: "0123456789abcdef")
    monkeypatch.setattr(
        playbook_module, "STABLE_TOKENS", StableTokens(source=lambda: "5e5e" * 4)
    )
    cfg = role_settings(_settings(LLM_MAX_RETRIES=0), "generator")
    transport = ScriptedTransport([_reply({"hypotheses": [IDEA]})], cfg=cfg)
    generator: HypothesisGenerator = ClaudeHypothesisGenerator(
        transport, config=cfg, sleep=lambda _s: None
    )
    project = Project(id="p1", name="dedupe", root_path="/tmp/dedupe")
    result = generator.generate(
        project=project,
        understanding=ProjectUnderstanding(
            language="python", summary="dedupe", served_by_model=SONNET
        ),
        hotspots=(
            Hotspot(
                project_id="p1",
                workload_id="w1",
                file_path="dedupe/core.py",
                symbol="unique",
                self_time_s=0.8,
                total_time_s=0.8,
                share=0.8,
            ),
        ),  # fmt: skip
        objective=Objective(
            project_id="p1",
            kind=ObjectiveKind.runtime,
            metric="wall_time_s",
            direction=Direction.minimize,
            description="faster",
        ),
        techniques=(),
        lessons=(),
        avoid_titles=(),
        n=5,
        budget=Budget(5.0),
        **facts,  # type: ignore[arg-type]
    )
    return result, transport


def test_todays_generator_ignores_the_facts_byte_for_byte(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    GIVEN today's adapter on ScriptedTransport
    WHEN it is called without the facts, then with all five
    THEN the request sent is identical and the result carries no events and
         no stats (the default path is unchanged, D43, D65)
    """
    plain, plain_wire = _today(monkeypatch)
    given, given_wire = _today(
        monkeypatch,
        commit="a" * 40,
        run_id="run-1",
        call_index=1,
        protected=("tests/**",),
        read_deny=("data/labels.txt",),
    )
    assert given_wire.requests == plain_wire.requests
    assert len(plain_wire.requests) == 1
    assert [h.title for h in given.hypotheses] == ["Use a set"]
    assert (given.events, given.stats) == (plain.events, plain.stats) == ((), None)


# ---------------------------------------------------------------------------
# NodeContext.portfolio_rounds (D54)
# ---------------------------------------------------------------------------


def test_portfolio_rounds_defaults_to_step2_and_takes_0_to_3(
    make_context: ContextFactory,
) -> None:
    assert make_context().portfolio_rounds == 0
    assert make_context(portfolio_rounds=3).portfolio_rounds == 3
    for bad in (-1, 4):
        with pytest.raises(ValueError, match="portfolio_rounds must be 0-3"):
            make_context(portfolio_rounds=bad)


# ---------------------------------------------------------------------------
# The pipeline's own types (idea_types.py)
# ---------------------------------------------------------------------------


def test_the_enums_hold_the_specs_values() -> None:
    assert [lane.value for lane in Lane] == [
        "obvious", "eliminate", "assume_less", "name_the_problem", "recombine",
        "resolve_tradeoff", "far", "leap",
    ]  # fmt: skip
    assert set(LENS_LANES) == set(Lane) - {Lane.obvious, Lane.leap}
    assert len(LENS_LANES) == 6
    assert len(Mechanism) == 12 and Mechanism.other in Mechanism
    assert MORPH_DIMENSIONS == (
        "work", "timing", "granularity", "representation", "algorithm", "memory"
    )  # fmt: skip
    assert len(MorphCell) == 18
    for dim in MORPH_DIMENSIONS:
        assert sum(c.value.startswith(f"{dim}:") for c in MorphCell) == 3
    assert MorphCell("algorithm:approximate_then_verify") in MorphCell
    assert [t.value for t in Tier] == [
        "combinational",
        "exploratory",
        "transformational",
    ]
    assert [t.value for t in Typicality] == ["common", "uncommon", "rare"]
    assert [v.value for v in ReviewVerdict] == ["feasible", "unknown", "infeasible"]
    assert [r.value for r in ReviewReason] == [
        "none", "violates_constraint", "precondition_false", "output_not_identical",
        "duplicate_of", "outside_hot_path",
    ]  # fmt: skip


def test_every_claimed_label_makes_a_valid_tag() -> None:
    """D57's claim tags built from any enum value pass the tag rule."""
    tags = [
        *(f"lane:{x.value}" for x in Lane),
        *(f"review:{x.value}" for x in ReviewVerdict),
        *(f"claimed_tier:{x.value}" for x in Tier),
        *(f"claimed_mechanism:{x.value}" for x in Mechanism),
        *(f"claimed_cell:{x.value}" for x in MorphCell),
        *(f"claimed_typicality:{x.value}" for x in Typicality),
    ]
    for start in range(0, len(tags), MAX_HYPOTHESIS_TAGS):
        _hypothesis(tags=tuple(tags[start : start + MAX_HYPOTHESIS_TAGS]))


def _span(**values: object) -> FunctionSpan:
    fields: dict[str, object] = {
        "path": "pkg/core.py", "qualname": "Index.find", "start_line": 10,
        "end_line": 20, "hotspot_ids": ("h1",),
    }  # fmt: skip
    return FunctionSpan.model_validate({**fields, **values})


def _document(**values: object) -> CodeDocument:
    fields: dict[str, object] = {
        "path": "pkg/core.py", "start_line": 1, "end_line": 40,
        "rendered": "L1: import re", "raw": "import re", "spans": (_span(),),
        "spawn_findings": ("line 3: uses __import__",),
    }  # fmt: skip
    return CodeDocument.model_validate({**fields, **values})


def test_spans_and_documents_hold_their_line_ranges() -> None:
    assert _span().end_line == 20
    assert _span(start_line=5, end_line=5).start_line == 5
    for bad in ({"start_line": 0}, {"end_line": 9}, {"qualname": ""}, {"path": ""}):
        with pytest.raises(ValidationError):
            _span(**bad)
    assert _document().spans[0].qualname == "Index.find"
    for values in (
        {"end_line": 0},
        {"start_line": 41},
        {"spans": (_span(path="pkg/other.py"),)},
        {"spans": (_span(end_line=41),)},
        {"start_line": 11, "spans": (_span(),)},
    ):
        with pytest.raises(ValidationError):
            _document(**values)


def test_a_code_context_shows_each_path_once() -> None:
    context = CodeContext(
        documents=(_document(),), totals_by_workload={"w1": 2.5}, notes=("n",)
    )
    assert context.totals_by_workload == {"w1": 2.5}
    assert CodeContext() == CodeContext(documents=(), totals_by_workload={}, notes=())
    with pytest.raises(ValidationError):
        CodeContext(documents=(_document(), _document()))
    with pytest.raises(ValidationError):
        CodeContext(totals_by_workload={"w1": -1.0})


def _candidate(**values: object) -> IdeaCandidate:
    fields: dict[str, object] = {
        "id": "i01", "lane": "far", "title": "Index the keys",
        "change_summary": "Build a dict once.", "justification_summary": "31 %",
        "change_class": "efficiency", "expected_gain": 0.2, "provability": 0.7,
        "risk": 0.2, "depends_on_path": "pkg/core.py",
        "depends_on_quote": "for key in keys: if key in seen", "precondition": "p",
        "equivalence_summary": "same output", "mechanism": "data_structure",
        "morph_cells": ("representation:indexed",), "tier": "exploratory",
        "typicality": "uncommon",
    }  # fmt: skip
    return IdeaCandidate.model_validate({**fields, **values})


def test_an_idea_candidate_carries_the_engine_facts_unset_until_derived() -> None:
    idea = _candidate()
    assert (idea.lane, idea.mechanism, idea.tier) == (
        Lane.far,
        Mechanism.data_structure,
        Tier.exploratory,
    )
    assert (idea.technique_slug, idea.hotspot_ids) == (None, ())
    assert (idea.anchor, idea.ceiling, idea.review, idea.plan) == (None,) * 4
    derived = idea.model_copy(
        update={
            "anchor": Anchor(path="pkg/core.py", qualname="Index.find"),
            "ceiling": 0.31,
            "review": ReviewVerdict.feasible,
            "plan": "Build the index in __init__.",
        }
    )
    assert derived.anchor == Anchor(path="pkg/core.py", qualname="Index.find")
    with pytest.raises(ValidationError):  # frozen
        idea.title = "other"  # type: ignore[misc]


@pytest.mark.parametrize(
    "values",
    [
        {"morph_cells": ()},
        {"morph_cells": ("work:eliminate",) * 4},
        {"morph_cells": ("work:sideways",)},
        {"lane": "sideways"},
        {"mechanism": "magic"},
        {"ceiling": 1.5},
        {"ceiling": -0.1},
        {"provability": 1.1},
        {"expected_gain": -0.1},
        {"id": ""},
        {"reasoning": "extra"},
    ],
)
def test_an_idea_candidate_refuses_off_contract_values(
    values: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        _candidate(**values)


def test_a_generate_event_is_a_matchable_code_with_scalar_data() -> None:
    event = GenerateEvent(
        code="idea_dropped",
        message="lane far: no anchor",
        data={"lane": "far", "reason": "anchor", "title": "t"},
    )
    assert event.level is EventLevel.info
    assert GenerateEvent(code="x", message="m").data == {}
    warned = GenerateEvent(
        code="discovery_unaffordable", message="m", level=EventLevel.warning
    )
    assert warned.level is EventLevel.warning
    for bad in (
        {"code": "Idea dropped", "message": "m"},
        {"code": "", "message": "m"},
        {"code": "x" * 41, "message": "m"},
        {"code": "x", "message": ""},
        {"code": "x", "message": "m", "data": {"code": "forged"}},
    ):
        with pytest.raises(ValidationError):
            GenerateEvent.model_validate(bad)


def test_idea_stats_default_to_nothing_counted() -> None:
    stats = IdeaStats()
    assert stats.ideas_per_lane == {} and stats.review_verdicts == {}
    assert (stats.grounded, stats.anchored, stats.gate_passed) == (0, 0, 0)
    assert (stats.non_obvious, stats.unique_signatures) == (0, 0)
    assert (stats.cost_usd, stats.cache_read_tokens, stats.stop_reasons) == (0.0, 0, {})
    counted = IdeaStats(
        ideas_per_lane={Lane.obvious: 5, Lane.far: 6},
        review_verdicts={ReviewVerdict.unknown: 2},
        stop_reasons={"obvious": "end_turn", "far": None},
        cost_usd=0.42,
    )
    assert counted.ideas_per_lane[Lane.far] == 6
    for bad in ({"grounded": -1}, {"cost_usd": float("nan")}, {"cost_usd": -0.1}):
        with pytest.raises(ValidationError):
            IdeaStats.model_validate(bad)


def test_the_idea_types_never_enter_the_checkpoint_allowlist() -> None:
    """They cross one call (D65); the state carries only ``Hypothesis``."""
    from autonomous_ai_agents.common.models import ENGINE_SERDE_ALLOWLIST

    own = {
        obj for obj in vars(idea_types).values()
        if isinstance(obj, type) and obj.__module__ == idea_types.__name__
    }  # fmt: skip
    assert own and not own & set(ENGINE_SERDE_ALLOWLIST)
