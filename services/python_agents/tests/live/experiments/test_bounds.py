"""Offline tests of the experiments' worst-case bounds and prices (``bounds.py``).

The central property: no answer a request can get within its limits is
priced above the worst case checked before it was sent. The adversarial
cases come from the X3 review: a fetched PDF past ``max_content_tokens``,
ten server-loop passes on one search, iterations that re-read the output
before them, and a prompt within one count margin of a long-context tier.
"""

from __future__ import annotations

import base64
import json
import math
from collections.abc import Mapping

import pytest
from anthropic.types.beta import BetaMessage

from autonomous_ai_agents.clients.cost import (
    BUILTIN_TOOL_INPUT_TOKENS,
    TOOL_USE_SYSTEM_PROMPT_TOKENS,
    count_margin,
)
from autonomous_ai_agents.common.config import settings
from autonomous_ai_agents.common.models import LongContextPrice, ModelPrice

from .bounds import (
    CITATIONS_TOKENS,
    IMAGE_TOKENS,
    PDF_MAX_PAGES,
    PDF_PAGE_TOKENS,
    SEARCH_RESULT_TOKENS,
    SERVER_LOOP_PASSES,
    SERVER_TOOL_DEFINITION_TOKENS,
    STRUCTURED_OUTPUT_TOKENS,
    WEB_FETCH_PDF_TOKENS,
    WEB_SEARCH_USD,
    ExperimentRefusedError,
    ToolAllowance,
    UploadedFile,
    billed_models,
    check_sources,
    count_body,
    count_extras,
    has_pdf,
    is_server_tool,
    minimal_pdf,
    pdf_pages,
    price_message,
    server_allowance,
    structural_tokens,
    worst_case_usd,
)

OPUS, FALLBACK, HAIKU = "claude-opus-5-5", "claude-opus-4-8", "claude-haiku-5-5"
PRICES: Mapping[str, ModelPrice] = settings.MODEL_PRICING
Json = dict[str, object]
SEARCH: Json = {"type": "web_search_20250305", "name": "web_search", "max_uses": 1}
FETCH: Json = {
    "type": "web_fetch_20250910",
    "name": "web_fetch",
    "max_uses": 1,
    "max_content_tokens": 5000,
}
EDITOR: Json = {"type": "text_editor_20250728", "name": "str_replace_based_edit_tool"}
CUSTOM: Json = {"name": "t", "input_schema": {"type": "object"}}


def _user(text: str = "Say ok.") -> Json:
    return {"role": "user", "content": text}


def _body(**extra: object) -> Json:
    body: Json = {"model": HAIKU, "max_tokens": 64, "messages": [_user()]}
    body.update(extra)
    return body


def _attempt(model: str, input_tokens: int, output_tokens: int, **cache: int) -> Json:
    return {
        "type": "message",
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_creation_input_tokens": cache.get("write", 0),
        "cache_read_input_tokens": cache.get("read", 0),
    }


def _message(model: str, usage: Json) -> BetaMessage:
    return BetaMessage.model_validate(
        {
            "id": "msg_01Bounds",
            "type": "message",
            "role": "assistant",
            "model": model,
            "content": [],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": usage,
        }
    )


def _turn(model: str, attempts: list[Json], searches: int = 0) -> BetaMessage:
    usage: Json = {"input_tokens": 0, "output_tokens": 0, "iterations": attempts}
    usage["server_tool_use"] = {
        "web_search_requests": searches,
        "web_fetch_requests": 0,
    }
    return _message(model, usage)


def _long(model: str) -> LongContextPrice:
    long = PRICES[model].long_context
    assert long is not None
    return long


def _bytes(body: Json) -> int:
    return len(json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode())


def _pdf_block(pages: int = 1) -> Json:
    data = base64.b64encode(minimal_pdf("hello", pages=pages)).decode()
    source = {"type": "base64", "media_type": "application/pdf", "data": data}
    return {"type": "document", "source": source}


# ---------------------------------------------------------------------------
# The chain and the server-tool allowance
# ---------------------------------------------------------------------------


