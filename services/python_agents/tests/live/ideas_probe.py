"""V7: the ``ideas-probe`` suite, idea-only (spec amendment 3.6 and section 6:
E0b, E1, E1b; D55, D58, D63, D65; owner decision O15).

Per library one live run, no trial: phase 1 on a fresh clone (as
``discovery_oss.run_task`` steps 1-2: ``start_oss_phase_one``, every corpus
guard, Sonnet 5.5 without fallbacks), or the facts an earlier dispatch
recorded (``$LIVE_IDEAS_FACTS``, a JSON-lines file of ``ideas-facts``
records, read on a fresh clone at the same head); then each arm of
``$LIVE_IDEAS_ARMS`` (comma separated, distinct) generates once from those
facts: ``A`` today's generator (``ClaudeHypothesisGenerator``), ``B``-``E``
and the E1b variants the factory's ``IdeaPipelineGenerator`` with
``repo_reader`` (B all-Sonnet, C the defaults, D a Fable 5.1 leap and
reviewer at 20,000 tokens, E Haiku lanes; ``C-low``/``C-high`` arm C with
the lanes at that effort), each role on its own captured transport.
``count`` (E0b, alone) is arm C with one lane worker: every request is
counted (``count_tokens``, free), only S1 and the first lens lane are sent,
the rest refused for nothing. With any E1 arm (A-E) one auditor pass per
library: the reviewer prompt on Opus 5.5 ``high`` at 20,000 tokens over at
most 48 pooled ideas (each arm's returned non-obvious ideas, its own
reviewer's removals, then the rest), neutral ids, its cost in the cap.

Minutes: each sequential model stage counts ``STAGE_MINUTES`` (S1, two lens
rounds on four workers, the reviewer: four a pipeline call), phase 1
``PHASE_ONE_MINUTES`` (re-pinned from E0b: a count-mode library took about
47 s; the stage minutes stay until E1's recorded seconds re-pin them, as E0b
timed only count mode's Sonnet sends, 9-18 s); a plan past ci.yml's
``JOB_MINUTES`` is refused, so E1 (56 minutes a library) runs four
libraries a dispatch (``$LIVE_IDEAS_REPOS``, 224; five would take 280).
Count mode (8 minutes a library) also counts the reviewer request with its
ideas repeated under fresh ids up to ``IDEAS_REVIEW_MAX_IDEAS`` (D55's
reviewer bound is for 16 ideas; S1 and one lens give fewer).

Caps: an arm's cap is the sum of its requests' worst cases on D55's bounds,
re-derived from E0b's counted maxima (D61; the E1 row: B 1.99, C 2.475, D
4.53, E 1.045, the auditor 0.69; A on the oss-ab suite's measured blind
bound, 0.27), count mode's real spend is ``COUNT_SENT`` lane requests (0.43,
the tap refuses past it); a library's run is phase 1, its arms and the
auditor, rounded up (E1 11.40, count 0.85, C-low/C-high 4.95); a plan past
the 150 USD ceiling is refused in the module fixture. Fable (30-day
retention) gets ``ALLOW_RETENTION_MODELS`` only in arm D's copy and only for
a library of the pinned OSS manifests (O15); the flag is cleared in every
other copy.

Recorded, never asserted (``$LIVE_RESULTS_PATH``): per library the facts
(``ideas-facts``, chunked JSON, keys redacted), per (library, arm) a row
(``ideas-probe``: ideas, non-obvious, good, auditor and own-reviewer counts,
the auditor's error (then no arm's good count is known), cost, ``IdeaStats``,
``stop_reason``, cache reads and counted tokens per request), every request's
reply (``ideas-reply``, redacted, chunked, with its shown ideas and seconds) and
every pooled idea's verdicts (``ideas-audit``); a cost-table note per
library and a summary table.
"""

from __future__ import annotations

import dataclasses
import functools
import itertools
import math
import re
import threading
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Final, Literal, cast

from anthropic.types.beta import BetaMessage, BetaMessageParam
from e2e.conftest import Isolation
from pydantic import BaseModel, ConfigDict, ValidationError

from autonomous_ai_agents.clients.budget import Budget
from autonomous_ai_agents.clients.cost import preflight_estimate
from autonomous_ai_agents.clients.structured import Fence, data_line
from autonomous_ai_agents.clients.transport import LLMRequest, LLMTransport, call
from autonomous_ai_agents.common.config import (
    RETENTION_REQUIRED_MODELS,
    Effort,
    Role,
    Settings,
    role_chain,
    role_settings,
    settings,
)
from autonomous_ai_agents.common.errors import LLMRequestError
from autonomous_ai_agents.common.models import (
    ChangeClass,
    Hotspot,
    Hypothesis,
    ModelPrice,
    Objective,
    Project,
    ProjectUnderstanding,
)
from autonomous_ai_agents.common.repo_read import RepoReader
from autonomous_ai_agents.optimization.hypothesis_source import (
    ClaudeHypothesisGenerator,
)
from autonomous_ai_agents.optimization.idea_context import (
    IdeaReadLimits,
    read_code_context,
    render_data_block,
)
from autonomous_ai_agents.optimization.idea_pipeline import IdeaPipelineGenerator
from autonomous_ai_agents.optimization.idea_review import read_review, review_request
from autonomous_ai_agents.optimization.idea_types import (
    Anchor,
    IdeaCandidate,
    Lane,
    Mechanism,
    MorphCell,
    ReviewVerdict,
    Tier,
    Typicality,
)
from autonomous_ai_agents.optimization.sources import (
    GenerateResult,
    HypothesisGenerator,
)
from autonomous_ai_agents.orchestrator.factory import PIPELINE_ROLES, repo_reader

