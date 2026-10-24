"""E3, the blind hypothesis sweep: which model and effort find the root cause?

For every repository of the benchmark corpus (12 slowdowns, 3 controls)
and the hard corpus (10), phase 1 (``discovery.phase_one``) runs once and
its facts are shared by every arm, so the arms differ only in generation.
Each arm (``ARMS``, or ``$LIVE_SWEEP_ARMS``) calls ``generate_hypotheses``
(n = 5, no techniques: blind) through a transport whose chain is the arm's
model alone; Fable 5.1 at medium joins on the 12 benchmark slowdowns when
``$LIVE_SWEEP_FABLE=1`` (the research plan's optional arm), in a run of its
own (its worst case is about 1.17 USD, with a cap of 1.40 USD).

Budget: one ``LiveRun`` per repository shared by phase 1, the arms and the
graders, capped at ``SweepPlan.cap_for(repo)``: the sum of the worst cases
of every request it may send (phase 1, each arm at ``BLIND_PROMPT_BOUND``
and 16000 output tokens, each grader on a slowdown), rounded up. No
request can be refused for the budget, so no arm loses its data because an
earlier one spent much. The Fable run and the cache probe are capped the
same way.

Recorded per (repository, arm), never asserted: hit@1 and hit@5 (the
grader, ``discovery_grader``; an ungraded row counts in no rate and is
reported apart), the root causes its hypotheses target, the number of
hypotheses, the generation
and grader cost, tokens (input, output, thinking, cache reads), wall
seconds; for a control, whether any hypothesis claims a gain of at least
``BIG_GAIN``. The cache probe (``cache_probe``) generates twice with the
shipped playbook on one model and effort and records the second call's
``cache_read_input_tokens`` (expected > 0: the playbook rides in the cached
system block, ``research.playbook.research_system``).

The recorded sweep (``$LIVE_SWEEP_RECORD=1``) keeps, per (repository, arm),
what a grader check against hand labels and an offline discovery eval need,
and sends no request of its own (the caps and the need are the plain
sweep's): ``sweep_generate`` sends the arm's one generation through a
``ReplyTap`` that keeps the reply text, and ``sweep_trace`` adds to the JSON
row each hypothesis (title, rationale cut to ``RATIONALE_CHARS``, class,
expected gain, the hotspots it names), the grader's verdict on it and the
reference part it maps to, a summary of each reference part as the grader
numbered it (``reference_parts``) and the raw reply cut to ``REPLY_CHARS`` in
``JSON_TEXT_MAX`` chunks (the results sink cuts longer strings), every model
text keys-redacted (``conftest.redact_keys``). The notes, which reach the CI
log, carry one line per hypothesis (``hypothesis_notes``) and one per
reference part (``reference_notes``, once per repository), each at most
``NOTE_CHARS``, the cost table's cell cut. With the flag off nothing changes:
``sweep_generate`` is ``generate_arm`` and ``sweep_traces`` is empty.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Final

from anthropic.types.beta import BetaMessage, BetaTextBlock

from autonomous_ai_agents.clients.budget import Budget
from autonomous_ai_agents.clients.transport import LLMRequest, LLMTransport
from autonomous_ai_agents.common.config import Settings, settings
from autonomous_ai_agents.common.models import (
    METRIC_WALL_TIME_S,
    Direction,
    Hotspot,
    Hypothesis,
    ModelPrice,
    Objective,
    ObjectiveKind,
    Technique,
)
from autonomous_ai_agents.optimization.generate import (
    GENERATE_MAX_TOKENS,
    generate_hypotheses,
)
from autonomous_ai_agents.research.playbook import TechniqueMatch, load_playbook

from .conftest import _CELL_MAX, LiveRun, redact_keys
from .corpus import CORPUS, HARD_CORPUS, JSON_TEXT_MAX, MIN_FIX_GAIN, CorpusRepo
from .discovery import (
    BLIND_PROMPT_BOUND,
    FABLE,
    OPUS,
    PHASE_ONE_WORST_USD,
    PROBE_PROMPT_BOUND,
    SONNET,
    Arm,
    ArmResult,
    RepoFacts,
    ceil_usd,
    generate_arm,
    run_arm,
    worst_usd,
)
from .discovery_grader import GRADE_WORST_USD, Grade, ReferencePatch, grade
from .discovery_io import (
    ResultsSink,
    cells,
    env_flag,
    flag,
    per,
    rate,
    write_markdown,
)

ARMS_ENV: Final = "LIVE_SWEEP_ARMS"
FABLE_ENV: Final = "LIVE_SWEEP_FABLE"
RECORD_ENV: Final = "LIVE_SWEEP_RECORD"
RATIONALE_CHARS: Final = 300
REPLY_CHARS: Final = 64_000  # about GENERATE_MAX_TOKENS of text: rarely cut
REPLY_CHUNK_CHARS: Final = JSON_TEXT_MAX  # the sink never cuts a chunk
NOTE_CHARS: Final = _CELL_MAX  # the cost table cuts a longer note
PART_LINES: Final = 20  # changed lines kept per reference part
ARMS: Final = (
    Arm("opus-5-5-low", OPUS, "low"),
    Arm("opus-5-5-medium", OPUS, "medium"),
    Arm("opus-5-5-high", OPUS, "high"),
    Arm("sonnet-5-5-medium", SONNET, "medium"),
    Arm("sonnet-5-5-high", SONNET, "high"),
)
FABLE_ARM: Final = Arm("fable-5-1-medium", FABLE, "medium")
SWEEP_N: Final = 5
PROBE_ARM: Final = Arm("sonnet-5-5-medium", SONNET, "medium")


def arm_worst_usd(arm: Arm) -> float:
    """One blind generation's worst case (the shipped 16000 output tokens)."""
    return worst_usd(BLIND_PROMPT_BOUND, GENERATE_MAX_TOKENS, arm.model)


