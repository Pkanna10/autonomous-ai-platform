"""V-reaudit (O44): the pooled re-audit of the X1-1 re-run, no idea generation.

The re-run (O42) audits only arm A and X1-1, so its duplicate rate is lower
than run 1's by construction. Per library of X1 run 1 (41679255224), one
auditor request pools the re-run's X1-1 ideas with run 1's A, X1-0, X1-2 and
X1-3, and the report reads that audit for those four libraries.

The pool is ``ideas_probe.pool``'s own (its tiers, its round robin in
``X1_ARMS`` order, its ``AUDIT_MAX_IDEAS`` bound), over ``ArmRun`` objects
rebuilt from the results files: the rows keep no reviewer request and no
pool past the bound (run 1 hit 48 at all four libraries), so each arm is
replayed through ``ideas_probe.run_arm`` on its recorded replies and counts
(``Replay``: nothing is sent, nothing billed). A replay is trusted only when
it reproduces its own file: run 1's five arms must pool to run 1's audit
rows and the re-run's two to the re-run's, or the library is refused before
its run is admitted. The audit is ``ideas_probe.run_audit``'s one request.

Rows: ``ideas_probe.ProbeRecorder.record`` with no arm writes the audit's
rows and the auditor's reply; ``ReauditSink`` renames each ``ideas-audit``
row ``ideas-reaudit`` (so a report that does not know them reads none) and
adds both files' sha256 to every row (``run1_sha256``, ``rerun_sha256``).

Caps: a library's run is capped at the audit request's worst case
(``ideas_probe.AUDIT_USD``, 0.69, a cap rounded up to 0.70; run 1 measured
1.445 for four, at most 0.381 one), the four need 2.80; a suite cap below it, a file missing or not
the run it names (other libraries, a re-run without X1-1), is refused in the
module fixture.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from collections import defaultdict, deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Final, Literal, NoReturn

from anthropic.types.beta import BetaMessage
from pydantic import BaseModel, ConfigDict, ValidationError

from autonomous_ai_agents.clients.cost import chain
from autonomous_ai_agents.clients.transport import LLMRequest
from autonomous_ai_agents.common.config import Settings, settings
from autonomous_ai_agents.common.errors import LLMRequestError
from autonomous_ai_agents.common.models import ModelPrice, Project
from autonomous_ai_agents.common.repo_read import RepoReader
from autonomous_ai_agents.optimization.idea_types import Lane
from autonomous_ai_agents.orchestrator.factory import repo_reader

from . import ideas_probe as ip
from . import ideas_views as iv
from .conftest import LiveRun, RecordingTransport, StartLive, suite_cap
from .discovery import ceil_usd
from .discovery_io import ResultsSink
from .discovery_oss import OSS_SELECTABLE
from .oss import PRODUCTION, GitPolicy, OssRepo

REAUDIT_EXPERIMENT: Final = "ideas-reaudit"
RUN1_ENV: Final = "LIVE_REAUDIT_RUN1"
RERUN_ENV: Final = "LIVE_REAUDIT_RERUN"
RUN1_KEYS: Final = ("A", "X1-0", "X1-1", "X1-2", "X1-3")  # run 1's pooled arms
RERUN_KEYS: Final = tuple(a.key for a in ip.X1_RERUN_ARMS)  # A, X1-1
REPLAYED_ARMS: Final = tuple(a for a in ip.X1_ARMS if a.key in RUN1_KEYS)
REAUDIT_REPOS: Final = ("more_itertools", "pyparsing", "tomli", "sortedcontainers")
REAUDIT_LIBRARIES: Final = tuple(r for r in OSS_SELECTABLE if r.name in REAUDIT_REPOS)
RUN1_AUDIT_USD: Final = 1.445  # run 1's four auditor requests (41679255224)
LIBRARY_USD: Final = ceil_usd(ip.AUDIT_USD)  # one request at its worst case: 0.70
CI_NEED: Final = 3  # ci.yml: 4 x 0.70, rounded up
CLONE_MINUTES: Final = 1
REPLAY_MINUTES: Final = 1  # seven replayed arms: run 1's five took 0.3-0.9 s a library
JOB_MINUTES: Final = 30  # ci.yml's ideas-reaudit timeout


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ReplyLine(_Strict):  # ``ideas_probe._reply``'s row
    experiment: Literal["ideas-reply"]
    repo: str
    arm: str
    role: str
    label: str
    counted: int
    sent: bool
    stop_reason: str | None
    usage: tuple[int, int, int, int]
    chars: int
    shown: int
    seconds: float
    chunks: tuple[str, ...]


class AuditLine(_Strict):  # ``ProbeRecorder.record``'s audit row
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


class _Keyed(_Strict):  # the key fields of an ``ideas-probe`` or ``ideas-idea`` row
    repo: str
    arm: str
    label: str = ""
    lane: str = ""


@dataclass(frozen=True)
class Source:
    """One results file: its digest, arms by library, replies, audit rows and
    each sent lane's lens by (repo, arm, label)."""

    path: Path
    sha256: str
    arms: Mapping[str, frozenset[str]]
    replies: tuple[ReplyLine, ...]
    lanes: Mapping[tuple[str, str, str], str]
    audits: tuple[AuditLine, ...]

    def lanes_of(self, repo: str, arm: str) -> dict[str, str]:
        return {k[2]: v for k, v in self.lanes.items() if k[:2] == (repo, arm)}


