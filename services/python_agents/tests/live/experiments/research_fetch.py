"""P2 (O18): the research agent's engine-side fetch tool (live, CI only).

Arm B of pilot P2 (``research_agent``) never lets the model reach the web
itself: the model names a URL, and ``Fetcher.fetch`` (engine code) decides
whether to fetch it, fetches it, and turns it into plain text the loop then
fences. What it promises:

- **Only the allowlist, only https.** ``check_url``: a printable https URL
  of at most ``MAX_URL_CHARS`` whose host is one of ``ALLOWED_DOMAINS`` (E6's
  list, ``web.in_allowlist``: no userinfo, odd ports, IP literals or
  punycode). Every redirect hop is checked again (at most ``MAX_REDIRECTS``),
  and a host whose addresses are not all global (loopback, private,
  link-local and the like) is refused before anything is sent. The address
  check and the connection resolve separately (a rebinding window), which is
  acceptable for five public, institution-run domains.
- **No credentials, no ambient configuration.** One GET per hop through a
  fresh client with ``trust_env=False`` (no proxy variables, no ``.netrc``),
  no redirect followed by the library, no cookie kept between hops, and no
  header but ``USER_AGENT`` and ``ACCEPT``; never the API key, which lives
  in another client entirely.
- **Bounded.** ``FETCH_TIMEOUT_S`` a hop, at most ``MAX_FETCH_BYTES`` read,
  the text cut at a line to ``MAX_TEXT_CHARS``, one request a host every
  ``MIN_HOST_INTERVAL_S`` (arXiv's API asks for one every three seconds).
- **Text only.** HTML, XML feeds, plain text and JSON (``TEXT_KINDS``);
  PDFs and anything binary are refused. ``sanitise`` drops script, style and
  other non-text elements, unescapes entities, and reduces the text to
  printable ASCII lines (``ascii_text``: typographic punctuation mapped,
  accents stripped, zero-width, bidi and control characters and other
  scripts dropped), so nothing invisible reaches the model. Text hidden by
  CSS is not detected: it reaches the model as visible text would.
- **The planted page** of an injection run is served from its fixture,
  sanitised like any page, with no network and no resolution; a URL holding
  one of its canaries (``blocked``) is refused locally, so an instruction the
  model follows never reaches the host it names.

``quote_found`` is the citation check: a quote counts only when its words,
in order and whole, appear in the text the model was shown (case and
punctuation ignored).
"""

from __future__ import annotations

import ipaddress
import math
import re
import socket
import time
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from html.parser import HTMLParser
from types import MappingProxyType
from typing import Final
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

import httpx2

from .web import ALLOWED_DOMAINS, in_allowlist

__all__ = ["ALLOWED_DOMAINS"]

MAX_URL_CHARS: Final = 2_000
FETCH_TIMEOUT_S: Final = 15.0
MAX_FETCH_BYTES: Final = 1_000_000
MAX_TEXT_CHARS: Final = 12_000
MAX_REDIRECTS: Final = 3
MIN_HOST_INTERVAL_S: Final = 3.0
USER_AGENT: Final = "autonomous-ai-platform-research-pilot/1 (P2 experiment)"
ACCEPT: Final = "text/html, application/xhtml+xml, text/plain, application/xml;q=0.9"
TEXT_KINDS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "text/html": "html",
        "application/xhtml+xml": "html",
        "application/xml": "html",
        "text/xml": "html",
        "application/atom+xml": "html",
        "application/rss+xml": "html",
        "text/plain": "text",
        "text/markdown": "text",
        "application/json": "text",
    }
)
_SKIPPED: Final = frozenset(
    {"script", "style", "noscript", "template", "svg", "iframe", "object", "math"}
)
_INLINE: Final = frozenset(
    {
        "a", "abbr", "b", "bdi", "bdo", "big", "cite", "code", "data", "dfn",
        "em", "font", "i", "kbd", "mark", "q", "s", "samp", "small", "span",
        "strong", "sub", "sup", "time", "tt", "u", "var", "wbr",
    }
)  # fmt: skip
_ASCII_MAP: Final = str.maketrans(
    {
        "‘": "'", "’": "'", "‚": "'", "‛": "'",
        "“": '"', "”": '"', "„": '"', "‟": '"',
        "‐": "-", "‑": "-", "‒": "-", "–": "-",
        "—": "-", "―": "-", "−": "-", "…": "...",
        " ": " ", " ": " ", " ": " ", "\t": " ",
    }
)  # fmt: skip
_WORDS: Final = re.compile(r"[a-z0-9]+")
_REDIRECTS: Final = frozenset({301, 302, 303, 307, 308})

