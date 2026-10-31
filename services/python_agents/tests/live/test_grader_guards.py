"""Offline guards of L3 (``test_grader_agreement_live.py``): no API call.

The hand labels (``tests/fixtures/grader_labels.json``, ground truth the Lead
owns) load strictly and name real corpus repositories and reference parts;
the run's cap is the sum of its worst-case grader requests, each within the
grader's prompt bound; the agreement rule (at least 9 of every 10 labels, no
near miss graded a hit) is checked on a mock wire; the grader never sees a
label, only each idea's title and rationale.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

import httpx2
import pytest

from autonomous_ai_agents.clients.transport import ScriptedTransport

from . import discovery_grader as grader
from . import test_grader_agreement_live as agreement
from .conftest import TESTS_DIR, LiveRun, restore_host_key
from .discovery import ceil_usd
from .discovery_sweep import SWEEP_N

Json = dict[str, Any]
# What the run asks the ledger for: 6 repositories x GRADE_WORST_USD (0.22725)
# rounded up; the Lead copies it into ci.yml's grader suite (need 2).
AGREEMENT_NEED = 1.40
LABELS = TESTS_DIR / "fixtures" / "grader_labels.json"
LIVE_MODULE = TESTS_DIR / "live" / "test_grader_agreement_live.py"
CI_WORKFLOW = TESTS_DIR.parents[2] / ".github" / "workflows" / "ci.yml"


def _labels_json(**changes: Any) -> Json:
    data: Json = json.loads(LABELS.read_text(encoding="utf-8"))
    data.update(changes)
    return data


def _with_label(index: int, **changes: Any) -> Json:
    data = _labels_json()
    data["labels"][index] = {**data["labels"][index], **changes}
    return data


def _load(data: Json) -> tuple[agreement.LabelGroup, ...]:
    text = json.dumps(data)  # through JSON, as the loader reads the file
    return agreement.label_groups(agreement.GraderLabels.model_validate_json(text))


# ---------------------------------------------------------------------------
# The label file
# ---------------------------------------------------------------------------


def test_the_label_file_loads_strictly_into_one_group_per_repository() -> None:
    groups = agreement.load_groups()
    labels = [label for group in groups for label in group.labels]
    assert agreement.LABELS_PATH == LABELS
    assert 10 <= len(labels) <= 12
    assert len({label.id for label in labels}) == len(labels)
    assert [g.repo.name for g in groups] == list(
        dict.fromkeys(label.repo for label in labels)
    )
    hits = [label for label in labels if label.label == "hit"]
    near = [label for label in labels if label.near_miss]
    assert len(hits) >= 4 and len(near) >= 4
    assert all(label.label == "miss" for label in near)
    assert any(label.part is not None and label.part > 1 for label in hits)
    for group in groups:
        assert group.repo.kind != "control"
        assert 1 <= len(group.labels) <= SWEEP_N
        assert group.patches == grader.reference_patches(group.repo)
        for label in group.labels:
            assert label.part is None or label.part <= len(group.patches)
            assert grader.scrub(label.title + label.rationale) == (
                label.title + label.rationale
            )
        ideas = group.hypotheses()
        assert [(h.title, h.rationale) for h in ideas] == [
            (label.title, label.rationale) for label in group.labels
        ]


@pytest.mark.parametrize(
    ("index", "changes", "message"),
    [
        (0, {"verdict": "hit"}, "Extra inputs"),
        (0, {"label": "maybe"}, "label"),
        (0, {"part": None}, "a hit names its part"),
        (0, {"near_miss": True}, "a hit names its part"),
        (1, {"part": 1}, "a miss targets no part"),
        (0, {"title": "Use the Opus trick"}, "names a model"),
        (0, {"part": "1"}, "part"),
        (0, {"id": "Bad Id"}, "id"),
        (0, {"rationale": ""}, "rationale"),
    ],
)
def test_a_malformed_label_is_refused(index: int, changes: Json, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _load(_with_label(index, **changes))


def test_the_file_level_rules_are_enforced() -> None:
    data = _labels_json()
    first = data["labels"][0]
    with pytest.raises(ValueError, match="repeats an id"):
        _load(_labels_json(labels=[*data["labels"][:11], {**first}]))
    with pytest.raises(ValueError, match="repeats a title"):
        _load(_labels_json(labels=[*data["labels"][:11], {**first, "id": "copy"}]))
    with pytest.raises(ValueError, match="at least 10"):
        _load(_labels_json(labels=data["labels"][:9]))
    with pytest.raises(ValueError, match="source"):
        _load(_labels_json(source=""))


def test_each_label_names_a_graded_corpus_repository_and_a_shown_part() -> None:
    with pytest.raises(ValueError, match="nosuchrepo: not a graded corpus"):
        _load(_with_label(0, repo="nosuchrepo"))
    with pytest.raises(ValueError, match="blockhash: not a graded corpus"):
        _load(_with_label(0, repo="blockhash"))  # a control: no reference fix
    with pytest.raises(ValueError, match="targets part 2 of 1"):
        _load(_with_label(0, part=2))
    data = _labels_json()
    crowd = [
        {**data["labels"][1], "id": f"near-{k}", "title": f"Near miss {k}"}
        for k in range(SWEEP_N)
    ]
    with pytest.raises(ValueError, match=f"more than {SWEEP_N} labels"):
        _load(_labels_json(labels=[*data["labels"][:6], *crowd]))


def test_more_repositories_than_the_cap_allows_are_refused() -> None:
    groups = agreement.load_groups()
    labels = agreement.GraderLabels.model_validate_json(json.dumps(_labels_json()))
    repos = {g.repo.name: g.repo for g in groups}
    with pytest.raises(ValueError, match="more than 5 repositories"):
        agreement.label_groups(labels, repos=repos, max_requests=5)


# ---------------------------------------------------------------------------
# The cap
# ---------------------------------------------------------------------------


def test_the_cap_is_one_worst_case_grader_request_per_repository() -> None:
    groups = agreement.load_groups()
    cap = agreement.agreement_cap(groups)
    assert cap == ceil_usd(len(groups) * grader.GRADE_WORST_USD) == AGREEMENT_NEED
    assert agreement.MAX_REQUESTS == 10  # the spec's cap: 10 x GRADE_WORST_USD
    assert cap <= ceil_usd(agreement.MAX_REQUESTS * grader.GRADE_WORST_USD)
    for group in groups:  # no request can be refused before it is sent
        request = grader.grader_request(group.repo, group.patches, group.hypotheses())
        counted = ScriptedTransport([]).count_input_tokens(request)
        assert counted <= grader.GRADER_PROMPT_BOUND, group.repo.name


def test_the_live_module_is_marked_live_and_reads_the_labels_before_spending() -> None:
    source = LIVE_MODULE.read_text(encoding="utf-8")
    assert "\npytestmark = pytest.mark.live\n" in source
    tests = re.findall(r"^def (test_\w+)\(([^)]*)\)", source, re.MULTILINE)
    assert [name for name, _ in tests] == ["test_grader_agrees_with_the_hand_labels"]
    assert "live: StartLive" in tests[0][1]
    body = source.split("def test_grader_agrees_with_the_hand_labels", 1)[1]
    assert body.index("load_groups()") < body.index("live(agreement_cap(groups))")


def _ci_run_step() -> str:
    """The live job's run step (ci.yml), up to the results upload."""
    text = CI_WORKFLOW.read_text(encoding="utf-8")
    start = text.index("      - name: Run live tests")
    return text[start : text.index("      - name: Upload live corpus", start)]