def test_billed_models_are_the_model_then_its_fallbacks() -> None:
    assert billed_models(_body()) == (HAIKU,)
    chained = _body(model=OPUS, fallbacks=[{"model": FALLBACK}])
    assert billed_models(chained) == (OPUS, FALLBACK)


@pytest.mark.parametrize(
    "body",
    [
        _body(fallbacks="default"),
        _body(fallbacks=[{"model": 5}]),
        _body(model=None),
        {"max_tokens": 5, "messages": []},
    ],
    ids=["default-scalar", "bad-fallback", "bad-model", "no-model"],
)
def test_billed_models_refuse_a_chain_they_cannot_price(body: Json) -> None:
    with pytest.raises(ExperimentRefusedError):
        billed_models(body)


def test_client_tools_add_no_server_pass() -> None:
    bash = {"type": "bash_20250124", "name": "bash"}
    for tool in (CUSTOM, EDITOR, bash):
        assert not is_server_tool(tool)
    assert server_allowance([CUSTOM, EDITOR, bash], batch=False) == ToolAllowance()
    assert server_allowance([CUSTOM], batch=True) == ToolAllowance()


def test_any_server_tool_runs_the_whole_server_loop() -> None:
    """A use past max_uses is an in-band error and the loop goes on, so a
    request with any server tool may take all ten passes."""
    search = server_allowance([{**SEARCH, "max_uses": 2}], batch=False)
    assert search == ToolAllowance(SERVER_LOOP_PASSES, 2 * SEARCH_RESULT_TOKENS, 0.02)
    assert SERVER_LOOP_PASSES == 10


def test_a_fetch_use_is_bounded_by_the_pdf_figure_not_the_text_cap() -> None:
    """Review blocker: max_content_tokens does not cap a PDF."""
    allowance = server_allowance([{**FETCH, "max_uses": 2}], batch=False)
    assert allowance == ToolAllowance(SERVER_LOOP_PASSES, 2 * WEB_FETCH_PDF_TOKENS)
    big = {**FETCH, "max_content_tokens": 300_000}
    assert server_allowance([big], batch=False).added_tokens == 300_000


@pytest.mark.parametrize(
    "tool",
    [
        {"type": "web_search_20250305", "name": "web_search"},
        {**SEARCH, "max_uses": 0},
        {**SEARCH, "max_uses": True},
        {"type": "web_search_20260209", "name": "web_search", "max_uses": 1},
        {"type": "web_fetch_20250910", "name": "web_fetch", "max_uses": 1},
        {"type": "code_execution_20260521", "name": "code_execution"},
        {"type": 7, "name": "odd"},
    ],
    ids=[
        "no-max-uses",
        "zero-uses",
        "bool-uses",
        "dynamic-filtering",
        "fetch-no-content-cap",
        "code-execution",
        "bad-type",
    ],
)
def test_a_tool_the_harness_cannot_bound_needs_an_explicit_allowance(
    tool: Json,
) -> None:
    with pytest.raises(ExperimentRefusedError, match="ToolAllowance"):
        server_allowance([tool], batch=False)
    explicit = ToolAllowance(12, 1000, 0.5)
    assert server_allowance([tool], batch=False, explicit=explicit) == explicit


def test_dynamic_filtering_called_directly_is_bounded_like_basic_search() -> None:
    tool = {
        "type": "web_search_20260318",
        "name": "web_search",
        "max_uses": 1,
        "allowed_callers": ["direct"],
    }
    assert server_allowance([tool], batch=False) == server_allowance(
        [SEARCH], batch=False
    )


def test_an_explicit_allowance_never_undercuts_the_documented_one() -> None:
    documented = server_allowance([SEARCH], batch=False)
    small = ToolAllowance(1, 0, 0.0)
    assert server_allowance([SEARCH], batch=False, explicit=small) == documented
    mixed = ToolAllowance(20, 1, 0.0)
    assert server_allowance([SEARCH], batch=False, explicit=mixed) == ToolAllowance(
        20, documented.added_tokens, documented.fee_usd
    )


