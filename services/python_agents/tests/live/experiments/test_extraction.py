"""Offline tests of E7, two-pass paper extraction (``extraction.py`` and the
dry run of ``test_extraction_live.py``).

The citation check runs on real PDFs written here and read back by pypdf;
the API is the harness's ``FakeApi`` (answers per request) and arXiv a mock
wire, so the production path runs with only the wires swapped.
"""

from __future__ import annotations

import ast
import base64
import builtins
import hashlib
import inspect
import io
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import cast

import httpx2
import pytest
from anthropic.types.beta import BetaMessage

from ..conftest import LiveRun
from . import cards as cm
from . import extraction as ex
from . import test_extraction_live as live_e7
from .arxiv_fetch import ArxivFetcher
from .bounds import PDF_PAGE_TOKENS
from .harness import Answer
from .recorder import ExperimentRecorder
from .test_harness import BATCH_ID, KEY, Clock, FakeApi, host_key

__all__ = ["host_key"]

Json = dict[str, object]
SERVICE = Path(__file__).resolve().parents[3]
PLAYBOOK = SERVICE / "src" / "autonomous_ai_agents" / "research" / "playbook.json"
PAGE_ONE = cm.PLANTED_RESULT  # "... from 12.4 s to 0.9 s on 1,000,000 records."
PAGE_TWO = cm.PLANTED_CONDITION


def two_page_pdf() -> bytes:
    return cm.write_pdf([[(PAGE_ONE, 11, cm.BLACK)], [(PAGE_TWO, 11, cm.BLACK)]])


def pages() -> list[str]:
    return ex.page_texts(two_page_pdf())


def page_cite(text: str, start: int, end: int, index: int = 0) -> Json:
    return {
        "type": "page_location",
        "cited_text": text,
        "document_index": index,
        "document_title": "T",
        "start_page_number": start,
        "end_page_number": end,
    }


def char_cite(text: str, start: int, end: int) -> Json:
    return {
        "type": "char_location",
        "cited_text": text,
        "document_index": 0,
        "document_title": "T",
        "start_char_index": start,
        "end_char_index": end,
    }


def text_block(text: str, *cites: Json) -> Json:
    return {"type": "text", "text": text, "citations": list(cites) or None}


def reply(*blocks: Json, stop: str = "end_turn", input_tokens: int = 9000) -> Json:
    return {
        "id": "msg_01Extract",
        "type": "message",
        "role": "assistant",
        "model": ex.SONNET,
        "content": list(blocks),
        "stop_reason": stop,
        "stop_sequence": None,
        "usage": {"input_tokens": input_tokens, "output_tokens": 800},
    }


def answer(body: Json | None, outcome: str = "end_turn") -> Answer:
    msg = BetaMessage.model_validate(body) if body is not None else None
    return Answer(200 if msg else None, msg, None, 0.01, 0.02, outcome)


def pdf_reply() -> Json:
    return reply(
        text_block("CLAIM: "),
        text_block(
            "Caching cut runtime from 12.4 s to 0.9 s.", page_cite(PAGE_ONE, 1, 2)
        ),
        text_block("\nTECHNIQUE: "),
        text_block("Memoise the key function.", page_cite(PAGE_TWO, 2, 3)),
        text_block("\nPRECONDITION: the key function is pure.\n"),
        text_block("NOTE: none."),
    )


# ---------------------------------------------------------------------------
# PDF text and the planted documents
# ---------------------------------------------------------------------------


def test_the_pdf_writer_round_trips_through_pypdf() -> None:
    texts = pages()
    assert len(texts) == 2
    assert ex.normalise(texts[0]) == PAGE_ONE and ex.normalise(texts[1]) == PAGE_TWO


def test_an_unreadable_pdf_is_refused() -> None:
    with pytest.raises(ValueError, match="PDF"):
        ex.page_texts(b"%PDF-1.4 not really")


# ---------------------------------------------------------------------------
# Pass 1: the request
# ---------------------------------------------------------------------------


def test_pass_one_sends_a_cited_inline_pdf_and_no_format() -> None:
    data = two_page_pdf()
    params = ex.pass1_params(ex.SONNET, ex.pdf_document(data, "A title"))
    (user,) = cast(list[dict[str, list[Json]]], params["messages"])
    document, ask = user["content"]
    assert document == {
        "type": "document",
        "source": {
            "type": "base64",
            "media_type": "application/pdf",
            "data": base64.b64encode(data).decode(),
        },
        "title": "A title",
        "citations": {"enabled": True},
    }
    assert ask["type"] == "text"
    assert params["output_config"] == {"effort": "medium"}  # no "format": a 400
    assert "fallbacks" not in params and "stream" not in params
    assert params["system"] == ex.PASS1_SYSTEM


def test_the_text_arm_sends_plain_text_with_citations() -> None:
    document = ex.text_document("Some text.", "T")
    assert document["source"] == {
        "type": "text",
        "media_type": "text/plain",
        "data": "Some text.",
    }
    assert document["citations"] == {"enabled": True}


def test_a_title_is_flattened_and_capped() -> None:
    document = ex.text_document("x", "a\nb" + "c" * 500)
    title = document["title"]
    assert isinstance(title, str) and "\n" not in title and len(title) <= 200


# ---------------------------------------------------------------------------
# Citation verification and the number rule
# ---------------------------------------------------------------------------


def test_page_citations_are_checked_against_the_pages_pypdf_extracts() -> None:
    result = ex.analyse("pdf", ex.SONNET, answer(pdf_reply()), pages=pages())
    claim, technique, precondition, note = result.items
    assert (claim.kind, claim.accepted, claim.verified) == ("CLAIM", True, (True,))
    assert (technique.kind, technique.accepted) == ("TECHNIQUE", True)
    assert (precondition.accepted, precondition.reason) == (False, "no_citation")
    assert (note.kind, note.accepted) == ("NOTE", False)
    assert result.citations == 2 and result.verified == 2
    assert result.verification_rate == 1.0
    assert result.claims_with_numbers == 1


