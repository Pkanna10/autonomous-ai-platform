"""Offline guards of the ideas-reaudit suite (V-reaudit, O44, ``ideas_reaudit``).

Not ``live``: these spend nothing. They prove that the pooled re-audit
rebuilds each arm's pool from the recorded replies alone (a replay through
``ideas_probe.run_arm``, checked against the file's own audit), pools the
re-run's X1-1 with run 1's A, X1-0, X1-2 and X1-3 exactly as
``ideas_probe.pool`` does (its order and its 48-idea bound), sends
``ideas_probe.run_audit``'s one request, and writes its rows marked with the
two files' digests; that a missing or mismatched file, a replay that does not
reproduce its file, or a cap below the need, refuses before any spend.

Fakes and what they stand for: ``dg.Wire`` with ``_Answers`` for the Messages
API (a recorded run's replies, then the live auditor); ``_Reader`` for the
project's git objects (the pinned clone's ``GitWorkspace``); ``_facts`` for
``ideas_probe.clone_facts`` (the recorded facts on a fresh clone); a results
file written by ``ideas_probe.ProbeRecorder`` for X1 run 1's and the
re-run's. Run 1's archived file is read as it is. What only a live run
proves: that the four pinned clones replay run 1 and the re-run exactly (a
scratch replay of run 1 reproduced its 48 audit rows on more_itertools,
pyparsing and tomli), and the auditor's reply.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from autonomous_ai_agents.clients.cost import response_cost
from autonomous_ai_agents.common.config import settings
from autonomous_ai_agents.common.errors import LLMRequestError
from autonomous_ai_agents.optimization.idea_review import REVIEW_SYSTEM_PROMPT

from . import ideas_probe as ip
from . import ideas_reaudit as ra
from . import ideas_views as iv
from . import test_discovery_guards as dg
from .conftest import TESTS_DIR
from .discovery import OPUS, ceil_usd
from .discovery_io import ResultsSink
from .discovery_oss import OSS_SELECTABLE
from .test_ideas_probe_guards import (
    CACHED,
    LIB,
    _Answers,
    _base,
    _facts,
    _Reader,
    _reader,
    _repos,
    _starter,
    _views_file,
)

dry = dg.dry

Json = dict[str, Any]
RUN1 = (
    TESTS_DIR.parents[2]
    / ".claude/handoff/step3/idea-lab/x1/ideas-probe-x1-run1-41679255224.jsonl"
)
FOUR = ("more_itertools", "pyparsing", "tomli", "sortedcontainers")


# ---------------------------------------------------------------------------
# The need, the plan, the inputs
# ---------------------------------------------------------------------------


def test_the_need_is_four_audit_requests_at_their_cap_over_run_1s_cost() -> None:
    """Run 1's auditor (41679255224) cost 1.445 USD for four libraries, at
    most 0.381 one; the per-request cap is ``ideas_probe.AUDIT_USD`` (0.69:
    D55's 58,000-token bound and 20,000 output tokens on Opus 5.5), so a
    library's run is capped at it, rounded up as a cap (0.70), and the four
    need 2.80, ci.yml's 3."""
    rows = [json.loads(x) for x in RUN1.read_text("utf-8").splitlines()]
    audits = [r for r in rows if r["experiment"] == ip.REPLY_EXPERIMENT
              and r["role"] == "auditor"]  # fmt: skip
    price = settings.MODEL_PRICING[OPUS]
    costs = [
        (r["usage"][0] * price.input + r["usage"][1] * price.output) / 1e6
        for r in audits
    ]
    assert len(costs) == 4 and max(costs) < ra.LIBRARY_USD
    assert math.fsum(costs) == pytest.approx(ra.RUN1_AUDIT_USD, abs=5e-4)
    assert ra.RUN1_AUDIT_USD == 1.445
    assert ip.AUDIT_USD == pytest.approx(0.69) and max(costs) < ip.AUDIT_USD
    assert ra.LIBRARY_USD == ceil_usd(ip.AUDIT_USD) == 0.70
    plan = ra.ReauditPlan(ra.REAUDIT_LIBRARIES, RUN1, RUN1)
    assert [r.name for r in plan.repos] == sorted(FOUR, key=_selectable)
    assert ra.reaudit_need(plan) == pytest.approx(2.80)
    assert ra.reaudit_need(plan) <= ra.CI_NEED < ra.reaudit_need(plan) + 1


def _selectable(name: str) -> int:
    return [r.name for r in OSS_SELECTABLE].index(name)


def test_the_minutes_are_a_clone_a_replay_and_one_audit_a_library() -> None:
    plan = ra.ReauditPlan(ra.REAUDIT_LIBRARIES, RUN1, RUN1)
    audit = math.ceil(ip.AUDIT_SECONDS / 60)  # 217.2 s: twice E1's slowest
    assert plan.library_minutes() == ra.CLONE_MINUTES + ra.REPLAY_MINUTES + audit
    assert plan.minutes() == 4 * plan.library_minutes() <= ra.JOB_MINUTES


def test_the_plan_reads_both_files_and_the_cap_before_any_spend(
    tmp_path: Path,
) -> None:
    rerun = tmp_path / "rerun.jsonl"
    rerun.write_text("", encoding="utf-8")
    env = {ra.RUN1_ENV: str(RUN1), ra.RERUN_ENV: str(rerun), "LIVE_SUITE_CAP_USD": "3"}
    plan = ra.reaudit_plan(env)
    assert (plan.run1, plan.rerun) == (RUN1, rerun)
    assert plan.facts == ip.SERVICE_DIR / ip.FACTS_FIXTURE
    assert plan.views == ip.SERVICE_DIR / ip.VIEWS_FIXTURE
    for name in (ra.RUN1_ENV, ra.RERUN_ENV):
        with pytest.raises(ValueError, match=f"{name}: name"):
            ra.reaudit_plan({k: v for k, v in env.items() if k != name})
        with pytest.raises(ValueError, match=f"{name}: no recorded"):
            ra.reaudit_plan({**env, name: str(tmp_path / "none.jsonl")})
    with pytest.raises(ValueError, match="below the re-audit's need 2.80"):
        ra.reaudit_plan({**env, "LIVE_SUITE_CAP_USD": "2.79"})


def test_run_1s_archived_file_loads_strictly_with_its_digest() -> None:
    source = ra.load_source(RUN1)
    assert source.sha256 == hashlib.sha256(RUN1.read_bytes()).hexdigest()
    assert set(source.arms) == set(FOUR)
    for name in FOUR:
        assert source.arms[name] == frozenset(a.key for a in ip.X1_ARMS)
        assert sum(a.repo == name for a in source.audits) == ip.AUDIT_MAX_IDEAS
    keys = ra.exchange_keys(
        [r for r in source.replies if (r.repo, r.arm) == ("sortedcontainers", "X1-2")],
        source.lanes_of("sortedcontainers", "X1-2"),
    )  # lane-10 answered no idea: the one re-priced lens no other row names
    labelled = dict(zip(
        [r.label for r in source.replies
         if (r.repo, r.arm) == ("sortedcontainers", "X1-2")], keys, strict=True,
    ))  # fmt: skip
    assert labelled["lane-10"] == "far" and labelled["lane-8"] == "eliminate"
    assert labelled["leap-2"] == "leap" and labelled["reviewer"] == "reviewer"
    for (repo, arm), _ in {(r.repo, r.arm): 0 for r in source.replies}.items():
        if arm == "auditor":
            continue
        mine = [r for r in source.replies if (r.repo, r.arm) == (repo, arm)]
        assert None not in ra.exchange_keys(mine, source.lanes_of(repo, arm))


def _rows(path: Path, rows: Sequence[Json]) -> Path:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def _probe(repo: str, arm: str) -> Json:
    return {"experiment": ip.ROW_EXPERIMENT, "repo": repo, "arm": arm}


def _audit(repo: str, arm: str) -> Json:
    return {
        "experiment": ip.AUDIT_EXPERIMENT, "repo": repo, "arm": arm, "id": "i01",
        "title": "t", "lane": "today", "tier": 0, "in_result": True, "own": None,
        "auditor": "feasible", "reason": "none", "duplicate_of": None,
    }  # fmt: skip


def _file(path: Path, repos: Sequence[str], arms: Sequence[str]) -> Path:
    rows = [_probe(r, a) for r in repos for a in arms]
    return _rows(path, [*rows, *(_audit(r, arms[0]) for r in repos)])


def test_a_mismatched_input_file_refuses_before_any_spend(tmp_path: Path) -> None:
    run1 = ra.load_source(_file(tmp_path / "r1.jsonl", FOUR, ra.RUN1_KEYS))
    rerun = ra.load_source(_file(tmp_path / "rr.jsonl", FOUR, ra.RERUN_KEYS))
    ra.check_sources(run1, rerun, FOUR)
    load = ra.load_source
    wrong = {
        "libraries": (load(_file(tmp_path / "a", FOUR[:3], ra.RUN1_KEYS)), rerun),
        "no X1-1": (run1, load(_file(tmp_path / "b", FOUR, ("A",)))),
        "run 1 twice": (run1, run1),
        "no X1-2": (load(_file(tmp_path / "c", FOUR, ("A", "X1-0", "X1-1", "X1-3"))),
                    rerun),
        "no audit": (run1, load(_rows(tmp_path / "d", [_probe(r, a) for r in FOUR
                                                       for a in ra.RERUN_KEYS]))),
    }  # fmt: skip
    for what, (one, two) in wrong.items():
        with pytest.raises(ValueError, match="X1 run 1|the re-run"):
            ra.check_sources(one, two, FOUR)
        assert what
    bad = _rows(tmp_path / "e", [{**_audit("tomli", "A"), "extra": 1}])
    with pytest.raises(ValueError, match=r"e:1: malformed ideas-audit row"):
        ra.load_source(bad)
    (tmp_path / "f").write_text("not json\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"f:1: not a JSON object"):
        ra.load_source(tmp_path / "f")


def test_the_marked_sink_renames_the_audit_rows_and_adds_both_digests(
    tmp_path: Path,
) -> None:
    out = tmp_path / "out.jsonl"
    sink = ra.ReauditSink({"LIVE_RESULTS_PATH": str(out)},
                          {"run1_sha256": "a" * 64, "rerun_sha256": "b" * 64})  # fmt: skip
    sink.write(_audit("tomli", "A"))
    sink.write({"experiment": ip.REPLY_EXPERIMENT, "arm": "auditor"})
    lines = [json.loads(x) for x in out.read_text("utf-8").splitlines()]
    assert [x["experiment"] for x in lines] == [ra.REAUDIT_EXPERIMENT, "ideas-reply"]
    assert {k: v for k, v in lines[0].items() if k != "experiment"} == {
        **{k: v for k, v in _audit("tomli", "A").items() if k != "experiment"},
        "run1_sha256": "a" * 64, "rerun_sha256": "b" * 64,
    }  # fmt: skip
    assert lines[1]["run1_sha256"] == "a" * 64
    assert (ra.REAUDIT_EXPERIMENT, ip.AUDIT_EXPERIMENT) == (
        "ideas-reaudit",
        "ideas-audit",
    )


# ---------------------------------------------------------------------------
# The replay: exact keys, a failure, a divergence
# ---------------------------------------------------------------------------


def _reply(arm: str, role: str, label: str, *, sent: bool = True) -> ra.ReplyLine:
    return ra.ReplyLine(
        experiment="ideas-reply", repo="tomli", arm=arm, role=role, label=label,
        counted=900, sent=sent, stop_reason="end_turn" if sent else None,
        usage=(1, 2, 3, 4), chars=2, shown=0, seconds=0.0, chunks=("{}",),
    )  # fmt: skip


def test_each_recorded_exchange_is_keyed_by_its_lane_or_the_reviewer() -> None:
    rows = [
        _reply("X1-2", "lane", "obvious"), _reply("X1-2", "lane", "far", sent=False),
        _reply("X1-2", "lane", "eliminate", sent=False),
        _reply("X1-2", "lane", "lane-8"), _reply("X1-2", "lane", "lane-9"),
        _reply("X1-2", "leap", "leap-2"), _reply("X1-2", "reviewer", "reviewer"),
        _reply("A", "generator", "generator"),
    ]  # fmt: skip
    keys = ra.exchange_keys(rows, {"lane-8": "eliminate"})
    assert keys == ["obvious", "far", "eliminate", "eliminate", "far", "leap",
                    "reviewer", "obvious"]  # fmt: skip
    with pytest.raises(
        ValueError, match="cannot tell which lens lane-8, lane-9 answered"
    ):
        ra.exchange_keys(rows, {})


def test_a_replay_serves_each_key_in_order_and_refuses_a_divergence() -> None:
    failed = _reply("C", "lane", "far").model_copy(update={"stop_reason": None})
    replay = ra.Replay([_reply("C", "lane", "obvious"), failed], {})
    assert replay.count("obvious") == 900
    message = replay.send("obvious", OPUS)
    assert (message.model, message.stop_reason) == (OPUS, "end_turn")
    assert (message.usage.input_tokens, message.usage.output_tokens) == (1, 2)
    assert message.usage.cache_read_input_tokens == 3
    assert response_cost(message.usage, settings.MODEL_PRICING, model=OPUS)[0] > 0
    assert replay.count("far") == 900
    with pytest.raises(LLMRequestError, match="failed when recorded"):
        replay.send("far", OPUS)
    replay.check("tomli C")
    with pytest.raises(LLMRequestError, match="replay: no recorded"):
        replay.count("leap")
    with pytest.raises(ValueError, match="tomli C: the replay diverged"):
        replay.check("tomli C")
    left = ra.Replay([_reply("C", "lane", "obvious")], {})
    with pytest.raises(ValueError, match="1 recorded exchange"):
        left.check("tomli C")


# ---------------------------------------------------------------------------
# The pool: recorded arms replayed, run 1's X1-1 swapped for the re-run's
# ---------------------------------------------------------------------------


class _Rerun(_Answers):
    """The re-run's replies: every lane and today idea retitled, so both its
    X1-1 and its own arm A differ from run 1's."""

    def __call__(self, body: Json) -> str:
        text = super().__call__(body).replace('"Idea ', '"Re-run idea ')
        return text.replace('"Today ', '"Re-run today ')


def _arms(keys: Sequence[str], answers: type[_Answers], views: iv.RecordedViews,
          ) -> list[ip.ArmRun]:  # fmt: skip
    body = ip.FactsBody.of(_facts())
    found = []
    for arm in (a for a in ip.X1_ARMS if a.key in keys):
        wire = dg.Wire(answers(), usages=[CACHED] * 20)
        found.append(ip.run_arm(
            arm, wire.run(), _facts(), base=_base(), reader=_reader,
            views=views.build, workloads=(iv.recorded_workload(LIB, body),),
        ))  # fmt: skip
    return found


def _recorded(path: Path, arms: Sequence[ip.ArmRun], plan: ip.ProbePlan) -> Path:
    """A results file as ``ideas_probe.run_library`` writes it."""
    recorder = ip.ProbeRecorder(plan, ResultsSink({"LIVE_RESULTS_PATH": str(path)}),
                                {LIB.name: ip.FactsBody.of(_facts())})  # fmt: skip
    pooled = ip.pool(arms, _facts())
    run = dg.Wire(_Answers(), usages=[CACHED] * 2).run()
    audit = ip.run_audit(pooled, run, _facts(), base=_base(), reader=_reader)
    recorder.record(LIB.name, arms, pooled, audit, run)
    return path


class _World:
    def __init__(self, tmp: Path, cut: int | None = None) -> None:
        body = ip.FactsBody.of(_facts())
        facts = _rows(tmp / "facts.jsonl", [_facts().record()])
        self.views_path = _views_file(tmp / "views.jsonl", body, _Reader())
        views = iv.load_views(self.views_path, {LIB.name: body})[LIB.name]
        plan = ip.ProbePlan(ra.REPLAYED_ARMS, _repos((LIB.name,)), facts,
                            self.views_path)  # fmt: skip
        self.first = _arms(ra.RUN1_KEYS, _Answers, views)
        self.again = _arms(ra.RERUN_KEYS, _Rerun, views)
        self.run1 = _recorded(tmp / "run1.jsonl", self.first, plan)
        self.rerun = _recorded(tmp / "rerun.jsonl", self.again, plan)
        self.plan = ra.ReauditPlan(_repos((LIB.name,)), self.run1, self.rerun,
                                   facts, self.views_path)  # fmt: skip

    def reaudit(self, out: Path) -> ra.Reaudit:
        return ra.Reaudit(self.plan, {"LIVE_RESULTS_PATH": str(out)})


def _titles(arm: ip.ArmRun) -> set[str]:
    assert arm.result is not None
    return {h.title for h in arm.result.hypotheses}


def _seen(pooled: Sequence[ip.Pooled]) -> list[tuple[object, ...]]:
    return [(p.arm, p.idea, p.own, p.in_result) for p in pooled]


@pytest.mark.parametrize("bound", [ip.AUDIT_MAX_IDEAS, 12])
def test_the_pool_is_ideas_probes_with_the_reruns_x1_1_in_its_place(
    bound: int, dry: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Membership exactly as O44 names it, in ``ideas_probe.pool``'s order
    and under its bound (at 12 the bound binds, and the re-run's X1-1 takes
    the slots run 1's held)."""
    monkeypatch.setattr(ip, "AUDIT_MAX_IDEAS", bound)
    world = _World(tmp_path)
    reaudit = world.reaudit(tmp_path / "out.jsonl")
    found = ra.pooled_of(reaudit, LIB, _facts(), base=_base(), reader=_reader)
    mixed = [*world.first[:2], world.again[1], *world.first[3:]]
    assert [a.arm.key for a in mixed] == ["A", "X1-0", "X1-1", "X1-2", "X1-3"]
    assert _seen(found) == _seen(ip.pool(mixed, _facts()))
    assert len(found) <= bound
    assert {p.arm for p in found} <= set(ra.RUN1_KEYS)
    x1_1 = [p.idea.title for p in found if p.arm == "X1-1"]
    assert x1_1 and all(t.startswith("Re-run idea") for t in x1_1)
    assert not any(t.startswith("Re-run") for p in found if p.arm != "X1-1"
                   for t in (p.idea.title,))  # fmt: skip
    again_a = _titles(world.again[0])
    assert again_a and all(t.startswith("Re-run today") for t in again_a)
    first_a = _titles(world.first[0])
    pooled_a = {p.idea.title for p in found if p.arm == "A" and p.in_result}
    assert pooled_a and (pooled_a == first_a if bound > 12 else pooled_a <= first_a)
    if bound == 12:
        assert len(found) == 12 < len(ip.pool(mixed, _facts())) + 1
        assert _seen(found) != _seen(ip.pool(world.first, _facts()))


def test_a_replay_that_does_not_reproduce_its_file_refuses_before_spend(
    dry: Path, tmp_path: Path
) -> None:
    world = _World(tmp_path)
    lines = world.run1.read_text("utf-8").splitlines()
    review = next(i for i, x in enumerate(lines)
                  if '"role": "reviewer"' in x and '"X1-0"' in x)  # fmt: skip
    row = json.loads(lines[review])
    row["chunks"] = [json.dumps({"reviews": []})]  # no verdict: the own differ
    lines[review] = json.dumps(row)
    world.run1.write_text("\n".join(lines) + "\n", encoding="utf-8")
    reaudit = world.reaudit(tmp_path / "out.jsonl")
    runs, start = _starter(dg.Wire(_Answers()))
    with pytest.raises(ValueError, match="X1 run 1: tomli's replayed pool is not"):
        ra.run_library(LIB, live=start, root=tmp_path / "live", reaudit=reaudit,
                       base=_base(), reader=_reader,
                       facts_of=lambda *_: _facts())  # fmt: skip
    assert runs == [] and not (tmp_path / "out.jsonl").exists()


def test_one_library_sends_ideas_probes_audit_and_writes_marked_rows(
    dry: Path, tmp_path: Path
) -> None:
    world = _World(tmp_path)
    out = tmp_path / "out.jsonl"
    reaudit = world.reaudit(out)
    wire = dg.Wire(_Answers(), usages=[CACHED] * 2)
    runs, start = _starter(wire)
    ra.run_library(LIB, live=start, root=tmp_path / "live", reaudit=reaudit,
                   base=_base(), reader=_reader, facts_of=lambda *_: _facts())  # fmt: skip
    (run,) = runs
    assert run.cap_usd == ra.LIBRARY_USD and len(wire.bodies) == 1  # no generation
    (body,) = wire.bodies
    assert (body["model"], body["max_tokens"]) == (OPUS, ip.AUDIT_MAX_TOKENS)
    assert body["output_config"]["effort"] == ip.AUDIT_EFFORT
    assert body["system"][0]["text"] == REVIEW_SYSTEM_PROMPT
    pooled = ra.pooled_of(reaudit, LIB, _facts(), base=_base(), reader=_reader)
    shown = {(x := json.loads(line))["id"]: x["title"] for line in _shown_lines(body)}
    ids = ip.pool_ids(len(pooled))  # run_audit's neutral ids, in pool order
    assert shown == {i: p.idea.title for i, p in zip(ids, pooled, strict=True)}
    lines = [json.loads(x) for x in out.read_text("utf-8").splitlines()]
    rows = [x for x in lines if x["experiment"] == ra.REAUDIT_EXPERIMENT]
    digests = {"run1_sha256": _sha(world.run1), "rerun_sha256": _sha(world.rerun)}
    assert [r["id"] for r in rows] == ip.pool_ids(len(pooled))
    assert [(r["arm"], r["title"], r["own"], r["in_result"]) for r in rows] == [
        (p.arm, p.idea.title, p.own, p.in_result) for p in pooled
    ]
    assert all(r.items() >= digests.items() for r in lines)
    shape = {"experiment", "repo", "arm", "id", "title", "lane", "tier",
             "in_result", "own", "auditor", "reason", "duplicate_of"}  # fmt: skip
    assert all(set(r) == shape | set(digests) for r in rows)
    assert {x["experiment"] for x in lines} == {ra.REAUDIT_EXPERIMENT, "ideas-reply"}
    assert run.notes[0].startswith(f"REAUDIT {LIB.name}: {len(pooled)} pooled, ")
    assert run.notes[1].startswith(f"IDEAS {LIB.name}: audit ")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _shown_lines(body: Json) -> list[str]:
    text = "\n".join(b["text"] for b in body["messages"][0]["content"])
    token = text.split("The review boundary token is ", 1)[1].split(".", 1)[0]
    tag = f"untrusted_model_content boundary={token}>"
    block = text.split(f"<{tag}", 1)[1].split(f"</{tag}", 1)[0]
    return [x for x in block.splitlines() if x.startswith("{")]


def test_a_breach_after_admission_is_noted_then_raised(
    dry: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = _World(tmp_path)
    reaudit = world.reaudit(tmp_path / "out.jsonl")
    runs, start = _starter(dg.Wire(_Answers(), usages=[CACHED] * 2))

    def broken(*_args: object) -> None:
        raise AssertionError("overrun")

    monkeypatch.setattr(ip, "check_spend", broken)
    with pytest.raises(AssertionError, match="overrun"):
        ra.run_library(LIB, live=start, root=tmp_path / "live", reaudit=reaudit,
                       base=_base(), reader=_reader, facts_of=lambda *_: _facts())  # fmt: skip
    (run,) = runs
    assert run.notes[-1] == f"IDEAS {LIB.name}: breach: AssertionError: overrun"


def test_the_reaudit_refuses_mismatched_files_and_missing_facts_on_load(
    dry: Path, tmp_path: Path
) -> None:
    world = _World(tmp_path)
    twice = ra.ReauditPlan(world.plan.repos, world.run1, world.run1,
                           world.plan.facts, world.plan.views)  # fmt: skip
    with pytest.raises(ValueError, match="the re-run"):
        ra.Reaudit(twice, {})
    empty = _rows(tmp_path / "nofacts.jsonl", [])
    none = ra.ReauditPlan(world.plan.repos, world.run1, world.rerun, empty,
                          world.plan.views)  # fmt: skip
    with pytest.raises(ValueError, match="no recorded facts for tomli"):
        ra.Reaudit(none, {})
    found = world.reaudit(tmp_path / "x.jsonl")
    assert found.sink.sources == {
        "run1_sha256": _sha(world.run1), "rerun_sha256": _sha(world.rerun),
    }  # fmt: skip
