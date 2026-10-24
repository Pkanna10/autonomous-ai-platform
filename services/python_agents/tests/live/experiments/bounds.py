"""Worst-case bounds and prices for the raw-SDK experiments (pure functions).

``worst_case_usd`` is what ``ExperimentClient`` checks against the run's
budget BEFORE a paid call; ``price_message`` is what it records after.

Docs relied on (platform.claude.com/docs, read 2026-10-23):

- pricing: batch 50 % of input and output; cache writes 1.25x (5 min) and
  2x (1 h) input, stacking with the batch discount; web search $10 per
  1,000 searches (a failed search is not billed), its results billed as
  input in each later iteration of the turn; web fetch free beyond tokens;
  long-context tiers (``ModelPrice.long_context``, Haiku 5.5) per request.
- web-fetch-tool: ``max_content_tokens`` "applies to text content, not to
  binary content such as PDFs"; a 500 kB research paper is about 125,000
  tokens. server-tools: ``_20260209`` and later web tools filter through
  code execution unless ``allowed_callers: ["direct"]``; a use past
  ``max_uses`` is an in-band error and the loop goes on.
- claude-api skill, shared/tool-use-concepts.md: the server-side loop stops
  at "its default limit of 10 iterations" with ``pause_turn``.
- batch-processing: a batch runs "more iterations in a turn" (no number).
- vision: at most 4,784 visual tokens an image (Claude 4.7 and later).
- pdf-support: 1,500-3,000 text tokens a page, each page also an image.

Assumptions (no documented figure; E1, E6 and E9 calibrate them):

- ``SERVER_LOOP_PASSES`` = 10 sampling passes for a synchronous request
  with a server tool (the skill's figure, not the API reference's).
- ``SEARCH_RESULT_TOKENS`` = 25,000 input tokens one search adds.
- ``WEB_FETCH_PDF_TOKENS`` = 200,000 tokens one fetched PDF adds.
- ``SERVER_TOOL_DEFINITION_TOKENS`` = 2,000 for a server tool's definition
  (``count_tokens`` refuses server tools, so they are stripped and added).
- ``CITATIONS_TOKENS`` = 2,000 for the citations prompt.
- ``STRUCTURED_OUTPUT_TOKENS`` = 2,000 for the structured-output system
  prompt, charged only when no count covers ``output_config``.
- ``count_tokens`` counts the structured-output system prompt when
  ``output_config.format`` is sent, which is why ``count_extras`` omits it.
- ``count + count_margin`` bounds the billed prompt (inherited from
  ``clients/cost.py``, whose reach rule the tier check also uses).
- ``PDF_PAGE_TOKENS`` = 3,000 + 4,784 per PDF page (the docs' typical upper
  text figure plus the image maximum); used for uploaded files only, since a
  PDF is never sized without ``count_tokens``.
"""

from __future__ import annotations

import base64
import binascii
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from typing import Final, TypeAlias, cast

from anthropic.types.beta import BetaMessage

from autonomous_ai_agents.clients.cost import (
    BUILTIN_TOOL_INPUT_TOKENS,
    TOOL_USE_SYSTEM_PROMPT_TOKENS,
    count_margin,
    response_cost,
)
from autonomous_ai_agents.common.models import LongContextPrice, ModelPrice

BATCH_DISCOUNT: Final = Fraction(1, 2)
ONE_HOUR_WRITE_PER_INPUT: Final = Fraction(2)
WEB_SEARCH_USD: Final = 0.01
SERVER_LOOP_PASSES: Final = 10  # assumption, see the module docstring
SEARCH_RESULT_TOKENS: Final = 25_000  # assumption
WEB_FETCH_PDF_TOKENS: Final = 200_000  # assumption
SERVER_TOOL_DEFINITION_TOKENS: Final = 2_000  # assumption
CITATIONS_TOKENS: Final = 2_000  # assumption
STRUCTURED_OUTPUT_TOKENS: Final = 2_000  # assumption
PDF_PAGE_TOKENS: Final = 3_000 + 4_784  # assumption
IMAGE_TOKENS: Final = 4_784
PDF_MAX_PAGES: Final = 600  # pdf-support: the most pages one request holds
CLIENT_TOOL_PREFIXES: Final = ("text_editor_", "bash_", "memory_", "computer_")
_PER_MTOK: Final = Fraction(1_000_000)
_PDF_SPACE = rb"(?:[\x00\t\n\x0c\r ]|%[^\r\n]*(?:\r\n|\r|\n))*"
_PDF_PAGE = re.compile(rb"/Type" + _PDF_SPACE + rb"/Page(?![A-Za-z0-9#])")
_PDF_HIDDEN = re.compile(rb"/ObjStm|/[A-Za-z0-9]*#[0-9A-Fa-f]{2}")
Json: TypeAlias = dict[str, object]