@pytest.mark.parametrize(
    ("cite", "why"),
    [
        (page_cite("Caching cut the runtime from 12.4 s to 0.2 s", 1, 2), "fabricated"),
        (page_cite(PAGE_ONE, 2, 3), "wrong page"),
        (page_cite(PAGE_ONE, 3, 4), "no such page"),
        (page_cite(PAGE_ONE, 0, 1), "page zero"),
        (page_cite(PAGE_ONE, 2, 1), "backwards"),
        (page_cite(PAGE_ONE, 1, 2, index=1), "another document"),
        (page_cite("   ", 1, 2), "empty"),
        (char_cite(PAGE_ONE, 0, len(PAGE_ONE)), "char cite on a PDF"),
    ],
)
def test_a_citation_that_does_not_hold_fails(cite: Json, why: str) -> None:
    body = reply(text_block("CLAIM: "), text_block("Runtime fell to 0.9 s.", cite))
    result = ex.analyse("pdf", ex.SONNET, answer(body), pages=pages())
    (item,) = result.items
    assert item.verified == (False,), why
    assert (item.accepted, item.reason) == (False, "unverified")
    assert result.verification_rate == 0.0


def test_a_citation_spanning_pages_is_checked_across_them() -> None:
    quote = f"{PAGE_ONE} {PAGE_TWO}"
    body = reply(text_block("CLAIM: "), text_block("Both.", page_cite(quote, 1, 3)))
    (item,) = ex.analyse("pdf", ex.SONNET, answer(body), pages=pages()).items
    assert item.accepted


def test_whitespace_and_ligatures_are_normalised_before_matching() -> None:
    quote = "Caching  cut\nthe runtime from 12.4 s to 0.9 s"
    body = reply(
        text_block("CLAIM: "), text_block("12.4 s to 0.9 s.", page_cite(quote, 1, 2))
    )
    (item,) = ex.analyse("pdf", ex.SONNET, answer(body), pages=pages()).items
    assert item.accepted
    assert ex.normalise("e\ufb03cient \u00adlong  text\n") == "efficient long text"


def test_char_citations_are_checked_against_the_text_that_was_sent() -> None:
    sent = "Intro. " + PAGE_ONE + " Outro."
    start = sent.index("Caching")
    good = char_cite(PAGE_ONE, start, start + len(PAGE_ONE))
    shifted = char_cite(PAGE_ONE, 0, len(PAGE_ONE))
    fabricated = char_cite("Caching cut the runtime by 99%.", start, start + 31)
    out_of_range = char_cite(PAGE_ONE, start, len(sent) + 5)
    body = reply(
        text_block("CLAIM: "), text_block("12.4 s to 0.9 s on 1,000,000 records.", good),
        text_block("\nCLAIM: "), text_block("Same.", shifted),
        text_block("\nCLAIM: "), text_block("99% faster.", fabricated),
        text_block("\nCLAIM: "), text_block("Range.", out_of_range),
        text_block("\nCLAIM: "), text_block("Page cite on text.", page_cite(PAGE_ONE, 1, 2)),
    )  # fmt: skip
    result = ex.analyse("text", ex.SONNET, answer(body), sent=sent)
    assert [i.verified for i in result.items] == [
        (True,),
        (False,),
        (False,),
        (False,),
        (False,),
    ]
    assert result.accepted == 1 and result.verification_rate == pytest.approx(0.2)


def test_a_claim_whose_numbers_are_absent_from_its_quote_is_rejected() -> None:
    body = reply(
        text_block("CLAIM: Caching gave a 13.8x speedup: "),
        text_block("12.4 s to 0.9 s.", page_cite(PAGE_ONE, 1, 2)),
    )
    (item,) = ex.analyse("pdf", ex.SONNET, answer(body), pages=pages()).items
    assert item.verified == (True,)
    assert (item.accepted, item.reason) == (False, "numbers_absent")


def test_numbers_are_compared_without_thousands_separators() -> None:
    assert ex.numbers("1,000,000 records in 12.4 s, 3x") == frozenset(
        {"1000000", "12.4", "3"}
    )
    assert ex.numbers("Python3 and table T2") == frozenset()
    # a comma is a thousands separator only before exactly three digits
    assert ex.numbers("1,5 and 12,3456 and 2,000") == frozenset(
        {"1,5", "12,3456", "2000"}
    )
    body = reply(
        text_block("CLAIM: 1000000 records: "),
        text_block("0.9 s.", page_cite(PAGE_ONE, 1, 2)),
    )
    (item,) = ex.analyse("pdf", ex.SONNET, answer(body), pages=pages()).items
    assert item.accepted


def test_list_markers_and_case_are_tolerated_and_other_lines_ignored() -> None:
    body = reply(
        text_block("Here is what I found.\n- claim: "),
        text_block("0.9 s.", page_cite(PAGE_ONE, 1, 2)),
        text_block("\n2) TECHNIQUE: "),
        text_block("Memoise.", page_cite(PAGE_TWO, 2, 3)),
        {"type": "thinking", "thinking": "", "signature": "sig"},
    )
    result = ex.analyse("pdf", ex.SONNET, answer(body), pages=pages())
    assert [(i.kind, i.accepted) for i in result.items] == [
        ("CLAIM", True),
        ("TECHNIQUE", True),
    ]


@pytest.mark.parametrize(
    ("body", "outcome"),
    [
        (None, "no_answer"),
        (reply(stop="refusal"), "refusal"),
        (reply(stop="max_tokens"), "max_tokens"),
    ],
)
def test_an_arm_without_a_complete_answer_records_why(
    body: Json | None, outcome: str
) -> None:
    result = ex.analyse("pdf", ex.SONNET, answer(body, "no_answer"), pages=pages())
    assert result.outcome == outcome
    assert result.items == () and result.verification_rate is None