FABLE_RUN_CAP_USD: Final = ceil_usd(arm_worst_usd(FABLE_ARM) + GRADE_WORST_USD)
CACHE_PROBE_CAP_USD: Final = ceil_usd(
    2 * worst_usd(PROBE_PROMPT_BOUND, GENERATE_MAX_TOKENS, PROBE_ARM.model)
)
SWEEP_REPOS: Final = (*CORPUS, *HARD_CORPUS)
FABLE_REPOS: Final = tuple(r for r in CORPUS if r.kind == "slowdown")
BIG_GAIN: Final = MIN_FIX_GAIN  # a control's "big gain" claim: the 30 % fix bar


def sweep_arms(environ: Mapping[str, str]) -> tuple[Arm, ...]:
    """``$LIVE_SWEEP_ARMS``: unset is every arm; else comma-separated arm
    labels, each exactly one of ``ARMS``, none repeated."""
    if ARMS_ENV not in environ:
        return ARMS
    known = {arm.label: arm for arm in ARMS}
    labels = environ[ARMS_ENV].split(",")
    if any(x not in known for x in labels) or len(set(labels)) != len(labels):
        raise ValueError(
            f"{ARMS_ENV} must list distinct arms out of {', '.join(known)}, "
            f"got {environ[ARMS_ENV]!r}"
        )
    return tuple(known[label] for label in labels)


@dataclass(frozen=True)
class SweepPlan:
    arms: tuple[Arm, ...]
    fable: bool
    record: bool = False  # $LIVE_SWEEP_RECORD: no request, so no cap of its own

    def cap_for(self, repo: CorpusRepo) -> float:
        """The repository's run: phase 1, every arm, a grader per arm on a
        slowdown, each at its worst case, rounded up."""
        total = PHASE_ONE_WORST_USD + math.fsum(arm_worst_usd(a) for a in self.arms)
        if repo.kind != "control":
            total += len(self.arms) * GRADE_WORST_USD
        return ceil_usd(total)


def sweep_plan(environ: Mapping[str, str]) -> SweepPlan:
    """Every knob, validated strictly (in the module fixture, before any spend)."""
    return SweepPlan(
        arms=sweep_arms(environ),
        fable=env_flag(environ, FABLE_ENV),
        record=env_flag(environ, RECORD_ENV),
    )


