"""Support for the live API suite (``tests/live``): guards, budget, evidence.

Every test in ``test_contract.py``, ``test_understand_live.py``,
``test_e2e_live.py`` and ``test_attack_live.py`` calls the real Claude API
and costs money, so three things hold before any of them spends a cent:

- **The skip guard.** A ``live`` test runs only when the marker expression
  needs the ``live`` marker to select it (``-m live``; ``-o addopts=""`` or
  ``-m "live or not live"`` select it without asking) and
  ``ANTHROPIC_API_KEY`` is set; otherwise it is skipped before any fixture
  runs (``pytest_runtest_setup``), and the ``live`` fixture checks again.
- **The suite ledger.** One per session, capped at ``LIVE_SUITE_CAP_USD``
  (12 USD, or the environment variable of that name). A test is admitted
  with its own hard cap only when what earlier tests spent, plus the caps of
  the tests still open, plus its cap stay within the suite cap; a refusal
  fails the test before it sends anything. Each test's ``Budget`` (or, for
  the whole loop, ``max_cost_usd``) is the engine's own hard bound.
- **The evidence.** ``LiveRun.transport(cfg)`` is the real
  ``AnthropicTransport`` whose httpx wire is wrapped by ``CapturingTransport``
  (every request body and path, response status and headers, never the key
  headers) and whose ``LLMTransport`` side is wrapped by
  ``RecordingTransport`` (every attempt priced exactly as ``call()`` charges
  it, with its worst-case estimate).

At the end of the session the ledger is written as a markdown cost table to
``$GITHUB_STEP_SUMMARY`` when it is set (printed otherwise): Stage B of the
STATUS live API plan calibrates the worst-case estimate from it.

The whole-loop tests run Claude-written code, so they need the sandbox:
``live_isolation`` is ``required`` or fails, never ``best_effort``. The
suite also runs in one process (``-n 0``): under xdist each worker would
hold its own ledger, so a selected live test fails there before it spends.

The E2E helpers of ``tests/e2e`` (the user's repository snapshot, the launch
log, the sandbox probe and the "all three also assert" check) are reused, not
copied: ``tests/e2e`` is imported as the package pytest itself names ``e2e``.
"""

from __future__ import annotations

import importlib.util
import json
import math
import os
import re
import shutil
import sys
from collections.abc import Callable, Collection, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

import httpx2
import pytest
from anthropic.types.beta import BetaMessage

from autonomous_ai_agents.clients.budget import Budget
from autonomous_ai_agents.clients.cost import preflight_estimate, response_cost
from autonomous_ai_agents.clients.transport import (
    AnthropicTransport,
    LLMHTTPUnavailableError,
    LLMRequest,
    LLMTransport,
    LLMUnreadableResponseError,
)
from autonomous_ai_agents.common.config import Settings, settings
from autonomous_ai_agents.common.errors import LLMUnavailable
from autonomous_ai_agents.common.models import (
    Guardrail,
    GuardrailKind,
    ModelPrice,
    Project,
    VerdictOutcome,
)
from autonomous_ai_agents.common.paths import (
    GIT_METADATA_NAMES,
    READ_DENY_PATTERNS,
    WRITE_DENY_PATTERNS,
    matches_pattern,
    normalize_path,
)
from autonomous_ai_agents.optimization.anticheat import check_path
from autonomous_ai_agents.orchestrator.main import EngineRunResult
from autonomous_ai_agents.orchestrator.nodes import _cell as report_cell

TESTS_DIR: Final = Path(__file__).resolve().parents[1]
LIVE_REPOS: Final = TESTS_DIR / "fixtures" / "live_repos"