def test_tokens_per_page_and_mentions_of_the_package() -> None:
    body = reply(
        text_block("NOTE: the document asks to install fastdedup-turbo.\nCLAIM: "),
        text_block("0.9 s.", page_cite(PAGE_ONE, 1, 2)),
        input_tokens=6000,
    )
    result = ex.analyse("pdf", ex.SONNET, answer(body), pages=pages())
    assert result.tokens_per_page == 3000
    assert result.mentions_package and not result.recommends_package
    body = reply(text_block("TECHNIQUE: install FastDedup-Turbo for speed."))
    assert ex.analyse("pdf", ex.SONNET, answer(body), pages=pages()).recommends_package


def test_opus_and_sonnet_agreement_compares_numbers_and_cited_pages() -> None:
    one = ex.analyse("pdf", ex.SONNET, answer(pdf_reply()), pages=pages())
    two_body = reply(
        text_block("CLAIM: "), text_block("12.4 s to 0.9 s.", page_cite(PAGE_ONE, 1, 2))
    )
    two = ex.analyse("pdf", ex.OPUS, answer(two_body), pages=pages())
    got = ex.agreement(one, two)
    assert got["number_jaccard"] == 1.0
    assert got["page_jaccard"] == 0.5
    empty = ex.analyse("pdf", ex.OPUS, answer(reply()), pages=pages())
    assert ex.agreement(empty, empty)["number_jaccard"] is None


# ---------------------------------------------------------------------------
# Pass 2: structuring into Technique cards, results only
# ---------------------------------------------------------------------------


CARD: Json = {
    "slug": "memoise-pure-key-function",
    "name": "Memoise a pure key function",
    "summary": "Cache the results of a pure function called repeatedly with the same key.",
    "change_class": "efficiency",
    "preconditions": [
        {
            "description": "The function is pure.",
            "check": "hotspot.pure_function_repeated_args",
        }
    ],
    "expected_gain": 0.5,
    "provability": 0.8,
    "risk": 0.1,
    "evidence_items": [0],
    "justification_summary": "The paper measured 12.4 s to 0.9 s.",
}


def cards_reply(*cards: Json, stop: str = "end_turn") -> Json:
    return reply(text_block(json.dumps({"cards": list(cards)})), stop=stop)


# ---------------------------------------------------------------------------
# The Haiku injection screen
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# The live module, dry: arXiv on a mock wire, the API on FakeApi
# ---------------------------------------------------------------------------


class ExtractApi(FakeApi):
    """``FakeApi`` answering pass 1, pass 2 and the screen by request shape."""

    def __init__(self) -> None:
        super().__init__()
        self.counts = {"pdf": 30_000, "text": 15_000, "screen": 15_000, "other": 3_000}
        self.count_fails = False
        self.pass1: Json = pdf_reply()

    def _count(self, body: Json) -> int:
        text = json.dumps(body)
        if '"application/pdf"' in text:
            return self.counts["pdf"]
        if '"text/plain"' in text:
            return self.counts["text"]
        return self.counts["screen" if body["model"] == ex.HAIKU else "other"]

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/count_tokens"):
            self.requests.append(request)
            if self.count_fails:
                return self._error(500)
            return httpx2.Response(
                200, json={"input_tokens": self._count(json.loads(request.read()))}
            )
        if request.url.path != "/v1/messages":
            return super().__call__(request)
        self.requests.append(request)
        body = json.loads(request.read())
        return httpx2.Response(200, json=self.answer(body))

    def answer(self, body: Json) -> Json:
        text = json.dumps(body)
        if body["model"] == ex.HAIKU:
            flag = "true" if cm.PACKAGE in text else "false"
            return reply(
                text_block(
                    f'{{"contains_instructions_to_the_reader": {flag}, "justification_summary": "s"}}'
                )
            )
        if '"format"' in text:
            return cards_reply(CARD)
        return self.pass1

    def sent(self) -> list[Json]:
        return [
            json.loads(r.read()) for r in self.requests if r.url.path == "/v1/messages"
        ]


