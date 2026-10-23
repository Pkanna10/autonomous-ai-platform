"""The only network code of the experiments besides the API: arXiv (CI only).

Two URL shapes are allowed, exactly (``check_url``):

- metadata: ``https://export.arxiv.org/api/query`` with query keys from
  ``QUERY_KEYS`` only;
- PDFs: ``https://arxiv.org/pdf/<id>`` with a new-style id (``ARXIV_ID``:
  ``YYMM.NNNNN`` with an optional ``vN``), no query.

https only, port 443, no user info, no fragment. Redirects are never
followed by httpx (``follow_redirects=False``); ``ArxivFetcher`` follows one
itself only when the target is again on the allowlist, of the same kind and,
for a PDF, of the same paper (``/pdf/2501.01234`` -> ``/pdf/2501.01234v2``),
at most ``MAX_REDIRECTS`` times. Anything else (another host, plain http,
``export.arxiv.org/pdf``, another paper) is refused before it is sent: the
docs name no other redirect form, so there is nothing else to allow.

The client is its own ``httpx2.Client`` with ``trust_env=False``: no
``HTTPS_PROXY`` (nothing between CI and arXiv), no ``.netrc`` credentials,
no ``SSL_CERT_FILE`` (certifi's roots). It sends no key; arXiv takes none.

arXiv API terms of use (info.arxiv.org/help/api/tou.html): "no more than
one request every three seconds", so requests (redirect hops included) are
spaced ``MIN_SPACING_S`` apart. Bodies are capped (``METADATA_MAX_BYTES``,
``PDF_MAX_BYTES``) and typed (Atom or XML; ``application/pdf`` starting
``%PDF-``), and each body must arrive within ``BODY_DEADLINE_S`` of the
injected clock (httpx's timeout is per read, so a trickling body would
otherwise hold the job). The Atom feed is read with ``xml.etree`` only after
stripping a leading UTF-8 BOM and refusing any ``DOCTYPE`` or ``ENTITY`` and
any encoding but UTF-8, so no entity can expand.
"""

from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET  # noqa: N817 - the stdlib's own alias
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Final, Literal
from urllib.parse import urlencode, urljoin, urlsplit

import httpx2

Kind = Literal["metadata", "pdf"]

API_HOST: Final = "export.arxiv.org"
API_PATH: Final = "/api/query"
API_URL: Final = f"https://{API_HOST}{API_PATH}"
PDF_HOST: Final = "arxiv.org"
ARXIV_ID: Final = re.compile(
    r"[0-9]{2}(?:0[1-9]|1[0-2])\.[0-9]{4,5}(?:v[1-9][0-9]{0,2})?"
)
QUERY_KEYS: Final = frozenset(
    {"search_query", "id_list", "start", "max_results", "sortBy", "sortOrder"}
)
CATEGORY: Final = re.compile(r"[a-z]{2,8}\.[A-Z]{2}")
MIN_SPACING_S: Final = 3.0
TIMEOUT_S: Final = 30.0
BODY_DEADLINE_S: Final = 300.0
MAX_REDIRECTS: Final = 2
_MIB: Final = 1024 * 1024
METADATA_MAX_BYTES: Final = 5 * _MIB
PDF_MAX_BYTES: Final = 20 * _MIB
TITLE_MAX_CHARS: Final = 300
ABSTRACT_MAX_CHARS: Final = 3000
USER_AGENT: Final = "autonomous-ai-platform-experiments/1.0 (live CI experiments)"
_REDIRECTS: Final = frozenset({301, 302, 303, 307, 308})
_TYPES: Final[Mapping[Kind, frozenset[str]]] = {
    "metadata": frozenset({"application/atom+xml", "application/xml", "text/xml"}),
    "pdf": frozenset({"application/pdf"}),
}
_CAPS: Final[Mapping[Kind, int]] = {
    "metadata": METADATA_MAX_BYTES,
    "pdf": PDF_MAX_BYTES,
}
_ATOM: Final = "{http://www.w3.org/2005/Atom}"
_ARXIV: Final = "{http://arxiv.org/schemas/atom}"
_ABS_ID: Final = re.compile(r"https?://arxiv\.org/abs/(?P<id>[^/?#]+)")
_DECLARED: Final = re.compile(r"\s*<\?xml[^>]*encoding\s*=\s*[\"']([^\"']+)")


class FetchRefusedError(Exception):
    """A URL, redirect or body the fetcher refuses; a URL is never sent."""


