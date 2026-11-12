"""The idea pipeline, a ``HypothesisGenerator`` (Step 3 Wave 2, N4a; spec
amendment 3.4, 4.2b, D43-D59, D64, D65, section 5).

One ``generate`` call: S0 reads the hot code at the base commit (no code:
today's generator, unchanged); a lens named in ``IDEAS_LANE_VIEWS`` sees its
own view instead (G2) and is grounded in it; S1, the obvious lane, names the
defaults;
S2 sends the lens lanes and the leap in parallel; S4a filters
deterministically; S3, the reviewer, may only remove, and is shown the
shared code plus whatever the views of the surviving ideas' lanes showed;
S4b picks the portfolio and interleaves it with S1. A second call in a run
is S1 only, unless it is seeded (G5b, D64). The run's ``workloads`` reach the
input-shape view through ``generate``.

What is already taken (G4), two switches, both off by default (off keeps
the parallel lanes and the portfolio exactly as they were):
``IDEAS_SEQUENTIAL_LANES`` sends S2's lanes one after another in the run's
rotation, each shown the mechanisms (``idea_dedupe.taken_block``: file,
function, target lines, mechanism, primary cell; never a title) of every
idea S1 and the earlier lanes produced, with a "do not repeat" lead-in,
after the cached data block so the cache is still shared; S2 is still
reserved whole first (each lane priced with S1's block), then each later
lane is re-priced with its grown block and a lane that no longer fits ends
S2 there (a ``discovery_unaffordable`` event naming it).
``IDEAS_MECHANISM_DEDUPE`` drops, in S4b, an idea whose mechanism key
matches an earlier admitted idea's (an ``idea_dropped`` event, reason
``mechanism_duplicate``, with ``duplicate_of``).

How each lane thinks (G5): ``IDEAS_LANE_FRAMEWORKS`` (off by default; off
keeps every request byte for byte) gives a lens whose view was built its
view's framework and a rule-relaxing lane its rule's
(``idea_prompts.lane_framework``), in the lane's own instruction after the
cached data block, so every shared block is unchanged. S1, the leap, the
reviewer and a lens on the shared block get none. A note per S2 lane records
which framework it was assigned (``framework_labels`` reads them), whether or
not its request was then sent (a budget stop, count mode): a report joins the
labels with the lanes it sent, to tell a view alone from a view with its
framework.

Round seeds (G5b): ``IDEAS_ROUND_SEEDS`` (off by default; off keeps every
request and result byte for byte) builds a seed per verdict in ``verdicts``
(this run's, passed by the node) whose hypothesis is no proposal and has a
recorded mechanism key: its key, plain title, outcome and primary gain over
the run's noise floor, keeps first. Each lens lane, and no other request, is
shown them as the first lines of G4's one mechanisms block (alone when
sequential lanes are off), so the prompt grows once. No verdict (round 1) is
no seed; a second call with a seed runs its lanes again instead of S1 only.
Seeds on, the result records each hypothesis's key as a ``KEY_EVENT`` event,
which the node reads back (``idea_dedupe.recorded_keys``) next round.
A seeded second call is its own cost line (D64): its result carries a
``SEEDED_CALL`` event (the seeds shown, the S2 lanes sent), and an error
raised inside it after a request was sent carries ``SEEDED_NOTE``
(``seeded_failure``), so the node can charge the call's whole spend, S1's
included, to its own counters either way.

Lessons (G11, W1, D21): ``GENERATOR_LESSONS`` (off by default; off keeps
every request byte for byte) appends ``generate.lessons_block`` (the
project's last 20 lessons, fenced under the call's token) to the data block
of S1, every lens and every rule-relaxing lane, shared view or own, so each
gets the same bytes where the cache breakpoint sits and no instruction
grows. ``avoid_titles`` stay where they are (``<already_on_the_table>``,
S4a), so no title is shown twice. The leap and the reviewer never get it.

The portfolio leap (U-portfolio): ``IDEAS_LEAP_PORTFOLIO`` (off by default;
off keeps every request byte for byte) deals the leap three procedures of
``idea_frameworks`` for (``IDEAS_LEAP_DEAL_LIBRARY``, ``IDEAS_LEAP_DEAL_RUN``,
the call's round), noted, and sends ``idea_portfolio_leap``'s ask and schema
on the leap's own request; its reply gives a ``leap_procedure`` event per
dealt procedure (also when no reply could be read) and a ``leap_diagnosis``
event, and each idea a ``framework:<id>`` tag, its cost model and further
functions in the rationale. On without its deal, the constructor refuses.

What they may change (G3):``IDEAS_RELAX_LANES`` (off by default) adds
rule-relaxing lanes to S2, after every other lane (in sequence, no other lane
sees their mechanisms). Their ideas carry ``proposal`` from birth
(``idea_lanes``); S4a filters them on their own (no other idea is a duplicate
of one, or one of another's), and they skip the reviewer and the portfolio
(whose rules they break by design). They follow every other idea in the
result, outside its bound, each with a ``proposal:<rule>`` tag, which the
node parks for a human; none counts in the idea stats but ``ideas_per_lane``.

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

import hashlib
import math
import re
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
    IdeaView,
    Role,
    Settings,
    leap_shape,
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
    VerdictOutcome,
    Workload,
)
from autonomous_ai_agents.common.repo_read import RepoReader
from autonomous_ai_agents.optimization.generate import lessons_block
from autonomous_ai_agents.optimization.idea_context import (
    HistoryReader,
    IdeaReadLimits,
    LaneView,
    ViewSource,
    amdahl_ceiling,
    build_view,
    read_code_context,
    render_data_block,
    review_context,
)
from autonomous_ai_agents.optimization.idea_dedupe import (
    IdeaKey,
    MechanismKey,
    Seed,
    idea_key,
    key_event,
    taken_block,
)
from autonomous_ai_agents.optimization.idea_frameworks import Deal, deal
from autonomous_ai_agents.optimization.idea_lanes import (
    lane_request,
    on_the_table,
    read_lane_reply,
)
from autonomous_ai_agents.optimization.idea_lanes import (
    lane_transports as resolve_lanes,
)
from autonomous_ai_agents.optimization.idea_portfolio import (
    deterministic_filter,
    lesson_titles,
    portfolio,
    rotation,
    signature,
)
from autonomous_ai_agents.optimization.idea_portfolio_leap import (
    FRAMEWORK_TAG,
    deal_settings,
    not_sent,
    portfolio_instruction,
    portfolio_request,
    read_portfolio_reply,
    reply_failure,
    steps_tag,
    unanswered,
    with_hypotheses,
)
from autonomous_ai_agents.optimization.idea_prompts import (
    IDEAS_SCHEMA,
    IDEAS_SYSTEM_PROMPT,
    Example,
    example_rotation,
    lane_framework,
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
    LENS_LANES,
    RELAXING_LANES,
    CodeContext,
    GenerateEvent,
    IdeaCandidate,
    IdeaStats,
    Lane,
    ReviewReason,
    ReviewVerdict,
    is_proposal,
    proposal_tag,
)
from autonomous_ai_agents.optimization.sources import (
    GenerateResult,
    HypothesisGenerator,
    RunVerdicts,
)
from autonomous_ai_agents.research.playbook import (
    ResearchSystem,
    repo_fence,
    research_system,
)

NO_CODE_CONTEXT: Final = "idea pipeline: no code context"
LANE_VIEW: Final = "lane_view"
"""``IDEAS_VIEW_RECORD``'s event: a lane request's view hash, served model
and output tokens against its cap (``_spent``)."""
_ROLES: Final[tuple[Role, ...]] = ("lane", "leap", "reviewer")
_SOFT: Final = (LLMUnavailable, LLMRequestError, UnusableReplyError, BudgetExceeded)
"""What ends one request without ending the pipeline (D48): noted, charged."""
_GATE_CODES: Final = frozenset({"no_anchor", "ceiling_unknown", "below_gate"})
_EQUIVALENCE_LABEL: Final = {
    False: "Why the output stays the same",
    True: "What the relaxed rule changes",  # a proposal (G3)
}
_FRAMEWORK_NOTE: Final = re.compile(
    rf"lane ({'|'.join(lane.value for lane in Lane)}): "
    r"framework (none|(?:view|rule) [a-z_]+)"
)
"""A note ``generate`` writes per S2 lane with frameworks on (G5)."""
SEEDED_CALL: Final = "seeded_second_call"
"""The code of the event a seeded second call's result carries (D64)."""
SEEDED_NOTE: Final = "D64: raised inside a seeded second generator call"
"""The note an error raised inside a seeded second call carries (D64)."""
_CLASS_ORDER: Final = {
    ChangeClass.efficiency: 0,
    ChangeClass.behaviour: 1,
    ChangeClass.novel: 2,
}
ViewBuilder = Callable[[IdeaView, ViewSource, list[str]], LaneView | None]
"""``build_view``'s signature: what builds a viewed lens's view (G2); a live
harness may give a recorded one instead (the idea lab's views pass, Va)."""


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
    view: str | None = None  # IDEAS_VIEW_RECORD: the request's ``view_sha``


