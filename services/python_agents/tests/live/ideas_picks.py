"""V-picks: the ``ideas-picks`` suite, the blind reader's would-try ideas as
ordinary engine trials (O48; spec-idea-lab 9.6 item 2, 9.7).

The ideas (``$LIVE_PICKS_IDS``, default ``PICK_IDS``: S04, S07, S09, S12,
S13, S20 and S23) are resolved before any spend through the committed sample
key (``owner-sample-key.json``: repo, arm, label, position, lane, model)
against the slice's committed inputs (``x1-1.jsonl``, run 1's libraries
with the re-run's X1-1, as the report's sample; ``x1-2.jsonl``). Refused:
an id not in the key, a library outside ``PICKS_REPOS``, a key that matches
no ``ideas-idea`` row or two, a row whose title is not the one
``owner-sample.md`` showed the reader, a lane reply that does not hold it.

Each idea is a ``Hypothesis`` exactly as ``ideas_slice.hypothesis`` builds
one, each library one ordinary engine loop through the slice's own path
(``discovery_oss.start_arm_loop``: a fresh clone, every pick trialled in
the loop's one round, then the combine; ``discovery.run_engine`` with every
corpus guard): sqlparse S20, S04, S12; more_itertools S13, S23; mistune
S07; tomli S09. The rule's ideas lead their loops (the engine trials in
candidate order and stops at the trial floor, so a budget stop lands on
the others). The engine is the slice's (``ideas_slice.check_engine``:
Opus 5.5, ``OP_COUNT_JUDGE`` on, asserted in the module fixture and before
each loop; the judge in each loop's judges before it runs; the op-count
column on every verdict after the records), under Step 3's noise rule.

Caps from the engine's own reservations: before every attempt ``call``
checks the spend so far plus ``preflight_estimate`` (the counted prompt
plus ``count_margin``, the request's ``max_tokens``, every model of its
chain) against the cap, and a trial starts only with ``min_trial_budget``
left; so a loop is never refused while its cap holds what it spends plus
its dearest request's reservation (``loop_need``). At measured rates
(``MEASURED``, the slice's cost tables, runs 41796813265 and 41803612871):
per library the dearest loop's spend, scaled when a loop runs more trials,
and the widest loop's input plus cache-write tokens, the most one prompt
held (each prompt token is billed once at one of those two rates within
its loop; a prefix an earlier loop of the job cached is the exception); a
library the slice did not run takes the widest of all (``WIDEST``). The
need, 7.55 USD (sqlparse 1.60, more_itertools 2.15, mistune 2.15, tomli
1.65), is under the owner's ``PICKS_CAP_USD`` (8): a need past it is
refused, never fitted by lowering a loop's cap. Minutes: the slice's
``LOOP_MINUTES`` a loop (its dispatches measured 33 and 29 minutes for
eight loops with their markers and tournaments, about 4 a loop).

Recorded, never asserted (``$LIVE_RESULTS_PATH``): per idea the slice's
trial row with its sample id and the reader's mark (``ideas-picks-trial``),
per library the slice's combine row with its sample ids
(``ideas-picks-combine``); model-derived text redacted and chunked.
Offline, ``python -m live.ideas_picks RESULTS`` prints the reader-vs-judge
table and O48's rule (``fable_rule``), refused (exit 2, after the table)
while S13 or S20 has no judged trial.
"""

from __future__ import annotations

import argparse
import functools
import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from e2e.conftest import Isolation

from autonomous_ai_agents.clients.cost import count_margin, preflight_estimate
from autonomous_ai_agents.common import models
from autonomous_ai_agents.common.config import Settings, role_chain, settings
from autonomous_ai_agents.orchestrator.main import EngineRunResult

from . import discovery_oss as dx
from . import ideas_pool as ipool
from . import ideas_probe as ip
from . import ideas_slice as sl
from .conftest import TESTS_DIR, LiveRun, StartLive, redact_keys, suite_cap
from .corpus import CorpusOutcome
from .discovery import ceil_usd, run_engine
from .discovery_io import ResultsSink, cells
from .discovery_oss import start_arm_loop
from .ideas_pool import IdeaRow
from .ideas_probe import _chunks, _fit, _Strict
from .ideas_report import REPORT_DIR
from .oss import PRODUCTION, GitPolicy, OssRepo

