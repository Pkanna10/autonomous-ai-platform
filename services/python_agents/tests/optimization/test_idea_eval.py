"""The offline idea eval (Step 3, V6 amended; spec-wave2-ideas section 6 E1
and section 7, D20's replay eval extended to the pipeline).

``tests/fixtures/idea_eval/recorded.json`` holds, for two of E1's libraries
(sqlparse, delivered in Wave 1; tomli, never), the facts the probe recorded
(``ideas-facts``), arm C's recorded replies (the defaults: S1, the six
lenses, the leap and the reviewer, ``ideas-reply``) and what E1 recorded of
that call (the ``ideas-probe`` row's counts and ``IdeaStats``, and the titles
the auditor saw returned, ``ideas-audit``). ``code/<repo>/`` holds the hot
files the call read, from the libraries' pinned upstream commits (the
engine's benchmark commit on top touches no source file).

The replay runs ``IdeaPipelineGenerator`` with ``IDEAS_LANE_WORKERS=1`` (the
lanes in ``IDEAS_LENSES`` order, then the leap), each role on its own
``ScriptedTransport``, the code through a ``RepoReader`` over the fixture
files. The gate (as the spec words it): the deterministic good-idea checks
(grounded, anchored, the gate's ceiling, non-obvious against S1) and the
interleaved order are at least the recorded values. No network, no key. What
only a live run proves: the replies themselves, and the auditor's verdicts.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final, Literal

import pytest
from live import discovery_sweep as sweep
from live.ideas_probe import FactsBody
from pydantic import BaseModel, ConfigDict

from autonomous_ai_agents.clients.budget import Budget
from autonomous_ai_agents.clients.transport import ScriptedTransport
from autonomous_ai_agents.common.config import Role, Settings, role_chain, role_settings
from autonomous_ai_agents.common.models import Hypothesis, Project
from autonomous_ai_agents.execution.git import GitError
from autonomous_ai_agents.optimization.idea_pipeline import IdeaPipelineGenerator
from autonomous_ai_agents.optimization.idea_types import LENS_LANES
from autonomous_ai_agents.optimization.sources import GenerateResult

FIXTURE: Final = Path(__file__).parents[1] / "fixtures" / "idea_eval"
BASE: Final = Settings.model_validate(
    {
        "IDEA_PIPELINE": True,
        "ENGINE_FALLBACKS": False,
        "LLM_MAX_RETRIES": 0,
        "IDEAS_LANE_WORKERS": 1,
    }
)
LANE_LABELS: Final = ("obvious", *(lane.value for lane in LENS_LANES))
REPLAY_CAP_USD: Final = 50.0  # a scripted reply costs nothing


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Recorded(_Frozen):
    """What E1 recorded of arm C's call on the library."""

    ideas: int  # the row's returned ideas
    non_obvious: int  # of those, not S1's
    grounded: int  # IdeaStats: the lane ideas whose quote is in the shown code
    anchored: int
    gate_passed: int  # the lens and leap ideas past the ceiling gate
    survivors_non_obvious: int  # IdeaStats.non_obvious: past the whole filter
    audited_returned: tuple[str, ...]  # returned titles the auditor was shown


class Library(_Frozen):
    repo: str
    wave1: Literal["delivered", "never"]
    licence: str
    upstream: str  # url@commit the code files come from
    facts: FactsBody
    code: tuple[str, ...]  # repo-relative paths under code/<repo>/
    replies: dict[str, str]  # by request label
    recorded: Recorded


class IdeaEval(_Frozen):
    source: str
    arm: Literal["C"]
    libraries: tuple[Library, ...]


def load_eval(path: Path = FIXTURE / "recorded.json") -> IdeaEval:
    return IdeaEval.model_validate_json(path.read_text(encoding="utf-8"))


class FixtureReader:
    """``RepoReader`` over a library's fixture files at its recorded commit."""

    def __init__(self, library: Library, root: Path = FIXTURE / "code") -> None:
        self._commit = library.facts.commit
        base = (root / library.repo).resolve()
        self._blobs: dict[str, bytes] = {}
        for path in library.code:
            where = (base / f"{path}.txt").resolve()
            if not where.is_relative_to(base) or Path(path).is_absolute():
                raise ValueError(f"{library.repo}: {path!r} leaves its code dir")
            self._blobs[path] = where.read_bytes()

    def ls_tree(self, commit: str) -> tuple[str, ...]:
        if commit != self._commit:
            raise GitError("unknown commit")
        return tuple(sorted(self._blobs))

    def read_blob(self, commit: str, path: str, *, limit: int | None = None) -> bytes:
        if commit != self._commit or path not in self._blobs:
            raise GitError(f"no {path} at {commit}")
        data = self._blobs[path]
        return data if limit is None else data[:limit]