def test_ci_runs_l3_only_as_its_own_suite_with_room_for_its_cap() -> None:
    """Stage A never collects L3 (its labels would spend the Stage A ledger);
    the grader suite runs it alone, its need covering the run's cap (D24),
    under Step 2's noise rule (L3 starts no engine run)."""
    step = _ci_run_step()
    path = LIVE_MODULE.relative_to(TESTS_DIR.parent).as_posix()
    stage_a = re.search(r"^ *corpus=\((.*)\)$", step, re.MULTILINE)
    assert stage_a is not None
    assert f"--ignore={path}" in stage_a.group(1).split()
    suite = re.search(
        rf"^ *grader\) paths=\({re.escape(path)}\); need=(\d+) ;;$", step, re.M
    )
    assert suite is not None
    need = agreement.agreement_cap(agreement.load_groups())
    assert need <= int(suite.group(1)) < need + 1
    rule = re.search(r"^ *(.*\bgrader\b.*)\) noise_rule=(\w+) ;;$", step, re.M)
    assert rule is not None and rule.group(2) == "step2"


# ---------------------------------------------------------------------------
# The agreement rule, on a mock wire
# ---------------------------------------------------------------------------

Answer = Callable[[agreement.GraderLabel], tuple[bool, int | None]]


def _truthful(label: agreement.GraderLabel) -> tuple[bool, int | None]:
    return label.label == "hit", label.part