PICK_IDS: Final = ("S04", "S07", "S09", "S12", "S13", "S20", "S23")
RULE_IDS: Final = ("S13", "S20")  # X1-1's Fable resolve_tradeoff ideas
RULE_FACTOR: Final = 2.0  # kept with a gain at least twice its floor
UNJUDGED: Final = frozenset({dx.NOT_HANDED, dx.NOT_TRIALLED, dx.NO_VERDICT,
                             dx.NO_RESULT})  # no verdict: the rule cannot read it  # fmt: skip
ADD_LANE: Final = "add a Fable resolve_tradeoff lane"
NO_FABLE: Final = "no-Fable call stands"
READER_MARK: Final = "would try"
READER_ARM: Final = "reader"  # a loop holds ideas of several configurations
SELECTION: Final = "the blind reader's would-try ideas (O48)"
IDS_ENV: Final = "LIVE_PICKS_IDS"
PICKS_REPOS: Final = ("sqlparse", "more_itertools", "mistune", "tomli")
PICKS_LIBRARIES: Final = tuple(
    next(r for r in dx.OSS_SELECTABLE if r.name == name) for name in PICKS_REPOS
)
KEY: Final = REPORT_DIR / "owner-sample-key.json"
SAMPLE: Final = REPORT_DIR / "owner-sample.md"
INPUTS: Final = tuple(TESTS_DIR / "fixtures/ideas_slice" / f"x1-{n}.jsonl"
                      for n in (1, 2))  # fmt: skip
TRIAL_EXPERIMENT: Final = "ideas-picks-trial"
COMBINE_EXPERIMENT: Final = "ideas-picks-combine"
PICKS_CAP_USD: Final = 8.0  # the owner's (O48), about 3 expected
JOB_MINUTES: Final = 45  # ci.yml's ideas-picks timeout


@dataclass(frozen=True)
class Measured:
    spend_usd: float  # the dearest loop's spend
    trials: int  # that loop's trials
    prompt_tokens: int  # the widest loop's input plus cache-write tokens


MEASURED: Final = {
    "sqlparse": Measured(0.5064, 3, 15_851 + 35_204),  # X1-3, both
    "pyparsing": Measured(0.7212, 3, 20_760 + 57_752),  # X1-3, both
    "tomli": Measured(0.4471, 3, 26_640 + 33_980),  # X1-0, both
    "sortedcontainers": Measured(0.2591, 3, 20_709 + 18_284),  # X1-2; X1-1
}
_DEAREST: Final = max(MEASURED.values(), key=lambda m: m.spend_usd / m.trials)
WIDEST: Final = Measured(_DEAREST.spend_usd, _DEAREST.trials,
                         max(m.prompt_tokens for m in MEASURED.values()))  # fmt: skip


def reserve_usd(prompt_tokens: int, cfg: Settings = settings) -> float:
    """The dearer of the understand's and an editor request's reservation
    on a prompt of ``prompt_tokens`` (``call``'s ``preflight_estimate``)."""
    counted = prompt_tokens + count_margin(prompt_tokens)
    return max(
        preflight_estimate(counted, cfg.UNDERSTAND_MAX_TOKENS,
                           role_chain(cfg, "engine"), cfg.MODEL_PRICING),
        preflight_estimate(counted, cfg.EDITOR_MAX_TOKENS,
                           role_chain(cfg, "editor"), cfg.MODEL_PRICING),
    )  # fmt: skip


def loop_need(repo: str, picks: int, cfg: Settings = settings) -> float:
    """What a loop of ``picks`` spends at measured rates plus its dearest
    request's reservation: every request, the trial floor included, fits."""
    m = MEASURED.get(repo, WIDEST)
    spend = m.spend_usd * max(1.0, picks / m.trials)
    return ceil_usd(spend + reserve_usd(m.prompt_tokens, cfg))


# ---------------------------------------------------------------------------
# The ideas, resolved through the sample key
# ---------------------------------------------------------------------------


class _KeyEntry(_Strict):
    repo: str
    arm: str
    label: str
    lane: str
    model: str
    position: int