def sweep_need(plan: SweepPlan) -> float:
    """The sum of the caps the suite asks the ledger for (recording adds none)."""
    fable = len(FABLE_REPOS) * FABLE_RUN_CAP_USD if plan.fable else 0.0
    repos = math.fsum(plan.cap_for(repo) for repo in SWEEP_REPOS)
    return repos + CACHE_PROBE_CAP_USD + fable


def grade_arm(
    run: LiveRun,
    budget: Budget,
    repo: CorpusRepo,
    patches: Sequence[ReferencePatch],
    result: ArmResult,
    *,
    base: Settings = settings,
) -> Grade | None:
    """The arm's grade; ``None`` for a control (no fix to grade against)."""
    if not patches:
        return None
    return grade(run, budget, repo, patches, result.hypotheses, base=base)


@dataclass(frozen=True)
class SweepRow:
    """One (repository, arm) of the sweep (recorded, never asserted)."""

    repo: str
    kind: str
    category: str
    arm: str
    model: str
    effort: str
    n_hypotheses: int
    hit_at_1: bool | None  # None: a control, or the grader failed
    hit_at_5: bool | None
    root_causes_hit: tuple[int, ...]  # the reference parts some idea targets
    root_causes: int  # how many parts the grader was shown (0: not graded)
    big_gain_claim: bool | None  # controls only
    generation_cost_usd: float
    grader_cost_usd: float
    input_tokens: int
    output_tokens: int
    thinking_tokens: int | None
    cache_read_tokens: int
    wall_s: float
    served_models: tuple[str, ...]
    phase_one_cost_usd: float
    error: str | None
    grader_error: str | None

    def record(self) -> dict[str, object]:
        return {"experiment": "E3-sweep", **asdict(self)}


def sweep_row(
    repo: CorpusRepo, result: ArmResult, graded: Grade | None, phase_cost: float
) -> SweepRow:
    claim = None
    if repo.kind == "control":
        claim = any(h.expected_gain >= BIG_GAIN for h in result.hypotheses)
    return SweepRow(
        repo=repo.name,
        kind=repo.kind,
        category=repo.category,
        arm=result.arm.label,
        model=result.arm.model,
        effort=result.arm.effort,
        n_hypotheses=len(result.hypotheses),
        hit_at_1=None if graded is None else graded.hit_at(1),
        hit_at_5=None if graded is None else graded.hit_at(SWEEP_N),
        root_causes_hit=()
        if graded is None or graded.error is not None
        else tuple(sorted({c for c in graded.causes if c is not None})),
        root_causes=0 if graded is None else graded.parts,
        big_gain_claim=claim,
        generation_cost_usd=result.cost_usd,
        grader_cost_usd=0.0 if graded is None else graded.cost_usd,
        input_tokens=result.tokens("input_tokens"),
        output_tokens=result.tokens("output_tokens"),
        thinking_tokens=result.thinking_tokens,
        cache_read_tokens=result.tokens("cache_read_tokens"),
        wall_s=round(result.wall_s, 3),
        served_models=result.models,
        phase_one_cost_usd=phase_cost,
        error=result.error,
        grader_error=None if graded is None else graded.error,
    )


# ---------------------------------------------------------------------------
# The recorded sweep ($LIVE_SWEEP_RECORD=1)
# ---------------------------------------------------------------------------


def reply_text(message: BetaMessage) -> str:
    """Every text block of ``message``, joined (an arm has no fallback, so it
    is what ``read_reply`` reads)."""
    return "".join(b.text for b in message.content if isinstance(b, BetaTextBlock))


class ReplyTap:
    """``LLMTransport`` that keeps the text of every answered reply. It sends
    nothing of its own: the count and the send are the inner transport's,
    with the same request object."""

    def __init__(self, inner: LLMTransport) -> None:
        self._inner = inner
        self.replies: list[str] = []

    @property
    def chain(self) -> tuple[str, ...]:
        return self._inner.chain

    @property
    def prices(self) -> Mapping[str, ModelPrice]:
        return self._inner.prices

    def count_input_tokens(self, request: LLMRequest) -> int:
        return self._inner.count_input_tokens(request)

    def send(self, request: LLMRequest) -> BetaMessage:
        message = self._inner.send(request)
        self.replies.append(reply_text(message))
        return message


