"""X2a: the ``ideas-x2`` suite, evolution on the levers X1 kept (spec-idea-lab
section 9, revision 2; O46-O48), the three settings-only arms.

**Arms** (``X2_ARMS``): every arm is ``SHARED``, X1-0's idea pipeline (S1 and
the six lenses on Sonnet 5.5, the think line as X1-0, the Opus 5.5 leap and
reviewer) with the eliminate lens on Haiku 5.5 (O48), two rounds in all
(O48; the router ends exploration at a keep once ``round`` reaches
``PORTFOLIO_ROUNDS``, so two takes 2, not the spec's 1, and
``MAX_TRIAL_ROUNDS`` 2 ends the run there), round seeds, near-miss
compounds, the op-count judge, and no lessons, sequential lanes, mechanism
dedupe or rule-relaxing lane. A round trials ``round_trials`` ideas: the
pipeline's largest result (``GENERATOR_N`` + ``IDEAS_PORTFOLIO_MAX``), since
the node calls the generator only on an empty pool, so round 1 leaves none
and round 2 is D64's seeded call (spec 9.3-9.4); ``WHOLE_POOL`` off is the
factory's 3, round 2 then draws on round 1's pool and the seeds stay dormant.
X2-0 runs it on the eight libraries, its A/A twin X2-0' again, independently,
on the four slice libraries, X2-V with each lens on X1-3's view
(``ideas_probe.X1_VIEWS``) and no framework. X2-F (frameworks on the shared
view) needs ``src`` (``idea_pipeline`` builds a framework only beside a
view) and a Fable lane is the owner's call (spec 9.7): both stay out, and an
arm is one more ``X2Arm`` and ``DISPATCHES`` entry.

**Settings**: ``oss.start_oss_loop`` reads the process-wide ``settings``, so
an arm is an env mapping (``arm_env``: booleans ``true``/``false``, dicts and
tuples as JSON) that ci.yml exports per dispatch; ``check_settings`` refuses,
before any spend, a process off the arm on any key, the op-count judge off or
another engine than Opus 5.5 (``ideas_slice.check_engine``).

**Runs**: each (arm, library) one whole engine run, wired, the idea pipeline
on, its profile and views live, on a fresh clone at the commit E1 recorded
(``ideas_probe``'s facts fixture, refused otherwise), every corpus guard
(``discovery.run_engine``). ``$LIVE_X2_DISPATCH`` names a dispatch's arm and
libraries, ``ARM:lib,lib`` (``dispatches``: four runs each, five dispatches);
the live module's cases are ``EVERY_RUN``, every arm's runs, the plan's first.

**Spend**: a run's hard cap (``run_cap``) is the least that lets the seeded
second call (D64) pass the engine's own reservations (``nodes._discovery_cap``,
then ``Budget.check`` per stage: S1, S2 whole, the reviewer) after a first
call and round 1's trials at X1's dearest measured, with what X1 measured
of a call before each stage: inside D55's discovery share; and the whole run
(the understand request at its worst, each round a call at X1's dearest and
its trials at the slice's dearest loop, the dearest seeded stage at its
worst) with one trial's reserve: X2-0 9.35, X2-V 9.45 (6.50 and 6.70 at 3 a
round; the spec proposed 6); with more rounds, the last seeded call after
every earlier one. Minutes: a clone, each round's trials in loops
of 3 at ``ideas_slice.LOOP_MINUTES`` and two calls at their worst, 89 (44).
A dispatch's need, the sum of its caps, stays under the 80 USD fuse, its
minutes under the job's, and the suite cap at least the need, before spend.

**Records** (``$LIVE_RESULTS_PATH``): ``ideas-x2-hypothesis`` per hypothesis
(trialled or left in the pool: round, title, lane, label, model, mechanism,
target lines, compound and parents, verdict, gain, floor, op counts),
``ideas-x2-round`` per round (trialled, kept, seeds shown and the seeded
lanes, the seeded call's calls and USD, compounds tried and kept),
``ideas-x2-run`` per run (commit, cap, cost, discovery and D64's
``seeded_calls``/``seeded_cost_usd``, refusals, the combine, the guard).

**Patches** (U-patch, record-only, every arm): each kept trial's recorded
diff and the held combine's delivered patch go to files beside the results
(``x2_patches``, redacted); a kept hypothesis row adds ``diff`` (its
verdict's trial id and commit, file, sha256, truncation, whether the
delivered patch applied it, or the error), the run row ``base_commit``,
``patch_dir``, ``kept_diffs``, ``delivered_patch`` (the delivery's tip and
the combination's applied trial ids) and a note for each when none is
written; a failed write is an error on its entry, never a lost row.

**X2-C** (emergence round 1, S1): X2-0 plus ``IDEAS_COUNT_CONTRACT=record``,
no request changed, so the cap and minutes are X2-0's; off ``X2_ARMS`` and
the plan until dispatched. Its hypothesis rows add ``realisation``, each
measured trial's ``evolve.realisation`` over the base text of the files it
changed (``base_sources``: the clone at E1's commit, which the engine never
writes), the anchor its mechanism key's function.

**X2-S** (emergence round 1, S2): X2-0 plus ``IDEAS_COUNT_CONTRACT=record``
(the unit counts part 3's eligibility reads) and ``SITE_STACKS=on``, on the
four libraries with same-site conflicts in X2; no request changed and part
3 trials none, so the cap and minutes are X2-0's; off the plan. A run whose
combination holds keep records (``SITE_STACKS`` on or record) writes per
kept hypothesis ``combine`` (``combine_row``: ids as hypothesis ids) and on
the run row its ``conflicts``; other runs write neither.

**Variance** (emergence round 2, S1): an arm's ``aa`` says whether its runs
are A/A pool draws (``full``: X2-0's requests and delivery; frozen before any
run, X2-S's delivery differs and X2-V's requests). Every arm sets
``IDEAS_VIEW_RECORD``: each round row adds ``lane_views`` (lane, view hash,
served model per lane request) and the run row ``minutes_planned`` and
``seconds_measured``. ``RIDER_SECONDS`` declares each record-only setting's
CPU (per run, trial and keep; ``RIDER_MEASURED`` the last measured, the
larger counts), which ``run_minutes`` adds, so ``check_plan`` refuses a
dispatch past the job's minutes with its riders.

**Shadow** (emergence round 2, S4): X2-SV is X2-C with
``SHADOW_VERIFY=record`` on sqlparse, tomli and mistune, off the plan (the
trial runner reads the setting, no request; no A/A draw until its timing is
shown equal, the owner's ruling of 2026-11-11); it is dispatchable,
in ``EVERY_ARM`` with its ci.yml case. Its hypothesis rows
add ``shadow_verify``, the first measured trial's reading
(``shadow_verify.shadow_reading``, its twin against itself), and its run row
``shadow_aa``, the twins that differ from the first (the A/A, 0).

**Depth** (Window 2): X2-D is X2-0 with three rounds (``PORTFOLIO_ROUNDS``
and ``MAX_TRIAL_ROUNDS`` 3) and a third generator call
(``GENERATOR_MAX_CALLS`` 3, the default 2: without it the router reaches
round 3 only for a waiting near-miss compound, round 2 leaving the pool
empty), nothing else, on sqlparse, tomli, mistune and markdown, off the
plan and no A/A draw (a third round changes what is trialled and
delivered); dispatchable, in ``EVERY_ARM`` with its ci.yml case. Its cap
and minutes are the derivation above with a third round, its call charged:
12.90 USD and 133 minutes, two runs a dispatch.
"""