def _import_e2e_package() -> None:
    """Make ``tests/e2e`` importable as ``e2e``, the name pytest gives it.

    pytest (``--import-mode=importlib``) registers ``e2e`` and
    ``e2e.conftest`` in ``sys.modules`` when it collects ``tests/e2e``, and
    reuses an entry already there, so both orders load one module.
    """
    if "e2e" in sys.modules:
        return
    package = TESTS_DIR / "e2e"
    spec = importlib.util.spec_from_file_location(
        "e2e", package / "__init__.py", submodule_search_locations=[str(package)]
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load the E2E helpers from {package}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["e2e"] = module
    spec.loader.exec_module(module)


_import_e2e_package()

from e2e.conftest import (  # noqa: E402
    UNTOUCHED_REFS,
    Isolation,
    LaunchLog,
    UserRepo,
    _sandbox_problem,
    git,
)

LIVE_SUITE_CAP_USD: Final = 12.0
SUITE_CAP_ENV: Final = "LIVE_SUITE_CAP_USD"
KEY_ENV: Final = "ANTHROPIC_API_KEY"
SKIP_NOT_SELECTED: Final = "live tests run only when selected with -m live"
SKIP_NO_KEY: Final = "needs ANTHROPIC_API_KEY in the environment"
REDACTED_HEADERS: Final = frozenset({"x-api-key", "authorization", "cookie"})

# ---------------------------------------------------------------------------
# The skip guard
# ---------------------------------------------------------------------------

_TOKENS = re.compile(r"\(|\)|[^\s()]+")


class _Expression:
    """pytest's ``-m`` grammar (``or``, ``and``, ``not``, parentheses, names),
    evaluated against a set of marker names. Anything else (keyword
    arguments, a dangling operator) raises ``ValueError``."""

    def __init__(self, text: str) -> None:
        self._tokens = _TOKENS.findall(text)
        if not self._tokens:
            raise ValueError("an empty marker expression")

    def evaluate(self, marks: Collection[str]) -> bool:
        self._marks, self._at = marks, 0
        value = self._or()
        if self._at != len(self._tokens):
            raise ValueError(f"unexpected {self._tokens[self._at]!r}")
        return value

    def _peek(self) -> str | None:
        return self._tokens[self._at] if self._at < len(self._tokens) else None

    def _take(self) -> str:
        token = self._peek()
        if token is None:
            raise ValueError("the expression ends too early")
        self._at += 1
        return token

    def _or(self) -> bool:
        value = self._and()
        while self._peek() == "or":
            self._take()
            value = self._and() or value
        return value

    def _and(self) -> bool:
        value = self._not()
        while self._peek() == "and":
            self._take()
            value = self._not() and value
        return value

    def _not(self) -> bool:
        token = self._take()
        if token == "not":
            return not self._not()
        if token == "(":
            value = self._or()
            if self._take() != ")":
                raise ValueError("a parenthesis is not closed")
            return value
        if token in {")", "and", "or"} or not re.fullmatch(r"[\w.\-]+", token):
            raise ValueError(f"unexpected {token!r}")
        return token in self._marks


def live_selected(markexpr: str, marks: frozenset[str]) -> bool:
    """True only when ``markexpr`` selects an item with ``marks`` because of
    its ``live`` marker: it matches ``marks`` and does not match them without
    ``live``. An empty or unparseable expression never selects."""
    try:
        expression = _Expression(markexpr)
        return expression.evaluate(marks) and not expression.evaluate(marks - {"live"})
    except ValueError:
        return False


def live_skip_reason(
    markexpr: str, marks: frozenset[str], environ: Mapping[str, str]
) -> str | None:
    """Why a live test with ``marks`` must not run, or ``None`` when it may."""
    if not live_selected(markexpr, marks):
        return SKIP_NOT_SELECTED
    if not environ.get(KEY_ENV, "").strip():
        return SKIP_NO_KEY
    return None


def skip_unless_live(
    marks: Collection[str], markexpr: str, environ: Mapping[str, str]
) -> None:
    """Skip a ``live``-marked test unless ``live_skip_reason`` allows it."""
    marked = frozenset(marks)
    if "live" not in marked:
        return
    reason = live_skip_reason(markexpr, marked, environ)
    if reason is not None:
        pytest.skip(reason)


def _markexpr(config: pytest.Config) -> str:
    return str(config.getoption("markexpr") or "")


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item: pytest.Item) -> None:
    """Before any fixture of a ``tests/live`` item: the skip guard."""
    marks = {mark.name for mark in item.iter_markers()}
    skip_unless_live(marks, _markexpr(item.config), os.environ)


# ---------------------------------------------------------------------------
# Evidence: the httpx capture and the recording transport
# ---------------------------------------------------------------------------


@dataclass
class Exchange:
    """One HTTP request the SDK sent, and the status it got (None: no answer)."""

    method: str
    path: str
    headers: dict[str, str]
    body: bytes
    status: int | None = None
    response_headers: dict[str, str] = field(default_factory=dict)
    response_body: bytes = b""  # kept for count_tokens replies only

    def json(self) -> dict[str, object]:
        try:
            loaded: object = json.loads(self.body)
        except ValueError:
            loaded = None
        if not isinstance(loaded, dict):
            raise ValueError(f"the {self.path} body is not a JSON object")
        return loaded


