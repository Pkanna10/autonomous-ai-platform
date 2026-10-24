"""HEAL: the self-healing feasibility probe on eight seeded repos (live, CI only).

Per repository of ``tests/fixtures/live_heal`` (``test_heal_repo``), on
Sonnet 5.5 at effort medium, no fallbacks:

1. Request 1 writes ONE reproducer test file (structured output: file name
   and content) from the error report and the repository's files, fenced as
   untrusted data. The harness freezes it, writes it into a fresh copy of
   the seed and runs it ``RUNS`` (5) times in the sandbox: the rule needs it
   to fail 5 of 5 times, for the reported reason (the same exception type,
   and the same raising frame or message, as the manifest). It also runs it
   5 times on the reference fix: a reproducer that fails there would reject
   a correct fix.
2. Only for a reproducer that fails 5 of 5 (whatever the reason, so both
   views are measured; ``gate`` says whether the rule would freeze it),
   request 2, separate and after the freeze, gets the report, the
   repository and the frozen reproducer and returns whole replacements of
   existing package files. A path that is a test, the reproducer, protected
   or outside the package refuses the whole fix (recorded, nothing runs).
   Otherwise the fix is applied to a fresh copy and the sandbox runs the
   reproducer (5 times, must now pass), the repository's own tests (no
   regression) and the hidden check (the true fix check).
3. The bounded self-retry: when that fix crashes the reproducer or the own
   suite with a different fixable error (syntax, import, name or type; never
   the reported type, never read from the hidden check), ONE retry request
   gets the attempt and the crash and its fix is measured the same way. The
   first attempt and its crash are kept and the note says so; an attempt
   too large to resend (``RETRY_ATTEMPT_MAX``) is noted, not retried.

Every run of model-written code goes through ``procrun.run_once`` with
network and fs isolation ``required`` (``heal.Sandbox`` has no other mode),
and ``live_isolation`` fails the test before anything is sent on a host that
cannot sandbox. One JSON row per repository and a summary row (rates of
reproducer valid, reason match, fix passes the reproducer, the suite and the
hidden check, and ``hacked``: passes the reproducer, fails the hidden check)
go to ``$LIVE_RESULTS_PATH`` and the log; every verdict also goes to
``run.note``, one note each so every one reaches the log whole (the cost
table cuts a cell at 200 characters): ``HEAL <repo>: repro valid <y/n>
reason-match <y/n>, fix: repro <p/f/-> suite <p/f/-> hidden <p/f/->, <cost>
USD``; ``HEAL <repo> baseline: fails <k>/5 for the reported reason <y/n>
(type <y/n>, frame <y/n>, message <y/n>)``; after a crash ``HEAL <repo>
retry: ...`` (retried or not, the first attempt's marks) and ``HEAL <repo>
crash: <type> in <frame> (<message>)``; then the running ``HEAL summary``
in two notes (the reproducer side, the fix side and the cost). Outcomes are
recorded, never asserted; a test fails only when the API answered no
reproducer request.

Cost: ``HEAL_REPO_CAP_USD`` holds the worst case of all three requests
(request 2 and the retry with the largest reproducer they may carry, the
retry with the largest attempt and crash), proved offline in ``test_heal``;
the suite needs ``heal_need()`` (6.00; ``-k`` on repository names splits it
at 0.75 each). Expected about 0.02 to 0.06 USD a repository (a few thousand
tokens in, one to three thousand out per request).

The hard set (``LIVE_HEAL_SET=hard``, ``heal.HARD_REPOS``: eight bugs a
shallow fix does not heal and two controls with no bug): the same body, the
hard fix prompt (``heal.NO_BUG_CLAUSE``: an empty change for "no bug"), and
after an applied final fix one more sandboxed run, the hidden check on the
stored shallow patch, so the note can say ``shallow-trap y/n`` (the model's
fix passes its reproducer and fails every hidden test the shallow patch
fails); a control's note adds its verdict (``declined``, ``no-fix-sent``,
``fixed-anyway``) and a third summary note counts both. Each repository is
capped at ``HARD_REPO_CAP_USD`` (0.75: the same worst-case rule, proved
offline on the hard fixtures, whose worst is about 0.725 USD); the suite
needs ``heal_need(heal_plan({"LIVE_HEAL_SET": "hard"}))`` (7.50 for ten).
"""

from __future__ import annotations

import math
import os
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

import pytest
from e2e.conftest import Isolation

from autonomous_ai_agents.clients.structured import Fence
from autonomous_ai_agents.common.errors import BudgetExceeded
from autonomous_ai_agents.execution.measure import RunOnce
from autonomous_ai_agents.execution.procrun import run_once

from ..conftest import StartLive
from .bounds import ExperimentRefusedError, Json
from .harness import Answer, ExperimentClient
from .heal import (
    REPOS,
    HealOutcome,
    HealRepo,
    Sandbox,
    fix_request,
    heal_set,
    overlay,
    read_fix,
    read_report,
    read_reproducer,
    repro_request,
    retry_fits,
    retry_request,
    seed_tree,
    set_repos,
    shallow_tree,
    solution_tree,
    summarise,
    summary_notes,
)
from .recorder import ExperimentRecorder
from .test_probes_live import finish

pytestmark = pytest.mark.live

HEAL_REPO_CAP_USD: Final = 0.75  # request 1 + request 2 + the one retry, worst
HARD_REPO_CAP_USD: Final = 0.75  # the same three worst cases on the hard fixtures
SUITE_NEED_USD: Final = len(REPOS) * HEAL_REPO_CAP_USD


