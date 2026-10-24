"""Offline tests of the Step 3b package-acquisition probe (``acquire.py``
and dry runs of ``test_acquire_live.py``).

No network and no key: ``PackageIndex`` talks to ``FakeIndex`` (pypi.org
and api.osv.dev on a mock httpx wire), ``ExperimentClient`` to the
harness's ``FakeApi`` through its ``LiveRun`` wire; clocks and sleeps are
fakes. Upload times are fixed against ``NOW``.
"""

from __future__ import annotations

import inspect
import json
import math
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import httpx2
import pytest
from anthropic.types.beta import BetaMessage

from autonomous_ai_agents.clients.structured import Fence

from ..conftest import LiveRun
from ..oss import OSS_CORPUS
from . import acquire
from . import test_acquire_live as live_acq
from .acquire import (
    CHECKS,
    OSV_HOST,
    SONNET,
    SUGGEST_SCHEMA,
    SYSTEM,
    Assessment,
    Assessor,
    FetchError,
    FetchRefusedError,
    FileFacts,
    NearMiss,
    PackageIndex,
    Popular,
    canonical,
    check_name,
    check_url,
    choose_pin,
    licence,
    load_inputs,
    load_popular,
    near_miss,
    osa_distance,
    parse_json,
    read_suggestions,
    release_files,
    release_url,
    requirements,
    suggest_body,
    suggestion_summary,
    summarize,
    verdict,
    wheel_facts,
)
from .harness import Answer, ExperimentClient
from .recorder import ExperimentRecorder
from .test_harness import Clock, FakeApi, host_key
from .test_triage import DryStart

__all__ = ["host_key"]  # the harness's fixture: the host key over the placeholder

Json = dict[str, object]
NOW = datetime(2026, 10, 24, tzinfo=UTC)
OLD = "2025-01-01T00:00:00.000000Z"
FRESH = "2026-10-22T00:00:00.000000Z"
SHA = "a" * 64
POPULAR = Popular(
    "2026-10-24",
    frozenset({"numpy", "orjson", "toolz", "sortedcontainers", "rapidfuzz", "six"}),
)


def file(
    filename: str, *, uploaded: str = OLD, sha: str | None = SHA, yanked: bool = False
) -> Json:
    kind = "sdist" if filename.endswith(".tar.gz") else "bdist_wheel"
    return {
        "filename": filename,
        "packagetype": kind,
        "yanked": yanked,
        "upload_time_iso_8601": uploaded,
        "digests": {"sha256": sha} if sha is not None else {},
    }


LINUX = "cp311-cp311-manylinux_2_17_x86_64.manylinux2014_x86_64"
MAC = "cp311-cp311-macosx_11_0_arm64"


def files(name: str, version: str, *, uploaded: str = OLD) -> list[Json]:
    stem = name.replace("-", "_")
    return [
        file(f"{stem}-{version}-{LINUX}.whl", uploaded=uploaded),
        file(f"{stem}-{version}-{MAC}.whl", uploaded=uploaded),
        file(f"{stem}-{version}.tar.gz", uploaded=uploaded),
    ]


def project(
    name: str,
    *,
    version: str = "1.0.0",
    releases: Mapping[str, Sequence[object]] | None = None,
    **info: object,
) -> Json:
    base: Json = {
        "name": name,
        "version": version,
        "license_expression": "MIT",
        "classifiers": [],
        "license": None,
        "requires_dist": None,
    }
    base.update(info)
    listed = dict(releases) if releases is not None else {version: files(name, version)}
    return {"info": base, "releases": listed}


def json_response(body: object, status: int = 200) -> httpx2.Response:
    return httpx2.Response(
        status,
        content=json.dumps(body).encode(),
        headers={"content-type": "application/json"},
    )


class FakeIndex:
    """pypi.org (redirecting to the display name, as PyPI does) and OSV."""

    def __init__(self) -> None:
        self.projects: dict[str, Json] = {}
        self.releases: dict[tuple[str, str], Json] = {}
        self.vulns: dict[tuple[str, str], list[Json]] = {}
        self.fallback: Callable[[str], Json | None] = lambda _: None
        self.pypi_status = 200
        self.release_status = 200
        self.osv_status = 200
        self.requests: list[httpx2.Request] = []

    def add(self, *projects: Json) -> FakeIndex:
        for item in projects:
            info = item["info"]
            assert isinstance(info, dict)
            self.projects[canonical(str(info["name"]))] = item
        return self

    def osv_bodies(self) -> list[Json]:
        return [json.loads(r.read()) for r in self.requests if r.url.host == OSV_HOST]

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if request.url.host == OSV_HOST:
            if self.osv_status != 200:
                return httpx2.Response(self.osv_status)
            body = json.loads(request.read())
            key = (body["package"]["name"], body["version"])
            found = self.vulns.get(key)
            return json_response({"vulns": found} if found else {})
        if self.pypi_status != 200:
            return httpx2.Response(self.pypi_status)
        parts = request.url.path.split("/")
        name = parts[2]
        own = canonical(name)
        found_project = self.projects.get(own) or self.fallback(own)
        if found_project is None:
            return httpx2.Response(404)
        info = found_project["info"]
        assert isinstance(info, dict)
        display = str(info["name"])
        if name != display:
            location = request.url.path.replace(f"/{name}/", f"/{display}/")
            return httpx2.Response(301, headers={"location": location})
        if len(parts) == 5:
            if self.release_status != 200:
                return httpx2.Response(self.release_status)
            release = self.releases.get((own, parts[3]))
            return json_response(release) if release else httpx2.Response(404)
        return json_response(found_project)


def index_for(
    handler: Callable[[httpx2.Request], httpx2.Response], clock: Clock | None = None
) -> PackageIndex:
    clock = clock or Clock()
    return PackageIndex(
        transport=httpx2.MockTransport(handler), clock=clock, sleep=clock.sleep
    )


def assess(fake: FakeIndex, name: str, popular: Popular = POPULAR) -> Assessment:
    return Assessor(index_for(fake), popular, now=NOW).assess(name)


# ---------------------------------------------------------------------------
# Inputs: the package list and the dated popular snapshot
# ---------------------------------------------------------------------------