def test_a_batch_item_with_server_tools_needs_an_explicit_allowance() -> None:
    with pytest.raises(ExperimentRefusedError, match="batch"):
        server_allowance([SEARCH], batch=True)
    explicit = ToolAllowance(30, 0, 0.0)
    allowed = server_allowance([SEARCH], batch=True, explicit=explicit)
    assert allowed.passes == 30 and allowed.added_tokens == SEARCH_RESULT_TOKENS


def test_tool_allowance_refuses_bad_numbers() -> None:
    for passes, added, fee in ((0, 0, 0.0), (1, -1, 0.0), (1, 0, math.nan)):
        with pytest.raises(ValueError):
            ToolAllowance(passes, added, fee)
    with pytest.raises(ValueError):
        ToolAllowance(passes=True)


# ---------------------------------------------------------------------------
# Sources, the count body and the structure
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "block",
    [
        {"type": "document", "source": {"type": "file", "file_id": "file_1"}},
        {"type": "image", "source": {"type": "url", "url": "https://x.example/a.png"}},
        {"type": "document", "source": {"type": "url", "url": "https://x.example/a"}},
    ],
    ids=["document-file", "image-url", "document-url"],
)
def test_file_and_url_sources_are_refused(block: Json) -> None:
    result = {"type": "tool_result", "tool_use_id": "t", "content": [block]}
    for content in ([block], [result]):
        with pytest.raises(ExperimentRefusedError, match="inline"):
            check_sources(_body(messages=[{"role": "user", "content": content}]))
    check_sources(_body(messages=[{"role": "user", "content": [_pdf_block()]}]))


def test_the_count_body_strips_server_tools_and_counts_what_it_cannot_see() -> None:
    keys = frozenset({"model", "messages", "tools", "tool_choice", "system"})
    body = _body(tools=[SEARCH, CUSTOM], tool_choice={"type": "auto"})
    assert count_body(body, keys)["tools"] == [CUSTOM]
    assert count_extras(body) == SERVER_TOOL_DEFINITION_TOKENS
    only = _body(tools=[SEARCH, FETCH], tool_choice={"type": "auto"})
    sent = count_body(only, keys)
    assert (
        "tools" not in sent and "tool_choice" not in sent and "max_tokens" not in sent
    )
    assert (
        count_extras(only)
        == 2 * SERVER_TOOL_DEFINITION_TOKENS + TOOL_USE_SYSTEM_PROMPT_TOKENS
    )
    cited = {
        "type": "document",
        "source": {"type": "text", "media_type": "text/plain", "data": "x"},
        "citations": {"enabled": True},
    }
    assert (
        count_extras(_body(messages=[{"role": "user", "content": [cited]}]))
        == CITATIONS_TOKENS
    )
    assert count_extras(_body(tools=[{**FETCH, "citations": {"enabled": True}}])) == (
        SERVER_TOOL_DEFINITION_TOKENS + TOOL_USE_SYSTEM_PROMPT_TOKENS + CITATIONS_TOKENS
    )
    assert count_extras(_body()) == 0


def test_structure_covers_every_byte_tools_and_the_structured_output_prompt() -> None:
    body = _body(system="Be brief.")
    assert structural_tokens(body, {}) == _bytes(body)
    tooled = _body(tools=[EDITOR, SEARCH, CUSTOM])
    added = (
        TOOL_USE_SYSTEM_PROMPT_TOKENS
        + BUILTIN_TOOL_INPUT_TOKENS["text_editor_20250728"]
        + SERVER_TOOL_DEFINITION_TOKENS
    )
    assert structural_tokens(tooled, {}) == _bytes(tooled) + added
    formatted = _body(output_config={"format": {"type": "json_schema", "schema": {}}})
    assert (
        structural_tokens(formatted, {}) == _bytes(formatted) + STRUCTURED_OUTPUT_TOKENS
    )
    effort = _body(output_config={"effort": "low"})
    assert structural_tokens(effort, {}) == _bytes(effort)


