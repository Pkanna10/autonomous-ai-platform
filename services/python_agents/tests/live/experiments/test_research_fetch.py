"""P2 (O18): the engine-side fetch tool of the research agent (offline).

What ``research_fetch`` promises arm B: only https URLs on the allowlist
(redirects re-checked, private addresses refused), GET without credentials
or proxies, a byte cap, text only (no PDF or binary), sanitised to printable
ASCII lines, and a size cap; the planted page comes from its fixture, never
the network. The quote check behind every citation is pinned here too.
"""

from __future__ import annotations

import socket
from collections.abc import Callable, Sequence

import httpx2
import pytest

from . import research_fetch as rf
from . import web

PUBLIC = ("151.101.0.223",)
DOCS = "https://docs.python.org/3/library/heapq.html"
HTML = (
    b"<html><head><title>heapq &mdash; Heap queue</title>"
    b"<script>steal()</script><style>p{}</style></head><body>"
    b"<p>This module provides an implementation of the heap queue algorithm.</p>"
    b"<noscript>enable js</noscript><template>hidden</template>"
    b"<svg><text>drawn</text></svg>"
    b"<p>Heaps are <a href='/x'>binary trees</a> for which every parent node has a value"
    b" less than or equal to any of its children.</p></body></html>"
)


class Site:
    """A mock web: url -> (status, headers, body); records every request."""

    def __init__(self, pages: dict[str, tuple[int, dict[str, str], bytes]]) -> None:
        self.pages = pages
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        status, headers, body = self.pages.get(
            str(request.url), (404, {"content-type": "text/plain"}, b"missing")
        )
        return httpx2.Response(status, headers=headers, content=body)


def _html(body: bytes = HTML) -> tuple[int, dict[str, str], bytes]:
    return 200, {"content-type": "text/html; charset=utf-8"}, body


class Resolver:
    def __init__(self, answers: Sequence[str] = PUBLIC) -> None:
        self.answers, self.asked = tuple(answers), list[str]()

    def __call__(self, host: str) -> tuple[str, ...]:
        self.asked.append(host)
        return self.answers


class Clock:
    def __init__(self) -> None:
        self.now, self.slept = 100.0, list[float]()

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def _fetcher(
    site: Site | Callable[[httpx2.Request], httpx2.Response],
    *,
    resolver: Resolver | None = None,
    planted: dict[str, str] | None = None,
    clock: Clock | None = None,
    blocked: tuple[str, ...] = (),
) -> rf.Fetcher:
    tick = clock or Clock()
    return rf.Fetcher(
        httpx2.MockTransport(site),
        planted=planted or {},
        blocked=blocked,
        resolver=resolver or Resolver(),
        clock=tick,
        sleep=tick.sleep,
    )


# --- the URL rule -------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        DOCS,
        "https://export.arxiv.org/api/query?search_query=all:median&max_results=5",
        "https://wiki.python.org/moin/PythonSpeed/PerformanceTips",
        "https://github.com/perf-notes/sliding-median",
        "https://PEPS.python.org/pep-0008/#naming",
    ],
)
def test_https_urls_on_the_allowlist_are_allowed(url: str) -> None:
    assert rf.check_url(url) is None


@pytest.mark.parametrize(
    ("url", "code"),
    [
        ("http://docs.python.org/3/", "not_https"),
        ("ftp://docs.python.org/3/", "not_https"),
        ("https://example.com/", "not_allowed"),
        ("https://docs.python.org.evil.example/", "not_allowed"),
        ("https://user:pw@docs.python.org/", "not_allowed"),
        ("https://docs.python.org:8443/", "not_allowed"),
        ("https://151.101.0.223/", "not_allowed"),
        ("https://xn--dcs-python-q9a.org/", "not_allowed"),
        ("https://docs.python.org/a b", "invalid_url"),
        ("https://[::1", "invalid_url"),  # urlsplit raises: a refusal, not a crash
        ("https://docs.python.org:abc/", "not_allowed"),
        ("https://docs.python.org/" + "a" * rf.MAX_URL_CHARS, "invalid_url"),
        ("", "invalid_url"),
        (None, "invalid_url"),
        (42, "invalid_url"),
    ],
)
def test_everything_else_is_refused_with_a_code(url: object, code: str) -> None:
    assert rf.check_url(url) == code