def test_the_inputs_are_forty_candidates_and_ten_decoys() -> None:
    inputs = load_inputs()
    roles = [i.role for i in inputs]
    assert roles.count("candidate") == 40 and roles.count("decoy") == 10
    names = {i.name for i in inputs}
    for required in ("orjson", "google-re2", "pyroaring", "lru-dict", "cytoolz"):
        assert required in names


def test_the_popular_snapshot_is_dated_canonical_and_a_few_hundred_names() -> None:
    popular = load_popular()
    assert popular.snapshot_date == "2026-10-24"
    assert 300 <= len(popular.names) <= 600
    assert {"numpy", "requests", "orjson", "sortedcontainers"} <= popular.names
    raw = json.loads(acquire.POPULAR.read_text(encoding="utf-8"))
    assert "knowledge" in raw["source"] and "not fetched" in raw["source"]
    decoys = {canonical(i.name) for i in load_inputs() if i.role == "decoy"}
    assert not decoys & popular.names


def test_every_decoy_is_a_near_miss_of_the_snapshot() -> None:
    """The decoys are built as near misses; the honest candidates show what
    the check costs (recorded live, not asserted)."""
    popular = load_popular()
    for item in load_inputs():
        if item.role == "decoy":
            assert near_miss(item.name, popular.names) is not None, item.name


@pytest.mark.parametrize(
    "doc",
    [
        {"written": "x", "note": "y"},
        {"written": "x", "note": "y", "packages": []},
        {"written": "x", "note": "y", "packages": [{"name": "a", "role": "boss"}]},
        {"written": "x", "note": "y", "packages": [{"name": "../a", "role": "decoy"}]},
        {
            "written": "x",
            "note": "y",
            "packages": [
                {"name": "A_b", "role": "decoy"},
                {"name": "a-b", "role": "candidate"},
            ],
        },
        {"written": "x", "note": "y", "packages": ["orjson"]},
    ],
    ids=["no-packages", "empty", "role", "name", "duplicate", "not-object"],
)
def test_bad_inputs_are_refused(tmp_path: Path, doc: Json) -> None:
    path = tmp_path / "inputs.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(ValueError, match="inputs|PyPI"):
        load_inputs(path)


@pytest.mark.parametrize(
    "doc",
    [
        {"snapshot_date": "2026-10-24", "names": []},
        {"snapshot_date": "2026-10-24", "source": "s", "names": ["Requests"]},
        {"snapshot_date": "2026-10-24", "source": "s", "names": ["a", "a"]},
        {"snapshot_date": 1, "source": "s", "names": []},
    ],
    ids=["keys", "not-canonical", "duplicate", "date"],
)
def test_a_bad_snapshot_is_refused(tmp_path: Path, doc: Json) -> None:
    path = tmp_path / "popular.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(ValueError, match="popular"):
        load_popular(path)


@pytest.mark.parametrize(
    ("name", "expected"),
    [("Sorted_Containers", "sorted-containers"), ("a.b--c", "a-b-c"), ("x", "x")],
)
def test_canonical_names(name: str, expected: str) -> None:
    assert canonical(name) == expected


@pytest.mark.parametrize(
    "name", ["", "-x", "x-", "a/b", "..", "a b", "nümpy", "a" * 101, "x\n"]
)
def test_a_name_that_is_not_a_pypi_name_is_refused(name: str) -> None:
    with pytest.raises(ValueError, match="not a PyPI project name"):
        check_name(name)


# ---------------------------------------------------------------------------
# The allowlist
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "kind", "name"),
    [
        ("https://pypi.org/pypi/More_Itertools/json", "project", "more-itertools"),
        ("https://pypi.org/pypi/numpy/2.1.0/json", "release", "numpy"),
        ("https://pypi.org:443/pypi/numpy/json", "project", "numpy"),
        ("https://api.osv.dev/v1/query", "osv", None),
    ],
)
def test_the_allowed_urls(url: str, kind: str, name: str | None) -> None:
    assert check_url(url) == (kind, name)


@pytest.mark.parametrize(
    "url",
    [
        "http://pypi.org/pypi/numpy/json",
        "https://pypi.org:8443/pypi/numpy/json",
        "https://user@pypi.org/pypi/numpy/json",
        "https://pypi.org/pypi/numpy/json?x=1",
        "https://pypi.org/pypi/numpy/json#x",
        "https://pypi.org/pypi/%2e%2e/json",
        "https://pypi.org/pypi/../json",
        "https://pypi.org/simple/numpy/",
        "https://pypi.org/pypi/numpy/2.0/../json",
        "https://files.pythonhosted.org/packages/x.whl",
        "https://pypi.org.evil.example/pypi/numpy/json",
        "https://api.osv.dev/v1/querybatch",
        "https://osv.dev/v1/query",
        "https://pypi.org/pypi/num py/json",
        "https://pypi.org/pypi/nümpy/json",
        "https://pypi.org:x/pypi/numpy/json",
    ],
)
def test_any_other_url_is_refused(url: str) -> None:
    with pytest.raises(FetchRefusedError, match="not an allowed index URL"):
        check_url(url)


@pytest.mark.parametrize("version", ["1.0+local", "../1", "v1", "1 0", "１.0", ""])
def test_a_version_unfit_for_a_url_is_refused(version: str) -> None:
    with pytest.raises(FetchRefusedError, match="not a release version"):
        release_url("numpy", version)


# ---------------------------------------------------------------------------
# The client: the wire, redirects, retries, caps
# ---------------------------------------------------------------------------


def test_the_client_ignores_the_environment_and_follows_no_redirect() -> None:
    with PackageIndex() as index:
        assert index.client.trust_env is False
        assert index.client.follow_redirects is False
    with pytest.raises(ValueError, match="apart"):
        PackageIndex(spacing_s=0.1)


def test_a_404_is_no_project_and_a_display_name_redirect_is_followed() -> None:
    fake = FakeIndex().add(project("Levenshtein"))
    with index_for(fake) as index:
        assert index.project("nunpy") is None
        found = index.project("levenshtein")
    assert found is not None
    assert [r.url.path for r in fake.requests] == [
        "/pypi/nunpy/json",
        "/pypi/levenshtein/json",
        "/pypi/Levenshtein/json",
    ]


