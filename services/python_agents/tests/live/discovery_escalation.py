"""E8a, "cheap first, escalate on failure" on our judges.

The benchmark corpus (12 slowdowns, 3 controls) in aimed mode (the
manifest's two candidates):

- first pass: ``ENGINE_MODEL`` Sonnet 5.5, no fallbacks, ``EDITOR_EFFORT``
  low, capped at ``FIRST_CAP_USD``;
- each slowdown that did not win (no delivered branch) is run again with
  Opus 5.5 at ``EDITOR_EFFORT`` high, no fallbacks (like every other arm,
  so the bill is that model's), capped at ``ESCALATED_CAP_USD``. A control
  is never escalated: it has nothing to win.

Caps: a whole run has no prompt bound (the editor's conversation grows
turn by turn), so a pass's worst case is the one U22 measured: its Opus
runs summed every request's worst case to 49.65 USD over 15 runs on the
``opus-5-5`` + ``opus-4-8`` chain (STATUS ledger, E0 row). A pass's cap
scales that per-run figure by the ratio of one editor request's worst case
on the pass's chain to the same request on U22's chain, rounded up (the
escalated pass gets twice that). Each pass's results line says whether the
cap ran out (``budget_exhausted``) or stopped a trial's edit
(``trial_budget_error``), so a loss the cap caused is never read as Opus
failing.

Every pass uses a validated settings copy (``discovery.model_settings``);
the global settings never change. Recorded per repository, never asserted:
the first pass's outcome and cost, the escalated pass's, and the totals,
compared in the summary with the committed U22 baseline.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from typing import Final, Literal

from autonomous_ai_agents.clients.cost import chain
from autonomous_ai_agents.common.config import Effort, Settings, settings
from autonomous_ai_agents.orchestrator.main import EngineRunResult

from .conftest import LiveRun
from .corpus import CORPUS, CorpusOutcome, CorpusRepo
from .discovery import (
    OPUS,
    SONNET,
    budget_flags,
    ceil_usd,
    chain_worst_usd,
    model_settings,
)
from .discovery_io import (
    ResultsSink,
    cells,
    flag,
    per,
    rate,
    write_markdown,
)

FIRST_EFFORT: Final[Effort] = "low"
ESCALATED_EFFORT: Final[Effort] = "high"
ESCALATION_REPOS: Final = CORPUS
ESCALATION_SLOWDOWNS: Final = tuple(r for r in CORPUS if r.kind == "slowdown")

# The committed U22 baseline: STATUS.md, "Live API ledger" rows of
# 2026-10-23, E0 (run 39972311136: Opus 5.5 at default effort, 12/12
# slowdowns won, mean 0.10 USD a run) and M (run 39978570791: Sonnet 5.5 as
# editor, no fallbacks, 12/12 won, 0.045 USD a run).
U22_OPUS_WINS: Final = 12
U22_OPUS_RUN_USD: Final = 0.10
U22_SONNET_WINS: Final = 12
U22_SONNET_RUN_USD: Final = 0.045

Stage = Literal["first", "escalated"]
RunPass = Callable[[Stage, Settings, float], CorpusOutcome]
"""``(stage, settings, cap) -> outcome``: one whole loop, guards asserted."""


def first_settings(base: Settings) -> Settings:
    return model_settings(base, SONNET, EDITOR_EFFORT=FIRST_EFFORT)


def escalated_settings(base: Settings) -> Settings:
    return model_settings(base, OPUS, EDITOR_EFFORT=ESCALATED_EFFORT)


U22_WORST_PER_RUN_USD: Final = 49.65 / 15
U22_CHAIN: Final = (OPUS, "claude-opus-4-8")
EDITOR_PROMPT_REFERENCE: Final = 20_000  # one late editor request's count


def _request_worst(models: Sequence[str]) -> float:
    return chain_worst_usd(EDITOR_PROMPT_REFERENCE, settings.EDITOR_MAX_TOKENS, models)


def pass_cap(cfg: Settings) -> float:
    """U22's worst case per run, scaled from U22's chain to ``cfg``'s."""
    scale = _request_worst(chain(cfg)) / _request_worst(U22_CHAIN)
    return ceil_usd(U22_WORST_PER_RUN_USD * scale)


FIRST_CAP_USD: Final = pass_cap(first_settings(settings))
ESCALATED_CAP_USD: Final = 2 * pass_cap(escalated_settings(settings))
"""Twice the derived figure: Opus at high effort is no U22 run (more
thinking per editor request), and a loss the cap caused is the one outcome
this pass must not produce."""


def needs_escalation(repo: CorpusRepo, outcome: CorpusOutcome) -> bool:
    """A slowdown whose first pass delivered no branch."""
    return repo.kind == "slowdown" and not outcome.delivered