class ExperimentRefusedError(Exception):
    """A call the harness cannot bound or must not send; it was not sent."""


def _whole(value: object, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"expected a whole number >= {minimum}, got {value!r}")
    return value


@dataclass(frozen=True)
class ToolAllowance:
    """What server tools may add to one request: sampling ``passes``, input
    ``added_tokens`` per pass (results) and fees outside tokens, per billed
    model. The bound also re-reads each earlier pass's output."""

    passes: int = 1
    added_tokens: int = 0
    fee_usd: float = 0.0

    def __post_init__(self) -> None:
        _whole(self.passes, 1)
        _whole(self.added_tokens, 0)
        if not math.isfinite(self.fee_usd) or self.fee_usd < 0:
            raise ValueError(f"bad allowance fee {self.fee_usd}")

    def at_least(self, other: ToolAllowance) -> ToolAllowance:
        """The component-wise maximum: an explicit allowance never undercuts."""
        return ToolAllowance(
            max(self.passes, other.passes),
            max(self.added_tokens, other.added_tokens),
            max(self.fee_usd, other.fee_usd),
        )


@dataclass(frozen=True)
class UploadedFile:
    file_id: str
    mime_type: str
    size_bytes: int
    pages: int | None

    @property
    def tokens(self) -> int:
        """The most the file can add to a prompt (PDF pages, an image, bytes)."""
        if self.mime_type == "application/pdf":
            return (self.pages or 1) * PDF_PAGE_TOKENS + self.size_bytes
        if self.mime_type.startswith("image/"):
            return IMAGE_TOKENS
        return self.size_bytes


def billed_models(body: Mapping[str, object]) -> tuple[str, ...]:
    """The model, then each explicit fallback: every model the request may bill."""
    fallbacks = body.get("fallbacks")
    if fallbacks is not None and not isinstance(fallbacks, list):
        raise ExperimentRefusedError(
            f"fallbacks {fallbacks!r} may bill an unpriced model; list them"
        )
    listed = [f.get("model") if isinstance(f, Mapping) else f for f in fallbacks or []]
    chain = [body.get("model"), *listed]
    if not all(isinstance(m, str) and m for m in chain):
        raise ExperimentRefusedError(f"the model chain {chain!r} is not model ids")
    return tuple(cast(list[str], chain))


def _kind(tool: object) -> object:
    return tool.get("type") if isinstance(tool, Mapping) else None


def is_server_tool(tool: object) -> bool:
    """A tool the API runs (or an unknown typed one): not custom, not client."""
    kind = _kind(tool)
    if kind is None or kind == "custom" or kind in BUILTIN_TOOL_INPUT_TOKENS:
        return False
    return not (isinstance(kind, str) and kind.startswith(CLIENT_TOOL_PREFIXES))


def server_allowance(
    tools: Sequence[object], *, batch: bool, explicit: ToolAllowance | None = None
) -> ToolAllowance:
    """The documented bound for direct web search and fetch, at least
    ``explicit``; any other server tool, or any server tool in a batch,
    needs ``explicit``."""
    server = [tool for tool in tools if is_server_tool(tool)]
    added, fee, unbounded = 0, Fraction(0), []
    for tool in server:
        assert isinstance(tool, Mapping)
        per_use = _per_use_tokens(tool)
        if per_use is None:
            unbounded.append(str(tool.get("type")))
            continue
        uses = cast(int, tool["max_uses"])
        added += uses * per_use
        if str(tool["type"]).startswith("web_search_"):
            fee += uses * Fraction(WEB_SEARCH_USD)
    if server and batch:
        unbounded.append("server tools in a batch (no documented iteration limit)")
    if unbounded and explicit is None:
        raise ExperimentRefusedError(
            f"no documented bound for {', '.join(unbounded)}; pass a ToolAllowance"
        )
    passes = SERVER_LOOP_PASSES if server else 1
    documented = ToolAllowance(passes, added, float(fee))
    return documented if explicit is None else explicit.at_least(documented)


def _per_use_tokens(tool: Mapping[str, object]) -> int | None:
    """Input one use of a direct web tool adds, or ``None`` when unbounded."""
    kind, uses = tool.get("type"), tool.get("max_uses")
    if not isinstance(kind, str) or not kind.startswith(("web_search_", "web_fetch_")):
        return None
    if kind.rsplit("_", 1)[1] >= "20260209" and tool.get("allowed_callers") != [
        "direct"
    ]:
        return None  # dynamic filtering runs code execution
    if isinstance(uses, bool) or not isinstance(uses, int) or uses < 1:
        return None
    if kind.startswith("web_search_"):
        return SEARCH_RESULT_TOKENS
    text = tool.get("max_content_tokens")
    if isinstance(text, bool) or not isinstance(text, int) or text < 1:
        return None
    return max(text, WEB_FETCH_PDF_TOKENS)  # the text cap does not cap PDFs