@dataclass(frozen=True)
class _Seen:
    """What one lane sees (G2): its data block, the documents it grounds in
    and whether another request reads the same block (then it is cached)."""

    prefix: str
    context: CodeContext
    shared: bool


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
    views: dict[Lane, _Seen] = field(default_factory=dict)
    understanding: ProjectUnderstanding | None = None
    keys: dict[str, MechanismKey] = field(default_factory=dict)
    frameworks: dict[Lane, str] = field(default_factory=dict)
    seeds: tuple[Seed, ...] = ()
    seeded: bool = False
    """A second call with a seed to show: it runs its lanes again (D64)."""
    lessons: str = ""
    """The lessons block every lane's data block ends with (W1); ``""``: none."""
    deal: Deal | None = None
    """The portfolio leap's three procedures (U-portfolio); ``None``: today's leap."""


class IdeaPipelineGenerator:
    """The five-stage pipeline on the ``lane``, ``leap`` and ``reviewer`` roles.

    ``reader`` gives the project's git objects (``None``: no code context);
    ``fallback`` is today's generator for the no-code path (``None``: an
    empty result, noted). Each transport must bill its role's chain and
    accept its effort, checked here, before any spend; ``lane_transports``
    serve the lanes that name their own model (G1, ``lane_transports``);
    ``view_builder`` builds each viewed lens's view (``build_view``).
    """

    def __init__(
        self,
        transports: Mapping[Role, LLMTransport],
        *,
        lane_transports: Mapping[Lane, LLMTransport] | None = None,
        reader: Callable[[Project], RepoReader] | None = None,
        config: Settings = settings,
        sleep: Callable[[float], None] = time.sleep,
        fallback: HypothesisGenerator | None = None,
        view_builder: ViewBuilder = build_view,
    ) -> None:
        self._leap = leap_shape(config)  # a Fable leap's fixed shape
        efforts = {
            "lane": config.IDEAS_LANE_EFFORT,
            "leap": self._leap.effort,
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
        self._lanes = resolve_lanes(self._transports, lane_transports or {}, config)
        self._reader, self._cfg, self._sleep = reader, config, sleep
        self._fallback, self._build_view = fallback, view_builder
        self._sequential = _switch(config, "IDEAS_SEQUENTIAL_LANES")
        self._dedupe = _switch(config, "IDEAS_MECHANISM_DEDUPE")
        self._frameworks = config.IDEAS_LANE_FRAMEWORKS
        self._seeded = config.IDEAS_ROUND_SEEDS
        self._lessons = config.GENERATOR_LESSONS
        self._view_record = config.IDEAS_VIEW_RECORD
        self._deal = (  # U-portfolio: refused before any spend without its deal
            deal_settings(config.IDEAS_LEAP_DEAL_LIBRARY, config.IDEAS_LEAP_DEAL_RUN)
            if config.IDEAS_LEAP_PORTFOLIO else None
        )  # fmt: skip

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
        workloads: Sequence[Workload] = (),
        verdicts: RunVerdicts | None = None,
    ) -> GenerateResult:
        """``workloads`` are the run's (G2): the input-shape view shows their
        real inputs; none, and that view shows no input. ``verdicts`` are
        this run's so far, the round seeds' source (G5b)."""
        notes: list[str] = []
        research = research_system(IDEAS_SYSTEM_PROMPT, techniques, notes)
        fence = repo_fence(research)
        context = CodeContext()
        reader = (
            None if commit is None or self._reader is None else self._reader(project)
        )
        if commit is not None and reader is not None:
            limits = IdeaReadLimits.from_settings(self._cfg)
            context = read_code_context(
                reader, commit, hotspots, fence=fence,
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
                read_deny=read_deny, workloads=workloads,
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
                  prefix, index, notes, budget.spent_usd,
                  understanding=understanding)  # fmt: skip
        if self._lessons:  # W1: the lessons only; the titles are on the table
            c.lessons = lessons_block(project.id, lessons, (), fence, notes)
        if self._seeded:
            c.seeds = _round_seeds(verdicts, notes)
        c.seeded = call_index >= 1 and bool(c.seeds)
        named = [*avoid_titles, *(t.name for t in research.by_slug.values())]
        s1 = self._s1(c, n, named)
        if call_index >= 1 and not c.seeded:
            notes.append("second generator call: S1 only, earlier titles avoided (D48)")
            return self._result(c, s1, n)
        if call_index >= 1:
            notes.append(f"second generator call with {len(c.seeds)} round seed(s): "
                         "the lanes run again, the lens lanes seeded (G5b)")  # fmt: skip
        seed = run_id if run_id is not None else f"{commit}:{project.id}"
        lanes = (
            *self._cfg.IDEAS_LENSES,
            *((Lane.leap,) if self._cfg.IDEAS_LEAP_N else ()),
        )
        if self._deal is not None and Lane.leap in lanes:  # U-portfolio
            c.deal = deal(*self._deal, call_index + 1)
            dealt = ", ".join(p.framework.id if p.tool is None
                              else f"{p.framework.id} ({p.tool})"
                              for p in c.deal.procedures)  # fmt: skip
            notes.append(f"portfolio leap: dealt {dealt} (library {c.deal.library}, "
                         f"run {c.deal.run}, round {c.deal.round}, cell "
                         f"{c.deal.cell})")  # fmt: skip
        if self._cfg.IDEAS_LANE_VIEWS and commit is not None and reader is not None:
            source = ViewSource(
                reader, commit, tuple(hotspots), fence, tuple(protected),
                tuple(read_deny), IdeaReadLimits.from_settings(self._cfg),
                tuple(workloads),
                reader if isinstance(reader, HistoryReader) else None,
            )  # fmt: skip
            c.views = self._views(c, source)
        relax = self._cfg.IDEAS_RELAX_LANES  # G3: after every other lane
        order = (*rotation(seed, lanes), *relax)
        lanes = (*lanes, *relax)
        if self._frameworks:
            self._frame(c, order)
        examples = example_rotation(seed, lanes, exclude=(project.name,))
        table = on_the_table([*(i.title for i in s1), *named], fence, notes)
        found = self._s2(c, lanes, order, table, examples)
        if found is None:
            if c.seeded:  # S1 alone is what D48 spends anyway: no seeded call
                c.seeded = False
                notes.append("seeded second call: its lanes were unaffordable, "
                             "counted as S1 only (D48)")  # fmt: skip
            return self._result(c, s1, n)
        others = [i for i in found if i.proposal is None]
        proposals = self._proposals(c, found, avoid_titles, lessons)
        survivors = self._s4a(c, s1, others, avoid_titles, lessons)
        reviewed = self._s3(c, survivors)
        olds = [i for i in reviewed if i.lane is Lane.obvious]
        news = [i for i in reviewed if i.lane is not Lane.obvious]
        merged: list[tuple[IdeaCandidate, IdeaCandidate]] = []
        picked = portfolio(olds, news, rotation=order, notes=notes,
                           minimum=self._cfg.IDEAS_PORTFOLIO_MIN,
                           maximum=self._cfg.IDEAS_PORTFOLIO_MAX,
                           mechanisms=c.keys if self._dedupe else None,
                           merged=merged)  # fmt: skip
        for idea, twin in merged:
            c.events.append(GenerateEvent(
                code="idea_dropped",
                message=f"mechanism dedupe dropped {shown(idea.title)}: the same "
                        f"mechanism as {shown(twin.title)}",
                data={"lane": idea.lane.value, "reason": "mechanism_duplicate",
                      "title": shorten(idea.title),
                      "duplicate_of": shorten(twin.title)},
            ))  # fmt: skip
        return self._result(c, picked, n, proposals)

    def _views(self, c: _Call, source: ViewSource) -> dict[Lane, _Seen]:
        """Each viewed lens's view (G2), built and rendered once per view; a
        view that cannot be built leaves its lane on the shared block."""
        wanted = self._cfg.IDEAS_LANE_VIEWS
        readers = Counter(wanted.values())
        built: dict[IdeaView, _Seen | None] = {}
        for name in readers:
            view = self._build_view(name, source, c.notes)
            built[name] = None if view is None else _Seen(
                render_data_block(
                    view.context, project=c.project, objective=c.objective,
                    understanding=c.understanding, hotspots=c.hotspots,
                    fence=c.fence, notes=c.notes, view=name, facts=view.facts,
                ),
                view.context, readers[name] > 1,
            )  # fmt: skip
        seen: dict[Lane, _Seen] = {}
        for lane, name in wanted.items():
            found = built[name]
            if found is None:
                c.notes.append(f"lane {lane.value}: no {name} view, so it sees the "
                               "shared data block")  # fmt: skip
            else:
                seen[lane] = found
        return seen

    def _frame(self, c: _Call, order: Sequence[Lane]) -> None:
        """Each S2 lane's framework block (G5), noted per lane in send order:
        a relaxing lane's rule, a lens's view only when that view was built."""
        for lane in order:
            view = self._cfg.IDEAS_LANE_VIEWS.get(lane) if lane in c.views else None
            block = lane_framework(lane, view)
            if block is None:
                label = "none"
            else:
                c.frameworks[lane] = block
                rule = RELAXING_LANES.get(lane)
                label = f"view {view}" if rule is None else f"rule {rule.value}"
            c.notes.append(f"lane {lane.value}: framework {label}")

    # ----------------------------------------------------------------------
    # The stages
    # ----------------------------------------------------------------------

    def _s1(self, c: _Call, n: int, named: Sequence[str]) -> list[IdeaCandidate]:
        """The obvious lane; a soft failure leaves the named defaults alone."""
        table = on_the_table(named, c.fence, c.notes)
        job = self._lane_job(c, Lane.obvious, n, table, ())
        c.budget.check(job.estimate)  # BudgetExceeded: unaffordable, as today
        self._run(c, [job])
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
        sizes.update({lane: cfg.IDEAS_LANE_N for lane in cfg.IDEAS_RELAX_LANES})
        first = self._taken(c, table) if self._sequential else table
        seeded = self._taken(c, table, c.seeds) if c.seeds else first
        jobs = {lane: self._lane_job(c, lane, sizes[lane],
                                     seeded if lane in LENS_LANES else first,
                                     examples[lane])
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
            if c.deal is not None:  # U-portfolio: the dealt procedures, unsent
                not_sent(c.deal, "the lanes were unaffordable", c.events)
            return None
        if self._sequential:
            return self._in_sequence(c, order, jobs, sizes, table, examples)
        self._run(c, list(jobs.values()))
        found: list[IdeaCandidate] = []
        for lane in order:  # the run's lane order decides dedup (D52)
            found += self._read(c, lane, jobs[lane], sizes[lane])
        return found

    def _in_sequence(
        self,
        c: _Call,
        order: Sequence[Lane],
        jobs: Mapping[Lane, _Job],
        sizes: Mapping[Lane, int],
        table: str,
        examples: Mapping[Lane, tuple[Example, ...]],
    ) -> list[IdeaCandidate]:
        """S2's lanes one at a time in the rotation (G4), each shown what S1
        and the lanes before it produced; a lane is re-priced once earlier
        lanes added ideas, and one that no longer fits ends S2 there."""
        priced = len(c.read)  # the ideas each job of ``jobs`` was built with
        found: list[IdeaCandidate] = []
        for at, lane in enumerate(order):
            job = jobs[lane]
            if len(c.read) != priced:
                seeds = c.seeds if lane in LENS_LANES else ()
                job = self._lane_job(c, lane, sizes[lane],
                                     self._taken(c, table, seeds),
                                     examples[lane])  # fmt: skip
                try:
                    c.budget.check(job.estimate)
                except BudgetExceeded as exc:
                    rest = ", ".join(x.value for x in order[at:])
                    message = (f"lanes {rest} not sent: the {lane.value} lane may "
                               f"cost {job.estimate:.6f} USD")  # fmt: skip
                    c.notes.append(f"{message} ({exc})")
                    c.events.append(GenerateEvent(
                        code="discovery_unaffordable", message=message,
                        level=EventLevel.warning,
                        data={"stage": "lanes", "lane": lane.value,
                              "estimate_usd": job.estimate},
                    ))  # fmt: skip
                    if c.deal is not None and Lane.leap in order[at:]:  # U-portfolio
                        not_sent(c.deal, f"the lanes stopped at {lane.value}",
                                 c.events)  # fmt: skip
                    break
            self._run(c, [job])
            found += self._read(c, lane, job, sizes[lane])
        return found

    def _taken(self, c: _Call, table: str, seeds: Sequence[Seed] = ()) -> str:
        """The table, then the one mechanisms block, if any: ``seeds`` first
        (G5b, a lens lane's), then the mechanisms taken so far (G4) when the
        lanes run in sequence."""
        notes: list[str] = []
        ideas = c.read if self._sequential else ()
        block = taken_block(ideas, c.keys, c.fence, notes, seeds)
        c.notes.extend(f"mechanisms block: {note}" for note in notes)
        return f"{table}\n{block}" if block else table

    def _proposals(
        self,
        c: _Call,
        found: Sequence[IdeaCandidate],
        avoid_titles: Sequence[str],
        lessons: Sequence[Lesson],
    ) -> tuple[IdeaCandidate, ...]:
        """S4a for the rule-relaxing lanes' ideas alone (G3): grounded,
        gated and deduplicated among themselves, never against another
        lane's idea; no reviewer, no portfolio."""
        relaxed = [i for i in found if i.proposal is not None]
        if not relaxed:
            return ()
        return deterministic_filter(
            (), relaxed, floor=c.objective.min_relative_gain, objective=c.objective,
            avoid=avoid_titles, lesson_titles=lesson_titles(lessons),
            multiplier=self._cfg.IDEAS_AMDAHL_MULTIPLIER, notes=c.notes,
            shown_slugs=frozenset(c.research.by_slug), events=c.events,
        )  # fmt: skip

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
                ideas, prefix=self._review_prefix(c, ideas), fence=c.fence,
                reviewer_fence=reviewer,
                max_ideas=cfg.IDEAS_REVIEW_MAX_IDEAS,
                max_tokens=cfg.IDEAS_REVIEWER_MAX_TOKENS,
                effort=self._efforts["reviewer"], notes=c.notes, think=think,
            )  # fmt: skip
            kept, why = self._review(c, ideas, request, shown_ids, fences)
        if kept is None:
            kept = unreviewed(ideas, fences=fences, why=why, notes=c.notes)
            c.verdicts.update(i.review for i in kept if i.review is not None)
        return kept

    def _review_prefix(self, c: _Call, ideas: Sequence[IdeaCandidate]) -> str:
        """The shared data block, or (G2) the shared documents with what the
        views of the ideas' lanes showed beyond them, under the same fence:
        the reviewer checks each quote in code it is shown."""
        used: list[_Seen] = []
        for lane, seen in c.views.items():
            mine = any(idea.lane is lane for idea in ideas)
            if mine and all(seen is not other for other in used):
                used.append(seen)
        merged = review_context(c.context, [s.context for s in used],
                                cap=self._cfg.IDEAS_CODE_MAX_BYTES,
                                notes=c.notes)  # fmt: skip
        if merged.documents == c.context.documents:
            return c.prefix
        return render_data_block(
            merged, project=c.project, objective=c.objective,
            understanding=c.understanding, hotspots=c.hotspots, fence=c.fence,
            notes=[],  # every withholding was noted when the blocks were built
        )  # fmt: skip

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
        job = self._job("reviewer", self._transports["reviewer"], request)
        try:
            c.budget.check(job.estimate)
        except BudgetExceeded:
            return None, "the reviewer is unaffordable"
        self._run(c, [job])
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
        leap, transport = lane is Lane.leap, self._lanes[lane]
        view = c.views.get(lane)
        prefix = c.prefix if view is None else view.prefix
        if c.lessons and not leap:  # the same bytes in every lane (W1)
            prefix = f"{prefix}\n{c.lessons}"
        instruction = lane_instruction(
            lane, table=table, examples=examples, n=n,
            floor=c.objective.min_relative_gain, model=transport.chain[0],
            framework=c.frameworks.get(lane), think=self._cfg.IDEAS_THINK_LINE_ALL,
        )  # fmt: skip
        portfolio = c.deal if leap else None  # U-portfolio: its own ask, no examples
        if portfolio is not None:
            instruction = portfolio_instruction(
                portfolio, table=table, floor=c.objective.min_relative_gain
            )
        request = lane_request(
            lane, system=c.research.system, instruction=instruction,
            prefix=prefix, shared=view is None or view.shared,
            schema=IDEAS_SCHEMA, effort=self._efforts[role],
            max_tokens=self._leap.max_tokens if leap
            else self._cfg.IDEAS_LANE_MAX_TOKENS,
        )  # fmt: skip
        if (
            portfolio is not None
        ):  # the leap's request (its cap leap_shape's), the portfolio's schema
            request = portfolio_request(request, portfolio)
        job = self._job(lane.value, transport, request)
        if self._view_record:
            job.view = view_sha(prefix, c.fence)
        return job

    def _job(self, label: str, transport: LLMTransport, request: LLMRequest) -> _Job:
        """Count once (free) and price the worst case; the child's cap."""
        estimate = preflight_estimate(
            transport.count_input_tokens(request),
            request.max_tokens,
            transport.chain,
            transport.prices,
        )
        return _Job(label, transport, request, estimate, Budget(cap_usd=estimate))

    def _run(self, c: _Call, jobs: Sequence[_Job]) -> None:
        """Send ``jobs`` on their child budgets, up to ``IDEAS_LANE_WORKERS`` at
        once; record every child on the call's budget here, then raise the
        first error that is not a lane failure, noted ``SEEDED_NOTE`` in a
        seeded call (D64). After such an error, lanes not yet started are
        not sent."""
        parent, stop = c.budget, threading.Event()

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
        raised = fatal[0] if fatal else overrun
        if raised is None:
            return
        if c.seeded:  # the node charges this call's spend to its line (D64)
            raised.add_note(SEEDED_NOTE)
        raise raised

    def _read(self, c: _Call, lane: Lane, job: _Job, n: int) -> list[IdeaCandidate]:
        """The lane's validated ideas; a failed or unusable lane gives none."""
        self._stopped(c, job)
        c.per_lane[lane] = 0
        if job.view is not None:  # IDEAS_VIEW_RECORD (S1, emergence round 2)
            c.events.append(GenerateEvent(
                code=LANE_VIEW, message=f"lane {lane.value}: view {job.view}",
                data={"lane": lane.value, "view_sha": job.view, **_spent(job)},
            ))  # fmt: skip
        portfolio = c.deal if lane is Lane.leap else None  # U-portfolio
        if job.result is None:
            c.notes.append(f"lane {lane.value}: charged failure, not retried"
                           if isinstance(job.error, BudgetExceeded)
                           else f"lane {lane.value} failed {_failure(job)}")  # fmt: skip
            if portfolio is not None:
                unanswered(portfolio, "the request failed", reply_failure(job.error),
                           c.events)  # fmt: skip
            return []
        view = c.views.get(lane)
        context = c.context if view is None else view.context
        try:
            ideas = read_lane_reply(
                job.result, lane=lane, context=context, index=c.index, n=n,
                fence=c.fence, notes=c.notes, events=c.events,
            ) if portfolio is None else read_portfolio_reply(
                job.result, deal=portfolio, context=context, index=c.index, n=n,
                fence=c.fence, notes=c.notes, events=c.events,
            )  # fmt: skip
        except UnusableReplyError as exc:
            c.notes.append(f"lane {lane.value} failed (UnusableReplyError): {exc}")
            if portfolio is not None:
                unanswered(portfolio, "the reply is unusable",
                           reply_failure(exc, job.result), c.events)  # fmt: skip
            return []
        found = [self._ceiling(c, self._floored(c, idea), context) for idea in ideas]
        for idea in found:
            key = idea_key(idea, context)
            if key is not None:
                c.keys[idea.id] = key
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

    def _ceiling(
        self, c: _Call, idea: IdeaCandidate, context: CodeContext
    ) -> IdeaCandidate:
        """The ceiling in the documents the idea was grounded in."""
        spots = [h for h in c.hotspots if h.id in idea.hotspot_ids]
        found = amdahl_ceiling(idea.anchor, spots, context, profile=c.hotspots)
        return idea.model_copy(update={"ceiling": found})

    # ----------------------------------------------------------------------
    # The result
    # ----------------------------------------------------------------------

    def _result(
        self,
        c: _Call,
        ideas: Sequence[IdeaCandidate],
        n: int,
        proposals: Sequence[IdeaCandidate] = (),
    ) -> GenerateResult:
        """The hypotheses within the bound, then the proposals (G3), which
        the node parks; the stats leave proposals out but per lane."""
        bound = n + self._cfg.IDEAS_PORTFOLIO_MAX
        head = [i for i in ideas if i.change_class is not ChangeClass.novel]
        tail = [i for i in ideas if i.change_class is ChangeClass.novel]
        room = max(0, bound - len(head))
        count_note(c.notes, len(tail[room:]),
                   f"novel idea(s) past the result's bound of {bound} dropped")  # fmt: skip
        ideas = (*head, *tail[:room], *proposals)
        hypotheses = tuple(self._hypothesis(c, i) for i in ideas)
        if c.deal is not None:  # U-portfolio: each idea row names its hypothesis
            c.events = with_hypotheses(c.events, {
                i.id: h.id for i, h in zip(ideas, hypotheses, strict=True)
                if i.framework is not None})  # fmt: skip
        if c.seeded:  # the node's own cost line for this call (D64)
            sent = [lane.value for lane in c.per_lane if lane is not Lane.obvious]
            lanes = f"lanes {', '.join(sent)}" if sent else "no lane sent"
            c.events.append(GenerateEvent(
                code=SEEDED_CALL,
                message=f"seeded second generator call (D64): {len(c.seeds)} "
                        f"seed(s), {lanes}",
                data={"seeds": len(c.seeds), "lanes": ",".join(sent)},
            ))  # fmt: skip
        if self._seeded:  # the keys the next round seeds from (G5b)
            for idea, hypothesis in zip(ideas, hypotheses, strict=True):
                key = c.keys.get(idea.id)
                if key is not None and idea.proposal is None:
                    function = None if idea.anchor is None else idea.anchor.qualname
                    c.events.append(key_event(hypothesis.id, idea.title,
                                              IdeaKey(key=key, function=function)))  # fmt: skip
        read = [i for i in c.read if i.proposal is None]
        stats = IdeaStats(
            ideas_per_lane=c.per_lane,
            grounded=sum(i.anchor is not None for i in read),
            anchored=sum(i.ceiling is not None for i in read),
            gate_passed=c.gate_passed,
            non_obvious=c.non_obvious,
            review_verdicts=dict(c.verdicts),
            unique_signatures=len({signature(i) for i in read}),
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
            f"\n{_EQUIVALENCE_LABEL[idea.proposal is not None]}: "
            f"{idea.equivalence_summary}"
        )
        if idea.plan is not None:
            rationale += f"\nPlan: {idea.plan}"
        if idea.cost_model is not None:  # U-portfolio
            rationale += f"\nCost model: {idea.cost_model}"
        if idea.more_anchors:  # U-portfolio: a multi-function idea
            rationale += "\nAlso changes: " + ", ".join(
                f"{a.path}::{a.qualname}" for a in idea.more_anchors
            )
        tags = [f"lane:{idea.lane.value}"]
        if idea.proposal is not None:  # the quarantine's tag (G3)
            tags.append(proposal_tag(idea.proposal))
        if idea.review is not None:
            tags.append(f"review:{idea.review.value}")
        if idea.framework is not None:  # U-portfolio: the procedure it came from
            tags += [f"{FRAMEWORK_TAG}:{idea.framework}", steps_tag(idea.steps_present)]
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


