"""The factory's Step 3 wiring (U10): role transports, discovery, retry, noise, quality.

Nothing here talks to the Claude API: a key is a fake ``SecretStr`` and every
transport a ``ScriptedTransport`` on its role's settings (it stands for
``AnthropicTransport``). ``_spy`` records the classes the factory builds; the
retry test runs the real ``GitTrialRunner`` on a copy of the dedupe fixture,
with ``_Crash`` standing for ``procrun.run_once`` and ``_Edits`` for
``ClaudeEditor``.
"""

from __future__ import annotations

import dataclasses
import inspect
import os
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

import pytest
from pydantic import SecretStr
from structlog.testing import capture_logs

from autonomous_ai_agents.clients.budget import Budget
from autonomous_ai_agents.clients.cost import chain, preflight_estimate
from autonomous_ai_agents.clients.transport import LLMTransport, ScriptedTransport
from autonomous_ai_agents.common.config import (
    Role,
    Settings,
    role_chain,
    role_settings,
    settings,
)
from autonomous_ai_agents.common.errors import EngineError, LLMConfigError
from autonomous_ai_agents.common.models import (
    METRIC_TESTS_PASSED,
    Baseline,
    BuiltinMeasure,
    ChangeClass,
    FrozenFile,
    Hypothesis,
    HypothesisSource,
    Measurement,
    NoiseCalibration,
    Project,
    QualityCheck,
    RunPhase,
    RunStats,
    TrialStatus,
    Workload,
)
from autonomous_ai_agents.execution.combine import GitCombiner
from autonomous_ai_agents.execution.procrun import OutputCaps, RunSample
from autonomous_ai_agents.execution.profiler import CProfiler
from autonomous_ai_agents.execution.protocols import EditResult, EditTask, TrialBrief
from autonomous_ai_agents.execution.runner import (
    ScriptedOutcome,
    StubBaselineRunner,
    StubTrialRunner,
)
from autonomous_ai_agents.execution.sandbox import SandboxPolicy
from autonomous_ai_agents.execution.trial_runner import (
    GitBaselineRunner,
    GitTrialRunner,
    NoteTap,
)
from autonomous_ai_agents.optimization.anticheat import DEFAULT_PROTECTED_PATTERNS
from autonomous_ai_agents.optimization.hypothesis_source import (
    ClaudeHypothesisGenerator,
    ClaudeTechniqueMatcher,
)
from autonomous_ai_agents.optimization.judges import default_judges
from autonomous_ai_agents.orchestrator import factory
from autonomous_ai_agents.orchestrator.factory import (
    ConnectedBaselineRunner,
    ConnectedRunners,
    RunNotes,
    build_context,
    min_trial_budget,
)
from autonomous_ai_agents.orchestrator.nodes import NodeContext
from autonomous_ai_agents.persistence.repository import InMemoryRepository
from autonomous_ai_agents.research.playbook import load_playbook

FAKE_KEY = "sk-ant-test-not-a-real-key-0000"  # nosec B105: a test value
SONNET = "claude-sonnet-5-5"
SHA = "0123456789abcdef0123456789abcdef01234567"
DEDUPE = Path(__file__).resolve().parents[1] / "fixtures" / "dedupe_repo"
QUALITY = QualityCheck(
    name="acc", measure=BuiltinMeasure.accuracy, labels="data/labels.txt",
    frozen_paths=("data/labels.txt",),
)  # fmt: skip
STEP2 = {f.name for f in dataclasses.fields(NodeContext)} - {
    "generator", "matcher", "retrieval", "generated_classes", "generator_n",
    "generator_max_calls", "matcher_k", "discovery_max_share",
    "fix_retries_per_run", "playbook", "quality", "default_output_check",
    "calibrator", "calibration_blocks", "confirm_winners", "portfolio_rounds",
}  # fmt: skip


@pytest.fixture(autouse=True)
def no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", None)


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Project:
    base = Path(os.path.realpath(tmp_path))
    monkeypatch.setattr(settings, "WORKTREE_ROOT", base / "wt-root")
    (base / "user").mkdir()
    return Project(name="dedupe", root_path=str(base / "user"))


