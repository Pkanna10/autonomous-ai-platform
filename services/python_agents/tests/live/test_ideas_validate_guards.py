"""Offline guards of the ideas-validate suite (Vc, ``ideas_validate.py``).

Not ``live``: these spend nothing. They prove, before a dollar goes to
``test_ideas_validate_live.py``, that the smoke requests go to Sonnet 5 and
Fable 5 first and once each, that a refusal, an error or a breach (over its
cap, or wire and records apart) fails them and admits no label request, that the
labeller wrote none of E1's ideas (the writer set derived here from E1's
recorded rows), that the pairs and the score are ``idea_dedupe``'s own, that
the owner's spot-check sample is seeded and carries no label or source, and
that the caps refuse before any spend.

Fakes and what they stand for: ``dg.Wire`` for the Messages API (the live
run's captured ``AnthropicTransport``; counts are a fixed 900 tokens, plus
the transport's margin and allowance); ``_Answer`` for the labeller's and
the smoke models' replies. Real: V6's ``recorded.json`` and its vendored
code, E1's two committed results files, ``idea_dedupe``. What only a live
run proves: the real counts against the bounds, the models' labels.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import shutil
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx2
import pytest

from autonomous_ai_agents.common.config import (
    RETENTION_REQUIRED_MODELS,
    Settings,
    role_chain,
    settings,
)
from autonomous_ai_agents.common.errors import BudgetExceeded
from autonomous_ai_agents.optimization import idea_dedupe as dd

from . import ideas_validate as iv
from . import test_discovery_guards as dg
from .conftest import TESTS_DIR, LiveRun
from .discovery import OPUS, ceil_usd
from .discovery_io import ResultsSink
from .ideas_probe import request_usd

dry = dg.dry
Json = dict[str, Any]
LIVE_DIR = TESTS_DIR / "live"
# E1's writers, read off its ideas-probe rows (arms A-E) by hand on
# 2026-11-03: the auditor was Opus 5.5 (ideas_probe.run_audit)
E1_WRITERS = {
    "claude-sonnet-5-5",
    "claude-opus-5-5",
    "claude-fable-5-1",
    "claude-haiku-5-5",
}
V6_PAIRS = 398  # candidate_pairs over V6's recorded.json (arm C, two libraries)
E1_ADDED_PAIRS = 831  # arms B, D and E on the same two libraries
OVERLAPPING = 190  # every pair whose target lines overlap (V6 56, E1 134)


def _base() -> Settings:
    return Settings.model_validate({"LLM_MAX_RETRIES": 0, "ENGINE_FALLBACKS": False})


def _text(body: Json) -> str:
    return str(body["messages"][0]["content"][0]["text"])


def _all_different(body: Json) -> str:
    ids = re.findall(r'"pair": "(P\d+)"', _text(body))
    labels = [{"pair": i, "same": False, "reason": "Other lines."} for i in ids]
    return json.dumps({"labels": labels})


def _answer(body: Json) -> str:
    """The smoke's ``ok`` or a well-formed label reply, by the schema."""
    keys = set(body["output_config"]["format"]["schema"]["properties"])
    return json.dumps({"reply": "ok"}) if keys == {"reply"} else _all_different(body)


def _sink(tmp_path: Path) -> ResultsSink:
    return ResultsSink({"LIVE_RESULTS_PATH": str(tmp_path / "results.jsonl")})


def _rows(tmp_path: Path) -> list[Json]:
    path = tmp_path / "results.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    return [json.loads(line) for line in lines]


@pytest.fixture(scope="module")
def plan() -> iv.ValidatePlan:
    return iv.validate_plan({"LIVE_SUITE_CAP_USD": str(iv.NEED_USD)})


def _recorder(plan: iv.ValidatePlan, tmp_path: Path) -> iv.ValidateRecorder:
    return iv.ValidateRecorder(plan, _sink(tmp_path))


# ---------------------------------------------------------------------------
# The smoke requests (O36.5e)
# ---------------------------------------------------------------------------


def test_the_smoke_models_are_the_two_x1_adds_with_g1s_price_rows() -> None:
    assert iv.SMOKE_MODELS == ("claude-sonnet-5", "claude-fable-5")
    for model in iv.SMOKE_MODELS:
        assert model in settings.MODEL_PRICING, model
        worst = request_usd(iv.SMOKE_PROMPT_BOUND, iv.SMOKE_MAX_TOKENS, model)
        assert iv.smoke_worst(model) == worst
    assert ceil_usd(sum(map(iv.smoke_worst, iv.SMOKE_MODELS))) <= 0.25  # spec ~0.1


