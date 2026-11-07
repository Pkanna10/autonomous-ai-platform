"""Offline guards of the ideas-marker suite (Vb, ``ideas_marker.py``).

Not ``live``: these spend nothing. They prove, before a dollar goes to
``test_ideas_marker_live.py``, that the rank rows load strictly into their
(library, repetition, arm) sets, that the score is O37's (within-library
AUC averaged over libraries, a seeded cluster bootstrap over libraries, the
generator's own order as the baseline, the 0.05 tie rule, nothing decided
under ~20 positives) with the bar's numbers pinned to STATUS's text, that
every marker request is blind (no verdict, gain, floor or rank: the request
is the same whatever those are; no outcome or expectation anywhere outside
the titles, the real profile notes included) and capped before it is sent,
that a reply that is not a permutation of the set is refused, and that the
reply rows alone rebuild the score and the verdict (a job cut short).

Fakes and what they stand for: ``dg.Wire`` for the Messages API (the live
run's captured ``AnthropicTransport``; counts are a fixed 900 tokens, or
``_Wire``'s); ``og.LOCAL`` and a ``file://`` bare upstream for GitHub over
https (``oss.PRODUCTION``); hand-made ``HotCode`` for the hot code a pinned
clone gives. What only a live run proves: the real counts against
``MARKER_PROMPT_BOUND``, the models' orders and the verdict.
"""

from __future__ import annotations

import ast
import dataclasses
import json
import math
import random
import re
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, cast

import httpx2
import pytest

from autonomous_ai_agents.clients.structured import Fence
from autonomous_ai_agents.common.config import Settings, settings

from . import ideas_marker as im
from . import test_discovery_guards as dg
from . import test_oss_guards as og
from .conftest import SUITE_CAP_ENV, TESTS_DIR, LiveRun
from .corpus import RESULTS_ENV
from .discovery import OPUS
from .discovery_io import ResultsSink
from .discovery_oss import CAP_CEILING_USD, OSS_SELECTABLE
from .ideas_probe import request_usd
from .oss import OSS_CORPUS, CloneRefusedError, OssRepo

dry = dg.dry
upstream = og.upstream

Json = dict[str, Any]
LIVE_DIR = TESTS_DIR / "live"
STATUS = TESTS_DIR.parents[2] / "STATUS.md"
FENCE = Fence("0123456789abcdef")
LIB = OSS_CORPUS[8]  # tomli, a pinned OSS library
ENOUGH = {SUITE_CAP_ENV: "150"}
SOURCE = '''"""Number tools."""


def slow_sum(values):
    total = 0
    for value in values:
        total = total + abs(value)
    return total


class Joiner:
    def slow_join(self, parts):
        text = ""
        for part in parts:
            text = text + str(part).strip()
        return text


def unused():
    return 0
'''
PROFILE = "cProfile, 1.0 s: Joiner.slow_join 0.6 s cumulative, slow_sum 0.3 s"


def _row(
    title: str = "t",
    verdict: str = "keep",
    *,
    rank: int = 1,
    repo: str = "tomli",
    rep: int = 1,
    arm: str = "A",
    gain: float | None = 12.5,
    floor: float | None = 5.25,
    guard: str = "ok",
) -> im.RankRow:
    return im.RankRow(
        run_id=1, arm=arm, change_class="efficiency", experiment="E5-oss-ab-rank",
        gain_pct=gain, guard=guard, noise_floor_pct=floor, rank=rank, rep=rep,
        repo=repo, title=title, verdict=verdict,
    )  # fmt: skip


def _set(
    *verdicts: str, repo: str = "tomli", rep: int = 1, arm: str = "A"
) -> im.RankSet:
    rows = [
        _row(f"idea {k}", v, rank=k + 1, repo=repo, rep=rep, arm=arm)
        for k, v in enumerate(verdicts)
    ]
    (found,) = im.rank_sets(rows)
    return found


def _hot(repo: str = "tomli") -> im.HotCode:
    return im.HotCode(
        repo=repo, profile=PROFILE,
        blocks=(("pkg/text.py:slow_sum lines 4-8", "def slow_sum(values):\n    pass"),),
    )  # fmt: skip


def _text(body: Json) -> str:
    return "\n".join(block["text"] for block in body["messages"][0]["content"])


def _ids(body: Json) -> list[str]:
    return re.findall(r'"id": "(I\d+)"', _text(body))


def _titled(body: Json) -> dict[str, str]:
    lines = re.findall(r'^\{"id": "I\d+".*$', _text(body), re.MULTILINE)
    return {d["id"]: d["title"] for d in map(json.loads, lines)}


def _by_title(body: Json) -> str:
    """An order by title: ``idea 0`` (the generator's first) first."""
    titled = _titled(body)
    return json.dumps({"order": sorted(titled, key=titled.__getitem__)})


# ---------------------------------------------------------------------------
# The bar: O37's numbers, pinned to STATUS's text
# ---------------------------------------------------------------------------


def _o37() -> str:
    text = STATUS.read_text(encoding="utf-8")
    begin = text.index("**O37. The bar.**")
    return " ".join(text[begin : text.index("**Known before the bar", begin)].split())