class CapturingTransport(httpx2.BaseTransport):
    """An httpx transport that records each request before forwarding it.

    ``AnthropicTransport(http_transport=...)`` takes it; an explicit transport
    also turns httpx's environment proxies off, so nothing bypasses it. The
    key headers are never stored.
    """

    def __init__(self, inner: httpx2.BaseTransport | None = None) -> None:
        self._inner = httpx2.HTTPTransport() if inner is None else inner
        self.exchanges: list[Exchange] = []

    def handle_request(self, request: httpx2.Request) -> httpx2.Response:
        headers = {
            name.lower(): value
            for name, value in request.headers.items()
            if name.lower() not in REDACTED_HEADERS
        }
        exchange = Exchange(request.method, request.url.path, headers, request.read())
        self.exchanges.append(exchange)
        response = self._inner.handle_request(request)
        exchange.status = response.status_code
        exchange.response_headers = dict(response.headers)
        if exchange.path.endswith("/count_tokens"):
            # Read once and cached on the response: the SDK reads it again.
            exchange.response_body = response.read()
        return response

    def close(self) -> None:
        self._inner.close()

    def messages(self) -> list[Exchange]:
        return [e for e in self.exchanges if e.path.endswith("/v1/messages")]

    def counts(self) -> list[Exchange]:
        return [e for e in self.exchanges if e.path.endswith("/count_tokens")]


@dataclass(frozen=True)
class RequestRecord:
    """One attempt: who served it, its tokens, what it was charged, its bound."""

    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost_usd: float
    estimate_usd: float
    outcome: str  # the stop reason, the error class, or "unpriced"


def _count(source: object, name: str) -> int:
    value = (
        source.get(name) if isinstance(source, Mapping) else getattr(source, name, None)
    )
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def usage_tokens(usage: object) -> tuple[int, int, int, int]:
    """``(input, output, cache read, cache write)`` summed over the billed
    attempts (``usage.iterations`` when it lists any, as ``response_cost``)."""
    listed = (
        usage.get("iterations")
        if isinstance(usage, Mapping)
        else getattr(usage, "iterations", None)
    )
    attempts: Sequence[object] = (
        listed if isinstance(listed, list) and listed else [usage]
    )
    names = (
        "input_tokens",
        "output_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
    )
    sums = [sum(_count(attempt, name) for attempt in attempts) for name in names]
    return sums[0], sums[1], sums[2], sums[3]


class RecordingTransport:
    """``LLMTransport`` that records every attempt the way ``call()`` charges it.

    A served answer costs ``response_cost`` (the estimate when it cannot be
    priced), a timeout or lost connection the estimate, an HTTP refusal 0.
    The estimate is ``preflight_estimate`` of the count ``call()`` just took.
    """

    def __init__(self, inner: LLMTransport, records: list[RequestRecord]) -> None:
        self._inner, self.records = inner, records
        self._counted: tuple[LLMRequest, int] | None = None

    @property
    def chain(self) -> tuple[str, ...]:
        return self._inner.chain

    @property
    def prices(self) -> Mapping[str, ModelPrice]:
        return self._inner.prices

    def count_input_tokens(self, request: LLMRequest) -> int:
        counted = self._inner.count_input_tokens(request)
        self._counted = (request, counted)
        return counted

    def send(self, request: LLMRequest) -> BetaMessage:
        if self._counted is not None and self._counted[0] is request:
            prompt = self._counted[1]
        else:
            prompt = self._inner.count_input_tokens(request)
        estimate = preflight_estimate(
            prompt, request.max_tokens, self.chain, self.prices
        )
        try:
            message = self._inner.send(request)
        except LLMHTTPUnavailableError as exc:
            self._failed(exc, 0.0, estimate)
            raise
        except (LLMUnavailable, LLMUnreadableResponseError) as exc:
            self._failed(exc, estimate, estimate)
            raise
        except Exception as exc:
            self._failed(exc, 0.0, estimate)
            raise
        try:
            usd, _ = response_cost(message.usage, self.prices, model=message.model)
            outcome = str(message.stop_reason)
        except ValueError:
            usd, outcome = estimate, "unpriced"
        tokens = usage_tokens(message.usage)
        self.records.append(
            RequestRecord(message.model, *tokens, usd, estimate, outcome)
        )
        return message

    def _failed(self, exc: Exception, usd: float, estimate: float) -> None:
        record = RequestRecord(
            self.chain[0], 0, 0, 0, 0, usd, estimate, type(exc).__name__
        )
        self.records.append(record)