@pytest.mark.parametrize(
    "location",
    [
        "https://evil.example/pypi/numpy/json",
        "http://pypi.org/pypi/numpy/json",
        "/pypi/other/json",
        "/pypi/numpy/1.0/json",
        "/simple/numpy/",
        "",
    ],
    ids=["host", "http", "project", "kind", "path", "empty"],
)
def test_a_redirect_elsewhere_is_refused(location: str) -> None:
    handler = lambda _: httpx2.Response(301, headers={"location": location})  # noqa: E731
    with index_for(handler) as index, pytest.raises(FetchRefusedError):
        index.project("numpy")


def test_a_release_redirect_to_another_version_is_refused() -> None:
    def moved(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/pypi/numpy/2.0.0/json":
            return httpx2.Response(200, json={"info": {"version": "2.0.0"}})
        return httpx2.Response(301, headers={"location": "/pypi/numpy/2.0.0/json"})

    with index_for(moved) as index, pytest.raises(FetchRefusedError, match="refused"):
        index.release("numpy", "1.0.0")


def test_redirect_loops_and_osv_redirects_are_refused() -> None:
    def loop(request: httpx2.Request) -> httpx2.Response:
        target = (
            "/pypi/NumPy/json" if "numpy" in request.url.path else "/pypi/numpy/json"
        )
        return httpx2.Response(302, headers={"location": target})

    with index_for(loop) as index, pytest.raises(FetchRefusedError, match="redirects"):
        index.project("numpy")
    moved = lambda _: httpx2.Response(301, headers={"location": "/v1/query"})  # noqa: E731
    with index_for(moved) as index, pytest.raises(FetchRefusedError, match="redirect"):
        index.osv("numpy", "1.0")


def test_busy_answers_are_retried_with_backoff_then_fail() -> None:
    clock, sent = Clock(), list[httpx2.Request]()

    def busy(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        headers = {"retry-after": "120"} if len(sent) == 1 else {}
        return httpx2.Response(429, headers=headers)

    with index_for(busy, clock) as index, pytest.raises(FetchError) as caught:
        index.project("numpy")
    assert str(caught.value) == "HTTP 429 after 4 attempts"
    assert len(sent) == 4
    assert [s for s in clock.sleeps if s > acquire.MIN_SPACING_S] == [30.0, 4.0, 8.0]


def test_silence_is_retried_and_a_refusal_status_is_final() -> None:
    calls: list[int] = []

    def flaky(request: httpx2.Request) -> httpx2.Response:
        calls.append(1)
        if len(calls) == 1:
            raise httpx2.ConnectError("down", request=request)
        return json_response(project("numpy"))

    with index_for(flaky) as index:
        assert index.project("numpy") is not None
        assert index.answered == 1 and index.requests == 2
    forbidden = lambda _: httpx2.Response(403)  # noqa: E731
    with index_for(forbidden) as index, pytest.raises(FetchError, match="HTTP 403$"):
        index.project("numpy")


@pytest.mark.parametrize(
    ("response", "match"),
    [
        (
            httpx2.Response(200, content=b"{}", headers={"content-type": "text/html"}),
            "content type",
        ),
        (
            httpx2.Response(
                200,
                content=b"{}",
                headers={
                    "content-type": "application/json",
                    "content-length": str(64 * 1024 * 1024),
                },
            ),
            "larger than",
        ),
        (
            httpx2.Response(
                200, content=b"[1]", headers={"content-type": "application/json"}
            ),
            "not a JSON object",
        ),
    ],
    ids=["type", "declared-size", "array"],
)
def test_bodies_are_typed_capped_and_objects(
    response: httpx2.Response, match: str
) -> None:
    with (
        index_for(lambda _: response) as index,
        pytest.raises(FetchRefusedError, match=match),
    ):
        index.project("numpy")


def test_a_streamed_body_past_its_cap_or_deadline_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(acquire.CAPS, "project", 10)
    big = lambda _: json_response({"x": "y" * 20})  # noqa: E731
    with index_for(big) as index, pytest.raises(FetchRefusedError, match="larger"):
        index.project("numpy")
    chunked = httpx2.Response(
        200,
        content=iter([b'{"x": "', b"y" * 20, b'"}']),
        headers={"content-type": "application/json"},
    )
    assert "content-length" not in chunked.headers
    with (
        index_for(lambda _: chunked) as index,
        pytest.raises(FetchRefusedError, match="larger"),
    ):
        index.project("numpy")
    monkeypatch.setitem(acquire.CAPS, "project", 1024)

    class Slow(Clock):
        def __call__(self) -> float:
            self.now += 1000.0
            return self.now

    with (
        index_for(big, Slow()) as index,
        pytest.raises(FetchRefusedError, match="deadline"),
    ):
        index.project("numpy")


@pytest.mark.parametrize(
    "body",
    [
        b'{"a": 1, "a": 2}',
        b'{"a": NaN}',
        b"\xff{}",
        b"[" * 100_000 + b"]" * 100_000,
        b"{",
    ],
    ids=["duplicate", "nan", "utf8", "deep", "truncated"],
)
def test_json_is_parsed_strictly(body: bytes) -> None:
    with pytest.raises(FetchRefusedError):
        parse_json(body)


def test_requests_are_spaced_per_host() -> None:
    clock = Clock()
    fake = FakeIndex().add(project("numpy"))
    with index_for(fake, clock) as index:
        index.project("numpy")
        index.osv("numpy", "1.0.0")
        index.project("numpy")
    assert clock.sleeps == [acquire.MIN_SPACING_S]


def test_the_osv_query_its_paging_and_withdrawn_entries() -> None:
    pages: list[Json] = [
        {
            "vulns": [{"id": "PYSEC-1"}, {"id": "GHSA-x", "withdrawn": "2025"}],
            "next_page_token": "t1",
        },
        {"vulns": [{"id": "bad id!"}, "junk"]},
    ]
    sent: list[Json] = []

    def osv(request: httpx2.Request) -> httpx2.Response:
        assert request.method == "POST"
        assert request.headers["content-type"] == "application/json"
        sent.append(json.loads(request.read()))
        return json_response(pages[len(sent) - 1])

    with index_for(osv) as index:
        result = index.osv("Sorted_Containers", "2.4.0")
    assert result.count == 2 and result.ids == ("PYSEC-1",)
    assert sent[0] == {
        "package": {"name": "sorted-containers", "ecosystem": "PyPI"},
        "version": "2.4.0",
    }
    assert sent[1]["page_token"] == "t1"


def test_osv_paging_without_end_a_bad_shape_and_a_404_are_failures() -> None:
    endless = lambda _: json_response({"next_page_token": "again"})  # noqa: E731
    with index_for(endless) as index, pytest.raises(FetchRefusedError, match="pages"):
        index.osv("numpy", "1.0")
    shape = lambda _: json_response({"vulns": {}})  # noqa: E731
    with index_for(shape) as index, pytest.raises(FetchRefusedError, match="list"):
        index.osv("numpy", "1.0")
    gone = lambda _: httpx2.Response(404)  # noqa: E731
    with index_for(gone) as index, pytest.raises(FetchError, match="404"):
        index.osv("numpy", "1.0")
    with index_for(gone) as index, pytest.raises(FetchRefusedError):
        index.osv("numpy", "1.0+local")


# ---------------------------------------------------------------------------
# Reading metadata: pins, wheels, licences, requirements
# ---------------------------------------------------------------------------


def test_the_pin_skips_fresh_yanked_prerelease_and_invalid_versions() -> None:
    releases = {
        "0.9": files("x", "0.9", uploaded="2024-01-01T00:00:00Z"),
        "1.0": files("x", "1.0"),
        "1.1": [file("x-1.1.tar.gz", yanked=True)],
        "2.0rc1": files("x", "2.0rc1"),
        "not-a-version": files("x", "9"),
        "1.2": files("x", "1.2", uploaded=FRESH),
        "1.3": [],
    }
    pin = choose_pin(project("x", version="1.2", releases=releases), NOW)
    assert pin.latest == "1.2" and pin.pinned == "1.0"
    assert pin.release_age_days == 2 and pin.project_age_days == 1027
    assert pin.stable_with_files == 3


def test_release_files_read_only_well_formed_entries() -> None:
    raw = project(
        "x",
        releases={
            "1.0": [
                file("x-1.0.tar.gz", sha="NOT-HEX"),
                {"filename": "x.exe", "packagetype": "bdist_wininst"},
                "junk",
                {**file("x-1.0.tar.gz"), "upload_time_iso_8601": "2025-01-01T00:00:00"},
                {**file("x-1.0.tar.gz"), "upload_time_iso_8601": "yesterday"},
                {**file("x-1.0.tar.gz"), "upload_time_iso_8601": 1700000000},
            ]
        },
    )
    found = release_files(raw, "1.0")
    assert [f.sha256 for f in found] == [None, SHA, SHA, SHA]
    assert [f.uploaded for f in found][1:] == [None, None, None]
    assert release_files({"releases": []}, "1.0") == []


@pytest.mark.parametrize(
    ("filename", "linux", "mac", "pure"),
    [
        (f"x-1.0-{LINUX}.whl", True, False, False),
        ("x-1.0-cp311-cp311-manylinux_2_28_x86_64.whl", True, False, False),
        ("x-1.0-cp311-cp311-manylinux_2_39_x86_64.whl", False, False, False),
        ("x-1.0-cp311-cp311-musllinux_1_2_x86_64.whl", False, False, False),
        ("x-1.0-cp312-cp312-manylinux_2_17_x86_64.whl", False, False, False),
        ("x-1.0-cp38-abi3-manylinux_2_17_x86_64.whl", True, False, False),
        (f"x-1.0-{MAC}.whl", False, True, False),
        ("x-1.0-cp311-cp311-macosx_10_9_universal2.whl", False, True, False),
        ("x-1.0-cp311-cp311-macosx_10_9_x86_64.whl", False, False, False),
        ("x-1.0-cp311-cp311-macosx_26_0_arm64.whl", False, False, False),
        ("x-1.0-py3-none-any.whl", True, True, True),
        ("x-1.0-py2.py3-none-any.whl", True, True, True),
        ("x-1.0-cp311-cp311-win_amd64.whl", False, False, False),
    ],
)
def test_wheel_tags_against_the_two_targets(
    filename: str, linux: bool, mac: bool, pure: bool
) -> None:
    facts = wheel_facts([FileFacts(filename, True, False, None, SHA)])
    assert (facts.linux, facts.mac, facts.pure) == (linux, mac, pure)


def test_sdist_only_unreadable_yanked_and_unhashed_files() -> None:
    sdist = wheel_facts([FileFacts("x-1.0.tar.gz", False, False, None, SHA)])
    assert sdist.sdist and sdist.wheels == 0 and sdist.hashed
    odd = wheel_facts(
        [
            FileFacts("not a wheel.whl", True, False, None, SHA),
            FileFacts("x-1.0-py3-none-any.whl", True, True, None, SHA),
            FileFacts("x-1.0.tar.gz", False, False, None, None),
        ]
    )
    assert odd.unreadable == 1 and odd.wheels == 0 and not odd.linux
    assert not odd.hashed
    assert not wheel_facts([]).hashed


@pytest.mark.parametrize(
    ("info", "label", "ok"),
    [
        ({"license_expression": "MIT"}, "MIT", True),
        ({"license_expression": "Apache-2.0 OR MIT"}, "Apache-2.0 OR MIT", True),
        ({"license_expression": "MIT AND GPL-3.0-only"}, "MIT AND GPL-3.0-only", False),
        ({"license_expression": "(GPL-2.0 OR BSD-3-Clause) AND MIT"}, None, True),
        ({"license_expression": "Apache-2.0 WITH LLVM-exception"}, None, True),
        ({"license_expression": "GPL-3.0-or-later"}, None, False),
        ({"license_expression": "MIT OR"}, None, False),
        ({"license_expression": "(MIT"}, None, False),
        ({"license_expression": "(MIT MIT)"}, None, False),
        ({"license_expression": "MIT WITH"}, None, False),
        ({"license_expression": "MIT WITH AND"}, None, False),
        ({"license_expression": "AND MIT"}, None, False),
        ({"license_expression": "MIT MIT"}, None, False),
        ({"license_expression": "MIT/BSD"}, None, False),
        ({"classifiers": ["License :: OSI Approved :: MIT License"]}, "MIT", True),
        (
            {
                "classifiers": [
                    "License :: OSI Approved :: Apache Software License",
                    "License :: OSI Approved :: BSD License",
                ]
            },
            "Apache-2.0 OR BSD",
            True,
        ),
        (
            {
                "classifiers": [
                    "License :: OSI Approved :: GNU General Public License v3 (GPLv3)"
                ]
            },
            "GPL-3.0",
            False,
        ),
        (
            {"classifiers": ["License :: Other/Proprietary License"]},
            "Other/Proprietary License",
            False,
        ),
        ({"classifiers": ["License :: OSI Approved"], "license": "BSD"}, "BSD", True),
        ({"license": "Apache License, Version 2.0"}, "Apache-2.0", True),
        ({"license": "BSD-3-Clause"}, "BSD-3-Clause", True),
        ({"license": "Apache License 2.0"}, "Apache-2.0", True),
        (
            {"license": "Permission is hereby granted, free of charge, " + "x" * 200},
            None,
            False,
        ),
        (
            {"license": "GNU GPL v3. Portions: Apache License, Version 2.0"},
            "GNU GPL v3. Portions: Apache License, Version 2.0",
            False,
        ),
        (
            {"license": "Redistribution and use in source and binary forms, " * 3},
            None,
            False,
        ),
        ({"license": "GPLv3"}, "GPLv3", False),
        ({"license": "  "}, "none", False),
        ({}, "none", False),
    ],
)
def test_licences_fail_closed(info: Json, label: str | None, ok: bool) -> None:
    found_label, found_ok = licence(info)
    assert found_ok is ok
    if label is not None:
        assert found_label == label


def test_requirements_on_either_target_without_extras() -> None:
    info: Json = {
        "requires_dist": [
            "toolz>=0.8.0",
            "Numpy ; sys_platform == 'darwin'",
            "pywin32 ; sys_platform == 'win32'",
            "pytest ; extra == 'test'",
            "tomli ; python_version < '3.11'",
            "typing_extensions>=4 ; python_version >= '3.8'",
            "toolz",
        ]
    }
    assert requirements(info) == ("toolz", "numpy", "typing-extensions")
    assert requirements({"requires_dist": None}) == ()
    for bad in ([1], "toolz", ["not a requirement !!"]):
        with pytest.raises(ValueError):
            requirements({"requires_dist": bad})


# ---------------------------------------------------------------------------
# Near misses
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("nunpy", NearMiss("numpy", "edit", 1)),
        ("numpyy", NearMiss("numpy", "edit", 1)),
        ("nmupy", NearMiss("numpy", "edit", 1)),
        ("sortedcontainer", NearMiss("sortedcontainers", "edit", 1)),
        ("sortedcontaners", NearMiss("sortedcontainers", "edit", 1)),
        ("rapid-fuzz", NearMiss("rapidfuzz", "separator", 0)),
        ("python-orjson", NearMiss("orjson", "combo", 0)),
        ("orjson-fast", NearMiss("orjson", "combo", 0)),
        ("pyorjson", NearMiss("orjson", "combo", 0)),
        ("orjson2", NearMiss("orjson", "combo", 0)),
        ("numpy-3", NearMiss("numpy", "combo", 0)),
        ("orjson", None),
        ("Sorted_Containers", NearMiss("sortedcontainers", "separator", 0)),
        ("cytoolz", None),
        ("orjson-schema", None),
        ("six2", None),
        ("nump", NearMiss("numpy", "edit", 1)),
        ("numbaa", None),
    ],
)
def test_near_misses_of_the_snapshot(name: str, expected: NearMiss | None) -> None:
    assert near_miss(name, POPULAR.names) == expected