def test_the_bar_is_o37s_text_fixed_before_any_result() -> None:
    bar = _o37()
    assert f"is at least {im.AUC_BAR:g}" in bar and im.AUC_BAR == 0.65
    assert f"lower bound is above {im.CI_LOWER_BAR:g}" in bar
    assert im.CI_LOWER_BAR == 0.5 and im.CI_LEVEL == 0.95 and "95 % interval" in bar
    assert f"within {im.TIE_MARGIN:g}, Opus 5 is chosen" in bar
    assert im.TIE_MARGIN == 0.05 and im.TIE_CHOICE == im.OPUS_5_MARKER.key
    assert f"Fewer than ~{im.MIN_POSITIVES} positives" in bar and im.MIN_POSITIVES == 20
    assert "Positive = `keep`" in bar and im.POSITIVE == {"keep"}
    assert "`reject` or `inconclusive`" in bar
    assert im.NEGATIVE == {"reject", "inconclusive"}
    for excluded in ("NOT_TRIALLED", "NOT_HANDED", "NO_RESULT", "no_verdict"):
        assert f"`{excluded}`" in bar
        assert _row(verdict=excluded).label is None
    assert "guard-breached rows" in bar and _row(guard="breach").label is None
    assert "resamples whole libraries" in bar and "the `rank` field" in bar
    assert im.BOOTSTRAP_RESAMPLES >= 2000  # the brief: at least 2000
    assert [m.model for m in im.MARKERS] == [OPUS, "claude-opus-5"]
    assert {m.effort for m in im.MARKERS} == {"high"}  # none named: high


# ---------------------------------------------------------------------------
# The rows and the rank sets
# ---------------------------------------------------------------------------


def test_the_committed_rows_load_strictly_into_72_sets_48_with_a_pair() -> None:
    rows = im.load_rows()
    assert len(rows) == 332
    assert sum(r.verdict == "keep" for r in rows) == 114
    assert sum(r.label is True for r in rows) == 114
    assert sum(r.label is False for r in rows) == 175 + 43
    sets = im.rank_sets(rows)
    assert len(sets) == 72 and len({s.repo for s in sets}) == 18
    for s in sets:
        assert [r.rank for r in s.rows] == list(range(1, len(s.rows) + 1))
    plan = im.marker_plan(ENOUGH)
    assert len(plan.sets) == 48 and len(plan.skipped) == 24
    assert all(s.informative for s in plan.sets)
    assert not any(s.informative for s in plan.skipped)
    assert plan.positives == 114 and plan.comparable == 103
    assert len(plan.repos) == 17
    assert "more_itertools" not in {r.name for r in plan.repos}


def test_a_row_is_refused_unless_strict_and_a_rank_repeated_in_a_set(
    tmp_path: Path,
) -> None:
    good = _row().model_dump()
    path = tmp_path / "rows.jsonl"
    for bad in (
        {**good, "extra": 1},
        {**good, "experiment": "E5-other"},
        {**good, "rank": "1"},
        {**good, "rank": 0},
        {**good, "title": ""},
    ):
        path.write_text(json.dumps(bad) + "\n", encoding="utf-8")
        with pytest.raises(ValueError):
            im.load_rows(path)
    with pytest.raises(ValueError, match="rank 1 twice"):
        im.rank_sets([_row("a"), _row("b")])
    path.write_text(json.dumps(good) + "\n\n", encoding="utf-8")
    assert im.load_rows(path) == (_row(),)


# ---------------------------------------------------------------------------
# AUC, the library mean and the bootstrap
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("scores", "labels", "expected"),
    [
        ((4, 3, 2, 1), (True, True, False, False), 1.0),  # perfect
        ((1, 2, 3, 4), (True, True, False, False), 0.0),  # reversed
        ((1, 1, 1, 1), (True, False, True, False), 0.5),  # all tied
        ((3, 2, 2, 1), (True, True, False, False), 0.875),  # one tie of four pairs
        ((4, 3, 2, 1), (True, False, True, False), 0.75),
        ((4, 3, 2), (True, None, False), 1.0),  # an excluded row never counts
        ((3, 2, 1), (True, True, True), None),  # no negative
        ((3, 2, 1), (False, None, False), None),  # no positive
        ((), (), None),
    ],
)
def test_auc_on_hand_made_sets(
    scores: Sequence[float], labels: Sequence[bool | None], expected: float | None
) -> None:
    assert im.auc(scores, labels) == expected


def test_auc_refuses_a_length_mismatch() -> None:
    with pytest.raises(ValueError, match="scores for 2 rows, labels for 3"):
        im.auc((1, 2), (True, False, None))


def test_the_library_auc_pools_its_sets_pairs_and_the_mean_is_over_libraries() -> None:
    entries = [
        ("a", (2, 1), (True, False)),  # 1 of 1
        ("a", (3, 2, 1), (False, True, True)),  # 0 of 2
        ("b", (2, 1), (True, False)),  # 1 of 1
        ("c", (2, 1), (True, True)),  # no pair: no library AUC
    ]
    assert im.library_aucs(entries) == {"a": pytest.approx(1 / 3), "b": 1.0}
    found = im.score_of(entries)
    assert found.auc == pytest.approx((1 / 3 + 1.0) / 2)
    assert (found.libraries, found.pairs, found.positives) == (2, 4, 4)
    assert found.auc is not None and found.low is not None and found.high is not None
    assert found.low <= found.auc <= found.high
    empty = im.score_of([("c", (2, 1), (True, True))])
    assert (empty.auc, empty.low, empty.high, empty.libraries) == (None, None, None, 0)