def test_structure_charges_images_uploads_and_citations() -> None:
    image = {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": "iVBORw0K"},
    }
    text = {
        "type": "document",
        "source": {"type": "base64", "media_type": "text/plain", "data": "aGk="},
        "citations": {"enabled": True},
    }
    upload = {"type": "container_upload", "file_id": "file_txt"}
    plain = {
        "type": "document",
        "source": {"type": "text", "media_type": "text/plain", "data": "hi"},
    }
    files = {"file_txt": UploadedFile("file_txt", "text/plain", 400, None)}
    body = _body(messages=[{"role": "user", "content": [image, text, upload, plain]}])
    expected = _bytes(body) + IMAGE_TOKENS + 400 + CITATIONS_TOKENS
    assert structural_tokens(body, files) == expected


@pytest.mark.parametrize(
    "block",
    [
        _pdf_block(),
        {"type": "tool_result", "tool_use_id": "t", "content": [_pdf_block()]},
        {"type": "container_upload", "file_id": "file_unknown"},
        {
            "type": "document",
            "source": {"type": "base64", "data": "!!", "media_type": "text/plain"},
        },
        {"type": "image", "source": {"type": "url", "url": "https://x.example/a.png"}},
    ],
    ids=["pdf", "pdf-in-tool-result", "unknown-upload", "bad-base64", "image-url"],
)
def test_the_structure_never_sizes_a_pdf_or_what_it_cannot_see(block: Json) -> None:
    body = _body(messages=[{"role": "user", "content": [block]}])
    with pytest.raises(ExperimentRefusedError):
        structural_tokens(body, {})


def test_has_pdf_finds_a_pdf_anywhere() -> None:
    nested = {"type": "tool_result", "tool_use_id": "t", "content": [_pdf_block()]}
    assert has_pdf(_body(messages=[{"role": "user", "content": [nested]}]))
    assert not has_pdf(_body())


def test_uploaded_file_tokens() -> None:
    assert (
        UploadedFile("f", "application/pdf", 900, 3).tokens == 3 * PDF_PAGE_TOKENS + 900
    )
    assert UploadedFile("f", "image/png", 50_000, None).tokens == IMAGE_TOKENS
    assert UploadedFile("f", "text/csv", 70, None).tokens == 70


def test_pdf_pages_sees_through_whitespace_nul_and_comments() -> None:
    plain = minimal_pdf("x", pages=2)
    assert pdf_pages(plain) == 2
    for gap in (b"\x00", b" % a comment\n", b"%c\r\n\x00 ", b"\t\x0c"):
        tricked = plain.replace(b"/Type /Page ", b"/Type" + gap + b"/Page ")
        assert pdf_pages(tricked) == 2, gap
    assert pdf_pages(b"%PDF-1.4 no pages here") == 1
    hidden = plain.replace(b"/Type /Page ", b"/Type /P#61ge ")
    packed = plain + b"\n9 0 obj << /Type /ObjStm /N 3 >> endobj"
    assert pdf_pages(hidden) == pdf_pages(packed) == PDF_MAX_PAGES


def test_minimal_pdf_is_well_formed() -> None:
    pdf = minimal_pdf("hello")
    assert pdf.startswith(b"%PDF-1.4") and pdf.rstrip().endswith(b"%%EOF")
    start = int(pdf.rsplit(b"startxref\n", 1)[1].split(b"\n")[0])
    assert pdf[start:].startswith(b"xref")
    with pytest.raises(ValueError):
        minimal_pdf("x", pages=0)
    with pytest.raises(ValueError):
        minimal_pdf("(unbalanced")


# ---------------------------------------------------------------------------
# The worst case
# ---------------------------------------------------------------------------


def test_worst_case_is_the_chain_times_the_dearest_attempt() -> None:
    body = _body(model=OPUS, fallbacks=[{"model": FALLBACK}], max_tokens=100)
    worst = worst_case_usd(body, 1000, PRICES, allowance=ToolAllowance(), batch=False)
    dear = PRICES[FALLBACK]  # dearer than Opus 5.5 in every component
    input_side = max(dear.input, dear.cache_write, dear.cache_read)
    assert worst == pytest.approx(2 * (1000 * input_side + 100 * dear.output) / 1e6)