from __future__ import annotations

import functools
import json
import math
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Literal

from e2e.conftest import Isolation, LaunchLog

from autonomous_ai_agents.clients.transport import LLMTransport
from autonomous_ai_agents.common.config import (
    LANE_ROLE_LANES,
    Settings,
    lane_chain,
    lane_settings,
    role_chain,
    settings,
)
from autonomous_ai_agents.common.models import (
    Combination,
    Delivery,
    DeliveryKind,
    EngineEvent,
    Hypothesis,
    JsonScalar,
    KeepRecord,
    Trial,
    TrialStatus,
    Verdict,
    VerdictOutcome,
)
from autonomous_ai_agents.common.paths import normalize_path
from autonomous_ai_agents.optimization.evolve import (
    COMPOUND_TAG,
    compound_parents,
    diff_hunks,
    realisation,
)
from autonomous_ai_agents.optimization.idea_dedupe import IdeaKey, recorded_keys
from autonomous_ai_agents.optimization.idea_pipeline import LANE_VIEW, SEEDED_CALL
from autonomous_ai_agents.optimization.idea_types import LENS_LANES, Lane
from autonomous_ai_agents.optimization.shadow_verify import shadow_aa, shadow_reading
from autonomous_ai_agents.orchestrator.factory import build_context
from autonomous_ai_agents.orchestrator.main import EngineRunResult

from . import discovery_oss as dx
from . import ideas_probe as ip
from . import ideas_slice as isl
from . import oss
from . import x2_patches as xp
from .conftest import LiveRun, StartLive, key_window, redact_keys, suite_cap
from .corpus import CorpusOutcome, Loop, role_wiring, settings_trial_budget
from .discovery import OPUS, SONNET, ceil_usd, run_engine
from .discovery_io import ResultsSink
from .oss import PRODUCTION, GitPolicy, OssRepo

DISPATCH_ENV: Final = "LIVE_X2_DISPATCH"
RUN_EXPERIMENT: Final = "ideas-x2-run"
ROUND_EXPERIMENT: Final = "ideas-x2-round"
IDEA_EXPERIMENT: Final = "ideas-x2-hypothesis"
X2_FUSE_USD: Final = ip.X1_FUSE_USD  # 80: each dispatch's worst case (spec 9.5)
JOB_MINUTES: Final = 360  # ci.yml's ideas-x2 timeout (GitHub's ceiling): 4 x 89
FACTORY_ROUND: Final = 3  # build_context's max_hypotheses_per_round
WHOLE_POOL: Final = True  # round 1 trials every idea: round 2 is the seeded call
LOOP_TRIALS: Final = 3  # X1_LOOP_USD's and LOOP_MINUTES' loop: up to 3 trials
# X1's measured rates (the handoff's x1/ rows, priced from their usage, each
# rounded up): the dearest X1-0 or X1-3 pipeline call of the eight libraries
# (X1-0 sqlparse), the dearest S1 (X1-3 mistune) and S1 + S2 (X1-0 sqlparse);
# the slice's dearest engine loop of 3 trials (pyparsing X1-3)
X1_CALL_USD: Final = 0.9138
X1_S1_USD: Final = 0.1066
X1_S1_S2_USD: Final = 0.6073
X1_LOOP_USD: Final = 0.7213