def test_the_closest_near_miss_wins_and_ties_break_by_name() -> None:
    popular = frozenset({"abcde", "abcdf", "abcdefgh"})
    assert near_miss("abcdx", popular) == NearMiss("abcde", "edit", 1)


@pytest.mark.parametrize(
    ("a", "b", "distance"),
    [
        ("numpy", "numpy", 0),
        ("numpy", "nmupy", 1),
        ("numpy", "nunpy", 1),
        ("", "ab", 2),
        ("abc", "", 3),
    ],
)
def test_the_osa_distance(a: str, b: str, distance: int) -> None:
    assert osa_distance(a, b) == distance


# ---------------------------------------------------------------------------
# The policy
# ---------------------------------------------------------------------------


def test_a_healthy_popular_package_is_auto_accepted() -> None:
    fake = FakeIndex().add(project("orjson", version="3.10.0"))
    found = assess(fake, "orjson")
    assert found.verdict == "auto-accept" and found.checks == ()
    assert found.exists and found.licence == "MIT" and found.osv is not None
    assert fake.osv_bodies() == [
        {"package": {"name": "orjson", "ecosystem": "PyPI"}, "version": "3.10.0"}
    ]
    assert found.note() == (
        "ACQUIRE orjson: exists y wheels y/y age 661 osv 0 licence MIT "
        "verdict auto-accept"
    )
    metrics = found.metrics()
    assert metrics["pinned"] == "3.10.0" and metrics["sdist_only"] is False
    assert metrics["verdict_sans_downloads"] == "auto-accept"


