"""Ve: the ``ideas-slice`` suite, X1's execution slice (spec-idea-lab 6.3,
O36.2; 6.5's shadow judge).

Inputs, read and checked before any spend: X1's results
(``$LIVE_SLICE_IDEAS``, comma-separated results files of Vd's dispatches:
their ``ideas-idea``, ``ideas-reply`` and ``ideas-audit`` rows) and Vb's
results (``$LIVE_SLICE_MARKER``, scored offline by
``ideas_marker.score_results``: which candidate passed O37, or none).

The pick, per configuration X1-0 to X1-3 and library (``$LIVE_SLICE_REPOS``,
at most two a dispatch of sqlparse, pyparsing, tomli and the control
sortedcontainers): the configuration's returned, efficiency, non-proposal
ideas that are **new to today's generator**. The signal is the pooled
auditor's ``duplicate_of`` (spec 6.2's "share new to today's generator"
against the same-day arm A): an idea is new when its duplicate class (the
audited ideas joined by the auditor's duplicate links, either way) holds no
arm-A idea; an idea outside the audit is not known new and never picked;
one idea a class (the first in pool order); one the auditor found
infeasible for another reason stays eligible (the marker ranks it). Ranked by the validated marker,
each idea graded by the best-validated marker that did not write it (6.1's
independence rule: O37's choice, else the other candidate): the first
``SHOWN_MAX`` in pool order go to each grader they need, once per set, as
Vb's own blind request (``ideas_marker.ask``: counted, capped); an idea
takes its grader's score, ties and unanswered ideas fall to pool order;
the top ``TOP`` run. With no candidate past O37 the pool's order (the
pipeline's own: each configuration's ideas as its reviewer was shown them)
is the fallback, and every row says so (``selection``). O39: Opus 5.5 passed
O37 and Opus 5 did not, so an idea whose recorded model is Opus 5.5 (the
leap in every configuration, X1-1's Opus 5.5 lens) takes Opus 5's grade;
each trial and marker row says whether its grader passed O37
(``grader_validated``, ``validated``: Vb's ``passed``, never a constant,
checked against Vb's verdict row when the job wrote one), and each marker
row which shown ideas take its score (``grades``).

Each pick is a ``Hypothesis`` of its lane idea (the pipeline's rationale
layout; the reviewer's plan line is not in Vd's rows) and each
(configuration, library) one normal engine loop: ``discovery_oss
.start_arm_loop`` (``oss.start_oss_loop`` on a fresh clone, every pick
trialled in its one round, then the combine), the global settings' engine
(Opus 5.5, Step 3's noise rule, ``OP_COUNT_JUDGE`` on: asserted in the
module fixture, again before the markers' run, and in each loop's judges
before it runs; the op-count column is checked on every verdict after the
records), ``discovery.run_engine`` (every corpus guard). Caps: a trial
``TRIAL_USD`` (E2's worst case), the markers' run each needed request's
worst case; a dispatch's worst case stays under ``X1_FUSE_USD``.

O40/O41: before its loops, each library's lens-lane pool (X1-0 to X1-3) is
ranked by ``ideas_pool.rank_library``'s tournament (the one implementation
the ``ideas-pool`` suite runs on the other four libraries), on the markers'
one clone of the hot code; its worst case (``POOL_LIBRARY_USD``, priced on
``ideas_pool.POOL_BOUND``) is in the need.

Recorded, never asserted (``$LIVE_RESULTS_PATH``): every marker request
(``ideas-slice-marker``), every pooled set and ranking (``ideas-pool-set``,
``ideas-pool-result``), per trial its idea in full, its source keys
(repo, arm, label, position: the ``ideas-idea`` row's), selection, verdict,
gain, floor and op counts (``ideas-slice-trial``), and per (configuration,
library) the combine summary (``ideas-slice-combine``). Model-derived text
is redacted and chunked.
"""

from __future__ import annotations

import functools
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Literal

from e2e.conftest import Isolation

