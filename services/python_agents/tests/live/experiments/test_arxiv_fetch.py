"""Offline tests of the arXiv fetcher (``arxiv_fetch.py``): a mock wire only.

The production ``ArxivFetcher`` runs (its own httpx client, the allowlist,
the redirect rule, the rate spacing, the caps, the strict Atom reader); only
the transport, the clock and the sleep are swapped.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from urllib.parse import parse_qs, urlsplit

import httpx2
import pytest

from . import arxiv_fetch as af
from .arxiv_fetch import (
    METADATA_MAX_BYTES,
    MIN_SPACING_S,
    PDF_MAX_BYTES,
    ArxivFetcher,
    Entry,
    FetchError,
    FetchRefusedError,
    check_id,
    check_url,
    parse_feed,
    pdf_url,
    query_url,
    recent,
)

ATOM = "application/atom+xml; charset=utf-8"
PDF = b"%PDF-1.4\n% a paper\n%%EOF\n"


def feed(*entries: tuple[str, str, str]) -> bytes:
    """An arXiv-shaped Atom feed: (abs id, title, summary) per entry."""
    rows = "".join(
        f"<entry><id>http://arxiv.org/abs/{i}</id><title>{t}</title>"
        f"<summary>{s}</summary><published>2026-10-20T00:00:00Z</published>"
        '<arxiv:primary_category term="cs.PF"/></entry>'
        for i, t, s in entries
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<feed xmlns="http://www.w3.org/2005/Atom" '
        'xmlns:arxiv="http://arxiv.org/schemas/atom">' + rows + "</feed>"
    ).encode()


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


Handler = Callable[[httpx2.Request], httpx2.Response]


class Wire:
    """A mock wire that records every request and answers with ``handler``."""

    def __init__(self, handler: Handler) -> None:
        self.handler = handler
        self.requests: list[httpx2.Request] = []
        self.sent_at: list[float] = []
        self.clock = Clock()

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        self.sent_at.append(self.clock.now)
        return self.handler(request)

    def fetcher(self) -> ArxivFetcher:
        return ArxivFetcher(
            transport=httpx2.MockTransport(self),
            clock=self.clock,
            sleep=self.clock.sleep,
        )


def _atom(body: bytes = feed(("2510.01234v1", "T", "S"))) -> Handler:
    return lambda _: httpx2.Response(200, content=body, headers={"content-type": ATOM})


# ---------------------------------------------------------------------------
# The allowlist and the id rule
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value", ["2501.01234", "2501.0123", "2510.01234v2", "1102.1523", "0704.0001v12"]
)
def test_new_style_ids_are_accepted(value: str) -> None:
    assert check_id(value) == value
    assert pdf_url(value) == f"https://arxiv.org/pdf/{value}"
    assert check_url(pdf_url(value)) == "pdf"


@pytest.mark.parametrize(
    "value",
    [
        "2513.01234",  # month 13
        "2500.01234",
        "250.01234",
        "2501.123",
        "2501.123456",
        "2501.01234v0",
        "2501.01234v",
        "2501.01234\n",
        "cs/0112017",
        "../2501.01234",
        "2501.01234/../../x",
        "\uff12\uff15\uff10\uff11.01234",  # fullwidth digits
        "",
    ],
)
def test_anything_else_is_not_an_id(value: str) -> None:
    with pytest.raises(FetchRefusedError):
        check_id(value)
    with pytest.raises(FetchRefusedError):
        check_url(f"https://arxiv.org/pdf/{value}")


def test_the_metadata_url_is_exactly_the_export_api() -> None:
    url = query_url({"search_query": "cat:cs.PF", "start": 0, "max_results": 10})
    assert url.startswith("https://export.arxiv.org/api/query?")
    assert check_url(url) == "metadata"
    assert check_url("https://export.arxiv.org/api/query") == "metadata"


@pytest.mark.parametrize(
    "url",
    [
        "http://export.arxiv.org/api/query",
        "http://arxiv.org/pdf/2501.01234",
        "https://export.arxiv.org/api/query/",
        "https://export.arxiv.org/api/query?search_query=x&callback=y",
        "https://export.arxiv.org:8443/api/query",
        "https://user:pw@export.arxiv.org/api/query",
        "https://export.arxiv.org/api/query#frag",
        "https://arxiv.org/api/query",
        "https://export.arxiv.org/pdf/2501.01234",
        "https://arxiv.org/pdf/2501.01234?download=1",
        "https://arxiv.org/pdf/2501.01234.pdf",
        "https://arxiv.org/abs/2501.01234",
        "https://arxiv.org.evil.example/pdf/2501.01234",
        "https://evil.example/https://arxiv.org/pdf/2501.01234",
        "https://ARXIV.org/pdf/2501.01234/",
        "https://arxiv.org//pdf/2501.01234",
        "https://arxiv.org/pdf/2501.01234%2F..",
        "ftp://arxiv.org/pdf/2501.01234",
        "https://127.0.0.1/api/query",
        "https://arxiv.org:443@evil.example/pdf/2501.01234",
        "https://arxiv.org:99999/pdf/2501.01234",
        "https://arxiv.org:port/pdf/2501.01234",
    ],
)
def test_the_allowlist_refuses_everything_else(url: str) -> None:
    with pytest.raises(FetchRefusedError):
        check_url(url)


def test_a_query_with_an_unknown_key_is_never_built() -> None:
    with pytest.raises(FetchRefusedError, match="query"):
        query_url({"search_query": "x", "callback": "y"})


def test_the_default_port_is_allowed_and_no_other() -> None:
    assert check_url("https://arxiv.org:443/pdf/2501.01234") == "pdf"


# ---------------------------------------------------------------------------
# The client: no environment, no automatic redirects, a timeout
# ---------------------------------------------------------------------------


def test_the_client_ignores_the_environment_and_never_follows_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("SSL_CERT_FILE", "/nonexistent")
    with ArxivFetcher() as fetcher:
        assert fetcher.client.trust_env is False
        assert fetcher.client.follow_redirects is False
        assert fetcher.client.timeout.read == af.TIMEOUT_S
        assert "autonomous-ai-platform" in fetcher.client.headers["user-agent"]


def test_the_spacing_cannot_be_set_below_the_arxiv_terms() -> None:
    with pytest.raises(ValueError, match="3"):
        ArxivFetcher(spacing_s=MIN_SPACING_S - 0.1)


def test_requests_are_at_least_three_seconds_apart() -> None:
    wire = Wire(_atom())
    with wire.fetcher() as fetcher:
        for _ in range(3):
            fetcher.search("cat:cs.PF", start=0, max_results=1)
            wire.clock.now += 0.5  # the caller's own work takes time too
    gaps = [b - a for a, b in zip(wire.sent_at, wire.sent_at[1:], strict=False)]
    assert gaps and all(gap >= MIN_SPACING_S for gap in gaps)
    assert wire.clock.sleeps == [pytest.approx(2.5), pytest.approx(2.5)]


def test_a_slow_caller_is_not_made_to_wait() -> None:
    wire = Wire(_atom())
    with wire.fetcher() as fetcher:
        fetcher.search("cat:cs.PF", start=0, max_results=1)
        wire.clock.now += 10
        fetcher.search("cat:cs.PF", start=0, max_results=1)
    assert wire.clock.sleeps == []


def test_a_transport_failure_is_a_fetch_error() -> None:
    def boom(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("slow", request=request)

    with Wire(boom).fetcher() as fetcher, pytest.raises(FetchError) as caught:
        fetcher.search("cat:cs.PF", start=0, max_results=1)
    assert caught.value.status is None and "ReadTimeout" in str(caught.value)


def test_an_http_error_is_a_fetch_error_with_its_status() -> None:
    wire = Wire(lambda _: httpx2.Response(503, content=b"busy"))
    with wire.fetcher() as fetcher, pytest.raises(FetchError) as caught:
        fetcher.pdf("2501.01234")
    assert caught.value.status == 503


# ---------------------------------------------------------------------------
# Redirects: only to the same allowlisted kind, the same paper, twice at most
# ---------------------------------------------------------------------------


def _redirect(location: str, status: int = 302) -> httpx2.Response:
    return httpx2.Response(status, headers={"location": location})


def test_a_pdf_redirect_to_a_version_of_the_same_paper_is_followed() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/pdf/2501.01234":
            return _redirect("/pdf/2501.01234v3", 301)
        return httpx2.Response(
            200, content=PDF, headers={"content-type": "application/pdf"}
        )

    wire = Wire(handler)
    with wire.fetcher() as fetcher:
        assert fetcher.pdf("2501.01234") == PDF
    assert [str(r.url) for r in wire.requests] == [
        "https://arxiv.org/pdf/2501.01234",
        "https://arxiv.org/pdf/2501.01234v3",
    ]
    assert wire.sent_at[1] - wire.sent_at[0] >= MIN_SPACING_S


@pytest.mark.parametrize(
    "location",
    [
        "https://evil.example/pdf/2501.01234",
        "http://arxiv.org/pdf/2501.01234v2",
        "https://arxiv.org/pdf/2501.09999",
        "https://export.arxiv.org/api/query?id_list=2501.01234",
        "https://export.arxiv.org/pdf/2501.01234",
        "//evil.example/pdf/2501.01234",
        "",
    ],
)
def test_any_other_redirect_is_refused_unsent(location: str) -> None:
    wire = Wire(lambda _: _redirect(location))
    with wire.fetcher() as fetcher, pytest.raises(FetchRefusedError):
        fetcher.pdf("2501.01234")
    assert len(wire.requests) == 1


def test_a_metadata_redirect_stays_on_the_export_api() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if "start=0" in str(request.url):
            return _redirect(query_url({"search_query": "cat:cs.PF", "start": 5}))
        return _atom()(request)

    wire = Wire(handler)
    with wire.fetcher() as fetcher:
        assert len(fetcher.search("cat:cs.PF", start=0, max_results=1)) == 1
    assert len(wire.requests) == 2


def test_a_redirect_loop_stops_after_two_hops() -> None:
    hops = iter(["/pdf/2501.01234v1", "/pdf/2501.01234v2", "/pdf/2501.01234v3"])
    wire = Wire(lambda _: _redirect(next(hops)))
    with wire.fetcher() as fetcher, pytest.raises(FetchRefusedError, match="redirect"):
        fetcher.pdf("2501.01234")
    assert len(wire.requests) == af.MAX_REDIRECTS + 1


# ---------------------------------------------------------------------------
# Size caps and content types
# ---------------------------------------------------------------------------


def test_a_declared_length_over_the_cap_is_refused_before_reading() -> None:
    read: list[int] = []

    def body() -> Iterator[bytes]:
        read.append(1)
        yield PDF

    wire = Wire(
        lambda _: httpx2.Response(
            200,
            content=body(),
            headers={
                "content-type": "application/pdf",
                "content-length": str(PDF_MAX_BYTES + 1),
            },
        )
    )
    with wire.fetcher() as fetcher, pytest.raises(FetchRefusedError, match="MiB"):
        fetcher.pdf("2501.01234")
    assert read == []


@pytest.mark.parametrize(
    ("kind", "cap", "content_type"),
    [("pdf", PDF_MAX_BYTES, "application/pdf"), ("metadata", METADATA_MAX_BYTES, ATOM)],
)
def test_a_streamed_body_over_the_cap_is_cut_off(
    kind: str, cap: int, content_type: str
) -> None:
    chunk = b"%PDF-" + b"x" * (1024 * 1024 - 5)
    sent: list[int] = []

    def body() -> Iterator[bytes]:
        for _ in range(cap // len(chunk) + 2):
            sent.append(len(chunk))
            yield chunk

    wire = Wire(
        lambda _: httpx2.Response(
            200, content=body(), headers={"content-type": content_type}
        )
    )
    with wire.fetcher() as fetcher, pytest.raises(FetchRefusedError, match="MiB"):
        if kind == "pdf":
            fetcher.pdf("2501.01234")
        else:
            fetcher.search("cat:cs.PF", start=0, max_results=1)
    assert sum(sent) <= cap + len(chunk)


def test_a_body_at_the_cap_is_read() -> None:
    wire = Wire(
        lambda _: httpx2.Response(
            200,
            content=PDF + b"0" * (PDF_MAX_BYTES - len(PDF)),
            headers={"content-type": "application/pdf"},
        )
    )
    with wire.fetcher() as fetcher:
        assert len(fetcher.pdf("2501.01234")) == PDF_MAX_BYTES


@pytest.mark.parametrize(
    ("content_type", "body"),
    [
        ("text/html", PDF),
        ("application/pdf; charset=binary", b"<html>not a pdf</html>"),
        (None, PDF),
    ],
)
def test_a_pdf_must_be_typed_and_shaped_as_one(
    content_type: str | None, body: bytes
) -> None:
    headers = {"content-type": content_type} if content_type else {}
    wire = Wire(lambda _: httpx2.Response(200, content=body, headers=headers))
    with wire.fetcher() as fetcher, pytest.raises(FetchRefusedError):
        fetcher.pdf("2501.01234")


def test_metadata_must_be_xml() -> None:
    wire = Wire(
        lambda _: httpx2.Response(
            200, content=feed(), headers={"content-type": "text/html"}
        )
    )
    with wire.fetcher() as fetcher, pytest.raises(FetchRefusedError, match="type"):
        fetcher.search("cat:cs.PF", start=0, max_results=1)


# ---------------------------------------------------------------------------
# The Atom reader: no DOCTYPE, no ENTITY, UTF-8 only, ids validated
# ---------------------------------------------------------------------------


LAUGHS = (
    b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">'
    b'<!ENTITY lol2 "&lol;&lol;&lol;&lol;">]>'
    b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>&lol2;</title>'
    b"</entry></feed>"
)
EXTERNAL = (
    b'<?xml version="1.0"?><!DOCTYPE feed [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
    b'<feed xmlns="http://www.w3.org/2005/Atom"><title>&xxe;</title></feed>'
)


@pytest.mark.parametrize(
    "body",
    [
        LAUGHS,
        EXTERNAL,
        b'<!doctype feed><feed xmlns="http://www.w3.org/2005/Atom"/>',
        b'<feed xmlns="http://www.w3.org/2005/Atom"><!ENTITY x "y"></feed>',
        LAUGHS.decode().encode("utf-16"),
        b'<?xml version="1.0" encoding="ISO-8859-1"?><feed/>',
        b"\xff\xfe<feed/>",
        b"<feed><entry></feed>",
        b"",
    ],
    ids=[
        "billion-laughs",
        "external-entity",
        "doctype-lowercase",
        "entity-in-body",
        "utf16",
        "latin1-declared",
        "not-utf8",
        "malformed",
        "empty",
    ],
)
def test_entity_and_doctype_feeds_are_refused(body: bytes) -> None:
    with pytest.raises(FetchRefusedError):
        parse_feed(body)


def test_a_feed_is_read_into_validated_entries() -> None:
    body = feed(
        ("2510.01234v2", "  A   fast\n  cache ", " We cut runtime\n by 30%. "),
        ("2510.99999v1", "Second", "Two"),
        ("errors#incorrect_id_format_for_x", "Error", "bad id"),
        ("2510.01234v1", "Duplicate", "again"),
    )

    entries = parse_feed(body)

    assert entries == (
        Entry("2510.01234v2", "A fast cache", "We cut runtime by 30%.", "2026-10-20T00:00:00Z", "cs.PF"),
        Entry("2510.99999v1", "Second", "Two", "2026-10-20T00:00:00Z", "cs.PF"),
    )  # fmt: skip
    assert entries[0].base_id == "2510.01234"


def test_titles_and_abstracts_are_capped() -> None:
    (entry,) = parse_feed(feed(("2510.01234", "t" * 5000, "a" * 50_000)))
    assert len(entry.title) == af.TITLE_MAX_CHARS
    assert len(entry.abstract) == af.ABSTRACT_MAX_CHARS


def test_an_entry_without_a_title_or_abstract_is_skipped() -> None:
    body = (
        b'<feed xmlns="http://www.w3.org/2005/Atom"><entry>'
        b"<id>http://arxiv.org/abs/2510.01234</id></entry></feed>"
    )
    assert parse_feed(body) == ()


# ---------------------------------------------------------------------------
# Queries: search, id lists, recent abstracts per category
# ---------------------------------------------------------------------------


def test_entries_by_id_sends_a_validated_id_list() -> None:
    wire = Wire(_atom())
    with wire.fetcher() as fetcher:
        fetcher.entries(["2501.01234", "1102.1523"])
        with pytest.raises(FetchRefusedError):
            fetcher.entries(["2501.01234", "x) OR (1"])
    (request,) = wire.requests
    query = parse_qs(urlsplit(str(request.url)).query)
    assert query["id_list"] == ["2501.01234,1102.1523"]
    assert query["max_results"] == ["2"]


def test_recent_pages_through_each_category_and_drops_repeats() -> None:
    pages: dict[tuple[str, str], bytes] = {
        ("cat:cs.PF", "0"): feed(("2510.00001v1", "a", "a"), ("2510.00002v1", "b", "b")),
        ("cat:cs.PF", "2"): feed(("2510.00003v1", "c", "c")),
        ("cat:cs.DC", "0"): feed(("2510.00002v1", "b", "b"), ("2510.00004v1", "d", "d")),
        ("cat:cs.DC", "2"): feed(),
    }  # fmt: skip

    def handler(request: httpx2.Request) -> httpx2.Response:
        query = parse_qs(urlsplit(str(request.url)).query)
        assert query["sortBy"] == ["submittedDate"]
        assert query["sortOrder"] == ["descending"]
        key = (query["search_query"][0], query["start"][0])
        return httpx2.Response(200, content=pages[key], headers={"content-type": ATOM})

    wire = Wire(handler)
    with wire.fetcher() as fetcher:
        got = recent(fetcher, {"cs.PF": 3, "cs.DC": 3}, page_size=2)

    assert [e.arxiv_id for e in got] == [
        "2510.00001v1",
        "2510.00002v1",
        "2510.00003v1",
        "2510.00004v1",
    ]
    assert len(wire.requests) == 4


def test_recent_refuses_an_unknown_category() -> None:
    with Wire(_atom()).fetcher() as fetcher, pytest.raises(FetchRefusedError):
        recent(fetcher, {"cs.PF OR all:x": 1})


def test_a_get_of_the_wrong_kind_is_refused_unsent() -> None:
    wire = Wire(_atom())
    with wire.fetcher() as fetcher, pytest.raises(FetchRefusedError, match="metadata"):
        fetcher.get(pdf_url("2501.01234"), "metadata")
    assert wire.requests == []


def test_a_leading_bom_is_stripped_before_the_encoding_check() -> None:
    bom = b"\xef\xbb\xbf"
    assert parse_feed(bom + feed(("2510.01234v1", "T", "S")))[0].title == "T"
    with pytest.raises(FetchRefusedError, match="encoding"):
        parse_feed(bom + b'<?xml version="1.0" encoding="ISO-8859-1"?><feed/>')
    with pytest.raises(FetchRefusedError, match="DOCTYPE"):
        parse_feed(bom + LAUGHS)


def test_a_body_that_trickles_past_the_deadline_is_cut_off() -> None:
    """httpx's timeout is per read; a body sent a byte at a time within it
    would hold the job, so the whole body has a wall-clock deadline."""
    wire = Wire(lambda _: httpx2.Response(200))
    sent: list[int] = []

    def trickle() -> Iterator[bytes]:
        for _ in range(10):
            wire.clock.now += 100.0
            sent.append(1)
            yield b"%PDF-" if not sent[1:] else b"x"

    wire.handler = lambda _: httpx2.Response(
        200, content=trickle(), headers={"content-type": "application/pdf"}
    )
    with wire.fetcher() as fetcher, pytest.raises(FetchRefusedError, match="deadline"):
        fetcher.pdf("2501.01234")
    assert af.BODY_DEADLINE_S == 300.0 and len(sent) == 4


# ---------------------------------------------------------------------------
# Retries: a busy, throttled or silent arXiv is retried with backoff
# ---------------------------------------------------------------------------


def _sequence(*answers: httpx2.Response | Exception) -> Handler:
    """Answer each request with the next item; the last one repeats."""
    queue = list(answers)

    def handler(request: httpx2.Request) -> httpx2.Response:
        answer = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(answer, Exception):
            raise answer
        return answer

    return handler


def _ok() -> httpx2.Response:
    return httpx2.Response(
        200, content=feed(("2510.01234v1", "T", "S")), headers={"content-type": ATOM}
    )


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_a_busy_answer_is_retried_with_growing_backoff(status: int) -> None:
    wire = Wire(_sequence(httpx2.Response(status), httpx2.Response(status), _ok()))
    with wire.fetcher() as fetcher:
        entries = fetcher.search("cat:cs.PF", start=0, max_results=1)
    assert [e.arxiv_id for e in entries] == ["2510.01234v1"]
    assert len(wire.requests) == 3
    gaps = [b - a for a, b in zip(wire.sent_at, wire.sent_at[1:], strict=False)]
    assert gaps[0] >= af.RETRY_BACKOFF_S
    assert gaps[1] >= 2 * af.RETRY_BACKOFF_S


def test_a_timeout_is_retried() -> None:
    def slow(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("slow", request=request)

    wire = Wire(lambda r: _ok() if len(wire.requests) > 1 else slow(r))
    with wire.fetcher() as fetcher:
        assert fetcher.search("cat:cs.PF", start=0, max_results=1)
    assert len(wire.requests) == 2


def test_retry_after_is_honoured_and_capped() -> None:
    wire = Wire(
        _sequence(
            httpx2.Response(429, headers={"retry-after": "20"}),
            httpx2.Response(429, headers={"retry-after": "100000"}),
            _ok(),
        )
    )
    with wire.fetcher() as fetcher:
        fetcher.search("cat:cs.PF", start=0, max_results=1)
    gaps = [b - a for a, b in zip(wire.sent_at, wire.sent_at[1:], strict=False)]
    assert gaps[0] >= 20
    assert af.RETRY_AFTER_MAX_S <= gaps[1] <= af.RETRY_AFTER_MAX_S + MIN_SPACING_S


def test_retries_stop_after_the_limit_with_the_last_status() -> None:
    wire = Wire(lambda _: httpx2.Response(503, content=b"busy"))
    with wire.fetcher() as fetcher, pytest.raises(FetchError) as caught:
        fetcher.search("cat:cs.PF", start=0, max_results=1)
    assert caught.value.status == 503
    assert len(wire.requests) == 1 + af.RETRIES
    assert "after 4 attempts" in str(caught.value)


@pytest.mark.parametrize("status", [400, 403, 404])
def test_a_client_error_is_not_retried(status: int) -> None:
    wire = Wire(lambda _: httpx2.Response(status))
    with wire.fetcher() as fetcher, pytest.raises(FetchError) as caught:
        fetcher.search("cat:cs.PF", start=0, max_results=1)
    assert caught.value.status == status and len(wire.requests) == 1


def test_a_refusal_is_never_retried() -> None:
    wire = Wire(lambda _: httpx2.Response(200, content=b"<x/>"))
    with wire.fetcher() as fetcher, pytest.raises(FetchRefusedError):
        fetcher.pdf("2501.01234")
    assert len(wire.requests) == 1


def test_the_read_timeout_suits_a_slow_sorted_search() -> None:
    fetcher = ArxivFetcher()
    try:
        timeout = fetcher.client.timeout
        assert timeout.read == af.TIMEOUT_S == 90.0 and timeout.connect == 10.0
    finally:
        fetcher.close()


def test_recent_asks_for_pages_of_fifty() -> None:
    wire = Wire(_atom(feed()))
    with wire.fetcher() as fetcher:
        recent(fetcher, {"cs.PF": 120})
    sizes = [parse_qs(urlsplit(str(r.url)).query)["max_results"] for r in wire.requests]
    assert sizes == [["50"]]