def load_source(path: Path) -> Source:
    data = path.read_bytes()
    arms: defaultdict[str, set[str]] = defaultdict(set)
    replies: list[ReplyLine] = []
    lanes: dict[tuple[str, str, str], str] = {}
    audits: list[AuditLine] = []
    for n, line in enumerate(data.decode("utf-8").splitlines(), 1):
        try:
            row: object = json.loads(line)
        except json.JSONDecodeError:
            row = None
        if not isinstance(row, dict):
            raise ValueError(f"{path}:{n}: not a JSON object")
        kind = row.get("experiment")
        try:
            if kind in (ip.ROW_EXPERIMENT, ip.IDEA_EXPERIMENT):
                k = _Keyed.model_validate(
                    {f: v for f, v in row.items() if f in _Keyed.model_fields}
                )
                if kind == ip.ROW_EXPERIMENT:
                    arms[k.repo].add(k.arm)
                else:
                    lanes[(k.repo, k.arm, k.label)] = k.lane
            elif kind == ip.REPLY_EXPERIMENT:
                replies.append(ReplyLine.model_validate(row))
            elif kind == ip.AUDIT_EXPERIMENT:
                audits.append(AuditLine.model_validate(row))
        except ValidationError:
            raise ValueError(f"{path}:{n}: malformed {kind} row") from None
    return Source(
        path, hashlib.sha256(data).hexdigest(),
        {r: frozenset(a) for r, a in arms.items()}, tuple(replies), lanes, tuple(audits),
    )  # fmt: skip


def check_sources(run1: Source, rerun: Source, names: Sequence[str]) -> None:
    """Run 1 holds A and X1-0 to X1-3, the re-run exactly A and X1-1, each on
    ``names`` alone and with its own audit there; else refused."""
    for src, keys, what in ((run1, RUN1_KEYS, "X1 run 1"), (rerun, RERUN_KEYS, "the re-run")):  # fmt: skip
        if set(src.arms) != set(names):
            raise ValueError(f"{src.path.name}: {what} holds {sorted(src.arms)}, "
                             f"not {sorted(names)}")  # fmt: skip
        for name in names:
            have = src.arms[name]
            if not set(keys) <= have or (src is rerun and have != set(keys)):
                raise ValueError(f"{src.path.name}: {what} has arms {sorted(have)} "
                                 f"on {name}, not {list(keys)}")  # fmt: skip
            if not any(a.repo == name for a in src.audits):
                raise ValueError(f"{src.path.name}: {what} has no audit on {name}")


# ---------------------------------------------------------------------------
# The replay: an arm's recorded replies through ``ideas_probe.run_arm``
# ---------------------------------------------------------------------------


def exchange_keys(rows: Sequence[ReplyLine], lanes: Mapping[str, str]) -> list[str]:
    """Each recorded exchange's key, as ``request_key`` reads its request: the
    reviewer, or its lane. A sequential re-priced lane (``lane-N``) takes its
    lens from its idea rows; one with no idea, the one re-priced lens left."""
    names = {lane.value for lane in Lane}
    fixed = {"reviewer": "reviewer", "leap": Lane.leap.value, "generator": "obvious"}
    keys = [fixed.get(r.role) or (r.label if r.label in names else lanes.get(r.label))
            for r in rows]  # fmt: skip
    open_ = [r.label for r, k in zip(rows, keys, strict=True) if k is None]
    if open_:
        priced = {r.label for r in rows if r.role == "lane" and not r.sent} & names
        left = sorted(priced - {lanes[r.label] for r in rows if r.label in lanes})
        if len(open_) != 1 or len(left) != 1:
            raise ValueError(f"cannot tell which lens {', '.join(open_)} answered")
        keys[keys.index(None)] = left[0]
    return [k for k in keys if k is not None]


def request_key(request: LLMRequest) -> str:
    return "reviewer" if ip.shown_ideas(request) else ip.request_lane(request).value