from autonomous_ai_agents.clients.structured import clamp_unit
from autonomous_ai_agents.common import models
from autonomous_ai_agents.common.config import Settings, settings
from autonomous_ai_agents.optimization.generate import MAX_EXPECTED_GAIN
from autonomous_ai_agents.optimization.idea_dedupe import _ReplyIdea
from autonomous_ai_agents.optimization.judges import OP_COUNT_JUDGE, primary_metric
from autonomous_ai_agents.orchestrator.main import EngineRunResult
from autonomous_ai_agents.orchestrator.nodes import op_count_cell

from . import discovery_oss as dx
from . import ideas_marker as im
from . import ideas_pool as ipool
from . import ideas_probe as ip
from .conftest import LiveRun, StartLive, redact_keys, suite_cap
from .corpus import CorpusOutcome, Loop
from .discovery import OPUS, ceil_usd, run_engine
from .discovery_io import ResultsSink
from .discovery_oss import OSS_TRIAL_CAP_USD, start_arm_loop
from .ideas_pool import MARKER_TITLE_MAX, IdeaRow, check_verdict
from .ideas_probe import X1_FUSE_USD, _chunks, _fit, _Strict
from .oss import PRODUCTION, GitPolicy, OssRepo

SLICE_CONFIGS: Final = ("X1-0", "X1-1", "X1-2", "X1-3")
SLICE_REPOS: Final = ("sqlparse", "pyparsing", "tomli", "sortedcontainers")
SLICE_LIBRARIES: Final = tuple(
    next(r for r in dx.OSS_SELECTABLE if r.name == name) for name in SLICE_REPOS
)
CONTROL: Final = "sortedcontainers"  # the reported control (spec 6.2)
TOP: Final = 3  # spec 6.3: the top 2-3 ideas a configuration
SHOWN_MAX: Final = 10  # Vb validated orders of at most 10 ideas (oss-ab's n)
DISPATCH_REPOS: Final = 2  # two dispatches of two libraries (spec 6.3)
TRIAL_USD: Final = OSS_TRIAL_CAP_USD  # E2's per-trial worst case, 2.50
MARKER_LIBRARY_USD: Final = ceil_usd(len(SLICE_CONFIGS) * im.set_usd())
POOL_LIBRARY_USD: Final = ipool.library_usd()  # O41's tournament at its bound
LOOP_MINUTES: Final = 9  # L2b: 42 min / 10 OSS loops of up to 3 trials, x2
CLONE_MINUTES: Final = 1
JOB_MINUTES: Final = 150  # ci.yml's ideas-slice timeout
REPOS_ENV: Final = "LIVE_SLICE_REPOS"
IDEAS_ENV: Final = "LIVE_SLICE_IDEAS"
MARKER_ENV: Final = "LIVE_SLICE_MARKER"
TRIAL_EXPERIMENT: Final = "ideas-slice-trial"
COMBINE_EXPERIMENT: Final = "ideas-slice-combine"
MARKER_EXPERIMENT: Final = "ideas-slice-marker"
FALLBACK: Final = "the pipeline's order (the auditor's pool ids), no marker"
NO_IDEA: Final = "no eligible idea: no loop"
NO_DECISION: Final = im.Decision(None, im.NO_MARKER, (), ())

# ---------------------------------------------------------------------------
# The plan: need, minutes, fuse, refused before any spend
# ---------------------------------------------------------------------------


def loop_cap(picks: int) -> float:
    return ceil_usd(picks * TRIAL_USD)


@dataclass(frozen=True)
class SlicePlan:
    repos: tuple[OssRepo, ...]
    ideas: tuple[Path, ...] = ()  # X1's results files
    marker: Path | None = None  # Vb's results file

    def library_cap(self) -> float:
        return ceil_usd(MARKER_LIBRARY_USD + POOL_LIBRARY_USD
                        + len(SLICE_CONFIGS) * loop_cap(TOP))  # fmt: skip

    def minutes(self) -> int:
        asks = len(im.MARKERS) * im.REQUEST_MINUTES
        pooled = CLONE_MINUTES + ipool.library_minutes()
        return len(self.repos) * (pooled + len(SLICE_CONFIGS) * (asks + LOOP_MINUTES))