SCENARIOS: list[tuple[str, Json, str, str]] = [
    ("not-popular", project("msgspec"), "downloads", "no download source"),
    (
        "sdist-only",
        project("toolz", releases={"1.0.0": [file("toolz-1.0.0.tar.gz")]}),
        "wheels",
        "sdist-only",
    ),
    (
        "linux-only",
        project("toolz", releases={"1.0.0": [file(f"toolz-1.0.0-{LINUX}.whl")]}),
        "wheels",
        "no mac wheel",
    ),
    (
        "no-wheel",
        project("toolz", releases={"1.0.0": [file("toolz-1.0.0.zip")]}),
        "wheels",
        "no wheel",
    ),
    (
        "gpl",
        project("toolz", license_expression="GPL-3.0-only"),
        "licence",
        "allowlist",
    ),
    (
        "young",
        project(
            "toolz",
            releases={
                "1.0.0": files("toolz", "1.0.0", uploaded="2026-09-01T00:00:00Z")
            },
        ),
        "project_age",
        "53 days",
    ),
    (
        "fresh-only",
        project("toolz", releases={"1.0.0": files("toolz", "1.0.0", uploaded=FRESH)}),
        "release_age",
        "7+ days",
    ),
    (
        "unhashed",
        project(
            "toolz",
            releases={
                "1.0.0": [*files("toolz", "1.0.0"), file("toolz-1.0.0.zip", sha=None)]
            },
        ),
        "hashes",
        "sha256",
    ),
]


# A project whose only release is fresh is also a young project.
ALSO_FAILS: dict[str, tuple[str, ...]] = {"fresh-only": ("project_age",)}