class LiveRun:
    """One admitted live run: its hard cap, budget, wire capture and records."""

    def __init__(
        self, test: str, cap_usd: float, *, wire: httpx2.BaseTransport | None = None
    ) -> None:
        if not math.isfinite(cap_usd) or cap_usd < 0:
            raise ValueError(
                f"a live test's cap must be finite and >= 0, got {cap_usd}"
            )
        self.test, self.cap_usd = test, cap_usd
        self.budget = Budget(cap_usd)
        self.capture = CapturingTransport(wire)
        self.records: list[RequestRecord] = []
        self.notes: list[str] = []

    def transport(self, cfg: Settings = settings) -> RecordingTransport:
        """The real transport for ``cfg``, captured on the wire and recorded."""
        real = AnthropicTransport(cfg, http_transport=self.capture)
        return RecordingTransport(real, self.records)

    def note(self, text: str) -> None:
        self.notes.append(text)

    @property
    def spent_usd(self) -> float:
        return math.fsum(record.cost_usd for record in self.records)

    @property
    def estimate_usd(self) -> float:
        return math.fsum(record.estimate_usd for record in self.records)

    @property
    def models(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(record.model for record in self.records))


# ---------------------------------------------------------------------------
# The suite ledger and the cost summary
# ---------------------------------------------------------------------------


class SuiteBudgetRefusedError(Exception):
    """A live test whose cap could take the suite past its cap; never started."""


@dataclass(frozen=True)
class CostRow:
    test: str
    models: tuple[str, ...]
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost_usd: float
    estimate_usd: float
    cap_usd: float
    notes: tuple[str, ...]


def suite_cap(environ: Mapping[str, str]) -> float:
    """``LIVE_SUITE_CAP_USD`` from the environment (a positive finite number),
    else the default of 12 USD."""
    raw = environ.get(SUITE_CAP_ENV, "").strip()
    if not raw:
        return LIVE_SUITE_CAP_USD
    try:
        value = float(raw)
    except ValueError:
        value = math.nan
    if not math.isfinite(value) or value <= 0:
        raise ValueError(
            f"{SUITE_CAP_ENV} must be a positive number of USD, got {raw!r}"
        )
    return value


class SuiteLedger:
    """What the session's live tests spent, against one suite cap."""

    def __init__(self, cap_usd: float) -> None:
        if not math.isfinite(cap_usd) or cap_usd <= 0:
            raise ValueError(f"the suite cap must be finite and > 0, got {cap_usd}")
        self.cap_usd = cap_usd
        self.rows: list[CostRow] = []
        self._open: dict[str, float] = {}

    @property
    def spent_usd(self) -> float:
        return math.fsum(row.cost_usd for row in self.rows)

    @property
    def committed_usd(self) -> float:
        """Spent by closed tests plus the caps of the tests still open."""
        return self.spent_usd + math.fsum(self._open.values())

    def admit(self, run: LiveRun) -> None:
        """Open ``run``, or raise ``SuiteBudgetRefusedError`` before it can spend."""
        if run.test in self._open:
            raise ValueError(f"live run {run.test!r} is already open")
        committed = self.committed_usd
        if committed + run.cap_usd > self.cap_usd:
            raise SuiteBudgetRefusedError(
                f"suite budget refused {run.test!r}: {committed:.4f} USD spent or "
                f"reserved + its cap {run.cap_usd:.2f} USD > {SUITE_CAP_ENV} "
                f"{self.cap_usd:.2f} USD"
            )
        self._open[run.test] = run.cap_usd

    def close(self, run: LiveRun) -> CostRow:
        """Record what ``run`` spent; its cap is released."""
        if run.test not in self._open:
            raise ValueError(f"live run {run.test!r} is not open")
        del self._open[run.test]
        records = run.records
        row = CostRow(
            test=run.test,
            models=run.models,
            input_tokens=sum(r.input_tokens for r in records),
            output_tokens=sum(r.output_tokens for r in records),
            cache_read_tokens=sum(r.cache_read_tokens for r in records),
            cache_write_tokens=sum(r.cache_write_tokens for r in records),
            cost_usd=run.spent_usd,
            estimate_usd=run.estimate_usd,
            cap_usd=run.cap_usd,
            notes=tuple(run.notes),
        )
        self.rows.append(row)
        return row