class GraderWire:
    """Answers count_tokens with a fixed count and each grader request with
    ``answer(label)`` per shown idea (found by its title); keeps every body."""

    def __init__(self, answer: Answer, *, broken: bool = False) -> None:
        self.answer, self.broken = answer, broken
        self.by_title = {
            label.title: label
            for group in agreement.load_groups()
            for label in group.labels
        }
        self.bodies: list[Json] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        body: Json = json.loads(request.read())
        if request.url.path.endswith("/count_tokens"):
            return httpx2.Response(200, json={"input_tokens": 900}, request=request)
        self.bodies.append(body)
        text = body["messages"][0]["content"][0]["text"]
        grades = []
        for line in text.splitlines():
            if line.startswith('{"id": "H'):
                shown = json.loads(line)
                hit, part = self.answer(self.by_title[shown["title"]])
                grades.append(
                    {
                        "hypothesis_id": shown["id"],
                        "targets_reference_root_cause": hit,
                        "root_cause": part,
                        "justification_summary": "j",
                    }
                )
        reply = "{" if self.broken else json.dumps({"grades": grades})
        message = {
            "id": f"msg_{len(self.bodies)}",
            "type": "message",
            "role": "assistant",
            "model": body["model"],
            "content": [{"type": "text", "text": reply}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 1000, "output_tokens": 200},
        }
        return httpx2.Response(200, json=message, request=request)

    def run(self) -> LiveRun:
        cap = agreement.agreement_cap(agreement.load_groups())
        return LiveRun("dry", cap, wire=httpx2.MockTransport(self))


@pytest.fixture
def dry(monkeypatch: pytest.MonkeyPatch) -> None:
    restore_host_key(monkeypatch, "dry-run-key")


def _grade(wire: GraderWire) -> tuple[agreement.Agreement, LiveRun]:
    run = wire.run()
    return agreement.grade_labels(run, agreement.load_groups()), run


@pytest.mark.usefixtures("dry")
def test_a_truthful_grader_agrees_on_every_label_in_one_request_per_repo() -> None:
    wire = GraderWire(_truthful)
    result, run = _grade(wire)
    groups = agreement.load_groups()
    assert len(wire.bodies) == len(groups)
    assert {b["model"] for b in wire.bodies} == {grader.GRADER_MODEL}
    labels = [label for group in groups for label in group.labels]
    assert [v.label for v in result.verdicts] == labels
    assert result.agreed == len(labels) and result.near_miss_false_positives == ()
    agreement.check_agreement(result)
    assert run.spent_usd <= run.cap_usd
    shown = json.dumps(wire.bodies)
    for label in labels:  # the grader sees the idea, never its label
        assert label.why not in shown and label.id not in shown
    assert "near_miss" not in shown
    notes = result.notes()
    assert len(notes) == len(labels) + 1
    assert notes[-1] == f"L3 agreement {len(labels)}/{len(labels)}, near-miss hits 0"