@pytest.mark.parametrize(
    ("scenario", "raw", "check", "detail"),
    SCENARIOS,
    ids=[s[0] for s in SCENARIOS],
)
def test_each_failing_check_asks_the_user(
    scenario: str, raw: Json, check: str, detail: str
) -> None:
    info = raw["info"]
    assert isinstance(info, dict)
    found = assess(FakeIndex().add(raw), str(info["name"]))
    assert found.verdict == "ask-user"
    expected = {check, *ALSO_FAILS.get(scenario, ())}
    assert sorted(found.checks) == sorted(expected)
    assert any(f.check == check and detail in f.detail for f in found.failures)


def test_a_known_vulnerability_and_an_osv_outage_ask_the_user() -> None:
    fake = FakeIndex().add(project("toolz"))
    fake.vulns[("toolz", "1.0.0")] = [{"id": "PYSEC-2026-1"}]
    found = assess(fake, "toolz")
    assert found.checks == ("osv",) and found.verdict == "ask-user"
    assert "1 known: PYSEC-2026-1" in found.failures[0].detail
    fake.osv_status = 503
    down = assess(fake, "toolz")
    assert down.checks == ("osv",) and "unchecked" in down.failures[0].detail


def test_nothing_to_pin_is_rejected_and_a_pypi_outage_asks() -> None:
    fake = FakeIndex().add(
        project("toolz", releases={"1.0.0": [file("toolz-1.0.0.tar.gz", yanked=True)]})
    )
    missing = assess(fake, "nunpy")
    assert missing.verdict == "reject"
    assert missing.exists is False and missing.checks == ("exists", "near_miss")
    empty = assess(fake, "toolz")
    assert empty.checks == ("files",) and empty.verdict == "reject"
    fake.pypi_status = 503
    down = assess(fake, "toolz")
    assert down.checks == ("index",) and down.verdict == "ask-user"
    assert down.exists is None and down.note().startswith("ACQUIRE toolz: exists ?")


def test_a_young_near_miss_is_rejected_an_old_one_asks() -> None:
    young = files("nunpy", "1.0.0", uploaded="2026-10-01T00:00:00Z")
    fake = FakeIndex().add(project("nunpy", releases={"1.0.0": young}))
    found = assess(fake, "nunpy")
    assert found.verdict == "reject"
    assert {"near_miss", "project_age", "downloads"} <= set(found.checks)
    old = assess(FakeIndex().add(project("nunpy")), "nunpy")
    assert old.verdict == "ask-user" and "near_miss" in old.checks


def test_a_pin_older_than_latest_reads_its_own_release_metadata() -> None:
    releases = {
        "1.0.0": files("toolz", "1.0.0"),
        "2.0.0": files("toolz", "2.0.0", uploaded=FRESH),
    }
    fake = FakeIndex().add(
        project("toolz", version="2.0.0", releases=releases, license_expression="MIT")
    )
    fake.releases[("toolz", "1.0.0")] = {
        "info": {"name": "toolz", "version": "1.0.0", "license": "GPLv2"}
    }
    found = assess(fake, "toolz")
    assert found.pin is not None and found.pin.pinned == "1.0.0"
    assert found.licence == "GPLv2" and found.checks == ("licence",)
    paths = [r.url.path for r in fake.requests if r.url.host == "pypi.org"]
    assert paths == ["/pypi/toolz/json", "/pypi/toolz/1.0.0/json"]
    del fake.releases[("toolz", "1.0.0")]
    lost = assess(fake, "toolz")
    assert lost.checks == ("index",) and "no metadata" in lost.failures[0].detail
    fake.release_status = 403
    refused = assess(fake, "toolz")
    assert refused.checks == ("index",) and "HTTP 403" in refused.failures[0].detail


def test_dependencies_pass_the_same_policy() -> None:
    fake = FakeIndex().add(
        project("cytoolz", requires_dist=["toolz>=0.8", "msgspec", "gone-pkg"]),
        project("toolz"),
        project("msgspec"),
    )
    found = assess(fake, "cytoolz")
    assert found.dependencies == ("toolz", "msgspec", "gone-pkg")
    assert "dependencies" in found.checks
    detail = next(f.detail for f in found.failures if f.check == "dependencies")
    assert detail == "msgspec ask-user, gone-pkg reject"
    assert found.verdict == "ask-user" and found.verdict_sans_downloads == "ask-user"
    fake.add(project("cytoolz", requires_dist=["toolz", "msgspec"]))
    only_downloads = assess(fake, "cytoolz")
    assert only_downloads.verdict == "ask-user"
    assert only_downloads.verdict_sans_downloads == "auto-accept"


def test_cycles_depth_and_the_project_budget_end_the_walk() -> None:
    fake = FakeIndex().add(
        project("numpy", requires_dist=["toolz"]),
        project("toolz", requires_dist=["numpy", "orjson"]),
        project("orjson", requires_dist=["six"]),
        project("six"),
    )
    assessor = Assessor(index_for(fake), POPULAR, now=NOW)
    assert assessor.assess("numpy").verdict == "auto-accept"
    assert set(assessor.done) == {"numpy", "toolz", "orjson", "six"}
    shallow = Assessor(index_for(fake), POPULAR, now=NOW, max_depth=1).assess("numpy")
    assert shallow.verdict == "ask-user"
    assert "orjson unchecked" not in str(shallow.failures)
    assert "toolz ask-user" in str(shallow.failures)
    tight = Assessor(index_for(fake), POPULAR, now=NOW, max_projects=1).assess("numpy")
    assert "toolz unchecked" in str(tight.failures)
    assert tight.verdict_sans_downloads == "ask-user"
    bad = assess(FakeIndex().add(project("toolz", requires_dist=["!!"])), "toolz")
    assert bad.checks == ("dependencies",) and bad.verdict_sans_downloads == "ask-user"
    with pytest.raises(ValueError, match="timezone"):
        Assessor(index_for(fake), POPULAR, now=datetime(2026, 1, 1))


def test_the_verdict_order() -> None:
    def fail(*checks: str) -> list[acquire.Failure]:
        return [acquire.Failure(c, "") for c in checks]

    assert verdict(fail()) == "auto-accept"
    assert verdict(fail("downloads")) == "ask-user"
    assert verdict(fail("downloads"), ignore=frozenset({"downloads"})) == "auto-accept"
    assert verdict(fail("near_miss")) == "ask-user"
    assert verdict(fail("near_miss", "project_age")) == "reject"
    assert verdict(fail("exists")) == verdict(fail("files")) == "reject"
    assert set(CHECKS) >= {"index", "exists", "osv", "dependencies"}