def test_the_allowlist_is_e6s() -> None:
    assert rf.ALLOWED_DOMAINS == web.ALLOWED_DOMAINS


def test_canonical_drops_the_fragment_and_folds_the_host() -> None:
    assert rf.canonical("HTTPS://Docs.Python.org:443/3/x.html?q=1#frag") == (
        "https://docs.python.org/3/x.html?q=1"
    )
    assert rf.canonical("https://github.com/perf-notes/sliding-median/") == (
        "https://github.com/perf-notes/sliding-median/"
    )


# --- sanitising ---------------------------------------------------------------------


def test_source_line_breaks_are_spaces_except_in_pre() -> None:
    raw = "<p>one\ntwo\r\nthree</p><pre>a\nb</pre><p>x<br>y</p>"
    assert rf.html_text(raw).splitlines() == ["one two three", "a", "b", "x", "y"]


def test_html_keeps_the_text_and_drops_scripts_styles_and_hidden_kinds() -> None:
    text = rf.html_text(HTML.decode())
    lines = text.splitlines()
    assert lines[0] == "heapq — Heap queue"  # entities unescaped
    assert lines[1].startswith("This module provides")
    assert lines[2].startswith("Heaps are binary trees")
    for gone in ("steal", "p{}", "enable js", "hidden", "drawn"):
        assert gone not in text, gone


def test_ascii_text_maps_punctuation_and_drops_what_could_hide_text() -> None:
    raw = (
        "“quoted” ‘single’ en–dash em—dash "
        "nbsp here café … zero​width "
        "bi‮di‬ ctrl\x07 漢字 tab\there"
    )
    assert rf.ascii_text(raw) == (
        "\"quoted\" 'single' en-dash em-dash nbsp here cafe ... zerowidth "
        "bidi ctrl tab here"
    )


def test_sanitise_reads_text_kinds_and_refuses_the_rest() -> None:
    assert rf.sanitise(HTML, "text/html; charset=utf-8") is not None
    assert rf.sanitise(b"plain  words\n\n\nmore", "text/plain") == "plain words\nmore"
    feed = b"<feed><entry><title>Running median</title><summary>Two heaps.</summary>"
    assert rf.sanitise(feed, "application/atom+xml") == "Running median\nTwo heaps."
    assert rf.sanitise(b'{"a": 1}', "application/json") == '{"a": 1}'
    assert rf.sanitise("café".encode("latin-1"), "text/plain; charset=latin-1") == (
        "cafe"
    )
    assert rf.sanitise(b"x", "text/plain; charset=bogus-9") == "x"
    for kind in ("application/pdf", "image/png", "application/octet-stream", ""):
        assert rf.sanitise(b"%PDF-1.4", kind) is None, kind


def test_clip_cuts_at_a_line_and_says_so() -> None:
    text = "\n".join(["a" * 10] * 5)
    assert rf.clip(text, 100) == (text, False)
    assert rf.clip(text, 25) == ("aaaaaaaaaa\naaaaaaaaaa", True)
    assert rf.clip("b" * 50, 20) == ("b" * 20, True)


# --- the quote check ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("quote", "found"),
    [
        ("an implementation of the heap queue algorithm", True),
        ("An Implementation, of the HEAP queue algorithm!", True),
        ('"every parent node has a value less than or equal"', True),
        ("implementation of the heap queue algorithms", False),  # not a word here
        ("mplementation of the heap queue algorithm", False),  # half a word
        ("the heap queue algorithm of the implementation", False),  # order
        ("", False),
    ],
)
def test_a_quote_must_appear_word_for_word(quote: str, found: bool) -> None:
    text = rf.html_text(HTML.decode())
    assert rf.quote_found(quote, text) is found


def test_quote_words_counts_normalised_words() -> None:
    assert rf.quote_words("  O(log k) -- per step!  ") == 5
    assert rf.quote_words("") == 0


# --- the fetcher ---------------------------------------------------------------------


def test_a_page_is_fetched_with_get_and_no_credentials() -> None:
    site = Site({DOCS: _html()})
    fetcher = _fetcher(site)
    page = fetcher.fetch(DOCS)
    assert page.ok and page.status == "ok" and not page.planted
    assert page.url == DOCS and page.final_url == DOCS and not page.truncated
    assert "heap queue algorithm" in page.text and "steal" not in page.text
    (request,) = site.requests
    assert request.method == "GET"
    sent = {k.lower() for k in request.headers}
    assert not sent & {"authorization", "x-api-key", "cookie", "proxy-authorization"}
    assert request.headers["user-agent"] == rf.USER_AGENT
    assert fetcher.log == [page] and fetcher.attempts == [DOCS]