def slice_need(plan: SlicePlan) -> float:
    return len(plan.repos) * plan.library_cap()


def check_fuse(plan: SlicePlan) -> None:
    """A dispatch's worst case under the 80 USD fuse, its minutes the job's."""
    need, minutes = slice_need(plan), plan.minutes()
    if need > min(X1_FUSE_USD, dx.CAP_CEILING_USD) or minutes > JOB_MINUTES:
        raise ValueError(f"the slice on {len(plan.repos)} libraries needs {need:.2f} "
                         f"USD and {minutes} minutes, past the {X1_FUSE_USD:g} USD "
                         f"fuse or the {JOB_MINUTES}-minute job")  # fmt: skip


def slice_plan(environ: Mapping[str, str]) -> SlicePlan:
    names = dx._keys(environ, REPOS_ENV, SLICE_REPOS)
    if names is None:
        raise ValueError(f"{REPOS_ENV}: name the dispatch's libraries ({SLICE_REPOS})")
    if len(names) > DISPATCH_REPOS:
        raise ValueError(f"{REPOS_ENV}: at most {DISPATCH_REPOS} libraries a dispatch")
    marker = ipool.paths(environ, MARKER_ENV, "marker results")
    if len(marker) > 1:
        raise ValueError(f"{MARKER_ENV}: Vb's one results file")
    plan = SlicePlan(tuple(r for r in SLICE_LIBRARIES if r.name in names),
                     ipool.paths(environ, IDEAS_ENV, "X1 results"), (*marker, None)[0])  # fmt: skip
    check_fuse(plan)
    need, cap = slice_need(plan), suite_cap(environ)
    if cap < need:
        raise ValueError(
            f"suite cap {cap:.2f} USD is below the slice's need {need:.2f}"
        )
    return plan


def check_engine(base: Settings) -> None:
    """The shadow op-count judge on (6.5) and the Opus 5.5 editor (6.3)."""
    if not base.OP_COUNT_JUDGE:
        raise ValueError("OP_COUNT_JUDGE must be on for the slice (spec 6.5)")
    if base.ENGINE_MODEL != OPUS or base.EDITOR_MODEL not in (None, OPUS):
        raise ValueError("the slice's trials run the Opus 5.5 engine and editor")


def check_judges(loop: Loop) -> None:
    if not any(j.name == OP_COUNT_JUDGE for j in loop.context.judges):
        raise AssertionError(f"the loop's judges hold no {OP_COUNT_JUDGE} judge")


# ---------------------------------------------------------------------------
# X1's rows: strict, joined, new to today's generator
# ---------------------------------------------------------------------------


class _AuditRow(_Strict):
    experiment: Literal["ideas-audit"]
    repo: str
    arm: str
    id: str
    title: str
    lane: str
    tier: int
    in_result: bool
    own: str | None
    auditor: str | None
    reason: str | None
    duplicate_of: str | None


_KINDS: Final[Mapping[str, type[_Strict]]] = {
    ip.IDEA_EXPERIMENT: IdeaRow, ip.AUDIT_EXPERIMENT: _AuditRow,
    ip.REPLY_EXPERIMENT: ipool.ReplyRow,
}  # fmt: skip


@dataclass(frozen=True)
class Idea:
    row: IdeaRow
    item: _ReplyIdea  # the lane reply's whole idea
    pool: int  # its auditor id's number: pool order
    family: int  # its duplicate class: the class's first pool number


def _number(audit_id: str) -> int:
    return int(audit_id[1:])


def families(audits: Mapping[str, _AuditRow]) -> dict[str, int]:
    """Each audited id's class under the auditor's duplicate links."""
    parent = {i: i for i in audits}

    def find(i: str) -> str:
        while parent[i] != i:
            i = parent[i]
        return i

    for i, a in audits.items():
        if (a.auditor, a.reason) == (
            ip._BAD,
            ip._DUPLICATE,
        ) and a.duplicate_of in parent:
            x, y = sorted((find(i), find(str(a.duplicate_of))), key=_number)
            parent[y] = x
    return {i: _number(find(i)) for i in audits}