EVAL: Final = load_eval()
BY_REPO: Final = {lib.repo: lib for lib in EVAL.libraries}


def _transports(library: Library, cfg: Settings) -> dict[Role, ScriptedTransport]:
    def replies(labels: Sequence[str], role: Role) -> list[dict[str, object]]:
        model = role_chain(cfg, role)[0]
        return [sweep.scripted_reply(library.replies[x], model) for x in labels]

    return {
        "lane": ScriptedTransport(
            replies(LANE_LABELS, "lane"), cfg=role_settings(cfg, "lane")
        ),
        "leap": ScriptedTransport(
            replies(("leap",), "leap"), cfg=role_settings(cfg, "leap")
        ),
        "reviewer": ScriptedTransport(
            replies(("reviewer",), "reviewer"), cfg=role_settings(cfg, "reviewer")
        ),
    }


def replay(
    library: Library, cfg: Settings = BASE
) -> tuple[GenerateResult, Mapping[Role, ScriptedTransport]]:
    """Arm C's recorded call on ``library``, replayed from its facts."""
    f = library.facts
    reader = FixtureReader(library)
    transports = _transports(library, cfg)

    def read(project: Project) -> FixtureReader:
        assert project.name == library.repo
        return reader

    generator = IdeaPipelineGenerator(
        transports, reader=read, config=cfg, sleep=lambda _s: None
    )
    result = generator.generate(
        project=f.project, understanding=f.understanding, hotspots=f.hotspots,
        objective=f.objective, techniques=(), lessons=(), avoid_titles=(),
        n=cfg.GENERATOR_N, budget=Budget(REPLAY_CAP_USD), commit=f.commit,
        run_id=f.run_id, protected=f.protected,
    )  # fmt: skip
    return result, transports


def _non_obvious(h: Hypothesis) -> bool:
    return "lane:obvious" not in h.tags


def d53_order(obvious: int, non_obvious: int) -> list[bool]:
    """D53's returned order for these counts (True: a non-obvious idea):
    ``O1 N1 N2 O2 N3 N4 O3 N5 O4 O5``, whichever runs out first. Parked
    ``novel`` ideas, which D53 appends after the interleave, are not modelled:
    the recorded calls returned none."""
    order: list[bool] = []
    o = n = 0
    while o < obvious or n < non_obvious:
        if o < obvious:
            order.append(False)
            o += 1
        for _ in range(2):
            if n < non_obvious:
                order.append(True)
                n += 1
    return order


def _prefix_counts(order: Sequence[bool]) -> list[int]:
    counts, total = [], 0
    for flag in order:
        total += flag
        counts.append(total)
    return counts


def test_the_fixture_is_e1s_arm_c_on_one_delivered_and_one_never_library() -> None:
    assert EVAL.arm == "C" and "E1" in EVAL.source
    assert {lib.repo: lib.wave1 for lib in EVAL.libraries} == {
        "sqlparse": "delivered",
        "tomli": "never",
    }
    for lib in EVAL.libraries:
        assert set(lib.replies) == {*LANE_LABELS, "leap", "reviewer"}, lib.repo
        assert lib.facts.project.name == lib.repo and lib.code, lib.repo
        assert {h.file_path for h in lib.facts.hotspots} >= set(lib.code), lib.repo
        assert lib.licence in ("BSD-3-Clause", "MIT") and "@" in lib.upstream
        assert (FIXTURE / "code" / lib.repo / "LICENSE").is_file(), lib.repo


@pytest.mark.parametrize("repo", sorted(BY_REPO))
def test_the_replay_sends_each_recorded_reply_once_and_returns_its_ideas(
    repo: str,
) -> None:
    """The replay is the recorded call: every reply sent once, in order, on
    the fixture's code, returning the ideas the auditor saw returned."""
    library, recorded = BY_REPO[repo], BY_REPO[repo].recorded
    result, transports = replay(library)
    assert {role: t.remaining for role, t in transports.items()} == {
        "lane": 0, "leap": 0, "reviewer": 0,
    }  # fmt: skip
    assert [len(t.requests) for t in transports.values()] == [7, 1, 1]
    assert result.stats is not None and set(result.stats.stop_reasons) == {
        *LANE_LABELS, "leap", "reviewer",
    }  # fmt: skip
    # the code context is the fixture's: every hot file the call read
    assert any(
        f"code context: {len(library.code)} file(s) shown" in note
        for note in result.notes
    )
    titles = {h.title for h in result.hypotheses}
    assert set(recorded.audited_returned) <= titles, repo


