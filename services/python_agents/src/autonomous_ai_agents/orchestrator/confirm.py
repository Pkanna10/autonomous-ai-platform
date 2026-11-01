"""Confirmation before keep (Step 3, U23; O10, D41 b, D42).

A trial's first look is the judges node's verdict over its paired run. A
would-be ``keep`` or ``review`` gets an independent second look before it
stands: :func:`confirm_one` re-tests the trial's commit alone through the
combiner (``combine_node.retest_one``: fresh interleaved A and B runs from
the base, the suite on the tip, the frozen judges and the completeness rule
on both sides), under the run baseline's objectives, so the per-project floor
(D41 c) applies again.

- Held: the verdict stands with one more confirmation and the second look's
  primary gain in ``confirmed_gain``.
- Not held: the verdict becomes ``inconclusive``, "did not confirm: <why>",
  which teaches a neutral lesson; the search continues.

A ``review`` confirms on a ``keep`` or ``review`` look (D10); a ``keep`` only
on a ``keep`` look, so no keep stands on a look that saw its output change
(D35). Confirmation spends no tokens: it is measurement only.

A combiner error is never a failed look: ``EngineError`` and
``RepoTamperedError`` propagate and stop the run, as in combine, before the
verdict is saved.

:func:`reported_gain` is D42's line per delivered change: the mean of both
looks' gains, the margin (the project floor or half the looks' gap, the
larger) and a label: small (< 5 %), solid (5-20 %), large (> 20 %).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

from autonomous_ai_agents.common.models import Verdict, VerdictOutcome
from autonomous_ai_agents.execution.protocols import Combiner, KeptChange
from autonomous_ai_agents.orchestrator.combine_node import (
    CombineRules,
    CombineTarget,
    retest_one,
)

CONFIRMABLE: frozenset[VerdictOutcome] = frozenset(
    {VerdictOutcome.keep, VerdictOutcome.review}
)
"""The outcomes that need a second look before they stand (D41 b)."""

_ACCEPTS: dict[VerdictOutcome, frozenset[VerdictOutcome]] = {
    VerdictOutcome.keep: frozenset({VerdictOutcome.keep}),
    VerdictOutcome.review: CONFIRMABLE,
}

GainLabel = Literal["small", "solid", "large"]


def confirm_one(
    combiner: Combiner,
    verdict: Verdict,
    change: KeptChange,
    rules: CombineRules,
    target: CombineTarget,
) -> Verdict:
    """``verdict`` after its second look (module docstring).

    ``change`` is the verdict's committed trial (``kept_changes``); ``rules``
    must carry the run baseline's objectives (the raised floor), never the
    caller's. Raises ``ValueError`` for an outcome other than keep or review.
    """
    accept = _ACCEPTS.get(verdict.outcome)
    if accept is None:
        raise ValueError(
            f"only a keep or a review is confirmed, not {verdict.outcome.value}"
        )
    look = retest_one(combiner, change, replace(rules, accept=accept), target)
    if not look.holds:
        reason = look.reason.removeprefix(f"{look.verdict.outcome.value}: ")
        return verdict.model_copy(
            update={
                "outcome": VerdictOutcome.inconclusive,
                "summary": f"inconclusive: did not confirm: {reason}",
            }
        )
    gain = look.verdict.gain
    seen = "" if gain is None else f" ({gain:+.1%})"
    return verdict.model_copy(
        update={
            "confirmations": verdict.confirmations + 1,
            "confirmed_gain": gain,
            "summary": f"{verdict.summary}; confirmed on a second look{seen}",
        }
    )


def gain_label(gain: float) -> GainLabel:
    """D42's plain label: small (< 5 %), solid (5-20 %), large (> 20 %)."""
    rounded = round(gain, 9)  # 0.05 reached by a mean is solid, not small
    if rounded < 0.05:
        return "small"
    return "solid" if rounded <= 0.20 else "large"


@dataclass(frozen=True)
class ReportedGain:
    """One delivered change's gain as D42 reports it (fractions, not percent)."""

    gain: float
    margin: float
    confirmations: int
    label: GainLabel

    def text(self) -> str:
        """E.g. "18.0% better, give or take 2.0%, confirmed twice (solid)"."""
        times = {1: "once", 2: "twice"}.get(
            self.confirmations, f"{self.confirmations} times"
        )
        return (
            f"{self.gain:.1%} better, give or take {self.margin:.1%}, "
            f"confirmed {times} ({self.label})"
        )


def reported_gain(verdict: Verdict, *, floor: float) -> ReportedGain | None:
    """D42 for ``verdict`` under the project ``floor``; ``None`` with no gain.

    With a second look the gain is the mean of both looks' primary gains and
    the margin ``max(floor, half their difference)``; with one look, its gain
    and the floor.
    """
    first = verdict.gain
    if first is None:
        return None
    second = verdict.confirmed_gain
    gain = first if second is None else (first + second) / 2
    margin = floor if second is None else max(floor, abs(first - second) / 2)
    return ReportedGain(gain, margin, verdict.confirmations, gain_label(gain))