@dataclass(frozen=True)
class Generated:
    """One arm's generation and, when recorded, its raw reply texts."""

    result: ArmResult
    replies: tuple[str, ...] = ()


def sweep_generate(
    plan: SweepPlan,
    arm: Arm,
    run: LiveRun,
    budget: Budget,
    facts: RepoFacts,
    *,
    base: Settings = settings,
) -> Generated:
    """The arm's blind generation: ``generate_arm`` itself when the plan does
    not record, else the same request through a ``ReplyTap``."""
    if not plan.record:
        return Generated(generate_arm(arm, run, budget, facts, n=SWEEP_N, base=base))
    taps: list[ReplyTap] = []

    def work(
        transport: LLMTransport, cfg: Settings, notes: list[str]
    ) -> tuple[tuple[Hypothesis, ...], tuple[TechniqueMatch, ...]]:
        tap = ReplyTap(transport)
        taps.append(tap)
        techniques: tuple[Technique, ...] = ()  # blind, as generate_arm's default
        found = generate_hypotheses(
            tap,
            budget,
            project=facts.project,
            understanding=facts.understanding,
            hotspots=facts.hotspots,
            objective=facts.objective,
            techniques=techniques,
            n=SWEEP_N,
            effort=arm.effort,
            max_tokens=GENERATE_MAX_TOKENS,
            notes=notes,
            config=cfg,
        )
        return found, ()

    result = run_arm(arm, run, base, work)
    return Generated(result, tuple(r for tap in taps for r in tap.replies))


@dataclass(frozen=True)
class RecordedHypothesis:
    """One generated hypothesis and the grader's verdict on it."""

    index: int  # 1-based, the generator's order (the grader saw a shuffle)
    title: str
    rationale: str  # cut to RATIONALE_CHARS
    change_class: str
    expected_gain: float
    hotspots: tuple[str, ...]  # "file_path:symbol" of the hotspots it names
    grader: str  # hit, miss, ungraded (grader failed or skipped it), control
    part: int | None  # the reference part the grader mapped it to


@dataclass(frozen=True)
class ReferencePart:
    """One reference diff as the grader numbered it, summarised."""

    part: int  # the grader's "root cause <part>"
    name: str
    files: tuple[str, ...]
    symbols: tuple[str, ...]  # the def or class around each changed line
    removed: int
    added: int
    removed_lines: tuple[str, ...]  # non-blank, stripped, at most PART_LINES
    added_lines: tuple[str, ...]


_HUNK: Final = re.compile(r"@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@(.*)")
_DEF: Final = re.compile(r"\s*(?:async\s+)?(?:def|class)\s+(\w+)")
_DECORATOR: Final = re.compile(r"\s*@")
_TOP_LEVEL: Final = re.compile(r"[A-Za-z_@]")


def _scope(code: str, where: str | None) -> str | None:
    """The def or class a line opens; module-level code closes ``where``."""
    found = _DEF.match(code)
    if found is not None:
        return found.group(1)
    return None if _TOP_LEVEL.match(code) else where


def _reference_part(number: int, patch: ReferencePatch) -> ReferencePart:
    files: list[str] = []
    symbols: list[str] = []
    changed: dict[str, list[str]] = {"-": [], "+": []}
    counts = {"-": 0, "+": 0}
    old = new = 0  # lines left in the current hunk
    where: str | None = None
    decorated = False  # a changed decorator waits for the def it decorates
    for line in patch.text.splitlines():
        if old <= 0 and new <= 0:  # between hunks: file headers
            hunk = _HUNK.fullmatch(line)
            if hunk is not None:
                old, new = int(hunk.group(1) or 1), int(hunk.group(2) or 1)
                where = _scope(hunk.group(3).strip(), None)
            elif line.startswith("+++ "):
                path = line[4:].split("\t")[0].removeprefix("b/")
                if path != "/dev/null" and path not in files:
                    files.append(path)
                where = None
            continue
        mark, code = line[:1] or " ", line[1:]
        if mark == "\\":  # "\ No newline at end of file"
            continue
        old -= mark != "+"
        new -= mark != "-"
        where = _scope(code, where)
        owner = where if decorated and _DEF.match(code) else None
        if mark in counts:
            counts[mark] += 1
            if code.strip():
                changed[mark].append(code.strip())
            if _DECORATOR.match(code):
                decorated = True
                continue
            owner = where
        if owner is not None:
            decorated = False
            if owner not in symbols:
                symbols.append(owner)
    return ReferencePart(
        part=number,
        name=patch.name,
        files=tuple(files),
        symbols=tuple(symbols),
        removed=counts["-"],
        added=counts["+"],
        removed_lines=tuple(changed["-"][:PART_LINES]),
        added_lines=tuple(changed["+"][:PART_LINES]),
    )


