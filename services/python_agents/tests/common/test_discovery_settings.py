"""Step 3 contracts (U2): the discovery and retry settings and model fields.

Spec section 3.1 (settings), 3.3 (models) and D4: every default reproduces
Step 2 or carries the owner's choice (O8: one fix retry a run, bound 0-1).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from autonomous_ai_agents.clients.cost import chain
from autonomous_ai_agents.common.config import Settings, role_chain, role_settings
from autonomous_ai_agents.common.models import (
    ChangeClass,
    Hypothesis,
    HypothesisSource,
    TechniqueMatchRecord,
    Trial,
    VerdictOutcome,
)

SONNET = "claude-sonnet-5-5"
OPUS = "claude-opus-5-5"


def _settings(**values: object) -> Settings:
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def test_the_discovery_and_retry_defaults_are_the_specs() -> None:
    """
    GIVEN no environment
    WHEN the settings load
    THEN the generator, matcher, retrieval and retry knobs carry the spec's
         defaults (D5, D1, D9, D7, D16, D12 and O8)
    """
    cfg = _settings()

    assert (cfg.GENERATOR_MODEL, cfg.GENERATOR_EFFORT) == (SONNET, "medium")
    assert (cfg.GENERATOR_N, cfg.GENERATOR_MAX_TOKENS, cfg.GENERATOR_MAX_CALLS) == (
        5,
        16000,
        2,
    )
    assert (cfg.MATCHER_MODEL, cfg.MATCHER_EFFORT, cfg.MATCHER_K) == (
        SONNET,
        "medium",
        3,
    )
    assert cfg.RESEARCH_RETRIEVAL == "blind"
    assert cfg.GENERATED_CLASSES == (ChangeClass.efficiency, ChangeClass.behaviour)
    assert cfg.DISCOVERY_MAX_SHARE == 0.25
    assert cfg.EDITOR_MODEL is None
    assert (cfg.EDITOR_FIX_RETRIES, cfg.EDITOR_FIX_RETRIES_PER_RUN) == (1, 1)
    assert cfg.RETRY_CLOSURE_MAX_SOURCE_BYTES == 8 * 1024 * 1024


@pytest.mark.parametrize(
    "values",
    [
        {"GENERATOR_N": 0},
        {"GENERATOR_N": 21},
        {"MATCHER_K": 0},
        {"MATCHER_K": 21},
        {"GENERATOR_MAX_CALLS": -1},
        {"GENERATOR_MAX_CALLS": 6},
        {"GENERATOR_MAX_TOKENS": 0},
        {"DISCOVERY_MAX_SHARE": 0.0},
        {"DISCOVERY_MAX_SHARE": 1.0},
        {"DISCOVERY_MAX_SHARE": float("nan")},
        {"RESEARCH_RETRIEVAL": "playbook"},
        {"GENERATED_CLASSES": ("efficiency", "novel")},
        {"GENERATED_CLASSES": ()},
        {"EDITOR_FIX_RETRIES": -1},
        {"EDITOR_FIX_RETRIES": 2},
        {"EDITOR_FIX_RETRIES_PER_RUN": -1},
        {"EDITOR_FIX_RETRIES_PER_RUN": 2},
        {"RETRY_CLOSURE_MAX_SOURCE_BYTES": 0},
    ],
)
def test_out_of_range_discovery_and_retry_values_are_refused(
    values: dict[str, object],
) -> None:
    """
    GIVEN a knob outside its spec range (novel or no generated class, either
          retry setting outside 0-1, a share outside (0, 1))
    WHEN the settings load
    THEN validation fails
    """
    with pytest.raises(ValidationError):
        _settings(**values)


def test_the_bounds_themselves_are_accepted() -> None:
    """
    GIVEN each knob at the edge of its range
    WHEN the settings load
    THEN they are kept; repeated generated classes collapse in order
    """
    cfg = _settings(
        GENERATOR_N=20,
        MATCHER_K=1,
        GENERATOR_MAX_CALLS=0,
        EDITOR_FIX_RETRIES=0,
        EDITOR_FIX_RETRIES_PER_RUN=0,
        RESEARCH_RETRIEVAL="matched",
        GENERATED_CLASSES=("behaviour", "efficiency", "behaviour"),
        GENERATOR_EFFORT="",
    )

    assert cfg.GENERATED_CLASSES == (ChangeClass.behaviour, ChangeClass.efficiency)
    assert cfg.GENERATOR_EFFORT is None
    assert (cfg.GENERATOR_N, cfg.MATCHER_K, cfg.GENERATOR_MAX_CALLS) == (20, 1, 0)


@pytest.mark.parametrize("key", ["GENERATOR_MODEL", "MATCHER_MODEL", "EDITOR_MODEL"])
def test_an_unpriced_role_model_is_refused(key: str) -> None:
    """
    GIVEN a role model with no MODEL_PRICING entry
    WHEN the settings load
    THEN validation fails naming the model
    """
    with pytest.raises(ValidationError, match="claude-unpriced-1"):
        _settings(**{key: "claude-unpriced-1"})


@pytest.mark.parametrize(
    ("values", "match"),
    [
        ({"GENERATOR_EFFORT": "xhigh", "GENERATOR_MODEL": "claude-opus-4-6"}, "GEN"),
        ({"MATCHER_EFFORT": "max", "MATCHER_MODEL": "claude-opus-4-5"}, "MATCHER"),
        ({"EDITOR_EFFORT": "xhigh", "EDITOR_MODEL": "claude-opus-4-6"}, "EDITOR"),
    ],
)
def test_an_effort_its_role_model_rejects_is_refused(
    values: dict[str, object], match: str
) -> None:
    """
    GIVEN a role effort its own model does not accept (or an id the effort
          docs do not list)
    WHEN the settings load
    THEN validation fails naming the setting
    """
    prices = dict(_settings().MODEL_PRICING)
    for model in ("claude-opus-4-6", "claude-opus-4-5"):
        prices[model] = prices[OPUS]
    with pytest.raises(ValidationError, match=match):
        _settings(MODEL_PRICING=prices, **values)


def test_role_chains_and_role_settings_follow_the_roles() -> None:
    """
    GIVEN the defaults, then an editor model set
    WHEN each role's chain and settings copy are built
    THEN new roles run without fallbacks, the unset editor keeps the engine
         chain, each copy's cost chain equals its role chain, and the base
         settings are unchanged
    """
    base = _settings(EDITOR_EFFORT="high")
    assert role_chain(base, "engine") == chain(base) == (OPUS, "claude-opus-4-8")
    assert role_chain(base, "editor") == chain(base)
    assert role_chain(base, "generator") == (SONNET,)
    assert role_chain(base, "matcher") == (SONNET,)
    assert role_settings(base, "editor") == base

    edited = _settings(
        EDITOR_MODEL=SONNET, EDITOR_EFFORT="low", UNDERSTAND_EFFORT="max"
    )
    assert role_chain(edited, "editor") == (SONNET,)
    for role in ("generator", "matcher", "editor"):
        copy = role_settings(edited, role)
        assert chain(copy) == role_chain(edited, role)
        assert copy.UNDERSTAND_EFFORT is None
    assert role_settings(edited, "editor").EDITOR_EFFORT == "low"
    assert role_settings(edited, "generator").EDITOR_EFFORT is None
    assert role_settings(edited, "matcher", LLM_TIMEOUT_S=9.0).LLM_TIMEOUT_S == 9.0
    assert edited.ENGINE_MODEL == OPUS and edited.ENGINE_FALLBACKS is True


def test_trial_and_hypothesis_step3_fields_default_to_step2() -> None:
    """
    GIVEN a Trial and a Hypothesis built as in Step 2
    WHEN the Step 3 fields are read
    THEN one attempt, no retry notes and no parked reason; attempts below 1
         and an empty parked reason are refused; review is a verdict outcome
    """
    trial = Trial(hypothesis_id="h1", round=1)
    hypothesis = Hypothesis(
        project_id="p",
        source=HypothesisSource.novel,
        title="t",
        rationale="r",
        change_class=ChangeClass.novel,
        expected_gain=0.1,
        provability=0.5,
        risk=0.5,
    )

    assert (trial.attempts, trial.retry_notes) == (1, ())
    assert hypothesis.parked_reason is None
    assert VerdictOutcome("review") is VerdictOutcome.review
    with pytest.raises(ValidationError):
        Trial(hypothesis_id="h1", round=1, attempts=0)
    with pytest.raises(ValidationError):
        hypothesis.model_validate({**hypothesis.model_dump(), "parked_reason": ""})


def test_a_technique_match_record_is_bounded() -> None:
    """
    GIVEN a technique match record
    WHEN it is built with a fit outside [0, 1] or an empty slug
    THEN validation fails; a valid one keeps its unmet preconditions
    """
    record = TechniqueMatchRecord(
        slug="cache-embeddings",
        fit=0.8,
        justification_summary="frozen encoder",
        unmet_preconditions=("gpu",),
    )

    assert record.unmet_preconditions == ("gpu",)
    for bad in ({"fit": 1.5}, {"fit": -0.1}, {"slug": ""}):
        with pytest.raises(ValidationError):
            record.model_validate({**record.model_dump(), **bad})