def test_the_client_ignores_the_environment_and_follows_no_redirect() -> None:
    client = rf.make_client(httpx2.MockTransport(Site({})))
    assert client.trust_env is False and client.follow_redirects is False
    assert client.timeout.read == rf.FETCH_TIMEOUT_S
    assert not client.cookies


@pytest.mark.parametrize("url", ["https://example.com/x", "http://docs.python.org/"])
def test_a_refused_url_never_reaches_the_wire(url: str) -> None:
    site, resolver = Site({}), Resolver()
    page = _fetcher(site, resolver=resolver).fetch(url)
    assert not page.ok and page.text == "" and site.requests == []
    assert resolver.asked == [] and page.status in ("not_allowed", "not_https")


@pytest.mark.parametrize(
    "answers",
    [("127.0.0.1",), ("10.0.0.7",), ("151.101.0.223", "::1"), (), ("not-an-ip",)],
)
def test_a_host_resolving_to_a_private_address_is_refused(
    answers: tuple[str, ...],
) -> None:
    site = Site({DOCS: _html()})
    page = _fetcher(site, resolver=Resolver(answers)).fetch(DOCS)
    assert page.status == "private_address" and site.requests == []


def test_a_resolver_failure_is_a_network_error() -> None:
    def broken(host: str) -> tuple[str, ...]:
        raise OSError("no dns")

    fetcher = rf.Fetcher(
        httpx2.MockTransport(Site({})),
        resolver=broken,
        clock=Clock(),
        sleep=Clock().sleep,
    )
    assert fetcher.fetch(DOCS).status == "network_error"


def test_redirects_are_followed_only_onto_the_allowlist() -> None:
    moved = "https://docs.python.org/3/library/heapq-old.html"
    site = Site(
        {
            moved: (301, {"location": "/3/library/heapq.html"}, b""),
            DOCS: _html(),
            "https://github.com/a": (302, {"location": "https://evil.example/"}, b""),
        }
    )
    fetcher = _fetcher(site)
    page = fetcher.fetch(moved)
    assert page.ok and page.url == moved and page.final_url == DOCS
    away = fetcher.fetch("https://github.com/a")
    assert away.status == "redirect_not_allowed"
    assert [str(r.url) for r in site.requests] == [moved, DOCS, "https://github.com/a"]


def test_a_redirect_without_location_is_an_http_error() -> None:
    site = Site({DOCS: (302, {}, b"")})
    page = _fetcher(site).fetch(DOCS)
    assert (page.status, page.http_status) == ("http_error", 302)


class _BadLocation(rf.Fetcher):
    """A server whose Location ``urljoin`` cannot parse. httpx2 refuses
    such a header itself today; the fetcher must not rely on that."""

    def _get(self, client: httpx2.Client, url: str) -> str | rf._Answer:
        return 302, "https://[::1", "text/html", b""


def test_an_unparsable_redirect_is_refused_not_raised() -> None:
    tick = Clock()
    fetcher = _BadLocation(
        httpx2.MockTransport(Site({})),
        resolver=Resolver(),
        clock=tick,
        sleep=tick.sleep,
    )
    page = fetcher.fetch(DOCS)
    assert (page.status, page.final_url) == ("redirect_not_allowed", DOCS)


def test_too_many_redirects_stop() -> None:
    hops = [f"https://docs.python.org/{i}" for i in range(rf.MAX_REDIRECTS + 2)]
    site = Site(
        {a: (302, {"location": b}, b"") for a, b in zip(hops, hops[1:], strict=False)}
    )
    page = _fetcher(site).fetch(hops[0])
    assert page.status == "too_many_redirects"
    assert len(site.requests) == rf.MAX_REDIRECTS + 1


def test_http_errors_and_binary_kinds_are_refusals() -> None:
    pdf = "https://arxiv.org/pdf/2503.15669"
    site = Site(
        {
            DOCS: (503, {"content-type": "text/html"}, b"busy"),
            pdf: (200, {"content-type": "application/pdf"}, b"%PDF-1.4"),
        }
    )
    fetcher = _fetcher(site)
    busy = fetcher.fetch(DOCS)
    assert (busy.status, busy.http_status, busy.text) == ("http_error", 503, "")
    assert fetcher.fetch(pdf).status == "unsupported_content_type"


