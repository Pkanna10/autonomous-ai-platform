"""The idea pipeline, a ``HypothesisGenerator`` (Step 3 Wave 2, N4a; spec
amendment 3.4, 4.2b, D43-D59, D64, D65, section 5).

One ``generate`` call: S0 reads the hot code at the base commit (no code:
today's generator, unchanged); S1, the obvious lane, names the defaults;
S2 sends the lens lanes and the leap in parallel; S4a filters
deterministically; S3, the reviewer, may only remove; S4b picks the
portfolio and interleaves it with S1. A second call in a run is S1 only.

Money (D48, section 5): before each stage every request is counted once
(free) and priced at its worst case; the parent ``Budget`` checks the
stage's sum once (S2 not fitting is skipped whole, a ``discovery_unaffordable``
event, never raised; S1 not fitting raises ``BudgetExceeded`` as today's
generator does). Each request then runs on its own child budget capped at
its estimate, which ``call()`` uses instead of a recount, so a charged
timeout ends the lane instead of being retried; the parent records every
child's spend on this thread, in a ``finally``, before any lane's error is
raised. Lanes are dropped on any soft failure (noted, never re-sent); only a
configuration error or a bug propagates, after the recording. Lanes never
touch the parent ``Budget``.

Bounds this unit owns: the result holds at most ``n`` obvious ideas, the
portfolio's ``IDEAS_PORTFOLIO_MAX`` and, after them, ``novel`` ideas (parked by
the node) only while the total stays within ``n + IDEAS_PORTFOLIO_MAX``: a
model-asserted label cannot let more through. S1 shows no examples (D45:
today's prompt plus code; the bank is for the lenses and the leap).
"""

from __future__ import annotations

import threading
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Final

from autonomous_ai_agents.clients.budget import Budget
from autonomous_ai_agents.clients.cost import preflight_estimate
from autonomous_ai_agents.clients.structured import (
    Fence,
    check_effort,
    count_note,
    hotspot_rows,
    shorten,
    shown,
)
from autonomous_ai_agents.clients.transport import (
    LLMRequest,
    LLMResult,
    LLMTransport,
    call,
)
from autonomous_ai_agents.common.config import (
    Effort,
    Role,
    Settings,
    role_chain,
    settings,
)
from autonomous_ai_agents.common.errors import (
    BudgetExceeded,
    LLMRequestError,
    LLMUnavailable,
    UnusableReplyError,
)
from autonomous_ai_agents.common.models import (
    ChangeClass,
    EventLevel,
    Hotspot,
    Hypothesis,
    HypothesisSource,
    Lesson,
    Objective,
    Project,
    ProjectUnderstanding,
    Technique,
)
from autonomous_ai_agents.common.repo_read import RepoReader
from autonomous_ai_agents.optimization.idea_context import (
    IdeaReadLimits,
    amdahl_ceiling,
    read_code_context,
    render_data_block,
)
from autonomous_ai_agents.optimization.idea_lanes import (
    lane_request,
    on_the_table,
    read_lane_reply,
)
from autonomous_ai_agents.optimization.idea_portfolio import (
    deterministic_filter,
    lesson_titles,
    portfolio,
    rotation,
    signature,
)
from autonomous_ai_agents.optimization.idea_prompts import (
    IDEAS_SCHEMA,
    IDEAS_SYSTEM_PROMPT,
    Example,
    example_rotation,
    lane_instruction,
    with_think,
)
from autonomous_ai_agents.optimization.idea_review import (
    apply_review,
    read_review,
    review_request,
    unreviewed,
)
from autonomous_ai_agents.optimization.idea_types import (
    CodeContext,
    GenerateEvent,
    IdeaCandidate,
    IdeaStats,
    Lane,
    ReviewReason,
    ReviewVerdict,
)
from autonomous_ai_agents.optimization.sources import (
    GenerateResult,
    HypothesisGenerator,
)
from autonomous_ai_agents.research.playbook import (
    ResearchSystem,
    repo_fence,
    research_system,
)