_KINDS: Final[Mapping[str, type[_Strict]]] = {
    ip.IDEA_EXPERIMENT: IdeaRow, ip.REPLY_EXPERIMENT: ipool.ReplyRow,
    ip.AUDIT_EXPERIMENT: sl._AuditRow,
}  # fmt: skip


@dataclass(frozen=True)
class Pick:
    sample: str
    idea: sl.Idea
    audit_id: str | None  # the pooled auditor's id (None: not one audit row)
    hypothesis: models.Hypothesis


def _shown(text: str, sample: str, row: IdeaRow) -> None:
    """The row's title is the one ``owner-sample.md`` showed the reader
    (the report's own cells: redacted, escaped)."""
    found = [x for x in text.splitlines() if x.startswith(f"| {sample} |")]
    if len(found) != 1:
        raise ValueError(f"{sample}: owner-sample.md has {len(found)} rows")
    if not found[0].startswith(cells([sample, row.repo, redact_keys(row.title)]) + " "):
        raise ValueError(f"{sample}: its title is not the one owner-sample.md shows")


def resolve(
    ids: Sequence[str], key: Mapping[str, _KeyEntry], sample: Path,
    inputs: Sequence[Path],
) -> tuple[Pick, ...]:  # fmt: skip
    text = sample.read_text(encoding="utf-8")
    rows = ipool.read_rows(inputs, _KINDS)
    out: list[Pick] = []
    for sid in ids:
        if sid not in key:
            raise ValueError(f"{sid}: not in the sample key")
        k = key[sid]
        if k.repo not in PICKS_REPOS:
            raise ValueError(f"{sid}: {k.repo} is not one of {', '.join(PICKS_REPOS)}")
        mine = rows.get(k.repo, [])
        found = [r for r in mine if isinstance(r, IdeaRow) and (r.arm, r.label,
                 r.position, r.lane, r.model) == (k.arm, k.label, k.position,
                                                  k.lane, k.model)]  # fmt: skip
        n = len(found)
        if n != 1:
            raise ValueError(f"{sid}: {k.repo} {k.arm} {k.label} #{k.position} resolves "
                             f"to {n or 'no'} ideas-idea row{'s' if n > 1 else ''}")  # fmt: skip
        row = found[0]
        _shown(text, sid, row)
        item = ipool.reply_item(row, ipool.reply_texts(k.repo, mine))
        audits = [a.id for a in mine if isinstance(a, sl._AuditRow)
                  and (a.arm, a.lane, redact_keys(a.title)) == (row.arm, row.lane, row.title)]  # fmt: skip
        aid = audits[0] if len(audits) == 1 else None
        idea = sl.Idea(row, item, 0 if aid is None else sl._number(aid), 0)
        out.append(Pick(sid, idea, aid, sl.hypothesis(idea)))
    return tuple(out)


@dataclass(frozen=True)
class PicksPlan:
    picks: tuple[Pick, ...]

    def of(self, repo: str) -> tuple[Pick, ...]:
        """The library's picks, the rule's ideas first (a stable sort)."""
        mine = [p for p in self.picks if p.idea.row.repo == repo]
        return tuple(sorted(mine, key=lambda p: p.sample not in RULE_IDS))

    @property
    def repos(self) -> tuple[OssRepo, ...]:
        return tuple(r for r in PICKS_LIBRARIES if self.of(r.name))

    def loop_cap(self, repo: str) -> float:
        return loop_need(repo, len(self.of(repo)))

    def minutes(self) -> int:
        return len(self.repos) * sl.LOOP_MINUTES


def picks_need(plan: PicksPlan) -> float:
    return math.fsum(plan.loop_cap(r.name) for r in plan.repos)


def check_fuse(plan: PicksPlan) -> None:
    need, minutes = picks_need(plan), plan.minutes()
    if need > PICKS_CAP_USD:
        raise ValueError(f"the picks need {need:.2f} USD, past the owner's "
                         f"{PICKS_CAP_USD:g} USD cap (O48); a loop's cap is never "
                         "lowered below what the engine needs to admit its trials")  # fmt: skip
    if minutes > JOB_MINUTES:
        raise ValueError(f"the picks take {minutes} minutes, past the "
                         f"{JOB_MINUTES}-minute job")  # fmt: skip