def pdf_pages(data: bytes) -> int:
    """An upper bound on a PDF's pages (a helper; never a prompt bound by
    itself): its page objects, at least 1, or the documented maximum when
    pages can hide (object streams, ``#``-escaped names). Whitespace,
    NUL and ``%`` comments may sit between ``/Type`` and ``/Page``."""
    if _PDF_HIDDEN.search(data):
        return PDF_MAX_PAGES
    return max(1, len(_PDF_PAGE.findall(data)))


def minimal_pdf(text: str, *, pages: int = 1) -> bytes:
    """A valid, uncompressed PDF with ``text`` on each of ``pages`` pages."""
    if pages < 1 or not re.fullmatch(r"[A-Za-z0-9 .,!?-]*", text):
        raise ValueError("pages >= 1 and plain ASCII text without parentheses")
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(pages))
    stream = f"BT /F1 24 Tf 72 720 Td ({text}) Tj ET".encode()
    font = 3 + 2 * pages
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {pages} >>".encode(),
    ]
    for i in range(pages):
        page = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents "
            f"{4 + 2 * i} 0 R /Resources << /Font << /F1 {font} 0 R >> >> >>"
        )
        objects.append(page.encode())
        objects.append(
            b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream)
        )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref, size = len(out), len(objects) + 1
    out += b"xref\n0 %d\n0000000000 65535 f \n" % size
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\n" % size
    out += b"startxref\n%d\n%%%%EOF\n" % xref
    return bytes(out)


def _nodes(body: Mapping[str, object]) -> list[Mapping[str, object]]:
    """Every object under the system prompt and the messages."""
    found, stack = [], [body.get("system"), body.get("messages")]
    while stack:
        node = stack.pop()
        if isinstance(node, list):
            stack.extend(node)
        elif isinstance(node, Mapping):
            found.append(node)
            stack.extend(node.values())
    return found


def _source(node: Mapping[str, object]) -> Mapping[str, object] | None:
    source = node.get("source")
    if node.get("type") in ("document", "image") and isinstance(source, Mapping):
        return source
    return None


def check_sources(body: Mapping[str, object]) -> None:
    """Refuse document and image sources ``count_tokens`` cannot size: a
    ``file`` or ``url`` source (URL content can change). Send them inline."""
    for node in _nodes(body):
        source = _source(node)
        if source is not None and source.get("type") in ("file", "url"):
            raise ExperimentRefusedError(
                f"a {node['type']} with a {source['type']} source cannot be bounded;"
                " send it inline as base64"
            )


def has_pdf(body: Mapping[str, object]) -> bool:
    return any(
        (s := _source(node)) is not None and s.get("media_type") == "application/pdf"
        for node in _nodes(body)
    )


def _citations(body: Mapping[str, object]) -> bool:
    tools = body.get("tools")
    listed = tools if isinstance(tools, list) else []
    nodes = _nodes(body) + [t for t in listed if isinstance(t, Mapping)]
    return any(
        isinstance(c := node.get("citations"), Mapping) and c.get("enabled") is True
        for node in nodes
    )


def count_body(body: Mapping[str, object], count_keys: frozenset[str]) -> Json:
    """What ``count_tokens`` accepts: its keys, server tools stripped (it
    refuses them), and ``tool_choice`` dropped when no tool is left."""
    sent = {k: v for k, v in body.items() if k in count_keys}
    tools = sent.get("tools")
    if isinstance(tools, list):
        kept = [tool for tool in tools if not is_server_tool(tool)]
        sent["tools"] = kept
        if not kept:
            del sent["tools"]
            sent.pop("tool_choice", None)
    return sent


def count_extras(body: Mapping[str, object]) -> int:
    """What a count of ``count_body`` cannot see: the stripped server tools'
    definitions (and the tool prompt when none is left) and citations."""
    tools = body.get("tools")
    listed = tools if isinstance(tools, list) else []
    server = sum(1 for tool in listed if is_server_tool(tool))
    extras = server * SERVER_TOOL_DEFINITION_TOKENS
    if server and server == len(listed):
        extras += TOOL_USE_SYSTEM_PROMPT_TOKENS
    return extras + (CITATIONS_TOKENS if _citations(body) else 0)


