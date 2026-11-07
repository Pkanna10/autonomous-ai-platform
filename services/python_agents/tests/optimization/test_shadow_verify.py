"""The shadow reading (emergence round 2, S4, VER-1): pure, on rows.

A side's ``shadow_calls`` rows (``measure.capture_workload``) are its
``sequence`` leg (every captured call in the benchmark's order) and one leg
per point (each distinct input once). The reading compares the trial's legs
with its base's: the share of the benchmark's counted cut that the
distinct-once legs do not keep is ``repetition_share``; 0.8 or more reads
``repetition_fit``, 0.2 or less ``clear``, between ``partial``. The label is
a record (rows and report): it never reaches a verdict, a seed or a prompt.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

import pytest

from autonomous_ai_agents.common.models import JsonScalar, Measurement, RunStats
from autonomous_ai_agents.execution.measure import (
    METRIC_OP_CALLS,
    METRIC_SHADOW_CALLS,
    SHADOW_CAPTURED_KEY,
    SHADOW_CORPUS_KEY,
    SHADOW_DISTINCT_KEY,
    SHADOW_LEG_KEY,
    SHADOW_RAISED_KEY,
    SHADOW_SEQUENCE,
)
from autonomous_ai_agents.optimization.idea_types import ShadowLabel, ShadowReading
from autonomous_ai_agents.optimization.shadow_verify import (
    CLEAR_AT,
    NO_GAIN_UNDER,
    REPETITION_FIT_AT,
    shadow_aa,
    shadow_reading,
)

CORPUS = "c" * 64


def row(leg: str, n: float, *, workload: str = "w", corpus: str = CORPUS,
        metric: str = METRIC_SHADOW_CALLS) -> Measurement:  # fmt: skip
    hardware: dict[str, JsonScalar] = {SHADOW_LEG_KEY: leg, SHADOW_CORPUS_KEY: corpus}
    if leg != SHADOW_SEQUENCE:
        hardware |= {SHADOW_CAPTURED_KEY: 120, SHADOW_DISTINCT_KEY: 3, SHADOW_RAISED_KEY: 1}  # fmt: skip
    return Measurement(workload_id=workload, metric=metric,
                       stats=RunStats.from_samples((n,), unit="calls"),
                       samples=(n,), hardware=hardware)  # fmt: skip


def side(sequence: float, *points: float, **kw: str) -> tuple[Measurement, ...]:
    legs = [row(f"pkg.f{i}", n, **kw) for i, n in enumerate(points)]
    return (row(SHADOW_SEQUENCE, sequence, **kw), *legs)


def read(base: Sequence[Measurement], trial: Sequence[Measurement]) -> ShadowReading:
    return shadow_reading(base, trial)


def test_thresholds() -> None:
    assert (REPETITION_FIT_AT, CLEAR_AT, NO_GAIN_UNDER) == (0.8, 0.2, 0.01)


def test_a_cut_the_distinct_inputs_lose_is_repetition_fit_and_clamps_at_one() -> None:
    """VER-1's PROBE-R shape: the benchmark cut 6.25 % while the distinct
    legs rose 1.5 %: the share clamps to 1."""
    reading = read(side(10_000, 3_000, 2_000), side(9_375, 3_045, 2_030))

    assert reading.label is ShadowLabel.repetition_fit
    assert reading.share == 1.0
    assert reading.bench_cut == pytest.approx(0.0625)
    assert reading.distinct_cut == pytest.approx(-0.015)
    assert (reading.points, reading.calls, reading.distinct, reading.raised) == (
        2,
        240,
        6,
        2,
    )


@pytest.mark.parametrize(
    ("trial_distinct", "label", "share"),
    [
        (4_000, ShadowLabel.clear, 0.0),
        (4_190, ShadowLabel.clear, 0.19),
        (4_250, ShadowLabel.partial, 0.25),
        (4_790, ShadowLabel.partial, 0.79),
        (4_850, ShadowLabel.repetition_fit, 0.85),
        (5_100, ShadowLabel.repetition_fit, 1.0),
        (2_000, ShadowLabel.clear, 0.0),
    ],
)
def test_the_share_decides_the_label(trial_distinct: float, label: ShadowLabel, share: float) -> None:  # fmt: skip
    """A 20 % benchmark cut (10,000 to 8,000) against distinct legs of 5,000:
    a 20 % distinct cut keeps the whole gain (share 0), none of it share 1;
    a larger distinct cut than the benchmark's clamps at 0."""
    reading = read(side(10_000, 5_000), side(8_000, trial_distinct))

    assert reading.label is label
    assert reading.share == pytest.approx(share, abs=1e-9)


