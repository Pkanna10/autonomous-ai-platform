"""V-O40: the pooled marker-feasible ranking (O40, O41; STATUS 2026-11-03), the
one implementation the execution slice (``ideas_slice``: sqlparse, pyparsing,
tomli, sortedcontainers) and the ``ideas-pool`` suite (the other four of the 8
development libraries, no engine trial) both run.

The pool, per library: every returned lens-lane idea of X1-0 to X1-3 (never
S1, the leap, a rule-relaxing lane, arm A or X1-4; audited or not, any class),
read from Vd's ``ideas-idea`` rows, its class from its lane reply. Its id is a
hash of its row key, so it carries no configuration, lane or model.

The rankers, from Vb's verdict (never a constant): the candidate O37 chose
ranks the pool less its own model's ideas (O39: X1-1's Opus 5.5 lens, listed
apart, not ranked); the other candidate ranks the whole pool, each row saying
whether its marker passed O37 (Opus 5 did not: unvalidated). No candidate
past O37: no ranking.

The tournament (O41): the ideas, in sorted id order, are split into
``ceil(n / SET_SIZE)`` sets as equal as possible; each set is one Vb request
(``ideas_marker.ask``: blind, titles and class with the hot code, shown in an
order shuffled by a recorded seed, counted, capped at its own worst case); the
top ``ADVANCE`` of each set advance; rounds repeat until the ideas fit one
set, whose order gives the top ``TOP``. So every request stays at the set size
the marker was validated on (Vb's sets: ``VB_SETS``). A set of one is not
sent; a set with no usable order stops that ranking (no top). Recorded: a row
per set (``ideas-pool-set``) and per library and marker (``ideas-pool-result``).

Caps: a ranking's run is capped at its requests' worst cases; a need is
priced on ``POOL_BOUND`` (four results of at most ``GENERATOR_N +
IDEAS_PORTFOLIO_MAX`` ideas, ``idea_pipeline``'s bound), and a loaded pool past
that price is refused before any spend, as is a need past the suite cap.
"""

from __future__ import annotations

import functools
import hashlib
import json
import math
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel

from autonomous_ai_agents.common.config import Settings, settings
from autonomous_ai_agents.optimization.idea_dedupe import _ReplyIdea
from autonomous_ai_agents.optimization.idea_types import LENS_LANES

from . import discovery_oss as dx
from . import ideas_marker as im
from . import ideas_probe as ip
from .conftest import StartLive, redact_keys, suite_cap
from .discovery import ceil_usd
from .discovery_io import ResultsSink
from .ideas_marker import hot_code
from .ideas_probe import _chunks, _fit, _Strict
from .oss import PRODUCTION, GitPolicy, OssRepo, clone_pinned

POOL_CONFIGS: Final = ("X1-0", "X1-1", "X1-2", "X1-3")
LENSES: Final = frozenset(lane.value for lane in LENS_LANES)
SET_SIZE: Final = 6  # O41: about six; Vb validated sets of 3 to 8 ideas
VB_SETS: Final = (3, 8, 4.6)  # Vb's 48 scored sets: fewest, most, mean ideas
ADVANCE: Final = 2
TOP: Final = 3
POOL_BOUND: Final = len(POOL_CONFIGS) * (
    settings.GENERATOR_N + settings.IDEAS_PORTFOLIO_MAX
)
REQUEST_SECONDS: Final = 30  # Opus 5 measured 5.4 s a ~4,070-token set: 5x
CLONE_MINUTES: Final = 1
JOB_MINUTES: Final = 60  # ci.yml's ideas-pool timeout
POOL_REPOS: Final = ("more_itertools", "mistune", "markdown", "idna")
POOL_LIBRARIES: Final = tuple(
    next(r for r in dx.OSS_SELECTABLE if r.name == n) for n in POOL_REPOS
)
IDEAS_ENV: Final = "LIVE_POOL_IDEAS"
MARKER_ENV: Final = "LIVE_POOL_MARKER"
SET_EXPERIMENT: Final = "ideas-pool-set"
RESULT_EXPERIMENT: Final = "ideas-pool-result"
MARKER_TITLE_MAX: Final = 300  # Vb's ``RankRow.title`` bound: longer is clipped
NO_DECISION: Final = im.Decision(None, im.NO_MARKER, (), ())

