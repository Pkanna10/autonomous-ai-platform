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

X1 (Vd, spec-idea-lab 6.2; ``$LIVE_IDEAS_ARMS`` ``X1``, or its keys): arm A
and five configurations, one lever each, on E1's facts (``$LIVE_IDEAS_FACTS``)
and Va's recorded views (``$LIVE_IDEAS_VIEWS``, checked against the source
this run builds before any spend): X1-0 arm C again; X1-1 each lens on a
model of a cyclic 6x6 Latin square (``square_models``, rows 1-6 then 1-2 over
``E1_REPOS``) and the think line on every lane (O38: X1-0's lanes are all
Sonnet 5.5, so all have it; the leap is X1-0's); X1-2 sequential lanes and the mechanism dedupe (G4); X1-3 a
different view per lens (``X1_VIEWS``) with its framework (G2 + G5, two
factors, labelled so), the views given through the pipeline's
``view_builder`` seam and never built live; X1-4 S1 and the four
rule-relaxing lanes alone (G3, O38: no lens, leap or reviewer; proposals
only: never pooled or scored). An X1 dispatch's worst case
stays under ``X1_FUSE_USD``. O42: X1-1's S1 and lenses write at most
``X1_1_LANE_MAX_TOKENS`` (32,000; every other arm 12,000) under a client
timeout of ``X1_1_TIMEOUT_S``; ``X1-1`` alone (``X1_RERUN_KEY``) re-runs it
beside arm A and the auditor, on X1 run 1's four libraries unless named.

Minutes, re-pinned from E1's recorded seconds (``E1_SECONDS``, the slowest
sent request per role and model; an unmeasured lane model reads as the
nearest measured request): a request takes ``TIME_MARGIN`` times that, a
parallel stage the slowest of each round of ``IDEAS_LANE_WORKERS`` (one lane
a round with ``IDEAS_SEQUENTIAL_LANES``, G4), phase 1 ``PHASE_ONE_MINUTES``
(E0b: a count-mode library about 47 s); a plan past ci.yml's ``JOB_MINUTES``
is refused: E1 49 minutes a library (arm D's Fable leap at its 951 s
timeout), X1 74 to 76 (O42: a lane past E1's
12,000-token cap takes ``cap_seconds``, the cap at its model's slowest X1
run-1 rate), so three a dispatch, O42's re-run 47 to 50; any X1 plan at most
four (``X1_LIBRARIES_A_DISPATCH``). Count mode also counts the reviewer request with its ideas
repeated under fresh ids up to ``IDEAS_REVIEW_MAX_IDEAS`` (D55's reviewer
bound is for 16 ideas; S1 and one lens give fewer).