def test_the_bootstrap_is_seeded_resamples_libraries_and_refuses_too_few() -> None:
    values = [0.4, 0.55, 0.6, 0.7, 0.72, 0.8, 0.9, 1.0]
    first = im.bootstrap_interval(values)
    assert first == im.bootstrap_interval(values)  # deterministic
    assert first != im.bootstrap_interval(values, seed=im.BOOTSTRAP_SEED + 1)
    low, high = first
    assert min(values) <= low < sum(values) / len(values) < high <= max(values)
    assert im.bootstrap_interval([0.7] * 5) == (0.7, 0.7)
    assert im.bootstrap_interval([0.6]) == (0.6, 0.6)
    with pytest.raises(ValueError, match="at least 2000 resamples"):
        im.bootstrap_interval(values, resamples=1999)
    with pytest.raises(ValueError, match="no library"):
        im.bootstrap_interval([])


def test_the_bootstrap_interval_covers_the_true_mean_on_a_synthetic_case() -> None:
    """100 synthetic validations of 17 libraries whose AUCs are drawn around
    a known mean: the 95 % interval holds it in about 95 of them."""
    rng = random.Random(7)  # noqa: S311 - a test's synthetic draw
    truth, hits = 0.7, 0
    for k in range(100):
        values = [min(1.0, max(0.0, rng.gauss(truth, 0.12))) for _ in range(17)]
        low, high = im.bootstrap_interval(values, seed=k)
        hits += low <= truth <= high
    assert 85 <= hits <= 100, hits


# ---------------------------------------------------------------------------
# The pass rule (O37 rules 1-4)
# ---------------------------------------------------------------------------


def _score(
    auc: float | None, low: float | None = 0.6, positives: int = 100
) -> im.Score:
    return im.Score(auc=auc, low=low, high=None if auc is None else auc + 0.1,
                    libraries=17, pairs=200, positives=positives)  # fmt: skip


def _cand(key: str, auc: float, low: float = 0.6, base: float = 0.6) -> im.Candidate:
    return im.Candidate(key, _score(auc, low), _score(base))


A, B = im.OPUS_55_MARKER.key, im.OPUS_5_MARKER.key


@pytest.mark.parametrize(
    ("candidates", "chosen", "passed", "reason"),
    [
        ((_cand(A, 0.80), _cand(B, 0.70)), A, (A, B), im.HIGHER),
        ((_cand(A, 0.70), _cand(B, 0.80)), B, (A, B), im.HIGHER),
        ((_cand(A, 0.74), _cand(B, 0.70)), B, (A, B), im.WITHIN),
        ((_cand(A, 0.75), _cand(B, 0.70)), B, (A, B), im.WITHIN),  # exactly 0.05
        ((_cand(A, 0.70), _cand(B, 0.66)), B, (A, B), im.WITHIN),
        ((_cand(A, 0.80), _cand(B, 0.64)), A, (A,), im.ONE),  # B under 0.65
        ((_cand(A, 0.80, low=0.5), _cand(B, 0.70)), B, (B,), im.ONE),  # low not > 0.5
        ((_cand(A, 0.70, base=0.71), _cand(B, 0.60)), None, (), im.NO_MARKER),
        ((_cand(A, 0.64), _cand(B, 0.60)), None, (), im.NO_MARKER),
    ],
)
def test_the_pass_rule_branches(
    candidates: tuple[im.Candidate, ...],
    chosen: str | None,
    passed: tuple[str, ...],
    reason: str,
) -> None:
    decision = im.decide(candidates, positives=103)
    assert (decision.chosen, decision.passed, decision.reason) == (
        chosen,
        passed,
        reason,
    )
    assert decision.baseline_ties == ()


def test_a_tie_with_the_generators_order_passes_and_is_recorded() -> None:
    tied = im.Candidate(A, _score(0.70), _score(0.70))
    decision = im.decide((tied, _cand(B, 0.60)), positives=103)
    assert (decision.chosen, decision.baseline_ties) == (A, (A,))
    assert tied.passes and tied.baseline_tie


def test_under_twenty_positives_the_validation_decides_nothing() -> None:
    both = (_cand(A, 0.9), _cand(B, 0.9))
    decision = im.decide(both, positives=19)
    assert (decision.chosen, decision.reason) == (None, im.UNDERPOWERED)
    assert im.decide(both, positives=20).chosen == B
    thin = im.Candidate(A, _score(0.9, positives=19), _score(0.5))
    assert not thin.passes  # its own answered sets hold too few positives
    unscored = im.Candidate(A, _score(None, None), _score(None, None))
    assert not unscored.passes and not unscored.baseline_tie


# ---------------------------------------------------------------------------
# The request: blind, shuffled by the set, strict structured output
# ---------------------------------------------------------------------------

_FORBIDDEN = re.compile(r"verdict|gain|floor|rank|keep|reject|inconclusive", re.I)


def _outside_data(request_text: str, system: str) -> str:
    """The request's own words: the system prompt and every line outside the
    fenced blocks."""
    kept, inside = [system], False
    for line in request_text.splitlines():
        if line.startswith("<") and f"boundary={FENCE.token}>" in line:
            inside = not line.startswith("</")
            continue
        if not inside:
            kept.append(line)
    return "\n".join(kept)


# an outcome, or an expectation of one, anywhere outside the ideas' titles
_BLIND = re.compile(
    _FORBIDDEN.pattern + r"|\bwins?\b|expect|control|hypothes|outcome|refus|tuned",
    re.I,
)