def _library(
    repo: str, rows: Sequence[_Strict]
) -> dict[tuple[str, str], tuple[Idea, ...]]:
    audits = {a.id: a for a in rows if isinstance(a, _AuditRow)}
    if not audits:
        raise ValueError(f"{repo}: no ideas-audit rows: newness is unknown")
    texts = ipool.reply_texts(repo, rows)
    family = families(audits)
    taken = {family[i] for i, a in audits.items() if a.arm == ip.ARM_A.key}
    by_key: dict[tuple[str, str, str], str | None] = {}
    for i, a in audits.items():
        key = (a.arm, a.lane, redact_keys(a.title))
        by_key[key] = None if key in by_key else i  # ambiguous: never joined
    found: dict[str, list[Idea]] = {c: [] for c in SLICE_CONFIGS}
    for row in (r for r in rows if isinstance(r, IdeaRow)):
        aid = by_key.get((row.arm, row.lane, row.title))
        if row.arm not in found or not row.returned or row.proposal or aid is None:
            continue
        item = ipool.reply_item(row, texts)
        if audits[aid].auditor is not None and item.change_class == "efficiency":
            found[row.arm].append(Idea(row, item, _number(aid), family[aid]))
    out: dict[tuple[str, str], tuple[Idea, ...]] = {}
    for config, ideas in found.items():
        seen, kept = set(taken), []
        for idea in sorted(ideas, key=lambda i: i.pool):  # one idea a class
            if idea.family not in seen:
                seen.add(idea.family)
                kept.append(idea)
        out[(repo, config)] = tuple(kept)
    return out


def load_ideas(
    paths: Sequence[Path], repos: Sequence[str]
) -> dict[tuple[str, str], tuple[Idea, ...]]:
    """The eligible ideas per (library, configuration), in pool order."""
    rows = ipool.read_rows(paths, _KINDS)
    out: dict[tuple[str, str], tuple[Idea, ...]] = {}
    for repo in repos:
        out.update(_library(repo, rows.get(repo, [])))
    return out


# ---------------------------------------------------------------------------
# The ranking: each idea graded by the validated marker that did not write it
# ---------------------------------------------------------------------------


def grader_order(decision: im.Decision) -> tuple[im.Marker, ...]:
    """O37's choice first, then the other candidate (6.1's runner-up): under
    O39 Opus 5.5, then Opus 5 for the ideas Opus 5.5 wrote (``grader``)."""
    chosen = next((m for m in im.MARKERS if m.key == decision.chosen), None)
    return () if chosen is None else (chosen, *(m for m in im.MARKERS if m != chosen))


def grader(idea: Idea, order: Sequence[im.Marker]) -> im.Marker | None:
    """The first marker in ``order`` whose model is not the idea's recorded one."""
    return next((m for m in order if m.model != idea.row.model), None)


def shown(ideas: Sequence[Idea]) -> tuple[Idea, ...]:
    return tuple(ideas[:SHOWN_MAX])


def rank_set(repo: str, config: str, ideas: Sequence[Idea]) -> im.RankSet:
    """Vb's request shape: title and class, never an outcome (labels none);
    a title past Vb's bound is clipped, never refused."""
    rows = tuple(
        im.RankRow(run_id=0, arm=config, change_class="efficiency",
                   experiment="E5-oss-ab-rank", gain_pct=None, guard="unmeasured",
                   noise_floor_pct=None, rank=k, rep=1, repo=repo, title=i.row.title[:MARKER_TITLE_MAX],
                   verdict="unmeasured")
        for k, i in enumerate(ideas, 1)
    )  # fmt: skip
    return im.RankSet(repo, 1, config, rows)