def test_no_count_gain_reads_no_share() -> None:
    for trial in (9_901, 10_000, 12_000):
        reading = read(side(10_000, 5_000), side(trial, 4_000))
        assert reading.label is ShadowLabel.no_count_gain
        assert reading.share is None and reading.bench_cut is not None


@pytest.mark.parametrize(
    ("base", "trial"),
    [
        ((), side(10, 5)),
        (side(10, 5), ()),
        (side(10), side(5)),
        (side(0, 5), side(0, 5)),
        (side(10, 0), side(5, 0)),
        ((row("pkg.f0", 5),), (row("pkg.f0", 4),)),
        ((row(SHADOW_SEQUENCE, 9, metric=METRIC_OP_CALLS),), side(5, 5)),
    ],
)
def test_a_side_without_legs_is_uncapturable(
    base: tuple[Measurement, ...], trial: tuple[Measurement, ...]
) -> None:
    reading = read(base, trial)

    assert reading.label is ShadowLabel.uncapturable
    assert reading.share is None and reading.bench_cut is None


def test_unequal_corpora_or_points_are_a_mismatch() -> None:
    assert read(side(10, 5), side(5, 5, corpus="d" * 64)).label is ShadowLabel.corpus_mismatch  # fmt: skip
    assert read(side(10, 5), side(5, 5, 5)).label is ShadowLabel.corpus_mismatch


def test_workloads_are_summed_per_side() -> None:
    base = (*side(6_000, 2_000), *side(4_000, 3_000, workload="v"))
    trial = (*side(4_000, 2_000), *side(4_000, 3_000, workload="v"))

    reading = read(base, trial)

    assert reading.bench_cut == pytest.approx(0.2) and reading.distinct_cut == 0.0
    assert reading.label is ShadowLabel.repetition_fit and reading.points == 2


def test_the_base_a_a_counts_every_base_side_that_differs_from_the_first() -> None:
    same = side(10, 5)

    assert shadow_aa([same, same, (), same]) == 0
    assert shadow_aa([same, side(10, 6), side(11, 5), same]) == 2
    assert shadow_aa([same, side(10, 5, corpus="d" * 64)]) == 1
    assert shadow_aa([(), ()]) == 0


def test_the_reading_is_a_frozen_record() -> None:
    reading = read(side(10, 5), side(5, 5))

    assert reading.model_dump(mode="json") == {
        "label": "repetition_fit", "share": 1.0, "bench_cut": 0.5,
        "distinct_cut": 0.0, "points": 1, "calls": 120, "distinct": 3, "raised": 1,
    }  # fmt: skip
    with pytest.raises(ValueError, match="extra"):
        ShadowReading.model_validate({**reading.model_dump(), "extra": 1})


def _pipeline() -> ModuleType:
    """``test_idea_pipeline``'s scripted pipeline, loaded under a name of its
    own (its tests are not collected twice; its golden hashes hold only
    under pytest's own module name, so both sides are hashed here)."""
    path = Path(__file__).with_name("test_idea_pipeline.py")
    spec = importlib.util.spec_from_file_location("_s4_pipeline", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("name", ["base", "views", "views_relax"])
def test_the_record_settings_together_leave_every_request_byte_identical(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Condition (c) of the correctness judge [87]: with the record settings
    that ride one arm set together (S1's count contract, S2's combine
    record, S4's shadow record), the scripted pipeline's every request and
    whole result hash as with all three off."""
    pipeline = _pipeline()
    record = {"IDEAS_COUNT_CONTRACT": "record", "SITE_STACKS": "record", "SHADOW_VERIFY": "record"}  # fmt: skip

    pipeline._reset_tokens(monkeypatch)  # the module's own fixed fence tokens
    off = pipeline._fingerprint(*pipeline._g5_run(pipeline._g5_settings(name)))
    pipeline._reset_tokens(monkeypatch)
    on = pipeline._fingerprint(*pipeline._g5_run(pipeline._g5_settings(name, **record)))

    assert on == off