def _real_profile(repo: str) -> im.HotCode:
    """The library's recorded profile note as the live run sends it, a stub
    for its code (the clone's code is the library's own)."""
    (found,) = (r for r in OSS_SELECTABLE if r.name == repo)
    return dataclasses.replace(_hot(repo), profile=found.profile)


def _without_ideas(request_text: str) -> str:
    """The whole request, fences included, but the ideas block (titles may
    hold such words; ``_outside_data`` checks the rest)."""
    kept, inside = [], False
    for line in request_text.splitlines():
        if line.startswith(("<ideas ", "</ideas ")):
            inside = not line.startswith("</")
            continue
        kept.append("" if inside else line)
    return "\n".join(kept)


def test_the_shown_profile_keeps_the_timings_and_drops_every_outcome_clause() -> None:
    note = (
        "cProfile, 2.0 s under the profiler (1.0 s plain): the code is already "
        "tuned; f 0.5 s cumulative (re._compile 10 calls). A win is expected: "
        "this is a control. Library code: g 0.2 s."
    )
    assert im.shown_profile(note) == (
        "cProfile, 2.0 s under the profiler (1.0 s plain): f 0.5 s cumulative "
        "(re._compile 10 calls). Library code: g 0.2 s."
    )
    raw = {r.name: r.profile for r in OSS_SELECTABLE}
    shown = {k: im.shown_profile(v) for k, v in raw.items()}
    assert "SortedList.add 1.07 s cumulative" in shown["sortedcontainers"]
    assert "_windowed_running_mean" in shown["more_itertools"]
    for name in ("sortedcontainers", "more_itertools"):
        assert shown[name] != raw[name] and not _BLIND.search(shown[name]), name
    # every other note is timings only, shown as recorded
    assert {k for k in raw if shown[k] != raw[k]} == {
        "sortedcontainers",
        "more_itertools",
    }
    assert im.shown_profile("") == ""


def test_every_request_on_the_committed_sets_is_blind() -> None:
    """For each of the 72 sets: the request is byte-identical when every
    verdict, gain, floor and the generator's ranks are changed; it shows
    only an id, the title and the class per idea, in an order that is not
    the generator's on the whole; its own words name none of them, and
    nothing outside the titles (the library's real profile note included)
    names an outcome or an expectation of one."""
    rng = random.Random(3)  # noqa: S311 - a test's synthetic draw
    identity = 0
    for s in im.rank_sets(im.load_rows()):
        hot = _real_profile(s.repo)
        request, shown = im.marker_request(s, hot, fence=FENCE)
        text = _text({"messages": request.messages})
        assert not _BLIND.search(_without_ideas(text) + request.system), s.key
        ranks = rng.sample(range(1, len(s.rows) + 1), len(s.rows))
        other = dataclasses.replace(
            s,
            rows=tuple(
                r.model_copy(update={"verdict": "reject", "gain_pct": -1.0,
                                     "noise_floor_pct": 99.0, "rank": k})
                for r, k in zip(s.rows, ranks, strict=True)
            ),
        )  # fmt: skip
        again, _ = im.marker_request(other, hot, fence=FENCE)
        assert again == request, s.key
        lines = re.findall(r'^\{"id".*$', text, re.MULTILINE)
        assert [json.loads(x) for x in lines] == [
            {"id": f"I{p + 1}", "title": s.rows[i].title, "change_class": "efficiency"}
            for p, i in enumerate(shown)
        ]
        assert not _FORBIDDEN.search(_outside_data(text, request.system)), s.key
        for r in s.rows:  # as a number of its own (a profile's 2.06 s is no 2.0)
            for value in (r.gain_pct, r.noise_floor_pct):
                number = rf"(?<![\d.]){re.escape(repr(value))}(?!\d)"
                assert not re.search(number, text), (s.key, value)
        identity += list(shown) == list(range(len(s.rows)))
        config = cast(Json, request.output_config)
        item = config["format"]["schema"]["properties"]["order"]["items"]
        assert item["enum"] == [f"I{p + 1}" for p in range(len(s.rows))]
        assert "effort" not in config  # set per marker (``ask``)
    assert identity < 72 // 4  # shuffled: the generator's order only by chance


def test_the_shown_order_depends_on_the_set_and_titles_only() -> None:
    s = _set("keep", "reject", "inconclusive", "keep", "reject")
    assert im.shown_order(s) == im.shown_order(s)
    assert sorted(im.shown_order(s)) == list(range(5))
    flipped = dataclasses.replace(s, rows=tuple(reversed(s.rows)))
    by_title = [s.rows[i].title for i in im.shown_order(s)]
    assert [flipped.rows[i].title for i in im.shown_order(flipped)] == by_title
    other = _set("keep", "reject", "inconclusive", "keep", "reject", rep=2)
    orders = {tuple(im.shown_order(dataclasses.replace(s, rep=k))) for k in range(8)}
    assert len(orders) > 1 and other.key != s.key


def test_fenced_lines_holding_the_token_are_withheld_and_controls_replaced() -> None:
    s = _set("keep", "reject")
    hot = im.HotCode(
        "tomli",
        f"profile {FENCE.token}",
        (("h", f"x = 1\nleak {FENCE.token}\ny = '‮'"),),
    )
    request, _ = im.marker_request(s, hot, fence=FENCE)
    text = _text({"messages": request.messages})
    assert text.count(FENCE.token) == 1 + 3 * 2  # the opening and three blocks
    assert "(line withheld: it holds the boundary token)" in text
    assert "y = '?'" in text and "‮" not in text