@dataclass(frozen=True)
class X2Arm:
    key: str
    repos: tuple[str, ...]
    update: Mapping[str, object]  # the settings, every one checked
    lever: str
    aa: Literal["none", "full"] = "none"  # S1: "full", an A/A pool draw


SHARED: Final[Mapping[str, object]] = {
    "IDEA_PIPELINE": True, "PORTFOLIO_ROUNDS": 2, "MAX_TRIAL_ROUNDS": 2,
    "IDEAS_ROUND_SEEDS": True,
    "NEAR_MISS_COMPOUNDS": True, "OP_COUNT_JUDGE": True, "GENERATOR_LESSONS": False,
    "IDEAS_SEQUENTIAL_LANES": False, "IDEAS_MECHANISM_DEDUPE": False,
    "IDEAS_RELAX_LANES": (), "IDEAS_LENSES": LENS_LANES, "IDEAS_LANE_MODEL": SONNET,
    "IDEAS_LANE_MODELS": {Lane.eliminate: ip.HAIKU}, "IDEAS_LEAP_MODEL": OPUS,
    "IDEAS_REVIEWER_MODEL": OPUS, "IDEAS_THINK_LINE_ALL": False,
    "IDEAS_LANE_VIEWS": {}, "IDEAS_LANE_FRAMEWORKS": False, "IDEAS_VIEW_RECORD": True,
}  # fmt: skip
X2_0: Final = X2Arm("X2-0", ip.E1_REPOS, SHARED, "baseline: the shared setup", "full")
X2_0_TWIN: Final = X2Arm("X2-0'", isl.SLICE_REPOS, SHARED,
                         "A/A twin: X2-0 again, independent runs, the band", "full")  # fmt: skip
X2_V: Final = X2Arm("X2-V", ip.E1_REPOS, {**SHARED, "IDEAS_LANE_VIEWS": dict(ip.X1_VIEWS)},
                    "views (G2): each lens X1-3's view, no framework")  # fmt: skip
X2_ARMS: Final = (X2_0, X2_0_TWIN, X2_V)
X2_C: Final = X2Arm("X2-C", ip.E1_REPOS, {**SHARED, "IDEAS_COUNT_CONTRACT": "record"},
                    "count record (S1): X2-0 with unit counts and realisation rows", "full")  # fmt: skip
X2_S: Final = X2Arm("X2-S", ("more_itertools", "tomli", "mistune", "sqlparse"),
                    {**SHARED, "IDEAS_COUNT_CONTRACT": "record", "SITE_STACKS": "on"},
                    "site stacks (S2): X2-0 with the combine record and delivery by gain")  # fmt: skip
X2_SV: Final = X2Arm("X2-SV", ("sqlparse", "tomli", "mistune"),
                     {**X2_C.update, "SHADOW_VERIFY": "record"},
                     "shadow record (S4): X2-C with capture rows and shadow readings")  # fmt: skip
X2_D: Final = X2Arm("X2-D", ("sqlparse", "tomli", "mistune", "markdown"),
                    {**SHARED, "PORTFOLIO_ROUNDS": 3, "MAX_TRIAL_ROUNDS": 3,
                     "GENERATOR_MAX_CALLS": 3},
                    "depth (Window 2): X2-0 with a third round")  # fmt: skip
# the plan's arms, then those off it (X2-D first, so the older tails stand)
EVERY_ARM: Final = (*X2_ARMS, X2_D, X2_S, X2_C, X2_SV)
LIBRARIES: Final = {r.name: r for r in dx.OSS_SELECTABLE if r.name in ip.E1_REPOS}
Run = tuple[X2Arm, OssRepo]
ALL_RUNS: Final[tuple[Run, ...]] = tuple(
    (a, LIBRARIES[n]) for a in X2_ARMS for n in a.repos
)
# the live module's cases: the plan's 20, then the off-plan arms' runs, so
# a dispatch of any arm selects a case (E1, run 42232651527, skipped all 20)
EVERY_RUN: Final[tuple[Run, ...]] = tuple(
    (a, LIBRARIES[n]) for a in EVERY_ARM for n in a.repos
)


def _env(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | str):
        return str(value)
    return json.dumps(value, separators=(",", ":"))


def arm_env(arm: X2Arm) -> dict[str, str]:
    """What ci.yml exports for ``arm`` (``Settings`` reads JSON for a dict or tuple)."""
    return {key: _env(value) for key, value in arm.update.items()}


def arm_settings(arm: X2Arm, base: Settings = settings) -> Settings:
    return base.model_copy(update=dict(arm.update))