def hypothesis(idea: Idea) -> models.Hypothesis:
    """The lane idea as the pipeline hands it on (``_hypothesis``'s layout)."""
    item = idea.item
    cells = (f"claimed_cell:{c.value}" for c in dict.fromkeys(item.morph_cells))
    return models.Hypothesis(
        project_id="x1-slice", source=models.HypothesisSource.novel, title=item.title,
        rationale=(f"{item.change_summary}\nWhy it should win: "
                   f"{item.justification_summary}\nPrecondition: {item.precondition}"
                   f"\nWhy the output stays the same: {item.equivalence_summary}"),
        change_class=models.ChangeClass.efficiency,
        expected_gain=max(0.0, min(MAX_EXPECTED_GAIN, item.expected_gain)),
        provability=clamp_unit(item.provability), risk=clamp_unit(item.risk),
        tags=(f"lane:{idea.row.lane}", f"claimed_tier:{item.tier.value}",
              f"claimed_mechanism:{item.mechanism.value}", *cells,
              f"claimed_typicality:{item.typicality.value}"),
    )  # fmt: skip


@dataclass(frozen=True)
class Pick:
    idea: Idea
    grader: str | None
    score: float | None
    rank: int
    hypothesis: models.Hypothesis


def picks(
    ideas: Sequence[Idea],
    order: Sequence[im.Marker],
    replies: Mapping[str, im.MarkerReply],
) -> tuple[Pick, ...]:
    scored: list[tuple[Idea, str | None, float | None]] = []
    for k, idea in enumerate(shown(ideas)):
        g = grader(idea, order)
        r = None if g is None else replies.get(g.key)
        scores = None if r is None else r.scores
        scored.append(
            (idea, None if g is None else g.key, None if scores is None else scores[k])
        )
    scored.sort(key=lambda t: (t[2] is None, -(t[2] or 0.0), t[0].pool))
    return tuple(
        Pick(i, g, s, n, hypothesis(i)) for n, (i, g, s) in enumerate(scored[:TOP], 1)
    )


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


def _op_count(v: models.Verdict | None) -> dict[str, object]:
    found = () if v is None else v.judge_results
    j = next((x for x in found if x.judge == OP_COUNT_JUDGE), None)
    return {
        "present": j is not None, "cell": None if v is None else op_count_cell(v.judge_results),
        "base": None if j is None or j.baseline is None else j.baseline.mean,
        "trial": None if j is None or j.trial is None else j.trial.mean,
        "change": None if j is None else j.details.get("change"),
    }  # fmt: skip


def _primary(result: EngineRunResult | None) -> models.JudgeResult | None:
    comb = None if result is None else result.state["combination"]
    if result is None or comb is None:
        return None
    metric = primary_metric(result.state["objectives"])
    return next((j for j in comb.judge_results if j.metric == metric), None)


def check_op_column(result: EngineRunResult | None) -> None:
    verdicts = () if result is None else result.state["verdicts"]
    missing = [v.hypothesis_id for v in verdicts if not _op_count(v)["present"]]
    if missing:
        raise AssertionError(f"no op-count column on the verdicts of {missing}")