def structural_tokens(
    body: Mapping[str, object], files: Mapping[str, UploadedFile]
) -> int:
    """A prompt bound without a count: every byte, each image at its maximum,
    files uploaded for code execution, the tool prompt and definitions, the
    citations and structured-output prompts. Refuses a PDF (only a count can
    size one) and file or URL sources."""
    check_sources(body)
    if has_pdf(body):
        raise ExperimentRefusedError("a PDF needs count_tokens; it did not answer")
    total = len(json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode())
    for node in _nodes(body):
        if node.get("type") == "container_upload":
            file_id = node.get("file_id")
            if not isinstance(file_id, str) or file_id not in files:
                raise ExperimentRefusedError(f"file {file_id!r} was not uploaded here")
            total += files[file_id].tokens
        elif node.get("type") == "image" and _source(node) is not None:
            total += IMAGE_TOKENS
        elif node.get("type") == "document" and _source(node) is not None:
            source = cast(Mapping[str, object], node["source"])
            if source.get("type") == "base64":
                _decodes(source.get("data"))
    tools = body.get("tools")
    if isinstance(tools, list) and tools:
        total += TOOL_USE_SYSTEM_PROMPT_TOKENS
        for tool in tools:
            kind = _kind(tool)
            if kind not in (None, "custom"):
                total += BUILTIN_TOOL_INPUT_TOKENS.get(
                    str(kind), SERVER_TOOL_DEFINITION_TOKENS
                )
    config = body.get("output_config")
    if isinstance(config, Mapping) and config.get("format") is not None:
        total += STRUCTURED_OUTPUT_TOKENS
    return total + (CITATIONS_TOKENS if _citations(body) else 0)


def _decodes(data: object) -> None:
    try:
        base64.b64decode(str(data), validate=True)
    except (binascii.Error, ValueError):
        raise ExperimentRefusedError("base64 document data does not decode") from None


def _one_hour(node: object) -> bool:
    if isinstance(node, Mapping):
        control = node.get("cache_control")
        if isinstance(control, Mapping) and control.get("ttl") == "1h":
            return True
        return any(_one_hour(value) for value in node.values())
    return isinstance(node, list) and any(_one_hour(item) for item in node)


def _side_and_output(
    price: ModelPrice, read: int, hour: bool
) -> tuple[Fraction, Fraction]:
    """The dearest input-side and output rates any prompt up to ``read``
    pays: a bound within one count margin of a long-context threshold
    counts as crossing it (``cost._rates_upto``'s reach rule)."""
    rates: list[ModelPrice | LongContextPrice] = [price]
    long = price.long_context
    if long is not None and read + count_margin(read) > long.threshold_tokens:
        rates.append(long)
    side, output = Fraction(0), Fraction(0)
    for rate in rates:
        inputs = [
            Fraction(rate.input),
            Fraction(rate.cache_write),
            Fraction(rate.cache_read),
        ]
        if hour:
            inputs.append(ONE_HOUR_WRITE_PER_INPUT * Fraction(rate.input))
        side = max(side, *inputs)
        output = max(output, Fraction(rate.output))
    return side, output


def worst_case_usd(
    body: Mapping[str, object],
    prompt_tokens: int,
    prices: Mapping[str, ModelPrice],
    *,
    allowance: ToolAllowance,
    batch: bool,
) -> float:
    """The most the request can be billed. Each of ``passes`` passes reads
    the prompt, the allowance's added tokens and every earlier pass's output
    (``(passes - 1) * max_tokens``) at the dearest input-side rate (2x input
    with a 1-hour breakpoint) and writes ``max_tokens``; every chain model
    may bill a whole turn; tokens at half price in a batch; fees per model."""
    max_tokens = body.get("max_tokens")
    if (
        isinstance(max_tokens, bool)
        or not isinstance(max_tokens, int)
        or max_tokens < 1
    ):
        raise ExperimentRefusedError(f"max_tokens must be >= 1, got {max_tokens!r}")
    models = billed_models(body)
    missing = sorted({m for m in models if m not in prices})
    if missing:
        raise ExperimentRefusedError(f"no price for {', '.join(missing)}")
    passes = allowance.passes
    per_pass = prompt_tokens + allowance.added_tokens + (passes - 1) * max_tokens
    read, hour = passes * per_pass, _one_hour(body)
    attempts = []
    for model in models:
        side, output = _side_and_output(prices[model], read, hour)
        attempts.append(read * side + passes * max_tokens * output)
    tokens = len(models) * max(attempts) / _PER_MTOK * (BATCH_DISCOUNT if batch else 1)
    return float(tokens + len(models) * Fraction(allowance.fee_usd))


def price_message(
    message: BetaMessage, prices: Mapping[str, ModelPrice], *, batch: bool
) -> float:
    """What the answer was billed: ``response_cost`` (each attempt at its own
    tier), halved in a batch, plus web searches at full price."""
    usd, _ = response_cost(message.usage, prices, model=message.model)
    tool_use = message.usage.server_tool_use
    searches = tool_use.web_search_requests if tool_use is not None else 0
    discount = BATCH_DISCOUNT if batch else 1
    return float(Fraction(usd) * discount + searches * Fraction(WEB_SEARCH_USD))