def picks_plan(
    environ: Mapping[str, str], *, key: Path = KEY, sample: Path = SAMPLE,
    inputs: Sequence[Path] = INPUTS,
) -> PicksPlan:  # fmt: skip
    """Every idea resolved and the need checked, before any spend."""
    raw = json.loads(key.read_text(encoding="utf-8"))
    entries = {k: _KeyEntry.model_validate(v) for k, v in raw.items()}
    ids = dx._keys(environ, IDS_ENV, sorted(entries))
    plan = PicksPlan(resolve(PICK_IDS if ids is None else ids, entries, sample, inputs))
    check_fuse(plan)
    need, cap = picks_need(plan), suite_cap(environ)
    if cap < need:
        raise ValueError(f"suite cap {cap:.2f} USD is below the picks' need {need:.2f}")
    return plan


# ---------------------------------------------------------------------------
# Records, as the slice writes them, and one loop per library
# ---------------------------------------------------------------------------


@dataclass
class PicksRecorder:
    plan: PicksPlan
    sink: ResultsSink
    base: Settings = field(default_factory=lambda: settings)

    def __post_init__(self) -> None:
        sl.check_engine(self.base)

    def record(self, repo: str, chosen: Sequence[Pick], guard: str, cost_usd: float,
               result: EngineRunResult | None) -> None:  # fmt: skip
        hyps = [p.hypothesis for p in chosen]
        ranks = dx.rank_rows(repo, 1, READER_ARM, hyps, result, guard=guard)
        verdicts: dict[str, models.Verdict] = {}
        for v in () if result is None else result.state["verdicts"]:
            verdicts.setdefault(v.hypothesis_id, v)
        guard = _fit(redact_keys(guard))
        for n, (p, r) in enumerate(zip(chosen, ranks, strict=True), 1):
            row, item = p.idea.row, p.idea.item
            self.sink.write({
                "experiment": TRIAL_EXPERIMENT, "sample": p.sample, "reader": READER_MARK,
                "repo": repo, "arm": row.arm, "label": row.label, "position": row.position,
                "lane": row.lane, "model": row.model, "audit_id": p.audit_id,
                "selection": SELECTION, "grader": None, "score": None,
                "grader_validated": None, "rank": n, "title": redact_keys(item.title),
                "mechanism": item.mechanism.value, "cells": list(row.cells),
                "path": row.path, "target": row.target,
                "rationale": _chunks(redact_keys(p.hypothesis.rationale)),
                "hypothesis_id": p.hypothesis.id, "verdict": r.verdict,
                "gain_pct": r.gain_pct, "floor_pct": r.noise_floor_pct,
                "op_count": sl._op_count(verdicts.get(p.hypothesis.id)), "guard": guard,
            })  # fmt: skip
        comb = None if result is None else result.state["combination"]
        j = sl._primary(result)
        self.sink.write({
            "experiment": COMBINE_EXPERIMENT, "repo": repo, "arm": READER_ARM,
            "samples": [p.sample for p in chosen], "selection": SELECTION,
            "eligible": len(chosen), "picked": len(chosen),
            "kept": sum(r.verdict == "keep" for r in ranks), "combined": comb is not None,
            "holds": None if comb is None else comb.holds,
            "applied": 0 if comb is None else len(comb.applied_trial_ids),
            "fallback": comb is not None and comb.fallback_trial_id is not None,
            "gain_pct": None if j is None else dx._pct(j.gain),
            "floor_pct": None if j is None else dx._pct(j.noise_floor),
            "delivered": result is not None and result.state["delivery"] is not None,
            "summary": _chunks("" if comb is None else redact_keys(comb.summary)),
            "cost_usd": cost_usd, "guard": guard,
            "seeded_calls": 0 if result is None else result.state["seeded_calls"],
            "seeded_cost_usd": 0.0 if result is None else result.state["seeded_cost_usd"],
        })  # fmt: skip


def _record(recorder: PicksRecorder, repo: str, chosen: Sequence[Pick], run: LiveRun,
            seen: list[EngineRunResult | None], outcome: CorpusOutcome,
            result: EngineRunResult | None) -> None:  # fmt: skip
    seen.append(result)
    recorder.record(repo, chosen, outcome.guard, run.spent_usd, result)