def test_the_summary_counts_rates_and_the_most_frequent_check() -> None:
    fake = FakeIndex().add(project("orjson"), project("msgspec"), project("blake3"))
    found = [assess(fake, n) for n in ("orjson", "msgspec", "blake3", "nunpy")]
    summary = summarize(found)
    assert summary["packages"] == 4
    assert (summary["auto_accept"], summary["ask_user"], summary["reject"]) == (1, 2, 1)
    assert summary["pass_rate"] == 0.25 and summary["pass_rate_sans_downloads"] == 0.75
    assert summary["most_frequent_check"] == "downloads"
    assert summary["check_counts"] == "downloads=2, exists=1, near_miss=1"
    assert summarize([])["pass_rate"] is None


# ---------------------------------------------------------------------------
# Part B: the request and its reading
# ---------------------------------------------------------------------------


def test_the_suggestion_request_shape() -> None:
    fence = Fence.new()
    repo = OSS_CORPUS[0]
    body = suggest_body(repo, fence)
    assert body is not None
    assert body["model"] == SONNET == "claude-sonnet-5-5"
    assert body["max_tokens"] == acquire.MAX_TOKENS
    assert body["system"] == SYSTEM
    assert body["output_config"] == {
        "format": {"type": "json_schema", "schema": SUGGEST_SCHEMA},
        "effort": "medium",
    }
    assert "fallbacks" not in body and "thinking" not in body and "tools" not in body
    text = json.dumps(body["messages"])
    assert fence.token in text and repo.name in text
    assert repo.hypotheses[0].title in text
    assert fence.token not in SYSTEM


def test_a_library_text_holding_a_live_token_is_withheld() -> None:
    repo = OSS_CORPUS[0]
    fence = Fence.new()
    planted = replace(repo, profile=f"see {fence.token}")
    assert suggest_body(planted, fence) is None


def sonnet_message(payload: object, *, stop: str = "end_turn") -> Json:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return {
        "id": "msg_01Acquire",
        "type": "message",
        "role": "assistant",
        "model": SONNET,
        "content": [
            {"type": "thinking", "thinking": "", "signature": "sig"},
            {"type": "text", "text": text},
        ],
        "stop_reason": stop,
        "stop_sequence": None,
        "usage": {"input_tokens": 1500, "output_tokens": 900},
    }


def answer_of(body: Json | None, outcome: str = "end_turn") -> Answer:
    message = BetaMessage.model_validate(body) if body is not None else None
    return Answer(200 if body else None, message, None, 0.0, 0.0, outcome)


def suggestions(*names: str, reason: str = "A compiled parser.") -> Json:
    return {"packages": [{"name": n, "reason": reason} for n in names]}


def test_suggestions_are_read_capped_and_deduplicated() -> None:
    reading = read_suggestions(
        answer_of(sonnet_message(suggestions("orjson", "ORJSON", "bad name!", "x")))
    )
    assert [s.name for s in reading.suggestions] == ["orjson"]
    assert (reading.invalid, reading.duplicates, reading.over_limit) == (1, 1, 1)
    assert reading.outcome == "ok"
    long = read_suggestions(
        answer_of(sonnet_message(suggestions("a", reason="r" * 301)))
    )
    assert long.suggestions == () and long.invalid == 1
    lines = read_suggestions(answer_of(sonnet_message(suggestions("a", reason="x\ny"))))
    assert lines.invalid == 1
    assert read_suggestions(answer_of(sonnet_message(suggestions()))).suggestions == ()


@pytest.mark.parametrize(
    ("body", "outcome"),
    [
        (sonnet_message(suggestions("a"), stop="refusal"), "refusal"),
        (sonnet_message(suggestions("a"), stop="max_tokens"), "stopped"),
        (sonnet_message("not json"), "unusable"),
        (sonnet_message({"packages": [{"name": "a"}]}), "unusable"),
        (sonnet_message('{"packages": [], "packages": []}'), "unusable"),
        (None, "no_answer"),
    ],
    ids=["refusal", "stopped", "not-json", "schema", "duplicate-key", "no-answer"],
)
def test_an_unusable_reply_keeps_its_reason(body: Json | None, outcome: str) -> None:
    reading = read_suggestions(answer_of(body, outcome="no_answer"))
    assert reading.suggestions == () and reading.outcome == outcome


def test_the_suggestion_summary_rates() -> None:
    fake = FakeIndex().add(project("orjson"), project("msgspec"))
    judged = [
        ("tabulate", assess(fake, "orjson")),
        ("tabulate", assess(fake, "fastjsonx")),
        ("idna", assess(fake, "msgspec")),
        ("idna", assess(fake, "python-orjson")),
    ]
    readings = {
        "tabulate": acquire.SuggestReading((), "ok", invalid=1),
        "idna": acquire.SuggestReading((), "ok", over_limit=2),
        "tomli": acquire.SuggestReading((), "refusal"),
    }
    summary = suggestion_summary(judged, readings)
    assert summary["suggestions"] == 4 and summary["distinct"] == 4
    assert summary["hallucinated_rate"] == 0.5 and summary["near_miss_rate"] == 0.25
    assert summary["auto_accept_rate"] == 0.25 and summary["ask_user_rate"] == 0.25
    assert summary["reject_rate"] == 0.5 and summary["unreachable_rate"] == 0.0
    assert summary["auto_accept_rate_sans_downloads"] == 0.5
    assert summary["outcomes"] == "ok=2, refusal=1"
    assert (summary["invalid_names"], summary["over_limit"]) == (1, 2)
    assert suggestion_summary([], {})["hallucinated_rate"] is None


# ---------------------------------------------------------------------------
# The live module, dry
# ---------------------------------------------------------------------------


def test_the_live_tests_are_marked_live_and_take_the_live_fixture() -> None:
    assert live_acq.pytestmark == pytest.mark.live
    for test in (live_acq.test_acquire_policy, live_acq.test_acquire_suggestions):
        assert "live" in inspect.signature(test).parameters