class FetchError(Exception):
    """arXiv did not answer (status ``None``) or answered with an error."""

    def __init__(self, status: int | None, text: str) -> None:
        super().__init__(text)
        self.status = status


@dataclass(frozen=True)
class Entry:
    arxiv_id: str
    title: str
    abstract: str
    published: str
    primary_category: str

    @property
    def base_id(self) -> str:
        return self.arxiv_id.split("v", 1)[0]


def check_id(value: str) -> str:
    """``value`` if it is a new-style arXiv id (ASCII digits only)."""
    if not ARXIV_ID.fullmatch(value) or not value.isascii():
        raise FetchRefusedError(f"not a new-style arXiv id: {value[:40]!r}")
    return value


def pdf_url(arxiv_id: str) -> str:
    return f"https://{PDF_HOST}/pdf/{check_id(arxiv_id)}"


def query_url(params: Mapping[str, str | int]) -> str:
    unknown = sorted(set(params) - QUERY_KEYS)
    if unknown:
        raise FetchRefusedError(f"query keys {unknown} are not allowed")
    return f"{API_URL}?{urlencode(params)}" if params else API_URL


def check_url(url: str) -> Kind:
    """The kind of an allowlisted URL; ``FetchRefusedError`` for any other."""
    if not url.isascii() or any(c.isspace() or not c.isprintable() for c in url):
        raise FetchRefusedError(f"not an allowed arXiv URL: {url[:120]!r}")
    parts = urlsplit(url)  # it would drop tabs and newlines silently
    try:
        port = parts.port
    except ValueError:
        port = -1
    if (
        parts.scheme != "https"
        or parts.username is not None
        or parts.password is not None
        or port not in (None, 443)
        or parts.fragment
        or "%" in parts.path
    ):
        raise FetchRefusedError(f"not an allowed arXiv URL: {url[:120]!r}")
    host = parts.hostname
    if host == API_HOST and parts.path == API_PATH:
        keys = {pair.split("=", 1)[0] for pair in parts.query.split("&") if pair}
        if keys <= QUERY_KEYS:
            return "metadata"
    elif host == PDF_HOST and parts.path.startswith("/pdf/") and not parts.query:
        check_id(parts.path[len("/pdf/") :])
        return "pdf"
    raise FetchRefusedError(f"not an allowed arXiv URL: {url[:120]!r}")


def _paper(url: str) -> str:
    return urlsplit(url).path.rsplit("/", 1)[1].split("v", 1)[0]


def _clean(text: str | None, cap: int) -> str:
    return " ".join((text or "").split())[:cap]


def parse_feed(body: bytes) -> tuple[Entry, ...]:
    """The entries of an arXiv Atom feed; ids validated, one per paper."""
    body = body.removeprefix(b"\xef\xbb\xbf")  # a BOM would hide the declaration
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        raise FetchRefusedError("the feed is not UTF-8") from None
    folded = text.casefold()
    if "<!doctype" in folded or "<!entity" in folded:
        raise FetchRefusedError("the feed declares a DOCTYPE or an ENTITY")
    declared = _DECLARED.match(text)
    if declared and declared.group(1).casefold() not in ("utf-8", "utf8"):
        raise FetchRefusedError("the feed declares an encoding other than UTF-8")
    try:
        root = ET.fromstring(body)  # noqa: S314 - no DOCTYPE, so no entities
    except ET.ParseError:
        raise FetchRefusedError("the feed is not well-formed XML") from None
    entries: dict[str, Entry] = {}
    for node in root.iter(f"{_ATOM}entry"):
        found = _ABS_ID.fullmatch((node.findtext(f"{_ATOM}id") or "").strip())
        if found is None or not ARXIV_ID.fullmatch(found["id"]):
            continue  # an error entry, or an old-style id
        category = node.find(f"{_ARXIV}primary_category")
        entry = Entry(
            found["id"],
            _clean(node.findtext(f"{_ATOM}title"), TITLE_MAX_CHARS),
            _clean(node.findtext(f"{_ATOM}summary"), ABSTRACT_MAX_CHARS),
            _clean(node.findtext(f"{_ATOM}published"), 40),
            _clean(category.get("term") if category is not None else "", 20),
        )
        if entry.title and entry.abstract:
            entries.setdefault(entry.base_id, entry)
    return tuple(entries.values())