# ---------------------------------------------------------------------------
# X1's rows, strictly (the slice reads them too)
# ---------------------------------------------------------------------------


class IdeaRow(_Strict):
    experiment: Literal["ideas-idea"]
    repo: str
    arm: str
    lane: str
    label: str
    model: str
    position: int
    title: str
    change: str
    returned: bool
    proposal: bool
    relaxes: str | None
    mechanism: str | None
    cells: tuple[str, ...]
    path: str | None
    target: dict[str, int] | None


class ReplyRow(_Strict):
    experiment: Literal["ideas-reply"]
    repo: str
    arm: str
    role: str
    label: str
    counted: int
    sent: bool
    stop_reason: str | None
    usage: tuple[int, ...]
    chars: int
    shown: int
    seconds: float
    chunks: tuple[str, ...]


class Verdict(_Strict):  # Vb's ``ideas-marker-verdict`` row, as ``finish`` writes it
    experiment: Literal["ideas-marker-verdict"]
    chosen: str | None
    reason: str
    passed: tuple[str, ...]
    baseline_ties: tuple[str, ...]
    positives: int
    comparable: int
    generator: dict[str, float | int | None]
    bar: dict[str, float | int]


def check_verdict(path: Path, decision: im.Decision) -> im.Decision:
    """The scorer's decision, refused when Vb's verdict row says otherwise."""
    rows = [Verdict.model_validate_json(x)
            for x in path.read_text(encoding="utf-8").splitlines()
            if f'"experiment": "{im.VERDICT_EXPERIMENT}"' in x]  # fmt: skip
    if len(rows) > 1:
        raise ValueError(f"{path}: {im.VERDICT_EXPERIMENT} row twice")
    if rows and (rows[0].chosen, rows[0].passed) != (decision.chosen, decision.passed):
        raise ValueError(f"{path}: its {im.VERDICT_EXPERIMENT} row disagrees with "
                         "the score of its reply rows")  # fmt: skip
    return decision


def paths(environ: Mapping[str, str], name: str, what: str) -> tuple[Path, ...]:
    raw = [x for x in environ.get(name, "").split(",") if x]
    found = tuple(Path(x) if Path(x).is_absolute() else ip.SERVICE_DIR / x for x in raw)
    missing = [str(p) for p in found if not p.is_file()]
    if missing:
        raise ValueError(f"{name}: no {what} at {missing[0]!r}")
    if len(set(found)) != len(found):
        raise ValueError(f"{name}: a results file named twice")
    return found


class _Keyed(BaseModel):
    repo: str


def read_rows(
    files: Iterable[Path], kinds: Mapping[str, type[_Strict]]
) -> dict[str, list[_Strict]]:
    """The rows of ``kinds`` by library, a library refused in two files."""
    rows: dict[str, list[_Strict]] = {}
    owner: dict[str, Path] = {}
    for path in files:
        for line in path.read_text(encoding="utf-8").splitlines():
            kind = next((k for k in kinds if f'"experiment": "{k}"' in line), None)
            if kind is None:
                continue
            row = kinds[kind].model_validate_json(line)
            repo = _Keyed.model_validate(row, from_attributes=True).repo
            if owner.setdefault(repo, path) != path:
                raise ValueError(f"{repo}: recorded in {owner[repo]} and {path}")
            rows.setdefault(repo, []).append(row)
    return rows


def reply_texts(repo: str, rows: Iterable[_Strict]) -> dict[tuple[str, str], str]:
    texts: dict[tuple[str, str], str] = {}
    for r in rows:
        if isinstance(r, ReplyRow) and r.sent and r.role in ("lane", "leap"):
            if (r.arm, r.label) in texts:
                raise ValueError(f"{repo} {r.arm} {r.label}: two sent replies")
            texts[(r.arm, r.label)] = "".join(r.chunks)
    return texts


def reply_item(row: IdeaRow, texts: Mapping[tuple[str, str], str]) -> _ReplyIdea:
    """The lane reply's whole idea the row names, refused when it is not."""
    items = ip.reply_ideas(texts.get((row.arm, row.label), ""), ip._no_text)
    if not 0 < row.position <= len(items) or (
        redact_keys(items[row.position - 1][0].title) != row.title
    ):
        raise ValueError(f"{row.repo} {row.arm} {row.label} #{row.position}: "
                         "not the idea its reply holds")  # fmt: skip
    return items[row.position - 1][0]