@pytest.mark.parametrize("repo", sorted(BY_REPO))
def test_the_recorded_fixture_still_reproduces_its_counts(repo: str) -> None:
    """Fixture integrity, not the gate: this pins today's exact reproduction
    of E1's counts. After an intended pipeline change, refresh the fixture
    from a new E1 run; the D20 gates below need only at least the recorded
    values."""
    library, recorded = BY_REPO[repo], BY_REPO[repo].recorded
    result, _ = replay(library)
    stats = result.stats
    assert stats is not None
    assert (stats.grounded, stats.anchored, stats.gate_passed, stats.non_obvious) == (
        recorded.grounded, recorded.anchored, recorded.gate_passed,
        recorded.survivors_non_obvious,
    )  # fmt: skip
    returned = sum(map(_non_obvious, result.hypotheses))
    assert (len(result.hypotheses), returned) == (recorded.ideas, recorded.non_obvious)


@pytest.mark.parametrize("repo", sorted(BY_REPO))
def test_the_deterministic_good_idea_checks_hold_the_recorded_values(
    repo: str,
) -> None:
    """D20's gate for the pipeline: grounded, anchored, past the ceiling and
    non-obvious against S1, each at least what E1 recorded."""
    library, recorded = BY_REPO[repo], BY_REPO[repo].recorded
    result, _ = replay(library)
    stats = result.stats
    assert stats is not None
    assert stats.grounded >= recorded.grounded, repo
    assert stats.anchored >= recorded.anchored, repo
    assert stats.gate_passed >= recorded.gate_passed, repo
    assert stats.non_obvious >= recorded.survivors_non_obvious, repo
    returned = sum(map(_non_obvious, result.hypotheses))
    assert returned >= recorded.non_obvious, repo


@pytest.mark.parametrize("repo", sorted(BY_REPO))
def test_the_interleaved_order_holds_the_recorded_value(repo: str) -> None:
    """D53's order: in every prefix (the node takes 3 a round) at least as
    many non-obvious ideas as the recorded call's order holds."""
    library, recorded = BY_REPO[repo], BY_REPO[repo].recorded
    result, _ = replay(library)
    order = [_non_obvious(h) for h in result.hypotheses]
    expected = d53_order(recorded.ideas - recorded.non_obvious, recorded.non_obvious)
    got, want = _prefix_counts(order), _prefix_counts(expected)
    assert all(g >= w for g, w in zip(got, want, strict=False)), (repo, order)
    assert len(got) >= len(want), (repo, order)
    assert len(got) >= 3, f"{repo}: fewer than one node round (3) returned: {order}"
    assert got[2] >= min(2, recorded.non_obvious), (repo, order)


def test_d53_order_interleaves_one_obvious_and_two_non_obvious() -> None:
    o, n = False, True
    assert d53_order(5, 5) == [o, n, n, o, n, n, o, n, o, o]
    assert d53_order(5, 3) == [o, n, n, o, n, o, o, o]
    assert d53_order(1, 4) == [o, n, n, n, n]
    assert d53_order(0, 2) == [n, n] and d53_order(2, 0) == [o, o]
    assert _prefix_counts([o, n, n, o]) == [0, 1, 2, 2]


def test_the_gate_fails_a_replay_that_loses_ideas() -> None:
    """A pipeline that dropped every lens idea would fail the gate: the
    recorded values are above what S1 alone gives."""
    library = BY_REPO["sqlparse"]
    lenses_off = {**library.replies, **{lane.value: '{"hypotheses": []}'
                                        for lane in LENS_LANES}}  # fmt: skip
    poorer = library.model_copy(update={"replies": lenses_off})
    result, _ = replay(poorer)
    assert result.stats is not None
    assert result.stats.grounded < library.recorded.grounded
    assert result.stats.non_obvious < library.recorded.survivors_non_obvious


def test_the_reader_refuses_a_path_outside_its_code_dir(tmp_path: Path) -> None:
    library = BY_REPO["tomli"]
    (tmp_path / "tomli").mkdir()
    (tmp_path / "secret.txt").write_text("no", encoding="utf-8")
    bad = library.model_copy(update={"code": ("../secret",)})
    with pytest.raises(ValueError, match="leaves its code dir"):
        FixtureReader(bad, root=tmp_path)
    reader = FixtureReader(library)
    with pytest.raises(GitError):
        reader.ls_tree("0" * 40)
    with pytest.raises(GitError):
        reader.read_blob(library.facts.commit, "src/tomli/_re.py")
    full = reader.read_blob(library.facts.commit, library.code[0])
    assert len(full) > 3
    assert reader.read_blob(library.facts.commit, library.code[0], limit=3) == full[:3]
