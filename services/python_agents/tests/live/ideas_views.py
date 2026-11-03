"""Va: the ``ideas-views`` suite, the views pass (idea-lab spec 6.1, O36.3).

A recorded hotspot holds no caller graph or argument shape, so the lane
views (G2) cannot come from E1's ``ideas-facts`` rows alone. Per library of
those facts (``FACTS_FIXTURE``, the 8 development libraries), with no
request at all:

- a fresh clone at E1's recorded head (``ideas_probe.clone_facts``: the
  corpus's hardened ``prepare_repo``, the head checked), then the pinned
  tag's history fetched to ``HISTORY_DEPTH`` commits by the same scratch
  git (``deepen``): the clone is depth 1, which would leave the history
  view nothing to read. Only the tag's own ancestors are fetched, and
  ``HEAD`` must not move, so no commit after the pin can be read (G2's
  contamination guard holds on the objects, not only on the walk).
- every view of ``IDEA_VIEWS`` built by ``idea_context.build_view`` from a
  ``ViewSource`` as the pipeline builds it (the real ``repo_reader``, the
  recorded commit, hotspots and protected patterns, no read-deny as E1,
  ``IdeaReadLimits.from_settings``). E1 recorded no workload: the corpus
  defines one per library (``OssRepo.workload``), so it is derived with
  the profile's one workload id; it names only the benchmark script, so
  the input-shape view shows its argv and no input file.
- one row per (library, view), ``ideas-views``: the view's documents,
  facts and notes, the limits and a digest of the source, as chunked JSON
  with keys redacted, like ``ideas-facts``.

``load_views`` reads the rows back strictly; ``RecordedViews.build`` has
``build_view``'s signature, so a pipeline seam that takes a view builder
can use a recorded view instead of building one (it refuses a source
other than the one recorded). Need 0 USD: the run's cap is 0 and nothing
may be sent; a breach is noted on the run, then raised.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Literal

from autonomous_ai_agents.clients.structured import Fence
from autonomous_ai_agents.common.config import (
    IDEA_VIEWS,
    IdeaView,
    Settings,
    settings,
)
from autonomous_ai_agents.common.models import Project, Workload
from autonomous_ai_agents.common.repo_read import RepoReader
from autonomous_ai_agents.optimization.idea_context import (
    HISTORY_WALK_MAX,
    HistoryReader,
    IdeaReadLimits,
    LaneView,
    ViewSource,
    build_view,
)
from autonomous_ai_agents.optimization.idea_types import CodeContext
from autonomous_ai_agents.orchestrator.factory import repo_reader

from .conftest import LiveRun, redact_keys
from .discovery_io import ResultsSink, cells, write_markdown
from .discovery_oss import OSS_SELECTABLE
from .ideas_probe import (
    CLONE_MINUTES,
    FACTS_FIXTURE,
    SERVICE_DIR,
    FactsBody,
    _chunks,
    _fit,
    _Strict,
    clone_facts,
    load_facts,
)
from .oss import (
    PRODUCTION,
    CloneRefusedError,
    GitPolicy,
    OssRepo,
    _scratch_git,
    check_pin,
)

VIEWS_EXPERIMENT: Final = "ideas-views"
VIEWS_RUN_CAP_USD: Final = 0.0  # no Claude request
VIEWS_JOB_MINUTES: Final = 30  # ci.yml's ideas-views timeout
VIEW_MINUTES: Final = 1  # six views of one library: seconds, with room
HISTORY_DEPTH: Final = HISTORY_WALK_MAX  # the walk reads no more commits


def views_need() -> float:
    """What a views dispatch asks the ledger for: nothing."""
    return VIEWS_RUN_CAP_USD


@dataclass(frozen=True)
class ViewsPlan:
    repos: tuple[OssRepo, ...]
    facts: Mapping[str, FactsBody]

    def minutes(self) -> int:
        return len(self.repos) * (CLONE_MINUTES + VIEW_MINUTES)


def views_plan(path: Path = SERVICE_DIR / FACTS_FIXTURE) -> ViewsPlan:
    """E1's facts, every library a pinned OSS one, within the job's minutes
    (in the module fixture, before any clone)."""
    facts = load_facts(path)
    if not facts:
        raise ValueError(f"{path}: no recorded facts")
    known = [repo.name for repo in OSS_SELECTABLE]
    foreign = sorted(set(facts) - set(known))
    if foreign:
        raise ValueError(
            f"facts for what is not a pinned OSS library: {', '.join(foreign)}"
        )
    plan = ViewsPlan(tuple(r for r in OSS_SELECTABLE if r.name in facts), facts)
    if plan.minutes() > VIEWS_JOB_MINUTES:
        raise ValueError(f"{len(plan.repos)} libraries take about {plan.minutes()} "
                         f"minutes, past the {VIEWS_JOB_MINUTES}-minute job")  # fmt: skip
    return plan


# ---------------------------------------------------------------------------
# The views of one library
# ---------------------------------------------------------------------------


def recorded_workload(repo: OssRepo, body: FactsBody) -> Workload:
    """The corpus's workload under the id E1's profile recorded."""
    ids = sorted({h.workload_id for h in body.hotspots})
    if len(ids) != 1:
        raise ValueError(f"{repo.name}: the profile names {len(ids)} workloads, "
                         "not the corpus's one")  # fmt: skip
    return Workload(id=ids[0], project_id=body.project.id, name=repo.name,
                    command=repo.workload_argv)  # fmt: skip


def deepen(
    repo: OssRepo,
    dest: Path,
    head: str,
    *,
    policy: GitPolicy,
    depth: int = HISTORY_DEPTH,
) -> int:
    """The pinned tag's history to ``depth`` commits into the clone at
    ``dest`` (argv only, the corpus's scratch git); ``HEAD`` stays ``head``.
    The number of commits ``head`` now reaches."""
    check_pin(repo.url, repo.tag, repo.commit, policy)
    with _scratch_git(dest, policy, None) as git:
        git("fetch", "-q", f"--depth={depth}", "--no-tags", "--no-recurse-submodules",
            "--", repo.url, f"refs/tags/{repo.tag}")  # fmt: skip
        fetched = git(
            "rev-parse", "--verify", "--end-of-options", "FETCH_HEAD^{commit}"
        )
        (dest / ".git" / "FETCH_HEAD").unlink()
        if fetched != repo.commit:
            raise CloneRefusedError(
                f"tag {repo.tag} is {fetched}, not the pinned {repo.commit}"
            )
        now = git("rev-parse", "--verify", "--end-of-options", "HEAD^{commit}")
        if now != head:
            raise CloneRefusedError(f"HEAD is {now}, not the recorded {head}")
        return int(git("rev-list", "--count", head))


def source_digest(source: ViewSource) -> str:
    """What decides a view besides the commit and the limits: the profile,
    the patterns and the workloads (the input shape is theirs; a fresh id or
    timestamp decides no view and would change the bytes)."""
    data = {"hotspots": [h.model_dump(mode="json") for h in source.hotspots],
            "protected": list(source.protected), "read_deny": list(source.read_deny),
            "workloads": [w.model_dump(mode="json", exclude={"id", "created_at"})
                          for w in source.workloads]}  # fmt: skip
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


class ViewBody(_Strict):
    view: IdeaView
    commit: str
    run_id: str
    source_sha256: str
    limits: IdeaReadLimits
    commits: int  # the commits the history walk could reach
    context: CodeContext | None  # None: build_view returned no view
    facts: tuple[str, ...]
    notes: tuple[str, ...]


class _ViewLine(_Strict):
    experiment: Literal["ideas-views"]
    repo: str
    view: IdeaView
    built: bool
    chunks: tuple[str, ...]


@dataclass(frozen=True)
class ViewRow:
    repo: str
    body: ViewBody

    def record(self) -> dict[str, object]:
        text = redact_keys(self.body.model_dump_json())
        return {"experiment": VIEWS_EXPERIMENT, "repo": self.repo,
                "view": self.body.view, "built": self.body.context is not None,
                "chunks": _chunks(text)}  # fmt: skip


def view_source(
    repo: OssRepo,
    body: FactsBody,
    dest: Path,
    *,
    policy: GitPolicy = PRODUCTION,
    base: Settings = settings,
    reader: Callable[[Project], RepoReader] = repo_reader,
    workloads: Sequence[Workload] | None = None,
) -> tuple[ViewSource, int]:
    """A fresh clone at the recorded head with its history, and the
    ``ViewSource`` the pipeline would build there; the commits reached."""
    facts = clone_facts(repo, body, dest, policy)
    commits = deepen(repo, dest, body.commit, policy=policy)
    git = reader(facts.facts.project)
    found = (recorded_workload(repo, body),) if workloads is None else tuple(workloads)
    source = ViewSource(
        git, body.commit, body.hotspots, Fence.new(), body.protected, (),
        IdeaReadLimits.from_settings(base), found,
        git if isinstance(git, HistoryReader) else None,
    )  # fmt: skip
    return source, commits


def views_rows(
    repo: OssRepo,
    body: FactsBody,
    dest: Path,
    *,
    policy: GitPolicy = PRODUCTION,
    base: Settings = settings,
    reader: Callable[[Project], RepoReader] = repo_reader,
    workloads: Sequence[Workload] | None = None,
) -> list[ViewRow]:
    """Every view of ``IDEA_VIEWS`` at the recorded commit, one row each."""
    source, commits = view_source(repo, body, dest, policy=policy, base=base,
                                  reader=reader, workloads=workloads)  # fmt: skip
    digest = source_digest(source)
    rows: list[ViewRow] = []
    for name in IDEA_VIEWS:
        notes: list[str] = []
        view = build_view(name, source, notes)
        rows.append(ViewRow(repo.name, ViewBody(
            view=name, commit=body.commit, run_id=body.run_id, source_sha256=digest,
            limits=source.limits, commits=commits,
            context=None if view is None else view.context,
            facts=() if view is None else view.facts, notes=tuple(notes),
        )))  # fmt: skip
    return rows


# ---------------------------------------------------------------------------
# The loader: what the pipeline needs to use a recorded view
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RecordedViews:
    """One library's recorded views, every one of ``IDEA_VIEWS``."""

    repo: str
    commit: str
    run_id: str
    source_sha256: str
    limits: IdeaReadLimits
    bodies: Mapping[IdeaView, ViewBody]

    def build(
        self, name: IdeaView, source: ViewSource, notes: list[str]
    ) -> LaneView | None:
        """``build_view`` from the record: its view and notes, for exactly
        the source it was built from (commit, limits, profile, patterns,
        workloads)."""
        digest = source_digest(source)
        if (source.commit, source.limits, digest) != (
            self.commit, self.limits, self.source_sha256
        ):  # fmt: skip
            raise ValueError(f"{self.repo}: view {name} asked for a source that is "
                             "not the source recorded")  # fmt: skip
        body = self.bodies[name]
        notes.extend(body.notes)
        return (
            None if body.context is None else LaneView(name, body.context, body.facts)
        )


def load_views(
    path: Path, facts: Mapping[str, FactsBody] | None = None
) -> dict[str, RecordedViews]:
    """The ``ideas-views`` rows of a results file, by library, strictly:
    each (library, view) once, every view, one source per library, and
    (with ``facts``) the commit and run of the facts recorded for it."""
    found: dict[str, dict[IdeaView, ViewBody]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if f'"experiment": "{VIEWS_EXPERIMENT}"' not in line:
            continue
        record = _ViewLine.model_validate_json(line)
        body = ViewBody.model_validate_json("".join(record.chunks))
        where = f"{path}: {record.repo}"
        if body.view != record.view:
            raise ValueError(f"{where}: a {record.view} row holds the {body.view} view")
        if record.built != (body.context is not None):
            raise ValueError(f"{where}: {record.view} says built {record.built}")
        views = found.setdefault(record.repo, {})
        if record.view in views:
            raise ValueError(f"{where}: view {record.view} recorded twice")
        views[record.view] = body
    loaded: dict[str, RecordedViews] = {}
    for repo, views in found.items():
        missing = [name for name in IDEA_VIEWS if name not in views]
        if missing:
            raise ValueError(f"{path}: {repo}: views missing: {', '.join(missing)}")
        keys = {(b.commit, b.run_id, b.source_sha256, b.limits) for b in views.values()}
        if len(keys) != 1:
            raise ValueError(f"{path}: {repo}: the views disagree on their source")
        ((commit, run_id, digest, limits),) = keys
        if facts is not None:
            recorded = facts.get(repo)
            if recorded is None:
                raise ValueError(f"{path}: no recorded facts for {repo}")
            if (recorded.commit, recorded.run_id) != (commit, run_id):
                raise ValueError(f"{path}: {repo}'s views are not the recorded facts'")
        loaded[repo] = RecordedViews(repo, commit, run_id, digest, limits, views)
    return loaded


# ---------------------------------------------------------------------------
# The recorder and one library
# ---------------------------------------------------------------------------


@dataclass
class ViewsRecorder:
    plan: ViewsPlan
    sink: ResultsSink
    rows: list[ViewRow] = field(default_factory=list)

    def record(self, repo: str, rows: Sequence[ViewRow], run: LiveRun) -> None:
        for row in rows:
            self.rows.append(row)
            self.sink.write(row.record())
        built = sum(row.body.context is not None for row in rows)
        commits = max((row.body.commits for row in rows), default=0)
        run.note(_fit(f"VIEWS {repo}: {built} of {len(rows)} view(s) built, "
                      f"{commits} commit(s) read"))  # fmt: skip

    def finish(self, echo: Callable[[str], None]) -> None:
        if not self.rows:
            return
        lines = ["## Ideas views (X1's views pass, no request)", "",
                 "| repo | view | built | documents | facts | notes |",
                 "| --- | --- | --- | ---: | ---: | ---: |"]  # fmt: skip
        for r in self.rows:
            b = r.body
            shown = 0 if b.context is None else len(b.context.documents)
            lines.append(cells([r.repo, b.view, "yes" if b.context else "no", shown,
                                len(b.facts), len(b.notes)]))  # fmt: skip
        write_markdown("Ideas views", "\n".join(lines), self.sink.environ, echo)


def check_no_request(run: LiveRun) -> None:
    """Nothing was sent, recorded or spent."""
    assert run.records == [] and run.capture.exchanges == [], "a request was sent"
    assert run.spent_usd == 0.0 <= run.cap_usd


def run_views(
    repo: OssRepo,
    *,
    run: LiveRun,
    root: Path,
    recorder: ViewsRecorder,
    policy: GitPolicy = PRODUCTION,
) -> None:
    """One library's views, recorded, then guarded; a breach is noted on
    the run, then raised."""
    try:
        body = recorder.plan.facts[repo.name]
        rows = views_rows(repo, body, root / "user", policy=policy)
        recorder.record(repo.name, rows, run)
        check_no_request(run)
    except BaseException as exc:
        run.note(_fit(f"VIEWS {repo.name}: breach: {type(exc).__name__}: {exc}"))
        raise