def reference_parts(patches: Sequence[ReferencePatch]) -> tuple[ReferencePart, ...]:
    """Each reference diff, numbered as the grader numbers it (from 1)."""
    return tuple(_reference_part(k, p) for k, p in enumerate(patches, start=1))


@dataclass(frozen=True)
class SweepTrace:
    """What a recorded (repository, arm) adds to its JSON row."""

    hypotheses: tuple[RecordedHypothesis, ...]
    reference_parts: tuple[ReferencePart, ...]
    reply_chunks: tuple[str, ...]  # the last reply, redacted, cut, in chunks
    reply_chars: int  # the redacted reply's whole length
    reply_truncated: bool
    replies: int  # answered generator replies (one, unless a retry answered)
    generator_notes: tuple[str, ...]  # what the generator dropped, and why

    def record(self) -> dict[str, object]:
        return asdict(self)


def _verdict(
    repo: CorpusRepo, graded: Grade | None, index: int
) -> tuple[str, int | None]:
    if repo.kind == "control":
        return "control", None
    if graded is None or graded.error is not None or index >= len(graded.hits):
        return "ungraded", None
    hit = graded.hits[index]
    part = graded.causes[index] if index < len(graded.causes) else None
    return ("ungraded" if hit is None else "hit" if hit else "miss"), part


def sweep_trace(
    repo: CorpusRepo,
    generated: Generated,
    graded: Grade | None,
    patches: Sequence[ReferencePatch],
    hotspots: Sequence[Hotspot],
) -> SweepTrace:
    """The recorded part of one (repository, arm) row (no request)."""
    spots = {h.id: f"{h.file_path}:{h.symbol}" for h in hotspots}
    ideas = []
    for index, h in enumerate(generated.result.hypotheses):
        verdict, part = _verdict(repo, graded, index)
        ideas.append(
            RecordedHypothesis(
                index=index + 1,
                title=redact_keys(h.title),
                rationale=redact_keys(h.rationale)[:RATIONALE_CHARS],
                change_class=h.change_class.value,
                expected_gain=h.expected_gain,
                hotspots=tuple(spots[i] for i in h.hotspot_ids if i in spots),
                grader=verdict,
                part=part,
            )
        )
    text = redact_keys(generated.replies[-1]) if generated.replies else ""
    kept = text[:REPLY_CHARS]
    return SweepTrace(
        hypotheses=tuple(ideas),
        reference_parts=reference_parts(patches),
        reply_chunks=tuple(
            kept[i : i + REPLY_CHUNK_CHARS]
            for i in range(0, len(kept), REPLY_CHUNK_CHARS)
        ),
        reply_chars=len(text),
        reply_truncated=len(text) > REPLY_CHARS,
        replies=len(generated.replies),
        generator_notes=tuple(redact_keys(n) for n in generated.result.notes),
    )


def sweep_traces(
    plan: SweepPlan,
    repo: CorpusRepo,
    generated: Sequence[Generated],
    grades: Sequence[Grade | None],
    patches: Sequence[ReferencePatch],
    hotspots: Sequence[Hotspot],
) -> list[SweepTrace]:
    """One trace per arm when the plan records, else none."""
    if not plan.record:
        return []
    return [
        sweep_trace(repo, made, graded, patches, hotspots)
        for made, graded in zip(generated, grades, strict=True)
    ]


def _note(head: str, body: str, tail: str = "") -> str:
    """``head + body + tail`` on one line in at most ``NOTE_CHARS``; the body
    (keys redacted) gives way first, cut with an ellipsis."""
    body = " ".join(redact_keys(body).split())
    room = NOTE_CHARS - len(head) - len(tail)
    if len(body) > room:
        body = body[: max(room - 1, 0)] + "…"
    return (head + body + tail)[:NOTE_CHARS]