def check_settings(arm: X2Arm, base: Settings = settings) -> None:
    wrong = sorted(k for k, v in arm.update.items() if getattr(base, k) != v)
    if wrong:
        raise ValueError(f"arm {arm.key}: {', '.join(wrong)} not as its mapping "
                         "(ci.yml exports ideas_x2.arm_env)")  # fmt: skip
    isl.check_engine(base)  # OP_COUNT_JUDGE on, the Opus 5.5 engine and editor


# ---------------------------------------------------------------------------
# The cap, the need, the minutes: the plan, refused before any spend
# ---------------------------------------------------------------------------


def seeded_stages(cfg: Settings) -> tuple[float, float, float]:
    """The seeded call's reservations at their worst (D55): S1, S2 (every lane
    with G4's mechanisms block, which holds the seeds; the leap never sees
    one, so an upper bound) and the reviewer."""
    seeded = cfg.model_copy(update={"IDEAS_SEQUENTIAL_LANES": True})

    def one(lane: Lane) -> float:  # the leap on ``leap_shape`` and its chain
        return ip.lane_usd(seeded, lane)

    bound = (
        ip.VIEW_REVIEW_PROMPT_BOUND if cfg.IDEAS_LANE_VIEWS else ip.REVIEW_PROMPT_BOUND
    )
    review = ip.request_usd(
        bound, cfg.IDEAS_REVIEWER_MAX_TOKENS, cfg.IDEAS_REVIEWER_MODEL
    )
    return one(Lane.obvious), math.fsum(map(one, ip.s2_lanes(cfg))), review


def round_trials(cfg: Settings) -> int:
    """``max_hypotheses_per_round``: the pipeline's largest result (its bound,
    ``idea_pipeline._result``) while ``WHOLE_POOL``, else the factory's."""
    return cfg.GENERATOR_N + cfg.IDEAS_PORTFOLIO_MAX if WHOLE_POOL else FACTORY_ROUND


def run_trials(cfg: Settings) -> tuple[int, ...]:
    """Most trials each round runs: its ideas, and from round 2 one
    near-miss compound (G5b, at most one a round)."""
    t, c = round_trials(cfg), int(cfg.NEAR_MISS_COMPOUNDS)
    return tuple(t + (c if n else 0) for n in range(cfg.MAX_TRIAL_ROUNDS))


# X2-D's third round, derived as X2-0's two (run_cap, run_minutes, which
# charge a call a round, MAX_TRIAL_ROUNDS, and X2-D's GENERATOR_MAX_CALLS 3
# makes it real): one more
# pipeline call at X1_CALL_USD and 11 trials at X1_LOOP_USD / 3, 3.56 USD, so
# 9.33 + 3.56 = 12.89, 12.90 rounded up (9.35 for two); one more call at 8
# minutes and 4 loops at 9, 89 + 44 = 133 minutes. The share term holds the
# last seeded call after every earlier call (8.77 for three: it never binds).
# Cross-check on the X2 archives (d1, d2, d4, d5, d7: the 12 X2-0 and X2-0'
# runs; test_ideas_x2_depth recomputes it): a round measured at most 1.66 USD
# (sqlparse round 1: a first call 0.84, discovery 1.548 less the seeded
# 0.706, and 9 trials at 0.090), round 2 1.41 (markdown: seeded 0.70, 7
# trials at 0.100), against the 3.56 a round charged; the dearest call 0.84
# (first) and 0.71 (seeded) against 0.91; the dearest trial 0.100 against
# 0.240; the dearest run 2.99 USD of 9.35. Minutes (STATUS's dispatch rows,
# job wall time): 36, 38 and 62 for three runs (d1, d2, d4; 33, 36 and 43
# trials), 20 for one (d5, 17), 26 for two (d7, 26): at most 21 a run and
# 1.44 a trial, against 89 for at most 21 trials (4.2 a trial).
def run_cap(cfg: Settings) -> float:
    s1, s2, review = seeded_stages(cfg)
    stage = max(s1, X1_S1_USD + s2, X1_S1_S2_USD + review)
    earlier = (cfg.MAX_TRIAL_ROUNDS - 1) * X1_CALL_USD  # before the last seeded call
    share = (earlier + stage) / cfg.IDEAS_DISCOVERY_MAX_SHARE
    trials = X1_LOOP_USD / LOOP_TRIALS * sum(run_trials(cfg))
    total = (settings_trial_budget(cfg) + dx.OSS_PHASE_ONE_WORST_USD
             + cfg.MAX_TRIAL_ROUNDS * X1_CALL_USD + trials + stage)  # fmt: skip
    return ceil_usd(max(share, total))


def arm_cap(arm: X2Arm, base: Settings = settings) -> float:
    return run_cap(arm_settings(arm, base))


@dataclass(frozen=True)
class Rider:
    """A record-only setting's CPU in seconds, per run, trial and keep (S1)."""

    run_s: float = 0.0
    trial_s: float = 0.0
    keep_s: float = 0.0