def test_the_marker_request_carries_the_marker_effort_and_bounds() -> None:
    request = im.marker_request(_set("keep", "reject"), _hot(), effort="high")[0]
    assert cast(Json, request.output_config)["effort"] == "high"
    assert request.max_tokens == im.MARKER_MAX_TOKENS and request.cache is False


# ---------------------------------------------------------------------------
# The reply: a permutation of the set, or refused
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "order",
    [
        ["I1", "I2"],
        ["I1", "I2", "I3", "I3"],
        ["I1", "I2", "I4"],
        [],
        ["I1", "I1", "I2"],
    ],
)
def test_an_order_that_is_not_a_permutation_is_refused(order: list[str]) -> None:
    with pytest.raises(im.NotPermutationError):
        im.check_permutation(order, ("I1", "I2", "I3"))


def test_a_permutation_gives_each_row_its_score() -> None:
    ids = ("I1", "I2", "I3")
    assert im.check_permutation(["I3", "I1", "I2"], ids) == ("I3", "I1", "I2")
    # shown position p holds row shown[p]; the marker's first gets n
    assert im.scores_of(("I3", "I1", "I2"), ids, (2, 0, 1)) == (1.0, 3.0, 2.0)


# ---------------------------------------------------------------------------
# One marker request on the wire: counted and capped before it is sent
# ---------------------------------------------------------------------------


class _Wire(dg.Wire):
    """``dg.Wire`` counting every prompt as ``tokens``."""

    def __init__(self, answer: Callable[[Json], str], tokens: int) -> None:
        super().__init__(answer)
        self.tokens = tokens

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/count_tokens"):
            self.counted.append(json.loads(request.read()))
            return httpx2.Response(
                200, json={"input_tokens": self.tokens}, request=request
            )
        raise AssertionError("a request past its bound reached the wire")


def _base() -> Settings:
    return settings.model_copy(update={"LLM_MAX_RETRIES": 0})


def test_one_request_is_counted_capped_sent_and_scored(dry: Path) -> None:
    wire = dg.Wire(_by_title)
    run = wire.run(1.0)
    s = _set("keep", "reject", "inconclusive")
    for marker in im.MARKERS:
        reply = im.ask(marker, run, s, _hot(), base=_base())
        assert reply.error is None and reply.scores == (3.0, 2.0, 1.0)
        assert reply.cost_usd > 0 and reply.exchange is not None
        # the wire's 900, its margin and the structured allowance
        assert reply.exchange.counted == 900 + 18 + 2000 and reply.exchange.sent
    assert [b["model"] for b in wire.bodies] == [OPUS, "claude-opus-5"]
    assert len(wire.counted) == 2  # every request counted before it went
    for body in wire.bodies:
        assert body["output_config"]["effort"] == "high"
        assert body["max_tokens"] == im.MARKER_MAX_TOKENS
        assert sorted(_ids(body)) == ["I1", "I2", "I3"]


def test_a_request_past_its_bound_is_refused_before_the_wire(dry: Path) -> None:
    wire = _Wire(_by_title, tokens=im.MARKER_PROMPT_BOUND + 1)
    run = wire.run(5.0)
    reply = im.ask(im.OPUS_5_MARKER, run, _set("keep", "reject"), _hot(), base=_base())
    assert reply.scores is None and reply.error is not None
    assert reply.error.startswith("BudgetExceeded")
    assert wire.bodies == [] and len(wire.counted) == 1 and run.records == []
    assert im.request_worst(im.OPUS_5_MARKER) == request_usd(
        im.MARKER_PROMPT_BOUND, im.MARKER_MAX_TOKENS, "claude-opus-5"
    )


@pytest.mark.parametrize(
    ("answer", "kind"),
    [
        (lambda b: json.dumps({"order": _ids(b)[:1]}), "NotPermutationError"),
        (
            lambda b: json.dumps({"order": [*_ids(b), _ids(b)[0]]}),
            "NotPermutationError",
        ),
        (lambda b: "not json", "UnusableReplyError"),
        (lambda b: json.dumps({"order": _ids(b), "why": "x"}), "UnusableReplyError"),
    ],
)
def test_an_unusable_reply_is_recorded_as_the_sets_error(
    dry: Path, answer: Callable[[Json], str], kind: str
) -> None:
    wire = dg.Wire(answer)
    reply = im.ask(im.OPUS_55_MARKER, wire.run(1.0), _set("keep", "reject"), _hot(),
                   base=_base())  # fmt: skip
    assert reply.scores is None and reply.error is not None
    assert reply.error.startswith(kind) and len(wire.bodies) == 1


# ---------------------------------------------------------------------------
# The plan, its need and its minutes; refused before any spend
# ---------------------------------------------------------------------------


def test_the_need_is_each_librarys_capped_sets_on_both_markers() -> None:
    plan = im.marker_plan(ENOUGH)
    per_set = request_usd(im.MARKER_PROMPT_BOUND, im.MARKER_MAX_TOKENS, OPUS) + (
        request_usd(im.MARKER_PROMPT_BOUND, im.MARKER_MAX_TOKENS, "claude-opus-5")
    )
    assert im.set_usd() == pytest.approx(per_set) == pytest.approx(0.495)
    for repo in plan.repos:
        n = len(plan.sets_of(repo.name))
        assert plan.library_cap(repo.name) >= n * per_set
        assert plan.library_cap(repo.name) < n * per_set + 0.05
    need = im.marker_need(plan)
    assert 48 * per_set <= need <= 48 * per_set + 17 * 0.05
    assert need <= im.MARKER_NEED_USD < need + 1 and im.MARKER_NEED_USD == 24
    assert plan.minutes() == 17 * im.CLONE_MINUTES + 96 * im.REQUEST_MINUTES
    assert plan.minutes() <= im.JOB_MINUTES == 240