from .conftest import _CELL_MAX, TESTS_DIR, LiveRun, StartLive, redact_keys
from .corpus import JSON_TEXT_MAX, check_loop_guards
from .discovery import (
    ARM_ERRORS,
    FABLE,
    OPUS,
    SONNET,
    RepoFacts,
    ceil_usd,
    check_untouched,
    model_settings,
    read_phase_one,
    worst_usd,
)
from .discovery_ab import (
    IDEAS_LANE_PROMPT_BOUND,
    IDEAS_REVIEW_PROMPT_BOUND,
    ab_settings,
)
from .discovery_grader import reply_text
from .discovery_io import ResultsSink, cells, write_markdown
from .discovery_oss import (
    CAP_CEILING_USD,
    OSS_BLIND_PROMPT_BOUND,
    OSS_PHASE_ONE_WORST_USD,
    OSS_SELECTABLE,
    _keys,
    engine_settings,
    start_oss_phase_one,
)
from .oss import OSS_CORPUS, PRODUCTION, GitPolicy, OssRepo, prepare_repo

ARMS_ENV: Final = "LIVE_IDEAS_ARMS"
REPOS_ENV: Final = "LIVE_IDEAS_REPOS"
FACTS_ENV: Final = "LIVE_IDEAS_FACTS"
SERVICE_DIR: Final = TESTS_DIR.parent
FACTS_FIXTURE: Final = "tests/fixtures/ideas_probe/facts.jsonl"  # E1b's (from E1)
ROW_EXPERIMENT: Final = "ideas-probe"
FACTS_EXPERIMENT: Final = "ideas-facts"
REPLY_EXPERIMENT: Final = "ideas-reply"
AUDIT_EXPERIMENT: Final = "ideas-audit"
HAIKU: Final = "claude-haiku-5-5"
# D55's lane and reviewer bounds are discovery_ab's (one source, re-derived
# from E0b, D61); the auditor's over 48 ideas: about 33.1k base + 48 x ~420
# a reviewed idea = 53.3k, + margin
LANE_PROMPT_BOUND: Final = IDEAS_LANE_PROMPT_BOUND
REVIEW_PROMPT_BOUND: Final = IDEAS_REVIEW_PROMPT_BOUND
AUDIT_PROMPT_BOUND: Final = 58_000
AUDIT_MAX_TOKENS: Final = 20_000
AUDIT_MAX_IDEAS: Final = 48
AUDIT_EFFORT: Final[Effort] = "high"
RETENTION_MAX_TOKENS: Final = 20_000  # arm D's Fable leap and reviewer (D58)
COUNT_SENT: Final = 2  # count mode sends S1 and the first lens lane
JOB_MINUTES: Final = 240  # ci.yml's ideas-probe timeout: E1 four libraries
# one long request: kept until E1's recorded seconds re-pin it (E0b timed only
# count mode's Sonnet sends, 8.8-18.4 s; Opus and Fable at 16-20k unmeasured)
STAGE_MINUTES: Final = 3
PHASE_ONE_MINUTES: Final = 2  # E0b: a whole count-mode library about 47 s
CLONE_MINUTES: Final = 1  # recorded facts: a fresh clone only
NOTE_CHARS: Final = _CELL_MAX
E1_REPOS: Final = (
    "more_itertools", "pyparsing", "tomli", "sortedcontainers",
    "mistune", "sqlparse", "markdown", "idna",
)  # fmt: skip
E1B_REPOS: Final = ("pyparsing", "tomli", "mistune", "markdown")
OSS_NAMES: Final = frozenset(repo.name for repo in OSS_SELECTABLE)
_ROLES: Final[tuple[Role, ...]] = ("generator", *PIPELINE_ROLES)
_REVIEW_TOKEN: Final = re.compile(r"The review boundary token is (\w+)\.")

# ---------------------------------------------------------------------------
# Arms, caps and the plan
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IdeaArm:
    """One arm: its key, the generator it runs and its settings overrides."""

    key: str
    pipeline: bool  # False: today's generator
    update: tuple[tuple[str, object], ...] = ()
    e1: bool = True  # an E1 arm: the auditor pools its ideas


ARM_A: Final = IdeaArm("A", pipeline=False)
ARM_B: Final = IdeaArm(
    "B", True, (("IDEAS_LEAP_MODEL", SONNET), ("IDEAS_REVIEWER_MODEL", SONNET))
)
ARM_C: Final = IdeaArm("C", True)
ARM_D: Final = IdeaArm(
    "D",
    True,
    (
        ("IDEAS_LEAP_MODEL", FABLE),
        ("IDEAS_LEAP_MAX_TOKENS", RETENTION_MAX_TOKENS),
        ("IDEAS_REVIEWER_MODEL", FABLE),
        ("IDEAS_REVIEWER_MAX_TOKENS", RETENTION_MAX_TOKENS),
    ),
)
ARM_E: Final = IdeaArm("E", True, (("IDEAS_LANE_MODEL", HAIKU),))
ARM_C_LOW: Final = IdeaArm("C-low", True, (("IDEAS_LANE_EFFORT", "low"),), e1=False)
ARM_C_HIGH: Final = IdeaArm("C-high", True, (("IDEAS_LANE_EFFORT", "high"),), e1=False)
ARM_COUNT: Final = IdeaArm("count", True, (("IDEAS_LANE_WORKERS", 1),), e1=False)
IDEA_ARMS: Final = (ARM_COUNT, ARM_A, ARM_B, ARM_C, ARM_D, ARM_E, ARM_C_LOW, ARM_C_HIGH)
E1_ARMS: Final = (ARM_A, ARM_B, ARM_C, ARM_D, ARM_E)