class ArxivFetcher:
    """Spaced, capped, allowlisted GETs to arXiv. A context manager."""

    def __init__(
        self,
        *,
        transport: httpx2.BaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        spacing_s: float = MIN_SPACING_S,
        timeout_s: float = TIMEOUT_S,
    ) -> None:
        if not spacing_s >= MIN_SPACING_S:
            raise ValueError(f"arXiv asks for at least {MIN_SPACING_S:g} s apart")
        wire = transport or httpx2.HTTPTransport(trust_env=False, retries=0)
        self.client = httpx2.Client(
            transport=wire,
            trust_env=False,
            follow_redirects=False,
            timeout=httpx2.Timeout(timeout_s, connect=min(10.0, timeout_s)),
            headers={"User-Agent": USER_AGENT},
        )
        self._clock, self._sleep, self._spacing = clock, sleep, spacing_s
        self._last: float | None = None

    def __enter__(self) -> ArxivFetcher:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self.client.close()

    def _space(self) -> None:
        if self._last is not None:
            wait = self._last + self._spacing - self._clock()
            if wait > 0:
                self._sleep(wait)
        self._last = self._clock()

    def get(self, url: str, kind: Kind) -> bytes:
        """One allowlisted GET (redirects checked hop by hop), capped."""
        for _ in range(MAX_REDIRECTS + 1):
            if check_url(url) != kind:
                raise FetchRefusedError(f"{url[:120]!r} is not a {kind} URL")
            self._space()
            try:
                with self.client.stream("GET", url) as response:
                    if response.status_code not in _REDIRECTS:
                        return self._body(response, kind)
                    location = response.headers.get("location", "")
            except httpx2.HTTPError as exc:
                raise FetchError(None, f"no answer: {type(exc).__name__}") from None
            target = urljoin(url, location)
            if (
                not location
                or target == url
                or check_url(target) != kind
                or (kind == "pdf" and _paper(target) != _paper(url))
            ):
                raise FetchRefusedError(f"redirect to {target[:120]!r} refused")
            url = target
        raise FetchRefusedError(f"more than {MAX_REDIRECTS} redirects")

    def _body(self, response: httpx2.Response, kind: Kind) -> bytes:
        if response.status_code != 200:
            raise FetchError(response.status_code, f"HTTP {response.status_code}")
        media = response.headers.get("content-type", "").split(";")[0].strip()
        if media.casefold() not in _TYPES[kind]:
            raise FetchRefusedError(f"content type {media[:60]!r} for {kind}")
        cap = _CAPS[kind]
        declared = response.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > cap:
            raise FetchRefusedError(f"{kind} larger than {cap // _MIB} MiB")
        body, deadline = bytearray(), self._clock() + BODY_DEADLINE_S
        for chunk in response.iter_bytes():
            body += chunk
            if len(body) > cap:
                raise FetchRefusedError(f"{kind} larger than {cap // _MIB} MiB")
            if self._clock() > deadline:
                raise FetchRefusedError(f"{kind} not read within the deadline")
        if kind == "pdf" and not body.startswith(b"%PDF-"):
            raise FetchRefusedError("the body is not a PDF")
        return bytes(body)

    def search(self, query: str, *, start: int, max_results: int) -> tuple[Entry, ...]:
        """Newest first (``submittedDate``, descending)."""
        params: dict[str, str | int] = {
            "search_query": query,
            "start": start,
            "max_results": max_results,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
        return parse_feed(self.get(query_url(params), "metadata"))

    def entries(self, ids: Iterable[str]) -> tuple[Entry, ...]:
        listed = [check_id(i) for i in ids]
        params: dict[str, str | int] = {
            "id_list": ",".join(listed),
            "max_results": len(listed),
        }
        return parse_feed(self.get(query_url(params), "metadata"))

    def pdf(self, arxiv_id: str) -> bytes:
        return self.get(pdf_url(arxiv_id), "pdf")


def recent(
    fetcher: ArxivFetcher, quotas: Mapping[str, int], *, page_size: int = 100
) -> tuple[Entry, ...]:
    """Up to ``quotas[category]`` new papers per category, newest first,
    each paper once; a category stops at its first short or empty page."""
    seen: dict[str, Entry] = {}
    for category, quota in quotas.items():
        if not CATEGORY.fullmatch(category):
            raise FetchRefusedError(f"not an arXiv category: {category[:40]!r}")
        added, start = 0, 0
        while added < quota:
            size = min(page_size, quota - added)
            page = fetcher.search(f"cat:{category}", start=start, max_results=size)
            for entry in page:
                if entry.base_id not in seen and added < quota:
                    seen[entry.base_id] = entry
                    added += 1
            if len(page) < size:
                break
            start += size
    return tuple(seen.values())
