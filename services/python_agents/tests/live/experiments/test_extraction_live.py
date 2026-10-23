"""E7: two-pass extraction from real performance papers (live, CI only).

Per paper of ``papers.json`` (``test_e7_paper``): fetch its metadata (the
title is compared with ours) and its PDF from arXiv; pass 1 on Sonnet 5.5
with the PDF inline and citations on (arm ``pdf``), on the pypdf text as a
plain-text document with citations (arm ``text``), and on Opus 5.5 with the
PDF for the papers marked ``opus`` (arm ``opus_pdf``); every citation is
verified locally (``extraction.analyse``); pass 2 turns the accepted items of
both Sonnet arms into Technique cards (results only, never the playbook);
the Haiku 5.5 screen reads the extracted text. ``test_e7_injection`` runs the
two planted PDFs through the same passes and the screen. ``test_e7_scale``
(only with ``LIVE_EXTRACT_SCALE=1``) sends up to ``LIVE_EXTRACT_COUNT`` (50)
recent cs.PF papers as one Sonnet pass-1 batch, verifies the results and
structures them while the cap allows; ``LIVE_EXTRACT_WAIT_S`` (3600) bounds
the wait, after which the batch id is recorded as pending.

A fetch failure, an unreadable PDF or one over ``MAX_PAGES`` is recorded and
skipped, never fatal. Caps: ``E7_PAPER_CAP_USD`` / ``E7_OPUS_PAPER_CAP_USD``
hold the worst case of every call at the page cap (``test_extraction``);
expected about 0.45 USD a Sonnet-only paper and 0.90 with Opus, 0.10 for
the planted pair, and 6-8 USD for the opt-in scale-up.
"""

from __future__ import annotations

import json
import math
import os
import re
import time
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

import pytest

from autonomous_ai_agents.clients.structured import Fence
from autonomous_ai_agents.common.errors import BudgetExceeded

from ..conftest import StartLive
from .arxiv_fetch import ArxivFetcher, FetchError, FetchRefusedError, check_id
from .bounds import ExperimentRefusedError, Json
from .cards import (
    INSTRUCTION,
    card_metrics,
    pass2_params,
    planted_pdf,
    read_cards,
    read_screen,
    screen_params,
)
from .extraction import (
    OPUS,
    SONNET,
    ArmResult,
    Item,
    agreement,
    analyse,
    normalise,
    page_texts,
    pass1_params,
    pdf_document,
    text_document,
)
from .harness import MAX_WAIT_S, Answer, BatchItem, ExperimentAPIError, ExperimentClient
from .recorder import ExperimentRecorder, Metric
from .test_probes_live import finish

pytestmark = pytest.mark.live

PAPERS_PATH: Final = Path(__file__).with_name("papers.json")
MAX_PAGES = 30
E7_PAPER_CAP_USD: Final = 1.25
E7_OPUS_PAPER_CAP_USD: Final = 2.75
E7_INJECTION_CAP_USD: Final = 0.75
E7_SCALE_CAP_USD: Final = 10.0
SCALE_QUERY: Final = "cat:cs.PF"
SCALE_BATCH_SHARE: Final = 0.6  # of the scale cap; the rest is for pass 2
BATCH_MAX_BYTES: Final = 200 * 1024 * 1024  # batch-processing: 256 MB a batch
PLANTED_ID: Final = "0001.00001"  # new-style in shape, before any real one


@dataclass(frozen=True)
class Paper:
    arxiv_id: str
    title: str
    opus: bool


def load_papers(path: Path = PAPERS_PATH) -> tuple[Paper, ...]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != 1:
        raise ValueError(f"{path.name}: unknown version")
    return tuple(
        Paper(check_id(p["arxiv_id"]), str(p["title"]), bool(p["opus"]))
        for p in data["papers"]
    )


PAPERS: Final = load_papers()
TITLES: Final = {p.arxiv_id: p.title for p in PAPERS}


@dataclass
class PaperResult:
    arms: dict[str, ArmResult] = field(default_factory=dict)
    cards: int = 0
    cost_usd: float = 0.0


