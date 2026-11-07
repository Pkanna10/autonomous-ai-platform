"""The shadow reading (emergence round 2, S4, VER-1): pure, no I/O.

A side's ``shadow_calls`` rows (``measure.capture_workload``, one capture
launch per workload) are its ``sequence`` leg, the benchmark's captured
package calls in order with their repetition, and one leg per point, each
distinct input once in fresh modules. Summed over workloads, the trial's
legs are read against its base's (its twin's, or the run baseline's):

- ``bench_cut``: the sequence legs' counted cut; under ``NO_GAIN_UNDER`` it
  is ``no_count_gain`` (a count-invisible change has no share to read);
- ``distinct_cut``: the distinct-once legs' counted cut;
- ``share`` = 1 - ``distinct_cut`` / ``bench_cut``, clamped to [0, 1]: the
  part of the benchmark's cut that is the benchmark repeating its own input.
  ``REPETITION_FIT_AT`` or more is ``repetition_fit``, ``CLEAR_AT`` or less
  ``clear``, between ``partial``.

A side with no sequence row, no point row or a zero count is
``uncapturable``; unequal corpora or points are ``corpus_mismatch`` (the
trial changed what the benchmark passes). Counts, not wall time, decide.
The reading goes to rows and the report only: never a verdict, a seed, a
prompt or a lane view; and ``clear`` is still benchmark-shaped (the
benchmark's own inputs, each once), not a transfer to other inputs.
``shadow_aa`` counts the base sides of one run that differ from its first:
the A/A, which must be exactly 0.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Final

from autonomous_ai_agents.common.models import JsonScalar, Measurement
from autonomous_ai_agents.execution.measure import (
    METRIC_SHADOW_CALLS,
    SHADOW_CAPTURED_KEY,
    SHADOW_CORPUS_KEY,
    SHADOW_DISTINCT_KEY,
    SHADOW_LEG_KEY,
    SHADOW_RAISED_KEY,
    SHADOW_SEQUENCE,
)
from autonomous_ai_agents.optimization.idea_types import ShadowLabel, ShadowReading

REPETITION_FIT_AT: Final = 0.8
CLEAR_AT: Final = 0.2
NO_GAIN_UNDER: Final = 0.01
"""A sequence cut under this share is no count gain (S1's ``NOT_FIRED_UNDER``)."""


@dataclass(frozen=True)
class _Side:
    corpus: frozenset[tuple[str, JsonScalar, JsonScalar]]
    sequence: float
    distinct_calls: float
    counts: dict[str, int]


def _int(value: JsonScalar | None) -> int:
    return value if type(value) is int else 0


def _side(rows: Iterable[Measurement]) -> _Side | None:
    legs = [m for m in rows if m.metric == METRIC_SHADOW_CALLS]
    sequence = [m for m in legs if m.hardware.get(SHADOW_LEG_KEY) == SHADOW_SEQUENCE]
    points = [m for m in legs if m.hardware.get(SHADOW_LEG_KEY) != SHADOW_SEQUENCE]
    if not sequence or not points:
        return None
    corpus = frozenset((m.workload_id, m.hardware.get(SHADOW_LEG_KEY),
                        m.hardware.get(SHADOW_CORPUS_KEY)) for m in legs)  # fmt: skip
    counts = {"points": len(points)} | {
        name: sum(_int(m.hardware.get(key)) for m in points)
        for name, key in (("calls", SHADOW_CAPTURED_KEY), ("distinct", SHADOW_DISTINCT_KEY),
                          ("raised", SHADOW_RAISED_KEY))
    }  # fmt: skip
    return _Side(corpus, sum(m.samples[0] for m in sequence),
                 sum(m.samples[0] for m in points), counts)  # fmt: skip


def shadow_reading(base: Sequence[Measurement], trial: Sequence[Measurement]) -> ShadowReading:  # fmt: skip
    """``trial``'s rows read against ``base``'s (module docstring)."""
    a, b = _side(base), _side(trial)
    if a is None or b is None or a.sequence <= 0 or a.distinct_calls <= 0:
        counts = {"points": 0, "calls": 0, "distinct": 0, "raised": 0} if b is None else b.counts  # fmt: skip
        return ShadowReading(label=ShadowLabel.uncapturable, share=None, bench_cut=None,
                             distinct_cut=None, **counts)  # fmt: skip
    if a.corpus != b.corpus:
        return ShadowReading(label=ShadowLabel.corpus_mismatch, share=None, bench_cut=None,
                             distinct_cut=None, **b.counts)  # fmt: skip
    bench = (a.sequence - b.sequence) / a.sequence
    distinct = (a.distinct_calls - b.distinct_calls) / a.distinct_calls
    if bench < NO_GAIN_UNDER:
        return ShadowReading(label=ShadowLabel.no_count_gain, share=None, bench_cut=bench,
                             distinct_cut=distinct, **b.counts)  # fmt: skip
    share = min(1.0, max(0.0, 1.0 - distinct / bench))
    label = (ShadowLabel.repetition_fit if share >= REPETITION_FIT_AT
             else ShadowLabel.clear if share <= CLEAR_AT else ShadowLabel.partial)  # fmt: skip
    return ShadowReading(label=label, share=share, bench_cut=bench, distinct_cut=distinct,
                         **b.counts)  # fmt: skip


def _signature(rows: Iterable[Measurement]) -> frozenset[tuple[object, ...]]:
    return frozenset((m.workload_id, m.samples, tuple(sorted(m.hardware.items())))
                     for m in rows if m.metric == METRIC_SHADOW_CALLS)  # fmt: skip


def shadow_aa(sides: Iterable[Sequence[Measurement]]) -> int:
    """How many base sides with capture rows differ from the first one, by
    counts, corpus, points or any other key of their rows."""
    found = [s for s in map(_signature, sides) if s]
    return sum(s != found[0] for s in found[1:])
