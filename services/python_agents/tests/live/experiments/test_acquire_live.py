"""Package-acquisition feasibility probe for Step 3b (live, CI only).

Part A (``test_acquire_policy``, no API spend: its run is admitted with a
cap of 0 so its notes reach the cost table): every package of
``acquire_packages.json`` (40 performance packages, 10 decoys) through the
automatic policy (``acquire.Assessor``) on pypi.org and api.osv.dev, its
dependencies too. One row per package (exists, latest and pinned version,
ages, wheels on each target, sdist-only, hashes, licence, OSV count, near
miss, failing checks, verdict, the verdict a download source would give)
and summary rows (all, candidates, decoys: pass rate, the most frequent
failing check).

Part B (``test_acquire_suggestions``, Sonnet 5.5 at effort ``medium``):
for each OSS library of ``tests/fixtures/live_oss/manifest.json``, up to
three packages the model suggests for its hot spot, each through the same
policy: hallucinated (404), near-miss, auto-accept, ask-user and reject
rates, the slopsquatting exposure of a model-driven acquisition step.

Notes (always in the log): ``ACQUIRE <name>: exists <y/n> wheels
<linux>/<mac> age <d> osv <n> licence <l> verdict <v> (<checks>)`` per
package and ``SUGGEST <repo>: <name> -> <verdict> (<checks>)`` per
suggestion, plus one summary note per part. Outcomes are recorded, never
asserted; a part asserts only that its services answered at all.

Cost: Part A 0; Part B ``SUGGEST_CAP_USD``, the sum of the ten requests'
worst cases rounded up to the cent (``test_acquire`` proves it, counted and uncounted); expected
about 0.10 USD (about 1,500 input and 1,000 output tokens a library,
thinking included).
"""

from __future__ import annotations

import math
import os
from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from autonomous_ai_agents.clients.structured import Fence

from ..conftest import StartLive
from ..oss import OSS_CORPUS, OssRepo
from .acquire import (
    Assessment,
    Assessor,
    PackageIndex,
    SuggestReading,
    load_inputs,
    load_popular,
    read_suggestions,
    suggest_body,
    suggestion_summary,
    summarize,
)
from .harness import Answer, ExperimentClient
from .recorder import ExperimentRecorder, Metric
from .test_probes_live import answered, finish
from .web import run_cap

pytestmark = pytest.mark.live

POLICY_CAP_USD = 0.0
SUGGEST_CAP_USD = 0.60


def utc_now() -> datetime:
    return datetime.now(UTC)


def suggest_need(repos: Sequence[OssRepo] = OSS_CORPUS) -> float:
    """Every Part B request at its offline worst case (``web.run_cap``)."""
    fence = Fence.new()
    bodies = [suggest_body(repo, fence) for repo in repos]
    return math.fsum(run_cap(body) for body in bodies if body is not None)


def _summary_note(label: str, summary: dict[str, Metric]) -> str:
    return (
        f"ACQUIRE {label}: {summary['packages']} packages, auto-accept "
        f"{summary['auto_accept']}, ask-user {summary['ask_user']}, reject "
        f"{summary['reject']}, pass rate {summary['pass_rate']}, sans downloads "
        f"{summary['pass_rate_sans_downloads']}, top check "
        f"{summary['most_frequent_check']}"
    )


@dataclass
class PolicyReport:
    assessments: dict[str, Assessment] = field(default_factory=dict)
    summary: dict[str, Metric] = field(default_factory=dict)
    answered: int = 0


def run_policy(
    start: StartLive,
    index: PackageIndex,
    *,
    recorder: ExperimentRecorder,
    now: datetime,
) -> PolicyReport:
    """Part A: every input, then every dependency the policy looked at."""
    run = start(POLICY_CAP_USD)
    popular = load_popular()
    run.note(
        f"ACQUIRE popular snapshot {popular.snapshot_date}: {len(popular.names)} names"
    )
    assessor, report = Assessor(index, popular, now=now), PolicyReport()
    inputs = load_inputs()
    for item in inputs:
        found = assessor.assess(item.name)
        report.assessments[item.name] = found
        recorder.record("ACQ-A", item.role, item.name, found.metrics())
        run.note(found.note())
    listed = {a.canonical for a in report.assessments.values()}
    for name, found in assessor.done.items():
        if name not in listed:
            recorder.record("ACQ-A", "dependency", name, found.metrics())
            run.note(found.note() + " [dependency]")
    roles = {item.name: item.role for item in inputs}
    groups = {
        "all": list(report.assessments.values()),
        "candidates": [
            a for n, a in report.assessments.items() if roles[n] == "candidate"
        ],
        "decoys": [a for n, a in report.assessments.items() if roles[n] == "decoy"],
    }
    for label, members in groups.items():
        summary = summarize(members)
        recorder.record("ACQ-A", "summary", label, summary)
        run.note(_summary_note(label, summary))
    report.summary = summarize(groups["all"])
    report.answered = index.answered
    run.note(f"ACQUIRE index: {index.requests} requests, {index.answered} answered")
    return report