def _on(role: Role) -> ScriptedTransport:
    return ScriptedTransport([], cfg=role_settings(settings, role))


def _no_factory(cfg: Settings) -> LLMTransport:
    raise AssertionError("an injected engine transport means no transport is built")


def _spy(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> list[tuple[tuple[object, ...], dict[str, object]]]:
    """Replace ``factory.<name>`` by a wrapper recording each call's arguments."""
    seen: list[tuple[tuple[object, ...], dict[str, object]]] = []
    real = getattr(factory, name)

    def recording(*args: object, **kwargs: object) -> object:
        seen.append((args, kwargs))
        return real(*args, **kwargs)

    monkeypatch.setattr(factory, name, recording)
    return seen


# ---------------------------------------------------------------------------
# Role transports (security: each role bills its own chain)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("retrieval", ["blind", "matched"])
def test_with_a_key_each_role_gets_a_transport_built_from_its_role_settings(
    project: Project, monkeypatch: pytest.MonkeyPatch, retrieval: str
) -> None:
    """The engine's transport from the settings, the editor's, generator's (and
    in matched retrieval the matcher's) each from ``role_settings``; each
    adapter is built on its own; blind builds no matcher transport."""
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", SecretStr(FAKE_KEY))
    monkeypatch.setattr(settings, "EDITOR_MODEL", SONNET)
    monkeypatch.setattr(settings, "RESEARCH_RETRIEVAL", retrieval)
    built: list[Settings] = []
    made: list[ScriptedTransport] = []

    def make(cfg: Settings) -> LLMTransport:
        built.append(cfg)
        made.append(ScriptedTransport([], cfg=cfg))
        return made[-1]

    spies = {
        name: _spy(monkeypatch, name)
        for name in ("ClaudeUnderstander", "claude_editor_factory",
                     "ClaudeHypothesisGenerator", "ClaudeTechniqueMatcher")
    }  # fmt: skip

    def nap(seconds: float) -> None:
        raise AssertionError("no test here backs off")

    ctx = build_context(project, transport_factory=make, sleep=nap)

    assert all(calls[0][1]["sleep"] is nap for calls in spies.values() if calls)
    roles: list[Role] = ["editor", "generator"]
    roles += ["matcher"] if retrieval == "matched" else []
    assert built == [settings, *(role_settings(settings, r) for r in roles)]
    used = [calls[0][0][0] for calls in spies.values() if calls]
    assert used == made and len(set(map(id, used))) == len(made)
    assert [tuple(t.chain) for t in made] == [
        chain(settings),
        *(role_chain(settings, r) for r in roles),
    ]
    assert isinstance(ctx.generator, ClaudeHypothesisGenerator)
    if retrieval == "matched":
        assert isinstance(ctx.matcher, ClaudeTechniqueMatcher)
    else:
        assert ctx.matcher is None and not spies["ClaudeTechniqueMatcher"]


def test_an_injected_engine_transport_serves_only_the_editor_on_its_chain(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Step 2's shared transport: the editor reuses the injected one while it
    bills the editor's chain; even with a key nothing else is built (a
    captured run gains no uncaptured transport), so no generator or matcher;
    once ``EDITOR_MODEL`` differs the editor refuses it, unless its own is
    given."""
    engine = ScriptedTransport([])
    editors = _spy(monkeypatch, "claude_editor_factory")
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", SecretStr(FAKE_KEY))

    ctx = build_context(project, transport=engine, transport_factory=_no_factory)

    assert editors[0][0][0] is engine
    assert (ctx.generator, ctx.matcher) == (None, None)
    monkeypatch.setattr(settings, "ENGINE_FALLBACKS", False)  # one chain for all
    monkeypatch.setattr(settings, "GENERATOR_MODEL", settings.ENGINE_MODEL)
    alone = ScriptedTransport([])
    assert tuple(alone.chain) == role_chain(settings, "generator")
    same = build_context(project, transport=alone, transport_factory=_no_factory)
    assert same.generator is None  # only the editor may reuse it
    monkeypatch.setattr(settings, "EDITOR_MODEL", SONNET)
    with pytest.raises(LLMConfigError, match="editor"):
        build_context(project, transport=engine)
    own = _on("editor")
    build_context(project, transport=engine, role_transports={"editor": own})
    assert editors[-1][0][0] is own


@pytest.mark.parametrize("role", ["editor", "generator", "matcher"])
def test_an_injected_role_transport_on_another_chain_is_refused(
    project: Project, monkeypatch: pytest.MonkeyPatch, role: Role
) -> None:
    monkeypatch.setattr(settings, "EDITOR_MODEL", SONNET)
    monkeypatch.setattr(settings, "RESEARCH_RETRIEVAL", "matched")
    roles: tuple[Role, ...] = ("editor", "generator", "matcher")
    given: dict[Role, LLMTransport] = {r: _on(r) for r in roles}
    given[role] = ScriptedTransport([])  # the engine chain
    with pytest.raises(ValueError, match=f"the {role} transport bills"):
        build_context(project, role_transports=given)
    with pytest.raises(ValueError, match="transport="):
        build_context(project, role_transports={"engine": ScriptedTransport([])})


@pytest.mark.parametrize(
    "given",
    [{"editer": "editor"}, {"generator": None}, {"matcher": None}],
    ids=["unknown role", "None generator", "None matcher"],
)
def test_role_transports_refuse_an_unknown_role_or_none_before_building(
    project: Project, monkeypatch: pytest.MonkeyPatch, given: dict[str, Role | None]
) -> None:
    """A mistyped role or a None would leave that role to be built from the
    key: a caller who thinks it captured the role is billed on a real one."""
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", SecretStr(FAKE_KEY))
    transports = {k: None if v is None else _on(v) for k, v in given.items()}
    ((name, _),) = given.items()
    with pytest.raises(ValueError, match=f"unknown role transport {name!r}"):
        build_context(
            project,
            role_transports=cast(Mapping[Role, LLMTransport], transports),
            transport_factory=_no_factory,
        )


def test_an_injected_editor_and_an_editor_transport_are_refused(
    project: Project,
) -> None:
    with pytest.raises(ValueError, match="editor= or an editor transport"):
        build_context(
            project,
            editor=lambda **_: _Edits([]),
            role_transports={"editor": _on("editor")},
        )


# ---------------------------------------------------------------------------
# Discovery, the floors and the knobs
# ---------------------------------------------------------------------------


def test_blind_gives_no_techniques_and_matched_the_playbook(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    given: dict[Role, LLMTransport] = {"generator": _on("generator"), "matcher": _on("matcher")}  # fmt: skip
    blind = build_context(project, transport=ScriptedTransport([]), role_transports=given)  # fmt: skip
    assert (blind.retrieval, blind.techniques, blind.playbook) == ("blind", (), ())
    assert blind.matcher is None and isinstance(blind.generator, ClaudeHypothesisGenerator)  # fmt: skip
    monkeypatch.setattr(settings, "RESEARCH_RETRIEVAL", "matched")
    matched = build_context(project, transport=ScriptedTransport([]), role_transports=given)  # fmt: skip
    assert (matched.retrieval, matched.techniques) == ("matched", ())
    assert matched.playbook == load_playbook() != ()
    assert isinstance(matched.matcher, ClaudeTechniqueMatcher)


def test_the_floor_prices_the_editor_chain_and_bounds_the_retry(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "EDITOR_MODEL", SONNET)
    trials = _spy(monkeypatch, "GitTrialRunner")
    floor = preflight_estimate(
        0, settings.EDITOR_MAX_TOKENS, (SONNET,), settings.MODEL_PRICING
    )
    given: dict[Role, LLMTransport] = {"editor": _on("editor")}
    ctx = build_context(project, transport=ScriptedTransport([]), role_transports=given)  # fmt: skip
    explicit = build_context(project, editor=lambda **_: _Edits([]), min_trial_budget_usd=0.25)  # fmt: skip
    assert min_trial_budget() == floor == ctx.min_trial_budget_usd > 0
    assert explicit.min_trial_budget_usd == 0.25
    for _, kwargs in trials:
        assert kwargs["retry_floor_usd"] == floor
        assert (kwargs["fix_retries"], kwargs["paired"]) == (1, True)


@pytest.mark.parametrize("flipped", [False, True])
def test_the_new_knobs_come_from_the_settings(
    project: Project, monkeypatch: pytest.MonkeyPatch, flipped: bool
) -> None:
    """Flipped, paired knobs differ (per-trial 0, per-run 1; paired off,
    confirmation on; output check off; 2 blocks), so no knob can stand in
    for another (D12's two retry caps above all)."""
    values: dict[str, object] = {
        "EDITOR_FIX_RETRIES": 0, "EDITOR_FIX_RETRIES_PER_RUN": 1,
        "PAIRED_TRIALS": False, "DEFAULT_OUTPUT_CHECK": False,
        "CONFIRM_WINNERS": True, "NOISE_CALIBRATION_BLOCKS": 2,
        "GENERATED_CLASSES": (ChangeClass.efficiency,), "GENERATOR_N": 7,
        "GENERATOR_MAX_CALLS": 0, "MATCHER_K": 4, "DISCOVERY_MAX_SHARE": 0.1,
    }  # fmt: skip
    for key, value in values.items() if flipped else ():
        monkeypatch.setattr(settings, key, value)
    trials = _spy(monkeypatch, "GitTrialRunner")
    ctx = build_context(project, transport=ScriptedTransport([]))
    assert ctx.calibrator is cast(object, ctx.baseline_runner)  # blocks 3, then 2
    assert (trials[-1][1]["fix_retries"], trials[-1][1]["paired"]) == (
        settings.EDITOR_FIX_RETRIES, settings.PAIRED_TRIALS,
    )  # fmt: skip
    assert (
        ctx.fix_retries_per_run, ctx.default_output_check, ctx.confirm_winners,
        ctx.calibration_blocks, ctx.generated_classes, ctx.generator_n,
        ctx.generator_max_calls, ctx.matcher_k, ctx.discovery_max_share,
    ) == (
        settings.EDITOR_FIX_RETRIES_PER_RUN, settings.DEFAULT_OUTPUT_CHECK,
        settings.CONFIRM_WINNERS, settings.NOISE_CALIBRATION_BLOCKS,
        settings.GENERATED_CLASSES, settings.GENERATOR_N,
        settings.GENERATOR_MAX_CALLS, settings.MATCHER_K,
        settings.DISCOVERY_MAX_SHARE,
    )  # fmt: skip


def test_the_default_context_keeps_every_step2_knob(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every field Step 2's factory set is what it set then; every new field
    is the owner's settings default (D4: output check, paired trials,
    confirmation, 3 blocks; one fix retry, which stays off until the trials
    node grants it, below); no generator without a generator transport."""
    trials = _spy(monkeypatch, "GitTrialRunner")
    ctx = build_context(project, transport=ScriptedTransport([]))
    assert isinstance(ctx.calibrator, ConnectedBaselineRunner)
    assert trials[-1][1]["paired"] is True
    step2 = {
        "judges": default_judges(settings.NOISE_MULTIPLIER), "candidates": (),
        "hotspots": (), "techniques": (), "min_runs": settings.MIN_RUNS,
        "protected_patterns": DEFAULT_PROTECTED_PATTERNS,
        "branch_prefix": settings.TRIAL_BRANCH_PREFIX,
        "max_hypotheses_per_round": 3, "min_trial_budget_usd": preflight_estimate(
            0, settings.EDITOR_MAX_TOKENS, chain(settings), settings.MODEL_PRICING),
    }  # fmt: skip
    seams = {"runner", "baseline_runner", "repository", "preflight", "understander",
             "profiler", "combiner", "publisher"}  # fmt: skip
    assert set(step2) | seams == STEP2
    assert {name: getattr(ctx, name) for name in step2} == step2
    assert isinstance(ctx.repository, InMemoryRepository)
    assert all(getattr(ctx, name) is not None for name in seams)
    new = {
        "generator": None, "matcher": None, "retrieval": "blind",
        "generated_classes": (ChangeClass.efficiency, ChangeClass.behaviour),
        "generator_n": 5, "generator_max_calls": 2, "matcher_k": 3,
        "discovery_max_share": 0.25, "fix_retries_per_run": 1, "playbook": (),
        "quality": None, "default_output_check": True, "calibrator": ctx.baseline_runner,
        "calibration_blocks": 3, "confirm_winners": True, "portfolio_rounds": 0,
    }  # fmt: skip
    assert {name: getattr(ctx, name) for name in new} == new


SCORED = ("GitBaselineRunner", "GitTrialRunner", "GitCombiner", "CProfiler")
REAL = {"GitBaselineRunner": GitBaselineRunner, "GitTrialRunner": GitTrialRunner,
        "GitCombiner": GitCombiner, "CProfiler": CProfiler}  # fmt: skip
STEP2_MODE: dict[str, object] = {
    "PAIRED_TRIALS": False, "CONFIRM_WINNERS": False, "NOISE_CALIBRATION_BLOCKS": 0,
    "DEFAULT_OUTPUT_CHECK": False, "EDITOR_FIX_RETRIES": 0,
    "EDITOR_FIX_RETRIES_PER_RUN": 0,
}  # fmt: skip


def test_with_the_noise_rule_output_check_and_retry_off_the_context_is_step2s(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each new field is ``NodeContext``'s own (Step 2) default, and every
    runner is built with its constructor's Step 2 defaults."""
    for key, value in STEP2_MODE.items():
        monkeypatch.setattr(settings, key, value)
    seen = {name: _spy(monkeypatch, name) for name in SCORED}
    ctx = build_context(project, transport=ScriptedTransport([]))
    defaults = {f.name: f.default for f in dataclasses.fields(NodeContext)}
    for name in defaults.keys() - STEP2:
        assert getattr(ctx, name) == defaults[name], name
    for name, keys in {
        "GitTrialRunner": ("fix_retries", "paired", "scorer"),
        "GitBaselineRunner": ("scorer", "scorer_notes"),
        "GitCombiner": ("scorer",), "CProfiler": ("scorer",),
    }.items():  # fmt: skip
        params = inspect.signature(REAL[name]).parameters
        kwargs = seen[name][-1][1]
        assert {k: kwargs[k] for k in keys} == {k: params[k].default for k in keys}


# ---------------------------------------------------------------------------
# Quality: one scorer, every runner, the profiler, the judges
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("quality", [None, QUALITY])
def test_a_quality_check_puts_one_scorer_in_every_runner_and_the_profiler(
    project: Project, monkeypatch: pytest.MonkeyPatch, quality: QualityCheck | None
) -> None:
    launched: list[Sequence[str]] = []

    def launcher(
        argv: Sequence[str], cwd: Path, env: Mapping[str, str], sandbox: SandboxPolicy,
        timeout_s: float, caps: OutputCaps, *, fresh_dirs: Sequence[Path] = (),
    ) -> RunSample:  # fmt: skip
        launched.append(argv)
        return RunSample(1, 0.0, 0.0, 1, 0, True, True, "0" * 64, b"", 0, b"")

    seen = {name: _spy(monkeypatch, name) for name in (*SCORED, "FrozenScorer")}
    ctx = build_context(project, transport=ScriptedTransport([]), network="best_effort",
                        fs="off", run=launcher, quality=quality)  # fmt: skip

    assert ctx.quality is quality
    assert ctx.judges == default_judges(settings.NOISE_MULTIPLIER, quality=quality)
    scorers = {id(seen[name][-1][1]["scorer"]) for name in SCORED}
    baseline = seen["GitBaselineRunner"][-1][1]
    if quality is None:
        assert scorers == {id(None)} and baseline["scorer_notes"] is None
        assert not seen["FrozenScorer"]
        return
    ((check,), made) = seen["FrozenScorer"][0]
    assert check is quality and (made["network"], made["fs"]) == ("best_effort", "off")
    tap = made["run"]
    assert isinstance(tap, NoteTap) and baseline["scorer_notes"] is tap
    tap(("x",), Path("/"), {}, cast(SandboxPolicy, None), 1.0, OutputCaps(1, 1, 1))
    assert launched == [("x",)]  # the scorer launches through the context's launcher
    (scorer,) = scorers
    assert scorer != id(None) and len(seen["FrozenScorer"]) == 1
    assert ctx.combiner is not None and ctx.combiner._quality.mask == QUALITY.frozen_paths  # type: ignore[attr-defined]  # fmt: skip
    assert ctx.profiler is not None and ctx.profiler._mask == QUALITY.frozen_paths  # type: ignore[attr-defined]  # fmt: skip


class _Calibrating(StubBaselineRunner):
    """A calibrator that notes once while it calibrates, as the git runner's
    ``calibration:`` notes do."""

    quality_files = (FrozenFile(path="l.txt", sha256="a" * 64, size=1),)
    label_leaks = ("in.csv column 2",)
    notes: RunNotes | None = None

    def calibrate(
        self, workloads: Sequence[Workload], *, run_id: str, commit: str, blocks: int
    ) -> NoiseCalibration:
        if self.notes is not None:
            self.notes("calibration: x")
        return NoiseCalibration(blocks=blocks, gaps={}, floor=0.02)


@pytest.mark.parametrize("runner", [StubBaselineRunner, _Calibrating])
def test_the_connected_baseline_passes_quality_files_leaks_and_calibration_through(
    project: Project, runner: type[StubBaselineRunner]
) -> None:
    notes = RunNotes()

    def build(bound: Project) -> tuple[StubBaselineRunner, StubTrialRunner]:
        stub = runner(ScriptedOutcome())
        if isinstance(stub, _Calibrating):
            stub.notes = notes
        return stub, StubTrialRunner({})

    connected = ConnectedBaselineRunner(ConnectedRunners(project, build, notes=notes))
    if runner is StubBaselineRunner:
        assert (connected.quality_files, connected.label_leaks) == ((), ())
        with pytest.raises(EngineError, match="cannot calibrate"):
            connected.calibrate([], run_id="r1", commit=SHA, blocks=2)
        return
    assert connected.quality_files == _Calibrating.quality_files
    assert connected.label_leaks == _Calibrating.label_leaks
    with capture_logs() as logs:
        assert connected.calibrate([], run_id="r1", commit=SHA, blocks=2).blocks == 2
    events = [log for log in logs if log["event"] == "engine_event"]
    assert [(e["run_id"], e["phase"], e["message"]) for e in events] == [
        ("r1", RunPhase.baseline.value, "runner_note: calibration: x")
    ]


# ---------------------------------------------------------------------------
# The retry is wired and stays off until the trials node grants one (U16)
# ---------------------------------------------------------------------------

CORE = "dedupe/core.py"
OLD, RAISING = "        if item not in result:\n", "        if item not in seen:\n"
BROKEN = (
    (DEDUPE / CORE).read_text().replace(OLD, RAISING + "            seen.add(item)\n")
)
DECL = "    result: list[int] = []\n"
FIXED = BROKEN.replace(DECL, "    seen: set[int] = set()\n" + DECL)
GIT_ENV = {"PATH": os.defpath, "HOME": os.devnull, "GIT_CONFIG_GLOBAL": os.devnull,
           "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "U", "GIT_COMMITTER_NAME": "U",
           "GIT_AUTHOR_EMAIL": "u@example.invalid", "GIT_COMMITTER_EMAIL": "u@example.invalid"}  # fmt: skip


class _Edits:
    def __init__(self, attempts: list[str]) -> None:
        self.attempts, self.tasks = attempts, list[EditTask]()

    def edit(self, worktree: Path, task: EditTask, budget: Budget) -> EditResult:
        self.tasks.append(task)
        (worktree / CORE).write_text(self.attempts[len(self.tasks) - 1])
        return EditResult({CORE: 1}, cost_usd=0.0, tokens_used=1)


class _Crash:
    """The first workload run raises NameError on the edited line."""

    def __init__(self) -> None:
        self.crashed = False

    def __call__(
        self, argv: Sequence[str], cwd: Path, env: Mapping[str, str], sandbox: SandboxPolicy,
        timeout_s: float, caps: OutputCaps, *, fresh_dirs: Sequence[Path] = (),
    ) -> RunSample:  # fmt: skip
        err, code = (b"Ran 11 tests in 0.01s\n\nOK\n", 0) if "unittest" in argv else (b"", 0)  # fmt: skip
        if "unittest" not in argv and not self.crashed:
            line = BROKEN.splitlines().index(RAISING.rstrip("\n")) + 1
            self.crashed, code = True, 1
            err = (f'Traceback (most recent call last):\n  File "{cwd}/{CORE}", line {line},'
                   f" in unique_in_order\n{RAISING}NameError: name 'seen' is not defined\n").encode()  # fmt: skip
        return RunSample(10_000_000, 0.01, 0.0, 1 << 20, code, True, True, "1" * 64, b"", 0, err)  # fmt: skip


@pytest.mark.parametrize(("left", "attempts"), [(0, 1), (1, 2)])
def test_the_factory_runner_retries_only_when_the_brief_grants_it(
    project: Project, monkeypatch: pytest.MonkeyPatch, left: int, attempts: int
) -> None:
    monkeypatch.setattr(settings, "PAIRED_TRIALS", False)
    repo = Path(project.root_path)
    shutil.copytree(DEDUPE, repo, dirs_exist_ok=True)
    for args in (
        ("init", "-q", "-b", "main"),
        ("add", "-A"),
        ("commit", "-qm", "base"),
    ):
        subprocess.run(["git", "-C", str(repo), *args], env=GIT_ENV, check=True)
    base = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], env=GIT_ENV,
                          capture_output=True, check=True).stdout.decode().strip()  # fmt: skip
    unittest = (sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", ".")
    project = project.model_copy(update={"test_command": unittest})
    edits = _Edits([BROKEN, FIXED])
    ctx = build_context(project, editor=lambda **_: edits, network="off", fs="off", run=_Crash())  # fmt: skip
    workload = Workload(project_id=project.id, name="d", warmup_runs=0, timeout_s=60.0,
                        command=(sys.executable, "-m", "dedupe.main", "200"))  # fmt: skip
    suite = Measurement(workload_id=workload.id, metric=METRIC_TESTS_PASSED,
                        stats=RunStats.from_samples((1.0,), unit="bool"), samples=(1.0,),
                        hardware={"tests_counted": 11})  # fmt: skip
    hypothesis = Hypothesis(project_id=project.id, source=HypothesisSource.novel,
                            title="a set", rationale="O(1)", change_class=ChangeClass.efficiency,
                            expected_gain=0.5, provability=0.9, risk=0.1)  # fmt: skip
    brief = TrialBrief(None, (), DEFAULT_PROTECTED_PATTERNS, fix_retries_left=left)
    trial = ctx.runner.run(
        hypothesis, [workload], Baseline(commit=base, measurements=(suite,)), round=1,
        branch=f"engine/trial-run1-{hypothesis.id}", budget_usd=1.0, brief=brief,
    )  # fmt: skip
    assert (trial.attempts, len(edits.tasks)) == (attempts, attempts)
    assert (trial.status is TrialStatus.measured) is (attempts == 2)
    assert TrialBrief(None, (), ()).fix_retries_left == 0  # the default grants none