class Replay:
    """One arm's recorded counts and replies, served by key in recorded order;
    a request with none left is refused and marks the replay diverged."""

    def __init__(self, rows: Sequence[ReplyLine], lanes: Mapping[str, str]) -> None:
        self.counts: defaultdict[str, deque[int]] = defaultdict(deque)
        self.sends: defaultdict[str, deque[ReplyLine]] = defaultdict(deque)
        self.diverged: list[str] = []
        for row, key in zip(rows, exchange_keys(rows, lanes), strict=True):
            self.counts[key].append(row.counted)
            if row.sent:
                self.sends[key].append(row)

    def _miss(self, key: str) -> NoReturn:
        self.diverged.append(key)
        raise LLMRequestError(f"replay: no recorded exchange left for {key}")

    def count(self, key: str) -> int:
        queue = self.counts[key]
        return queue.popleft() if queue else self._miss(key)

    def send(self, key: str, model: str) -> BetaMessage:
        queue = self.sends[key]
        row = queue.popleft() if queue else self._miss(key)
        if row.stop_reason is None:  # sent, no reply: it failed when recorded
            raise LLMRequestError(f"replay: {key} failed when recorded")
        i, o, read, write = row.usage
        return BetaMessage.model_validate({
            "id": f"replay-{row.label}", "type": "message", "role": "assistant",
            "model": model, "content": [{"type": "text", "text": "".join(row.chunks)}],
            "stop_reason": row.stop_reason, "stop_sequence": None,
            "usage": {"input_tokens": i, "output_tokens": o,
                      "cache_read_input_tokens": read, "cache_creation_input_tokens": write},
        })  # fmt: skip

    def check(self, what: str) -> None:
        left = sum(map(len, self.counts.values()))
        if self.diverged or left:
            raise ValueError(f"{what}: the replay diverged ({left} recorded "
                             f"exchange(s) unserved, {len(self.diverged)} unmatched)")  # fmt: skip


class _Served:
    """``LLMTransport`` on ``cfg``'s chain and prices, answered by the replay;
    a request counted again (``RecordingTransport``'s estimate) gets its count
    again, as the recorded rows hold one count a request."""

    def __init__(self, cfg: Settings, replay: Replay) -> None:
        self.chain, self._replay = chain(cfg), replay
        self.prices: Mapping[str, ModelPrice] = MappingProxyType(
            dict(cfg.MODEL_PRICING)
        )
        self._seen: list[tuple[LLMRequest, int]] = []

    def count_input_tokens(self, request: LLMRequest) -> int:
        n = next((n for r, n in self._seen if r is request), None)
        if n is None:
            n = self._replay.count(request_key(request))
            self._seen.append((request, n))
        return n

    def send(self, request: LLMRequest) -> BetaMessage:
        return self._replay.send(request_key(request), self.chain[0])


class _ReplayRun(LiveRun):
    """A run whose every transport is the replay: no wire, no spend."""

    def __init__(self, replay: Replay) -> None:
        super().__init__("replay", 0.0)
        self._replay = replay

    def transport(self, cfg: Settings = settings) -> RecordingTransport:
        return RecordingTransport(_Served(cfg, self._replay), self.records)


# ---------------------------------------------------------------------------
# The plan, the pool, one library
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReauditPlan:
    repos: tuple[OssRepo, ...]
    run1: Path
    rerun: Path
    facts: Path = ip.SERVICE_DIR / ip.FACTS_FIXTURE  # the facts X1 ran on
    views: Path = ip.SERVICE_DIR / ip.VIEWS_FIXTURE  # X1-3's recorded views

    def library_minutes(self) -> int:
        return CLONE_MINUTES + REPLAY_MINUTES + math.ceil(ip.AUDIT_SECONDS / 60)

    def minutes(self) -> int:
        return len(self.repos) * self.library_minutes()


def reaudit_need(plan: ReauditPlan) -> float:
    return len(plan.repos) * LIBRARY_USD


def reaudit_plan(environ: Mapping[str, str]) -> ReauditPlan:
    found = [ip.facts_path(environ, name, what) for name, what in
             ((RUN1_ENV, "X1 run 1 results"), (RERUN_ENV, "X1-1 re-run results"))]  # fmt: skip
    for path, name in zip(found, (RUN1_ENV, RERUN_ENV), strict=True):
        if path is None:
            raise ValueError(f"{name}: name the results file")
    run1, rerun = (p for p in found if p is not None)
    plan = ReauditPlan(REAUDIT_LIBRARIES, run1, rerun)
    need, cap = reaudit_need(plan), suite_cap(environ)
    if cap < need:
        raise ValueError(
            f"suite cap {cap:.2f} USD is below the re-audit's need {need:.2f}"
        )
    return plan