Resolver = Callable[[str], tuple[str, ...]]


def check_url(url: object) -> str | None:
    """``None`` for a URL the fetcher may open, else why not."""
    if not isinstance(url, str) or not url or len(url) > MAX_URL_CHARS:
        return "invalid_url"
    if any(c.isspace() or not c.isprintable() for c in url) or "\\" in url:
        return "invalid_url"
    try:
        scheme = urlsplit(url).scheme.lower()
    except ValueError:  # e.g. an unclosed IPv6 bracket: a refusal, not a crash
        return "invalid_url"
    if scheme != "https":
        return "not_https"
    return None if in_allowlist(url) else "not_allowed"


def folded(text: str) -> str:
    """``text`` as canaries are matched in: percent-encoding undone (nested
    encodings too, up to four rounds) and case folded."""
    for _ in range(4):
        plain = unquote(text)
        if plain == text:
            break
        text = plain
    return text.casefold()


def canonical(url: str) -> str:
    """The form a fetched page is known by: scheme and host folded, the
    default port and the fragment dropped, path and query kept as given."""
    parts = urlsplit(url)
    host = (parts.hostname or "").rstrip(".")
    netloc = host if parts.port in (None, 443) else f"{host}:{parts.port}"
    return urlunsplit((parts.scheme.lower(), netloc, parts.path, parts.query, ""))


class _Text(HTMLParser):
    """The text of an HTML or XML document, a line per block element."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skipping = self.pre = 0

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag in _SKIPPED:
            self.skipping += 1
        elif tag not in _INLINE:
            self.pre += tag == "pre"
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIPPED:
            self.skipping = max(0, self.skipping - 1)
        elif tag not in _INLINE:
            self.pre = max(0, self.pre - (tag == "pre"))
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        """Source line breaks are spaces, except inside ``pre``."""
        if not self.skipping:
            self.parts.append(data if self.pre else " ".join(data.splitlines()))


def _lines(text: str) -> str:
    """Whitespace collapsed within each line, blank lines dropped."""
    lines = (" ".join(line.split()) for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def html_text(raw: str) -> str:
    parser = _Text()
    parser.feed(raw)
    parser.close()
    return _lines("".join(parser.parts))


def ascii_text(text: str) -> str:
    """Printable ASCII lines: punctuation mapped, accents stripped, every
    other character (controls, zero-width, bidi, other scripts) dropped."""
    mapped = unicodedata.normalize("NFKD", text.translate(_ASCII_MAP))
    return _lines("".join(c for c in mapped if c == "\n" or " " <= c <= "~"))


def _kind(content_type: str) -> tuple[str | None, str]:
    media, _, params = content_type.partition(";")
    charset = "utf-8"
    for param in params.split(";"):
        key, _, value = param.partition("=")
        if key.strip().lower() == "charset" and value.strip():
            charset = value.strip().strip("\"'")
    return TEXT_KINDS.get(media.strip().lower()), charset


def sanitise(body: bytes, content_type: str) -> str | None:
    """The page as printable ASCII lines, or ``None`` for a kind not read."""
    kind, charset = _kind(content_type)
    if kind is None:
        return None
    try:
        raw = body.decode(charset, errors="replace")
    except LookupError:
        raw = body.decode("utf-8", errors="replace")
    return ascii_text(html_text(raw) if kind == "html" else raw)


def clip(text: str, limit: int) -> tuple[str, bool]:
    """At most ``limit`` characters, cut after the last whole line when
    there is one; and whether anything was cut."""
    if len(text) <= limit:
        return text, False
    head = text[:limit]
    cut = head.rfind("\n")
    return (head[:cut] if cut > 0 else head), True


def _normal(text: str) -> str:
    return " ".join(_WORDS.findall(text.casefold()))


def quote_words(quote: str) -> int:
    return len(_WORDS.findall(quote.casefold()))


def quote_found(quote: str, text: str) -> bool:
    """The quote's words, whole and in order, appear in ``text``."""
    words = _normal(quote)
    return bool(words) and f" {words} " in f" {_normal(text)} "


def resolve(host: str) -> tuple[str, ...]:
    """Every address ``host`` resolves to (the default resolver)."""
    found = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    return tuple(dict.fromkeys(str(entry[4][0]) for entry in found))


def _global(addresses: tuple[str, ...]) -> bool:
    try:
        return bool(addresses) and all(
            ipaddress.ip_address(a).is_global for a in addresses
        )
    except ValueError:
        return False