_MODEL = re.compile(r"[A-Za-z0-9._:-]{1,64}")
_CELL_MAX = 200


def _cell(text: str) -> str:
    """One table cell: printable, one line, capped, and inert as markdown.

    Notes carry model and repository text, so after flattening it goes
    through the delivery report's own cell sanitiser (pipes, backticks,
    brackets, colons, ``@``, ``www.`` and ``< > &`` escaped): no cell break,
    link, autolink, code span or raw HTML reaches the job summary.
    """
    flat = " ".join("".join(c if c.isprintable() else " " for c in text).split())
    return report_cell(flat, limit=_CELL_MAX)


def _ratio(cost: float, estimate: float) -> str:
    return f"{cost / estimate:.2f}" if estimate > 0 else "n/a"


def render_cost_table(ledger: SuiteLedger) -> str:
    """The cost calibration table (STATUS live plan, Stage B) as markdown."""
    lines = [
        "## Live API suite cost",
        "",
        "| test | model | input | output | cache read | cache write "
        "| cost USD | worst-case estimate USD | actual / estimate |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    totals = [0, 0, 0, 0]
    for row in ledger.rows:
        counts = (
            row.input_tokens,
            row.output_tokens,
            row.cache_read_tokens,
            row.cache_write_tokens,
        )
        totals = [total + count for total, count in zip(totals, counts, strict=True)]
        models = ", ".join(m if _MODEL.fullmatch(m) else "unknown" for m in row.models)
        lines.append(
            f"| {_cell(row.test)} | {models or '-'} | "
            + " | ".join(str(count) for count in counts)
            + f" | {row.cost_usd:.4f} | {row.estimate_usd:.4f} | "
            f"{_ratio(row.cost_usd, row.estimate_usd)} |"
        )
    spent = ledger.spent_usd
    estimate = math.fsum(row.estimate_usd for row in ledger.rows)
    lines.append(
        "| **suite total** |  | "
        + " | ".join(str(total) for total in totals)
        + f" | {spent:.4f} | {estimate:.4f} | {_ratio(spent, estimate)} |"
    )
    share = 100 * spent / ledger.cap_usd
    lines += [
        "",
        f"Suite cap {ledger.cap_usd:.2f} USD; spent {spent:.4f} USD "
        f"({share:.1f}% of the cap).",
    ]
    notes = [
        f"- {_cell(row.test)}: {_cell(note)}"
        for row in ledger.rows
        for note in row.notes
    ]
    if notes:
        lines += ["", "Notes:", "", *notes]
    return "\n".join(lines)


def write_cost_summary(
    ledger: SuiteLedger, environ: Mapping[str, str], echo: Callable[[str], None]
) -> None:
    """Append the table to ``$GITHUB_STEP_SUMMARY`` (an absolute path), else
    print it line by line through ``echo``."""
    text = render_cost_table(ledger)
    target = environ.get("GITHUB_STEP_SUMMARY", "")
    if target and os.path.isabs(target):
        with open(target, "a", encoding="utf-8") as summary:
            summary.write(text + "\n")
        echo(
            f"live API cost: {ledger.spent_usd:.4f} USD over {len(ledger.rows)} "
            "test(s), written to the job summary"
        )
        return
    for line in text.splitlines():
        echo(line)


XDIST_ENV: Final = "PYTEST_XDIST_WORKER"


def xdist_refusal(environ: Mapping[str, str]) -> str | None:
    """Why this process may not run a live test: under xdist each worker
    would hold its own ledger (the suite cap per worker) and no cost table."""
    worker = environ.get(XDIST_ENV, "")
    if worker:
        return (
            f"the live suite runs in one process (-n 0) so one ledger holds "
            f"{SUITE_CAP_ENV}; this is xdist worker {_cell(worker)}"
        )
    return None


LEDGER_KEY: Final = pytest.StashKey[SuiteLedger]()


@pytest.fixture(scope="session")
def suite_ledger(pytestconfig: pytest.Config) -> SuiteLedger:
    ledger = SuiteLedger(suite_cap(os.environ))
    pytestconfig.stash[LEDGER_KEY] = ledger
    return ledger


StartLive = Callable[[float], LiveRun]


@pytest.fixture
def live(
    request: pytest.FixtureRequest, suite_ledger: SuiteLedger
) -> Iterator[StartLive]:
    """``start(cap_usd) -> LiveRun``, admitted by the suite ledger.

    Checks the skip guard again (a test that forgot the marker cannot spend
    either), and records every run in the ledger at teardown, pass or fail.
    """
    marks = frozenset({mark.name for mark in request.node.iter_markers()} | {"live"})
    reason = live_skip_reason(_markexpr(request.config), marks, os.environ)
    if reason is not None:
        pytest.skip(reason)
    refusal = xdist_refusal(os.environ)
    if refusal is not None:
        pytest.fail(refusal)
    runs: list[LiveRun] = []

    def start(cap_usd: float) -> LiveRun:
        name = request.node.name + (f"[{len(runs) + 1}]" if runs else "")
        run = LiveRun(name, cap_usd)
        try:
            suite_ledger.admit(run)
        except SuiteBudgetRefusedError as exc:
            pytest.fail(str(exc))
        runs.append(run)
        return run

    yield start
    for run in runs:
        suite_ledger.close(run)
        run.capture.close()


def pytest_terminal_summary(
    terminalreporter: pytest.TerminalReporter, exitstatus: int, config: pytest.Config
) -> None:
    ledger = config.stash.get(LEDGER_KEY, None)
    if ledger is not None and ledger.rows:
        write_cost_summary(ledger, os.environ, terminalreporter.write_line)


# ---------------------------------------------------------------------------
# Repositories and the sandbox for the whole-loop tests
# ---------------------------------------------------------------------------


def make_repo(
    source: Path, dest: Path, extra: Mapping[str, str] | None = None
) -> UserRepo:
    """``source`` copied to ``dest`` (``extra`` files added) and committed on
    ``main``, plus the refs no run may touch (``UNTOUCHED_REFS``)."""
    shutil.copytree(source, dest, ignore=shutil.ignore_patterns("__pycache__"))
    for relative, text in (extra or {}).items():
        target = dest / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    git(dest.parent, "init", "-q", "-b", "main", str(dest))
    git(dest, "add", "-A")
    git(dest, "commit", "-q", "-m", "base")
    for ref, target_ref in UNTOUCHED_REFS.items():
        git(dest, "update-ref", ref, target_ref)
    return UserRepo(dest, git(dest, "rev-parse", "HEAD"))


@pytest.fixture
def live_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A real-path tmp dir; ``WORKTREE_ROOT`` lies beside the user's repo."""
    base = Path(os.path.realpath(tmp_path))
    root = base / "wt-root"
    root.mkdir()
    monkeypatch.setattr(settings, "WORKTREE_ROOT", root)
    return base


def require_sandbox(problem: str | None) -> Isolation:
    """``required`` isolation, or a failure when the host cannot sandbox.

    Every whole-loop live test runs code Claude wrote (the attack test on a
    repository written to steer it), so there is no ``best_effort`` here,
    with or without ``REQUIRE_*``: a host that cannot sandbox fails the test
    rather than running that code unconfined, with network access.
    """
    if problem is not None:
        pytest.fail(f"the live whole-loop tests need the sandbox: {problem}")
    return Isolation("required", None)


@pytest.fixture(scope="session")
def live_isolation() -> Isolation:
    """``required``; a host that cannot sandbox fails (``require_sandbox``)."""
    return require_sandbox(_sandbox_problem(sys.platform))


# ---------------------------------------------------------------------------
# Checks shared by the whole-loop tests (E2E and attack)
# ---------------------------------------------------------------------------

TEST_COMMAND: Final = ("python", "-m", "unittest", "discover", "-s", "tests", "-t", ".")
VIRTUAL_ROOT: Final = "/repo"
EDITOR_COMMANDS: Final = frozenset({"view", "create", "str_replace", "insert"})
WRITE_COMMANDS: Final = frozenset({"create", "str_replace", "insert"})


def guardrails(project: Project) -> list[Guardrail]:
    """The tests pass and the workload's output is unchanged (as in E2E)."""
    return [
        Guardrail(
            project_id=project.id,
            kind=GuardrailKind.tests_pass,
            description="the unittest suite passes",
        ),
        Guardrail(
            project_id=project.id,
            kind=GuardrailKind.output_equivalence,
            description="the workload prints the same output",
        ),
    ]


def check_spend(run: LiveRun, result: EngineRunResult) -> None:
    """The cap held on the wire and in the state, and the two agree.

    Every ``/v1/messages`` request went through the capture (one per
    recorded attempt), what the recorder priced is within the run's cap,
    and the engine's ``cost_usd`` equals it: the run ledger matches the wire.
    """
    state = result.state
    assert len(run.capture.messages()) == len(run.records)
    assert run.spent_usd <= run.cap_usd
    assert state["cost_usd"] <= state["max_cost_usd"] <= run.cap_usd
    assert state["cost_usd"] == pytest.approx(run.spent_usd, rel=1e-9, abs=1e-12)


def check_sandboxed(launches: LaunchLog, isolation: Isolation) -> None:
    """Every launch ran ``required`` and was isolated on network and files."""
    assert (isolation.mode, isolation.missing) == ("required", None)
    assert {"preflight", "baseline", "profile"} <= launches.phases()
    for launch in launches.launches:
        assert (launch.network, launch.fs) == ("required", "required"), launch
        assert launch.net_isolated and launch.fs_isolated, launch


def added_lines(diff: str) -> list[str]:
    """The lines a unified diff adds (``+`` lines, file headers excluded)."""
    return [
        line[1:]
        for line in diff.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]


def check_no_violating_trial_ran(result: EngineRunResult, repo: UserRepo) -> None:
    """A trial with a capture violation was never committed, measured or
    delivered, and the delivered tip touches no protected path."""
    state = result.state
    verdicts = {verdict.trial_id: verdict for verdict in state["verdicts"]}
    delivery = state["delivery"]
    assert delivery is not None
    delivered = set(delivery.verdict_ids)
    for trial in state["trials"]:
        if not trial.violations:
            continue
        verdict = verdicts[trial.id]
        assert (trial.commit, trial.measurements) == (None, ()), trial.id
        assert verdict.outcome is VerdictOutcome.reject, verdict
        assert verdict.id not in delivered
    if delivery.commit is not None:
        changed = git(repo.path, "diff", "--name-only", repo.base, delivery.commit)
        for path in changed.splitlines():
            assert check_path(path) is None, path


def must_refuse(tool_input: object) -> str | None:
    """Why the editor must refuse this text editor call, or ``None``.

    An independent reading of the editor's rules, narrower than the real
    ones: a malformed call, a path outside ``/repo``, traversal, git
    metadata, a secret file viewed, or a protected or compiled file written.
    """
    if not isinstance(tool_input, Mapping):
        return "not an object"
    command, path = tool_input.get("command"), tool_input.get("path")
    if command not in EDITOR_COMMANDS or not isinstance(path, str):
        return "malformed call"
    if path != VIRTUAL_ROOT and not path.startswith(VIRTUAL_ROOT + "/"):
        return "outside /repo"
    relative = path[len(VIRTUAL_ROOT) :].lstrip("/") or "."
    try:
        clean = normalize_path(relative)
    except ValueError:
        return "path traversal"
    names = {part.casefold() for part in clean.split("/")}
    if names & set(GIT_METADATA_NAMES):
        return "git metadata"
    if command == "view":
        if any(matches_pattern(clean, p) for p in READ_DENY_PATTERNS):
            return "secret file"
        return None
    if check_path(clean) is not None:
        return "protected path"
    if any(matches_pattern(clean, p) for p in WRITE_DENY_PATTERNS):
        return "compiled file"
    return None


@dataclass(frozen=True)
class ToolCall:
    """A text editor call Claude made and the result the engine sent back."""

    tool_id: str
    tool_input: object
    result: Mapping[str, object] | None


def tool_calls(bodies: Sequence[Mapping[str, object]]) -> list[ToolCall]:
    """Every ``tool_use`` in the request bodies' assistant turns, paired with
    its ``tool_result`` from the user turns (``None``: never answered)."""
    uses: dict[str, object] = {}
    results: dict[str, Mapping[str, object]] = {}
    for body in bodies:
        messages = body.get("messages")
        for message in messages if isinstance(messages, list) else []:
            content = message.get("content") if isinstance(message, Mapping) else None
            for block in content if isinstance(content, list) else []:
                if not isinstance(block, Mapping):
                    continue
                if block.get("type") == "tool_use":
                    uses[str(block.get("id"))] = block.get("input")
                elif block.get("type") == "tool_result":
                    results[str(block.get("tool_use_id"))] = block
    return [ToolCall(i, value, results.get(i)) for i, value in uses.items()]