@dataclass
class ReauditSink(ResultsSink):
    """``ResultsSink`` marking the re-audit: ``ideas-audit`` rows renamed, both
    files' digests on every row."""

    sources: Mapping[str, str] = field(default_factory=dict)

    def write(self, record: Mapping[str, object]) -> None:
        kind = record.get("experiment")
        kind = REAUDIT_EXPERIMENT if kind == ip.AUDIT_EXPERIMENT else kind
        super().write({**record, "experiment": kind, **self.sources})


class Reaudit:
    """Both files loaded and checked, the facts and X1-3's views loaded by
    ``ProbeRecorder`` (its checks): all before any spend."""

    def __init__(self, plan: ReauditPlan, environ: Mapping[str, str]) -> None:
        self.plan = plan
        self.run1, self.rerun = load_source(plan.run1), load_source(plan.rerun)
        check_sources(self.run1, self.rerun, [r.name for r in plan.repos])
        digests = {"run1_sha256": self.run1.sha256, "rerun_sha256": self.rerun.sha256}
        self.sink = ReauditSink(environ, digests)
        probe = ip.ProbePlan(REPLAYED_ARMS, plan.repos, plan.facts, plan.views)
        self.probe = ip.ProbeRecorder(probe, self.sink)


def _replayed(src: Source, keys: Sequence[str], repo: OssRepo, facts: ip.IdeaFacts,
              reaudit: Reaudit, base: Settings,
              reader: Callable[[Project], RepoReader]) -> list[ip.ArmRun]:  # fmt: skip
    body, views = reaudit.probe.recorded[repo.name], reaudit.probe.views[repo.name]
    found: list[ip.ArmRun] = []
    for arm in (a for a in REPLAYED_ARMS if a.key in keys):
        rows = [r for r in src.replies if (r.repo, r.arm) == (repo.name, arm.key)]
        replay = Replay(rows, src.lanes_of(repo.name, arm.key))
        found.append(ip.run_arm(
            arm, _ReplayRun(replay), facts, base=base, reader=reader,
            views=views.build, workloads=(iv.recorded_workload(repo, body),),
        ))  # fmt: skip
        replay.check(f"{src.path.name} {repo.name} {arm.key}")
    pooled = ip.pool(found, facts)
    seen = [(p.arm, p.idea.title, p.idea.lane, ip.tier(p), p.in_result, p.own)
            for p in pooled]  # fmt: skip
    want = [(a.arm, a.title, a.lane, a.tier, a.in_result, a.own)
            for a in src.audits if a.repo == repo.name]  # fmt: skip
    if seen != want:
        what = "X1 run 1" if src is reaudit.run1 else "the re-run"
        raise ValueError(f"{what}: {repo.name}'s replayed pool is not its recorded "
                         f"audit's ({len(seen)} against {len(want)} ideas)")  # fmt: skip
    return found


def pooled_of(reaudit: Reaudit, repo: OssRepo, facts: ip.IdeaFacts, *,
              base: Settings = settings,
              reader: Callable[[Project], RepoReader] = repo_reader) -> list[ip.Pooled]:  # fmt: skip
    """``ideas_probe.pool`` over run 1's arms with the re-run's X1-1 in X1-1's
    place, each replay first checked against its own file's audit."""
    first = _replayed(reaudit.run1, RUN1_KEYS, repo, facts, reaudit, base, reader)
    again = _replayed(reaudit.rerun, RERUN_KEYS, repo, facts, reaudit, base, reader)
    x1_1 = next(a for a in again if a.arm.key == ip.ARM_X1_1.key)
    return ip.pool([x1_1 if a.arm.key == x1_1.arm.key else a for a in first], facts)


def run_library(
    repo: OssRepo, *, live: StartLive, root: Path, reaudit: Reaudit,
    policy: GitPolicy = PRODUCTION, base: Settings = settings,
    reader: Callable[[Project], RepoReader] = repo_reader,
    facts_of: Callable[[OssRepo, ip.FactsBody, Path, GitPolicy], ip.IdeaFacts] = ip.clone_facts,
) -> None:  # fmt: skip
    """The recorded facts on a fresh clone, the pool (refused before the run is
    admitted), then one audit, its rows and the spend guards."""
    facts = facts_of(repo, reaudit.probe.recorded[repo.name], root / "user", policy)
    began = time.monotonic()
    pooled = pooled_of(reaudit, repo, facts, base=base, reader=reader)
    run = live(LIBRARY_USD)
    try:
        run.note(f"REAUDIT {repo.name}: {len(pooled)} pooled, replayed in "
                 f"{time.monotonic() - began:.1f} s")  # fmt: skip
        audit = ip.run_audit(pooled, run, facts, base=base, reader=reader)
        reaudit.probe.record(repo.name, [], pooled, audit, run)
        ip.check_spend(run, [], audit)
    except BaseException as exc:
        run.note(
            f"IDEAS {repo.name}: breach: {type(exc).__name__}: {exc}"[: ip.NOTE_CHARS]
        )
        raise