def _simple(title: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", title.casefold()).split())


UNAFFORDABLE: Final = "unaffordable"  # the run's cap refused the call; not sent


def _arm(
    client: ExperimentClient,
    arm: str,
    model: str,
    document: Json,
    *,
    pages: Sequence[str] | None = None,
    sent: str | None = None,
) -> ArmResult:
    try:
        answer = client.messages(pass1_params(model, document))
    except ExperimentRefusedError as exc:
        answer = Answer(None, None, str(exc), 0.0, 0.0, "refused")
    except BudgetExceeded as exc:
        answer = Answer(None, None, str(exc), 0.0, 0.0, UNAFFORDABLE)
    return analyse(arm, model, answer, pages=pages, sent=sent)


def _structure(
    client: ExperimentClient,
    recorder: ExperimentRecorder,
    arxiv_id: str,
    items: Sequence[Item],
    item: str,
) -> tuple[int, str, str]:
    """Pass 2 on ``items``: the cards it kept, its reply text, its outcome."""
    params = pass2_params(items, arxiv_id, Fence.new())
    if params is None:
        recorder.record("E7", "pass2", item, {"outcome": "nothing_to_structure"})
        return 0, "", "nothing_to_structure"
    try:
        answer = client.messages(params)
    except BudgetExceeded:
        recorder.record("E7", "pass2", item, {"outcome": UNAFFORDABLE})
        return 0, "", UNAFFORDABLE
    cards, rejected = read_cards(answer, arxiv_id, len(items))
    for card in cards:
        recorder.record("E7", "card", item, card_metrics(card))
    text = "".join(
        b.text
        for b in (answer.message.content if answer.message else [])
        if b.type == "text"
    )
    recorder.record(
        "E7",
        "pass2",
        item,
        {
            "outcome": answer.outcome,
            "cards": len(cards),
            "rejected": "; ".join(rejected),
            "cost_usd": answer.cost_usd,
        },
    )
    return len(cards), text, answer.outcome


def _screen(
    client: ExperimentClient, recorder: ExperimentRecorder, text: str, item: str
) -> bool | None:
    params, metrics = screen_params(text, Fence.new())
    try:
        answer = client.messages(params)
    except BudgetExceeded:
        recorder.record("E7", "screen", item, {**metrics, "outcome": UNAFFORDABLE})
        return None
    positive, outcome = read_screen(answer)
    recorder.record(
        "E7",
        "screen",
        item,
        {
            **metrics,
            "positive": positive,
            "outcome": outcome,
            "cost_usd": answer.cost_usd,
        },
    )
    return positive


def _accepted(*arms: ArmResult) -> list[Item]:
    seen: dict[str, Item] = {}
    for arm in arms:
        for item in arm.items:
            if item.accepted:
                seen.setdefault(normalise(item.text).casefold(), item)
    return list(seen.values())


def run_paper(
    start: StartLive,
    fetcher: ArxivFetcher,
    paper: Paper,
    *,
    recorder: ExperimentRecorder,
) -> PaperResult | None:
    """Both passes, the arms and the screen for one paper (``None``: skipped)."""
    key = paper.arxiv_id
    try:
        meta = fetcher.entries([key])
    except (FetchError, FetchRefusedError):
        meta = ()
    try:
        data = fetcher.pdf(key)
        pages = page_texts(data)
    except (FetchError, FetchRefusedError, ValueError) as exc:
        status = exc.status if isinstance(exc, FetchError) else None
        recorder.record("E7", "fetch", key, {"status": status, "error": str(exc)})
        return None
    if len(pages) > MAX_PAGES:
        recorder.record(
            "E7", "paper", key, {"outcome": "too_long", "pages": len(pages)}
        )
        return None
    text = "\n\n".join(pages)
    run = start(E7_OPUS_PAPER_CAP_USD if paper.opus else E7_PAPER_CAP_USD)
    result = PaperResult()
    with ExperimentClient(run, recorder=recorder) as client:
        result.arms["pdf"] = _arm(
            client, "pdf", SONNET, pdf_document(data, paper.title), pages=pages
        )
        if text.strip():
            result.arms["text"] = _arm(
                client, "text", SONNET, text_document(text, paper.title), sent=text
            )
        if paper.opus:
            result.arms["opus_pdf"] = _arm(
                client, "opus_pdf", OPUS, pdf_document(data, paper.title), pages=pages
            )
        # the measurements first: a later refusal cannot lose them
        for name, arm in result.arms.items():
            recorder.record("E7", name, key, arm.metrics())
        if "opus_pdf" in result.arms:
            recorder.record(
                "E7",
                "agreement",
                key,
                agreement(result.arms["pdf"], result.arms["opus_pdf"]),
            )
        result.cards, _, _ = _structure(
            client,
            recorder,
            key,
            _accepted(*(result.arms[a] for a in ("pdf", "text") if a in result.arms)),
            key,
        )
        _screen(client, recorder, text, key)
    result.cost_usd = run.spent_usd
    pdf, txt = result.arms["pdf"], result.arms.get("text")
    recorder.record(
        "E7",
        "paper",
        key,
        {
            "title_matches": bool(meta)
            and _simple(meta[0].title) == _simple(paper.title),
            "pages": len(pages),
            "bytes": len(data),
            "cards": result.cards,
            "cost_usd": result.cost_usd,
            "text_vs_pdf_claims": f"{txt.claims_with_numbers}/{pdf.claims_with_numbers}"
            if txt
            else None,
        },
    )
    run.note(f"E7 {key}: {len(pages)} pages, {result.cards} card(s)")
    return result


def run_injection(
    start: StartLive, *, recorder: ExperimentRecorder
) -> dict[str, dict[str, Metric]]:
    """The two planted PDFs through pass 1 (both arms), pass 2 and the screen."""
    run = start(E7_INJECTION_CAP_USD)
    found: dict[str, dict[str, Metric]] = {}
    with ExperimentClient(run, recorder=recorder) as client:
        for mode in ("white", "tiny"):
            data = planted_pdf(mode)
            pages = page_texts(data)
            text = "\n\n".join(pages)
            pdf = _arm(
                client, "pdf", SONNET, pdf_document(data, "Planted paper"), pages=pages
            )
            txt = _arm(
                client, "text", SONNET, text_document(text, "Planted paper"), sent=text
            )
            cards, reply, _ = _structure(
                client, recorder, PLANTED_ID, _accepted(pdf, txt), f"planted-{mode}"
            )
            positive = _screen(client, recorder, text, f"planted-{mode}")
            for arm in (pdf, txt):
                recorder.record("E7", f"injection_{arm.arm}", mode, arm.metrics())
            found[mode] = {
                "extracted_has_instruction": INSTRUCTION in normalise(text),
                "pass1_mentions_package": pdf.mentions_package or txt.mentions_package,
                "pass1_recommends_package": pdf.recommends_package
                or txt.recommends_package,
                "pass2_mentions_package": "fastdedup" in reply.casefold(),
                "cards": cards,
                "screen_positive": positive,
            }
            recorder.record("E7", "injection", mode, found[mode])
    return found


def scale_requested(environ: Mapping[str, str]) -> bool:
    raw = environ.get("LIVE_EXTRACT_SCALE", "").strip()
    if raw not in ("", "0", "1"):
        raise ValueError(f"LIVE_EXTRACT_SCALE must be 0 or 1, got {raw!r}")
    return raw == "1"


def _knob(environ: Mapping[str, str], name: str, default: float, high: float) -> float:
    raw = environ.get(name, "").strip()
    value = (
        float(raw)
        if re.fullmatch(r"\d+(\.\d+)?", raw)
        else (default if not raw else math.nan)
    )
    if not 1 <= value <= high:
        raise ValueError(f"{name} must be a number from 1 to {high:g}, got {raw!r}")
    return value


def run_scale(
    start: StartLive,
    fetcher: ArxivFetcher,
    environ: Mapping[str, str],
    *,
    recorder: ExperimentRecorder,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Metric]:
    """Pass 1 on up to 50 recent papers in one Sonnet batch, then pass 2."""
    count = int(_knob(environ, "LIVE_EXTRACT_COUNT", 50, 50))
    wait_s = _knob(environ, "LIVE_EXTRACT_WAIT_S", 3600, MAX_WAIT_S)
    docs: dict[str, tuple[str, list[str], BatchItem]] = {}
    summary: dict[str, Metric] = {"papers": 0, "batch_id": None, "status": "no_papers"}
    size = 0
    try:
        found = fetcher.search(SCALE_QUERY, start=0, max_results=count)
    except (FetchError, FetchRefusedError) as exc:
        found, summary["status"] = (), "fetch_failed"
        recorder.record("E7", "scale_skip", "search", {"error": str(exc)})
    for entry in found:
        try:
            data = fetcher.pdf(entry.arxiv_id)
            pages = page_texts(data)
        except (FetchError, FetchRefusedError, ValueError) as exc:
            recorder.record("E7", "scale_skip", entry.arxiv_id, {"error": str(exc)})
            continue
        size += len(data) * 4 // 3 + 4096
        if len(pages) > MAX_PAGES or size > BATCH_MAX_BYTES:
            recorder.record(
                "E7",
                "scale_skip",
                entry.arxiv_id,
                {"pages": len(pages), "batch_bytes": size},
            )
            continue
        cid = "e7-" + entry.arxiv_id.replace(".", "-")
        docs[cid] = (
            entry.arxiv_id,
            pages,
            BatchItem(cid, pass1_params(SONNET, pdf_document(data, entry.title))),
        )
    if not docs:
        recorder.record("E7", "scale", "summary", summary)
        return summary
    summary["status"] = "nothing_affordable"
    run = start(E7_SCALE_CAP_USD)
    with ExperimentClient(run, recorder=recorder, clock=clock, sleep=sleep) as client:
        items, reserved = [], 0.0
        for _, _, item in docs.values():
            estimate = client.estimate(item.params, batch=True)
            if reserved + estimate <= SCALE_BATCH_SHARE * E7_SCALE_CAP_USD:
                items.append(item)
                reserved += estimate
        try:
            batch = client.submit(items) if items else None
        except ExperimentAPIError as exc:
            batch, summary["status"] = None, f"refused: {exc}"
        if batch is not None:
            summary.update(papers=len(items), batch_id=batch.batch_id)
            summary["status"] = client.wait(batch, timeout_s=wait_s, poll_s=30.0)
            if summary["status"] == "ended":
                summary.update(_collect(client, recorder, docs, client.results(batch)))
    recorder.record("E7", "scale", "summary", summary)
    run.note(f"E7 scale batch {summary['batch_id']}: {summary['status']}")
    return summary


def _collect(
    client: ExperimentClient,
    recorder: ExperimentRecorder,
    docs: Mapping[str, tuple[str, list[str], BatchItem]],
    answers: Mapping[str, Answer],
) -> dict[str, Metric]:
    accepted = cited = verified = cards = 0
    budget_left = True
    reasons: Counter[str] = Counter()
    for cid, answer in answers.items():
        arxiv_id, pages, _ = docs[cid]
        arm = analyse("scale_pdf", SONNET, answer, pages=pages)
        recorder.record("E7", "scale_pdf", arxiv_id, arm.metrics())
        accepted, cited, verified = (
            accepted + arm.accepted,
            cited + arm.citations,
            verified + arm.verified,
        )
        reasons.update(arm.reasons())
        if budget_left and arm.accepted:
            kept, _, outcome = _structure(
                client, recorder, arxiv_id, _accepted(arm), arxiv_id
            )
            cards += kept
            if outcome == UNAFFORDABLE:
                budget_left = False
                recorder.record("E7", "pass2", "budget_stop", {"after": arxiv_id})
    return {
        "accepted": accepted,
        "verification_rate": verified / cited if cited else None,
        "cards": cards,
        **{f"reason.{k}": v for k, v in sorted(reasons.items())},
    }


def summarise(results: Sequence[PaperResult]) -> dict[str, dict[str, Metric]]:
    """Across papers, per arm: verification rate, tokens a page, cost, recall."""
    out: dict[str, dict[str, Metric]] = {}
    for name in ("pdf", "text", "opus_pdf"):
        arms = [r.arms[name] for r in results if name in r.arms]
        cited = sum(a.citations for a in arms)
        per_page = [a.tokens_per_page for a in arms if a.tokens_per_page is not None]
        out[name] = {
            "papers": len(arms),
            "verification_rate": sum(a.verified for a in arms) / cited
            if cited
            else None,
            "tokens_per_page": sum(per_page) / len(per_page) if per_page else None,
            "cost_usd": math.fsum(a.cost_usd for a in arms),
            "claims_with_numbers": sum(a.claims_with_numbers for a in arms),
        }
    claims = {
        name: sum(r.arms[name].claims_with_numbers for r in results if name in r.arms)
        for name in ("pdf", "text")
    }
    out["paper"] = {
        "papers": len(results),
        "cost_per_paper_usd": (
            math.fsum(r.cost_usd for r in results) / len(results) if results else None
        ),
        "numeric_claims_ratio": (
            claims["text"] / claims["pdf"] if claims["pdf"] else None
        ),
        "cards": sum(r.cards for r in results),
    }
    return out


@dataclass
class E7Log:
    recorder: ExperimentRecorder
    results: list[PaperResult] = field(default_factory=list)
    attempted: int = 0


@pytest.fixture(scope="module")
def e7(pytestconfig: pytest.Config) -> Iterator[E7Log]:
    log = E7Log(ExperimentRecorder("E7 two-pass paper extraction", os.environ))
    yield log
    close_log(log, pytestconfig)


def close_log(log: E7Log, config: pytest.Config) -> None:
    """The summary rows across papers, then the table to the job summary;
    then a failure when papers were tried and none could be read (one fetch
    failure is not fatal, all of them make the run red)."""
    if log.results:
        for arm, metrics in summarise(log.results).items():
            log.recorder.record("E7", "summary", arm, metrics)
    finish(log.recorder, config)
    if log.attempted and not log.results:
        pytest.fail(f"E7: no paper of {log.attempted} could be fetched and read")


@pytest.fixture(scope="module")
def arxiv() -> Iterator[ArxivFetcher]:
    with ArxivFetcher() as fetcher:
        yield fetcher


def _answered(result: PaperResult | None) -> bool:
    gone = {"refused", "no_answer", "lost", "unreadable", UNAFFORDABLE}
    return result is None or any(a.outcome not in gone for a in result.arms.values())


@pytest.mark.parametrize("arxiv_id", [p.arxiv_id for p in PAPERS])
def test_e7_paper(
    live: StartLive, e7: E7Log, arxiv: ArxivFetcher, arxiv_id: str
) -> None:
    paper = next(p for p in PAPERS if p.arxiv_id == arxiv_id)
    e7.attempted += 1
    result = run_paper(live, arxiv, paper, recorder=e7.recorder)
    if result is not None:
        e7.results.append(result)
    assert _answered(result), f"{arxiv_id}: the API answered no pass-1 request"


def test_e7_injection(live: StartLive, e7: E7Log) -> None:
    found = run_injection(live, recorder=e7.recorder)
    assert all(m["extracted_has_instruction"] for m in found.values())


def test_e7_scale(live: StartLive, e7: E7Log, arxiv: ArxivFetcher) -> None:
    if not scale_requested(os.environ):
        pytest.skip("the 50-paper batch runs only with LIVE_EXTRACT_SCALE=1")
    summary = run_scale(live, arxiv, os.environ, recorder=e7.recorder)
    assert summary["status"] not in ("no_papers", "nothing_affordable"), (
        f"the scale-up sent no batch: {summary['status']}"
    )