@dataclass
class SliceRecorder:
    plan: SlicePlan
    sink: ResultsSink
    base: Settings = field(default_factory=lambda: settings)
    ideas: dict[tuple[str, str], tuple[Idea, ...]] | None = None
    decision: im.Decision | None = None
    pools: dict[str, tuple[ipool.PoolIdea, ...]] | None = None  # O41's, by library

    def __post_init__(self) -> None:
        check_engine(self.base)
        if self.ideas is None and not self.plan.ideas:
            raise ValueError(f"{IDEAS_ENV}: name X1's results files")
        if self.decision is None and self.plan.marker is None:
            raise ValueError(f"{MARKER_ENV}: name Vb's results file")
        names = [r.name for r in self.plan.repos]
        if self.ideas is None:
            self.ideas = load_ideas(self.plan.ideas, names)
        if self.pools is None:
            self.pools = ipool.load_pools(self.plan.ideas, names)
        if self.decision is None and self.plan.marker is not None:
            marker = self.plan.marker
            self.decision = check_verdict(marker, im.score_results(marker)[1])
        ipool.check_priced(self.pools or {}, self.decision or NO_DECISION)

    @property
    def order(self) -> tuple[im.Marker, ...]:
        return () if self.decision is None else grader_order(self.decision)

    @property
    def selection(self) -> str:
        d = self.decision or NO_DECISION
        if d.chosen is None:
            return f"fallback ({d.reason}): {FALLBACK}"
        return f"marker {d.chosen} ({d.reason})"

    def validated(self, key: str | None) -> bool | None:
        """Whether the grader ``key`` passed O37 (None: no grader)."""
        return None if key is None else key in (self.decision or NO_DECISION).passed

    def eligible(self, repo: str, config: str) -> tuple[Idea, ...]:
        return (self.ideas or {}).get((repo, config), ())

    def marker(
        self, repo: str, config: str, r: im.MarkerReply, ideas: Sequence[Idea]
    ) -> None:
        e = r.exchange
        self.sink.write({
            "experiment": MARKER_EXPERIMENT, "repo": repo, "arm": config,
            "marker": r.marker.key, "model": r.marker.model,
            "shown": [{"label": i.row.label, "position": i.row.position} for i in ideas],
            "grades": [grader(i, self.order) == r.marker for i in ideas],
            "validated": self.validated(r.marker.key),
            "scores": None if r.scores is None else list(r.scores),
            "error": None if r.error is None else _fit(redact_keys(r.error)),
            "cost_usd": r.cost_usd, "counted": 0 if e is None else e.counted,
            "sent": e is not None and e.sent,
            "chunks": _chunks("" if e is None else redact_keys(e.reply)),
        })  # fmt: skip

    def record(self, repo: str, config: str, chosen: Sequence[Pick], guard: str,
               cost_usd: float, result: EngineRunResult | None) -> None:  # fmt: skip
        hyps = [p.hypothesis for p in chosen]
        ranks = dx.rank_rows(repo, 1, config, hyps, result, guard=guard)
        verdicts: dict[str, models.Verdict] = {}
        for v in () if result is None else result.state["verdicts"]:
            verdicts.setdefault(v.hypothesis_id, v)
        guard = _fit(redact_keys(guard))
        for p, r in zip(chosen, ranks, strict=True):
            row, item = p.idea.row, p.idea.item
            self.sink.write({
                "experiment": TRIAL_EXPERIMENT, "repo": repo, "arm": config,
                "label": row.label, "position": row.position, "lane": row.lane,
                "model": row.model, "audit_id": f"i{p.idea.pool:02d}",
                "selection": self.selection, "grader": p.grader, "score": p.score,
                "grader_validated": self.validated(p.grader),
                "rank": p.rank, "title": redact_keys(item.title),
                "mechanism": item.mechanism.value, "cells": list(row.cells),
                "path": row.path, "target": row.target,
                "rationale": _chunks(redact_keys(p.hypothesis.rationale)),
                "hypothesis_id": p.hypothesis.id, "verdict": r.verdict,
                "gain_pct": r.gain_pct, "floor_pct": r.noise_floor_pct,
                "op_count": _op_count(verdicts.get(p.hypothesis.id)), "guard": guard,
            })  # fmt: skip
        self.combine(repo, config, chosen, guard, cost_usd, result,
                     kept=sum(r.verdict == "keep" for r in ranks))  # fmt: skip

    def combine(self, repo: str, config: str, chosen: Sequence[Pick], guard: str,
                cost_usd: float, result: EngineRunResult | None, kept: int = 0) -> None:  # fmt: skip
        comb = None if result is None else result.state["combination"]
        j = _primary(result)
        self.sink.write({
            "experiment": COMBINE_EXPERIMENT, "repo": repo, "arm": config,
            "selection": self.selection, "eligible": len(self.eligible(repo, config)),
            "picked": len(chosen), "kept": kept, "combined": comb is not None,
            "holds": None if comb is None else comb.holds,
            "applied": 0 if comb is None else len(comb.applied_trial_ids),
            "fallback": comb is not None and comb.fallback_trial_id is not None,
            "gain_pct": None if j is None else dx._pct(j.gain),
            "floor_pct": None if j is None else dx._pct(j.noise_floor),
            "delivered": result is not None and result.state["delivery"] is not None,
            "summary": _chunks("" if comb is None else redact_keys(comb.summary)),
            "cost_usd": cost_usd, "guard": guard,
            # D64's cost line for the report (Vf); 0 / 0.0 when no loop ran
            "seeded_calls": 0 if result is None else result.state["seeded_calls"],
            "seeded_cost_usd": 0.0 if result is None else result.state["seeded_cost_usd"],
        })  # fmt: skip