Caps: an arm's cap is the sum of its requests' worst cases on D55's bounds,
re-derived from E0b's counted maxima (D61; the E1 row: B 1.99, C 2.475, D
7.205 since the Fable leap (E1's 4.53), E 1.045, the auditor 0.69; A on the
oss-ab suite's measured blind
bound, 0.27; X1-1 7.216 (O42), X1-2 2.539 and X1-3 2.675 on wider bounds for the
mechanisms block and the views, X1-4 1.075), count mode's real spend is
``COUNT_SENT`` lane requests (0.43, the tap refuses past it); a library's
run is phase 1, its arms and the auditor, rounded up (E1 14.10, count 0.85,
C-low/C-high 4.95, X1 16.95 and O42's re-run 8.20 on recorded facts); a plan past
the 150 USD ceiling is refused in the module fixture. Fable (30-day
retention) gets ``ALLOW_RETENTION_MODELS`` only in arm D's copy and only for
a library of the pinned OSS manifests (O15); the flag is cleared in every
other copy.

Recorded, never asserted (``$LIVE_RESULTS_PATH``): per library the facts
(``ideas-facts``, chunked JSON, keys redacted), per (library, arm) a row
(``ideas-probe``: ideas, non-obvious, good as coded, good corrected for the
pooled auditor's cross-arm duplicates and good strict (STATUS 2026-10-31),
auditor and own-reviewer counts, the auditor's error (then no arm's good
count is known), cost, ``IdeaStats``, ``stop_reason``, cache reads and
counted tokens per request; X1: the lever, the lens models and views),
every idea every lane reply proposed and every idea today's generator
returned (``ideas-idea``: lane, the exchange label its ``ideas-reply`` row
carries, model, title, change summary, mechanism, cells, target lines in the
file at the commit, returned, the proposal flag), every request's
reply (``ideas-reply``, redacted, chunked, with its shown ideas and seconds)
and every pooled idea's review (``ideas-audit``: its id, the auditor's
verdict, reason and ``duplicate_of``); a cost-table note per library and a
summary table.
Quarantined proposals (G3, rule-relaxing lanes) are never pooled, scored or
counted as ideas (X1-4): each is recorded apart for the owner to read
(``ideas-proposal``: its title, lane, rules and rationale) and counted in
the row's ``proposals``.
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
from typing import TYPE_CHECKING, Final, Literal, cast

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
    IdeaView,
    Role,
    Settings,
    lane_chain,
    lane_settings,
    leap_shape,
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
    Workload,
)
from autonomous_ai_agents.common.paths import normalize_path
from autonomous_ai_agents.common.repo_read import RepoReader
from autonomous_ai_agents.execution.git import GitError
from autonomous_ai_agents.optimization.hypothesis_source import (
    ClaudeHypothesisGenerator,
)
from autonomous_ai_agents.optimization.idea_context import (
    IdeaReadLimits,
    ViewSource,
    build_view,
    read_code_context,
    render_data_block,
)
from autonomous_ai_agents.optimization.idea_dedupe import (
    _Reply,
    _ReplyIdea,
    quote_lines,
)
from autonomous_ai_agents.optimization.idea_pipeline import (
    IdeaPipelineGenerator,
    ViewBuilder,
    framework_labels,
)
from autonomous_ai_agents.optimization.idea_review import read_review, review_request
from autonomous_ai_agents.optimization.idea_types import (
    LENS_LANES,
    RELAXING_LANES,
    Anchor,
    IdeaCandidate,
    Lane,
    Mechanism,
    MorphCell,
    ReviewVerdict,
    Tier,
    Typicality,
    is_proposal,
    relaxed_rules,
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

if TYPE_CHECKING:  # ideas_views imports this module
    from .ideas_views import RecordedViews

ARMS_ENV: Final = "LIVE_IDEAS_ARMS"
REPOS_ENV: Final = "LIVE_IDEAS_REPOS"
FACTS_ENV: Final = "LIVE_IDEAS_FACTS"
VIEWS_ENV: Final = "LIVE_IDEAS_VIEWS"
SERVICE_DIR: Final = TESTS_DIR.parent
FACTS_FIXTURE: Final = "tests/fixtures/ideas_probe/facts.jsonl"  # E1b's (from E1)
VIEWS_FIXTURE: Final = "tests/fixtures/ideas_probe/views.jsonl"  # Va's rows, for X1
ROW_EXPERIMENT: Final = "ideas-probe"
FACTS_EXPERIMENT: Final = "ideas-facts"
REPLY_EXPERIMENT: Final = "ideas-reply"
AUDIT_EXPERIMENT: Final = "ideas-audit"
PROPOSAL_EXPERIMENT: Final = "ideas-proposal"
IDEA_EXPERIMENT: Final = "ideas-idea"
HAIKU: Final = "claude-haiku-5-5"
SONNET_5: Final = "claude-sonnet-5"
FABLE_5: Final = "claude-fable-5"
# D55's lane and reviewer bounds are discovery_ab's (one source, re-derived
# from E0b, D61); the auditor's over 48 ideas: about 33.1k base + 48 x ~420
# a reviewed idea = 53.3k, + margin
LANE_PROMPT_BOUND: Final = IDEAS_LANE_PROMPT_BOUND
REVIEW_PROMPT_BOUND: Final = IDEAS_REVIEW_PROMPT_BOUND
AUDIT_PROMPT_BOUND: Final = 58_000
# X1, unmeasured until X1 counts them: G4's mechanisms block, at most 48 lines
# of about 60 tokens and its lead-in, on each S2 lane in sequence; a lens on
# its own view (G2: capped at the code cap like the shared block, plus its
# facts); the reviewer with the views' code (up to twice the 64 KiB code cap,
# about 22k tokens more)
TAKEN_PROMPT_EXTRA: Final = 3_200
VIEW_PROMPT_BOUND: Final = LANE_PROMPT_BOUND + 6_000
VIEW_REVIEW_PROMPT_BOUND: Final = REVIEW_PROMPT_BOUND + 22_000
X1_FUSE_USD: Final = 80.0  # spec-idea-lab 6.4: each X1 dispatch's worst case
AUDIT_MAX_TOKENS: Final = 20_000
AUDIT_MAX_IDEAS: Final = 48
AUDIT_EFFORT: Final[Effort] = "high"
RETENTION_MAX_TOKENS: Final = 20_000  # arm D's Fable leap and reviewer (D58)
COUNT_SENT: Final = 2  # count mode sends S1 and the first lens lane
JOB_MINUTES: Final = 240  # ci.yml's ideas-probe timeout: four libraries
X1_LIBRARIES_A_DISPATCH: Final = 4  # ci.yml; X1-4 alone fits five in minutes
TIME_MARGIN: Final = 2  # over E1's slowest request (the timing-guard rule)
E1_SECONDS: Final[Mapping[tuple[str, str], float]] = {
    ("generator", SONNET): 11.772, ("lane", SONNET): 23.866,
    ("lane", HAIKU): 34.72, ("leap", SONNET): 63.328, ("leap", OPUS): 97.648,
    ("leap", FABLE): 234.283, ("reviewer", SONNET): 69.121,
    ("reviewer", OPUS): 65.35, ("reviewer", FABLE): 138.737,
    ("auditor", OPUS): 108.613,
}  # fmt: skip
"""E1's slowest sent request per (role, model), both dispatches' replies."""
_AS_MEASURED: Final[Mapping[tuple[str, str], tuple[str, str]]] = {
    ("lane", SONNET_5): ("lane", SONNET), ("lane", OPUS): ("leap", OPUS),
    ("lane", FABLE): ("leap", FABLE), ("lane", FABLE_5): ("leap", FABLE),
}  # fmt: skip
"""X1-1's unmeasured lane models, read as the nearest measured (slower) one."""
E1_LANE_MAX_TOKENS: Final = 12_000  # the lane cap E1's and X1 run 1's seconds hold at
X1_1_LANE_MAX_TOKENS: Final = 32_000  # O42: X1-1's lane output cap, X1-1 alone
X1_RUN1_TOKENS_PER_S: Final[Mapping[str, float]] = {
    SONNET: 99.595, SONNET_5: 84.399, HAIKU: 181.057, OPUS: 71.519,
    FABLE_5: 69.293, FABLE: 67.327,
}  # fmt: skip
"""X1 run 1 (41679255224), O42's re-pin: each model's slowest output rate,
tokens a second, over every sent reply of at least 1,000 output tokens on
that model, any role (Opus 5.5's is X1-3's leap at effort high, 3,567 in
49.875 s; its slowest X1-1 lens lane wrote 88.3 a second)."""
X1_1_TIMEOUT_S: Final = math.ceil(
    TIME_MARGIN * X1_1_LANE_MAX_TOKENS / min(X1_RUN1_TOKENS_PER_S.values())
)  # 951: a lens may write its whole cap; the default 300 s ends Fable near 20k
PHASE_ONE_MINUTES: Final = 2  # E0b: a whole count-mode library about 47 s
CLONE_MINUTES: Final = 1  # recorded facts: a fresh clone only
NOTE_CHARS: Final = _CELL_MAX
E1_REPOS: Final = (
    "more_itertools", "pyparsing", "tomli", "sortedcontainers",
    "mistune", "sqlparse", "markdown", "idna",
)  # fmt: skip
E1B_REPOS: Final = ("pyparsing", "tomli", "mistune", "markdown")
X1_RERUN_REPOS: Final = E1_REPOS[:4]  # X1 run 1's (41679255224), for O42's re-run
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
    square: bool = False  # X1-1: each lens on its row's model (``square_models``)
    lever: str = ""  # X1: what the configuration moves, as the report labels it


ARM_A: Final = IdeaArm("A", pipeline=False, lever="today's generator, one request")
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
"""Arm D, E1's Fable 5.1 leap and reviewer. Since the Fable leap
(``leap_shape``) its leap request is not E1's: 32,000 output tokens (its
``IDEAS_LEAP_MAX_TOKENS`` is ignored), Opus 4.8 as its server-side fallback
and a 951 s timeout; its cap and minutes price that request."""
ARM_E: Final = IdeaArm("E", True, (("IDEAS_LANE_MODEL", HAIKU),))
ARM_C_LOW: Final = IdeaArm("C-low", True, (("IDEAS_LANE_EFFORT", "low"),), e1=False)
ARM_C_HIGH: Final = IdeaArm("C-high", True, (("IDEAS_LANE_EFFORT", "high"),), e1=False)
ARM_COUNT: Final = IdeaArm("count", True, (("IDEAS_LANE_WORKERS", 1),), e1=False)
IDEA_ARMS: Final = (ARM_COUNT, ARM_A, ARM_B, ARM_C, ARM_D, ARM_E, ARM_C_LOW, ARM_C_HIGH)
E1_ARMS: Final = (ARM_A, ARM_B, ARM_C, ARM_D, ARM_E)

SQUARE_MODELS: Final = (SONNET_5, HAIKU, OPUS, FABLE_5, FABLE, SONNET)
"""X1-1's lens models (spec-idea-lab 6.2), one column of the square each."""
X1_VIEWS: Final[Mapping[Lane, IdeaView]] = {
    Lane.eliminate: "callers",  # work a caller repeats, or memoised across calls
    Lane.assume_less: "input_shape",  # assume only the inputs the workload passes
    Lane.name_the_problem: "data_structures",  # the representation's misfit
    Lane.recombine: "whole_module",  # work two functions of the module repeat
    Lane.resolve_tradeoff: "next_hotspots",  # trade across the 2nd and 3rd
    Lane.far: "history",  # the project's own past speed-ups as prior art
}
"""X1-3's fixed lens-to-view map (Vd's choice): each lens a different view."""


def square_row(repo: str) -> int:
    """X1-1's row for ``repo``: rows 1-6 over the first six of ``E1_REPOS``,
    then rows 1-2 again (0-based here)."""
    if repo not in E1_REPOS:
        raise ValueError(f"X1-1's Latin square: {repo!r} is not one of the 8 "
                         "development libraries")  # fmt: skip
    return E1_REPOS.index(repo) % len(SQUARE_MODELS)


def square_models(row: int) -> dict[Lane, str]:
    """Row ``row`` of the cyclic 6x6 Latin square: lens j on model row + j."""
    n = len(SQUARE_MODELS)
    return {lane: SQUARE_MODELS[(row + j) % n] for j, lane in enumerate(LENS_LANES)}


ARM_X1_0: Final = IdeaArm("X1-0", True, lever="baseline: arm C's settings again")
ARM_X1_1: Final = IdeaArm(
    "X1-1", True,
    (("IDEAS_THINK_LINE_ALL", True),
     ("IDEAS_LANE_MAX_TOKENS", X1_1_LANE_MAX_TOKENS),
     ("LLM_TIMEOUT_S", float(X1_1_TIMEOUT_S))),
    square=True,
    lever="who thinks (G1): S1 on Sonnet 5.5, each lens on its square's model, "
    "the think line on every lane as X1-0's all-Sonnet 5.5 lanes have it (O38); "
    "lane output cap 32,000 (O42)",
)  # fmt: skip
ARM_X1_2: Final = IdeaArm(
    "X1-2", True,
    (("IDEAS_SEQUENTIAL_LANES", True), ("IDEAS_MECHANISM_DEDUPE", True)),
    lever="what is taken (G4): sequential lanes, mechanism dedupe",
)  # fmt: skip
ARM_X1_3: Final = IdeaArm(
    "X1-3", True,
    (("IDEAS_LANE_VIEWS", dict(X1_VIEWS)), ("IDEAS_LANE_FRAMEWORKS", True)),
    lever="what they see and how they think (G2 + G5): two factors, a view per "
    "lens and its framework; split in X2 if it wins",
)  # fmt: skip
ARM_X1_4: Final = IdeaArm(
    "X1-4", True,
    (("IDEAS_RELAX_LANES", tuple(RELAXING_LANES)), ("IDEAS_LENSES", ()),
     ("IDEAS_LEAP_N", 0), ("IDEAS_REVIEW", False)),
    e1=False,
    lever="what they may change (G3): S1 and four rule-relaxing lanes alone "
    "(O38: X1-0 is the baseline), proposals only, reported, never scored",
)  # fmt: skip
X1_CONFIGS: Final = (ARM_X1_0, ARM_X1_1, ARM_X1_2, ARM_X1_3, ARM_X1_4)
X1_ARMS: Final = (ARM_A, *X1_CONFIGS)  # arm A: today's generator, same day
X1_KEY: Final = "X1"  # ``$LIVE_IDEAS_ARMS`` for all of ``X1_ARMS``
X1_RERUN_KEY: Final = "X1-1"  # O42's re-run: X1-1 beside arm A and the auditor
X1_RERUN_ARMS: Final = (ARM_A, ARM_X1_1)  # A: share-new in the re-run's own pool
_X1_KEYS: Final = frozenset(arm.key for arm in X1_CONFIGS)
_KNOWN_ARMS: Final = (*IDEA_ARMS, *X1_CONFIGS)


def arm_update(arm: IdeaArm, repo: str | None = None) -> dict[str, object]:
    """The arm's overrides; X1-1's lens models are ``repo``'s row (row 1 for
    ``None``: every row holds the same models, so the same cap)."""
    update = dict(arm.update)
    if arm.square:
        row = 0 if repo is None else square_row(repo)
        update["IDEAS_LANE_MODELS"] = square_models(row)
    return update


def arm_config(arm: IdeaArm, project: Project, base: Settings = settings) -> Settings:
    """The arm's validated settings copy. A retention model (D63) is admitted
    only for a library of the pinned OSS manifests (O15), by setting the flag
    in this copy; every other copy has it off, whatever ``base`` says."""
    overrides = arm_update(arm, project.name)
    raw = base.model_copy(update=overrides)
    needs = sorted(
        ({m for role in _ROLES for m in role_chain(raw, role)}
         | set(raw.IDEAS_LANE_MODELS.values()))
        & RETENTION_REQUIRED_MODELS
    )  # fmt: skip
    if needs and project.name not in OSS_NAMES:
        raise ValueError(
            f"arm {arm.key}: {', '.join(needs)} keeps data 30 days and may see code "
            f"only on a pinned OSS library (O15), not {project.name!r}"
        )
    update = {
        **overrides,
        "IDEA_PIPELINE": arm.pipeline,
        "ALLOW_RETENTION_MODELS": bool(needs),
    }
    return type(base).model_validate(base.model_copy(update=update).model_dump())


def request_usd(bound: int, max_tokens: int, model: str) -> float:
    """D55's worst case of one request whose count (margin and allowance
    included) is at most ``bound``."""
    return preflight_estimate(bound, max_tokens, (model,), settings.MODEL_PRICING)


def s2_lanes(cfg: Settings) -> tuple[Lane, ...]:
    """S2's requests in the order the pipeline submits them."""
    leap = (Lane.leap,) if cfg.IDEAS_LEAP_N else ()
    return (*cfg.IDEAS_LENSES, *leap, *cfg.IDEAS_RELAX_LANES)


def lane_bound(cfg: Settings, lane: Lane) -> int:
    """D55's prompt bound of one lane request: a lens on its own view (G2)
    the view bound, an S2 lane in sequence (G4) the mechanisms block more."""
    bound = VIEW_PROMPT_BOUND if lane in cfg.IDEAS_LANE_VIEWS else LANE_PROMPT_BOUND
    if cfg.IDEAS_SEQUENTIAL_LANES and lane is not Lane.obvious:
        bound += TAKEN_PROMPT_EXTRA
    return bound


def lane_usd(cfg: Settings, lane: Lane) -> float:
    """D55's worst case of one S1 or S2 request: its bound, its whole chain
    (the engine's preflight: one attempt per model, dearest rates over the
    chain) and its output cap, the leap's ``leap_shape``'s (a Fable leap's
    32,000 on Fable and Opus 4.8)."""
    out = leap_shape(cfg).max_tokens if lane is Lane.leap else cfg.IDEAS_LANE_MAX_TOKENS
    chain = lane_chain(cfg, lane)
    return preflight_estimate(lane_bound(cfg, lane), out, chain, settings.MODEL_PRICING)


def pipeline_usd(cfg: Settings) -> float:
    """One pipeline call at its worst: S1, each S2 lane on its own model (G1)
    and bound (``lane_usd``), the reviewer (with the views' code, G2)."""
    lanes = [lane_usd(cfg, lane) for lane in (Lane.obvious, *s2_lanes(cfg))]
    bound = VIEW_REVIEW_PROMPT_BOUND if cfg.IDEAS_LANE_VIEWS else REVIEW_PROMPT_BOUND
    review = request_usd(bound, cfg.IDEAS_REVIEWER_MAX_TOKENS, cfg.IDEAS_REVIEWER_MODEL)
    return math.fsum((*lanes, review if cfg.IDEAS_REVIEW else 0.0))


def count_usd(cfg: Settings) -> float:
    return COUNT_SENT * request_usd(
        LANE_PROMPT_BOUND, cfg.IDEAS_LANE_MAX_TOKENS, cfg.IDEAS_LANE_MODEL
    )


def arm_usd(arm: IdeaArm, base: Settings = settings, repo: str | None = None) -> float:
    """What the arm may spend: today's generator on the OSS blind bound, a
    pipeline call, or count mode's sent requests."""
    raw = base.model_copy(update=arm_update(arm, repo))
    if not arm.pipeline:
        return worst_usd(
            OSS_BLIND_PROMPT_BOUND, raw.GENERATOR_MAX_TOKENS, raw.GENERATOR_MODEL
        )
    return count_usd(raw) if arm is ARM_COUNT else pipeline_usd(raw)


AUDIT_USD: Final = request_usd(AUDIT_PROMPT_BOUND, AUDIT_MAX_TOKENS, OPUS)


def request_seconds(role: str, model: str) -> float:
    """``TIME_MARGIN`` times E1's slowest such request; none measured: refused."""
    key = _AS_MEASURED.get((role, model), (role, model))
    if key not in E1_SECONDS:
        raise ValueError(f"no E1 seconds for a {role} request on {model}")
    return TIME_MARGIN * E1_SECONDS[key]


def arm_seconds(
    arm: IdeaArm, base: Settings = settings, repo: str | None = None
) -> float:
    """The arm's wall time at worst: today's generator, count mode's sends,
    or S1, S2's rounds of ``IDEAS_LANE_WORKERS`` in submission order (one
    lane a round with ``IDEAS_SEQUENTIAL_LANES``, G4), each its slowest
    request, and the reviewer."""
    cfg = base.model_copy(update=arm_update(arm, repo))
    if not arm.pipeline:
        return request_seconds("generator", cfg.GENERATOR_MODEL)
    if arm is ARM_COUNT:
        return COUNT_SENT * request_seconds("lane", cfg.IDEAS_LANE_MODEL)

    def one(lane: Lane) -> float:
        model = lane_chain(cfg, lane)[0]
        if lane is Lane.leap:  # a Fable leap may run to its timeout (951 s)
            timeout = leap_shape(cfg).timeout_s
            return request_seconds("leap", model) if timeout is None else timeout
        cap = cap_seconds(cfg.IDEAS_LANE_MAX_TOKENS, model)
        return max(request_seconds("lane", model), cap)

    s2 = [one(lane) for lane in s2_lanes(cfg)]
    k = 1 if cfg.IDEAS_SEQUENTIAL_LANES else cfg.IDEAS_LANE_WORKERS
    rounds = [max(s2[i : i + k]) for i in range(0, len(s2), k)]
    review = (
        request_seconds("reviewer", cfg.IDEAS_REVIEWER_MODEL)
        if cfg.IDEAS_REVIEW
        else 0.0
    )
    return math.fsum((one(Lane.obvious), *rounds, review))


AUDIT_SECONDS: Final = request_seconds("auditor", OPUS)


def cap_seconds(max_tokens: int, model: str) -> float:
    """O42: a lane past E1's cap may write all of it, ``TIME_MARGIN`` times
    at the model's slowest run-1 rate; at or under it, none (E1's hold)."""
    if max_tokens <= E1_LANE_MAX_TOKENS:
        return 0.0
    rate = X1_RUN1_TOKENS_PER_S.get(model)
    if rate is None:
        raise ValueError(f"no run-1 rate for a lane on {model}")
    return TIME_MARGIN * max_tokens / rate


@dataclass(frozen=True)
class ProbePlan:
    arms: tuple[IdeaArm, ...]
    repos: tuple[OssRepo, ...]
    facts: Path | None = None  # recorded facts: no phase 1
    views: Path | None = None  # Va's recorded views (X1)

    @property
    def audit(self) -> bool:
        return any(arm.e1 for arm in self.arms)

    def library_cap(self, repo: str | None = None) -> float:
        phase = 0.0 if self.facts is not None else OSS_PHASE_ONE_WORST_USD
        audit = AUDIT_USD if self.audit else 0.0
        arms = (arm_usd(arm, repo=repo) for arm in self.arms)
        return ceil_usd(math.fsum((phase, audit, *arms)))

    def library_minutes(self, repo: str | None = None) -> int:
        phase = CLONE_MINUTES if self.facts is not None else PHASE_ONE_MINUTES
        arms = (arm_seconds(arm, repo=repo) for arm in self.arms)
        audit = AUDIT_SECONDS if self.audit else 0.0
        return phase + math.ceil(math.fsum((*arms, audit)) / 60)

    def minutes(self) -> int:
        return sum(self.library_minutes(repo.name) for repo in self.repos)


def probe_need(plan: ProbePlan) -> float:
    return math.fsum(plan.library_cap(repo.name) for repo in plan.repos)


X1_LIBRARY_CENTS: Final = round(
    100 * ProbePlan(X1_ARMS, (), Path(FACTS_FIXTURE)).library_cap()
)
"""ci.yml's need of one X1 library (every row of the square alike)."""
X1_RERUN_LIBRARY_CENTS: Final = round(
    100 * ProbePlan(X1_RERUN_ARMS, (), Path(FACTS_FIXTURE)).library_cap()
)
"""ci.yml's need of one library of O42's re-run."""


def check_fuse(plan: ProbePlan) -> None:
    """An X1 dispatch's worst case stays under ``X1_FUSE_USD`` (spec 6.4)."""
    need = probe_need(plan)
    if any(arm.key in _X1_KEYS for arm in plan.arms) and need > X1_FUSE_USD:
        raise ValueError(f"X1 on {len(plan.repos)} libraries needs {need:.2f} USD, "
                         f"past the {X1_FUSE_USD:g} USD fuse of an X1 dispatch: "
                         f"name fewer in {REPOS_ENV}")  # fmt: skip


def probe_arms(environ: Mapping[str, str]) -> tuple[IdeaArm, ...]:
    if environ.get(ARMS_ENV) == X1_KEY:
        return X1_ARMS
    if environ.get(ARMS_ENV) == X1_RERUN_KEY:
        return X1_RERUN_ARMS
    keys = _keys(environ, ARMS_ENV, [arm.key for arm in _KNOWN_ARMS])
    if keys is None:
        return E1_ARMS
    if ARM_COUNT.key in keys and len(keys) > 1:
        raise ValueError(f"{ARMS_ENV}: count runs alone, got {environ[ARMS_ENV]!r}")
    return tuple(arm for arm in _KNOWN_ARMS if arm.key in keys)


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
        if tuple(arms) == X1_RERUN_ARMS:  # run 1's four (O42)
            names = X1_RERUN_REPOS
    return tuple(repo for repo in OSS_SELECTABLE if repo.name in names)


def facts_path(
    environ: Mapping[str, str], name: str = FACTS_ENV, what: str = "facts"
) -> Path | None:
    raw = environ.get(name, "")
    if not raw:
        return None
    path = Path(raw) if Path(raw).is_absolute() else SERVICE_DIR / raw
    if not path.is_file():
        raise ValueError(f"{name}: no recorded {what} at {raw!r}")
    return path


def probe_plan(environ: Mapping[str, str]) -> ProbePlan:
    """Every knob, strictly, and a plan past the ceiling or the job's
    minutes refused (in the module fixture, before any spend)."""
    arms = probe_arms(environ)
    plan = ProbePlan(arms, probe_repos(environ, arms), facts_path(environ),
                     facts_path(environ, VIEWS_ENV, "views"))  # fmt: skip
    if any(arm.key in _X1_KEYS for arm in arms):
        if plan.facts is None:
            raise ValueError(f"X1 reads E1's facts: set {FACTS_ENV} ({FACTS_FIXTURE})")
        if plan.views is None:
            raise ValueError(f"X1 reads Va's views: set {VIEWS_ENV} ({VIEWS_FIXTURE})")
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
    if (
        any(a.key in _X1_KEYS for a in arms)
        and len(plan.repos) > X1_LIBRARIES_A_DISPATCH
    ):
        raise ValueError(f"X1 runs at most {X1_LIBRARIES_A_DISPATCH} libraries a "
                         f"dispatch (ci.yml), not {len(plan.repos)}: {fewer}")  # fmt: skip
    check_fuse(plan)
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
    model: str = ""  # the tap's model (its chain's first)


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
            self.exchanges.append(
                Exchange(self.role, label, counted, request, model=self.chain[0])
            )
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
    lane_models: dict[str, str] = field(default_factory=dict)  # G1, X1-1
    views: dict[str, str] = field(default_factory=dict)  # G2, X1-3


def _taps(
    arm: IdeaArm, cfg: Settings, run: LiveRun
) -> tuple[dict[Role, Tap], dict[Lane, Tap]]:
    """The role taps, and a tap per lane that names its own model (G1)."""
    if not arm.pipeline:
        inner = run.transport(role_settings(cfg, "generator"))
        return {"generator": Tap(inner, "generator", ("generator",))}, {}
    own = cfg.IDEAS_LANE_MODELS
    labels = {
        "lane": tuple(
            lane.value
            for lane in (Lane.obvious, *cfg.IDEAS_LENSES, *cfg.IDEAS_RELAX_LANES)
            if lane not in own  # G3's lanes are sent last
        ),
        "leap": ("leap",),
        "reviewer": ("reviewer", f"reviewer-{cfg.IDEAS_REVIEW_MAX_IDEAS}"),
    }
    counting = arm is ARM_COUNT
    roles: dict[Role, Tap] = {
        role: Tap(
            run.transport(role_settings(cfg, role)),
            role,
            labels[role],
            sends=(COUNT_SENT if role == "lane" else 0) if counting else None,
            send_cap_usd=count_usd(cfg) if counting else math.inf,
        )  # fmt: skip
        for role in PIPELINE_ROLES
    }
    lanes = {
        lane: Tap(run.transport(lane_settings(cfg, lane)), "lane", (lane.value,))
        for lane in own
    }
    return roles, lanes


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
    views: ViewBuilder | None = None,
    workloads: Sequence[Workload] = (),
) -> ArmRun:
    """One generation from ``facts`` on the arm's own transports, under its
    cap (``arm_usd``; a pipeline arm's reservations need the whole call's,
    count mode's real spend is bounded by its taps). An arm with lane views
    (G2) takes them from ``views`` (Va's recorded rows, through the
    pipeline's ``view_builder`` seam) with the run's ``workloads``, which
    decide the input-shape view; none given is refused before any spend."""
    f = facts.facts
    cfg = arm_config(arm, f.project, base)
    if cfg.IDEAS_LANE_VIEWS and views is None:
        raise ValueError(f"arm {arm.key}: views are never built live; give the "
                         "recorded views (Va)")  # fmt: skip
    taps, lane_taps = _taps(arm, cfg, run)
    generator: HypothesisGenerator = (
        IdeaPipelineGenerator(
            dict(taps),
            lane_transports=dict(lane_taps),
            reader=reader,
            config=cfg,
            view_builder=views or build_view,
        )  # fmt: skip
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
            workloads=tuple(workloads) if cfg.IDEAS_LANE_VIEWS else (),
        )  # fmt: skip
        if arm is ARM_COUNT:  # D55's reviewer bound is for 16 ideas
            _count_full_review(taps["reviewer"], cfg.IDEAS_REVIEW_MAX_IDEAS)
    except ARM_ERRORS as exc:
        error = f"{type(exc).__name__}: {exc}"
    records = run.records[first:]
    every = (*taps.values(), *lane_taps.values())
    return ArmRun(
        arm=arm,
        result=result,
        error=error,
        cost_usd=math.fsum(r.cost_usd for r in records),
        models=tuple(dict.fromkeys(r.model for r in records)),
        billable=tuple(dict.fromkeys(m for t in every for m in t.chain)),
        exchanges=tuple(e for tap in every for e in tap.exchanges),
        lane_models={k.value: v for k, v in cfg.IDEAS_LANE_MODELS.items()},
        views={k.value: v for k, v in cfg.IDEAS_LANE_VIEWS.items()},
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


@dataclass(frozen=True)
class AuditReview:
    """One idea's single review: its verdict, reason and the earlier id it
    repeats (``duplicate_of``, as the reply names it, unchecked)."""

    verdict: str
    reason: str
    duplicate_of: str | None


def audit_reviews(reply: str) -> dict[str, AuditReview]:
    """Each id reviewed once and its review; an unreadable reply gives none."""
    try:
        reviews = _Reviews.model_validate_json(reply).reviews
    except ValidationError:
        return {}
    seen = Counter(r.idea for r in reviews)
    return {
        r.idea: AuditReview(r.verdict.value, r.reason, r.duplicate_of)
        for r in reviews
        if seen[r.idea] == 1
    }


def own_verdicts(reply: str) -> dict[str, str]:
    """Each id reviewed once and its verdict; an unreadable reply gives none."""
    return {i: r.verdict for i, r in audit_reviews(reply).items()}


def scored_hypotheses(result: GenerateResult | None) -> tuple[Hypothesis, ...]:
    """The returned ideas the probe scores: every one but the quarantined
    proposals (G3: reported, never scored or trialled, X1-4)."""
    hypotheses = () if result is None else result.hypotheses
    return tuple(h for h in hypotheses if not is_proposal(h))


def proposals_of(result: GenerateResult | None) -> tuple[Hypothesis, ...]:
    """The returned quarantined proposals, recorded apart for the owner."""
    hypotheses = () if result is None else result.hypotheses
    return tuple(h for h in hypotheses if is_proposal(h))


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
        returned = scored_hypotheses(run.result)
        review = next((e for e in run.exchanges if e.label == "reviewer"), None)
        shown = [
            i
            for i in ([] if review is None else shown_ideas(review.request))
            if i.lane not in _RELAXING_LANE_VALUES  # a proposal: never pooled
        ]
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


_RELAXING_LANE_VALUES: Final = frozenset(lane.value for lane in RELAXING_LANES)


def candidate(idea: ShownIdea, idea_id: str) -> IdeaCandidate:
    """A pooled idea as the reviewer request takes it: the shown fields, the
    rest neutral (``review_request`` renders only the shown ones); a
    relaxing lane's idea keeps its lane's proposal tag (G3), as its
    validator requires (``pool`` never pools one)."""
    path, _, name = (idea.anchor or "").rpartition(":")
    lane = Lane(idea.lane if idea.lane in Lane.__members__ else Lane.obvious.value)
    return IdeaCandidate(
        id=idea_id, lane=lane, proposal=RELAXING_LANES.get(lane), title=idea.title,
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
    reviews: tuple[AuditReview | None, ...] = ()  # per pooled idea, as verdicts


def pool_ids(n: int) -> list[str]:
    """The auditor's neutral ids of ``n`` pooled ideas, in pool order."""
    return [f"i{k:02d}" for k in range(1, n + 1)]


def audit_of(
    reply: str,
    n: int,
    *,
    shown: Sequence[str] | None = None,
    cost_usd: float = 0.0,
    error: str | None = None,
    exchanges: tuple[Exchange, ...] = (),
) -> Audit:
    """The audit of ``n`` pooled ideas from the auditor's reply: per idea its
    single review, ``None`` for one not shown (``shown``: the ids the request
    showed; all by default), not reviewed or reviewed twice."""
    found = audit_reviews(reply)
    reviews = tuple(
        found.get(i) if shown is None or i in shown else None for i in pool_ids(n)
    )
    verdicts = tuple(None if r is None else r.verdict for r in reviews)
    return Audit(verdicts, cost_usd, error, exchanges, reviews)


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
    ids = pool_ids(len(pooled))
    request, shown = review_request(
        [candidate(p.idea, i) for p, i in zip(pooled, ids, strict=True)],
        prefix=prefix, fence=fence, reviewer_fence=Fence.new(others=(fence.token,)),
        max_ideas=AUDIT_MAX_IDEAS, max_tokens=AUDIT_MAX_TOKENS, effort=AUDIT_EFFORT,
        notes=notes,
    )  # fmt: skip
    cfg = model_settings(base, OPUS)
    tap = Tap(run.transport(cfg), "auditor", ("auditor",))
    first = len(run.records)
    reply = ""
    error: str | None = None
    try:
        result = call(tap, request, Budget(AUDIT_USD), sleep=time.sleep,
                      max_retries=cfg.LLM_MAX_RETRIES)  # fmt: skip
        read_review(result)  # strict: a stop or refusal is the audit's error
        reply = reply_text(result.message)
    except ARM_ERRORS as exc:
        error = f"{type(exc).__name__}: {exc}"
    return audit_of(
        reply, len(pooled), shown=tuple(shown),
        cost_usd=math.fsum(r.cost_usd for r in run.records[first:]),
        error=error, exchanges=tuple(tap.exchanges),
    )  # fmt: skip


@dataclass(frozen=True)
class Score:
    non_obvious: int
    good: int | None  # None: not audited; as pre-registered and coded
    audited: int
    auditor_infeasible: int
    own_removed: int  # pooled ideas its own reviewer marked infeasible
    agreed: int  # of those, infeasible for the auditor too
    good_corrected: int | None = None  # STATUS 2026-10-31: duplicates inherit
    good_strict: int | None = None  # corrected, less roots of arm A (A: None)


_BAD: Final = ReviewVerdict.infeasible.value
_DUPLICATE: Final = "duplicate_of"


def _root(
    k: int, reviews: Sequence[AuditReview | None], index: Mapping[str, int]
) -> int | None:
    """The pooled idea that idea ``k`` repeats, followed to the first one: ``k``
    itself unless the auditor marked it a duplicate; ``None`` when a link names
    no pooled id (or none) or the links loop."""
    seen = {k}
    while (r := reviews[k]) is not None and (r.verdict, r.reason) == (_BAD, _DUPLICATE):
        target = index.get(r.duplicate_of or "")
        if target is None or target in seen:
            return None
        seen.add(target)
        k = target
    return k


def _inherited(
    pooled: Sequence[Pooled], audit: Audit
) -> list[tuple[str | None, str | None]]:
    """Per pooled idea, the corrected rule (STATUS 2026-10-31): its verdict and
    the arm of the idea it was decided on. A duplicate whose root is another
    arm's takes the root's verdict; one of the same arm's own idea, or with no
    root, keeps its own (``infeasible``)."""
    n = len(pooled)
    reviews = [*audit.reviews, *[None] * n][:n]
    verdicts = [*audit.verdicts, *[None] * n][:n]
    index = {i: k for k, i in enumerate(pool_ids(n))}
    out: list[tuple[str | None, str | None]] = []
    for k, p in enumerate(pooled):
        root = _root(k, reviews, index)
        if root is None or pooled[root].arm == p.arm:
            out.append((verdicts[k], p.arm))
        else:
            out.append((verdicts[root], pooled[root].arm))
    return out


def scores(
    arms: Sequence[ArmRun], pooled: Sequence[Pooled], audit: Audit | None
) -> dict[str, Score]:
    """Per arm: good = returned non-obvious ideas (arm A: distinct titles)
    the auditor answered once and did not mark infeasible; unknown with no
    audit or a failed one. ``good_corrected``: the same, a duplicate taking
    the verdict of the other arm's idea it repeats (``_inherited``);
    ``good_strict``: of those, none decided on an arm-A idea (unknown for A,
    the baseline it is read against)."""
    out: dict[str, Score] = {}
    verdicts = () if audit is None else audit.verdicts
    fixed = [] if audit is None else _inherited(pooled, audit)
    audited_ok = audit is not None and audit.error is None
    for run in arms:
        mine = [
            (p, v, *f)
            for p, v, f in zip(pooled, verdicts, fixed, strict=False)
            if p.arm == run.arm.key
        ]
        audited = [(p, v) for p, v, *_ in mine if v is not None]
        ok = {p.idea.title for p, v in audited if tier(p) == 0 and v != _BAD}
        kept = [
            (p.idea.title, root)
            for p, _, w, root in mine
            if tier(p) == 0 and w is not None and w != _BAD
        ]
        removed = [(p, v) for p, v in audited if p.own == _BAD]
        hypotheses = scored_hypotheses(run.result)
        known = audited_ok and run.arm.e1
        strict = known and run.arm.key != ARM_A.key
        out[run.arm.key] = Score(
            non_obvious=sum(_lane(h) not in ("obvious", "today") for h in hypotheses),
            good=len(ok) if known else None,
            audited=len(audited),
            auditor_infeasible=sum(v == _BAD for _, v in audited),
            own_removed=len(removed),
            agreed=sum(v == _BAD for _, v in removed),
            good_corrected=len({t for t, _ in kept}) if known else None,
            good_strict=(
                len({t for t, root in kept if root != ARM_A.key}) if strict else None
            ),
        )
    return out


# ---------------------------------------------------------------------------
# Rows, notes, the summary
# ---------------------------------------------------------------------------


def sent_frameworks(run: ArmRun) -> dict[str, str | None]:
    """The framework of each S2 lane this arm sent and got an answer for
    (G5). The pipeline labels every lane it assigned one, sent or not, so the
    labels are joined with the pipeline's own stop reasons, keyed by lane in
    every mode (a sequential re-priced lane is sent under a fresh ``lane-N``
    tap label). A lane the budget or count mode stopped, or whose request
    failed after its retries, produced nothing and is left out."""
    if run.result is None or run.result.stats is None:
        return {}
    answered = {k for k, v in run.result.stats.stop_reasons.items() if v is not None}
    return {
        lane.value: label
        for lane, label in framework_labels(run.result.notes).items()
        if lane.value in answered
    }


@dataclass(frozen=True)
class ProbeRow:
    repo: str
    arm: str
    models: tuple[str, ...]
    error: str | None
    ideas: int  # returned, less the quarantined proposals
    non_obvious: int
    good: int | None
    good_corrected: int | None
    good_strict: int | None
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
    proposals: int = 0  # returned quarantined proposals (G3): never scored
    # G5: each sent S2 lane's framework ("view <name>", "rule <rule>" or
    # None); empty with IDEAS_LANE_FRAMEWORKS off, so X1-3 labels its two
    # factors (``sent_frameworks``)
    frameworks: dict[str, str | None] = field(default_factory=dict)
    lever: str = ""  # X1: what the configuration moves (X1-3: two factors)
    lane_models: dict[str, str] = field(default_factory=dict)  # X1-1's row
    views: dict[str, str] = field(default_factory=dict)  # X1-3's lens views

    def record(self) -> dict[str, object]:
        return {"experiment": ROW_EXPERIMENT, **asdict(self)}


# ---------------------------------------------------------------------------
# Every idea, one row each (X1's full lists, Vf's input)
# ---------------------------------------------------------------------------

_LENS_TAG: Final = re.compile(r'<lens name="([a-z_]+)"')


def request_lane(request: LLMRequest) -> Lane:
    """The lane a lane request is for, from its instruction (the last block):
    its lens tag (a lens, a rule-relaxing lane, the leap), none for S1. A
    sequential re-priced lane's tap label is ``lane-N``, so the label is not
    read."""
    content = request.messages[0]["content"]
    blocks = cast(Sequence[Mapping[str, object]], content)
    last = content if isinstance(content, str) else str(blocks[-1].get("text", ""))
    found = _LENS_TAG.search(last)
    return Lane.obvious if found is None else Lane(found.group(1))


def read_text_of(reader: RepoReader, commit: str) -> Callable[[str], str | None]:
    """Each file's text at ``commit``, read once (``None``: not tracked there
    or not readable); git objects only, never the work tree."""

    @functools.cache
    def tracked() -> frozenset[str]:
        try:
            return frozenset(reader.ls_tree(commit))
        except GitError:
            return frozenset()

    @functools.cache
    def read(path: str) -> str | None:
        if path not in tracked():
            return None
        try:
            data = reader.read_blob(commit, path, limit=settings.IDEAS_PARSE_MAX_BYTES)
        except GitError:
            return None
        return data.decode("utf-8", errors="replace")

    return read


def _no_text(_path: str) -> str | None:
    return None


def reply_ideas(
    reply: str, read: Callable[[str], str | None]
) -> list[tuple[_ReplyIdea, dict[str, int] | None]]:
    """A lane reply's ideas (``IDEAS_SCHEMA``, strictly; unreadable: none),
    each with its target lines: the quote's first match in the file it names,
    as E1's recorded ideas are keyed (``idea_dedupe.load_recorded``)."""
    try:
        items = _Reply.model_validate_json(reply).hypotheses
    except ValidationError:
        return []
    found: list[tuple[_ReplyIdea, dict[str, int] | None]] = []
    for item in items:
        try:
            text = read(normalize_path(item.depends_on_path))
        except ValueError:
            text = None
        lines = None if text is None else quote_lines(text, item.depends_on_quote)
        target = None if lines is None else {"first": lines[0], "last": lines[1]}
        found.append((item, target))
    return found


def idea_records(
    repo: str, run: ArmRun, read: Callable[[str], str | None]
) -> list[dict[str, object]]:
    """Every idea the arm proposed: each sent lane reply's (S1, the lenses,
    the leap, the rule-relaxing lanes; returned or not), or the ideas today's
    generator returned; the proposal flag is the lane's (G3). ``label`` is
    the exchange's: (repo, arm, label) names its sent ``ideas-reply`` row,
    also for a sequential lane re-priced under a generic ``lane-N`` label."""
    hypotheses = () if run.result is None else run.result.hypotheses
    returned = {h.title for h in hypotheses}
    rows: list[dict[str, object]] = []

    def row(
        lane: Lane | None, e: Exchange | None, k: int, title: str, change: str
    ) -> dict[str, object]:
        rule = None if lane is None else RELAXING_LANES.get(lane)
        return {
            "experiment": IDEA_EXPERIMENT, "repo": repo, "arm": run.arm.key,
            "lane": "today" if lane is None else lane.value,
            "label": "generator" if e is None else e.label,
            "model": "" if e is None else e.model, "position": k,
            "title": redact_keys(title), "change": _fit(redact_keys(change)),
            "returned": title in returned, "proposal": rule is not None,
            "relaxes": None if rule is None else rule.value,
        }  # fmt: skip

    if not run.arm.pipeline:
        first = next(iter(run.exchanges), None)  # today's one generator request
        for k, h in enumerate(hypotheses, 1):
            change = h.rationale.split("\n", 1)[0]  # today's change_summary line
            rows.append({**row(None, first, k, h.title, change), "mechanism": None,
                         "cells": [], "path": None, "target": None})  # fmt: skip
        return rows
    for e in run.exchanges:
        if e.role not in ("lane", "leap") or not e.sent:
            continue
        lane = request_lane(e.request)
        for k, (item, target) in enumerate(reply_ideas(e.reply, read), 1):
            rows.append({
                **row(lane, e, k, item.title, item.change_summary),
                "mechanism": item.mechanism.value,
                "cells": [c.value for c in item.morph_cells],
                "path": redact_keys(item.depends_on_path), "target": target,
            })  # fmt: skip
    return rows


def _reply(repo: str, arm: str, e: Exchange) -> dict[str, object]:
    text = redact_keys(e.reply)
    return {
        "experiment": REPLY_EXPERIMENT, "repo": repo, "arm": arm, "role": e.role,
        "label": e.label, "counted": e.counted, "sent": e.sent,
        "stop_reason": e.stop_reason, "usage": list(e.usage), "chars": len(text),
        "shown": len(shown_ideas(e.request)), "seconds": round(e.seconds, 3),
        "chunks": _chunks(text),
    }  # fmt: skip


def _proposal(repo: str, arm: str, h: Hypothesis) -> dict[str, object]:
    """One quarantined proposal for the owner to read (G3): never scored."""
    return {
        "experiment": PROPOSAL_EXPERIMENT, "repo": repo, "arm": arm,
        "title": h.title, "lane": _lane(h), "relaxes": list(relaxed_rules(h)),
        "rationale": _chunks(redact_keys(h.rationale)),
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
    views: dict[str, RecordedViews] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.plan.facts is not None and not self.recorded:
            self.recorded = load_facts(self.plan.facts)
        if self.plan.facts is not None:
            for repo in self.plan.repos:
                if repo.name not in self.recorded:
                    raise ValueError(f"{FACTS_ENV}: no recorded facts for {repo.name}")
        viewed = [
            a.key for a in self.plan.arms if arm_update(a).get("IDEAS_LANE_VIEWS")
        ]
        if viewed and self.plan.views is None:
            raise ValueError(f"{VIEWS_ENV}: {viewed[0]}'s views are never built live; "
                             "name the recorded views (Va)")  # fmt: skip
        if self.plan.views is not None:
            self.views = checked_views(self.plan, self.recorded)

    def record(
        self,
        repo: str,
        arms: Sequence[ArmRun],
        pooled: Sequence[Pooled],
        audit: Audit | None,
        run: LiveRun,
        *,
        read: Callable[[str], str | None] = _no_text,
    ) -> None:
        """Rows, replies, proposals and every idea (``read``: a file's text
        at the commit, for target lines), then the audit's records."""
        n = len(pooled)
        reviewed = (  # every pooled idea's record, or a short audit refused here
            []
            if audit is None
            else list(zip(pool_ids(n), pooled, audit.verdicts,
                          [*audit.reviews, *[None] * n][:n], strict=True))
        )  # fmt: skip
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
                ideas=len(scored_hypotheses(a.result)),
                proposals=len(kept := proposals_of(a.result)),
                non_obvious=s.non_obvious, good=s.good,
                good_corrected=s.good_corrected, good_strict=s.good_strict,
                audited=s.audited,
                auditor_infeasible=s.auditor_infeasible, own_removed=s.own_removed,
                agreed=s.agreed, cost_usd=a.cost_usd,
                stats=None if stats is None else stats.model_dump(mode="json"),
                stops={e.label: e.stop_reason for e in ex},
                cache_reads={e.label: e.usage[2] for e in ex},
                counted={e.label: e.counted for e in ex},
                sent=tuple(e.label for e in ex if e.sent), audit_error=audit_error,
                frameworks=sent_frameworks(a), lever=a.arm.lever,
                lane_models=a.lane_models, views=a.views,
            )  # fmt: skip
            self.rows.append(row)
            self.sink.write(row.record())
            for idea in idea_records(repo, a, read):
                self.sink.write(idea)
            for e in ex:
                self.sink.write(_reply(repo, a.arm.key, e))
            for h in kept:
                self.sink.write(_proposal(repo, a.arm.key, h))
            good = "-" if s.good is None else s.good
            held = f", {row.proposals} proposal(s)" if row.proposals else ""
            parts.append(
                f"{a.arm.key} {row.ideas} idea(s){held}, good {good}, {a.cost_usd:.3f}"
            )
        if audit is not None:
            for i, p, v, r in reviewed:
                self.sink.write({
                    "experiment": AUDIT_EXPERIMENT, "repo": repo, "arm": p.arm,
                    "id": i, "title": p.idea.title, "lane": p.idea.lane,
                    "tier": tier(p), "in_result": p.in_result, "own": p.own,
                    "auditor": v, "reason": None if r is None else r.reason,
                    "duplicate_of": None if r is None else r.duplicate_of,
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
            "| repo | arm | ideas | non-obvious | good | good corrected | good strict "
            "| audited | auditor infeasible | own removed (agreed) | proposals "
            "| USD | error |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: "
            "| ---: | ---: | --- |",
        ]  # fmt: skip
        for r in self.rows:
            lines.append(cells([
                r.repo, r.arm, r.ideas, r.non_obvious, _known(r.good),
                _known(r.good_corrected), _known(r.good_strict), r.audited,
                r.auditor_infeasible, f"{r.own_removed} ({r.agreed})",
                r.proposals, f"{r.cost_usd:.4f}", _errors(r),
            ]))  # fmt: skip
        write_markdown("Ideas probe", "\n".join(lines), self.sink.environ, echo)


def checked_views(
    plan: ProbePlan, recorded: Mapping[str, FactsBody], base: Settings = settings
) -> dict[str, RecordedViews]:
    """Va's views for every planned library, each recorded from exactly the
    source this run builds (the facts' commit, run, profile and patterns, no
    read-deny, ``base``'s limits, the corpus workload), or refused: before any
    spend, not when a lane asks for its view after S1 has spent."""
    from . import ideas_views as iv  # it imports this module

    loaded = iv.load_views(cast(Path, plan.views), recorded)
    limits = IdeaReadLimits.from_settings(base)
    for repo in plan.repos:
        views = loaded.get(repo.name)
        if views is None:
            raise ValueError(f"{VIEWS_ENV}: no recorded views for {repo.name}")
        body = recorded[repo.name]
        source = ViewSource(
            cast(RepoReader, None),  # the digest reads no git object
            body.commit, body.hotspots, Fence.new(), body.protected, (), limits,
            (iv.recorded_workload(repo, body),),
        )  # fmt: skip
        if (views.limits, views.source_sha256) != (limits, iv.source_digest(source)):
            raise ValueError(f"{VIEWS_ENV}: {repo.name}'s views are not the source "
                             "this run builds (limits, profile, patterns or workload)")  # fmt: skip
    return loaded


def _known(value: int | None) -> str:
    return "-" if value is None else str(value)


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
    run = live(plan.library_cap(repo.name))
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
        views = recorder.views.get(repo.name)
        workloads = () if views is None or body is None else _workload(repo, body)
        arms = [
            run_arm(a, run, facts, base=base, reader=reader,
                    views=None if views is None else views.build, workloads=workloads)
            for a in plan.arms
        ]  # fmt: skip
        pooled = pool(arms, facts) if plan.audit else []
        audit = (
            run_audit(pooled, run, facts, base=base, reader=reader) if pooled else None
        )
        read = read_text_of(reader(facts.facts.project), facts.commit)
        recorder.record(repo.name, arms, pooled, audit, run, read=read)
        untouched()
        check_spend(run, arms, audit)
    except BaseException as exc:
        run.note(_fit(f"IDEAS {repo.name}: breach: {type(exc).__name__}: {exc}"))
        raise


def _nothing() -> None:
    return None


def _workload(repo: OssRepo, body: FactsBody) -> tuple[Workload]:
    """The workload Va's views were built with (the input shape is its)."""
    from . import ideas_views as iv  # it imports this module

    return (iv.recorded_workload(repo, body),)
