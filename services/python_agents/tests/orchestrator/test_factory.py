"""The engine factory: the real NodeContext for one project (Step 2, U20d).

Nothing here talks to the Claude API. The branch that needs a key is driven
with a fake ``SecretStr`` and an injected transport factory; the one test
that sends a request sends it to an ``httpx2.MockTransport``.
"""

from __future__ import annotations

import inspect
import json
import logging
import os
import shutil
from collections.abc import Callable, Iterator, Mapping, MutableMapping, Sequence
from pathlib import Path
from typing import TypedDict, cast

import httpx2
import pytest
from langgraph.graph import END, START, StateGraph
from pydantic import SecretStr
from structlog.testing import capture_logs

from autonomous_ai_agents.clients.budget import Budget
from autonomous_ai_agents.clients.cost import chain, preflight_estimate
from autonomous_ai_agents.clients.transport import (
    AnthropicTransport,
    LLMRequest,
    LLMTransport,
    ScriptedTransport,
)
from autonomous_ai_agents.common.config import Settings, role_settings, settings
from autonomous_ai_agents.common.errors import (
    DeliveryError,
    EngineError,
    LLMConfigError,
    PreflightError,
)
from autonomous_ai_agents.common.models import (
    Baseline,
    ChangeClass,
    EngineEvent,
    EventLevel,
    Hypothesis,
    HypothesisSource,
    Measurement,
    Project,
    RunPhase,
    Trial,
    Workload,
)
from autonomous_ai_agents.execution.combine import GitBranchPublisher, GitCombiner
from autonomous_ai_agents.execution.editor import ClaudeEditor
from autonomous_ai_agents.execution.fakes import FakePreflight, ScriptedEditor
from autonomous_ai_agents.execution.preflight import GitPreflight
from autonomous_ai_agents.execution.procrun import OutputCaps, RunSample, run_once
from autonomous_ai_agents.execution.profiler import CProfiler
from autonomous_ai_agents.execution.protocols import (
    EditTask,
    Preflight,
    PreflightReport,
    TrialBrief,
)
from autonomous_ai_agents.execution.runner import (
    BaselineRunner,
    ScriptedOutcome,
    StubBaselineRunner,
    StubTrialRunner,
    TrialRunner,
)
from autonomous_ai_agents.execution.sandbox import SandboxPolicy
from autonomous_ai_agents.execution.trial_runner import (
    GitBaselineRunner,
    GitTrialRunner,
)
from autonomous_ai_agents.optimization.anticheat import DEFAULT_PROTECTED_PATTERNS
from autonomous_ai_agents.optimization.judges import default_judges
from autonomous_ai_agents.orchestrator import factory
from autonomous_ai_agents.orchestrator.factory import (
    ConnectedBaselineRunner,
    ConnectedPreflight,
    ConnectedRunners,
    ConnectedTrialRunner,
    RunNotes,
    build_context,
    claude_editor_factory,
    engine_transport,
    min_trial_budget,
)
from autonomous_ai_agents.orchestrator.understand import ClaudeUnderstander
from autonomous_ai_agents.persistence.repository import InMemoryRepository

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
DEDUPE_REPO = FIXTURES / "dedupe_repo"
H1_CORE = FIXTURES / "dedupe_edits" / "h1" / "files" / "dedupe" / "core.py"
TRANSCRIPT = FIXTURES / "transcripts" / "e2e_a_h1_attack_then_edit.json"
FAKE_KEY = "sk-ant-test-not-a-real-key-0000"  # nosec B105: a test value
SHA = "0123456789abcdef0123456789abcdef01234567"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test here may see a key the host configured."""
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", None)


@pytest.fixture
def worktree_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = Path(os.path.realpath(tmp_path)) / "wt-root"
    root.mkdir()
    monkeypatch.setattr(settings, "WORKTREE_ROOT", root)
    return root


@pytest.fixture
def project(tmp_path: Path, worktree_root: Path) -> Project:
    repo = Path(os.path.realpath(tmp_path)) / "user"
    repo.mkdir()
    return Project(name="dedupe", root_path=str(repo))


@pytest.fixture
def sdk_logger() -> Iterator[logging.Logger]:
    logger = logging.getLogger("anthropic")
    level = logger.level
    yield logger
    logger.setLevel(level)


def _scripted() -> ScriptedTransport:
    return ScriptedTransport([])


def _no_real_transport(cfg: Settings) -> LLMTransport:
    raise AssertionError("a test reached the real transport factory")


def _hypothesis(project: Project, title: str = "h1") -> Hypothesis:
    return Hypothesis(
        id="h1",
        project_id=project.id,
        source=HypothesisSource.playbook,
        title=title,
        rationale="keep a set of seen values",
        change_class=ChangeClass.efficiency,
        expected_gain=0.5,
        provability=0.9,
        risk=0.1,
    )


# ---------------------------------------------------------------------------
# What the factory wires
# ---------------------------------------------------------------------------


def test_every_seam_is_the_real_implementation(project: Project) -> None:
    """
    GIVEN a project and an injected transport
    WHEN the context is built
    THEN every Step 2 seam and both runners are the real classes, the judges
         are the default judges, the repository defaults to in-memory and the
         knobs come from the settings
    """
    hypothesis = _hypothesis(project)

    ctx = build_context(project, candidates=[hypothesis], transport=_scripted())

    assert isinstance(ctx.preflight, ConnectedPreflight)
    assert isinstance(ctx.preflight.inner, GitPreflight)
    assert isinstance(ctx.understander, ClaudeUnderstander)
    assert isinstance(ctx.profiler, CProfiler)
    assert isinstance(ctx.combiner, GitCombiner)
    assert isinstance(ctx.publisher, GitBranchPublisher)
    assert isinstance(ctx.runner, ConnectedTrialRunner)
    assert isinstance(ctx.runner.current, GitTrialRunner)
    assert isinstance(ctx.baseline_runner, ConnectedBaselineRunner)
    assert isinstance(ctx.baseline_runner.current, GitBaselineRunner)
    assert isinstance(ctx.runner, TrialRunner)
    assert isinstance(ctx.baseline_runner, BaselineRunner)
    assert isinstance(ctx.preflight, Preflight)
    assert ctx.judges == default_judges(settings.NOISE_MULTIPLIER)
    assert isinstance(ctx.repository, InMemoryRepository)
    assert ctx.candidates == (hypothesis,)
    assert ctx.protected_patterns == DEFAULT_PROTECTED_PATTERNS
    assert ctx.branch_prefix == settings.TRIAL_BRANCH_PREFIX
    assert ctx.min_runs == settings.MIN_RUNS
    assert ctx.max_hypotheses_per_round == 3


def test_explicit_overrides_reach_the_context(project: Project) -> None:
    """
    GIVEN a repository, patterns, a prefix and a round size
    WHEN the context is built
    THEN the context holds them as given
    """
    repository = InMemoryRepository()

    ctx = build_context(
        project,
        repository=repository,
        protected_patterns=("**/bench/**",),
        branch_prefix="aip/",
        max_hypotheses_per_round=4,
        transport=_scripted(),
    )

    assert ctx.repository is repository
    assert ctx.protected_patterns == ("**/bench/**",)
    assert ctx.branch_prefix == "aip/"
    assert ctx.max_hypotheses_per_round == 4


def test_the_context_prefix_bounds_the_trial_runner_and_the_publisher(
    project: Project,
) -> None:
    """
    GIVEN a context built with the branch prefix aip/
    WHEN its trial runner gets an engine/ trial branch and its publisher an
         engine/ delivery branch
    THEN both refuse before touching git: they were built with the context's
         prefix, not the setting's
    """
    ctx = build_context(project, branch_prefix="aip/", transport=_scripted())
    hypothesis = _hypothesis(project)
    brief = TrialBrief(understanding=None, hotspots=(), protected=())

    with pytest.raises(ValueError, match="aip/trial-"):
        ctx.runner.run(
            hypothesis,
            [],
            Baseline(commit=SHA),
            round=1,
            branch="engine/trial-run1-h1",
            budget_usd=1.0,
            brief=brief,
        )
    assert ctx.publisher is not None
    with pytest.raises(DeliveryError, match="outside the engine prefix 'aip/'"):
        ctx.publisher.publish(project, "engine/run-run1", tip=SHA, base=SHA)


def _record(monkeypatch: pytest.MonkeyPatch, name: str) -> list[dict[str, object]]:
    """Replace ``factory.<name>`` by a wrapper that records its keyword args."""
    seen: list[dict[str, object]] = []
    real = getattr(factory, name)

    def recording(*args: object, **kwargs: object) -> object:
        seen.append(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(factory, name, recording)
    return seen


SANDBOXED = (
    "GitPreflight",
    "CProfiler",
    "GitCombiner",
    "GitBaselineRunner",
    "GitTrialRunner",
)
"""Every class the factory builds that launches repository code."""


def _launcher(
    argv: Sequence[str],
    cwd: Path,
    env: Mapping[str, str],
    sandbox: SandboxPolicy,
    timeout_s: float,
    caps: OutputCaps,
    *,
    fresh_dirs: Sequence[Path] = (),
) -> RunSample:
    raise AssertionError("no test here launches a process")


def test_preflight_protects_the_context_patterns(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    GIVEN explicit protected patterns
    WHEN the context is built
    THEN GitPreflight is constructed with exactly those patterns and the
         settings' isolation modes, or the explicit ones
    """
    seen = _record(monkeypatch, "GitPreflight")

    build_context(project, protected_patterns=("a/**",), transport=_scripted())
    build_context(project, transport=_scripted(), network="best_effort", fs="off")

    assert seen[0]["protected"] == ("a/**",)
    assert (seen[0]["network"], seen[0]["fs"]) == (
        settings.NETWORK_ISOLATION,
        settings.FS_ISOLATION,
    )
    assert seen[1]["protected"] == DEFAULT_PROTECTED_PATTERNS
    assert (seen[1]["network"], seen[1]["fs"]) == ("best_effort", "off")
    assert seen[0]["executable"] == settings.GIT_EXECUTABLE