def test_the_suggestion_cap_holds_every_request_at_its_worst_case(
    host_key: str,
) -> None:
    """Ten requests, each at its worst case, counted (a count as large as
    the body's bytes) or uncounted (the count failed): within the cap."""
    api = FakeApi()
    run = LiveRun("dry", 10.0, wire=httpx2.MockTransport(api))
    fence = Fence.new()
    bodies = [suggest_body(repo, fence) for repo in OSS_CORPUS]
    assert len(OSS_CORPUS) == 10 and all(b is not None for b in bodies)
    for status in (200, 500):
        api.count_status = status
        with ExperimentClient(run) as client:
            api.count = max(len(json.dumps(b)) + 2000 for b in bodies)
            need = sum(client.estimate(b) for b in bodies if b is not None)
        assert need <= live_acq.SUGGEST_CAP_USD
    assert live_acq.SUGGEST_CAP_USD == math.ceil(live_acq.suggest_need() * 100) / 100


@pytest.fixture
def dry_start(host_key: str) -> Iterator[DryStart]:
    start = DryStart(FakeApi())
    yield start
    for run in start.runs:
        assert run.spent_usd <= run.cap_usd


def _dry_index(monkeypatch: pytest.MonkeyPatch, fake: FakeIndex) -> None:
    monkeypatch.setattr(live_acq, "PackageIndex", lambda: index_for(fake))
    monkeypatch.setattr(live_acq, "utc_now", lambda: NOW)


def _healthy_unless(missing: set[str]) -> Callable[[str], Json | None]:
    return lambda name: None if name in missing else project(name)


def test_the_policy_test_body_runs_dry(
    dry_start: DryStart, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    decoys = {canonical(i.name) for i in load_inputs() if i.role == "decoy"}
    fake = FakeIndex()
    fake.fallback = _healthy_unless(decoys)
    fake.add(project("cytoolz", requires_dist=["toolz", "typing_extensions"]))
    _dry_index(monkeypatch, fake)
    results = tmp_path / "r.jsonl"
    recorder = ExperimentRecorder("acquire", {"LIVE_RESULTS_PATH": str(results)})

    live_acq.test_acquire_policy(dry_start, recorder)

    (run,) = dry_start.runs
    assert run.cap_usd == 0.0 and run.records == []
    assert dry_start.api.requests == []
    acquired = [n for n in run.notes if n.startswith("ACQUIRE ") and ": exists " in n]
    assert len(acquired) == 51  # 50 inputs and the one dependency
    assert (
        "ACQUIRE orjson: exists y wheels y/y age 661 osv 0 licence MIT verdict auto-accept"
        in run.notes
    )
    assert any(
        n.startswith("ACQUIRE msgspec: ") and n.endswith("(downloads)")
        for n in run.notes
    )
    assert any(
        n.startswith("ACQUIRE nunpy: exists n ") and "reject" in n for n in run.notes
    )
    assert any(
        n.endswith("[dependency]") and n.startswith("ACQUIRE typing-extensions:")
        for n in run.notes
    )
    assert any(
        n.startswith("ACQUIRE decoys: 10 packages") and "reject 10" in n
        for n in run.notes
    )
    assert run.notes[0].startswith("ACQUIRE popular snapshot 2026-10-24: ")
    rows = [json.loads(line) for line in results.read_text().splitlines()]
    assert {r["arm"] for r in rows} == {"candidate", "decoy", "dependency", "summary"}
    assert [r["item"] for r in rows if r["arm"] == "summary"] == [
        "all",
        "candidates",
        "decoys",
    ]


def test_a_silent_index_fails_the_policy_test_after_recording(
    dry_start: DryStart, monkeypatch: pytest.MonkeyPatch
) -> None:
    def down(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("blocked", request=request)

    clock = Clock()
    monkeypatch.setattr(live_acq, "PackageIndex", lambda: index_for(down, clock))
    recorder = ExperimentRecorder("acquire", {})
    with pytest.raises(AssertionError, match="never answered"):
        live_acq.test_acquire_policy(dry_start, recorder)
    (run,) = dry_start.runs
    assert any("verdict ask-user (index" in n for n in run.notes)


def test_the_suggestion_test_body_runs_dry(
    dry_start: DryStart, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeIndex()
    fake.fallback = _healthy_unless({"fastjsonx"})
    _dry_index(monkeypatch, fake)
    dry_start.api.reply = sonnet_message(suggestions("orjson", "fastjsonx"))
    recorder = ExperimentRecorder("acquire", {})

    live_acq.test_acquire_suggestions(dry_start, recorder)

    (run,) = dry_start.runs
    assert run.cap_usd == live_acq.SUGGEST_CAP_USD
    assert len(run.records) == 10 and run.spent_usd > 0
    assert "SUGGEST tabulate: orjson -> auto-accept" in run.notes
    assert "SUGGEST tabulate: fastjsonx -> reject (exists)" in run.notes
    (summary,) = [r for r in recorder.rows if r.arm == "summary"]
    assert summary.metrics["suggestions"] == 20
    assert summary.metrics["hallucinated_rate"] == 0.5
    assert summary.metrics["withheld"] == 0
    assert run.notes[-1].startswith("SUGGEST summary: 20 suggestions, hallucinated 0.5")


def test_a_refused_suggestion_request_is_recorded_and_the_test_fails(
    dry_start: DryStart, monkeypatch: pytest.MonkeyPatch
) -> None:
    _dry_index(monkeypatch, FakeIndex())
    dry_start.api.status = 401
    recorder = ExperimentRecorder("acquire", {})
    with pytest.raises(AssertionError, match="answered none"):
        live_acq.test_acquire_suggestions(dry_start, recorder)
    (run,) = dry_start.runs
    assert "SUGGEST tabulate: none (http_401)" in run.notes


def test_a_withheld_library_is_noted_and_never_sent(
    dry_start: DryStart, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(live_acq, "suggest_body", lambda repo, fence: None)
    report = live_acq.run_suggestions(
        dry_start,
        index_for(FakeIndex()),
        recorder=ExperimentRecorder("acquire", {}),
        now=NOW,
        repos=OSS_CORPUS[:1],
    )
    assert report.withheld == 1 and dry_start.api.requests == []
    assert report.summary["suggestions"] == 0 and report.summary["withheld"] == 1
    (run,) = dry_start.runs
    assert "SUGGEST tabulate: withheld (holds a boundary token)" in run.notes