def reference_notes(repo: str, parts: Sequence[ReferencePart]) -> list[str]:
    """One note per reference part (a control: one note, no part)."""
    if not parts:
        return [f"SWEEP {repo} ref: none (a control, not graded)"]
    notes = []
    for p in parts:
        where = ", ".join(p.files)
        if p.symbols:
            where += " " + ", ".join(p.symbols)
        changed = " / ".join(p.removed_lines) or "+ " + " / ".join(p.added_lines)
        head = f"SWEEP {repo} ref {p.part}/{len(parts)}: {where} -{p.removed}+{p.added}"
        notes.append(_note(head + " | ", changed))
    return notes


def hypothesis_notes(
    repo: str, arm: str, trace: SweepTrace, error: str | None
) -> list[str]:
    """One note per hypothesis: its title and the grader's verdict."""
    if not trace.hypotheses:
        return [_note(f"SWEEP {repo} {arm}: no hypotheses | ", error or "none listed")]
    return [
        _note(
            f"SWEEP {repo} {arm} #{h.index}: ",
            h.title,
            f" | grader: {h.grader} parts {'none' if h.part is None else h.part}",
        )
        for h in trace.hypotheses
    ]


@dataclass(frozen=True)
class Probe:
    """The cache probe: the same playbook twice on one model and effort."""

    model: str
    effort: str
    first_cache_write: int
    second_cache_read: int
    cost_usd: float
    answered: bool
    error: str | None

    @property
    def hit(self) -> bool:
        return self.second_cache_read > 0

    def record(self) -> dict[str, object]:
        return {"experiment": "E3-cache-probe", "hit": self.hit, **asdict(self)}


def cache_probe(run: LiveRun, repo: CorpusRepo, *, base: Settings = settings) -> Probe:
    """Two generator calls with the whole shipped playbook; no repository
    is read or run (the facts are the project's name and an objective)."""
    project = repo.project(repo.path)
    objective = Objective(
        project_id=project.id,
        kind=ObjectiveKind.runtime,
        metric=METRIC_WALL_TIME_S,
        direction=Direction.minimize,
        min_relative_gain=base.MIN_RELATIVE_GAIN,
        description="minimize wall time",
    )
    facts = RepoFacts(project, None, (), objective)
    budget = Budget(run.cap_usd)
    playbook = load_playbook()
    calls = [
        generate_arm(PROBE_ARM, run, budget, facts, n=3, techniques=playbook, base=base)
        for _ in range(2)
    ]
    usages = [u for call in calls for u in call.usages]
    errors = [c.error for c in calls if c.error is not None]
    return Probe(
        model=PROBE_ARM.model,
        effort=PROBE_ARM.effort,
        first_cache_write=usages[0].cache_write_tokens if usages else 0,
        second_cache_read=usages[1].cache_read_tokens if len(usages) > 1 else 0,
        cost_usd=math.fsum(c.cost_usd for c in calls),
        answered=len(usages) == 2,
        error="; ".join(errors) or None,
    )


def _arm_line(label: str, rows: Sequence[SweepRow]) -> list[object]:
    slow = [r for r in rows if r.kind != "control"]
    graded = [r for r in slow if r.hit_at_5 is not None]
    controls = [r for r in rows if r.kind == "control"]
    hits1 = sum(r.hit_at_1 is True for r in graded)
    hits5 = sum(r.hit_at_5 is True for r in graded)
    spend = math.fsum(r.generation_cost_usd for r in rows)
    slow_spend = math.fsum(r.generation_cost_usd for r in graded)
    claims = sum(r.big_gain_claim is True for r in controls)
    return [
        label,
        rate(hits1, len(graded)),
        rate(hits5, len(graded)),
        per(spend, len(rows)),
        per(slow_spend, hits5),
        rate(claims, len(controls)),
        len(slow) - len(graded),
    ]


def _causes(row: SweepRow) -> str:
    if not row.root_causes:
        return "-"
    hit = ", ".join(str(c) for c in row.root_causes_hit) or "none"
    return f"{hit} of {row.root_causes}"