def arm_config(arm: IdeaArm, project: Project, base: Settings = settings) -> Settings:
    """The arm's validated settings copy. A retention model (D63) is admitted
    only for a library of the pinned OSS manifests (O15), by setting the flag
    in this copy; every other copy has it off, whatever ``base`` says."""
    raw = base.model_copy(update=dict(arm.update))
    needs = sorted(
        {m for role in _ROLES for m in role_chain(raw, role)}
        & RETENTION_REQUIRED_MODELS
    )
    if needs and project.name not in OSS_NAMES:
        raise ValueError(
            f"arm {arm.key}: {', '.join(needs)} keeps data 30 days and may see code "
            f"only on a pinned OSS library (O15), not {project.name!r}"
        )
    update = {
        **dict(arm.update),
        "IDEA_PIPELINE": arm.pipeline,
        "ALLOW_RETENTION_MODELS": bool(needs),
    }
    return type(base).model_validate(base.model_copy(update=update).model_dump())


def request_usd(bound: int, max_tokens: int, model: str) -> float:
    """D55's worst case of one request whose count (margin and allowance
    included) is at most ``bound``."""
    return preflight_estimate(bound, max_tokens, (model,), settings.MODEL_PRICING)


def pipeline_usd(cfg: Settings) -> float:
    """One pipeline call at its worst: S1 and the lenses, the leap, the reviewer."""
    lane = request_usd(
        LANE_PROMPT_BOUND, cfg.IDEAS_LANE_MAX_TOKENS, cfg.IDEAS_LANE_MODEL
    )
    leap = request_usd(
        LANE_PROMPT_BOUND, cfg.IDEAS_LEAP_MAX_TOKENS, cfg.IDEAS_LEAP_MODEL
    )
    review = request_usd(
        REVIEW_PROMPT_BOUND, cfg.IDEAS_REVIEWER_MAX_TOKENS, cfg.IDEAS_REVIEWER_MODEL
    )
    return math.fsum(
        (
            (1 + len(cfg.IDEAS_LENSES)) * lane,
            leap if cfg.IDEAS_LEAP_N else 0.0,
            review if cfg.IDEAS_REVIEW else 0.0,
        )
    )


def count_usd(cfg: Settings) -> float:
    return COUNT_SENT * request_usd(
        LANE_PROMPT_BOUND, cfg.IDEAS_LANE_MAX_TOKENS, cfg.IDEAS_LANE_MODEL
    )


def arm_usd(arm: IdeaArm, base: Settings = settings) -> float:
    """What the arm may spend: today's generator on the OSS blind bound, a
    pipeline call, or count mode's sent requests."""
    raw = base.model_copy(update=dict(arm.update))
    if not arm.pipeline:
        return worst_usd(
            OSS_BLIND_PROMPT_BOUND, raw.GENERATOR_MAX_TOKENS, raw.GENERATOR_MODEL
        )
    return count_usd(raw) if arm is ARM_COUNT else pipeline_usd(raw)


AUDIT_USD: Final = request_usd(AUDIT_PROMPT_BOUND, AUDIT_MAX_TOKENS, OPUS)


def arm_stages(arm: IdeaArm, base: Settings = settings) -> int:
    """The arm's model requests in sequence: one for today's generator,
    count mode's sends, or S1, the lens rounds (the lenses and the leap on
    ``IDEAS_LANE_WORKERS``) and the reviewer."""
    if not arm.pipeline or arm is ARM_COUNT:
        return 1 if not arm.pipeline else COUNT_SENT
    cfg = base.model_copy(update=dict(arm.update))
    fan = len(cfg.IDEAS_LENSES) + (1 if cfg.IDEAS_LEAP_N else 0)
    return 1 + math.ceil(fan / cfg.IDEAS_LANE_WORKERS) + (1 if cfg.IDEAS_REVIEW else 0)


@dataclass(frozen=True)
class ProbePlan:
    arms: tuple[IdeaArm, ...]
    repos: tuple[OssRepo, ...]
    facts: Path | None = None  # recorded facts: no phase 1

    @property
    def audit(self) -> bool:
        return any(arm.e1 for arm in self.arms)

    def library_cap(self) -> float:
        phase = 0.0 if self.facts is not None else OSS_PHASE_ONE_WORST_USD
        audit = AUDIT_USD if self.audit else 0.0
        return ceil_usd(math.fsum((phase, audit, *map(arm_usd, self.arms))))

    def library_minutes(self) -> int:
        phase = CLONE_MINUTES if self.facts is not None else PHASE_ONE_MINUTES
        stages = sum(map(arm_stages, self.arms)) + (1 if self.audit else 0)
        return phase + STAGE_MINUTES * stages

    def minutes(self) -> int:
        return len(self.repos) * self.library_minutes()


def probe_need(plan: ProbePlan) -> float:
    return len(plan.repos) * plan.library_cap()


def probe_arms(environ: Mapping[str, str]) -> tuple[IdeaArm, ...]:
    keys = _keys(environ, ARMS_ENV, [arm.key for arm in IDEA_ARMS])
    if keys is None:
        return E1_ARMS
    if ARM_COUNT.key in keys and len(keys) > 1:
        raise ValueError(f"{ARMS_ENV}: count runs alone, got {environ[ARMS_ENV]!r}")
    return tuple(arm for arm in IDEA_ARMS if arm.key in keys)


def probe_repos(
    environ: Mapping[str, str], arms: Sequence[IdeaArm]
) -> tuple[OssRepo, ...]:
    """``$LIVE_IDEAS_REPOS``, else the run's own: E0b the first OSS set, E1b
    its four, E1 its eight."""
    names = _keys(environ, REPOS_ENV, [repo.name for repo in OSS_SELECTABLE])
    if names is None:
        if tuple(arms) == (ARM_COUNT,):
            return OSS_CORPUS
        names = E1_REPOS if any(arm.e1 for arm in arms) else E1B_REPOS
    return tuple(repo for repo in OSS_SELECTABLE if repo.name in names)


def facts_path(environ: Mapping[str, str]) -> Path | None:
    raw = environ.get(FACTS_ENV, "")
    if not raw:
        return None
    path = Path(raw) if Path(raw).is_absolute() else SERVICE_DIR / raw
    if not path.is_file():
        raise ValueError(f"{FACTS_ENV}: no recorded facts at {raw!r} (an E1 run's)")
    return path


