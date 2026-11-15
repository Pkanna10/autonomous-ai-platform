"""X2-DT U6: the factory's wiring of stacked rounds (dt-design sections 1
and 6; O63, amended by O71).

- Off (``STACKED_ROUNDS`` at its default): no ``GitStacker`` is built and
  the context's stacking fields are ``NodeContext``'s own defaults, so the
  context is today's.
- On: a ``GitStacker`` on the very ``GitWorkspace`` the combiner uses, and
  ``stack_rounds`` set.
- Refused with ``ValueError``, before any transport is built: stacking with
  a quality check, or with ``DEFAULT_OUTPUT_CHECK`` off; a resumed run whose
  stored state holds an open stack ledger, when the context would not stack;
  stacking a resumed run whose stored baseline has no ``output_equivalence``
  guardrail (the run's recorded mode, not only the context's).
- O71: ``SITE_STACKS="on"`` beside stacking builds, and the combiner carries
  ``"on"``. Until U5c lifts ``NodeContext._check_stack_knobs``' refusal,
  ``test_site_stacks_on_with_stacking_builds`` fails on that refusal.

Swap points: ``factory.GitStacker`` and ``factory.GitCombiner`` are wrapped
by recorders that call the real classes, so the shared workspace is read
from their constructor arguments; the transport is a ``ScriptedTransport``
and the transport factory refuses to be called. The resumed states are
hand-built mappings (what ``Repository.get_run`` or a checkpoint returns),
the ledger a real ``StackLedger``. Nothing launches repository code or git.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from pathlib import Path

import pytest
from pydantic import SecretStr

from autonomous_ai_agents.clients.transport import LLMTransport, ScriptedTransport
from autonomous_ai_agents.common.config import Settings, settings
from autonomous_ai_agents.common.models import (
    Baseline,
    BuiltinMeasure,
    Combination,
    Guardrail,
    GuardrailKind,
    Project,
    QualityCheck,
    RoundBase,
    StackLedger,
)
from autonomous_ai_agents.execution.combine import GitCombiner
from autonomous_ai_agents.execution.git import GitWorkspace
from autonomous_ai_agents.execution.stacking import GitStacker
from autonomous_ai_agents.orchestrator import factory
from autonomous_ai_agents.orchestrator.factory import build_context
from autonomous_ai_agents.orchestrator.nodes import NodeContext

FAKE_KEY = "sk-ant-test-not-a-real-key-0000"  # nosec B105: a test value
ORIGIN = "0123456789abcdef0123456789abcdef01234567"
TIP = "89abcdef0123456789abcdef0123456789abcdef"
QUALITY = QualityCheck(
    name="acc", measure=BuiltinMeasure.accuracy, labels="data/labels.txt",
    frozen_paths=("data/labels.txt",),
)  # fmt: skip
STACK_FIELDS = ("stack_rounds", "stacker")


@pytest.fixture(autouse=True)
def no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", None)


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Project:
    base = tmp_path.resolve()
    monkeypatch.setattr(settings, "WORKTREE_ROOT", base / "wt-root")
    (base / "user").mkdir()
    return Project(name="dedupe", root_path=str(base / "user"))


@pytest.fixture
def stacking(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "STACKED_ROUNDS", True)


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


def _no_factory(cfg: Settings) -> LLMTransport:
    raise AssertionError("a refused build must not build a transport")


def _guardrail(kind: GuardrailKind, project: Project) -> Guardrail:
    return Guardrail(project_id=project.id, kind=kind, description=kind.value)


def _baseline(project: Project, *kinds: GuardrailKind) -> Baseline:
    return Baseline(
        commit=ORIGIN, guardrails=tuple(_guardrail(kind, project) for kind in kinds)
    )


def _ledger(baseline: Baseline, *, closed: bool) -> StackLedger:
    combination = Combination(base_commit=ORIGIN, tip_commit=TIP,
                              applied_trial_ids=("t-1",), holds=True,
                              summary="t-1 applied; holds")  # fmt: skip
    first = RoundBase(round=1, base_commit=ORIGIN, offered_trial_ids=("t-1",),
                      combination=combination, adopted=True, tip_commit=TIP,
                      floor=0.025, reason="held")  # fmt: skip
    ledger = StackLedger(origin_commit=ORIGIN, origin_baseline=baseline,
                         rounds=(first,))  # fmt: skip
    return ledger.closed(None, None) if closed else ledger


def _resumed(
    project: Project, *, stack: object = None, exact: bool = True
) -> dict[str, object]:
    """A stored run's state, as far as the factory reads it."""
    kinds = (GuardrailKind.output_equivalence,) if exact else ()
    baseline = _baseline(project, GuardrailKind.tests_pass, *kinds)
    if stack == "open" or stack == "closed":
        stack = _ledger(baseline, closed=stack == "closed")
    return {"run_id": "run-1", "baseline": baseline, "stack": stack}