@pytest.mark.parametrize("explicit", [False, True])
def test_everything_that_launches_repo_code_gets_the_context_isolation(
    project: Project, monkeypatch: pytest.MonkeyPatch, explicit: bool
) -> None:
    """
    GIVEN isolation settings, and in one case explicit modes and a launcher
    WHEN the context is built
    THEN preflight, profiler, combiner and both runners are each passed the
         context's network and fs modes and its launcher explicitly (none is
         left to fall back to its own default), and both runners the notes
    """
    monkeypatch.setattr(settings, "NETWORK_ISOLATION", "best_effort")
    monkeypatch.setattr(settings, "FS_ISOLATION", "required")
    seen = {name: _record(monkeypatch, name) for name in SANDBOXED}

    if explicit:
        build_context(
            project, transport=_scripted(), network="off", fs="off", run=_launcher
        )
    else:
        build_context(project, transport=_scripted())

    expected = (
        ("off", "off", _launcher) if explicit else ("best_effort", "required", run_once)
    )
    for name, calls in seen.items():
        (call,) = calls
        assert (call["network"], call["fs"], call["run"]) == expected, name
    for name in ("GitBaselineRunner", "GitTrialRunner"):
        assert isinstance(seen[name][0]["on_note"], RunNotes), name


# ---------------------------------------------------------------------------
# The trial floor
# ---------------------------------------------------------------------------