def probe_plan(environ: Mapping[str, str]) -> ProbePlan:
    """Every knob, strictly, and a plan past the ceiling or the job's
    minutes refused (in the module fixture, before any spend)."""
    arms = probe_arms(environ)
    plan = ProbePlan(arms, probe_repos(environ, arms), facts_path(environ))
    need, minutes = probe_need(plan), plan.minutes()
    what = f"{len(plan.repos)} libraries x arms {','.join(a.key for a in arms)}"
    fewer = f"name fewer in {REPOS_ENV} or {ARMS_ENV}"
    if need > CAP_CEILING_USD:
        raise ValueError(
            f"{what} need {need:.2f} USD, past the {CAP_CEILING_USD:g} USD "
            f"ceiling of a live-smoke dispatch: {fewer}"
        )
    if minutes > JOB_MINUTES:
        raise ValueError(
            f"{what} take about {minutes} minutes, past the {JOB_MINUTES}-minute "
            f"job (a killed job loses the rest): {fewer}"
        )
    return plan


# ---------------------------------------------------------------------------
# Facts: from phase 1, recorded, reloaded on a fresh clone
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IdeaFacts:
    """What every arm generates from: phase 1's facts and the run's keys."""

    facts: RepoFacts
    commit: str
    run_id: str
    protected: tuple[str, ...]

    def record(self) -> dict[str, object]:
        text = redact_keys(FactsBody.of(self).model_dump_json())
        return {
            "experiment": FACTS_EXPERIMENT,
            "repo": self.facts.project.name,
            "chunks": _chunks(text),
        }


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FactsBody(_Strict):
    commit: str
    run_id: str
    protected: tuple[str, ...]
    project: Project
    understanding: ProjectUnderstanding | None
    hotspots: tuple[Hotspot, ...]
    objective: Objective

    @classmethod
    def of(cls, facts: IdeaFacts) -> FactsBody:
        f = facts.facts
        return cls(
            commit=facts.commit, run_id=facts.run_id, protected=facts.protected,
            project=f.project, understanding=f.understanding, hotspots=f.hotspots,
            objective=f.objective,
        )  # fmt: skip


class _FactsLine(_Strict):
    experiment: Literal["ideas-facts"]
    repo: str
    chunks: tuple[str, ...]


def _chunks(text: str) -> tuple[str, ...]:
    step = JSON_TEXT_MAX  # the sink cuts a longer string
    return tuple(text[i : i + step] for i in range(0, len(text), step))


def load_facts(path: Path) -> dict[str, FactsBody]:
    """The ``ideas-facts`` records of a results file, by library, strictly."""
    found: dict[str, FactsBody] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if f'"experiment": "{FACTS_EXPERIMENT}"' not in line:
            continue
        record = _FactsLine.model_validate_json(line)
        if record.repo in found:
            raise ValueError(f"{path}: facts for {record.repo} recorded twice")
        found[record.repo] = FactsBody.model_validate_json("".join(record.chunks))
    return found


def phase_facts(
    repo: OssRepo, run: LiveRun, root: Path, isolation: Isolation, policy: GitPolicy
) -> tuple[IdeaFacts, Callable[[], None]]:
    """Phase 1 as the run's first spend, every corpus guard; the facts and
    the check that the clone is untouched."""
    if run.records:
        raise ValueError("phase one must be the first spend of its run")
    root.mkdir(parents=True, exist_ok=True)
    loop = start_oss_phase_one(repo, run, root, isolation, policy=policy)
    result = loop.run()
    check_loop_guards(loop, run, result, isolation)
    phase, state = read_phase_one(loop, run, result), result.state
    commit = state["base_commit"]
    if commit is None:
        raise ValueError("phase one ended without a base commit")
    protected = (*loop.context.protected_patterns, *state["extra_protected"])
    facts = IdeaFacts(phase.facts, commit, state["run_id"], tuple(protected))
    return facts, functools.partial(check_untouched, phase)