# ---------------------------------------------------------------------------
# One library
# ---------------------------------------------------------------------------


def _ask(recorder: SliceRecorder, repo: OssRepo, live: StartLive,
         hot: Callable[[], im.HotCode], base: Settings) -> dict[str, dict[str, im.MarkerReply]]:  # fmt: skip
    """Each configuration's shown set once to each grader it needs."""
    order = recorder.order
    needs = {c: tuple(dict.fromkeys(g for i in shown(recorder.eligible(repo.name, c))
                                    if (g := grader(i, order)) is not None))
             for c in SLICE_CONFIGS}  # fmt: skip
    replies: dict[str, dict[str, im.MarkerReply]] = {c: {} for c in SLICE_CONFIGS}
    cap = ceil_usd(math.fsum(im.request_worst(m) for ms in needs.values() for m in ms))
    if cap == 0:
        return replies
    run = live(cap)
    for c in SLICE_CONFIGS:
        ideas = shown(recorder.eligible(repo.name, c))
        for m in needs[c]:
            r = im.ask(m, run, rank_set(repo.name, c, ideas), hot(), base=base)
            recorder.marker(repo.name, c, r, ideas)
            replies[c][m.key] = r
    assert len(run.capture.messages()) == len(run.records)
    return replies


def _record(recorder: SliceRecorder, repo: str, config: str, chosen: Sequence[Pick],
            run: LiveRun, seen: list[EngineRunResult | None], outcome: CorpusOutcome,
            result: EngineRunResult | None) -> None:  # fmt: skip
    seen.append(result)
    recorder.record(repo, config, chosen, outcome.guard, run.spent_usd, result)


def run_library(
    repo: OssRepo,
    *,
    live: StartLive,
    root: Path,
    isolation: Isolation,
    recorder: SliceRecorder,
    policy: GitPolicy = PRODUCTION,
    base: Settings = settings,
) -> None:
    """The markers' run, the pooled tournament (O41) on the same clone's hot
    code, then one engine loop per configuration's picks."""
    check_engine(base)
    hot = ipool.hot_of(repo, root, policy)
    replies = _ask(recorder, repo, live, hot, base)
    ipool.rank_library(repo.name, (recorder.pools or {}).get(repo.name, ()),
                       recorder.decision or NO_DECISION, live=live, hot=hot,
                       sink=recorder.sink, base=base)  # fmt: skip
    for c in SLICE_CONFIGS:
        chosen = picks(recorder.eligible(repo.name, c), recorder.order, replies[c])
        if not chosen:
            recorder.combine(repo.name, c, (), NO_IDEA, 0.0, None)
            continue
        run = live(loop_cap(len(chosen)))
        loop = start_arm_loop(repo, run, root / c, isolation,
                              [p.hypothesis for p in chosen], policy=policy)  # fmt: skip
        check_judges(loop)
        seen: list[EngineRunResult | None] = []
        record = functools.partial(_record, recorder, repo.name, c, chosen, run, seen)
        run_engine(loop, run, isolation, model=base.ENGINE_MODEL, record=record)
        run.note(_fit(f"SLICE {repo.name} {c}: {len(chosen)} trial(s), "
                      f"{run.spent_usd:.3f} USD; {recorder.selection}"))  # fmt: skip
        check_op_column(seen[-1])