RiderKey = tuple[str, str]  # a setting and its value as ``arm_env`` writes it
# S4's rider: 1 capture launch at the baseline and 2 a trial (twin and trial),
# 7.4-7.9 s each on sqlparse (3.11, this container); the ledger takes the
# larger measured figure
SHADOW_RIDER: Final = Rider(run_s=8.0, trial_s=16.0)
RIDER_SECONDS: Mapping[RiderKey, Rider] = {
    ("IDEAS_VIEW_RECORD", "true"): Rider(),  # one sha256 a lane request
    ("SHADOW_VERIFY", "record"): SHADOW_RIDER,
}  # each rider's own declared figures, added by the unit that builds it
RIDER_MEASURED: Mapping[RiderKey, Rider] = {}  # from run rows: the larger counts


def rider_seconds(cfg: Settings) -> float:
    """Every rider ``cfg`` turns on, each part at max(declared, measured),
    every trial counted as a keep (the worst case)."""
    trials, total = sum(run_trials(cfg)), 0.0
    for key, declared in RIDER_SECONDS.items():
        if _env(getattr(cfg, key[0])) == key[1]:
            seen = RIDER_MEASURED.get(key, declared)
            total += max(declared.run_s, seen.run_s) + trials * (
                max(declared.trial_s, seen.trial_s) + max(declared.keep_s, seen.keep_s))  # fmt: skip
    return total


def run_minutes(cfg: Settings) -> int:
    """A clone, each round's trials in loops of 3 at L2b's whole wired OSS
    run (``ideas_slice.LOOP_MINUTES``, twice its measured 4.2), a pipeline
    call a round at its worst (``arm_seconds``, twice E1's slowest request)
    and the riders' seconds (``rider_seconds``)."""
    call = ip.arm_seconds(ip.ARM_X1_0, cfg)  # X1-0 overrides nothing: cfg's lanes
    loops = sum(math.ceil(t / LOOP_TRIALS) for t in run_trials(cfg))
    return (isl.CLONE_MINUTES + loops * isl.LOOP_MINUTES
            + cfg.MAX_TRIAL_ROUNDS * math.ceil(call / 60)
            + math.ceil(rider_seconds(cfg) / 60))  # fmt: skip


@dataclass(frozen=True)
class X2Plan:
    dispatch: str
    runs: tuple[Run, ...]


def x2_need(plan: X2Plan, base: Settings = settings) -> float:
    return round(math.fsum(arm_cap(a, base) for a, _ in plan.runs), 2)


def plan_minutes(plan: X2Plan, base: Settings = settings) -> int:
    return sum(run_minutes(arm_settings(a, base)) for a, _ in plan.runs)


def check_plan(plan: X2Plan, cap: float, base: Settings = settings) -> None:
    need, minutes = x2_need(plan, base), plan_minutes(plan, base)
    if need > min(X2_FUSE_USD, dx.CAP_CEILING_USD) or minutes > JOB_MINUTES:
        raise ValueError(f"dispatch {plan.dispatch}: {len(plan.runs)} runs need "
                         f"{need:.2f} USD and {minutes} minutes, past the "
                         f"{X2_FUSE_USD:g} USD fuse or the {JOB_MINUTES}-minute job")  # fmt: skip
    if cap < need:
        raise ValueError(f"suite cap {cap:.2f} USD is below dispatch {plan.dispatch}'s "
                         f"need {need:.2f}")  # fmt: skip


def x2_plan(environ: Mapping[str, str]) -> X2Plan:
    raw = environ.get(DISPATCH_ENV, "")
    key, _, names = raw.partition(":")
    arm, wanted = next((a for a in EVERY_ARM if a.key == key), None), names.split(",")
    if arm is None or len(set(wanted)) < len(wanted) or not {*wanted} <= {*arm.repos}:
        raise ValueError(f"{DISPATCH_ENV}: an arm ({', '.join(a.key for a in EVERY_ARM)}),"
                         f" ':' and its libraries, comma-separated; got {raw!r}")  # fmt: skip
    plan = X2Plan(raw, tuple((arm, LIBRARIES[n]) for n in arm.repos if n in wanted))
    check_plan(plan, suite_cap(environ))
    return plan