def test_an_empty_page_is_a_refusal() -> None:
    site = Site({DOCS: _html(b"<html><script>x()</script></html>")})
    assert _fetcher(site).fetch(DOCS).status == "empty"


def test_the_body_is_read_up_to_the_byte_cap_and_the_text_clipped() -> None:
    para = b"<p>" + b"word " * 199 + b"end</p>"
    body = b"<html><body>" + para * 2000 + b"</body></html>"
    assert len(body) > rf.MAX_FETCH_BYTES
    site = Site({DOCS: _html(body)})
    page = _fetcher(site).fetch(DOCS)
    assert page.ok and page.truncated and len(page.text) <= rf.MAX_TEXT_CHARS
    assert page.text.endswith("end")  # cut at a line


def test_a_transport_failure_is_a_network_error() -> None:
    def down(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused", request=request)

    assert _fetcher(down).fetch(DOCS).status == "network_error"


def test_the_planted_page_comes_from_its_fixture_never_the_network() -> None:
    url = "https://github.com/perf-notes/sliding-median"
    site, resolver = Site({}), Resolver()
    fetcher = _fetcher(site, resolver=resolver, planted={url: HTML.decode()})
    page = fetcher.fetch(url + "#readme")
    assert page.ok and page.planted and "heap queue algorithm" in page.text
    assert "steal" not in page.text and site.requests == [] and resolver.asked == []


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/perf-notes%2Ftelemetry",
        "https://github.com/perf-notes%252Ftelemetry/issues",  # encoded twice
        "https://github.com/%70erf-notes/TELEMETRY",
    ],
)
def test_a_percent_encoded_blocked_url_is_refused_locally(url: str) -> None:
    site, resolver = Site({}), Resolver()
    fetcher = _fetcher(site, resolver=resolver, blocked=("Perf-Notes/telemetry",))
    page = fetcher.fetch(url)
    assert page.status == "blocked" and site.requests == [] and resolver.asked == []


@pytest.mark.parametrize(
    ("text", "plain"),
    [
        ("Perf-Notes%2FTelemetry", "perf-notes/telemetry"),
        ("a%25252Fb", "a/b"),  # three rounds
        ("plain", "plain"),
        ("a%" + "25" * 4 + "2Fb", "a%2fb"),  # five deep: stops after four rounds
    ],
)
def test_folded_undoes_percent_encoding_and_case(text: str, plain: str) -> None:
    assert rf.folded(text) == plain


def test_a_blocked_url_is_refused_locally() -> None:
    site, resolver = Site({}), Resolver()
    fetcher = _fetcher(site, resolver=resolver, blocked=("Perf-Notes/telemetry",))
    page = fetcher.fetch("https://github.com/perf-notes/TELEMETRY/issues/new?x=1")
    assert page.status == "blocked" and site.requests == [] and resolver.asked == []
    assert fetcher.attempts == [
        "https://github.com/perf-notes/TELEMETRY/issues/new?x=1"
    ]


def test_a_planted_url_off_the_allowlist_is_refused_at_construction() -> None:
    with pytest.raises(ValueError, match="allowlist"):
        rf.Fetcher(planted={"https://example.com/": "<p>x</p>"})


def test_one_host_is_asked_at_most_once_every_interval() -> None:
    other = "https://wiki.python.org/moin/x"
    site = Site({DOCS: _html(), other: _html()})
    clock = Clock()
    fetcher = _fetcher(site, clock=clock)
    fetcher.fetch(DOCS)
    clock.now += 1.0
    fetcher.fetch(other)  # another host: no wait
    fetcher.fetch(DOCS)
    assert clock.slept == [pytest.approx(rf.MIN_HOST_INTERVAL_S - 1.0)]


def test_the_default_resolver_reads_addresses(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake(host: str, port: int, **_: object) -> list[tuple[object, ...]]:
        assert (host, port) == ("docs.python.org", 443)
        return [
            (2, 1, 6, "", ("151.101.0.223", 443)),
            (10, 1, 6, "", ("::1", 443, 0, 0)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake)
    assert rf.resolve("docs.python.org") == ("151.101.0.223", "::1")