@pytest.mark.usefixtures("dry")
def test_one_wrong_hit_is_tolerated_but_two_are_not() -> None:
    hits = [
        label
        for group in agreement.load_groups()
        for label in group.labels
        if label.label == "hit"
    ]

    def drop(count: int) -> Answer:
        dropped = {label.id for label in hits[:count]}

        def answer(label: agreement.GraderLabel) -> tuple[bool, int | None]:
            return (False, None) if label.id in dropped else _truthful(label)

        return answer

    one, _ = _grade(GraderWire(drop(1)))
    assert one.agreed == len(one.verdicts) - 1
    agreement.check_agreement(one)  # 11 of 12 is at least 9 of 10
    two, _ = _grade(GraderWire(drop(2)))
    with pytest.raises(AssertionError, match="agreement 10/12"):
        agreement.check_agreement(two)


@pytest.mark.usefixtures("dry")
def test_a_near_miss_graded_a_hit_fails_even_when_agreement_holds() -> None:
    near = next(
        label
        for group in agreement.load_groups()
        for label in group.labels
        if label.near_miss
    )

    def answer(label: agreement.GraderLabel) -> tuple[bool, int | None]:
        return (True, 1) if label.id == near.id else _truthful(label)

    result, _ = _grade(GraderWire(answer))
    assert result.agreed == len(result.verdicts) - 1
    assert [v.label.id for v in result.near_miss_false_positives] == [near.id]
    with pytest.raises(AssertionError, match=f"near miss graded a hit: {near.id}"):
        agreement.check_agreement(result)


@pytest.mark.usefixtures("dry")
def test_a_hit_on_the_wrong_part_of_a_multi_repo_disagrees() -> None:
    def answer(label: agreement.GraderLabel) -> tuple[bool, int | None]:
        if label.label == "hit" and label.part is not None and label.part > 1:
            return True, 1
        return _truthful(label)

    result, _ = _grade(GraderWire(answer))
    wrong = [v for v in result.verdicts if not v.agrees]
    assert wrong and all(v.label.part != 1 and v.part == 1 for v in wrong)
    single = next(v for v in result.verdicts if v.parts == 1 and v.label.part == 1)
    assert agreement.Verdict(single.label, True, None, 1).agrees  # one part only
    assert not agreement.Verdict(single.label, None, None, 1).agrees  # ungraded


@pytest.mark.usefixtures("dry")
def test_a_failed_grader_request_fails_the_check() -> None:
    result, run = _grade(GraderWire(_truthful, broken=True))
    assert all(v.hit is None for v in result.verdicts) and result.agreed == 0
    with pytest.raises(AssertionError, match="grader failed on tagfilter"):
        agreement.check_agreement(result)
    assert run.spent_usd <= run.cap_usd


def test_a_grade_billed_to_another_model_fails_the_check() -> None:
    groups = agreement.load_groups()
    group = groups[0]
    graded = grader.Grade(
        hits=tuple(label.label == "hit" for label in group.labels),
        cost_usd=0.01,
        answered=True,
        error=None,
        models=("claude-sonnet-5-5",),
        causes=tuple(label.part for label in group.labels),
        parts=len(group.patches),
    )
    result = agreement.Agreement(
        verdicts=agreement.verdicts_of(group, graded), grades=((group, graded),)
    )
    with pytest.raises(AssertionError, match="tagfilter billed"):
        agreement.check_agreement(result)


def test_the_grader_and_the_rule_are_the_spec_s() -> None:
    assert agreement.GRADER_MODEL == grader.GRADER_MODEL == "claude-opus-4-8"
    assert agreement.MIN_AGREEMENT == (9, 10)