def _build(project: Project, **kwargs: object) -> NodeContext:
    return build_context(project, transport=ScriptedTransport([]), **kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Off and on
# ---------------------------------------------------------------------------


def test_off_builds_no_stacker(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    GIVEN STACKED_ROUNDS at its product default (off)
    WHEN the context is built
    THEN no GitStacker is constructed, and the stacking fields are
         NodeContext's own defaults (today's context)
    """
    assert settings.STACKED_ROUNDS is False
    stackers = _spy(monkeypatch, "GitStacker")

    ctx = _build(project)

    assert stackers == []
    defaults = {f.name: f.default for f in dataclasses.fields(NodeContext)}
    assert {name: getattr(ctx, name) for name in STACK_FIELDS} == {
        name: defaults[name] for name in STACK_FIELDS
    }
    assert (ctx.stack_rounds, ctx.stacker) == (False, None)


@pytest.mark.usefixtures("stacking")
def test_on_builds_a_git_stacker_on_the_combiners_workspace(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    GIVEN STACKED_ROUNDS on, the default output check and no quality check
    WHEN the context is built
    THEN it stacks, through one GitStacker on the same GitWorkspace (the
         project's checkout) as the combiner, and the combiner is GitCombiner
    """
    stackers = _spy(monkeypatch, "GitStacker")
    combiners = _spy(monkeypatch, "GitCombiner")

    ctx = _build(project)

    assert ctx.stack_rounds is True
    assert isinstance(ctx.stacker, GitStacker)
    assert isinstance(ctx.combiner, GitCombiner)
    assert len(stackers) == len(combiners) == 1
    git = stackers[0][1]["git"]
    assert isinstance(git, GitWorkspace)
    assert git is combiners[0][1]["git"]
    assert git.repo == Path(project.root_path)
    assert ctx.default_output_check is True
    assert ctx.quality is None


def test_stacking_changes_only_the_stacking_fields(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    GIVEN the same settings, with STACKED_ROUNDS off and then on
    WHEN the two contexts are built
    THEN every field but stack_rounds and stacker is the same value, or the
         same class for a seam: the off context is the on one without
         stacking, so off is today's context
    """

    def fingerprint(ctx: NodeContext) -> dict[str, object]:
        plain = (bool, int, float, str, tuple, type(None))
        return {
            f.name: (
                value if isinstance(value := getattr(ctx, f.name), plain)
                else type(value).__qualname__
            )
            for f in dataclasses.fields(NodeContext)
            if f.name not in STACK_FIELDS
        }  # fmt: skip

    off = _build(project)
    monkeypatch.setattr(settings, "STACKED_ROUNDS", True)
    on = _build(project)

    assert fingerprint(off) == fingerprint(on)
    assert (off.stack_rounds, on.stack_rounds) == (False, True)


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("stacking")
def test_stacking_with_a_quality_check_is_refused_before_any_transport(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    GIVEN STACKED_ROUNDS on and a confirmed quality check, with a key set
    WHEN the context is built
    THEN ValueError names both, and no transport was built
    """
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", SecretStr(FAKE_KEY))

    with pytest.raises(ValueError, match="STACKED_ROUNDS.*quality check"):
        build_context(project, quality=QUALITY, transport_factory=_no_factory)


@pytest.mark.usefixtures("stacking")
def test_stacking_with_the_output_check_off_is_refused(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    GIVEN STACKED_ROUNDS on and DEFAULT_OUTPUT_CHECK off
    WHEN the context is built
    THEN ValueError names the setting: a tip is adopted only on outputs equal
         to the original base's
    """
    monkeypatch.setattr(settings, "DEFAULT_OUTPUT_CHECK", False)

    with pytest.raises(ValueError, match="STACKED_ROUNDS.*DEFAULT_OUTPUT_CHECK"):
        _build(project)


def test_without_stacking_a_quality_check_or_the_output_check_off_still_builds(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Off, neither refusal applies: today's quality mode and Step 2 mode."""
    monkeypatch.setattr(settings, "DEFAULT_OUTPUT_CHECK", False)

    assert _build(project).default_output_check is False
    assert _build(project, quality=QUALITY).quality == QUALITY


def test_an_open_ledger_resumed_without_stacking_is_refused(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    GIVEN STACKED_ROUNDS off and a stored run whose ledger is open (its base
          may be a round tip)
    WHEN the context to resume it is built
    THEN ValueError names the run, before any transport: today's combine
         would deliver from the tip with no squash and no re-test
    """
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", SecretStr(FAKE_KEY))
    resumed = _resumed(project, stack="open")

    with pytest.raises(ValueError, match="run 'run-1' has an open stack ledger"):
        build_context(project, resumed=resumed, transport_factory=_no_factory)


def test_a_ledger_of_an_unknown_shape_counts_as_open(project: Project) -> None:
    """Fail closed: a stored ``stack`` that is not a ``StackLedger`` (a plain
    dict a fallback load left) cannot be shown closed."""
    with pytest.raises(ValueError, match="open stack ledger"):
        _build(project, resumed=_resumed(project, stack={"origin_commit": ORIGIN}))


@pytest.mark.parametrize(
    "resumed",
    [
        pytest.param("closed", id="closed-ledger"),
        pytest.param(None, id="no-ledger"),
        pytest.param("pre-u1", id="no-stack-key"),
    ],
)
def test_without_stacking_a_resumed_run_with_no_open_ledger_builds(
    project: Project, resumed: str | None
) -> None:
    """A closed ledger, ``stack=None`` and a pre-U1 state (no ``stack`` key)
    resume with today's context; the baseline is not read when off."""
    state: Mapping[str, object] = _resumed(project, stack=resumed, exact=False)
    if resumed == "pre-u1":
        state = {k: v for k, v in state.items() if k != "stack"}

    ctx = _build(project, resumed=state)

    assert (ctx.stack_rounds, ctx.stacker) == (False, None)


@pytest.mark.usefixtures("stacking")
@pytest.mark.parametrize("stack", [None, "open", "closed"])
def test_stacking_resumes_a_run_with_the_exact_output_check(
    project: Project, stack: str | None
) -> None:
    """Stacking resumes a run defined with the exact output check, whatever
    its ledger holds (an open one is exactly what stacking continues)."""
    ctx = _build(project, resumed=_resumed(project, stack=stack))

    assert ctx.stack_rounds is True
    assert isinstance(ctx.stacker, GitStacker)


@pytest.mark.usefixtures("stacking")
@pytest.mark.parametrize("stack", [None, "open"])
def test_stacking_a_resumed_run_without_the_exact_output_check_is_refused(
    project: Project, monkeypatch: pytest.MonkeyPatch, stack: str | None
) -> None:
    """
    GIVEN STACKED_ROUNDS on and a stored run whose baseline has no
          output_equivalence guardrail (defined with DEFAULT_OUTPUT_CHECK off)
    WHEN the context to resume it is built
    THEN ValueError: its tip rounds would be judged on outputs the frozen
         judge treats as not applicable (dt-design section 6)
    """
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", SecretStr(FAKE_KEY))
    resumed = _resumed(project, stack=stack, exact=False)

    with pytest.raises(ValueError, match="run 'run-1'.*output_equivalence"):
        build_context(project, resumed=resumed, transport_factory=_no_factory)


@pytest.mark.usefixtures("stacking")
def test_stacking_a_resumed_run_with_no_stored_baseline_is_refused(
    project: Project,
) -> None:
    """Fail closed: with no stored baseline the run's mode cannot be shown."""
    resumed = {**_resumed(project), "baseline": None}

    with pytest.raises(ValueError, match="output_equivalence"):
        _build(project, resumed=resumed)


# ---------------------------------------------------------------------------
# O71: gain order beside stacking
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("stacking")
def test_site_stacks_on_with_stacking_builds(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    GIVEN STACKED_ROUNDS on and SITE_STACKS "on" (O71: gain order is the
          X2-DT baseline)
    WHEN the context is built
    THEN it stacks, and its combiner carries "on" for every round's combine
         (the delivery squash makes no choice) (depends on U5c lifting the node refusal)
    """
    monkeypatch.setattr(settings, "SITE_STACKS", "on")

    ctx = _build(project)

    assert ctx.stack_rounds is True
    assert isinstance(ctx.combiner, GitCombiner)
    assert ctx.combiner.site_stacks == "on"