def test_the_trial_floor_is_one_worst_case_editor_request(project: Project) -> None:
    """
    GIVEN the default settings (fallbacks on)
    WHEN the context is built
    THEN min_trial_budget_usd is preflight_estimate(0, EDITOR_MAX_TOKENS,
         ENGINE_MODEL then ENGINE_FALLBACK_MODELS, MODEL_PRICING)
    """
    expected = preflight_estimate(
        0,
        settings.EDITOR_MAX_TOKENS,
        (settings.ENGINE_MODEL, *settings.ENGINE_FALLBACK_MODELS),
        settings.MODEL_PRICING,
    )

    ctx = build_context(project, transport=_scripted())

    assert ctx.min_trial_budget_usd == expected == min_trial_budget()
    assert expected > 0


def test_without_fallbacks_the_floor_prices_the_engine_model_only(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    GIVEN ENGINE_FALLBACKS off
    WHEN the floor is computed
    THEN it prices a one-model chain, so it is below the fallback floor
    """
    with_fallbacks = min_trial_budget()
    monkeypatch.setattr(settings, "ENGINE_FALLBACKS", False)

    floor = min_trial_budget()

    assert chain(settings) == (settings.ENGINE_MODEL,)
    assert floor == preflight_estimate(
        0, settings.EDITOR_MAX_TOKENS, (settings.ENGINE_MODEL,), settings.MODEL_PRICING
    )
    assert floor < with_fallbacks
    assert build_context(project, transport=_scripted()).min_trial_budget_usd == floor


def test_an_explicit_trial_floor_wins(project: Project) -> None:
    ctx = build_context(project, transport=_scripted(), min_trial_budget_usd=0.25)
    assert ctx.min_trial_budget_usd == 0.25


# ---------------------------------------------------------------------------
# The transport and the key
# ---------------------------------------------------------------------------


def test_without_a_key_nothing_builds_a_transport(project: Project) -> None:
    """
    GIVEN no ANTHROPIC_API_KEY and an injected (scripted) editor
    WHEN the context is built
    THEN no transport is built: understand keeps its Step 1 stub (None) and
         the trials use the injected editor
    """
    assert engine_transport(None, _no_real_transport) is None

    ctx = build_context(
        project,
        editor=lambda **_: ScriptedEditor(FIXTURES / "dedupe_edits"),
        transport_factory=_no_real_transport,
    )

    assert ctx.understander is None
    assert isinstance(ctx.runner, ConnectedTrialRunner)
    assert isinstance(ctx.runner.current, GitTrialRunner)


def test_without_a_key_or_an_editor_the_factory_refuses(project: Project) -> None:
    """
    GIVEN no ANTHROPIC_API_KEY, no transport and no editor
    WHEN the context is built
    THEN LLMConfigError says the editor needs a key, before any run starts
    """
    with pytest.raises(LLMConfigError, match="ANTHROPIC_API_KEY"):
        build_context(project, transport_factory=_no_real_transport)


def test_with_a_key_the_transport_factory_builds_the_engine_and_role_transports(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    GIVEN a (fake) key and an injected transport factory
    WHEN the context is built
    THEN the factory is called with the settings (its transport backs the
         understander), then with the editor's and the generator's role
         settings (Step 3, U10; test_factory_roles.py covers the roles)
    """
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", SecretStr(FAKE_KEY))
    built: list[Settings] = []
    scripted = _scripted()

    def make(cfg: Settings) -> LLMTransport:
        built.append(cfg)
        return scripted if cfg is settings else ScriptedTransport([], cfg=cfg)

    ctx = build_context(project, transport_factory=make)

    assert built == [
        settings,
        role_settings(settings, "editor"),
        role_settings(settings, "generator"),
    ]
    assert built[0] is settings
    assert isinstance(ctx.understander, ClaudeUnderstander)
    assert engine_transport(scripted, _no_real_transport) is scripted


def test_an_injected_transport_is_used_even_with_a_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", SecretStr(FAKE_KEY))
    scripted = _scripted()
    assert engine_transport(scripted, _no_real_transport) is scripted


def test_the_default_transport_factory_is_the_real_client() -> None:
    """The default is AnthropicTransport (never constructed here)."""
    parameters = inspect.signature(build_context).parameters
    assert parameters["transport_factory"].default is AnthropicTransport


def test_the_built_transport_ignores_anthropic_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    GIVEN ANTHROPIC_BASE_URL pointing elsewhere (this container sets it) and
          a fake key
    WHEN the transport the factory resolves sends one request (to a mock)
    THEN it goes to ENGINE_API_BASE_URL, and the key travels only there
    """
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://elsewhere.invalid")
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", SecretStr(FAKE_KEY))
    reply = json.loads(TRANSCRIPT.read_text(encoding="utf-8"))["replies"][-1]
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json=reply)

    def make(cfg: Settings) -> LLMTransport:
        return AnthropicTransport(cfg, http_transport=httpx2.MockTransport(handler))

    transport = engine_transport(None, make)
    assert transport is not None
    transport.send(
        LLMRequest(
            system="s",
            messages=({"role": "user", "content": "hi"},),
            max_tokens=16,
            cache=False,
        )
    )

    assert len(seen) == 1
    expected = httpx2.URL(settings.ENGINE_API_BASE_URL)
    assert (seen[0].url.scheme, seen[0].url.host) == (expected.scheme, expected.host)
    assert seen[0].headers["x-api-key"] == FAKE_KEY
    assert FAKE_KEY not in repr(transport)


# ---------------------------------------------------------------------------
# The editor
# ---------------------------------------------------------------------------


def test_the_editor_factory_builds_a_claude_editor_on_the_transport(
    tmp_path: Path, project: Project
) -> None:
    """
    GIVEN the factory's editor factory over a scripted transport
    WHEN the trial runner's call builds an editor for a run scope and edits
    THEN it is a ClaudeEditor that edits through WorktreeEditor (the four
         attacks of the h1 transcript are refused, the real edit lands) and
         consumes the transport's replies
    """
    replies = json.loads(TRANSCRIPT.read_text(encoding="utf-8"))["replies"]
    transport = ScriptedTransport(replies)
    worktree = tmp_path / "wt"
    shutil.copytree(DEDUPE_REPO, worktree, ignore=shutil.ignore_patterns("__pycache__"))
    (worktree / "dedupe" / "fast.py").symlink_to("core.py")

    editor = claude_editor_factory(transport, sleep=lambda _: None)(
        module_roots=frozenset({""}), reserved_modules=frozenset({"json"})
    )
    result = editor.edit(
        worktree,
        EditTask(
            hypothesis=_hypothesis(project),
            brief=TrialBrief(
                understanding=None, hotspots=(), protected=DEFAULT_PROTECTED_PATTERNS
            ),
            boundary="0123456789abcdef",
        ),
        Budget(cap_usd=5.0),
    )

    assert isinstance(editor, ClaudeEditor)
    assert result.error is None, result.error
    assert dict(result.written) == {"dedupe/core.py": H1_CORE.stat().st_size}
    assert (worktree / "dedupe" / "core.py").read_bytes() == H1_CORE.read_bytes()
    assert transport.remaining == 0


# ---------------------------------------------------------------------------
# Logging and the worktree root
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("before", "after"),
    [
        (logging.NOTSET, logging.INFO),
        (logging.DEBUG, logging.INFO),
        (logging.INFO, logging.INFO),
        (logging.WARNING, logging.WARNING),
    ],
)
def test_the_sdk_logger_is_never_left_below_info(
    project: Project, sdk_logger: logging.Logger, before: int, after: int
) -> None:
    """
    GIVEN the anthropic logger at some level (its DEBUG log prints request
          options)
    WHEN the context is built
    THEN the logger is at INFO or above, and a stricter level is kept
    """
    sdk_logger.setLevel(before)

    build_context(project, transport=_scripted())

    assert sdk_logger.level == after


@pytest.mark.parametrize("where", ["inside", "same", "outside"])
def test_a_worktree_root_overlapping_the_checkout_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, where: str
) -> None:
    """
    GIVEN WORKTREE_ROOT inside the user's checkout, equal to it, or the
          checkout inside WORKTREE_ROOT
    WHEN the context is built
    THEN PreflightError refuses it: trial worktrees and their cleanup must
         never live in (or contain) the user's checkout
    """
    base = Path(os.path.realpath(tmp_path))
    repo = base / "user"
    roots = {"inside": repo / ".cache" / "wt", "same": repo, "outside": base}
    root = roots[where]
    root.mkdir(parents=True, exist_ok=True)
    repo.mkdir(exist_ok=True)
    monkeypatch.setattr(settings, "WORKTREE_ROOT", root)
    project = Project(name="dedupe", root_path=str(repo))

    with pytest.raises(PreflightError, match="WORKTREE_ROOT"):
        build_context(project, transport=_scripted())


def test_a_symlinked_checkout_inside_the_worktree_root_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = Path(os.path.realpath(tmp_path))
    root, elsewhere = base / "wt-root", base / "elsewhere"
    (root / "repo").mkdir(parents=True)
    elsewhere.mkdir()
    (elsewhere / "link").symlink_to(root / "repo")
    monkeypatch.setattr(settings, "WORKTREE_ROOT", root)
    project = Project(name="dedupe", root_path=str(elsewhere / "link"))

    with pytest.raises(PreflightError, match="WORKTREE_ROOT"):
        build_context(project, transport=_scripted())


# ---------------------------------------------------------------------------
# Connect binds the runners to the resolved test command
# ---------------------------------------------------------------------------


class _Built:
    """A runner pair builder that records the project of every build."""

    def __init__(self) -> None:
        self.projects: list[Project] = []
        self.pairs: list[tuple[StubBaselineRunner, StubTrialRunner]] = []

    def __call__(self, project: Project) -> tuple[BaselineRunner, TrialRunner]:
        self.projects.append(project)
        pair = (
            StubBaselineRunner(ScriptedOutcome()),
            StubTrialRunner({}, default=ScriptedOutcome()),
        )
        self.pairs.append(pair)
        return pair


def _report(test_command: tuple[str, ...] | None) -> PreflightReport:
    return PreflightReport(
        head_commit=SHA,
        dirty_entries=(),
        git_version=(2, 43, 0),
        network="required",
        fs="required",
        workloads=(),
        test_command=test_command,
        extra_protected=(),
    )


def test_connect_rebuilds_the_runners_with_the_resolved_test_command(
    project: Project,
) -> None:
    """
    GIVEN runners built for a project whose test command is a bare python
    WHEN the connected preflight's check resolves it to an absolute path
    THEN the report passes through unchanged and the delegates now use
         runners built for the resolved project (the bare name would only
         resolve against the worktree)
    """
    raw = project.model_copy(update={"test_command": ("python", "-m", "unittest")})
    resolved = ("/usr/bin/python3", "-m", "unittest")
    built = _Built()
    runners = ConnectedRunners(raw, built)
    baseline, trial = ConnectedBaselineRunner(runners), ConnectedTrialRunner(runners)
    report = _report(resolved)
    inner = FakePreflight(report)

    assert baseline.current is built.pairs[0][0]
    returned = ConnectedPreflight(inner, runners).check(raw, [], [])

    assert returned is report
    assert [p.test_command for p in built.projects] == [raw.test_command, resolved]
    assert built.projects[1] == raw.model_copy(update={"test_command": resolved})
    assert (baseline.current, trial.current) == built.pairs[1]


def test_the_delegates_forward_every_argument(project: Project) -> None:
    """
    GIVEN the connected delegates over stub runners
    WHEN measure and run are called
    THEN the bound runners see the same arguments and their results return
    """
    built = _Built()
    runners = ConnectedRunners(project, built)
    hypothesis = _hypothesis(project)
    brief = TrialBrief(understanding=None, hotspots=(), protected=())

    rows = ConnectedBaselineRunner(runners).measure([], run_id="r1", commit=SHA)
    trial = ConnectedTrialRunner(runners).run(
        hypothesis,
        [],
        Baseline(commit=SHA),
        round=2,
        branch="engine/trial-r1-h1",
        budget_usd=0.5,
        brief=brief,
    )

    assert rows == ()
    assert (trial.hypothesis_id, trial.round, trial.branch) == (
        "h1",
        2,
        "engine/trial-r1-h1",
    )
    assert built.pairs[0][1].calls == [("h1", 2)]


@pytest.mark.parametrize("field", ["id", "root_path"])
def test_connect_refuses_a_project_the_context_was_not_built_for(
    project: Project, field: str
) -> None:
    """
    GIVEN a context's runners built for one project
    WHEN connect checks another project (other id or other root)
    THEN EngineError: the runners' git workspace is the first project's repo
    """
    runners = ConnectedRunners(project, _Built())
    value = "other-id" if field == "id" else "/elsewhere/repo"
    stranger = project.model_copy(update={field: value})

    with pytest.raises(EngineError, match="built for project"):
        ConnectedPreflight(FakePreflight(_report(None)), runners).check(
            stranger, [], []
        )


# ---------------------------------------------------------------------------
# The runners' notes
# ---------------------------------------------------------------------------


NOTE = "workload 'w': the 5 timed runs did not agree on one output"


class _NotingRunner:
    """Stands in for both git runners: one note per call through on_note."""

    def __init__(self, project: Project, **kwargs: object) -> None:
        self.note = cast(Callable[[str], None], kwargs["on_note"])

    def measure(
        self, workloads: Sequence[Workload], *, run_id: str, commit: str | None
    ) -> tuple[Measurement, ...]:
        self.note(f"baseline: {NOTE}")
        return ()

    def run(
        self,
        hypothesis: Hypothesis,
        workloads: Sequence[Workload],
        baseline: Baseline,
        *,
        round: int,
        branch: str,
        budget_usd: float,
        brief: TrialBrief,
    ) -> Trial:
        self.note(f"trial for hypothesis {hypothesis.id}: {NOTE}")
        raise RuntimeError("the fake trial stops here")


@pytest.fixture
def noting(project: Project, monkeypatch: pytest.MonkeyPatch) -> ConnectedRunners:
    """A context whose runners are ``_NotingRunner``s; its connected runners."""
    monkeypatch.setattr(factory, "GitBaselineRunner", _NotingRunner)
    monkeypatch.setattr(factory, "GitTrialRunner", _NotingRunner)
    ctx = build_context(project, transport=_scripted(), branch_prefix="aip/")
    assert isinstance(ctx.baseline_runner, ConnectedBaselineRunner)
    return ctx.baseline_runner.runners


def _trial(runners: ConnectedRunners, project: Project, branch: str) -> None:
    with pytest.raises(RuntimeError, match="fake trial"):
        ConnectedTrialRunner(runners).run(
            _hypothesis(project),
            [],
            Baseline(commit=SHA),
            round=1,
            branch=branch,
            budget_usd=1.0,
            brief=TrialBrief(understanding=None, hotspots=(), protected=()),
        )


def _note_events(
    logs: Sequence[MutableMapping[str, object]],
) -> list[tuple[object, ...]]:
    return [
        (log["run_id"], log["phase"], log["level"], log["message"], log["data"])
        for log in logs
        if log["event"] == "engine_event"
    ]


def test_a_baseline_note_is_a_warning_event_of_the_run(
    noting: ConnectedRunners,
) -> None:
    """
    GIVEN the factory's runners
    WHEN the baseline runner notes something (the nondeterministic-output
         warning) while measuring run run1
    THEN it is a runner_note warning event of run1's baseline phase, which
         emit sends to the graph's live stream (a log line outside a graph)
    """
    with capture_logs() as logs:
        rows = ConnectedBaselineRunner(noting).measure([], run_id="run1", commit=SHA)

    assert rows == ()
    note = f"baseline: {NOTE}"
    assert _note_events(logs) == [
        (
            "run1",
            "baseline",
            "warning",
            f"runner_note: {note}",
            {"code": "runner_note", "note": note},
        )
    ]


def test_a_trial_note_is_a_warning_event_of_the_run_its_branch_names(
    noting: ConnectedRunners, project: Project
) -> None:
    """
    GIVEN the factory's runners with the prefix aip/
    WHEN the trial runner notes something on aip/trial-run-1-h1 and then
         fails
    THEN the note is a trials-phase warning event of run run-1 (the run id
         may hold dashes), and once the call is over a late note is only a
         log line: no event is stamped with a run that is not running
    """
    with capture_logs() as logs:
        _trial(noting, project, "aip/trial-run-1-h1")
        noting.notes("late")

    note = f"trial for hypothesis h1: {NOTE}"
    assert _note_events(logs) == [
        (
            "run-1",
            "trials",
            "warning",
            f"runner_note: {note}",
            {"code": "runner_note", "note": note},
        )
    ]
    assert logs[-1] == {"event": "runner_note", "note": "late", "log_level": "info"}


@pytest.mark.parametrize(
    "branch", ["engine/trial-run1-h1", "aip/trial-run1-h2", "aip/trial--h1"]
)
def test_a_note_on_a_branch_that_names_no_run_is_a_log_line(
    noting: ConnectedRunners, project: Project, branch: str
) -> None:
    """A branch outside the prefix, of another hypothesis or with no run id
    names no run: the note is logged, never an event (the runner refuses
    such a branch anyway)."""
    with capture_logs() as logs:
        _trial(noting, project, branch)

    assert logs == [
        {
            "event": "runner_note",
            "note": f"trial for hypothesis h1: {NOTE}",
            "log_level": "info",
        }
    ]


def test_note_text_is_printable_and_capped() -> None:
    """
    GIVEN a note with control characters and 1000 more characters (notes can
          quote repo-chosen text)
    WHEN it is logged and when it is an event
    THEN both carry the printable, capped text only
    """
    notes = RunNotes()
    raw = "a\x1b[31mb\nc" + "x" * 1000
    shown = "a?[31mb?c" + "x" * (RunNotes.CAP - 9)

    with capture_logs() as logs:
        notes(raw)
        with notes.scope("run1", RunPhase.baseline):
            notes(raw)

    assert logs[0] == {"event": "runner_note", "note": shown, "log_level": "info"}
    assert logs[1]["message"] == f"runner_note: {shown}"
    assert logs[1]["data"] == {"code": "runner_note", "note": shown}
    assert len(shown) == RunNotes.CAP


class _OneNode(TypedDict):
    done: bool


def test_inside_a_graph_a_runner_note_reaches_the_live_stream(
    noting: ConnectedRunners,
) -> None:
    """
    GIVEN a graph node that measures through the connected baseline runner
    WHEN the graph is streamed in custom mode (what Orchestrator.stream reads)
    THEN the runner's note arrives there as an EngineEvent of the run
    """

    def baseline(state: _OneNode) -> dict[str, bool]:
        ConnectedBaselineRunner(noting).measure([], run_id="run1", commit=SHA)
        return {"done": True}

    graph = StateGraph(_OneNode)
    graph.add_node("baseline", baseline)
    graph.add_edge(START, "baseline")
    graph.add_edge("baseline", END)

    chunks = list(graph.compile().stream({"done": False}, stream_mode="custom"))

    (event,) = [EngineEvent.model_validate(chunk) for chunk in chunks]
    assert (event.run_id, event.phase, event.level) == (
        "run1",
        RunPhase.baseline,
        EventLevel.warning,
    )
    assert event.data == {"code": "runner_note", "note": f"baseline: {NOTE}"}