def test_a_plan_is_refused_before_any_spend(monkeypatch: pytest.MonkeyPatch) -> None:
    need = im.marker_need(im.marker_plan(ENOUGH))
    with pytest.raises(ValueError, match="is below the suite's need"):
        im.marker_plan({SUITE_CAP_ENV: f"{need - 0.01:.2f}"})
    with pytest.raises(ValueError, match="is below the suite's need"):
        im.marker_plan({})  # the 12 USD default
    assert im.marker_plan({SUITE_CAP_ENV: f"{need:.2f}"}).sets
    monkeypatch.setattr(im, "REQUEST_MINUTES", 3)
    with pytest.raises(ValueError, match="past the 240-minute job"):
        im.marker_plan(ENOUGH)
    monkeypatch.setattr(im, "REQUEST_MINUTES", 2)
    monkeypatch.setattr(im, "MARKER_MAX_TOKENS", 400_000)
    with pytest.raises(ValueError, match=f"past the {CAP_CEILING_USD:g} USD ceiling"):
        im.marker_plan(ENOUGH)
    with pytest.raises(ValueError, match="not a pinned OSS library"):
        im.marker_plan(
            ENOUGH,
            rows=[_row(repo="leftpad"), _row("b", "reject", rank=2, repo="leftpad")],
        )


# ---------------------------------------------------------------------------
# The hot code from the pinned clone
# ---------------------------------------------------------------------------