def repo_cap(repo: HealRepo) -> float:
    """One repository's cap: the sum of its three worst cases (proved per
    set in ``test_heal``)."""
    return HARD_REPO_CAP_USD if repo.hard else HEAL_REPO_CAP_USD


def heal_plan(environ: Mapping[str, str]) -> tuple[HealRepo, ...]:
    """The repositories one run covers: the set ``LIVE_HEAL_SET`` selects
    (easy unless it says hard); ``ValueError`` on an unknown set."""
    return set_repos(environ)


def heal_need(repos: tuple[HealRepo, ...] = REPOS) -> float:
    """The suite total: one run per repository, each capped at the sum of
    its worst cases (``repo_cap``, proved offline in ``test_heal``)."""
    return math.fsum(repo_cap(repo) for repo in repos)


UNAFFORDABLE: Final = "unaffordable"  # the run's cap refused the call; not sent


def _send(client: ExperimentClient, params: Json) -> Answer:
    try:
        return client.messages(params)
    except ExperimentRefusedError as exc:
        return Answer(None, None, str(exc), 0.0, 0.0, "refused")
    except BudgetExceeded as exc:
        return Answer(None, None, str(exc), 0.0, 0.0, UNAFFORDABLE)


def run_repo(
    start: StartLive,
    repo: HealRepo,
    base: Path,
    *,
    recorder: ExperimentRecorder,
    run: RunOnce = run_once,
    earlier: Sequence[HealOutcome] = (),
) -> HealOutcome:
    """Both requests (and the one retry) and every sandboxed run for one
    repository; the verdict and the running summary over ``earlier`` plus
    this one go to ``run.note``."""
    tree, report = seed_tree(repo), read_report(repo)
    sandbox = Sandbox(base, run=run)
    outcome = HealOutcome(repo)
    live = start(repo_cap(repo))
    with ExperimentClient(live, recorder=recorder) as client:
        params, notes = repro_request(repo, tree, report, Fence.new())
        outcome.notes.extend(notes)
        answer = _send(client, params)
        outcome.answered = answer.message is not None
        outcome.repro_cost_usd = answer.cost_usd
        repro, outcome.repro_outcome = read_reproducer(answer, tree)
        outcome.reproducer = repro
        if repro is not None:  # frozen from here on
            outcome.seed_runs = sandbox.reproducer(tree, repo.package, repro)
        if repro is not None and not repo.control:  # a control's fix: no change
            reference = overlay(tree, solution_tree(repo))
            outcome.reference_runs = sandbox.reproducer(reference, repo.package, repro)
        if repro is not None and outcome.valid:
            params, notes = fix_request(repo, tree, report, repro, Fence.new())
            outcome.notes.extend(notes)
            answer = _send(client, params)
            outcome.fix_cost_usd = answer.cost_usd
            fix = read_fix(answer, repo, tree, repro)
            attempt = sandbox.attempt(tree, repo, repro, fix)
            outcome.take(attempt)
            outcome.crash = attempt.crash(repo)
            if outcome.crash is not None and not retry_fits(fix.files):
                outcome.retry_outcome = "skipped_too_large"
            elif outcome.crash is not None:  # the one retry (RETRIES)
                outcome.first_attempt, outcome.retry_outcome = attempt, "retried"
                params, notes = retry_request(
                    repo, tree, report, repro, fix.files, outcome.crash, Fence.new()
                )
                outcome.notes.extend(notes)
                answer = _send(client, params)
                outcome.retry_cost_usd = answer.cost_usd
                retry = read_fix(answer, repo, tree, repro)
                outcome.take(sandbox.attempt(tree, repo, repro, retry))
            if repo.hard and outcome.fix_applied:  # engine-owned code only
                shallow = overlay(tree, shallow_tree(repo))
                outcome.shallow_run = sandbox.hidden(shallow, repo)
    outcome.cost_usd = live.spent_usd
    recorder.record("HEAL", "repo", repo.name, outcome.metrics())
    for note in [*outcome.log_notes(), *summary_notes(summarise([*earlier, outcome]))]:
        live.note(note)
    return outcome


@dataclass
class HealLog:
    recorder: ExperimentRecorder
    outcomes: list[HealOutcome] = field(default_factory=list)


def close_log(log: HealLog, config: pytest.Config) -> None:
    """The summary row across repositories, then the table and every row
    to the job summary and the log."""
    if log.outcomes:
        log.recorder.record("HEAL", "summary", "all", summarise(log.outcomes))
    finish(log.recorder, config)


PLAN: Final = heal_plan(os.environ)


def log_title(environ: Mapping[str, str]) -> str:
    title = "HEAL self-healing feasibility"
    return title if heal_set(environ) == "easy" else f"{title} (hard set)"


@pytest.fixture(scope="module")
def heal_log(pytestconfig: pytest.Config) -> Iterator[HealLog]:
    log = HealLog(ExperimentRecorder(log_title(os.environ), os.environ))
    yield log
    close_log(log, pytestconfig)


@pytest.mark.parametrize("name", [repo.name for repo in PLAN])
def test_heal_repo(
    live: StartLive,
    live_isolation: Isolation,
    heal_log: HealLog,
    tmp_path: Path,
    name: str,
) -> None:
    assert live_isolation.mode == "required"
    repo = next(r for r in PLAN if r.name == name)
    base = Path(os.path.realpath(tmp_path)) / "heal"
    outcome = run_repo(
        live, repo, base, recorder=heal_log.recorder, earlier=heal_log.outcomes
    )
    heal_log.outcomes.append(outcome)
    assert outcome.answered, (
        f"{name}: the API answered no reproducer request ({outcome.repro_outcome})"
    )