def _spent(job: _Job) -> dict[str, str | int | None]:
    """What a lane request's reply spent against its cap (X2-L): the served
    model, its output tokens, the request's ``max_tokens``, the stop reason
    and, where usage has iterations (a server-side fallback), every
    attempt's ``model=tokens``; with no reply, the cap and None for the rest."""
    if job.result is None:
        return {**dict.fromkeys(("served_model", "output_tokens", "stop_reason",
                                 "attempt_output_tokens")),
                "max_tokens": job.request.max_tokens}  # fmt: skip
    message = job.result.message
    attempts = ",".join(
        f"{getattr(i, 'model', None) or message.model}={i.output_tokens}"
        for i in message.usage.iterations or []
    )
    return {
        "served_model": job.result.served_model,
        "output_tokens": message.usage.output_tokens,
        "max_tokens": job.request.max_tokens,
        "stop_reason": message.stop_reason,
        "attempt_output_tokens": attempts or None,
    }


def view_sha(prefix: str, fence: Fence) -> str:
    """8 hex of the sha256 of a lane's data block with its per-request fence
    token masked: two requests shown the same view hash alike (S1)."""
    masked = prefix.replace(fence.token, "<boundary>")
    return hashlib.sha256(masked.encode("utf-8")).hexdigest()[:8]