def render_sweep(rows: Sequence[SweepRow], probes: Sequence[Probe]) -> str:
    """The sweep summary: one row per (repository, arm), then per arm."""
    lines = ["## Blind hypothesis sweep (E3)", ""]
    if rows:
        lines += [
            "| repo | kind | arm | hypotheses | hit at 1 | hit at 5 | root causes "
            "| big gain claim | generation USD | grader USD | output | thinking "
            "| cache read | wall s | error |",
            "| --- | --- | --- | ---: | --- | --- | --- | --- | ---: | ---: | ---: "
            "| ---: | ---: | ---: | --- |",
        ]
        for r in rows:
            lines.append(
                cells(
                    [
                        r.repo,
                        r.kind,
                        r.arm,
                        r.n_hypotheses,
                        flag(r.hit_at_1),
                        flag(r.hit_at_5),
                        _causes(r),
                        flag(r.big_gain_claim),
                        f"{r.generation_cost_usd:.4f}",
                        f"{r.grader_cost_usd:.4f}",
                        r.output_tokens,
                        "-" if r.thinking_tokens is None else r.thinking_tokens,
                        r.cache_read_tokens,
                        f"{r.wall_s:.1f}",
                        r.error or r.grader_error or "-",
                    ]
                )
            )
        lines += [
            "",
            "| arm | hit at 1 rate | hit at 5 rate | cost per repo USD | cost per hit "
            "USD (graded slowdown spend / hits at 5) | control big-gain claims "
            "| ungraded slowdowns |",
            "| --- | --- | --- | ---: | ---: | --- | ---: |",
        ]
        for label in dict.fromkeys(r.arm for r in rows):
            lines.append(cells(_arm_line(label, [r for r in rows if r.arm == label])))
    else:
        lines.append("No sweep repository finished.")
    for probe in probes:
        lines += [
            "",
            cells(
                [
                    f"Cache probe {probe.model} {probe.effort}: first write "
                    f"{probe.first_cache_write}, second read "
                    f"{probe.second_cache_read} tokens, cache hit: "
                    f"{flag(probe.hit)}, {probe.cost_usd:.4f} USD"
                    + (f", {probe.error}" if probe.error else "")
                ]
            ),
        ]
    return "\n".join(lines)


@dataclass
class SweepRecorder:
    """The module's rows and probes; ``finish`` writes the summary once."""

    plan: SweepPlan
    sink: ResultsSink
    rows: list[SweepRow] = field(default_factory=list)
    probes: list[Probe] = field(default_factory=list)
    referenced: set[str] = field(default_factory=set)  # repos whose parts are noted

    def record(
        self, rows: Sequence[SweepRow], run: LiveRun, traces: Sequence[SweepTrace] = ()
    ) -> None:
        """One JSON line and one note per row; with ``traces`` (one per row,
        the recorded sweep) the trace joins the line, and the notes gain the
        repository's reference parts (once) and one line per hypothesis."""
        if traces and len(traces) != len(rows):
            raise ValueError(f"{len(traces)} trace(s) for {len(rows)} row(s)")
        for index, row in enumerate(rows):
            trace = traces[index] if traces else None
            self.rows.append(row)
            if trace is not None and row.repo not in self.referenced:
                self.referenced.add(row.repo)
                for note in reference_notes(row.repo, trace.reference_parts):
                    run.note(note)
            line = row.record() if trace is None else {**row.record(), **trace.record()}
            self.sink.write(line)
            run.note(
                f"sweep {row.repo} {row.arm}: {row.n_hypotheses} hypotheses, "
                f"hit@1 {flag(row.hit_at_1)}, hit@5 {flag(row.hit_at_5)}"
            )
            if trace is not None:
                for note in hypothesis_notes(row.repo, row.arm, trace, row.error):
                    run.note(note)

    def record_probe(self, probe: Probe, run: LiveRun) -> None:
        self.probes.append(probe)
        self.sink.write(probe.record())
        run.note(f"cache probe: second read {probe.second_cache_read} tokens")

    def finish(self, echo: Callable[[str], None]) -> None:
        if self.rows or self.probes:
            text = render_sweep(self.rows, self.probes)
            write_markdown("Blind hypothesis sweep", text, self.sink.environ, echo)