@dataclass
class SuggestReport:
    answers: dict[str, Answer] = field(default_factory=dict)
    readings: dict[str, SuggestReading] = field(default_factory=dict)
    judged: list[tuple[str, Assessment]] = field(default_factory=list)
    summary: dict[str, Metric] = field(default_factory=dict)
    withheld: int = 0


def run_suggestions(
    start: StartLive,
    index: PackageIndex,
    *,
    recorder: ExperimentRecorder,
    now: datetime,
    repos: Sequence[OssRepo] = OSS_CORPUS,
) -> SuggestReport:
    """Part B: one Sonnet request per library, then the policy per name."""
    run = start(SUGGEST_CAP_USD)
    fence, report = Fence.new(), SuggestReport()
    with ExperimentClient(run, recorder=recorder) as client:
        for repo in repos:
            body = suggest_body(repo, fence)
            if body is None:
                report.withheld += 1
                run.note(f"SUGGEST {repo.name}: withheld (holds a boundary token)")
                continue
            answer = client.messages(body)
            reading = read_suggestions(answer)
            report.answers[repo.name], report.readings[repo.name] = answer, reading
            recorder.record(
                "ACQ-B",
                "repo",
                repo.name,
                {
                    "outcome": reading.outcome,
                    "error": answer.error,
                    "suggestions": len(reading.suggestions),
                    "invalid": reading.invalid,
                    "over_limit": reading.over_limit,
                    "duplicates": reading.duplicates,
                    "cost_usd": answer.cost_usd,
                    "estimate_usd": answer.estimate_usd,
                },
            )
            if not reading.suggestions:
                run.note(f"SUGGEST {repo.name}: none ({reading.outcome})")
    assessor = Assessor(index, load_popular(), now=now)
    for repo_name, reading in report.readings.items():
        for suggestion in reading.suggestions:
            found = assessor.assess(suggestion.name)
            report.judged.append((repo_name, found))
            metrics: dict[str, Metric] = {
                **found.metrics(),
                "reason": suggestion.reason,
            }
            recorder.record(
                "ACQ-B", "suggestion", f"{repo_name}:{suggestion.name}", metrics
            )
            checks = f" ({', '.join(found.checks)})" if found.checks else ""
            run.note(
                f"SUGGEST {repo_name}: {suggestion.name} -> {found.verdict}{checks}"
            )
    report.summary = suggestion_summary(report.judged, report.readings)
    report.summary["withheld"] = report.withheld
    report.summary["cost_usd"] = run.spent_usd
    recorder.record("ACQ-B", "summary", "all", report.summary)
    top = Counter(c for _, a in report.judged for c in a.checks).most_common(1)
    run.note(
        f"SUGGEST summary: {report.summary['suggestions']} suggestions, "
        f"hallucinated {report.summary['hallucinated_rate']}, near-miss "
        f"{report.summary['near_miss_rate']}, auto-accept "
        f"{report.summary['auto_accept_rate']}, ask-user "
        f"{report.summary['ask_user_rate']}, reject {report.summary['reject_rate']}, "
        f"top check {top[0][0] if top else None}"
    )
    return report


@pytest.fixture(scope="module")
def acquire_recorder(pytestconfig: pytest.Config) -> Iterator[ExperimentRecorder]:
    recorder = ExperimentRecorder("Step 3b package acquisition probe", os.environ)
    yield recorder
    finish(recorder, pytestconfig)


def test_acquire_policy(live: StartLive, acquire_recorder: ExperimentRecorder) -> None:
    with PackageIndex() as index:
        report = run_policy(live, index, recorder=acquire_recorder, now=utc_now())
    assert report.answered, "pypi.org and api.osv.dev never answered"


def test_acquire_suggestions(
    live: StartLive, acquire_recorder: ExperimentRecorder
) -> None:
    with PackageIndex() as index:
        report = run_suggestions(live, index, recorder=acquire_recorder, now=utc_now())
    assert any(answered(a) for a in report.answers.values()), (
        "the API answered none of the suggestion requests"
    )