NO_CODE_CONTEXT: Final = "idea pipeline: no code context"
_ROLES: Final[tuple[Role, ...]] = ("lane", "leap", "reviewer")
_SOFT: Final = (LLMUnavailable, LLMRequestError, UnusableReplyError, BudgetExceeded)
"""What ends one request without ending the pipeline (D48): noted, charged."""
_GATE_CODES: Final = frozenset({"no_anchor", "ceiling_unknown", "below_gate"})
_CLASS_ORDER: Final = {
    ChangeClass.efficiency: 0,
    ChangeClass.behaviour: 1,
    ChangeClass.novel: 2,
}


@dataclass
class _Job:
    """One request of a stage: its worst case and the child budget it runs on."""

    label: str
    transport: LLMTransport
    request: LLMRequest
    estimate: float
    child: Budget
    result: LLMResult | None = None
    error: Exception | None = None


@dataclass
class _Call:
    """The facts and the running record of one ``generate`` call."""

    project: Project
    objective: Objective
    hotspots: Sequence[Hotspot]
    budget: Budget
    research: ResearchSystem
    fence: Fence
    context: CodeContext
    prefix: str
    index: dict[tuple[str, str], list[str]]
    notes: list[str]
    start: float
    events: list[GenerateEvent] = field(default_factory=list)
    per_lane: dict[Lane, int] = field(default_factory=dict)
    read: list[IdeaCandidate] = field(default_factory=list)
    stops: dict[str, str | None] = field(default_factory=dict)
    cache_reads: int = 0
    verdicts: Counter[ReviewVerdict] = field(default_factory=Counter)
    gate_passed: int = 0
    non_obvious: int = 0