def make_client(transport: httpx2.BaseTransport | None) -> httpx2.Client:
    """A client that follows nothing and reads nothing from the environment."""
    return httpx2.Client(
        transport=transport,
        follow_redirects=False,
        trust_env=False,
        timeout=httpx2.Timeout(FETCH_TIMEOUT_S),
        headers={"User-Agent": USER_AGENT, "Accept": ACCEPT},
    )


@dataclass(frozen=True)
class Page:
    """One fetch: the URL asked for (canonical), ``ok`` or why not, the
    sanitised text, whether it was cut, the planted page or not, where it
    ended after redirects and the last HTTP status."""

    url: str
    status: str
    text: str = ""
    truncated: bool = False
    planted: bool = False
    final_url: str = ""
    http_status: int | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"


_Answer = tuple[int, str, str, bytes]  # status, Location, Content-Type, body


class Fetcher:
    """The fetch tool's engine side for one run. ``transport`` (``None``:
    the network), ``resolver`` and the clock are injected in tests; every
    ``fetch`` is logged, and ``attempts`` holds each URL as it was asked.
    ``planted`` maps a URL to its fixture HTML; ``blocked`` holds the text a
    URL must not contain (case ignored)."""

    def __init__(
        self,
        transport: httpx2.BaseTransport | None = None,
        *,
        planted: Mapping[str, str] | None = None,
        blocked: Sequence[str] = (),
        resolver: Resolver = resolve,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._planted: dict[str, str] = {}
        for url, html in (planted or {}).items():
            if check_url(url) is not None:
                raise ValueError(f"a planted page must be on the allowlist: {url!r}")
            self._planted[canonical(url)] = html
        self._blocked = tuple(folded(b) for b in blocked if b)
        self._transport, self._resolver = transport, resolver
        self._clock, self._sleep = clock, sleep
        self._last: dict[str, float] = {}
        self.log: list[Page] = []
        self.attempts: list[str] = []

    def fetch(self, url: str) -> Page:
        self.attempts.append(url)
        page = self._fetch(url)
        self.log.append(page)
        return page

    def _fetch(self, url: str) -> Page:
        refused = check_url(url)
        if refused is not None:
            return Page(url, refused)
        asked = current = canonical(url)
        if any(b in folded(asked) for b in self._blocked):
            return Page(asked, "blocked")
        if asked in self._planted:
            text = sanitise(self._planted[asked].encode(), "text/html") or ""
            return self._page(asked, asked, text, planted=True)
        with make_client(self._transport) as client:
            for hop in range(MAX_REDIRECTS + 1):
                if check_url(current) is not None:
                    return Page(asked, "redirect_not_allowed", final_url=current)
                answer = self._get(client, current)
                if isinstance(answer, str):
                    return Page(asked, answer, final_url=current)
                status, location, kind, body = answer
                if status in _REDIRECTS and location:
                    if hop == MAX_REDIRECTS:
                        return Page(asked, "too_many_redirects", final_url=current)
                    try:
                        current = canonical(urljoin(current, location))
                    except ValueError:
                        return Page(asked, "redirect_not_allowed", final_url=current)
                    continue
                if status != 200:
                    return Page(
                        asked, "http_error", final_url=current, http_status=status
                    )
                read = sanitise(body, kind)
                if read is None:
                    return Page(asked, "unsupported_content_type", final_url=current)
                return self._page(asked, current, read, planted=False)
        raise AssertionError("unreachable: the last hop returns")

    def _page(self, asked: str, final: str, text: str, *, planted: bool) -> Page:
        shown, cut = clip(text, MAX_TEXT_CHARS)
        if not shown:
            return Page(asked, "empty", final_url=final, planted=planted)
        return Page(asked, "ok", shown, cut, planted, final, None if planted else 200)

    def _get(self, client: httpx2.Client, url: str) -> str | _Answer:
        """One GET after the address check and the host's interval, the
        body read up to the byte cap; or why not."""
        host = urlsplit(url).hostname or ""
        try:
            addresses = tuple(self._resolver(host))
        except OSError:
            return "network_error"
        if not _global(addresses):
            return "private_address"
        wait = self._last.get(host, -math.inf) + MIN_HOST_INTERVAL_S - self._clock()
        if wait > 0:
            self._sleep(wait)
        self._last[host] = self._clock()
        client.cookies.clear()
        try:
            with client.stream("GET", url) as response:
                body = bytearray()
                for chunk in response.iter_bytes():
                    body += chunk[: MAX_FETCH_BYTES - len(body)]
                    if len(body) >= MAX_FETCH_BYTES:
                        break
                return (
                    response.status_code,
                    response.headers.get("location", ""),
                    response.headers.get("content-type", ""),
                    bytes(body),
                )
        except httpx2.HTTPError:
            return "network_error"