def run_library(
    repo: OssRepo,
    *,
    live: StartLive,
    root: Path,
    isolation: Isolation,
    recorder: PicksRecorder,
    policy: GitPolicy = PRODUCTION,
    base: Settings = settings,
) -> None:
    """One engine loop of the library's picks, every one in its round."""
    sl.check_engine(base)
    chosen = recorder.plan.of(repo.name)
    if not chosen:
        raise ValueError(f"{repo.name}: no pick, no loop")
    run = live(recorder.plan.loop_cap(repo.name))
    loop = start_arm_loop(repo, run, root / repo.name, isolation,
                          [p.hypothesis for p in chosen], policy=policy)  # fmt: skip
    sl.check_judges(loop)
    seen: list[EngineRunResult | None] = []
    record = functools.partial(_record, recorder, repo.name, chosen, run, seen)
    run_engine(loop, run, isolation, model=base.ENGINE_MODEL, record=record)
    run.note(_fit(f"PICKS {repo.name} {','.join(p.sample for p in chosen)}: "
                  f"{len(chosen)} trial(s), {run.spent_usd:.3f} USD"))  # fmt: skip
    sl.check_op_column(seen[-1])


# ---------------------------------------------------------------------------
# Offline: the reader against the judges, and O48's rule
# ---------------------------------------------------------------------------


class ReadLine(_Strict):  # one ideas-picks-trial row, as the readout reads it
    sample: str
    reader: str
    repo: str
    verdict: str
    gain_pct: float | None
    floor_pct: float | None


def readout(path: Path) -> tuple[ReadLine, ...]:
    """The trial rows of a results file in file order, a sample refused twice."""
    found: dict[str, ReadLine] = {}
    for text in path.read_text(encoding="utf-8").splitlines():
        raw = json.loads(text)
        if not isinstance(raw, dict) or raw.get("experiment") != TRIAL_EXPERIMENT:
            continue
        line = ReadLine.model_validate({k: raw.get(k) for k in ReadLine.model_fields})
        if line.sample in found:
            raise ValueError(f"{line.sample}: two {TRIAL_EXPERIMENT} rows")
        found[line.sample] = line
    return tuple(found.values())


def fires(line: ReadLine) -> bool:
    return (line.verdict == "keep" and line.gain_pct is not None
            and line.floor_pct is not None
            and line.gain_pct >= RULE_FACTOR * line.floor_pct)  # fmt: skip


def fable_rule(lines: Sequence[ReadLine]) -> str:
    """O48: S13 or S20 kept with a gain at least twice its floor adds a Fable
    resolve_tradeoff lane to X2; otherwise the no-Fable call stands."""
    by = {x.sample: x for x in lines}
    for sid in RULE_IDS:
        if sid not in by:
            raise ValueError(f"{sid}: no {TRIAL_EXPERIMENT} row; O48's rule reads "
                             f"{' and '.join(RULE_IDS)}")  # fmt: skip
        if by[sid].verdict in UNJUDGED:
            raise ValueError(
                f"{sid}: {by[sid].verdict}; O48's rule needs a judged trial"
            )
    return ADD_LANE if any(fires(by[s]) for s in RULE_IDS) else NO_FABLE


def _num(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}"


def table(lines: Sequence[ReadLine]) -> list[str]:
    head = ("sample", "reader", "verdict", "gain %", "floor %")
    return [cells(head), cells(["---"] * len(head)),
            *(cells([x.sample, x.reader, x.verdict, _num(x.gain_pct), _num(x.floor_pct)])
              for x in lines)]  # fmt: skip


def main(argv: Sequence[str] | None = None, echo: Callable[[str], None] = print) -> int:
    """The reader-vs-judge table and O48's rule; 2 on a refused input
    (the table first when the rows were read, then why)."""
    parser = argparse.ArgumentParser(prog="ideas_picks", description=fable_rule.__doc__)
    parser.add_argument("results", type=Path)
    args = parser.parse_args(argv)
    try:
        lines = readout(args.results)
    except (OSError, ValueError) as error:
        echo(f"error: {error}")
        return 2
    for x in (*table(lines), ""):
        echo(x)
    try:
        verdict = fable_rule(lines)
    except ValueError as error:
        echo(f"error: {error}")
        return 2
    echo(f"O48's rule: {verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
