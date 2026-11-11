"""U-portfolio's records and report: the portfolio leap per arm and framework.

**Records.** ``ideas_x2.X2Recorder`` adds, only when the portfolio leap ran
(so every other arm's rows are unchanged): on each ``ideas-x2-hypothesis``
row of a portfolio leap idea ``framework`` (its procedure id),
``steps_present`` (the step products its procedure returned, ``"1,2,4"``)
and ``not_applicable`` (``None``: an idea came of it), read from its
``framework:`` and ``steps_present:`` tags (``hypothesis_fields``); on each
``ideas-x2-round`` row ``procedures``, one row per dealt procedure (the
``leap_procedure`` event's data: framework, SIT's tool, place, library, run,
deal round, cell, seed, steps required and present, ``not_applicable``,
outcome, idea id, title, reason, functions, the failure kind of a
``no_reply`` row and ``hypothesis_id``, the join key to the hypothesis row,
once the idea became a hypothesis), and ``diagnoses``, the
``leap_diagnosis`` events' data (``round_fields``). ``ideas_x2._by_round``
puts a call's portfolio rows under its round even when no ranking followed
it (a call whose lanes were unaffordable, rows ``not_sent``).

**Per case** (``deal_library``): the deal's library is the case's, set on
the process-wide settings while ``ideas_x2.run_one`` builds the run's
generator (which reads it once, ``idea_pipeline``), then restored; an arm
with the portfolio off sets nothing.

**Report** (``framework_table``, ``framework_section``): per arm and
framework, over the results rows: dealt (procedure rows), no reply
(``no_reply`` rows: the request went out, no reply could be read), not sent
(``not_sent`` rows), ideas (procedure rows whose idea passed the reply's
checks), trialled (hypothesis rows of the framework with a round), kept
(their ``keep`` verdicts), the median gain over the floor (``gain_pct /
floor_pct`` of the trialled ones with both and a positive floor) and the
adherence rate over the answered procedures only (dealt less no reply and
not sent: step products present over steps required). A deal is unique per (run,
round), so a framework's hypothesis rows and its procedure rows describe the
same ideas. Pure code over rows: nothing is sent.
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field

from autonomous_ai_agents.common.config import Settings, settings
from autonomous_ai_agents.common.models import Hypothesis, JsonScalar
from autonomous_ai_agents.optimization.idea_frameworks import CATALOGUE, check_library
from autonomous_ai_agents.optimization.idea_portfolio_leap import (
    DIAGNOSIS_EVENT,
    FRAMEWORK_TAG,
    PROCEDURE_EVENT,
    STEPS_TAG,
)

IDEA_EXPERIMENT = "ideas-x2-hypothesis"  # ideas_x2's, without its imports
ROUND_EXPERIMENT = "ideas-x2-round"
HEAD = ("arm", "framework", "dealt", "no reply", "not sent", "ideas", "trialled",
        "kept", "median gain / floor", "adherence (answered)")  # fmt: skip
UNANSWERED = frozenset({"no_reply", "not_sent"})
ROUND_CODES = frozenset({PROCEDURE_EVENT, DIAGNOSIS_EVENT})
"""The codes ``ideas_x2._by_round`` keeps under a round no ranking closed."""
_ORDER = {f.id: i for i, f in enumerate(CATALOGUE)}


@contextmanager
def deal_library(library: str, cfg: Settings) -> Iterator[None]:
    """``library`` as the process-wide deal library for the block when
    ``cfg`` (the arm's settings) has the portfolio leap on."""
    if not cfg.IDEAS_LEAP_PORTFOLIO:
        yield
        return
    saved = settings.IDEAS_LEAP_DEAL_LIBRARY
    settings.IDEAS_LEAP_DEAL_LIBRARY = check_library(library)
    try:
        yield
    finally:
        settings.IDEAS_LEAP_DEAL_LIBRARY = saved


def _tag(h: Hypothesis, key: str) -> str | None:
    prefix = f"{key}:"
    return next((t.removeprefix(prefix) for t in h.tags if t.startswith(prefix)), None)


def hypothesis_fields(h: Hypothesis) -> dict[str, object]:
    """``framework``, ``steps_present`` and ``not_applicable`` for a
    portfolio leap idea, else ``{}``."""
    found = _tag(h, FRAMEWORK_TAG)
    if found is None:
        return {}
    steps = _tag(h, STEPS_TAG)
    present = "" if steps in (None, "none") else str(steps).replace(".", ",")
    return {"framework": found, "steps_present": present, "not_applicable": None}


def round_fields(data: Iterable[Mapping[str, JsonScalar]]) -> dict[str, object]:
    """``procedures`` and ``diagnoses`` of a round's events, or ``{}``."""
    procedures: list[dict[str, JsonScalar]] = []
    diagnoses: list[dict[str, JsonScalar]] = []
    for d in data:
        code = d.get("code")
        rest = {k: v for k, v in d.items() if k != "code"}
        if code == PROCEDURE_EVENT:
            procedures.append(rest)
        elif code == DIAGNOSIS_EVENT:
            diagnoses.append(rest)
    if not procedures and not diagnoses:
        return {}
    return {"procedures": procedures, "diagnoses": diagnoses}


@dataclass
class FrameworkLine:
    arm: str
    framework: str
    dealt: int = 0
    ideas: int = 0
    trialled: int = 0
    kept: int = 0
    no_reply: int = 0
    not_sent: int = 0
    present: int = 0
    required: int = 0
    gains: list[float] = field(default_factory=list)

    @property
    def median_gain(self) -> float | None:
        return statistics.median(self.gains) if self.gains else None

    @property
    def adherence(self) -> float | None:
        return self.present / self.required if self.required else None


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _steps(value: object) -> int:
    return len([s for s in value.split(",") if s]) if isinstance(value, str) else 0


def framework_table(rows: Iterable[Mapping[str, object]]) -> tuple[FrameworkLine, ...]:
    """The table's lines, by arm, then catalogue order."""
    lines: dict[tuple[str, str], FrameworkLine] = {}

    def line(arm: object, framework: object) -> FrameworkLine | None:
        if not isinstance(arm, str) or not isinstance(framework, str):
            return None
        return lines.setdefault((arm, framework), FrameworkLine(arm, framework))

    for row in rows:
        experiment, arm = row.get("experiment"), row.get("arm")
        if experiment == ROUND_EXPERIMENT:
            procedures = row.get("procedures")
            for p in procedures if isinstance(procedures, list) else ():
                found = line(arm, p.get("framework")) if isinstance(p, dict) else None
                if found is None:
                    continue
                found.dealt += 1
                outcome = p.get("outcome")
                found.no_reply += outcome == "no_reply"
                found.not_sent += outcome == "not_sent"
                found.ideas += outcome == "idea"
                if outcome in UNANSWERED:  # adherence over answered ones only
                    continue
                found.present += _steps(p.get("steps_present"))
                required = p.get("steps_required")
                found.required += required if isinstance(required, int) else 0
        elif experiment == IDEA_EXPERIMENT:
            found = line(arm, row.get("framework"))
            if found is None or row.get("round") is None:
                continue
            found.trialled += 1
            found.kept += row.get("verdict") == "keep"
            gain, floor = _number(row.get("gain_pct")), _number(row.get("floor_pct"))
            if gain is not None and floor is not None and floor > 0:
                found.gains.append(gain / floor)
    return tuple(sorted(lines.values(),
                        key=lambda x: (x.arm, _ORDER.get(x.framework, len(_ORDER)),
                                       x.framework)))  # fmt: skip


def _cells(x: FrameworkLine) -> Sequence[str]:
    gain = "-" if x.median_gain is None else f"{x.median_gain:.2f}"
    adherence = "-" if x.adherence is None else f"{x.adherence:.0%}"
    return (x.arm, x.framework, str(x.dealt), str(x.no_reply), str(x.not_sent),
            str(x.ideas), str(x.trialled), str(x.kept), gain, adherence)  # fmt: skip


def framework_section(rows: Iterable[Mapping[str, object]]) -> list[str]:
    """The report's section: a Markdown table, or one line when no portfolio
    leap ran."""
    table = framework_table(rows)
    if not table:
        return ["No portfolio leap recorded.", ""]
    return [
        "| " + " | ".join(HEAD) + " |",
        "| " + " | ".join("---" for _ in HEAD) + " |",
        *("| " + " | ".join(_cells(x)) + " |" for x in table),
        "",
    ]