def idea_id(row: IdeaRow) -> str:
    """A hash of the row key: no configuration, lane or model readable in it."""
    key = json.dumps([row.repo, row.arm, row.label, row.position]).encode()
    return "p" + hashlib.sha256(key).hexdigest()[:12]


@dataclass(frozen=True)
class PoolIdea:
    row: IdeaRow
    change_class: str

    @property
    def id(self) -> str:
        return idea_id(self.row)

    def key(self) -> dict[str, object]:
        r = self.row
        return {"arm": r.arm, "label": r.label, "position": r.position}


def pooled(row: IdeaRow) -> bool:
    return (row.arm in POOL_CONFIGS and row.lane in LENSES and row.returned
            and not row.proposal)  # fmt: skip


def members(repo: str, rows: Sequence[_Strict]) -> tuple[PoolIdea, ...]:
    """The library's pool; a library with no idea to pool is refused, never a
    zero-count result."""
    if not any(isinstance(r, IdeaRow) for r in rows):
        raise ValueError(f"{repo}: no {ip.IDEA_EXPERIMENT} rows in the X1 results")
    texts = reply_texts(repo, rows)
    found = [PoolIdea(r, reply_item(r, texts).change_class)
             for r in rows if isinstance(r, IdeaRow) and pooled(r)]  # fmt: skip
    if len({i.id for i in found}) != len(found):
        raise ValueError(f"{repo}: an ideas-idea row recorded twice")
    if not found:
        raise ValueError(f"{repo}: no returned lens-lane idea of {POOL_CONFIGS}")
    return tuple(sorted(found, key=lambda i: i.id))


def load_pools(
    files: Sequence[Path], repos: Sequence[str]
) -> dict[str, tuple[PoolIdea, ...]]:
    kinds: dict[str, type[_Strict]] = {ip.IDEA_EXPERIMENT: IdeaRow,
                                       ip.REPLY_EXPERIMENT: ReplyRow}  # fmt: skip
    rows = read_rows(files, kinds)
    return {repo: members(repo, rows.get(repo, [])) for repo in repos}


# ---------------------------------------------------------------------------
# The rankers and the tournament
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Ranker:
    marker: im.Marker
    validated: bool  # Vb's verdict: it passed O37
    ideas: tuple[PoolIdea, ...]  # what it ranks
    apart: tuple[PoolIdea, ...]  # its own model's ideas: never ranked by it


def rankers(pool: Sequence[PoolIdea], decision: im.Decision) -> tuple[Ranker, ...]:
    chosen = next((m for m in im.MARKERS if m.key == decision.chosen), None)
    if chosen is None:
        return ()
    own = tuple(i for i in pool if i.row.model == chosen.model)
    first = Ranker(chosen, chosen.key in decision.passed,
                   tuple(i for i in pool if i not in own), own)  # fmt: skip
    return (first, *(Ranker(m, m.key in decision.passed, tuple(pool), ())
                     for m in im.MARKERS if m != chosen))  # fmt: skip