def test_only_fables_smoke_copy_admits_a_retention_model() -> None:
    """D63: Fable 5 keeps data 30 days; its copy alone sets the flag, and
    the smoke request it is sent holds no repository text."""
    fable = iv.smoke_settings(iv.FABLE_5, _base())
    sonnet = iv.smoke_settings(iv.SONNET_5, _base())
    assert iv.FABLE_5 in RETENTION_REQUIRED_MODELS
    assert fable.ALLOW_RETENTION_MODELS and role_chain(fable, "engine") == (iv.FABLE_5,)
    assert not sonnet.ALLOW_RETENTION_MODELS
    assert role_chain(sonnet, "engine") == (iv.SONNET_5,)
    assert not iv.labeller_settings(_base()).ALLOW_RETENTION_MODELS
    request = iv.smoke_request()
    assert request.messages[0]["content"][0]["text"] == iv.SMOKE_TEXT  # type: ignore[index]


def test_each_smoke_sends_one_minimal_capped_request_and_records_it(
    dry: Path, plan: iv.ValidatePlan, tmp_path: Path
) -> None:
    wire = dg.Wire(_answer)
    recorder = _recorder(plan, tmp_path)
    for model in iv.SMOKE_MODELS:
        run = wire.run(plan.smoke_cap(model))
        result = recorder.smoke(model, run, base=_base())
        assert result.error is None and result.served == model
        assert run.spent_usd <= run.cap_usd
    assert [b["model"] for b in wire.bodies] == list(iv.SMOKE_MODELS)
    assert all(b["max_tokens"] == iv.SMOKE_MAX_TOKENS for b in wire.bodies)
    assert len(wire.counted) == 2  # each counted before it was sent
    rows = [r for r in _rows(tmp_path) if r["experiment"] == iv.SMOKE_EXPERIMENT]
    assert [r["model"] for r in rows] == list(iv.SMOKE_MODELS)
    assert all(r["stop_reason"] == "end_turn" and r["usage"][:2] == [1000, 200]
               for r in rows)  # fmt: skip
    assert all(r["served"] == r["model"] and r["error"] is None for r in rows)
    recorder.ready()  # both passed: the labels may start


def test_a_second_smoke_of_one_model_is_refused_before_the_wire(
    dry: Path, plan: iv.ValidatePlan, tmp_path: Path
) -> None:
    wire = dg.Wire(_answer)
    recorder = _recorder(plan, tmp_path)
    recorder.smoke(iv.SONNET_5, wire.run(), base=_base())
    with pytest.raises(ValueError, match="once"):
        recorder.smoke(iv.SONNET_5, wire.run(), base=_base())
    assert len(wire.bodies) == 1 and len(wire.counted) == 1
    with pytest.raises(ValueError, match="not a smoke model"):
        recorder.smoke(OPUS, wire.run(), base=_base())


def _refusing(request: httpx2.Request) -> httpx2.Response:
    body: Json = json.loads(request.read())
    if request.url.path.endswith("/count_tokens"):
        return httpx2.Response(200, json={"input_tokens": 900}, request=request)
    message = {
        "id": "msg_1", "type": "message", "role": "assistant", "model": body["model"],
        "content": [{"type": "text", "text": "I cannot help with that."}],
        "stop_reason": "refusal", "stop_sequence": None, "usage": dg.USAGE,
    }  # fmt: skip
    return httpx2.Response(200, json=message, request=request)


def _failing(request: httpx2.Request) -> httpx2.Response:
    if request.url.path.endswith("/count_tokens"):
        return httpx2.Response(200, json={"input_tokens": 900}, request=request)
    error = {"type": "error", "error": {"type": "invalid_request_error",
                                        "message": "model not found"}}  # fmt: skip
    return httpx2.Response(404, json=error, request=request)


@pytest.mark.parametrize("handler", [_refusing, _failing], ids=["refusal", "error"])
def test_a_smoke_refusal_or_error_fails_the_suite_and_blocks_the_labels(
    dry: Path,
    plan: iv.ValidatePlan,
    tmp_path: Path,
    handler: Callable[[httpx2.Request], httpx2.Response],
) -> None:
    recorder = _recorder(plan, tmp_path)
    started: list[float] = []

    def live(cap: float) -> LiveRun:
        started.append(cap)
        return LiveRun("dry", cap, wire=httpx2.MockTransport(handler))

    with pytest.raises(iv.SmokeFailedError, match=iv.FABLE_5):
        iv.run_smoke(iv.FABLE_5, live=live, recorder=recorder, base=_base())
    [row] = _rows(tmp_path)
    assert row["experiment"] == iv.SMOKE_EXPERIMENT and row["error"]
    with pytest.raises(iv.SmokeFailedError):
        iv.run_labels(live=live, recorder=recorder, base=_base())
    assert started == [plan.smoke_cap(iv.FABLE_5)]  # the labels never started