def escalation_need() -> float:
    """The worst case the suite asks the ledger for: every first pass, and
    an escalation of every slowdown."""
    first = len(ESCALATION_REPOS) * FIRST_CAP_USD
    return first + len(ESCALATION_SLOWDOWNS) * ESCALATED_CAP_USD


@dataclass(frozen=True)
class EscalationRow:
    repo: str
    kind: str
    first: CorpusOutcome
    escalated: CorpusOutcome | None

    @property
    def final_win(self) -> bool:
        last = self.first if self.escalated is None else self.escalated
        return last.delivered

    @property
    def cost_usd(self) -> float:
        later = 0.0 if self.escalated is None else self.escalated.cost_usd
        return self.first.cost_usd + later


def run_escalation(
    repo: CorpusRepo, run_pass: RunPass, base: Settings
) -> EscalationRow:
    """The first pass, then the escalated one when ``needs_escalation``."""
    first = run_pass("first", first_settings(base), FIRST_CAP_USD)
    escalated = None
    if needs_escalation(repo, first):
        escalated = run_pass("escalated", escalated_settings(base), ESCALATED_CAP_USD)
    return EscalationRow(repo.name, repo.kind, first, escalated)


def pass_record(
    stage: Stage, outcome: CorpusOutcome, result: EngineRunResult | None = None
) -> dict[str, object]:
    """One pass as a results line, with the cap's part in a loss."""
    return {
        "experiment": "E8a-escalation",
        "stage": stage,
        **asdict(outcome),
        **asdict(budget_flags(result)),
    }


def render_escalation(rows: Sequence[EscalationRow]) -> str:
    lines = ["## Editor escalation (E8a)", ""]
    if not rows:
        return "\n".join([*lines, "No escalation repository finished."])
    lines += [
        "| repo | kind | first win | first USD | escalated | escalated win "
        "| escalated USD | total USD | guards |",
        "| --- | --- | --- | ---: | --- | --- | ---: | ---: | --- |",
    ]
    for r in rows:
        later = r.escalated
        guards = r.first.guard if later is None else f"{r.first.guard}; {later.guard}"
        lines.append(
            cells(
                [
                    r.repo,
                    r.kind,
                    flag(r.first.delivered),
                    f"{r.first.cost_usd:.4f}",
                    flag(later is not None),
                    "-" if later is None else flag(later.delivered),
                    "-" if later is None else f"{later.cost_usd:.4f}",
                    f"{r.cost_usd:.4f}",
                    guards,
                ]
            )
        )
    slow = [r for r in rows if r.kind == "slowdown"]
    controls = [r for r in rows if r.kind == "control"]
    first_wins = sum(r.first.delivered for r in slow)
    final_wins = sum(r.final_win for r in slow)
    spend = math.fsum(r.cost_usd for r in slow)
    escalations = sum(r.escalated is not None for r in slow)
    false_wins = sum(r.first.delivered for r in controls)
    lines += [
        "",
        f"First pass (Sonnet 5.5, editor effort low): {rate(first_wins, len(slow))} "
        "slowdowns won.",
        f"After escalation (Opus 5.5, editor effort high): "
        f"{rate(final_wins, len(slow))}; {escalations} escalation(s).",
        f"Slowdown spend {spend:.4f} USD, {per(spend, len(slow))} USD per slowdown, "
        f"{per(spend, final_wins)} USD per win. Control false wins: "
        f"{rate(false_wins, len(controls))}.",
        f"U22 baseline (default editor effort): Opus 5.5 {U22_OPUS_WINS}/12 at "
        f"{U22_OPUS_RUN_USD:.4f} USD a run, Sonnet 5.5 {U22_SONNET_WINS}/12 at "
        f"{U22_SONNET_RUN_USD:.4f} USD a run.",
        "The escalated cost includes a full re-run (understand, baseline, "
        "profile) as well as the trials; production escalation would re-run only "
        "the editor, so it overstates what escalating costs.",
    ]
    return "\n".join(lines)


@dataclass
class EscalationRecorder:
    sink: ResultsSink
    rows: list[EscalationRow] = field(default_factory=list)

    def record_pass(
        self,
        stage: Stage,
        outcome: CorpusOutcome,
        result: EngineRunResult | None = None,
        *,
        run: LiveRun,
    ) -> None:
        self.sink.write(pass_record(stage, outcome, result))
        run.note(
            f"escalation {outcome.repo} {stage}: {outcome.engine_model}, delivered "
            f"{flag(outcome.delivered)}, guards {outcome.guard}"
        )

    def add(self, row: EscalationRow) -> None:
        self.rows.append(row)

    def finish(self, echo: Callable[[str], None]) -> None:
        if self.rows:
            text = render_escalation(self.rows)
            write_markdown("Editor escalation", text, self.sink.environ, echo)