def sizes(n: int) -> tuple[int, ...]:
    """``ceil(n / SET_SIZE)`` set sizes, as equal as possible."""
    k = math.ceil(n / SET_SIZE)
    return tuple(n // k + (s < n % k) for s in range(k)) if k else ()


def split(ids: Iterable[str]) -> tuple[tuple[str, ...], ...]:
    ordered = sorted(ids)
    out, at = [], 0
    for size in sizes(len(ordered)):
        out.append(tuple(ordered[at : at + size]))
        at += size
    return tuple(out)


def rounds(n: int) -> tuple[tuple[int, ...], ...]:
    out = []
    while n:
        out.append(s := sizes(n))
        n = 0 if len(s) == 1 else sum(min(ADVANCE, x) for x in s)
    return tuple(out)


def requests(n: int) -> int:
    return sum(x > 1 for r in rounds(n) for x in r)


@dataclass(frozen=True)
class SetResult:
    round: int
    index: int
    of: int  # the sets in its round: 1 is the final
    ids: tuple[str, ...]
    order: tuple[str, ...] | None  # most likely first; None: no usable order

    @property
    def advanced(self) -> tuple[str, ...]:
        return () if self.order is None or self.of == 1 else self.order[:ADVANCE]


Rank = Callable[[int, int, int, tuple[str, ...]], tuple[str, ...] | None]


def tournament(
    ids: Iterable[str], rank: Rank
) -> tuple[tuple[SetResult, ...], tuple[str, ...] | None]:
    """Every set's result and the final set's top ``TOP`` (None: stopped)."""
    done: list[SetResult] = []
    current, rnd = sorted(ids), 1
    while current:
        sets = split(current)
        for k, shown in enumerate(sets, 1):
            order = shown if len(shown) == 1 else rank(rnd, k, len(sets), shown)
            if order is not None and sorted(order) != list(shown):
                raise ValueError(f"round {rnd} set {k}: not a permutation of its ideas")
            done.append(SetResult(rnd, k, len(sets), shown, order))
            if order is None:
                return tuple(done), None
        if len(sets) == 1:
            return tuple(done), (done[-1].order or ())[:TOP]
        current = sorted(x for s in done[-len(sets) :] for x in s.advanced)
        rnd += 1
    return (), ()


def counts(top: Sequence[str], pool: Iterable[PoolIdea]) -> dict[str, int]:
    arm = {i.id: i.row.arm for i in pool}
    found = Counter(arm[x] for x in top)
    return {c: found[c] for c in POOL_CONFIGS}


def pool_cap(found: Iterable[Ranker]) -> float:
    return ceil_usd(math.fsum(requests(len(r.ideas)) * im.request_worst(r.marker)
                              for r in found))  # fmt: skip


def library_usd() -> float:
    """A library's priced worst case: both markers on a pool at the bound."""
    return ceil_usd(requests(POOL_BOUND) * im.set_usd())


def library_minutes() -> int:
    return math.ceil(len(im.MARKERS) * requests(POOL_BOUND) * REQUEST_SECONDS / 60)


def check_priced(
    pools: Mapping[str, Sequence[PoolIdea]], decision: im.Decision
) -> None:
    for repo, pool in pools.items():
        if pool_cap(rankers(pool, decision)) > library_usd():
            raise ValueError(f"{repo}: the pool of {len(pool)} ideas is past the "
                             f"{POOL_BOUND} its need was priced on: refused before "
                             "any spend")  # fmt: skip


# ---------------------------------------------------------------------------
# One library on the wire, recorded
# ---------------------------------------------------------------------------


def pool_set(repo: str, name: str, ideas: Sequence[PoolIdea]) -> im.RankSet:
    """Vb's request shape: title and class, never an outcome, a configuration,
    a lane or a model (``name`` seeds the shuffle and is never shown)."""
    rows = tuple(
        im.RankRow(run_id=0, arm=name, change_class=i.change_class,
                   experiment="E5-oss-ab-rank", gain_pct=None, guard="unmeasured",
                   noise_floor_pct=None, rank=k, rep=1, repo=repo,
                   title=i.row.title[:MARKER_TITLE_MAX], verdict="unmeasured")
        for k, i in enumerate(ideas, 1)
    )  # fmt: skip
    return im.RankSet(repo, 1, name, rows)


def rank_library(repo: str, pool: Sequence[PoolIdea], decision: im.Decision, *,
                 live: StartLive, hot: Callable[[], im.HotCode], sink: ResultsSink,
                 base: Settings = settings) -> None:  # fmt: skip
    """Each ranker's tournament on one run capped at every request's worst case."""
    if not pool:  # the recorders refuse it on load; a caller's pool too
        raise ValueError(f"{repo}: no idea to pool")
    found = rankers(pool, decision)
    cap = pool_cap(found)
    run = live(cap) if cap else None
    for r in found:
        by_id = {i.id: i for i in r.ideas}
        where = {"repo": repo, "marker": r.marker.key, "model": r.marker.model,
                 "validated": r.validated}  # fmt: skip

        def rank(rnd: int, k: int, of: int, ids: tuple[str, ...], r: Ranker = r,
                 by_id: dict[str, PoolIdea] = by_id,
                 where: dict[str, object] = where) -> tuple[str, ...] | None:  # fmt: skip
            assert run is not None  # a set of two or more: priced in the cap
            s = pool_set(repo, f"{r.marker.key}-r{rnd}-s{k}", [by_id[x] for x in ids])
            reply = im.ask(r.marker, run, s, hot(), base=base)
            e = reply.exchange
            order = None if reply.scores is None else tuple(
                x for _, x in sorted(zip(reply.scores, ids, strict=True), reverse=True))  # fmt: skip
            sink.write({
                "experiment": SET_EXPERIMENT, **where, "round": rnd, "set": k, "of": of,
                "name": s.arm, "ids": list(ids), "seed": f"{im.SHUFFLE_SEED}:{s.key}",
                "shown": [ids[n] for n in im.shown_order(s)],
                "order": None if order is None else list(order),
                "advanced": [] if order is None or of == 1 else list(order[:ADVANCE]),
                "error": None if reply.error is None else _fit(redact_keys(reply.error)),
                "cost_usd": reply.cost_usd, "counted": 0 if e is None else e.counted,
                "sent": e is not None and e.sent,
                "chunks": _chunks("" if e is None else redact_keys(e.reply)),
            })  # fmt: skip
            return order

        sets, top = tournament(by_id, rank)
        sink.write({
            "experiment": RESULT_EXPERIMENT, **where,
            "members": [{"id": i.id, **i.key()} for i in r.ideas],
            "apart": [i.key() for i in r.apart],
            "top": None if top is None else list(top),
            "counts": None if top is None else counts(top, r.ideas),
            "requests": sum(len(s.ids) > 1 for s in sets),
            "rounds": max((s.round for s in sets), default=0),
            "max_shown": max((len(s.ids) for s in sets), default=0),
        })  # fmt: skip


def hot_of(repo: OssRepo, root: Path, policy: GitPolicy) -> Callable[[], im.HotCode]:
    """The pinned clone's hot code, cloned on the first call only."""

    @functools.cache
    def get() -> im.HotCode:
        dest = root / f"hot-{repo.name}"
        clone_pinned(repo.url, repo.tag, repo.commit, dest, policy=policy)
        return hot_code(repo, dest)

    return get


# ---------------------------------------------------------------------------
# The ideas-pool suite: the four libraries outside the slice, no engine trial
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PoolPlan:
    repos: tuple[OssRepo, ...]
    ideas: tuple[Path, ...] = ()  # X1's results files
    marker: Path | None = None  # Vb's results file

    def minutes(self) -> int:
        return len(self.repos) * (CLONE_MINUTES + library_minutes())


def pool_need(plan: PoolPlan) -> float:
    return len(plan.repos) * library_usd()


def pool_plan(environ: Mapping[str, str]) -> PoolPlan:
    marker = paths(environ, MARKER_ENV, "marker results")
    if len(marker) > 1:
        raise ValueError(f"{MARKER_ENV}: Vb's one results file")
    plan = PoolPlan(POOL_LIBRARIES, paths(environ, IDEAS_ENV, "X1 results"),
                    (*marker, None)[0])  # fmt: skip
    need, cap = pool_need(plan), suite_cap(environ)
    if cap < need:
        raise ValueError(f"suite cap {cap:.2f} USD is below the pool's need {need:.2f}")
    return plan


@dataclass
class PoolRecorder:
    plan: PoolPlan
    sink: ResultsSink
    pools: dict[str, tuple[PoolIdea, ...]] | None = None
    decision: im.Decision | None = None

    def __post_init__(self) -> None:
        if self.pools is None and not self.plan.ideas:
            raise ValueError(f"{IDEAS_ENV}: name X1's results files")
        if self.decision is None and self.plan.marker is None:
            raise ValueError(f"{MARKER_ENV}: name Vb's results file")
        if self.pools is None:
            self.pools = load_pools(self.plan.ideas, [r.name for r in self.plan.repos])
        if self.decision is None and self.plan.marker is not None:
            marker = self.plan.marker
            self.decision = check_verdict(marker, im.score_results(marker)[1])
        check_priced(self.pools, self.decision or NO_DECISION)


def run_library(repo: OssRepo, *, live: StartLive, root: Path, recorder: PoolRecorder,
                policy: GitPolicy = PRODUCTION, base: Settings = settings) -> None:  # fmt: skip
    rank_library(repo.name, (recorder.pools or {}).get(repo.name, ()),
                 recorder.decision or NO_DECISION, live=live,
                 hot=hot_of(repo, root, policy), sink=recorder.sink, base=base)  # fmt: skip