def test_the_labels_are_refused_until_both_smokes_passed(
    dry: Path, plan: iv.ValidatePlan, tmp_path: Path
) -> None:
    wire = dg.Wire(_answer)
    recorder = _recorder(plan, tmp_path)
    recorder.smoke(iv.SONNET_5, wire.run(), base=_base())
    with pytest.raises(iv.SmokeFailedError, match=iv.FABLE_5):
        recorder.label(wire.run(plan.label_cap()), base=_base())
    assert [b["model"] for b in wire.bodies] == [iv.SONNET_5]


# ---------------------------------------------------------------------------
# The labeller wrote none of E1's ideas
# ---------------------------------------------------------------------------


def test_the_labeller_is_outside_the_writer_set_of_e1s_rows() -> None:
    """The writers derived here from E1's ideas-probe rows (every arm's
    billed models) and its auditor; the harness's set holds them all."""
    found: set[str] = {OPUS}  # the auditor: ideas_probe.run_audit on Opus 5.5
    for path in sorted(iv.E1_DIR.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row["experiment"] == "ideas-probe":
                assert row["arm"] in {"A", "B", "C", "D", "E"}
                found.update(row["models"])
    assert found == E1_WRITERS
    writers = iv.writer_models()
    assert found <= writers
    assert iv.LABELLER == "claude-opus-5" and iv.LABELLER not in writers
    assert iv.LABELLER in settings.MODEL_PRICING
    for model in sorted(writers):
        with pytest.raises(ValueError, match="wrote"):
            iv.check_labeller(model, writers)
    assert role_chain(iv.labeller_settings(_base()), "engine") == (iv.LABELLER,)


def test_a_probe_row_with_other_keys_is_refused(tmp_path: Path) -> None:
    row = {"experiment": "ideas-probe", "repo": "x", "arm": "A", "models": ["m"],
           "author": "someone"}  # fmt: skip
    (tmp_path / "r.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="ideas-probe row"):
        iv.writer_models(tmp_path)
    del row["author"]
    row["models"] = "m"  # not a list of model ids
    (tmp_path / "r.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="ideas-probe row"):
        iv.writer_models(tmp_path)
    row["models"] = ["claude-x"]
    (tmp_path / "r.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    assert "claude-x" in iv.writer_models(tmp_path)  # E1's older rows: a subset


# ---------------------------------------------------------------------------
# The pairs: idea_dedupe's own, V6 and what E1 adds
# ---------------------------------------------------------------------------


def test_the_pairs_are_idea_dedupes_over_v6_and_e1s_other_arms(
    plan: iv.ValidatePlan,
) -> None:
    v6 = dd.candidate_pairs(dd.load_recorded(iv.V6))
    assert len(v6) == V6_PAIRS
    groups = {p.first.library for p in plan.pairs}
    assert groups == {f"{r}/{a}" for r in ("sqlparse", "tomli") for a in "BCDE"}
    mine = [p for p in plan.pairs if p.first.library.endswith("/C")]
    assert [p.id.replace("/C:", ":", 1) for p in mine] == [p.id for p in v6]
    assert [(p.overlap, p.merged) for p in mine] == [(p.overlap, p.merged) for p in v6]
    assert len(plan.pairs) == V6_PAIRS + E1_ADDED_PAIRS
    assert len({p.id for p in plan.pairs}) == len(plan.pairs)
    for p in plan.pairs:  # the dedupe's own verdict on every pair
        assert p.first.library == p.second.library and p.first.path == p.second.path
        assert p == dd.candidate_pair(p.first, p.second).model_copy(update={"id": p.id})


def test_e1s_arm_c_must_be_v6(tmp_path: Path) -> None:
    """V6 is E1's arm C as recorded: a differing arm C is refused."""
    copy = tmp_path / "e1"
    shutil.copytree(iv.E1_DIR, copy)
    path = sorted(copy.glob("*.jsonl"))[1]  # sqlparse's dispatch
    lines = path.read_text(encoding="utf-8").splitlines()
    for k, line in enumerate(lines):
        row = json.loads(line)
        if (row["experiment"], row["repo"], row.get("arm"), row.get("label")) == (
            "ideas-reply", "sqlparse", "C", "far"
        ):  # fmt: skip
            row["chunks"] = ['{"hypotheses": []}']
            lines[k] = json.dumps(row)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="arm C"):
        iv.recorded_ideas(e1_dir=copy)


def test_the_chosen_pairs_are_every_overlap_and_an_equal_seeded_draw(
    plan: iv.ValidatePlan,
) -> None:
    near = [p for p in plan.pairs if p.overlap]
    assert len(near) == OVERLAPPING
    assert all(p in plan.chosen for p in near)
    assert len(plan.chosen) == 2 * OVERLAPPING
    assert iv.selected(plan.pairs) == plan.chosen  # deterministic
    assert iv.selected(tuple(reversed(plan.pairs))) == tuple(reversed(plan.chosen))
    assert [p for p in plan.pairs if p in plan.chosen] == list(plan.chosen)
    assert sum(p.merged for p in plan.chosen) == sum(p.merged for p in plan.pairs)


def test_each_chunk_is_one_group_within_the_request_limits(
    plan: iv.ValidatePlan,
) -> None:
    assert tuple(p for c in plan.chunks for p in c.pairs) == plan.chosen
    for chunk in plan.chunks:
        assert len({p.first.library for p in chunk.pairs}) == 1
        assert len(chunk.pairs) <= iv.PAIRS_PER_REQUEST
        assert len(chunk.ideas) <= iv.IDEAS_PER_REQUEST
        request, ids = iv.label_request(chunk)
        assert iv.byte_bound(request) <= iv.LABEL_PROMPT_BOUND  # even uncounted
        assert len(ids) == len(chunk.pairs)
    assert len(plan.chunks) == iv.LABEL_REQUESTS


def test_the_label_request_hides_the_key_and_the_source() -> None:
    """The labeller sees each idea's file, target lines, title, change and
    quote under neutral ids; never its mechanism, cell, lane or arm, nor
    the dedupe's verdict. A line holding the fence token is withheld."""
    chunk = iv.validate_plan({"LIVE_SUITE_CAP_USD": "150"}).chunks[0]
    request, ids = iv.label_request(chunk)
    text = request.messages[0]["content"][0]["text"]  # type: ignore[index]
    shown = [json.loads(x) for x in text.splitlines() if x.startswith('{"id"')]
    assert {k for s in shown for k in s} == {"id", "file", "lines", "title",
                                             "change", "quote"}  # fmt: skip
    assert [s["id"] for s in shown] == [f"A{k + 1}" for k in range(len(chunk.ideas))]
    assert f"{chunk.pairs[0].first.library}:" not in text
    for idea in chunk.ideas:  # no lane-position id, mechanism or cell value
        assert f'"{idea.ident}"' not in text, idea.ident
        assert f'"{idea.mechanism.value}"' not in text
        assert all(f'"{cell.value}"' not in text for cell in idea.morph_cells)
    for word in ("merged", "overlap", "mechanism", "cell"):
        assert f'"{word}"' not in text, word
    assert ids == tuple(f"P{k + 1:02d}" for k in range(len(chunk.pairs)))
    first = chunk.ideas[0]
    token = re.search(r"boundary token is (\w+)\.", text)
    assert token is not None
    planted = first.model_copy(update={"title": f"x {token.group(1)} y"})
    from autonomous_ai_agents.clients.structured import Fence

    fence = Fence(token.group(1))
    lines = iv.idea_lines((planted, *chunk.ideas[1:]), fence)
    assert lines[0] == iv.WITHHELD and token.group(1) not in "".join(lines[1:])


# ---------------------------------------------------------------------------
# Labels, the score and the refusals
# ---------------------------------------------------------------------------


def _ready(recorder: iv.ValidateRecorder, wire: dg.Wire) -> None:
    for model in iv.SMOKE_MODELS:
        recorder.smoke(model, wire.run(), base=_base())


def test_the_score_is_idea_dedupes_against_its_fixed_bar(
    dry: Path, plan: iv.ValidatePlan, tmp_path: Path
) -> None:
    wire = dg.Wire(_answer)
    recorder = _recorder(plan, tmp_path)
    _ready(recorder, wire)
    run = wire.run(plan.label_cap())
    recorder.label(run, base=_base())
    assert run.spent_usd <= run.cap_usd
    sent = [b for b in wire.bodies if b["model"] == iv.LABELLER]
    assert len(sent) == iv.LABEL_REQUESTS
    assert all(b["max_tokens"] == iv.LABEL_MAX_TOKENS for b in sent)
    score = recorder.finish(lambda _line: None)
    labels = [dd.PairLabel(pair_id=p.id, same=False) for p in plan.chosen]
    assert score == dd.score(plan.chosen, labels)
    rows = _rows(tmp_path)
    [row] = [r for r in rows if r["experiment"] == iv.SCORE_EXPERIMENT]
    assert row["score"] == score.model_dump(mode="json")
    assert row["bar"] == {"min_agreement": 0.9, "max_different_merged": 0.05}
    assert row["labeller"] == iv.LABELLER and iv.LABELLER not in row["writers"]
    assert row["chosen"] == 2 * OVERLAPPING and row["unlabelled"] == 0
    labelled = [r for r in rows if r["experiment"] == iv.LABEL_EXPERIMENT]
    assert [r["pair_id"] for r in labelled] == [p.id for p in plan.chosen]
    assert all(r["same"] is False and r["reason"] == ["Other lines."]
               for r in labelled)  # fmt: skip


def _one_chunk_plan(plan: iv.ValidatePlan) -> iv.ValidatePlan:
    chunk = plan.chunks[0]
    return iv.ValidatePlan(plan.pairs, chunk.pairs, (chunk,), plan.writers)


def _bad_replies(body: Json) -> list[str]:
    ids = re.findall(r'"pair": "(P\d+)"', _text(body))
    good = [{"pair": i, "same": True, "reason": "Same lines."} for i in ids]
    return [
        json.dumps({"labels": good[1:]}),  # a pair missing
        json.dumps({"labels": [*good, good[0]]}),  # a pair twice
        json.dumps({"labels": [*good[1:], {**good[0], "pair": "P99"}]}),  # unknown
        json.dumps({"labels": [{**good[0], "extra": 1}, *good[1:]]}),  # a key more
        json.dumps({"labels": [{**good[0], "same": "yes"}, *good[1:]]}),  # a type
        json.dumps({"labels": [{**good[0], "reason": " "}, *good[1:]]}),  # empty
        json.dumps({"labels": [{**good[0], "reason": "x" * 241}, *good[1:]]}),
        json.dumps({"labels": [{**good[0], "reason": "a\nb"}, *good[1:]]}),
        "not json",
    ]


@pytest.mark.parametrize("k", range(9))
def test_a_malformed_label_reply_is_refused_and_recorded(
    dry: Path, plan: iv.ValidatePlan, tmp_path: Path, k: int
) -> None:
    small = _one_chunk_plan(plan)
    wire = dg.Wire(
        lambda b: _answer(b) if "reply" in _schema(b) else _bad_replies(b)[k]
    )
    recorder = _recorder(small, tmp_path)
    _ready(recorder, wire)
    with pytest.raises(iv.LabelsIncompleteError, match="1 of 1"):
        iv.run_labels(live=lambda cap: wire.run(cap), recorder=recorder, base=_base())
    rows = _rows(tmp_path)
    assert not [r for r in rows if r["experiment"] == iv.LABEL_EXPERIMENT]
    [reply] = [r for r in rows if r["experiment"] == iv.LABEL_REPLY_EXPERIMENT]
    assert reply["error"] and reply["sent"] and reply["labelled"] == 0
    assert recorder.finish(lambda _line: None) is None  # no label: no score
    [row] = [r for r in _rows(tmp_path) if r["experiment"] == iv.SCORE_EXPERIMENT]
    assert row["score"] is None and row["unlabelled"] == len(small.chosen)


def _schema(body: Json) -> set[str]:
    return set(body["output_config"]["format"]["schema"]["properties"])


class _BigCount(dg.Wire):
    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/count_tokens"):
            self.counted.append(json.loads(request.read()))
            body = {"input_tokens": iv.LABEL_PROMPT_BOUND}
            return httpx2.Response(200, json=body, request=request)
        return super().__call__(request)


def test_a_count_past_the_bound_is_refused_before_the_wire(
    dry: Path, plan: iv.ValidatePlan, tmp_path: Path
) -> None:
    wire = _BigCount(_answer)
    small = _one_chunk_plan(plan)
    recorder = _recorder(small, tmp_path)
    _ready(recorder, dg.Wire(_answer))
    result = iv.label_chunk(small.chunks[0], wire.run(small.label_cap()), base=_base())
    assert result.error is not None and BudgetExceeded.__name__ in result.error
    assert not wire.bodies and len(wire.counted) == 1


def test_the_plan_refuses_a_cap_below_its_need_before_any_spend() -> None:
    plan = iv.validate_plan({"LIVE_SUITE_CAP_USD": "150"})
    need = iv.validate_need(plan)
    assert need == pytest.approx(
        sum(plan.smoke_cap(m) for m in iv.SMOKE_MODELS) + plan.label_cap()
    )
    assert plan.label_cap() == ceil_usd(iv.LABEL_REQUESTS * iv.label_worst())
    assert iv.label_worst() == request_usd(
        iv.LABEL_PROMPT_BOUND, iv.LABEL_MAX_TOKENS, iv.LABELLER
    )
    assert need <= iv.NEED_USD < need + 1  # ci.yml's need, rounded up
    assert plan.minutes() <= iv.JOB_MINUTES
    with pytest.raises(ValueError, match="below the suite's need"):
        iv.validate_plan({"LIVE_SUITE_CAP_USD": str(iv.NEED_USD - 1)})
    iv.validate_plan({})  # the 12 USD default covers it


def test_a_writer_as_labeller_is_refused_in_the_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(iv, "LABELLER", "claude-fable-5-1")  # arm D's leap
    with pytest.raises(ValueError, match="wrote"):
        iv.validate_plan({"LIVE_SUITE_CAP_USD": "150"})


# ---------------------------------------------------------------------------
# The owner's spot-check sample and the records
# ---------------------------------------------------------------------------


def test_the_spot_check_sample_is_seeded_and_carries_no_label_or_source(
    plan: iv.ValidatePlan,
) -> None:
    rows = iv.spot_check(plan.chosen)
    assert rows == iv.spot_check(plan.chosen)
    assert len(rows) == iv.SAMPLE_SIZE == 20
    assert rows != iv.spot_check(plan.chosen, seed=iv.SAMPLE_SEED + 1)
    keys = {hashlib.sha256(f"{iv.SAMPLE_SEED}:{p.id}".encode()).hexdigest()[:16]: p
            for p in plan.chosen}  # fmt: skip
    for k, row in enumerate(rows):
        assert set(row) == {"experiment", "sample", "seed", "key", "chunks"}
        assert row["sample"] == f"S{k + 1:02d}" and row["key"] in keys
        chunks = row["chunks"]
        assert isinstance(chunks, tuple)
        shown = json.loads("".join(chunks))
        assert set(shown) == {"a", "b"}
        for idea in shown.values():
            assert set(idea) == {"file", "lines", "title", "change", "quote"}
        pair = keys[row["key"]]
        assert shown["a"]["title"] == pair.first.title[: iv.TITLE_CHARS]
    blob = json.dumps(rows)
    assert all(p.id not in blob and p.first.library not in blob for p in plan.chosen)


def test_model_text_is_redacted_and_chunked_in_every_row(
    dry: Path, plan: iv.ValidatePlan, tmp_path: Path
) -> None:
    key = "sk-ant-" + "A" * 24

    def leaky(body: Json) -> str:
        if "reply" in _schema(body):
            return json.dumps({"reply": "ok"})
        ids = re.findall(r'"pair": "(P\d+)"', _text(body))
        reason = f"see {key}"
        return json.dumps({"labels": [{"pair": i, "same": True, "reason": reason}
                                      for i in ids]})  # fmt: skip

    small = _one_chunk_plan(plan)
    wire = dg.Wire(leaky)
    recorder = _recorder(small, tmp_path)
    _ready(recorder, wire)
    recorder.label(wire.run(small.label_cap()), base=_base())
    recorder.finish(lambda _line: None)
    text = (tmp_path / "results.jsonl").read_text(encoding="utf-8")
    assert key not in text and "[redacted]" in text
    for row in _rows(tmp_path):
        for name in ("chunks", "reason"):
            if name in row:
                assert isinstance(row[name], list), (row["experiment"], name)


def test_finish_writes_the_summary_and_nothing_before_any_run(
    plan: iv.ValidatePlan, tmp_path: Path
) -> None:
    recorder = _recorder(plan, tmp_path)
    lines: list[str] = []
    assert recorder.finish(lines.append) is None
    assert not lines and not _rows(tmp_path)


def test_the_live_file_runs_the_smokes_before_the_labels() -> None:
    tree = ast.parse((LIVE_DIR / "test_ideas_validate_live.py").read_text("utf-8"))
    tests = [n.name for n in tree.body
             if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")]  # fmt: skip
    assert tests == ["test_smoke", "test_dedupe_labels"]


def test_an_e1_reply_recorded_twice_is_refused(tmp_path: Path) -> None:
    path = sorted(iv.E1_DIR.glob("*.jsonl"))[0]
    line = next(x for x in path.read_text(encoding="utf-8").splitlines()
                if '"experiment": "ideas-reply"' in x)  # fmt: skip
    (tmp_path / "r.jsonl").write_text(f"{line}\n{line}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="recorded twice"):
        iv.e1_replies(tmp_path)


def test_a_smoke_served_by_another_model_fails(
    dry: Path, plan: iv.ValidatePlan, tmp_path: Path
) -> None:
    def other(request: httpx2.Request) -> httpx2.Response:
        response = dg.Wire(_answer)(request)
        if request.url.path.endswith("/count_tokens"):
            return response
        body = {**json.loads(response.read()), "model": iv.SONNET_5}
        return httpx2.Response(200, json=body, request=request)

    recorder = _recorder(plan, tmp_path)
    run = LiveRun("dry", 1.0, wire=httpx2.MockTransport(other))
    result = recorder.smoke(iv.FABLE_5, run, base=_base())
    assert result.error is not None and "served by" in result.error
    with pytest.raises(iv.SmokeFailedError):
        recorder.ready()


def test_a_plan_past_the_jobs_minutes_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(iv, "JOB_MINUTES", 2 * iv.REQUEST_MINUTES)
    with pytest.raises(ValueError, match="minutes"):
        iv.validate_plan({"LIVE_SUITE_CAP_USD": "150"})


def _passed(recorder: iv.ValidateRecorder) -> None:
    """Both smokes passed, set by hand: only the labels path is tested."""
    for model in iv.SMOKE_MODELS:
        recorder.smokes[model] = iv.SmokeResult(model, model, None, 0.0, None)


def test_a_breach_is_noted_on_the_run_then_raised(
    dry: Path, plan: iv.ValidatePlan, tmp_path: Path
) -> None:
    """A run over its cap (here a cap of 0) is noted and raised, smoke and
    labels alike; the per-request budget is the run's own bound."""
    wire = dg.Wire(_answer)
    runs: list[LiveRun] = []

    def live(cap: float) -> LiveRun:
        runs.append(wire.run(0.0))
        return runs[-1]

    with pytest.raises(AssertionError):
        iv.run_smoke(
            iv.SONNET_5, live=live, recorder=_recorder(plan, tmp_path), base=_base()
        )
    recorder = _recorder(_one_chunk_plan(plan), tmp_path)
    _passed(recorder)
    with pytest.raises(AssertionError):
        iv.run_labels(live=live, recorder=recorder, base=_base())
    assert [r.notes[0].split(":")[0] for r in runs] == [
        f"VALIDATE {iv.SONNET_5}", "VALIDATE labels",
    ]  # fmt: skip


def _breach_then_labels(
    recorder: iv.ValidateRecorder, live: Callable[[float], LiveRun], tmp_path: Path
) -> None:
    """After the breached Sonnet smoke and a clean Fable smoke, the smoke is
    a failed one (stored and recorded once), and no label run starts."""
    found = recorder.smokes[iv.SONNET_5]
    assert found.error is not None and found.error.startswith("breach: ")
    rows = [r for r in _rows(tmp_path) if r["experiment"] == iv.SMOKE_EXPERIMENT]
    assert [r["model"] for r in rows] == [iv.SONNET_5]
    assert rows[0]["error"] == found.error and rows[0]["cost_usd"] == found.cost_usd
    iv.run_smoke(iv.FABLE_5, live=dg.Wire(_answer).run, recorder=recorder, base=_base())
    with pytest.raises(iv.SmokeFailedError, match="breach"):
        iv.run_labels(live=live, recorder=recorder, base=_base())
    with pytest.raises(ValueError, match="sent once"):
        recorder.smoke(iv.SONNET_5, dg.Wire(_answer).run(), base=_base())


def test_a_smoke_over_its_cap_is_a_failed_smoke_and_admits_no_labels(
    dry: Path, plan: iv.ValidatePlan, tmp_path: Path
) -> None:
    wire = dg.Wire(_answer)
    runs: list[LiveRun] = []

    def live(cap: float) -> LiveRun:
        runs.append(wire.run(0.0))
        return runs[-1]

    recorder = _recorder(plan, tmp_path)
    with pytest.raises(AssertionError):
        iv.run_smoke(iv.SONNET_5, live=live, recorder=recorder, base=_base())
    assert recorder.smokes[iv.SONNET_5].cost_usd > 0  # it was sent and charged
    _breach_then_labels(recorder, live, tmp_path)
    assert len(runs) == 1  # the label run never started: nothing admitted


def test_a_retried_529_smoke_is_one_record_per_attempt_and_passes(
    dry: Path, plan: iv.ValidatePlan, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 529 retried by ``call`` is no breach: ``RecordingTransport`` records
    the refused attempt (at 0 USD) beside the served one, so the wire and the
    records agree (the SDK itself never retries, ``max_retries=0``)."""
    wire, sent = dg.Wire(_answer), [0]

    def flaky(request: httpx2.Request) -> httpx2.Response:
        if not request.url.path.endswith("/count_tokens") and not sent[0]:
            sent[0] += 1
            return httpx2.Response(529, json={"type": "error"}, request=request)
        return wire(request)

    run = LiveRun("dry", plan.smoke_cap(iv.SONNET_5), wire=httpx2.MockTransport(flaky))
    monkeypatch.setattr(time, "sleep", lambda _s: None)  # call()'s 1 s backoff
    retrying = Settings.model_validate(
        {"LLM_MAX_RETRIES": 1, "ENGINE_FALLBACKS": False}
    )
    recorder = _recorder(plan, tmp_path)
    iv.run_smoke(iv.SONNET_5, live=lambda _cap: run, recorder=recorder, base=retrying)
    assert len(run.capture.messages()) == len(run.records) == 2
    assert recorder.smokes[iv.SONNET_5].error is None


def test_a_wire_record_mismatch_is_a_failed_smoke_and_admits_no_labels(
    dry: Path, plan: iv.ValidatePlan, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A record with no wire message (spend under the cap) breaks ``_checked``."""
    real = iv.send_smoke

    def stray(model: str, run: LiveRun, *, base: Settings) -> iv.SmokeResult:
        result = real(model, run, base=base)
        run.records.append(run.records[-1])
        return result

    monkeypatch.setattr(iv, "send_smoke", stray)
    runs: list[LiveRun] = []

    def live(cap: float) -> LiveRun:
        runs.append(dg.Wire(_answer).run(cap))
        return runs[-1]

    recorder = _recorder(plan, tmp_path)
    with pytest.raises(AssertionError):
        iv.run_smoke(iv.SONNET_5, live=live, recorder=recorder, base=_base())
    assert runs[0].spent_usd <= runs[0].cap_usd
    monkeypatch.setattr(iv, "send_smoke", real)
    _breach_then_labels(recorder, live, tmp_path)
    assert len(runs) == 1


def test_a_smoke_that_raises_unexpectedly_is_stored_failed_and_not_resent(
    dry: Path, plan: iv.ValidatePlan, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An error ``send_smoke`` does not catch still leaves a failed smoke, so
    the model is never sent a second smoke request."""

    def boom(*_a: object, **_k: object) -> iv.SmokeResult:
        raise RuntimeError("not an arm error")

    real = iv.send_smoke
    monkeypatch.setattr(iv, "send_smoke", boom)
    recorder = _recorder(plan, tmp_path)
    runs: list[LiveRun] = []

    def live(cap: float) -> LiveRun:
        runs.append(dg.Wire(_answer).run(cap))
        return runs[-1]

    with pytest.raises(RuntimeError):
        iv.run_smoke(iv.SONNET_5, live=live, recorder=recorder, base=_base())
    found = recorder.smokes[iv.SONNET_5]
    assert found.error == "breach: RuntimeError: not an arm error"
    assert found.served is None and found.exchange is None and found.cost_usd == 0.0
    assert runs[0].notes[0].startswith(f"VALIDATE {iv.SONNET_5}: breach")
    monkeypatch.setattr(iv, "send_smoke", real)
    _breach_then_labels(recorder, live, tmp_path)
    assert len(runs) == 1


def test_the_live_suite_passes_on_a_dry_wire(
    dry: Path, plan: iv.ValidatePlan, tmp_path: Path
) -> None:
    """Both smokes, then every label request, through the live entry points."""
    wire = dg.Wire(_answer)
    recorder = _recorder(plan, tmp_path)
    for model in iv.SMOKE_MODELS:
        iv.run_smoke(model, live=wire.run, recorder=recorder, base=_base())
    iv.run_labels(live=wire.run, recorder=recorder, base=_base())
    lines: list[str] = []
    score = recorder.finish(lines.append)
    assert score is not None and not score.passed  # all "different": no same pair
    assert lines[0].startswith("## Ideas validation") and any(
        "Dedupe" in x for x in lines
    )