class IdeaPipelineGenerator:
    """The five-stage pipeline on the ``lane``, ``leap`` and ``reviewer`` roles.

    ``reader`` gives the project's git objects (``None``: no code context);
    ``fallback`` is today's generator for the no-code path (``None``: an
    empty result, noted). Each transport must bill its role's chain and
    accept its effort, checked here, before any spend.
    """

    def __init__(
        self,
        transports: Mapping[Role, LLMTransport],
        *,
        reader: Callable[[Project], RepoReader] | None = None,
        config: Settings = settings,
        sleep: Callable[[float], None] = time.sleep,
        fallback: HypothesisGenerator | None = None,
    ) -> None:
        efforts = {
            "lane": config.IDEAS_LANE_EFFORT,
            "leap": config.IDEAS_LEAP_EFFORT,
            "reviewer": config.IDEAS_REVIEWER_EFFORT,
        }
        self._transports: dict[Role, LLMTransport] = {}
        self._efforts: dict[Role, Effort | None] = {}
        for role in _ROLES:
            transport = transports.get(role)
            if transport is None:
                raise ValueError(f"the idea pipeline needs a {role} transport")
            expected = role_chain(config, role)
            if tuple(transport.chain) != expected:
                raise ValueError(f"the {role} transport bills {list(transport.chain)}"
                                 f", not the {role} chain {list(expected)}")  # fmt: skip
            self._efforts[role] = check_effort(efforts[role], transport.chain)
            self._transports[role] = transport
        self._reader, self._cfg, self._sleep = reader, config, sleep
        self._fallback = fallback

    def generate(
        self,
        *,
        project: Project,
        understanding: ProjectUnderstanding | None,
        hotspots: Sequence[Hotspot],
        objective: Objective,
        techniques: Sequence[Technique],
        lessons: Sequence[Lesson],
        avoid_titles: Sequence[str],
        n: int,
        budget: Budget,
        commit: str | None = None,
        run_id: str | None = None,
        call_index: int = 0,
        protected: Sequence[str] = (),
        read_deny: Sequence[str] = (),
    ) -> GenerateResult:
        notes: list[str] = []
        research = research_system(IDEAS_SYSTEM_PROMPT, techniques, notes)
        fence = repo_fence(research)
        context = CodeContext()
        if commit is not None and self._reader is not None:
            limits = IdeaReadLimits.from_settings(self._cfg)
            context = read_code_context(
                self._reader(project), commit, hotspots, fence=fence,
                protected=protected, read_deny=read_deny, limits=limits, notes=notes,
            )  # fmt: skip
        if not context.documents:
            notes.append(NO_CODE_CONTEXT)
            if self._fallback is None:
                return GenerateResult(notes=tuple(notes))
            today = self._fallback.generate(
                project=project, understanding=understanding, hotspots=hotspots,
                objective=objective, techniques=techniques, lessons=lessons,
                avoid_titles=avoid_titles, n=n, budget=budget, commit=commit,
                run_id=run_id, call_index=call_index, protected=protected,
                read_deny=read_deny,
            )  # fmt: skip
            return GenerateResult(
                today.hypotheses, (*notes, *today.notes), today.events, today.stats
            )
        prefix = render_data_block(
            context, project=project, objective=objective,
            understanding=understanding, hotspots=hotspots, fence=fence, notes=notes,
        )  # fmt: skip
        index: dict[tuple[str, str], list[str]] = {}
        for spot in hotspot_rows(hotspots, fence, [])[1]:  # the shown profile only
            index.setdefault((spot.file_path, spot.symbol), []).append(spot.id)
        c = _Call(project, objective, hotspots, budget, research, fence, context,
                  prefix, index, notes, budget.spent_usd)  # fmt: skip
        named = [*avoid_titles, *(t.name for t in research.by_slug.values())]
        s1 = self._s1(c, n, named)
        if call_index >= 1:
            notes.append("second generator call: S1 only, earlier titles avoided (D48)")
            return self._result(c, s1, n)
        seed = run_id if run_id is not None else f"{commit}:{project.id}"
        lanes = (
            *self._cfg.IDEAS_LENSES,
            *((Lane.leap,) if self._cfg.IDEAS_LEAP_N else ()),
        )
        order = rotation(seed, lanes)
        examples = example_rotation(seed, lanes, exclude=(project.name,))
        table = on_the_table([*(i.title for i in s1), *named], fence, notes)
        others = self._s2(c, lanes, order, table, examples)
        if others is None:
            return self._result(c, s1, n)
        survivors = self._s4a(c, s1, others, avoid_titles, lessons)
        reviewed = self._s3(c, survivors)
        olds = [i for i in reviewed if i.lane is Lane.obvious]
        news = [i for i in reviewed if i.lane is not Lane.obvious]
        picked = portfolio(olds, news, rotation=order, notes=notes,
                           minimum=self._cfg.IDEAS_PORTFOLIO_MIN,
                           maximum=self._cfg.IDEAS_PORTFOLIO_MAX)  # fmt: skip
        return self._result(c, picked, n)

    # ----------------------------------------------------------------------
    # The stages
    # ----------------------------------------------------------------------

    def _s1(self, c: _Call, n: int, named: Sequence[str]) -> list[IdeaCandidate]:
        """The obvious lane; a soft failure leaves the named defaults alone."""
        table = on_the_table(named, c.fence, c.notes)
        job = self._lane_job(c, Lane.obvious, n, table, ())
        c.budget.check(job.estimate)  # BudgetExceeded: unaffordable, as today
        self._run([job], c.budget)
        return self._read(c, Lane.obvious, job, n)

    def _s2(
        self,
        c: _Call,
        lanes: Sequence[Lane],
        order: Sequence[Lane],
        table: str,
        examples: Mapping[Lane, tuple[Example, ...]],
    ) -> list[IdeaCandidate] | None:
        """The lens lanes and the leap, reserved as one stage (``None``: the
        reservation did not fit; S2 is skipped whole)."""
        cfg = self._cfg
        sizes = {lane: cfg.IDEAS_LANE_N for lane in cfg.IDEAS_LENSES}
        sizes[Lane.leap] = cfg.IDEAS_LEAP_N
        jobs = {lane: self._lane_job(c, lane, sizes[lane], table, examples[lane])
                for lane in lanes}  # fmt: skip
        total = sum(job.estimate for job in jobs.values())
        try:
            c.budget.check(total)
        except BudgetExceeded as exc:
            message = f"no lane request: the {len(jobs)} lanes may cost {total:.6f} USD"
            c.notes.append(f"{message}; S1's ideas returned alone ({exc})")
            c.events.append(GenerateEvent(
                code="discovery_unaffordable", message=message,
                level=EventLevel.warning, data={"stage": "lanes", "estimate_usd": total},
            ))  # fmt: skip
            return None
        self._run(list(jobs.values()), c.budget)
        found: list[IdeaCandidate] = []
        for lane in order:  # the run's lane order decides dedup (D52)
            found += self._read(c, lane, jobs[lane], sizes[lane])
        return found

    def _s4a(
        self,
        c: _Call,
        s1: Sequence[IdeaCandidate],
        others: Sequence[IdeaCandidate],
        avoid_titles: Sequence[str],
        lessons: Sequence[Lesson],
    ) -> tuple[IdeaCandidate, ...]:
        before = len(c.events)
        survivors = deterministic_filter(
            s1, others, floor=c.objective.min_relative_gain, objective=c.objective,
            avoid=avoid_titles, lesson_titles=lesson_titles(lessons),
            multiplier=self._cfg.IDEAS_AMDAHL_MULTIPLIER, notes=c.notes,
            shown_slugs=frozenset(c.research.by_slug), events=c.events,
        )  # fmt: skip
        gated = [e for e in c.events[before:] if e.data.get("reason") in _GATE_CODES]
        c.gate_passed = len(others) - len(gated)
        c.non_obvious = len(survivors) - len(s1)
        return survivors

    def _s3(
        self, c: _Call, ideas: Sequence[IdeaCandidate]
    ) -> tuple[IdeaCandidate, ...]:
        """The reviewer: a filter that may only remove (D49); every failure
        leaves every idea ``unknown`` with no plan."""
        cfg = self._cfg
        if not ideas:
            return ()
        reviewer = Fence.new(others=(c.fence.token, *c.fence.others))
        fences = (c.fence, reviewer)
        kept: tuple[IdeaCandidate, ...] | None = None
        why = "IDEAS_REVIEW is off"
        if cfg.IDEAS_REVIEW:
            think = with_think("", self._transports["reviewer"].chain[0]) != ""
            request, shown_ids = review_request(
                ideas, prefix=c.prefix, fence=c.fence, reviewer_fence=reviewer,
                max_ideas=cfg.IDEAS_REVIEW_MAX_IDEAS,
                max_tokens=cfg.IDEAS_REVIEWER_MAX_TOKENS,
                effort=self._efforts["reviewer"], notes=c.notes, think=think,
            )  # fmt: skip
            kept, why = self._review(c, ideas, request, shown_ids, fences)
        if kept is None:
            kept = unreviewed(ideas, fences=fences, why=why, notes=c.notes)
            c.verdicts.update(i.review for i in kept if i.review is not None)
        return kept

    def _review(
        self,
        c: _Call,
        ideas: Sequence[IdeaCandidate],
        request: LLMRequest,
        shown_ids: Sequence[str],
        fences: Sequence[Fence],
    ) -> tuple[tuple[IdeaCandidate, ...] | None, str]:
        """The reviewed ideas, or ``None`` and why the review is not used."""
        if not shown_ids:
            return None, "no idea could be shown to the reviewer"
        job = self._job("reviewer", "reviewer", request)
        try:
            c.budget.check(job.estimate)
        except BudgetExceeded:
            return None, "the reviewer is unaffordable"
        self._run([job], c.budget)
        self._stopped(c, job)
        if job.result is None:
            return None, f"the reviewer failed: {_failure(job)}"
        try:
            reply = read_review(job.result)
        except UnusableReplyError as exc:
            return None, f"the reply is unusable: {exc}"
        removed: list[tuple[IdeaCandidate, ReviewReason]] = []
        kept = apply_review(ideas, reply, shown_ids=shown_ids, fences=fences,
                            notes=c.notes, removed=removed)  # fmt: skip
        c.verdicts.update(i.review for i in kept if i.review is not None)
        c.verdicts[ReviewVerdict.infeasible] += len(removed)
        for idea, reason in removed:
            message = f"reviewer removed {shown(idea.title)}: {reason.value}"
            c.events.append(GenerateEvent(code="idea_dropped", message=message, data={
                "lane": idea.lane.value, "reason": f"review_{reason.value}",
                "title": shorten(idea.title),
            }))  # fmt: skip
        return kept, ""

    # ----------------------------------------------------------------------
    # Requests, spend and replies
    # ----------------------------------------------------------------------

    def _lane_job(
        self,
        c: _Call,
        lane: Lane,
        n: int,
        table: str,
        examples: Sequence[Example],
    ) -> _Job:
        role: Role = "leap" if lane is Lane.leap else "lane"
        leap = lane is Lane.leap
        instruction = lane_instruction(
            lane, table=table, examples=examples, n=n,
            floor=c.objective.min_relative_gain,
            model=self._transports[role].chain[0],
        )  # fmt: skip
        request = lane_request(
            lane, system=c.research.system, prefix=c.prefix, instruction=instruction,
            schema=IDEAS_SCHEMA, effort=self._efforts[role],
            max_tokens=self._cfg.IDEAS_LEAP_MAX_TOKENS if leap
            else self._cfg.IDEAS_LANE_MAX_TOKENS,
        )  # fmt: skip
        return self._job(lane.value, role, request)

    def _job(self, label: str, role: Role, request: LLMRequest) -> _Job:
        """Count once (free) and price the worst case; the child's cap."""
        transport = self._transports[role]
        estimate = preflight_estimate(
            transport.count_input_tokens(request),
            request.max_tokens,
            transport.chain,
            transport.prices,
        )
        return _Job(label, transport, request, estimate, Budget(cap_usd=estimate))

    def _run(self, jobs: Sequence[_Job], parent: Budget) -> None:
        """Send ``jobs`` on their child budgets, up to ``IDEAS_LANE_WORKERS`` at
        once; record every child on ``parent`` here, then raise the first
        error that is not a lane failure. After such an error, lanes not yet
        started are not sent."""
        stop = threading.Event()

        def work(job: _Job) -> None:
            if stop.is_set():
                return
            try:
                job.result = call(
                    job.transport, job.request, job.child, sleep=self._sleep,
                    max_retries=self._cfg.LLM_MAX_RETRIES, estimate=job.estimate,
                )  # fmt: skip
            except Exception as exc:  # classified on the pipeline's thread
                job.error = exc
                if not isinstance(exc, _SOFT):
                    stop.set()

        overrun: BudgetExceeded | None = None
        try:
            workers = min(self._cfg.IDEAS_LANE_WORKERS, len(jobs))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                list(pool.map(work, jobs))
        finally:
            for job in jobs:  # every child's money is on the parent first
                try:
                    parent.record(job.child.spent_usd, job.child.tokens)
                except BudgetExceeded as exc:
                    overrun = overrun or exc
        fatal = [e for j in jobs if (e := j.error) and not isinstance(e, _SOFT)]
        if fatal:
            raise fatal[0]
        if overrun is not None:
            raise overrun

    def _read(self, c: _Call, lane: Lane, job: _Job, n: int) -> list[IdeaCandidate]:
        """The lane's validated ideas; a failed or unusable lane gives none."""
        self._stopped(c, job)
        c.per_lane[lane] = 0
        if job.result is None:
            c.notes.append(f"lane {lane.value}: charged failure, not retried"
                           if isinstance(job.error, BudgetExceeded)
                           else f"lane {lane.value} failed {_failure(job)}")  # fmt: skip
            return []
        try:
            ideas = read_lane_reply(
                job.result, lane=lane, context=c.context, index=c.index, n=n,
                fence=c.fence, notes=c.notes, events=c.events,
            )  # fmt: skip
        except UnusableReplyError as exc:
            c.notes.append(f"lane {lane.value} failed (UnusableReplyError): {exc}")
            return []
        found = [self._ceiling(c, self._floored(c, idea)) for idea in ideas]
        c.per_lane[lane] = len(found)
        c.read += found
        return found

    def _stopped(self, c: _Call, job: _Job) -> None:
        message = None if job.result is None else job.result.message
        c.stops[job.label] = None if message is None else message.stop_reason
        if message is not None:
            c.cache_reads += message.usage.cache_read_input_tokens or 0

    def _floored(self, c: _Call, idea: IdeaCandidate) -> IdeaCandidate:
        """The class never weaker than a named shown technique's; an unshown
        slug is noted (the idea then counts as novel in origin)."""
        slug = idea.technique_slug
        technique = None if slug is None else c.research.by_slug.get(slug)
        if slug is not None and technique is None:
            c.notes.append(f"idea {shown(idea.title)} names {shown(slug)}: not a "
                           "technique that was shown, so it counts as novel")  # fmt: skip
        if technique is not None and (
            _CLASS_ORDER[technique.change_class] > _CLASS_ORDER[idea.change_class]
        ):
            return idea.model_copy(update={"change_class": technique.change_class})
        return idea

    def _ceiling(self, c: _Call, idea: IdeaCandidate) -> IdeaCandidate:
        spots = [h for h in c.hotspots if h.id in idea.hotspot_ids]
        found = amdahl_ceiling(idea.anchor, spots, c.context, profile=c.hotspots)
        return idea.model_copy(update={"ceiling": found})

    # ----------------------------------------------------------------------
    # The result
    # ----------------------------------------------------------------------

    def _result(
        self, c: _Call, ideas: Sequence[IdeaCandidate], n: int
    ) -> GenerateResult:
        bound = n + self._cfg.IDEAS_PORTFOLIO_MAX
        head = [i for i in ideas if i.change_class is not ChangeClass.novel]
        tail = [i for i in ideas if i.change_class is ChangeClass.novel]
        room = max(0, bound - len(head))
        count_note(c.notes, len(tail[room:]),
                   f"novel idea(s) past the result's bound of {bound} dropped")  # fmt: skip
        hypotheses = tuple(self._hypothesis(c, i) for i in (*head, *tail[:room]))
        stats = IdeaStats(
            ideas_per_lane=c.per_lane,
            grounded=sum(i.anchor is not None for i in c.read),
            anchored=sum(i.ceiling is not None for i in c.read),
            gate_passed=c.gate_passed,
            non_obvious=c.non_obvious,
            review_verdicts=dict(c.verdicts),
            unique_signatures=len({signature(i) for i in c.read}),
            cost_usd=max(0.0, c.budget.spent_usd - c.start),
            cache_read_tokens=c.cache_reads,
            stop_reasons=c.stops,
        )
        return GenerateResult(hypotheses, tuple(c.notes), tuple(c.events), stats)

    def _hypothesis(self, c: _Call, idea: IdeaCandidate) -> Hypothesis:
        slug = idea.technique_slug
        technique = None if slug is None else c.research.by_slug.get(slug)
        rationale = (
            f"{idea.change_summary}\nWhy it should win: {idea.justification_summary}"
            f"\nPrecondition: {idea.precondition}"
            f"\nWhy the output stays the same: {idea.equivalence_summary}"
        )
        if idea.plan is not None:
            rationale += f"\nPlan: {idea.plan}"
        tags = [f"lane:{idea.lane.value}"]
        if idea.review is not None:
            tags.append(f"review:{idea.review.value}")
        tags += [f"claimed_tier:{idea.tier.value}",
                 f"claimed_mechanism:{idea.mechanism.value}",
                 *(f"claimed_cell:{cell.value}" for cell in idea.morph_cells),
                 f"claimed_typicality:{idea.typicality.value}"]  # fmt: skip
        return Hypothesis(
            project_id=c.project.id,
            hotspot_ids=idea.hotspot_ids,
            source=HypothesisSource.novel if technique is None
            else HypothesisSource.playbook,
            technique_id=None if technique is None else technique.id,
            title=idea.title,
            rationale=rationale,
            change_class=idea.change_class,
            expected_gain=idea.expected_gain,
            provability=idea.provability,
            risk=idea.risk,
            tags=tuple(tags),
        )  # fmt: skip


def _failure(job: _Job) -> str:
    error = job.error
    return f"({type(error).__name__}): {str(error)[:200]}"