def test_each_later_pass_rereads_the_output_before_it() -> None:
    body = _body(model=OPUS, max_tokens=100)
    rate = PRICES[OPUS]
    worst = worst_case_usd(
        body, 1000, PRICES, allowance=ToolAllowance(3, 50), batch=False
    )
    read = 3 * (1000 + 50 + 2 * 100)
    assert worst == pytest.approx(
        (read * rate.cache_write + 3 * 100 * rate.output) / 1e6
    )


def test_worst_case_halves_tokens_in_a_batch_but_not_fees() -> None:
    allowance = ToolAllowance(2, 500, 0.01)
    plain = worst_case_usd(_body(), 100, PRICES, allowance=allowance, batch=False)
    batch = worst_case_usd(_body(), 100, PRICES, allowance=allowance, batch=True)
    assert batch - 0.01 == pytest.approx((plain - 0.01) / 2)


def test_worst_case_charges_one_hour_cache_writes_at_twice_input() -> None:
    ttl = {
        "type": "text",
        "text": "x",
        "cache_control": {"type": "ephemeral", "ttl": "1h"},
    }
    body = _body(model=OPUS, system=[ttl], max_tokens=1)
    worst = worst_case_usd(body, 1000, PRICES, allowance=ToolAllowance(), batch=False)
    rate = PRICES[OPUS]
    assert worst == pytest.approx((1000 * 2 * rate.input + rate.output) / 1e6)


def test_a_bound_within_one_margin_of_the_tier_is_priced_at_the_long_rates() -> None:
    """Review item 6 (flipped): a prompt bound whose margin reaches past the
    threshold already pays the long rates; one whose margin does not, the
    base rates."""
    long, base = _long(HAIKU), PRICES[HAIKU]
    threshold = long.threshold_tokens
    within = next(
        p for p in range(threshold - 3000, threshold) if p + count_margin(p) > threshold
    )
    below = within - 1
    assert below + count_margin(below) <= threshold < within + count_margin(within)
    body = _body(max_tokens=1)
    short = worst_case_usd(body, below, PRICES, allowance=ToolAllowance(), batch=False)
    reach = worst_case_usd(body, within, PRICES, allowance=ToolAllowance(), batch=False)
    assert short == pytest.approx((below * base.cache_write + base.output) / 1e6)
    assert reach == pytest.approx((within * long.cache_write + long.output) / 1e6)


def test_worst_case_refuses_an_unpriced_model_or_a_bad_max_tokens() -> None:
    allowance = ToolAllowance()
    with pytest.raises(ExperimentRefusedError, match="no price"):
        worst_case_usd(
            _body(model="claude-unknown"), 1, PRICES, allowance=allowance, batch=False
        )
    for bad in (0, True, "5"):
        with pytest.raises(ExperimentRefusedError, match="max_tokens"):
            worst_case_usd(
                _body(max_tokens=bad), 1, PRICES, allowance=allowance, batch=False
            )


# ---------------------------------------------------------------------------
# The price, and the bound holding against adversarial answers
# ---------------------------------------------------------------------------


def _bound(
    tools: list[Json],
    prompt: int,
    max_tokens: int,
    model: str = HAIKU,
    *,
    batch: bool = False,
    explicit: ToolAllowance | None = None,
) -> float:
    allowance = server_allowance(tools, batch=batch, explicit=explicit)
    body = _body(model=model, max_tokens=max_tokens, tools=tools)
    return worst_case_usd(body, prompt, PRICES, allowance=allowance, batch=batch)


def test_a_fetched_pdf_past_the_text_cap_stays_within_the_bound() -> None:
    """The review's blocker: a 130K-token PDF fetched under a 5,000-token
    text cap (two passes: before and after the fetch)."""
    prompt, out = 1000, 100
    answer = _turn(
        HAIKU,
        [_attempt(HAIKU, prompt, out), _attempt(HAIKU, prompt + 130_000 + out, out)],
    )
    assert price_message(answer, PRICES, batch=False) <= _bound([FETCH], prompt, out)