def _clone(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "clone"
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    return root


def _repo(
    profile: str = PROFILE, targets: tuple[str, ...] = ("pkg/text.py",)
) -> OssRepo:
    return dataclasses.replace(LIB, targets=(targets, targets), profile=profile)


def test_the_hot_code_is_the_profiles_functions_in_the_order_it_names_them(
    tmp_path: Path,
) -> None:
    root = _clone(tmp_path, {"pkg/text.py": SOURCE})
    hot = im.hot_code(_repo(), root)
    assert [h for h, _ in hot.blocks] == [
        "pkg/text.py:Joiner.slow_join lines 12-16",
        "pkg/text.py:slow_sum lines 4-8",
    ]
    assert hot.blocks[1][1].splitlines()[0] == "def slow_sum(values):"
    assert "unused" not in "".join(code for _, code in hot.blocks)
    assert hot.profile == PROFILE and hot.symbols == ("Joiner.slow_join", "slow_sum")
    small = im.hot_code(_repo(), root, limit=len(hot.blocks[1][1]) + 5)
    assert small.symbols == ("slow_sum",)  # a block past the limit is left out
    record = hot.record()
    assert record["experiment"] == im.HOT_EXPERIMENT and record["chars"] == hot.chars
    assert set(record) == {"experiment", "repo", "symbols", "chars", "sha256"}


def test_the_hot_code_refuses_no_match_a_link_and_a_path_outside(
    tmp_path: Path,
) -> None:
    root = _clone(tmp_path, {"pkg/text.py": SOURCE})
    with pytest.raises(ValueError, match="names no function"):
        im.hot_code(_repo(profile="cProfile: re._compile 0.1 s"), root)
    (root / "pkg/link.py").symlink_to(root / "pkg/text.py")
    with pytest.raises(ValueError, match="not a regular file"):
        im.hot_code(_repo(targets=("pkg/link.py",)), root)
    outside = tmp_path / "outside.py"
    outside.write_text(SOURCE, encoding="utf-8")
    (root / "esc").symlink_to(tmp_path)
    with pytest.raises(ValueError, match="not a regular file"):
        im.hot_code(_repo(targets=("esc/outside.py",)), root)
    (root / "pkg/big.py").write_text("#" * (im.MAX_FILE_BYTES + 1), encoding="utf-8")
    with pytest.raises(ValueError, match="more than"):
        im.hot_code(_repo(targets=("pkg/big.py",)), root)


# ---------------------------------------------------------------------------
# One library offline: clone, ask both markers, record; the verdict rows
# ---------------------------------------------------------------------------


def _rows_file(tmp_path: Path) -> tuple[ResultsSink, Path]:
    path = tmp_path / "results.jsonl"
    return ResultsSink({RESULTS_ENV: str(path)}), path


def test_one_library_offline_records_replies_sets_and_the_verdict(
    dry: Path, upstream: og.Upstream, tmp_path: Path
) -> None:
    url, commit = upstream({"pkg/text.py": SOURCE, "LICENSE": "MIT\n"})
    repo = dataclasses.replace(_repo(), url=url, tag="v1", commit=commit)
    rows = [
        *(_row(f"idea {k}", v, rank=k + 1) for k, v in enumerate(("keep", "keep", "reject"))),
        *(_row(f"idea {k}", v, rank=k + 1, rep=2) for k, v in enumerate(("keep", "keep"))),
    ]  # fmt: skip
    plan = im.marker_plan(ENOUGH, rows=rows)
    assert [s.key for s in plan.sets] == ["tomli:1:A"] and len(plan.skipped) == 1
    sink, path = _rows_file(tmp_path)
    recorder = im.MarkerRecorder(plan, sink)
    wire = dg.Wire(_by_title)
    runs: list[LiveRun] = []

    def live(cap: float) -> LiveRun:
        runs.append(wire.run(cap))
        return runs[-1]

    im.run_library(repo, live=live, root=dry, recorder=recorder, policy=og.LOCAL,
                   base=_base())  # fmt: skip
    assert runs[0].cap_usd == plan.library_cap("tomli")
    assert runs[0].spent_usd <= runs[0].cap_usd and len(wire.bodies) == 2
    printed: list[str] = []
    decision = recorder.finish(printed.append)
    assert decision is not None and decision.reason == im.UNDERPOWERED  # 2 positives
    records = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
    kinds = [r["experiment"] for r in records]
    assert kinds.count(im.HOT_EXPERIMENT) == 1
    assert kinds.count(im.REPLY_EXPERIMENT) == 2 and kinds.count(im.SET_EXPERIMENT) == 2
    assert kinds.count(im.SKIPPED_EXPERIMENT) == 1
    assert kinds.count(im.SCORE_EXPERIMENT) == 2 and kinds[-1] == im.VERDICT_EXPERIMENT
    for r in records:
        if r["experiment"] == im.REPLY_EXPERIMENT:
            assert r["order"] == [1, 2, 3] and r["error"] is None
            assert all(len(c) <= 500 for c in r["chunks"])
        if r["experiment"] == im.SET_EXPERIMENT:
            assert (r["auc"], r["generator_auc"], r["pairs"]) == (1.0, 1.0, 2)
    verdict = records[-1]
    assert verdict["chosen"] is None and verdict["positives"] == 4
    assert verdict["comparable"] == 2 and verdict["bar"]["auc"] == im.AUC_BAR
    assert any("Marker validation" in line for line in printed)
    # a cut job leaves its reply rows: the same score and verdict from them
    assert im.score_results(path, rows=rows) == (recorder.candidates(), decision)


def test_a_breach_is_noted_on_the_run_then_raised(
    dry: Path, upstream: og.Upstream
) -> None:
    url, _ = upstream({"pkg/text.py": SOURCE})
    repo = dataclasses.replace(_repo(), url=url, tag="v1", commit="0" * 40)
    plan = im.marker_plan(ENOUGH, rows=[_row("a"), _row("b", "reject", rank=2)])
    wire = dg.Wire(_by_title)
    runs: list[LiveRun] = []

    def live(cap: float) -> LiveRun:
        runs.append(wire.run(cap))
        return runs[-1]

    with pytest.raises(CloneRefusedError):
        im.run_library(repo, live=live, root=dry,
                       recorder=im.MarkerRecorder(plan, ResultsSink({})), policy=og.LOCAL)  # fmt: skip
    assert wire.bodies == [] and wire.counted == []
    assert runs[0].notes[0].startswith("MARKER tomli: breach: CloneRefusedError")


def test_a_planted_key_in_a_reply_is_redacted_and_long_replies_chunked(
    dry: Path,
) -> None:
    secret = "sk-ant-api03-" + "y" * 24
    wire = dg.Wire(lambda b: json.dumps({"order": _ids(b)}) + " " * 600 + secret)
    sink_path = Path(dry) / "r.jsonl"
    recorder = im.MarkerRecorder(
        im.marker_plan(ENOUGH, rows=[_row("a"), _row("b", "reject", rank=2)]),
        ResultsSink({RESULTS_ENV: str(sink_path)}),
    )
    recorder.add(im.ask(im.OPUS_55_MARKER, wire.run(1.0), _set("keep", "reject"),
                        _hot(), base=_base()))  # fmt: skip
    text = sink_path.read_text(encoding="utf-8")
    assert secret not in text and "[redacted]" in text
    reply = next(json.loads(x) for x in text.splitlines() if im.REPLY_EXPERIMENT in x)
    assert len(reply["chunks"]) >= 2 and reply["error"] is not None


def test_finish_with_no_reply_writes_nothing() -> None:
    recorder = im.MarkerRecorder(im.marker_plan(ENOUGH), ResultsSink({}))
    printed: list[str] = []
    assert recorder.finish(printed.append) is None and printed == []


def test_the_verdict_scores_each_marker_against_the_generator_on_its_own_sets() -> None:
    sets = [
        _set("keep", "reject", repo=f"lib{k}", rep=r) for k in range(12) for r in (1, 2)
    ]
    recorder = im.MarkerRecorder(
        im.MarkerPlan(sets=tuple(sets), skipped=(), positives=24, comparable=24),
        ResultsSink({}),
    )
    for s in sets:  # Opus 5.5 reverses every set; Opus 5 agrees with the generator
        recorder.replies.append(
            im.MarkerReply(s, im.OPUS_55_MARKER, (1.0, 2.0), None, 0.1, None)
        )
        recorder.replies.append(
            im.MarkerReply(s, im.OPUS_5_MARKER, (2.0, 1.0), None, 0.1, None)
        )
    recorder.replies.append(
        im.MarkerReply(sets[0], im.OPUS_5_MARKER, None, "x", 0.0, None)
    )
    found = recorder.candidates()
    assert [c.marker for c in found] == [A, B]
    assert (found[0].score.auc, found[1].score.auc) == (0.0, 1.0)
    assert found[0].baseline.auc == found[1].baseline.auc == 1.0
    assert found[1].score.positives == 24 and found[1].baseline_tie
    decision = im.decide(found, positives=24)
    assert (decision.chosen, decision.baseline_ties) == (B, (B,))
    assert math.isclose(found[1].score.low or 0.0, 1.0)


def test_the_recorded_replies_rebuild_the_score_and_the_verdict_offline(
    tmp_path: Path,
) -> None:
    sets = [  # the generator ranks a rival first: its own AUC is 0.5
        _set("reject", "keep", "inconclusive", repo=f"lib{k}", rep=r)
        for k in range(12) for r in (1, 2)
    ]  # fmt: skip
    sink, path = _rows_file(tmp_path)
    sink.write({"experiment": im.HOT_EXPERIMENT, "repo": "lib0"})  # not a reply
    plan = im.MarkerPlan(sets=tuple(sets), skipped=(), positives=24, comparable=24)
    recorder = im.MarkerRecorder(plan, sink)
    for k, s in enumerate(sets):  # Opus 5.5 puts the kept idea last, Opus 5 first
        recorder.add(
            im.MarkerReply(s, im.OPUS_55_MARKER, (3.0, 1.0, 2.0), None, 0.1, None)
        )
        mine = (1.0, 3.0, 2.0) if k % 3 else (3.0, 2.0, 1.0)
        if k == 1:  # an unusable reply: recorded, never scored
            recorder.add(
                im.MarkerReply(s, im.OPUS_5_MARKER, None, "Boom: x", 0.0, None)
            )
        else:
            recorder.add(im.MarkerReply(s, im.OPUS_5_MARKER, mine, None, 0.1, None))
    rows = [r for s in sets for r in s.rows]
    found, decision = im.score_results(path, rows=rows)
    assert found == recorder.candidates()
    assert decision == im.decide(recorder.candidates(), 24)
    assert (decision.chosen, decision.reason) == (B, im.ONE)
    assert found[0].score.auc == 0.0 and found[1].baseline.auc == 0.5
    replies = im.load_replies(path, sets)
    assert len(replies) == 48 and replies[3].error == "Boom: x"
    assert replies[3].scores is None and replies[0].scores == (3.0, 1.0, 2.0)
    assert replies[1].scores == (3.0, 2.0, 1.0) and replies[1].cost_usd == 0.1
    assert found[1].score.positives == 23  # the unusable reply's set left out


def _reply_line(**change: object) -> str:
    row: dict[str, object] = {
        "experiment": im.REPLY_EXPERIMENT, "repo": "tomli", "rep": 1, "arm": "A",
        "marker": A, "model": OPUS, "counted": 918, "sent": True,
        "stop_reason": "end_turn", "usage": [900, 9, 0, 0], "seconds": 1.5,
        "cost_usd": 0.02, "order": [2, 1], "error": None, "chunks": ["{}"],
    }  # fmt: skip
    return json.dumps({**row, **change}) + "\n"


@pytest.mark.parametrize(
    ("lines", "error"),
    [
        ([_reply_line(repo="toml")], "toml:1:A: not a sent set"),
        ([_reply_line(marker="opus-4")], "opus-4: not a marker"),
        ([_reply_line(order=[1, 1])], "not a permutation"),
        ([_reply_line(order=[1])], "not a permutation"),
        ([_reply_line(), _reply_line(order=[1, 2])], "tomli:1:A: opus-5-5 twice"),
        ([_reply_line(why="x")], "Extra inputs"),
        ([_reply_line(order=None, error=None)], "neither an order nor an error"),
        ([_reply_line(rep="1")], "valid integer"),
    ],
)
def test_the_recorded_replies_are_read_strictly(
    tmp_path: Path, lines: list[str], error: str
) -> None:
    path = tmp_path / "r.jsonl"
    path.write_text("".join(lines), encoding="utf-8")
    with pytest.raises(ValueError, match=error):
        im.load_replies(path, [_set("keep", "reject")])


def test_a_recorded_order_gives_each_row_the_markers_score(tmp_path: Path) -> None:
    path = tmp_path / "r.jsonl"
    path.write_text(_reply_line(order=[2, 1]) + _reply_line(marker=B, order=[1, 2]),
                    encoding="utf-8")  # fmt: skip
    first, second = im.load_replies(path, [_set("keep", "reject")])
    assert (first.scores, second.scores) == ((1.0, 2.0), (2.0, 1.0))
    assert (first.marker, second.marker) == (im.OPUS_55_MARKER, im.OPUS_5_MARKER)
    assert first.exchange is None and first.error is None


# ---------------------------------------------------------------------------
# The live module
# ---------------------------------------------------------------------------


def test_the_live_module_is_marked_reads_its_plan_first_and_runs_libraries() -> None:
    source = (LIVE_DIR / "test_ideas_marker_live.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    marks = [
        ast.unparse(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and [ast.unparse(t) for t in node.targets] == ["pytestmark"]
    ]
    assert marks == ["pytest.mark.live"]
    tests = [
        n
        for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")
    ]
    assert [t.name for t in tests] == ["test_ideas_marker"]
    assert "live" in [a.arg for a in tests[0].args.args]
    assert '@pytest.fixture(scope="module")' in source
    assert "marker_plan(os.environ)" in source and "MarkerRecorder(" in source
    calls = {ast.unparse(n.func) for n in ast.walk(tests[0]) if isinstance(n, ast.Call)}
    assert "run_library" in calls and "live" not in calls
    assert "OSS_SELECTABLE, ids=[r.name for r in OSS_SELECTABLE]" in source