def dispatches(base: Settings = settings) -> tuple[str, ...]:
    """The plan: each arm's libraries in order, as many a dispatch as the
    job's minutes and the fuse allow."""
    out = []
    for arm in X2_ARMS:
        cfg = arm_settings(arm, base)
        per = min(JOB_MINUTES // run_minutes(cfg), int(X2_FUSE_USD // run_cap(cfg)))
        out += [f"{arm.key}:{','.join(arm.repos[i:i + per])}"
                for i in range(0, len(arm.repos), per)]  # fmt: skip
    return tuple(out)


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


def _by_round(
    events: Iterable[EngineEvent],
) -> dict[int, list[Mapping[str, JsonScalar]]]:
    """Each event's data under the round its hypotheses turn fed: a turn's
    events come before that round's ``ranked`` event (``nodes``)."""
    out: dict[int, list[Mapping[str, JsonScalar]]] = {}
    held: list[Mapping[str, JsonScalar]] = []
    for e in events:
        number = e.data.get("round")
        if "ranked" in e.data and isinstance(number, int):
            out.setdefault(number, []).extend(held)
            held = []
        else:
            held.append(e.data)
    return out


def _num(data: Mapping[str, JsonScalar], key: str) -> float:
    value = data.get(key)
    return float(value) if isinstance(value, int | float) else 0.0


def base_sources(root: Path, paths: Iterable[str], *,
                 cap: int = settings.IDEAS_PARSE_MAX_BYTES) -> dict[str, str]:  # fmt: skip
    """The base text of each normalised ``.py`` path under ``root``: no
    link, at most ``cap`` bytes, UTF-8; any other path is left out."""
    top, found = root.resolve(), {}
    for path in paths:
        file = root / path
        try:
            if (normalize_path(path) == path and path.endswith(".py") and not file.is_symlink()
                    and file.resolve().is_relative_to(top) and file.stat().st_size <= cap):  # fmt: skip
                found[path] = file.read_text(encoding="utf-8")
        except (OSError, ValueError):  # PathTraversalError, UnicodeDecodeError
            continue
    return found


def _tag(h: Hypothesis, key: str) -> str | None:
    return next((t.split(":", 1)[1] for t in h.tags if t.startswith(f"{key}:")), None)


def _realised(trials: Iterable[Trial], keys: Mapping[str, IdeaKey],
              verdicts: Mapping[str, Verdict], clone: Path) -> dict[str, object]:  # fmt: skip
    """S1: the first measured trial's realisation record per hypothesis."""
    out: dict[str, object] = {}
    for t in trials:
        if t.status is TrialStatus.measured and t.hypothesis_id not in out:
            key, v = keys.get(t.hypothesis_id), verdicts.get(t.hypothesis_id)
            fn = None if key is None else key.function
            out[t.hypothesis_id] = realisation(
                t, base_sources(clone, diff_hunks(t.diff)),
                anchor=None if key is None or fn is None else (key.key.target.path, fn),
                kept=v is not None and v.outcome is VerdictOutcome.keep,
            ).model_dump(mode="json")  # fmt: skip
    return out


def _shadowed(trials: Iterable[Trial]) -> tuple[dict[str, object], int]:
    """S4: the first measured trial's shadow reading per hypothesis (its
    twin against itself), and the base A/A over every measured twin."""
    out: dict[str, object] = {}
    measured = [t for t in trials if t.status is TrialStatus.measured]
    for t in measured:
        if t.hypothesis_id not in out:
            out[t.hypothesis_id] = shadow_reading(t.base_measurements, t.measurements).model_dump(mode="json")  # fmt: skip
    return out, shadow_aa(t.base_measurements for t in measured)


def combine_row(keep: KeepRecord | None, owner: Mapping[str, str]) -> dict[str, object] | None:  # fmt: skip
    """S2's record of one kept hypothesis, trial ids as hypothesis ids
    (``owner``), the order gain in percent; ``None`` for no record."""
    if keep is None:
        return None
    ids = {k: None if (v := getattr(keep, k)) is None else owner.get(v, v)
           for k in ("blocked_by", "duplicate_of", "superseded_by")}  # fmt: skip
    return {"delivered": keep.delivered, "skip_reason": keep.skip_reason, **ids,
            "component": keep.component, "best_subset": keep.best_subset,
            "gain_pct": dx._pct(keep.gain),
            "reconcile": keep.reconcile}  # fmt: skip


def _delivered_patch(writer: xp.PatchWriter, comb: Combination | None,
                     delivery: Delivery | None) -> tuple[xp.Entry | None, str | None]:  # fmt: skip
    """U-patch: the held combine's delivered patch, or why none is written.
    Its trials are the combination's ``applied_trial_ids``: the tip the
    publisher diffs is theirs (``combine_kept``; the delivery's verdict ids
    are the same trials' verdicts)."""
    if comb is None:
        return None, xp.NO_COMBINE
    if not comb.holds:
        return None, xp.NOT_HELD
    if not isinstance(delivery, Delivery) or delivery.kind is DeliveryKind.report_only:
        return None, xp.NO_BRANCH
    entry = writer.write(xp.DELIVERED_FILE, delivery.combined_diff)
    return {**entry, "base_commit": comb.base_commit, "tip_commit": delivery.commit,
            "branch": delivery.branch,
            "applied_trial_ids": list(comb.applied_trial_ids)}, None  # fmt: skip


def _kept_diffs(writer: xp.PatchWriter, hyps: Iterable[Hypothesis],
                verdicts: Mapping[str, Verdict], trials: Iterable[Trial],
                applied: Iterable[str]) -> dict[str, xp.Entry]:  # fmt: skip
    """U-patch: per kept hypothesis its verdict's trial's recorded diff, one
    file, and whether the delivered patch applied it."""
    by_id, delivered, out = {t.id: t for t in trials}, {*applied}, {}
    for h in hyps:
        v = verdicts.get(h.id)
        if v is None or v.outcome is not VerdictOutcome.keep:
            continue
        t = by_id.get(v.trial_id)
        entry = xp.missing(xp.ORPHAN) if t is None else {
            **writer.write(xp.trial_file(t.id), t.diff),
            "commit": t.commit, "base_commit": t.base_commit}  # fmt: skip
        out[h.id] = {
            "trial_id": v.trial_id,
            **entry,
            "applied": v.trial_id in delivered,
        }
    return out


@dataclass
class X2Recorder:
    plan: X2Plan
    sink: ResultsSink
    base: Settings = field(default_factory=lambda: settings)
    commits: Mapping[str, str] | None = None  # E1's recorded head per library

    def __post_init__(self) -> None:
        for arm in {a.key: a for a, _ in self.plan.runs}.values():
            check_settings(arm, self.base)
        if self.commits is None:
            facts = ip.load_facts(ip.SERVICE_DIR / ip.FACTS_FIXTURE)
            self.commits = {name: body.commit for name, body in facts.items()}

    def record(self, arm: X2Arm, repo: str, run: LiveRun, commit: str,
               seen: list[EngineRunResult | None], outcome: CorpusOutcome,
               result: EngineRunResult | None, *, clone: Path | None = None,
               started: float | None = None) -> None:  # fmt: skip
        seen.append(result)
        st = None if result is None else result.state
        hyps = [] if st is None else [*st["hypotheses"], *st["candidate_pool"]]
        events = [] if st is None else st["events"]
        guard = ip._fit(redact_keys(outcome.guard))
        ranks = dx.rank_rows(repo, 1, arm.key, hyps, result, guard=guard)
        rounds: dict[str, int] = {}
        for t in [] if st is None else st["trials"]:
            rounds.setdefault(t.hypothesis_id, t.round)
        verdicts = {
            v.hypothesis_id: v for v in reversed([] if st is None else st["verdicts"])
        }
        keys, cfg = recorded_keys(e.data for e in events), arm_settings(arm, self.base)
        viewed = cfg.IDEAS_VIEW_RECORD
        head = {"repo": repo, "arm": arm.key}
        realised = {} if st is None or clone is None else _realised(st["trials"], keys, verdicts, clone)  # fmt: skip
        shadow, aa = ({}, 0) if st is None else _shadowed(st["trials"])
        shadowed = cfg.SHADOW_VERIFY == "record"
        comb = None if st is None else st["combination"]
        owner = {} if st is None else {t.id: t.hypothesis_id for t in st["trials"]}
        stacked = {owner.get(k.trial_id, k.trial_id): k for k in (() if comb is None else comb.keeps)}  # fmt: skip
        writer = xp.PatchWriter(xp.patch_root(self.sink), xp.run_dir(arm.key, repo))
        patch, patch_note = _delivered_patch(
            writer, comb, None if st is None else st["delivery"]
        )
        applied = () if patch is None or comb is None else comb.applied_trial_ids
        diffs = _kept_diffs(
            writer, hyps, verdicts, [] if st is None else st["trials"], applied
        )
        for h, r in zip(hyps, ranks, strict=True):
            key, lane, parents = keys.get(h.id), _tag(h, "lane"), compound_parents(h)
            self.sink.write({**head, "experiment": IDEA_EXPERIMENT, "round": rounds.get(h.id),
                "hypothesis_id": h.id, "title": redact_keys(h.title), "lane": lane,
                "label": lane, "model": None if lane is None else lane_chain(cfg, Lane(lane))[0],
                "mechanism": _tag(h, "claimed_mechanism") if key is None else key.key.mechanism.value,
                "target": None if key is None else key.key.target.model_dump(),
                "compound": parents is not None,
                "parents": [] if parents is None else [parents.first, parents.second],
                "verdict": r.verdict, "gain_pct": r.gain_pct, "floor_pct": r.noise_floor_pct,
                "op_count": isl._op_count(verdicts.get(h.id)),
                **({} if clone is None else {"realisation": realised.get(h.id)}),
                **({} if not shadowed else {"shadow_verify": shadow.get(h.id)}),
                **({} if not stacked else {"combine": combine_row(stacked.get(h.id), owner)}),
                **({} if h.id not in diffs else {"diff": diffs[h.id]})})  # fmt: skip
        kept = [h for h in hyps if (v := verdicts.get(h.id)) is not None
                and v.outcome is VerdictOutcome.keep]  # fmt: skip
        for n, data in sorted(_by_round(events).items()):
            seeded = [d for d in data if d.get("code") == SEEDED_CALL]
            costs = [d for d in data if d.get("code") == "seeded_call_cost"]
            self.sink.write({**head, "experiment": ROUND_EXPERIMENT, "round": n,
                "trialled": sum(v == n for v in rounds.values()),
                "kept": sum(rounds.get(h.id) == n for h in kept),
                "seeds": int(math.fsum(_num(d, "seeds") for d in seeded)),
                "seeded_lanes": [str(d.get("lanes")) for d in seeded],
                "seeded_calls": len(costs),
                "seeded_cost_usd": math.fsum(_num(d, "cost_usd") for d in costs),
                "compounds": sum(d.get("code") == "compound" for d in data),
                "compounds_kept": sum(rounds.get(h.id) == n and COMPOUND_TAG in h.tags
                                      for h in kept),
                **({} if not viewed else {"lane_views": [
                    {k: d.get(k) for k in ("lane", "view_sha", "served_model")}
                    for d in data if d.get("code") == LANE_VIEW]})})  # fmt: skip
        j = isl._primary(result)
        self.sink.write({**head, "experiment": RUN_EXPERIMENT, "dispatch": self.plan.dispatch,
            "commit": commit, "cap_usd": run.cap_usd, "cost_usd": run.spent_usd,
            "window": key_window(self.sink.environ),
            "discovery_cost_usd": 0.0 if st is None else st["discovery_cost_usd"],
            "seeded_calls": 0 if st is None else st["seeded_calls"],
            "seeded_cost_usd": 0.0 if st is None else st["seeded_cost_usd"],
            "unaffordable": sum(e.data.get("code") == "discovery_unaffordable" for e in events),
            "hypotheses": len(hyps), "parked": 0 if st is None else len(st["parked"]),
            "kept": len(kept), "combined": comb is not None,
            "holds": None if comb is None else comb.holds,
            "applied": 0 if comb is None else len(comb.applied_trial_ids),
            "gain_pct": None if j is None else dx._pct(j.gain),
            "floor_pct": None if j is None else dx._pct(j.noise_floor),
            "delivered": st is not None and st["delivery"] is not None, "guard": guard,
            "base_commit": None if st is None else st.get("base_commit"),
            "patch_dir": writer.folder,
            "kept_diffs": [{"hypothesis_id": k, **d} for k, d in diffs.items()],
            "kept_diffs_note": None if diffs else xp.NO_KEEP,
            "delivered_patch": patch, "delivered_patch_note": patch_note,
            **({} if not shadowed else {"shadow_aa": aa}),
            **({} if not viewed or started is None else {"minutes_planned": run_minutes(cfg),
               "seconds_measured": round(time.monotonic() - started, 1)}),
            **({} if not stacked else {"conflicts": [[owner.get(t, t) for t in pair]
                                                     for pair in (() if comb is None else comb.conflicts)]})})  # fmt: skip


# ---------------------------------------------------------------------------
# One run
# ---------------------------------------------------------------------------


def lane_wiring(run: LiveRun) -> dict[Lane, LLMTransport]:
    """A captured transport for each lane on its own model (G1: the
    factory builds none beside an injected engine transport, and refuses)."""
    shared = role_chain(settings, "lane")
    own = [lane for lane in LANE_ROLE_LANES if lane_chain(settings, lane) != shared]
    return {lane: run.transport(lane_settings(settings, lane)) for lane in own}


def start_x2_loop(repo: OssRepo, run: LiveRun, root: Path, isolation: Isolation, *,
                  policy: GitPolicy = PRODUCTION) -> Loop:  # fmt: skip
    """``oss.start_oss_loop`` in mode ``wired`` with ``lane_wiring``'s lanes
    (it passes none, so X2's Haiku 5.5 lens would be refused) and
    ``round_trials`` a round."""
    user = oss.prepare_repo(repo, root / "user", policy=policy)
    before, project = user.snapshot(), repo.project(user.path)
    launches = LaunchLog()
    context = build_context(project, candidates=(), transport=run.transport(settings),
                            max_hypotheses_per_round=round_trials(settings),
                            role_transports=role_wiring(run, "wired"),
                            lane_transports=lane_wiring(run),
                            transport_factory=oss._no_factory, network=isolation.mode,
                            fs=isolation.mode, run=launches)  # fmt: skip
    return Loop(repo.corpus, user, before, project, repo.workload(project), (),
                launches, context, run.cap_usd, "wired")  # fmt: skip


def run_one(arm: X2Arm, repo: OssRepo, *, live: StartLive, root: Path,
            isolation: Isolation, recorder: X2Recorder,
            policy: GitPolicy = PRODUCTION) -> None:  # fmt: skip
    """The settings checked, the run capped, a fresh clone at E1's head and
    its op-count judge checked, then the whole engine run and its records;
    the measured span starts here, so it holds the clone the plan counts."""
    started = time.monotonic()
    check_settings(arm, recorder.base)
    cap = arm_cap(arm, recorder.base)
    run = live(cap)
    where = root / f"{EVERY_ARM.index(arm)}-{repo.name}"
    where.mkdir(parents=True)
    loop = start_x2_loop(repo, run, where, isolation, policy=policy)
    commit = (recorder.commits or {}).get(repo.name, "")
    if loop.user.base != commit:
        raise ValueError(
            f"{repo.name}: head {loop.user.base} is not E1's recorded {commit}"
        )
    isl.check_judges(loop)
    seen: list[EngineRunResult | None] = []
    counted = arm_settings(arm, recorder.base).IDEAS_COUNT_CONTRACT == "record"
    record = functools.partial(recorder.record, arm, repo.name, run, commit, seen,
                               clone=loop.user.path if counted else None,
                               started=started)  # fmt: skip
    run_engine(loop, run, isolation, model=recorder.base.ENGINE_MODEL, record=record)
    run.note(ip._fit(f"X2 {arm.key} {repo.name}: {run.spent_usd:.3f} of {cap:.2f} USD"))
    isl.check_op_column(seen[-1])