def test_ten_passes_on_one_search_stay_within_the_bound() -> None:
    prompt, out = 1000, 200
    attempts = [
        _attempt(HAIKU, prompt + SEARCH_RESULT_TOKENS + i * out, out) for i in range(10)
    ]
    answer = _turn(HAIKU, attempts, searches=1)
    assert price_message(answer, PRICES, batch=False) <= _bound([SEARCH], prompt, out)


def test_iterations_that_reread_every_earlier_output_stay_within_the_bound() -> None:
    prompt, out = 5000, 4000
    attempts = []
    for i in range(SERVER_LOOP_PASSES):
        read = prompt + SEARCH_RESULT_TOKENS + i * out
        attempts.append(_attempt(OPUS, 0, out, write=read))  # all as cache writes
    answer = _turn(OPUS, attempts, searches=1)
    assert price_message(answer, PRICES, batch=False) <= _bound(
        [SEARCH], prompt, out, OPUS
    )


def test_a_prompt_counted_just_under_the_tier_and_billed_over_it_stays_within() -> None:
    """``count_tokens`` is an estimate: a count whose margin reaches the
    threshold may be billed just over it, at the long rates."""
    threshold = _long(HAIKU).threshold_tokens
    counted = threshold - count_margin(threshold)
    bound = counted + count_margin(counted)
    body = _body(max_tokens=10)
    worst = worst_case_usd(body, bound, PRICES, allowance=ToolAllowance(), batch=False)
    billed = _message(
        HAIKU, {"input_tokens": bound + count_margin(bound), "output_tokens": 10}
    )
    assert price_message(billed, PRICES, batch=False) <= worst


@pytest.mark.parametrize("batch", [False, True])
def test_the_dearest_plain_answer_stays_within_the_bound(batch: bool) -> None:
    for model in (OPUS, HAIKU):
        body = _body(model=model, max_tokens=512)
        worst = worst_case_usd(
            body, 4000, PRICES, allowance=ToolAllowance(), batch=batch
        )
        dear = _message(
            model,
            {
                "input_tokens": 0,
                "output_tokens": 512,
                "cache_creation_input_tokens": 4000,
            },
        )
        assert 0 < price_message(dear, PRICES, batch=batch) <= worst


def test_a_batch_with_an_explicit_allowance_stays_within_the_bound() -> None:
    prompt, out, passes = 2000, 200, 20
    attempts = [
        _attempt(HAIKU, prompt + SEARCH_RESULT_TOKENS + i * out, out)
        for i in range(passes)
    ]
    answer = _turn(HAIKU, attempts, searches=1)
    bound = _bound([SEARCH], prompt, out, batch=True, explicit=ToolAllowance(passes))
    assert price_message(answer, PRICES, batch=True) <= bound


def test_price_message_prices_each_attempt_at_its_own_tier() -> None:
    long, base = _long(HAIKU), PRICES[HAIKU]
    over = long.threshold_tokens + 1
    answer = _turn(HAIKU, [_attempt(HAIKU, 1000, 0), _attempt(HAIKU, over, 0)])
    expected = (1000 * base.input + over * long.input) / 1e6
    assert price_message(answer, PRICES, batch=False) == pytest.approx(expected)
    assert price_message(answer, PRICES, batch=True) == pytest.approx(expected / 2)


def test_price_message_adds_searches_at_full_price() -> None:
    answer = _turn(HAIKU, [_attempt(HAIKU, 0, 0)], searches=3)
    assert price_message(answer, PRICES, batch=True) == pytest.approx(
        3 * WEB_SEARCH_USD
    )
    plain = _message(HAIKU, {"input_tokens": 10, "output_tokens": 0})
    assert price_message(plain, PRICES, batch=False) == pytest.approx(
        10 * PRICES[HAIKU].input / 1e6
    )


def test_price_message_refuses_an_unreadable_usage() -> None:
    broken = _message(HAIKU, {"input_tokens": 1, "output_tokens": 0})
    broken.usage.input_tokens = -1
    with pytest.raises(ValueError):
        price_message(broken, PRICES, batch=False)