def clone_facts(
    repo: OssRepo, body: FactsBody, dest: Path, policy: GitPolicy
) -> IdeaFacts:
    """Recorded facts on a fresh clone at the recorded head."""
    if body.project.name != repo.name:
        raise ValueError(f"facts recorded for {body.project.name}, not {repo.name}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    user = prepare_repo(repo, dest, policy=policy)
    if user.base != body.commit:
        raise ValueError(
            f"{repo.name}: head {user.base} is not the recorded {body.commit}"
        )
    project = body.project.model_copy(update={"root_path": str(user.path)})
    facts = RepoFacts(project, body.understanding, body.hotspots, body.objective)
    return IdeaFacts(facts, body.commit, body.run_id, body.protected)


# ---------------------------------------------------------------------------
# The tap: every request counted, labelled, its reply kept; count mode
# ---------------------------------------------------------------------------


@dataclass
class Exchange:
    """One request of an arm: its label, count and, when sent, its reply."""

    role: str
    label: str
    counted: int
    request: LLMRequest
    sent: bool = False
    stop_reason: str | None = None
    usage: tuple[int, int, int, int] = (0, 0, 0, 0)  # in, out, cache read, write
    reply: str = ""
    seconds: float = 0.0  # the send's wall time


class Tap:
    """``LLMTransport`` that labels each request at its count (``labels`` in
    the order the generator counts them) and keeps its reply. ``sends``: at
    most that many sends, each within ``send_cap_usd`` together (count mode);
    any other send is refused before the wire, for nothing."""

    def __init__(
        self,
        inner: LLMTransport,
        role: str,
        labels: Sequence[str],
        *,
        sends: int | None = None,
        send_cap_usd: float = math.inf,
    ) -> None:
        self._inner, self.role, self._labels = inner, role, tuple(labels)
        self._sends, self._left = sends, send_cap_usd
        self.exchanges: list[Exchange] = []
        self._lock = threading.Lock()

    @property
    def chain(self) -> tuple[str, ...]:
        return self._inner.chain

    @property
    def prices(self) -> Mapping[str, ModelPrice]:
        return self._inner.prices

    def count_input_tokens(self, request: LLMRequest) -> int:
        counted = self._inner.count_input_tokens(request)
        with self._lock:
            k = len(self.exchanges)
            label = self._labels[k] if k < len(self._labels) else f"{self.role}-{k + 1}"
            self.exchanges.append(Exchange(self.role, label, counted, request))
        return counted

    def send(self, request: LLMRequest) -> BetaMessage:
        found = next((e for e in self.exchanges if e.request is request), None)
        if found is None:  # every caller counts first; count it now if not
            self.count_input_tokens(request)
            found = self.exchanges[-1]
        with self._lock:
            if self._sends is not None:
                estimate = preflight_estimate(
                    found.counted, request.max_tokens, self.chain, self.prices
                )
                done = sum(e.sent for e in self.exchanges)
                if done >= self._sends or estimate > self._left:
                    raise LLMRequestError(
                        f"count mode: {found.label} counted, not sent"
                    )
                self._left -= estimate
            found.sent = True
        began = time.monotonic()
        message = self._inner.send(request)
        found.seconds = time.monotonic() - began
        u = message.usage
        found.usage = (
            u.input_tokens, u.output_tokens,
            u.cache_read_input_tokens or 0, u.cache_creation_input_tokens or 0,
        )  # fmt: skip
        found.stop_reason, found.reply = message.stop_reason, reply_text(message)
        return message


# ---------------------------------------------------------------------------
# One arm
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ArmRun:
    arm: IdeaArm
    result: GenerateResult | None
    error: str | None
    cost_usd: float
    models: tuple[str, ...]  # what the recorder billed
    billable: tuple[str, ...]  # the arm's role chains
    exchanges: tuple[Exchange, ...]


def _taps(arm: IdeaArm, cfg: Settings, run: LiveRun) -> dict[Role, Tap]:
    if not arm.pipeline:
        inner = run.transport(role_settings(cfg, "generator"))
        return {"generator": Tap(inner, "generator", ("generator",))}
    labels = {
        "lane": ("obvious", *(lane.value for lane in cfg.IDEAS_LENSES)),
        "leap": ("leap",),
        "reviewer": ("reviewer", f"reviewer-{cfg.IDEAS_REVIEW_MAX_IDEAS}"),
    }
    counting = arm is ARM_COUNT
    return {
        role: Tap(
            run.transport(role_settings(cfg, role)),
            role,
            labels[role],
            sends=(COUNT_SENT if role == "lane" else 0) if counting else None,
            send_cap_usd=count_usd(cfg) if counting else math.inf,
        )  # fmt: skip
        for role in PIPELINE_ROLES
    }


def _count_full_review(tap: Tap, n: int) -> None:
    """Count mode: the reviewer request counted again with ``n`` ideas."""
    full = padded_review(tap.exchanges[0].request, n) if tap.exchanges else None
    if full is not None:
        tap.count_input_tokens(full)


def run_arm(
    arm: IdeaArm,
    run: LiveRun,
    facts: IdeaFacts,
    *,
    base: Settings = settings,
    reader: Callable[[Project], RepoReader] = repo_reader,
    cap: float | None = None,
) -> ArmRun:
    """One generation from ``facts`` on the arm's own transports, under its
    cap (``arm_usd``; a pipeline arm's reservations need the whole call's,
    count mode's real spend is bounded by its taps)."""
    f = facts.facts
    cfg = arm_config(arm, f.project, base)
    taps = _taps(arm, cfg, run)
    generator: HypothesisGenerator = (
        IdeaPipelineGenerator(taps, reader=reader, config=cfg)
        if arm.pipeline
        else ClaudeHypothesisGenerator(taps["generator"], config=cfg)
    )
    if cap is None:
        cap = pipeline_usd(cfg) if arm.pipeline else arm_usd(arm, base)
    first = len(run.records)
    result: GenerateResult | None = None
    error: str | None = None
    try:
        result = generator.generate(
            project=f.project, understanding=f.understanding, hotspots=f.hotspots,
            objective=f.objective, techniques=(), lessons=(), avoid_titles=(),
            n=cfg.GENERATOR_N, budget=Budget(cap), commit=facts.commit,
            run_id=facts.run_id, protected=facts.protected,
        )  # fmt: skip
        if arm is ARM_COUNT:  # D55's reviewer bound is for 16 ideas
            _count_full_review(taps["reviewer"], cfg.IDEAS_REVIEW_MAX_IDEAS)
    except ARM_ERRORS as exc:
        error = f"{type(exc).__name__}: {exc}"
    records = run.records[first:]
    return ArmRun(
        arm=arm,
        result=result,
        error=error,
        cost_usd=math.fsum(r.cost_usd for r in records),
        models=tuple(dict.fromkeys(r.model for r in records)),
        billable=tuple(dict.fromkeys(m for t in taps.values() for m in t.chain)),
        exchanges=tuple(e for tap in taps.values() for e in tap.exchanges),
    )


# ---------------------------------------------------------------------------
# The auditor: the pool, one review on Opus high, the scores
# ---------------------------------------------------------------------------


class ShownIdea(_Strict):
    """One idea as the reviewer's data line shows it (``idea_review._rendered``)."""

    id: str
    lane: str
    title: str
    change_class: str
    anchor: str | None
    change_summary: str
    precondition: str
    equivalence_summary: str
    depends_on_path: str
    depends_on_quote: str


class _Review(_Strict):
    idea: str
    verdict: ReviewVerdict
    reason: str
    duplicate_of: str | None
    change_plan: str


class _Reviews(_Strict):
    reviews: tuple[_Review, ...]


@dataclass(frozen=True)
class Pooled:
    arm: str
    idea: ShownIdea
    own: str | None  # the arm's own reviewer's verdict (None: none, or A)
    in_result: bool  # the arm handed it on


def _request_text(request: LLMRequest) -> str:
    content = request.messages[0]["content"]
    if isinstance(content, str):
        return content
    blocks = cast(Sequence[Mapping[str, object]], content)
    return "\n".join(str(block.get("text", "")) for block in blocks)


def shown_ideas(request: LLMRequest) -> list[ShownIdea]:
    """The ideas a reviewer request shows, from its fenced block."""
    text = _request_text(request)
    found = _REVIEW_TOKEN.search(text)
    if found is None:
        return []
    boundary = f"untrusted_model_content boundary={found.group(1)}>"
    body = text[text.index(f"<{boundary}", found.end()) :]
    lines = body[len(boundary) + 1 : body.index(f"</{boundary}")].splitlines()
    return [ShownIdea.model_validate_json(line) for line in lines if line]


def padded_review(request: LLMRequest, n: int) -> LLMRequest | None:
    """A reviewer request's ideas repeated under fresh ids up to ``n``, the
    rest of its text unchanged; ``None``: it shows no idea."""
    ideas = shown_ideas(request)
    if not ideas:
        return None
    text = _request_text(request)
    token = cast(re.Match[str], _REVIEW_TOKEN.search(text)).group(1)
    close = f"</untrusted_model_content boundary={token}>"
    extra = [
        data_line({**idea.model_dump(), "id": f"pad-{k:02d}"})
        for k, idea in zip(range(1, n - len(ideas) + 1), itertools.cycle(ideas))
    ]
    text = text.replace(close, "\n".join((*extra, close)), 1)
    message: BetaMessageParam = {
        "role": "user",
        "content": [{"type": "text", "text": text}],
    }
    return dataclasses.replace(request, messages=(message,))


def own_verdicts(reply: str) -> dict[str, str]:
    """Each id reviewed once and its verdict; an unreadable reply gives none."""
    try:
        reviews = _Reviews.model_validate_json(reply).reviews
    except ValidationError:
        return {}
    seen = Counter(r.idea for r in reviews)
    return {r.idea: r.verdict.value for r in reviews if seen[r.idea] == 1}


def _lane(h: Hypothesis) -> str:
    return next((t[5:] for t in h.tags if t.startswith("lane:")), "today")


def _today(h: Hypothesis, k: int, spots: Mapping[str, Hotspot]) -> ShownIdea:
    """A returned hypothesis as a data line (today's generator, or a pipeline
    idea its reviewer was not shown): no quote, the first hotspot as anchor."""
    spot = next((spots[i] for i in h.hotspot_ids if i in spots), None)
    return ShownIdea(
        id=f"r{k}", lane=_lane(h), title=h.title, change_class=h.change_class.value,
        anchor=None if spot is None else f"{spot.file_path}:{spot.symbol}",
        change_summary=h.rationale, precondition="", equivalence_summary="",
        depends_on_path="", depends_on_quote="",
    )  # fmt: skip


def tier(p: Pooled) -> int:
    """0: scored (returned non-obvious, or arm A's); 1: an own removal; 2: rest."""
    if p.in_result and p.idea.lane != Lane.obvious.value:
        return 0
    return 1 if p.own == ReviewVerdict.infeasible.value else 2


def ranked(items: Sequence[Pooled]) -> list[Pooled]:
    """By tier, then round robin over the arms, at most ``AUDIT_MAX_IDEAS``."""
    arms = list(dict.fromkeys(p.arm for p in items))
    seen: Counter[tuple[str, int]] = Counter()
    keyed: list[tuple[int, int, int, Pooled]] = []
    for p in items:
        keyed.append((tier(p), seen[(p.arm, tier(p))], arms.index(p.arm), p))
        seen[(p.arm, tier(p))] += 1
    return [p for *_, p in sorted(keyed, key=lambda k: k[:3])][:AUDIT_MAX_IDEAS]


def pool(arms: Sequence[ArmRun], facts: IdeaFacts) -> list[Pooled]:
    """Every E1 arm's ideas: what its reviewer was shown with its own
    verdicts, and each returned idea it was not shown."""
    spots = {h.id: h for h in facts.facts.hotspots}
    items: list[Pooled] = []
    for run in arms:
        if not run.arm.e1 or run.result is None:
            continue
        returned = run.result.hypotheses
        review = next((e for e in run.exchanges if e.label == "reviewer"), None)
        shown = [] if review is None else shown_ideas(review.request)
        own = {} if review is None else own_verdicts(review.reply)
        titles = {h.title for h in returned}
        items += [
            Pooled(run.arm.key, i, own.get(i.id), i.title in titles) for i in shown
        ]
        seen = {i.title for i in shown}
        items += [
            Pooled(run.arm.key, _today(h, k, spots), None, True)
            for k, h in enumerate(returned)
            if h.title not in seen
        ]
    return ranked(items)


def candidate(idea: ShownIdea, idea_id: str) -> IdeaCandidate:
    """A pooled idea as the reviewer request takes it: the shown fields, the
    rest neutral (``review_request`` renders only the shown ones)."""
    path, _, name = (idea.anchor or "").rpartition(":")
    lane = idea.lane if idea.lane in Lane.__members__ else Lane.obvious.value
    return IdeaCandidate(
        id=idea_id, lane=Lane(lane), title=idea.title,
        change_summary=idea.change_summary, justification_summary="",
        change_class=ChangeClass(idea.change_class), expected_gain=0.0,
        provability=0.0, risk=0.0, depends_on_path=idea.depends_on_path,
        depends_on_quote=idea.depends_on_quote, precondition=idea.precondition,
        equivalence_summary=idea.equivalence_summary, mechanism=Mechanism.other,
        morph_cells=(MorphCell.work_eliminate,), tier=Tier.combinational,
        typicality=Typicality.common,
        anchor=Anchor(path=path, qualname=name) if path and name else None,
    )  # fmt: skip


@dataclass(frozen=True)
class Audit:
    verdicts: tuple[str | None, ...]  # per pooled idea; None: no single verdict
    cost_usd: float
    error: str | None
    exchanges: tuple[Exchange, ...]


def run_audit(
    pooled: Sequence[Pooled],
    run: LiveRun,
    facts: IdeaFacts,
    *,
    base: Settings = settings,
    reader: Callable[[Project], RepoReader] = repo_reader,
) -> Audit:
    """One reviewer request on Opus 5.5 ``high`` over the pooled ideas, on its
    own data block and fences, ids ``i01``... in pool order."""
    f = facts.facts
    notes: list[str] = []
    fence = Fence.new()
    context = read_code_context(
        reader(f.project), facts.commit, f.hotspots, fence=fence,
        protected=facts.protected, read_deny=(),
        limits=IdeaReadLimits.from_settings(base), notes=notes,
    )  # fmt: skip
    prefix = render_data_block(
        context, project=f.project, objective=f.objective,
        understanding=f.understanding, hotspots=f.hotspots, fence=fence, notes=notes,
    )  # fmt: skip
    ids = [f"i{k:02d}" for k in range(1, len(pooled) + 1)]
    request, shown = review_request(
        [candidate(p.idea, i) for p, i in zip(pooled, ids, strict=True)],
        prefix=prefix, fence=fence, reviewer_fence=Fence.new(others=(fence.token,)),
        max_ideas=AUDIT_MAX_IDEAS, max_tokens=AUDIT_MAX_TOKENS, effort=AUDIT_EFFORT,
        notes=notes,
    )  # fmt: skip
    cfg = model_settings(base, OPUS)
    tap = Tap(run.transport(cfg), "auditor", ("auditor",))
    first = len(run.records)
    verdicts: dict[str, str] = {}
    error: str | None = None
    try:
        result = call(tap, request, Budget(AUDIT_USD), sleep=time.sleep,
                      max_retries=cfg.LLM_MAX_RETRIES)  # fmt: skip
        read_review(result)  # strict: a stop or refusal is the audit's error
        verdicts = own_verdicts(reply_text(result.message))
    except ARM_ERRORS as exc:
        error = f"{type(exc).__name__}: {exc}"
    return Audit(
        tuple(verdicts.get(i) if i in shown else None for i in ids),
        math.fsum(r.cost_usd for r in run.records[first:]),
        error,
        tuple(tap.exchanges),
    )


@dataclass(frozen=True)
class Score:
    non_obvious: int
    good: int | None  # None: not audited
    audited: int
    auditor_infeasible: int
    own_removed: int  # pooled ideas its own reviewer marked infeasible
    agreed: int  # of those, infeasible for the auditor too


def scores(
    arms: Sequence[ArmRun], pooled: Sequence[Pooled], audit: Audit | None
) -> dict[str, Score]:
    """Per arm: good = returned non-obvious ideas (arm A: distinct titles)
    the auditor answered once and did not mark infeasible; unknown with no
    audit or a failed one."""
    out: dict[str, Score] = {}
    verdicts = () if audit is None else audit.verdicts
    audited_ok = audit is not None and audit.error is None
    for run in arms:
        mine = [
            (p, v)
            for p, v in zip(pooled, verdicts, strict=False)
            if p.arm == run.arm.key
        ]
        audited = [(p, v) for p, v in mine if v is not None]
        bad = ReviewVerdict.infeasible.value
        ok = {p.idea.title for p, v in audited if tier(p) == 0 and v != bad}
        removed = [(p, v) for p, v in audited if p.own == bad]
        hypotheses = () if run.result is None else run.result.hypotheses
        out[run.arm.key] = Score(
            non_obvious=sum(_lane(h) not in ("obvious", "today") for h in hypotheses),
            good=len(ok) if audited_ok and run.arm.e1 else None,
            audited=len(audited),
            auditor_infeasible=sum(v == bad for _, v in audited),
            own_removed=len(removed),
            agreed=sum(v == bad for _, v in removed),
        )
    return out


# ---------------------------------------------------------------------------
# Rows, notes, the summary
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProbeRow:
    repo: str
    arm: str
    models: tuple[str, ...]
    error: str | None
    ideas: int
    non_obvious: int
    good: int | None
    audited: int
    auditor_infeasible: int
    own_removed: int
    agreed: int
    cost_usd: float
    stats: dict[str, object] | None
    stops: dict[str, str | None]
    cache_reads: dict[str, int]
    counted: dict[str, int]
    sent: tuple[str, ...]
    audit_error: str | None

    def record(self) -> dict[str, object]:
        return {"experiment": ROW_EXPERIMENT, **asdict(self)}


def _reply(repo: str, arm: str, e: Exchange) -> dict[str, object]:
    text = redact_keys(e.reply)
    return {
        "experiment": REPLY_EXPERIMENT, "repo": repo, "arm": arm, "role": e.role,
        "label": e.label, "counted": e.counted, "sent": e.sent,
        "stop_reason": e.stop_reason, "usage": list(e.usage), "chars": len(text),
        "shown": len(shown_ideas(e.request)), "seconds": round(e.seconds, 3),
        "chunks": _chunks(text),
    }  # fmt: skip


def _fit(text: str) -> str:
    return text if len(text) <= NOTE_CHARS else text[: NOTE_CHARS - 1] + "…"


@dataclass
class ProbeRecorder:
    """The module's rows; recorded facts are loaded (and checked to cover
    every planned library) before any test spends."""

    plan: ProbePlan
    sink: ResultsSink
    recorded: dict[str, FactsBody] = field(default_factory=dict)
    rows: list[ProbeRow] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.plan.facts is not None and not self.recorded:
            self.recorded = load_facts(self.plan.facts)
        if self.plan.facts is not None:
            for repo in self.plan.repos:
                if repo.name not in self.recorded:
                    raise ValueError(f"{FACTS_ENV}: no recorded facts for {repo.name}")

    def record(
        self,
        repo: str,
        arms: Sequence[ArmRun],
        pooled: Sequence[Pooled],
        audit: Audit | None,
        run: LiveRun,
    ) -> None:
        scored = scores(arms, pooled, audit)
        audit_error = None if audit is None else audit.error
        parts: list[str] = []
        for a in arms:
            s, ex = scored[a.arm.key], a.exchanges
            stats = (
                None if a.result is None or a.result.stats is None else a.result.stats
            )
            row = ProbeRow(
                repo=repo, arm=a.arm.key, models=a.models, error=a.error,
                ideas=0 if a.result is None else len(a.result.hypotheses),
                non_obvious=s.non_obvious, good=s.good, audited=s.audited,
                auditor_infeasible=s.auditor_infeasible, own_removed=s.own_removed,
                agreed=s.agreed, cost_usd=a.cost_usd,
                stats=None if stats is None else stats.model_dump(mode="json"),
                stops={e.label: e.stop_reason for e in ex},
                cache_reads={e.label: e.usage[2] for e in ex},
                counted={e.label: e.counted for e in ex},
                sent=tuple(e.label for e in ex if e.sent), audit_error=audit_error,
            )  # fmt: skip
            self.rows.append(row)
            self.sink.write(row.record())
            for e in ex:
                self.sink.write(_reply(repo, a.arm.key, e))
            good = "-" if s.good is None else s.good
            parts.append(
                f"{a.arm.key} {row.ideas} idea(s), good {good}, {a.cost_usd:.3f}"
            )
        if audit is not None:
            for p, v in zip(pooled, audit.verdicts, strict=True):
                self.sink.write({
                    "experiment": AUDIT_EXPERIMENT, "repo": repo, "arm": p.arm,
                    "title": p.idea.title, "lane": p.idea.lane, "tier": tier(p),
                    "in_result": p.in_result, "own": p.own, "auditor": v,
                })  # fmt: skip
            for e in audit.exchanges:
                self.sink.write(_reply(repo, "auditor", e))
            parts.append(f"audit {audit.cost_usd:.3f}")
        failed = "" if audit_error is None else f"; audit failed: {audit_error}"
        run.note(_fit(f"IDEAS {repo}: " + "; ".join(parts) + " USD" + failed))

    def finish(self, echo: Callable[[str], None]) -> None:
        if not self.rows:
            return
        lines = [
            "## Ideas probe (E0b, E1, E1b: idea-only)", "",
            "| repo | arm | ideas | non-obvious | good | audited | auditor infeasible "
            "| own removed (agreed) | USD | error |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]  # fmt: skip
        for r in self.rows:
            lines.append(cells([
                r.repo, r.arm, r.ideas, r.non_obvious, "-" if r.good is None else r.good,
                r.audited, r.auditor_infeasible, f"{r.own_removed} ({r.agreed})",
                f"{r.cost_usd:.4f}", _errors(r),
            ]))  # fmt: skip
        write_markdown("Ideas probe", "\n".join(lines), self.sink.environ, echo)


def _errors(row: ProbeRow) -> str:
    audit = None if row.audit_error is None else f"audit: {row.audit_error}"
    return "; ".join(e for e in (row.error, audit) if e) or "-"


# ---------------------------------------------------------------------------
# One library: what each live case runs
# ---------------------------------------------------------------------------


def check_spend(run: LiveRun, arms: Sequence[ArmRun], audit: Audit | None) -> None:
    """Every arm billed its own role models only; count mode sent at most
    ``COUNT_SENT``; the wire and the recorder agree and hold the cap."""
    for a in arms:
        assert set(a.models) <= set(a.billable), (a.arm.key, a.models)
        if a.arm is ARM_COUNT:
            assert sum(e.sent for e in a.exchanges) <= COUNT_SENT
    if audit is not None:
        assert all(e.request.max_tokens == AUDIT_MAX_TOKENS for e in audit.exchanges)
    assert len(run.capture.messages()) == len(run.records)
    assert run.spent_usd <= run.cap_usd, (run.spent_usd, run.cap_usd)


def run_library(
    repo: OssRepo,
    *,
    live: StartLive,
    root: Path,
    isolation: Isolation,
    recorder: ProbeRecorder,
    policy: GitPolicy = PRODUCTION,
    base: Settings = settings,
    reader: Callable[[Project], RepoReader] = repo_reader,
) -> None:
    """Phase 1 (or the recorded facts), every arm, the auditor; recorded,
    then guarded. A breach is noted on the run, then raised."""
    plan = recorder.plan
    run = live(plan.library_cap())
    try:
        body = recorder.recorded.get(repo.name)
        if body is None:
            with engine_settings(ab_settings(settings)):
                facts, untouched = phase_facts(
                    repo, run, root / "phase", isolation, policy
                )
            recorder.sink.write(facts.record())
        else:
            facts = clone_facts(repo, body, root / "user", policy)
            untouched = _nothing
        arms = [run_arm(a, run, facts, base=base, reader=reader) for a in plan.arms]
        pooled = pool(arms, facts) if plan.audit else []
        audit = (
            run_audit(pooled, run, facts, base=base, reader=reader) if pooled else None
        )
        recorder.record(repo.name, arms, pooled, audit, run)
        untouched()
        check_spend(run, arms, audit)
    except BaseException as exc:
        run.note(_fit(f"IDEAS {repo.name}: breach: {type(exc).__name__}: {exc}"))
        raise


def _nothing() -> None:
    return None