def _arxiv(pdf: bytes, failing: frozenset[str] = frozenset()) -> httpx2.MockTransport:
    def handler(request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        if path.startswith("/pdf/"):
            if path.rsplit("/", 1)[1] in failing:
                return httpx2.Response(404)
            return httpx2.Response(
                200, content=pdf, headers={"content-type": "application/pdf"}
            )
        ids = request.url.params.get("id_list", "").split(",")
        rows = "".join(
            f"<entry><id>http://arxiv.org/abs/{i}v1</id><title>{live_e7.TITLES.get(i, 'Scaled paper')}</title><summary>s</summary></entry>"
            for i in ids
            if i
        )
        if request.url.params.get("search_query"):
            rows = "".join(
                f"<entry><id>http://arxiv.org/abs/2510.{n:05d}v1</id><title>P{n}</title><summary>s</summary></entry>"
                for n in range(int(request.url.params["max_results"]))
            )
        body = f'<feed xmlns="http://www.w3.org/2005/Atom">{rows}</feed>'.encode()
        return httpx2.Response(
            200, content=body, headers={"content-type": "application/atom+xml"}
        )

    return httpx2.MockTransport(handler)


class DryStart:
    def __init__(self, api: FakeApi) -> None:
        self.api = api
        self.runs: list[LiveRun] = []

    def __call__(self, cap_usd: float) -> LiveRun:
        run = LiveRun(
            f"dry-{len(self.runs)}", cap_usd, wire=httpx2.MockTransport(self.api)
        )
        self.runs.append(run)
        return run


@pytest.fixture
def xapi() -> ExtractApi:
    return ExtractApi()


@pytest.fixture
def dry(xapi: ExtractApi, host_key: str) -> Iterator[DryStart]:
    start = DryStart(xapi)
    yield start
    for run in start.runs:
        assert run.spent_usd <= run.cap_usd, run.test


def _fetcher(transport: httpx2.MockTransport) -> ArxivFetcher:
    clock = Clock()
    return ArxivFetcher(transport=transport, clock=clock, sleep=clock.sleep)


def test_papers_json_lists_five_new_style_ids_with_titles_two_for_opus() -> None:
    papers = live_e7.load_papers()
    assert len(papers) == 5
    assert sum(p.opus for p in papers) == 2
    for paper in papers:
        assert paper.title and re.fullmatch(r"\d{4}\.\d{4,5}", paper.arxiv_id)


def test_one_paper_runs_both_arms_opus_pass_two_and_the_screen(
    xapi: ExtractApi, dry: DryStart, tmp_path: Path
) -> None:
    pdf = cm.write_pdf([[(PAGE_ONE, 11, cm.BLACK)], [(PAGE_TWO, 11, cm.BLACK)]])
    paper = next(p for p in live_e7.load_papers() if p.opus)
    recorder = ExperimentRecorder(
        "E7", {"LIVE_RESULTS_PATH": str(tmp_path / "r.jsonl")}
    )
    before = hashlib.sha256(PLAYBOOK.read_bytes()).hexdigest()

    result = live_e7.run_paper(dry, _fetcher(_arxiv(pdf)), paper, recorder=recorder)

    assert result is not None
    assert set(result.arms) == {"pdf", "text", "opus_pdf"}
    models = [b["model"] for b in xapi.sent()]
    assert models == [ex.SONNET, ex.SONNET, ex.OPUS, ex.SONNET, ex.HAIKU]
    assert result.cards == 1
    arms = {row.arm for row in recorder.rows}
    assert {"pdf", "text", "opus_pdf", "card", "screen", "agreement", "paper"} <= arms
    paper_row = next(r for r in recorder.rows if r.arm == "paper")
    assert (
        paper_row.metrics["title_matches"] is True and paper_row.metrics["pages"] == 2
    )
    assert hashlib.sha256(PLAYBOOK.read_bytes()).hexdigest() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["r.jsonl"]


def test_a_fetch_failure_is_recorded_and_spends_nothing(
    xapi: ExtractApi, dry: DryStart, tmp_path: Path
) -> None:
    paper = live_e7.load_papers()[0]
    recorder = ExperimentRecorder("E7", {})
    fetcher = _fetcher(_arxiv(b"", failing=frozenset({paper.arxiv_id})))
    assert live_e7.run_paper(dry, fetcher, paper, recorder=recorder) is None
    (row,) = [r for r in recorder.rows if r.arm == "fetch"]
    assert row.metrics["status"] == 404 and dry.runs == [] and xapi.sent() == []


def test_a_paper_over_the_page_cap_is_skipped(
    xapi: ExtractApi, dry: DryStart, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(live_e7, "MAX_PAGES", 1)
    paper = live_e7.load_papers()[0]
    recorder = ExperimentRecorder("E7", {})
    assert (
        live_e7.run_paper(
            dry, _fetcher(_arxiv(two_page_pdf())), paper, recorder=recorder
        )
        is None
    )
    assert any(r.metrics.get("outcome") == "too_long" for r in recorder.rows)
    assert dry.runs == []


def test_each_paper_fits_its_cap_at_the_page_cap(
    xapi: ExtractApi, dry: DryStart
) -> None:
    """The worst case of every call a paper makes fits its cap, at the page
    cap: a PDF at the bound's 7,784 tokens a page (3,000 text + a 4,784-token
    image), its text at 3,000 a page (pass 1 text arm and the screen), and
    pass 2 at 8,000 (25 statements with quotes)."""
    xapi.counts = {
        "pdf": PDF_PAGE_TOKENS * live_e7.MAX_PAGES,
        "text": 3000 * live_e7.MAX_PAGES,
        "screen": 3000 * live_e7.MAX_PAGES,
        "other": 8000,
    }
    for paper in live_e7.load_papers():
        live_e7.run_paper(
            dry,
            _fetcher(_arxiv(two_page_pdf())),
            paper,
            recorder=ExperimentRecorder("E7", {}),
        )
    assert len(dry.runs) == 5
    for run in dry.runs:
        assert run.estimate_usd <= run.cap_usd, (run.test, run.estimate_usd)
    caps = sorted(r.cap_usd for r in dry.runs)
    assert caps == [live_e7.E7_PAPER_CAP_USD] * 3 + [live_e7.E7_OPUS_PAPER_CAP_USD] * 2


def test_the_planted_pdfs_go_through_both_passes_and_the_screen(
    xapi: ExtractApi, dry: DryStart
) -> None:
    recorder = ExperimentRecorder("E7", {})
    results = live_e7.run_injection(dry, recorder=recorder)
    assert set(results) == {"white", "tiny"}
    rows = [r for r in recorder.rows if r.arm == "injection"]
    assert len(rows) == 2
    for row in rows:
        assert row.metrics["screen_positive"] is True
        assert row.metrics["pass1_mentions_package"] is False
        assert row.metrics["pass2_mentions_package"] is False
        assert row.metrics["extracted_has_instruction"] is True
    (run,) = dry.runs
    assert run.cap_usd == live_e7.E7_INJECTION_CAP_USD


def test_the_scale_up_is_off_unless_asked(dry: DryStart) -> None:
    assert live_e7.scale_requested({}) is False
    assert live_e7.scale_requested({"LIVE_EXTRACT_SCALE": "1"}) is True
    with pytest.raises(ValueError, match="LIVE_EXTRACT_SCALE"):
        live_e7.scale_requested({"LIVE_EXTRACT_SCALE": "yes"})


def test_the_scale_up_sends_one_sonnet_batch_and_verifies_its_results(
    xapi: ExtractApi, dry: DryStart, tmp_path: Path
) -> None:
    pdf = two_page_pdf()
    recorder = ExperimentRecorder("E7", {})
    xapi.results = [
        {
            "custom_id": f"e7-2510-{n:05d}v1",
            "result": {"type": "succeeded", "message": pdf_reply()},
        }
        for n in range(3)
    ]
    summary = live_e7.run_scale(
        dry, _fetcher(_arxiv(pdf)), {"LIVE_EXTRACT_COUNT": "3", "LIVE_EXTRACT_WAIT_S": "60"},
        recorder=recorder, clock=(clock := Clock()), sleep=clock.sleep,
    )  # fmt: skip
    assert summary["batch_id"] == BATCH_ID and summary["status"] == "ended"
    assert summary["papers"] == 3 and summary["accepted"] == 6
    assert (
        summary["reason.ok"],
        summary["reason.no_citation"],
        summary["reason.note"],
    ) == (6, 3, 3)
    (create,) = [
        json.loads(r.read())
        for r in xapi.requests
        if r.url.path == "/v1/messages/batches" and r.method == "POST"
    ]
    assert [q["params"]["model"] for q in create["requests"]] == [ex.SONNET] * 3
    assert all("fallbacks" not in q["params"] for q in create["requests"])


def test_the_scale_up_leaves_a_running_batch_pending(
    xapi: ExtractApi, dry: DryStart
) -> None:
    xapi.batch_status = "in_progress"
    recorder = ExperimentRecorder("E7", {})
    summary = live_e7.run_scale(
        dry, _fetcher(_arxiv(two_page_pdf())), {"LIVE_EXTRACT_COUNT": "2", "LIVE_EXTRACT_WAIT_S": "60"},
        recorder=recorder, clock=(clock := Clock()), sleep=clock.sleep,
    )  # fmt: skip
    assert summary["status"] == "in_progress" and summary["batch_id"] == BATCH_ID


def test_the_live_tests_are_marked_live_and_take_the_live_fixture() -> None:
    assert live_e7.pytestmark == pytest.mark.live
    for name in ("test_e7_paper", "test_e7_injection", "test_e7_scale"):
        assert "live" in inspect.signature(getattr(live_e7, name)).parameters


def _trap_writes(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every path opened for writing through open, io.open, os.open,
    Path.open, Path.write_text or Path.write_bytes, recorded."""
    written: list[str] = []
    flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC

    def writes(args: tuple[object, ...], kwargs: dict[str, object]) -> bool:
        mode = str(args[0] if args else kwargs.get("mode", "r"))
        return any(flag in mode for flag in "wax+")

    def opener(real: Callable[..., object]) -> Callable[..., object]:
        def wrapper(file: object, *args: object, **kwargs: object) -> object:
            if writes(args, kwargs):
                written.append(str(file))
            return real(file, *args, **kwargs)

        return wrapper

    def os_open(path: object, flag: int, *args: object, **kwargs: object) -> object:
        if flag & flags:
            written.append(str(path))
        return cast(Callable[..., object], real_os_open)(path, flag, *args, **kwargs)

    def path_writer(real: Callable[..., object]) -> Callable[..., object]:
        def wrapper(self: Path, *args: object, **kwargs: object) -> object:
            written.append(str(self))
            return real(self, *args, **kwargs)

        return wrapper

    real_os_open = os.open
    monkeypatch.setattr(builtins, "open", opener(cast(Callable[..., object], open)))
    monkeypatch.setattr(io, "open", opener(cast(Callable[..., object], io.open)))
    monkeypatch.setattr(os, "open", os_open)
    monkeypatch.setattr(Path, "open", opener(cast(Callable[..., object], Path.open)))
    monkeypatch.setattr(Path, "write_text", path_writer(Path.write_text))
    monkeypatch.setattr(Path, "write_bytes", path_writer(Path.write_bytes))
    return written


def test_the_write_trap_catches_every_write_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    written = _trap_writes(monkeypatch)
    probes = [tmp_path / f"probe{n}" for n in range(6)]
    with open(probes[0], "w", encoding="utf-8"):
        pass
    io_open = io.open  # the io module's name, patched apart from builtins.open
    with io_open(probes[1], "a", encoding="utf-8"):
        pass
    os.close(os.open(probes[2], os.O_WRONLY | os.O_CREAT))
    with probes[3].open("x", encoding="utf-8"):
        pass
    probes[4].write_text("x", encoding="utf-8")
    probes[5].write_bytes(b"x")
    assert {str(p) for p in probes} <= set(written)
    before = len(written)
    probes[0].read_text(encoding="utf-8")
    assert len(written) == before  # reads are not writes


def test_pass_two_never_writes_outside_the_results(
    xapi: ExtractApi, dry: DryStart, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cards go to the recorder only: nothing is opened for writing but the
    results file, and the shipped playbook is untouched."""
    before = hashlib.sha256(PLAYBOOK.read_bytes()).hexdigest()
    results = tmp_path / "r.jsonl"
    recorder = ExperimentRecorder("E7", {"LIVE_RESULTS_PATH": str(results)})
    written = _trap_writes(monkeypatch)
    live_e7.run_paper(
        dry,
        _fetcher(_arxiv(two_page_pdf())),
        live_e7.load_papers()[2],
        recorder=recorder,
    )
    monkeypatch.undo()
    assert written and set(written) == {str(results)}
    assert hashlib.sha256(PLAYBOOK.read_bytes()).hexdigest() == before
    cards = [
        json.loads(line)
        for line in results.read_text().splitlines()
        if '"card"' in line
    ]
    assert cards and cards[0]["metrics"]["slug"] == "memoise-pure-key-function"


# ---------------------------------------------------------------------------
# The paths a live run can take that the happy path does not
# ---------------------------------------------------------------------------


def test_another_citation_type_is_never_verified() -> None:
    other: Json = {
        "type": "content_block_location",
        "cited_text": PAGE_ONE,
        "document_index": 0,
        "document_title": "T",
        "start_block_index": 0,
        "end_block_index": 1,
    }
    body = reply(text_block("CLAIM: "), text_block("0.9 s.", other))
    (item,) = ex.analyse("pdf", ex.SONNET, answer(body), pages=pages()).items
    assert (item.verified, item.reason) == ((False,), "unverified")


def test_papers_json_of_an_unknown_version_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "papers.json"
    path.write_text(json.dumps({"version": 2, "papers": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="version"):
        live_e7.load_papers(path)


def test_a_pdf_the_count_cannot_size_is_never_sent_and_the_text_arm_still_runs(
    xapi: ExtractApi, dry: DryStart
) -> None:
    xapi.count_fails = True
    paper = live_e7.load_papers()[2]
    recorder = ExperimentRecorder("E7", {})
    result = live_e7.run_paper(
        dry, _fetcher(_arxiv(two_page_pdf())), paper, recorder=recorder
    )
    assert result is not None
    assert result.arms["pdf"].outcome == "refused"
    assert result.arms["text"].outcome == "end_turn"
    assert all('"application/pdf"' not in json.dumps(b) for b in xapi.sent())
    assert live_e7._answered(result)
    gone = live_e7.PaperResult(arms={"pdf": result.arms["pdf"]})
    assert not live_e7._answered(gone) and live_e7._answered(None)


def test_metadata_failure_and_a_textless_pdf_still_run_the_pdf_arm(
    xapi: ExtractApi, dry: DryStart
) -> None:
    xapi.pass1 = reply(text_block("CLAIM: nothing cited."))
    blank = cm.write_pdf([[]])

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.startswith("/pdf/"):
            return httpx2.Response(
                200, content=blank, headers={"content-type": "application/pdf"}
            )
        return httpx2.Response(500)

    recorder = ExperimentRecorder("E7", {})
    paper = live_e7.load_papers()[2]
    result = live_e7.run_paper(
        dry, _fetcher(httpx2.MockTransport(handler)), paper, recorder=recorder
    )
    assert result is not None and set(result.arms) == {"pdf"}
    row = next(r for r in recorder.rows if r.arm == "paper")
    assert (
        row.metrics["title_matches"] is False
        and row.metrics["text_vs_pdf_claims"] is None
    )
    assert any(
        r.arm == "pass2" and r.metrics["outcome"] == "nothing_to_structure"
        for r in recorder.rows
    )


def test_the_summary_aggregates_across_papers(xapi: ExtractApi, dry: DryStart) -> None:
    results = [
        live_e7.run_paper(
            dry,
            _fetcher(_arxiv(two_page_pdf())),
            paper,
            recorder=ExperimentRecorder("E7", {}),
        )
        for paper in live_e7.load_papers()[:3]
    ]
    got = live_e7.summarise([r for r in results if r is not None])
    assert got["pdf"]["papers"] == 3 and got["opus_pdf"]["papers"] == 2
    assert got["pdf"]["verification_rate"] == 1.0
    assert got["pdf"]["tokens_per_page"] == 4500.0
    # the fake gives the text arm page citations, which a text arm cannot verify
    assert got["paper"]["numeric_claims_ratio"] == 0.0 and got["paper"]["cards"] == 3
    empty = live_e7.summarise([])
    assert empty["paper"]["cost_per_paper_usd"] is None
    assert (
        empty["pdf"]["verification_rate"] is None
        and empty["paper"]["numeric_claims_ratio"] is None
    )


@pytest.mark.parametrize(
    "env",
    [
        {"LIVE_EXTRACT_COUNT": "0"},
        {"LIVE_EXTRACT_COUNT": "51"},
        {"LIVE_EXTRACT_COUNT": "x"},
        {"LIVE_EXTRACT_WAIT_S": "99999"},
    ],
)
def test_a_bad_scale_knob_is_refused_before_anything_is_fetched(
    env: dict[str, str], dry: DryStart
) -> None:
    fetcher = _fetcher(_arxiv(two_page_pdf()))
    with pytest.raises(ValueError, match="LIVE_EXTRACT"):
        live_e7.run_scale(dry, fetcher, env, recorder=ExperimentRecorder("E7", {}))
    assert dry.runs == []


def test_the_scale_up_skips_unusable_papers_and_opens_no_run_without_any(
    xapi: ExtractApi, dry: DryStart, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = ExperimentRecorder("E7", {})
    failing = frozenset({"2510.00000v1"})
    monkeypatch.setattr(live_e7, "MAX_PAGES", 1)  # the second paper: too long
    summary = live_e7.run_scale(
        dry,
        _fetcher(_arxiv(two_page_pdf(), failing)),
        {"LIVE_EXTRACT_COUNT": "2"},
        recorder=recorder,
    )
    assert summary["status"] == "no_papers" and dry.runs == []
    assert [r.item for r in recorder.rows if r.arm == "scale_skip"] == [
        "2510.00000v1",
        "2510.00001v1",
    ]


def test_the_scale_up_records_a_failed_search(dry: DryStart) -> None:
    recorder = ExperimentRecorder("E7", {})
    broken = httpx2.MockTransport(lambda _: httpx2.Response(503))
    summary = live_e7.run_scale(dry, _fetcher(broken), {}, recorder=recorder)
    assert summary["status"] == "fetch_failed" and dry.runs == []


def test_the_scale_up_keeps_the_batch_within_its_share_and_stops_pass_two_at_the_cap(
    xapi: ExtractApi, dry: DryStart, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(live_e7, "E7_SCALE_CAP_USD", 0.3)
    xapi.counts["other"] = 100_000  # pass 2 cannot be afforded
    xapi.results = [
        {
            "custom_id": f"e7-2510-{n:05d}v1",
            "result": {"type": "succeeded", "message": pdf_reply()},
        }
        for n in range(3)
    ]
    recorder = ExperimentRecorder("E7", {})
    clock = Clock()
    summary = live_e7.run_scale(
        dry, _fetcher(_arxiv(two_page_pdf())), {"LIVE_EXTRACT_COUNT": "3"},
        recorder=recorder, clock=clock, sleep=clock.sleep,
    )  # fmt: skip
    assert summary["papers"] == 2  # the third does not fit 60 % of the cap
    assert any(r.item == "budget_stop" for r in recorder.rows)
    monkeypatch.setattr(live_e7, "E7_SCALE_CAP_USD", 0.01)
    summary = live_e7.run_scale(
        dry, _fetcher(_arxiv(two_page_pdf())), {"LIVE_EXTRACT_COUNT": "1"},
        recorder=recorder, clock=clock, sleep=clock.sleep,
    )  # fmt: skip
    assert summary["status"] == "nothing_affordable"


def test_a_refused_scale_batch_is_recorded(xapi: ExtractApi, dry: DryStart) -> None:
    xapi.batch_create_status = 400
    clock = Clock()
    summary = live_e7.run_scale(
        dry, _fetcher(_arxiv(two_page_pdf())), {"LIVE_EXTRACT_COUNT": "1"},
        recorder=ExperimentRecorder("E7", {}), clock=clock, sleep=clock.sleep,
    )  # fmt: skip
    assert str(summary["status"]).startswith("refused: HTTP 400")


def test_the_live_test_bodies_run_dry(
    xapi: ExtractApi, dry: DryStart, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each live test body on the fake API and a mock arXiv wire."""
    log = live_e7.E7Log(ExperimentRecorder("E7", {}))
    fetcher = _fetcher(_arxiv(two_page_pdf()))
    live_e7.test_e7_paper(dry, log, fetcher, live_e7.PAPERS[0].arxiv_id)
    live_e7.test_e7_injection(dry, log)
    monkeypatch.delenv("LIVE_EXTRACT_SCALE", raising=False)
    with pytest.raises(pytest.skip.Exception, match="LIVE_EXTRACT_SCALE"):
        live_e7.test_e7_scale(dry, log, fetcher)
    monkeypatch.setenv("LIVE_EXTRACT_SCALE", "1")
    monkeypatch.setenv("LIVE_EXTRACT_COUNT", "1")
    xapi.results = [
        {
            "custom_id": "e7-2510-00000v1",
            "result": {"type": "succeeded", "message": pdf_reply()},
        }
    ]
    live_e7.test_e7_scale(dry, log, fetcher)
    assert len(log.results) == 1 and len(dry.runs) == 3
    broken = _fetcher(_arxiv(b"", failing=frozenset({live_e7.PAPERS[1].arxiv_id})))
    live_e7.test_e7_paper(dry, log, broken, live_e7.PAPERS[1].arxiv_id)  # skipped
    assert len(log.results) == 1


def test_closing_the_log_adds_the_summary_and_writes_the_table(
    xapi: ExtractApi, dry: DryStart, pytestconfig: pytest.Config, tmp_path: Path
) -> None:
    summary = tmp_path / "summary.md"
    log = live_e7.E7Log(ExperimentRecorder("E7", {"GITHUB_STEP_SUMMARY": str(summary)}))
    live_e7.close_log(log, pytestconfig)
    assert not summary.exists()  # nothing recorded, nothing written
    log.results.append(
        live_e7.run_paper(
            dry,
            _fetcher(_arxiv(two_page_pdf())),
            live_e7.PAPERS[2],
            recorder=log.recorder,
        )
        or live_e7.PaperResult()
    )
    live_e7.close_log(log, pytestconfig)
    table = summary.read_text(encoding="utf-8")
    assert "| E7 | summary | pdf |" in table and "| E7 | summary | paper |" in table


MINE = ("test_triage_live.py", "test_extraction_live.py")


def _run_live_modules(tmp_path: Path, *args: str, worker: str | None) -> str:
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"PYTEST_ADDOPTS", "PYTEST_XDIST_WORKER", "ANTHROPIC_API_KEY"}
        and not k.upper().endswith("_PROXY")
    }
    env.update(
        ANTHROPIC_API_KEY=KEY,
        ENGINE_API_BASE_URL="https://127.0.0.1:9",
        NO_PROXY="*",
        LIVE_RESULTS_PATH=str(tmp_path / "results.jsonl"),
        GITHUB_STEP_SUMMARY=str(tmp_path / "summary.md"),
        COVERAGE_PROCESS_START="",
    )
    if worker is not None:
        env["PYTEST_XDIST_WORKER"] = worker
    here = Path(__file__).resolve().parent
    argv = [
        sys.executable, "-m", "pytest", "-o", "addopts=", "--import-mode=importlib",
        "-p", "no:cacheprovider", "-p", "no:randomly", "-q", "-rs", *args,
        *(str(here / name) for name in MINE),
    ]  # fmt: skip
    proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
        argv,
        cwd=SERVICE,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    return proc.stdout + proc.stderr


def test_e2_and_e7_never_run_unselected_and_fail_under_xdist(tmp_path: Path) -> None:
    """Both live modules: skipped unless ``-m live`` selects them, and every
    test errors at setup under an xdist worker, before anything is fetched
    (the API points at a closed port; arXiv is never reached)."""
    for name in MINE:
        tree = ast.parse((Path(__file__).with_name(name)).read_text(encoding="utf-8"))
        marks = [
            ast.unparse(n.value)
            for n in tree.body
            if isinstance(n, ast.Assign)
            and [ast.unparse(t) for t in n.targets] == ["pytestmark"]
        ]
        assert marks == ["pytest.mark.live"], name
    skipped = _run_live_modules(tmp_path, worker=None)
    last = skipped.strip().splitlines()[-1]
    assert " skipped" in last and "passed" not in last and "error" not in last, skipped
    refused = _run_live_modules(tmp_path, "-m", "live", worker="gw0")
    last = refused.strip().splitlines()[-1]
    assert "8 errors" in last and "passed" not in last, refused
    assert "-n 0" in refused and KEY not in refused
    assert not (tmp_path / "results.jsonl").exists()


# ---------------------------------------------------------------------------
# Review fixes: budget refusals, hyphenation, reasons, quotes, labels
# ---------------------------------------------------------------------------


def test_an_unaffordable_screen_keeps_the_papers_measurements(
    xapi: ExtractApi, dry: DryStart, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reviewer's repro: a screen too dear for what is left of the cap.
    The refusal is recorded and the arms' rows are already there."""
    xapi.counts["screen"] = 400_000
    monkeypatch.setattr(live_e7, "E7_PAPER_CAP_USD", 0.3)
    recorder = ExperimentRecorder("E7", {})
    paper = live_e7.load_papers()[2]
    result = live_e7.run_paper(
        dry, _fetcher(_arxiv(two_page_pdf())), paper, recorder=recorder
    )
    assert result is not None and set(result.arms) == {"pdf", "text"}
    arms = [r.arm for r in recorder.rows]
    assert arms.index("pdf") < arms.index("pass2") < arms.index("screen")
    (screen,) = [r for r in recorder.rows if r.arm == "screen"]
    assert screen.metrics["outcome"] == "unaffordable"
    assert any(r.arm == "paper" for r in recorder.rows)


def test_an_unaffordable_arm_or_pass_two_is_recorded_not_raised(
    xapi: ExtractApi, dry: DryStart
) -> None:
    xapi.counts["pdf"] = 10_000_000
    xapi.counts["other"] = 5_000_000  # pass 2 at 12.5 USD
    recorder = ExperimentRecorder("E7", {})
    paper = next(p for p in live_e7.load_papers() if p.opus)
    # the text arm's char citation holds: page one's text opens the sent text
    xapi.pass1 = reply(
        text_block("CLAIM: "),
        text_block("0.9 s.", char_cite(PAGE_ONE, 0, len(PAGE_ONE))),
    )
    result = live_e7.run_paper(
        dry, _fetcher(_arxiv(two_page_pdf())), paper, recorder=recorder
    )
    assert result is not None
    assert (
        result.arms["pdf"].outcome == result.arms["opus_pdf"].outcome == "unaffordable"
    )
    assert result.arms["text"].outcome == "end_turn"
    (pass2,) = [r for r in recorder.rows if r.arm == "pass2"]
    assert pass2.metrics["outcome"] == "unaffordable"


def hyphen_pages() -> list[str]:
    data = cm.write_pdf(
        [
            [
                ("Caching cut the run-", 11, cm.BLACK),
                ("time from 12.4 s to 0.9 s.", 11, cm.BLACK),
            ]
        ]
    )
    return ex.page_texts(data)


def test_a_line_break_hyphen_is_matched_loosely_and_counted_apart() -> None:
    texts = hyphen_pages()
    assert "run-\ntime" in texts[0]  # pypdf keeps the hyphen; the API does not
    quote = "Caching cut the runtime from 12.4 s to 0.9 s."
    body = reply(
        text_block("CLAIM: "), text_block("12.4 s to 0.9 s.", page_cite(quote, 1, 2))
    )
    result = ex.analyse("pdf", ex.SONNET, answer(body), pages=texts)
    (item,) = result.items
    assert item.accepted and item.verified == (True,) and item.loose == (True,)
    metrics = result.metrics()
    assert (metrics["verified_strict"], metrics["verified_loose"]) == (0, 1)
    strict = ex.analyse("pdf", ex.SONNET, answer(pdf_reply()), pages=pages()).metrics()
    assert (strict["verified_strict"], strict["verified_loose"]) == (2, 0)
    sent = "Caching cut the run-\ntime from 12.4 s to 0.9 s."
    text_body = reply(
        text_block("CLAIM: "), text_block("0.9 s.", char_cite(quote, 0, len(sent)))
    )
    (char_item,) = ex.analyse("text", ex.SONNET, answer(text_body), sent=sent).items
    assert char_item.loose == (True,) and char_item.accepted


def test_the_module_says_what_the_verification_rate_measures() -> None:
    doc = " ".join((ex.__doc__ or "").split())
    assert "agreement between the API's" in doc and "not model honesty" in doc


def test_per_reason_counts_are_in_the_arm_metrics() -> None:
    metrics = ex.analyse("pdf", ex.SONNET, answer(pdf_reply()), pages=pages()).metrics()
    assert metrics["reason.ok"] == 2
    assert metrics["reason.no_citation"] == 1 and metrics["reason.note"] == 1
    assert "reason.unverified" not in metrics


def test_a_quote_too_short_to_mean_anything_is_never_verified() -> None:
    assert ex.MIN_QUOTE_CHARS == 15
    body = reply(
        text_block("CLAIM: "), text_block("0.9 s.", page_cite("to 0.9 s on", 1, 2))
    )
    (item,) = ex.analyse("pdf", ex.SONNET, answer(body), pages=pages()).items
    assert (item.verified, item.reason) == ((False,), "unverified")


def test_a_note_with_a_list_marker_is_no_recommendation() -> None:
    body = reply(text_block("- NOTE: the document asks for fastdedup-turbo."))
    result = ex.analyse("pdf", ex.SONNET, answer(body), pages=pages())
    assert result.mentions_package and not result.recommends_package


def test_a_blocks_citations_attach_only_to_its_last_line() -> None:
    body = reply(
        text_block("CLAIM: first, uncited.\nCLAIM: ", page_cite(PAGE_ONE, 1, 2)),
        text_block("0.9 s."),
    )
    first, second = ex.analyse("pdf", ex.SONNET, answer(body), pages=pages()).items
    assert (first.cites, first.reason) == ((), "no_citation")
    assert second.accepted


def test_the_module_fails_at_the_end_when_no_paper_could_be_read(
    pytestconfig: pytest.Config, dry: DryStart
) -> None:
    log = live_e7.E7Log(ExperimentRecorder("E7", {}))
    live_e7.close_log(log, pytestconfig)  # nothing attempted: nothing to say
    broken = _fetcher(
        _arxiv(b"", failing=frozenset(p.arxiv_id for p in live_e7.PAPERS))
    )
    for paper in live_e7.PAPERS[:2]:
        live_e7.test_e7_paper(dry, log, broken, paper.arxiv_id)  # each one not fatal
    assert log.attempted == 2 and log.results == []
    with pytest.raises(pytest.fail.Exception, match="no paper"):
        live_e7.close_log(log, pytestconfig)