def framework_labels(notes: Sequence[str]) -> dict[Lane, str | None]:
    """Which framework each S2 lane was assigned (G5), from a result's notes:
    ``"view <name>"``, ``"rule <rule>"`` or ``None``; empty when frameworks
    were off (or the call was S1 only). Assigned, not sent: a lane the budget
    or count mode stopped is labelled too, so join with the lanes sent."""
    labels: dict[Lane, str | None] = {}
    for note in notes:
        found = _FRAMEWORK_NOTE.fullmatch(note)
        if found is not None:
            label = found.group(2)
            labels[Lane(found.group(1))] = None if label == "none" else label
    return labels


def _round_seeds(verdicts: RunVerdicts | None, notes: list[str]) -> tuple[Seed, ...]:
    """A seed per verdict whose hypothesis is no proposal and has a key, its
    gain over the floor rounded (``None``: either unknown), keeps first."""
    if verdicts is None:
        return ()
    floor = verdicts.noise_floor
    found: list[Seed] = []
    proposals = unkeyed = 0
    for item in verdicts.trialled:
        if is_proposal(item.hypothesis):  # never a seed (G3)
            proposals += 1
            continue
        if item.key is None:
            unkeyed += 1
            continue
        gain, below = item.gain, item.floor  # the trial's own primary result
        if gain is None or below is None:  # none measured: the run's floor
            gain, below = item.verdict.gain, floor
        ratio = None if gain is None or below is None or not below > 0 else gain / below
        found.append(Seed(
            key=item.key, title=item.hypothesis.title, outcome=item.verdict.outcome,
            gain_over_floor=None if ratio is None or not math.isfinite(ratio)
            else round(ratio, 2),
        ))  # fmt: skip
    count_note(notes, proposals, "proposal(s) never seeded (G3)")
    count_note(notes, unkeyed, "verdict(s) not seeded: no mechanism key recorded")
    found.sort(key=lambda seed: seed.outcome is not VerdictOutcome.keep)
    return tuple(found)


def seeded_failure(exc: BaseException) -> bool:
    """Whether ``exc`` was raised inside a seeded second call (D64)."""
    notes: list[str] = getattr(exc, "__notes__", [])
    return SEEDED_NOTE in notes


def _switch(config: Settings, name: str) -> bool:
    """A G4 switch. ``Settings`` gains both with the G4 config patch; until
    it lands a missing one reads as off (``model_copy(update=...)`` sets it)."""
    return getattr(config, name, False) is True


def _failure(job: _Job) -> str:
    error = job.error
    return f"({type(error).__name__}): {str(error)[:200]}"
