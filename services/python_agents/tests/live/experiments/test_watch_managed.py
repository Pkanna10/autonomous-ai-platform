"""P3 (O18): the Managed Agents WATCH pilot's design, offline.

- **The design pins**: the decision, the worst cases and caps (D24), the
  environment (the arXiv API host only), the agent (Haiku 5.5, bash alone),
  the date-pinned cron, the deployment's budget, task and program, and that
  only engine constants reach the hosted agent.
- **The program** (``SCRIPT``) run here against a fake ``urlopen``: its
  outputs pass the engine's own check, the probe classes, the retries.
- **The readers**: the summary line (from the sandbox's bash output only),
  the overshoot rule, the output check, the state in the metadata, the gate.
- **The dispatches** on a fake Managed Agents wire (``WatchApi``, whose
  hosted session runs the real program): arm, fire, pause, watch, record,
  pull, delete; refusals before any change; every failure path cleans up and
  verifies by listing.
- **The live module** dry, and the CI wiring (a guard that fails until the
  Lead applies the A3-lead patches to ``ci.yml`` and the corpus guards).
"""

from __future__ import annotations

import contextlib
import dataclasses
import inspect
import io
import itertools
import json
import math
import re
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.message import Message
from pathlib import Path
from typing import TypedDict, cast
from urllib.parse import parse_qs, urlsplit

import httpx2
import pytest

from autonomous_ai_agents.clients.cost import response_cost
from autonomous_ai_agents.clients.structured import Fence
from autonomous_ai_agents.common.config import settings
from autonomous_ai_agents.common.errors import BudgetExceeded

from ..conftest import TESTS_DIR, LiveRun
from . import test_watch_managed_live as live_wm
from . import watch_managed as wm
from .arxiv_fetch import Entry, check_url, parse_feed
from .harness import ExperimentClient
from .recorder import ExperimentRecorder
from .test_harness import host_key
from .test_triage import TriageApi
from .triage import HAIKU, triage_params

__all__ = ["host_key"]  # the harness's fixture: the host key over the placeholder

Json = dict[str, object]
SERVICE_DIR = TESTS_DIR.parent
CI_WORKFLOW = TESTS_DIR.parents[2] / ".github" / "workflows" / "ci.yml"
LIVE_MODULE = "tests/live/experiments/test_watch_managed_live.py"
START = datetime(2026, 10, 27, 6, 50, tzinfo=UTC)
IDS = ("2610.01001v1", "2610.01002v2", "2610.01003v1")
TUNNEL_403 = urllib.error.URLError(OSError("Tunnel connection failed: 403 Forbidden"))
USAGES: tuple[Json, ...] = (
    {
        "input_tokens": 3000,
        "output_tokens": 120,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 4000,
    },
    {
        "input_tokens": 500,
        "output_tokens": 30,
        "cache_read_input_tokens": 4000,
        "cache_creation_input_tokens": 0,
    },
)


def iso(at: datetime) -> str:
    return at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def atom(ids: tuple[str, ...] = IDS, *, extra: str = "") -> bytes:
    entries = "".join(
        f"<entry><id>http://arxiv.org/abs/{i}</id>"
        "<published>2026-10-26T17:00:00Z</published>"
        f"<title>Paper {i}</title><summary>We make loop {i} 2x faster.</summary>"
        '<arxiv:primary_category term="cs.PF"/></entry>'
        for i in ids
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        + extra
        + '<feed xmlns="http://www.w3.org/'
        '2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">' + entries + "</feed>"
    ).encode()


class WallClock:
    """A fake UTC clock that the fake sleep advances."""

    def __init__(self, start: datetime = START) -> None:
        self.at = start
        self.sleeps: list[float] = []

    def __call__(self) -> datetime:
        return self.at

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.at += timedelta(seconds=seconds)

    def mono(self) -> float:
        return self.at.timestamp()


# ---------------------------------------------------------------------------
# The program, run here
# ---------------------------------------------------------------------------


class Reply:
    def __init__(self, status: int, body: bytes) -> None:
        self.status, self.body = status, body

    def __enter__(self) -> Reply:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return self.body if size < 0 else self.body[:size]


Opener = Callable[..., Reply]


def opener(
    feed: bytes,
    *,
    blocked: Exception | int = TUNNEL_403,
    statuses: tuple[int, ...] = (200,),
    calls: list[str] | None = None,
) -> Opener:
    left = list(statuses)

    def open_(request: urllib.request.Request, timeout: float) -> Reply:
        url = request.full_url
        assert timeout > 0
        if calls is not None:
            calls.append(url)
        if url == wm.LISTING_URL:
            status = left.pop(0) if len(left) > 1 else left[0]
            if status != 200:
                raise urllib.error.HTTPError(url, status, "busy", Message(), None)
            return Reply(200, feed)
        if url == wm.BLOCKED_URL:
            if isinstance(blocked, Exception):
                raise blocked
            if blocked >= 400:
                raise urllib.error.HTTPError(url, blocked, "no", Message(), None)
            return Reply(blocked, b"simple index")
        raise AssertionError(f"the program opened {url}")

    return open_


def run_script(out: Path, open_: Opener) -> tuple[bytes, bytes, str]:
    """``SCRIPT``'s ``main`` with ``out`` for the outputs directory."""
    space: dict[str, object] = {"__name__": "a3_program"}
    exec(compile(wm.SCRIPT, wm.SCRIPT_NAME, "exec"), space)  # noqa: S102 - our constant
    main = cast(Callable[[str, Opener, Callable[[float], None]], int], space["main"])
    printed = io.StringIO()
    with contextlib.redirect_stdout(printed):
        assert main(str(out), open_, lambda _: None) == 0
    return (
        (out / wm.LISTING_FILE).read_bytes(),
        (out / wm.FEED_FILE).read_bytes(),
        printed.getvalue(),
    )


def tool_events(
    stdout: str, *, command: str = f"python3 {wm.SCRIPT_PATH}"
) -> list[Json]:
    return [
        {
            "type": "agent.tool_use",
            "id": "sevt_use",
            "name": "bash",
            "input": {"command": command},
        },
        {
            "type": "agent.tool_result",
            "id": "sevt_res",
            "tool_use_id": "sevt_use",
            "content": [{"type": "text", "text": stdout}],
        },
    ]


def span(usage: Json) -> Json:
    return {"type": "span.model_request_end", "id": "sevt_span", "model_usage": usage}


def idle(stop: str = "end_turn") -> Json:
    return {
        "type": "session.status_idle",
        "id": "sevt_idle",
        "stop_reason": {"type": stop},
    }


# ---------------------------------------------------------------------------
# The fake Managed Agents wire
# ---------------------------------------------------------------------------


@dataclass
class Fail:
    """Refuse ``count`` requests matching ``method`` and the ``path`` regex,
    after letting ``skip`` of them through; ``drop`` answers none (a
    connection error) instead of a 500."""

    method: str
    path: str
    count: int = 1
    skip: int = 0
    drop: bool = False


def _page(rows: list[Json]) -> httpx2.Response:
    return httpx2.Response(200, json={"data": rows, "next_page": None})


class WatchApi(TriageApi):
    """Environments, agents, deployments, runs, sessions, events and files
    in memory; a deployment that is active when the clock passes its armed
    minute fires one run whose session runs the real program."""

    def __init__(self, clock: WallClock, work: Path) -> None:
        super().__init__()
        self.clock, self.work = clock, work
        self.ids = itertools.count(1)
        self.envs: dict[str, Json] = {}
        self.agents: dict[str, Json] = {}
        self.deployments: dict[str, Json] = {}
        self.runs: list[Json] = []
        self.sessions: dict[str, Json] = {}
        self.events: dict[str, list[Json]] = {}
        self.outputs: dict[str, dict[str, bytes]] = {}
        self.uploads: dict[str, bytes] = {}
        self.fired: set[tuple[str, datetime]] = set()
        self.ma_calls: list[tuple[str, str, Json]] = []
        self.batch_ids: list[str] = []
        # knobs
        self.feed = atom()
        self.blocked: Exception | int = TUNNEL_403
        self.polls = 2
        self.hang = False
        self.hang_after_interrupt = False
        self.cents: str | None = "4"
        self.fire = True
        self.run_error: Json | None = None
        self.env_echo: Json | None = None
        self.env_delete_status = 200
        self.session_delete_status = 200
        self.outputs_missing = False
        self.second_fire: timedelta | None = None
        self.usages: tuple[Json, ...] = USAGES
        self.fail_path: str | None = None
        self.failing: list[Fail] = []
        self.double_fire = False
        self.terminate = False
        self.oversize = False

    # --- helpers ----------------------------------------------------------

    def _id(self, prefix: str) -> str:
        return f"{prefix}_{next(self.ids):04d}"

    def _planned(self, expression: str) -> datetime:
        minute, hour, day, month, _ = expression.split()
        return datetime(
            self.clock().year, int(month), int(day), int(hour), int(minute), tzinfo=UTC
        )

    def _schedule(self, given: Json) -> Json:
        at = self._planned(str(given["expression"]))
        second = at + (self.second_fire or timedelta(days=365))
        return {
            **given,
            "upcoming_runs_at": [iso(at), iso(second)],
            "last_run_at": None,
        }

    def _maybe_fire(self) -> None:
        for dep_id, dep in self.deployments.items():
            if dep["archived_at"] or dep["status"] == "paused" or not self.fire:
                continue
            at = self._planned(str(cast(Json, dep["schedule"])["expression"]))
            if at > self.clock() or (dep_id, at) in self.fired:
                continue
            self.fired.add((dep_id, at))
            run: Json = {
                "type": "deployment_run",
                "id": self._id("drun"),
                "deployment_id": dep_id,
                "agent": dep["agent"],
                "created_at": iso(self.clock()),
                "trigger_context": {"type": "schedule", "scheduled_at": iso(at)},
                "session_id": None,
                "error": self.run_error,
            }
            if self.run_error is None:
                run["session_id"] = self._start(dep)
            self.runs.append(run)
            if self.double_fire:
                self.runs.append(
                    {**run, "id": self._id("drun"), "session_id": self._start(dep)}
                )

    def _start(self, dep: Json) -> str:
        sid = self._id("sesn")
        out = self.work / sid
        out.mkdir(parents=True)
        listing, feed, stdout = run_script(out, opener(self.feed, blocked=self.blocked))
        self.events[sid] = [
            *tool_events(stdout),
            *(span(u) for u in self.usages),
            {"type": "session.status_terminated", "id": "sevt_end"}
            if self.terminate
            else idle(),
        ]
        if self.oversize:
            listing = b" " * (wm.LISTING_MAX_BYTES + 1)
        if not self.outputs_missing:
            self.outputs[sid] = {wm.LISTING_FILE: listing, wm.FEED_FILE: feed}
        usage: Json = {
            "input_tokens": 3500,
            "output_tokens": 150,
            "cache_read_input_tokens": 4000,
            "cache_creation": {
                "ephemeral_5m_input_tokens": 4000,
                "ephemeral_1h_input_tokens": 0,
            },
            "active_seconds": 42.0,
        }
        if self.cents is not None:
            usage["list_cost"] = {"amount": self.cents, "currency": "USD"}
        self.sessions[sid] = {
            "type": "session",
            "id": sid,
            "status": "running",
            "deployment_id": dep["id"],
            "environment_id": dep["environment_id"],
            "agent": {
                "type": "agent",
                "id": cast(Json, dep["agent"])["id"],
                "model": {"id": HAIKU},
            },
            "usage": usage,
            "budget": dep["budget"],
            "metadata": {},
            "_polls": self.polls,
        }
        return sid

    def _session(self, sid: str) -> Json:
        session = self.sessions[sid]
        polls = cast(int, session["_polls"])
        if session["status"] == "running" and not self.hang:
            if polls > 0:
                session["_polls"] = polls - 1
            else:
                session["status"] = "terminated" if self.terminate else "idle"
        return {k: v for k, v in session.items() if not k.startswith("_")}

    def _record(self, request: httpx2.Request) -> Json:
        raw = request.read()
        body = cast(Json, json.loads(raw)) if raw and request.method != "GET" else {}
        self.ma_calls.append((request.method, request.url.path, body))
        return body

    def _missing(self) -> httpx2.Response:
        return self._error(404, "not found")

    # --- routes -----------------------------------------------------------

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        path, method = request.url.path, request.method
        query = {  # a repeated key (``types[]``) joined with commas
            k: ",".join(v)
            for k, v in parse_qs(urlsplit(str(request.url)).query).items()
        }
        for rule in self.failing:
            if rule.method != method or not re.fullmatch(rule.path, path):
                continue
            if rule.skip:
                rule.skip -= 1
            elif rule.count:
                rule.count -= 1
                self.requests.append(request)
                if rule.drop:
                    raise httpx2.ConnectError("dry: no answer", request=request)
                return self._error(500, "dry failure")
        if self.fail_path is not None and path.startswith(self.fail_path):
            self.requests.append(request)
            return self._error(500, "dry failure")
        if path == "/v1/files" and method == "POST":
            self.requests.append(request)
            file_id = self._id("file")
            self.uploads[file_id] = request.read()
            return httpx2.Response(
                200,
                json={
                    "id": file_id,
                    "type": "file",
                    "filename": wm.SCRIPT_NAME,
                    "mime_type": "text/plain",
                    "size_bytes": 1,
                    "created_at": iso(self.clock()),
                },
            )
        if path == "/v1/files" and method == "GET":
            self.requests.append(request)
            sid = query.get("scope_id", "")
            files = [
                {
                    "id": f"file_out_{sid}_{name}",
                    "type": "file",
                    "filename": name,
                    "mime_type": "application/octet-stream",
                    "size_bytes": len(data),
                    "created_at": iso(self.clock()),
                }
                for name, data in self.outputs.get(sid, {}).items()
            ]
            return _page(files)
        if path.startswith("/v1/files/file_out_") and path.endswith("/content"):
            self.requests.append(request)
            _, sid, name = (
                path.removeprefix("/v1/files/file_out_")
                .removesuffix("/content")
                .split("_", 2)
            )
            return httpx2.Response(200, content=self.outputs[f"sesn_{sid}"][name])
        if path.startswith("/v1/files/") and method == "DELETE":
            self.uploads.pop(path.rsplit("/", 1)[1], None)
        if path.endswith("/results") and path.startswith("/v1/messages/batches/"):
            self.requests.append(request)
            lines = [
                {
                    "custom_id": cid,
                    "result": {"type": "succeeded", "message": self.answer({})},
                }
                for cid in self.batch_ids
            ]
            return httpx2.Response(
                200, content="\n".join(json.dumps(x) for x in lines).encode()
            )
        if path == "/v1/messages/batches" and method == "POST":
            self.batch_ids = [
                r["custom_id"] for r in json.loads(request.read())["requests"]
            ]
        for prefix, handler in (
            ("/v1/environments", self._environments),
            ("/v1/agents", self._agents),
            ("/v1/deployment_runs", self._runs),
            ("/v1/deployments", self._deployments),
            ("/v1/sessions", self._sessions),
        ):
            if path.startswith(prefix):
                self.requests.append(request)
                body = self._record(request)
                return handler(
                    path.removeprefix(prefix).strip("/").split("/"), method, body, query
                )
        return super().__call__(request)

    def _environments(
        self, parts: list[str], method: str, body: Json, query: dict[str, str]
    ) -> httpx2.Response:
        if parts == [""] and method == "POST":
            env_id = self._id("env")
            self.envs[env_id] = {
                "type": "environment",
                "id": env_id,
                "name": body["name"],
                "config": self.env_echo
                or {**cast(Json, body["config"]), "packages": {}},
                "metadata": body.get("metadata", {}),
                "archived_at": None,
                "created_at": iso(self.clock()),
                "updated_at": iso(self.clock()),
            }
            return httpx2.Response(200, json=self.envs[env_id])
        if parts == [""]:
            rows = [
                e
                for e in self.envs.values()
                if query.get("include_archived") == "true" or not e["archived_at"]
            ]
            return _page(rows)
        env_id = parts[0]
        if env_id not in self.envs:
            return self._missing()
        if method == "DELETE":
            if self.env_delete_status != 200:
                return self._error(
                    self.env_delete_status, "sessions still reference it"
                )
            del self.envs[env_id]
            return httpx2.Response(204)  # the documented reply: no body
        if parts[1:] == ["archive"]:
            self.envs[env_id]["archived_at"] = iso(self.clock())
        return httpx2.Response(200, json=self.envs[env_id])

    def _agents(
        self, parts: list[str], method: str, body: Json, query: dict[str, str]
    ) -> httpx2.Response:
        if parts == [""] and method == "POST":
            agent_id = self._id("agent")
            self.agents[agent_id] = {
                **body,
                "type": "agent",
                "id": agent_id,
                "version": 1,
                "archived_at": None,
            }
            return httpx2.Response(200, json=self.agents[agent_id])
        if parts == [""]:
            return _page(
                [
                    a
                    for a in self.agents.values()
                    if query.get("include_archived") == "true" or not a["archived_at"]
                ]
            )
        agent = self.agents.get(parts[0])
        if agent is None:
            return self._missing()
        if parts[1:] == ["archive"]:
            agent["archived_at"] = iso(self.clock())
        return httpx2.Response(200, json=agent)

    def _deployments(
        self, parts: list[str], method: str, body: Json, query: dict[str, str]
    ) -> httpx2.Response:
        if parts == [""] and method == "POST":
            dep_id = self._id("depl")
            self.deployments[dep_id] = {
                "type": "deployment",
                "id": dep_id,
                "name": body["name"],
                "agent": {"type": "agent", "id": body["agent"], "version": 1},
                "environment_id": body["environment_id"],
                "initial_events": body["initial_events"],
                "resources": body["resources"],
                "budget": body["budget"],
                "metadata": body["metadata"],
                "schedule": self._schedule(cast(Json, body["schedule"])),
                "status": "active",
                "archived_at": None,
            }
            return httpx2.Response(200, json=self.deployments[dep_id])
        if parts == [""]:
            rows = [
                d
                for d in self.deployments.values()
                if query.get("include_archived") == "true" or not d["archived_at"]
            ]
            return _page(rows)
        dep = self.deployments.get(parts[0])
        if dep is None:
            return self._missing()
        action = parts[1] if len(parts) > 1 else ""
        if action == "pause":
            dep["status"] = "paused"
        elif action == "unpause":
            dep["status"] = "active"
        elif action == "archive":
            dep["archived_at"], dep["status"] = iso(self.clock()), "active"
            cast(Json, dep["schedule"])["upcoming_runs_at"] = []
        elif method == "POST":
            if "schedule" in body:
                dep["schedule"] = self._schedule(cast(Json, body["schedule"]))
            if "resources" in body:
                dep["resources"] = body["resources"]
            if "metadata" in body:
                meta = cast(dict[str, object], dep["metadata"])
                for key, value in cast(Json, body["metadata"]).items():
                    if value is None:
                        meta.pop(key, None)
                    else:
                        meta[key] = value
        return httpx2.Response(200, json=dep)

    def _runs(
        self, parts: list[str], method: str, body: Json, query: dict[str, str]
    ) -> httpx2.Response:
        self._maybe_fire()
        since = (
            parse_iso(query["created_at[gte]"]) if "created_at[gte]" in query else None
        )
        rows = [
            r
            for r in self.runs
            if r["deployment_id"] == query.get("deployment_id")
            and (since is None or parse_iso(str(r["created_at"])) >= since)
        ]
        return _page(rows)

    def _sessions(
        self, parts: list[str], method: str, body: Json, query: dict[str, str]
    ) -> httpx2.Response:
        if parts == [""]:
            dep = query.get("deployment_id")
            return _page(
                [
                    self._session(s)
                    for s, v in list(self.sessions.items())
                    if v["deployment_id"] == dep
                ]
            )
        sid = parts[0]
        if sid not in self.sessions:
            return self._missing()
        if parts[1:] == ["events"] and method == "POST":
            if not self.hang_after_interrupt:
                self.hang = False
                self.sessions[sid]["_polls"] = 0
            return httpx2.Response(200, json={"data": []})
        if parts[1:] == ["events"]:
            events = self.events[sid]
            done = self._session(sid)["status"] != "running"
            events = events if done else events[:-1]
            if "types[]" in query:
                types = query["types[]"].split(",")
                events = [e for e in events if e["type"] in types]
            return _page(events)
        if method == "DELETE":
            if self.sessions[sid]["status"] == "running":
                return self._error(400, "a running session cannot be deleted")
            if self.session_delete_status != 200:
                return self._error(self.session_delete_status, "delete refused")
            del self.sessions[sid]
            self.outputs.pop(sid, None)
            return httpx2.Response(200, json={"id": sid, "type": "session_deleted"})
        return httpx2.Response(200, json=self._session(sid))

    def ma(self, method: str, prefix: str) -> list[Json]:
        return [b for m, p, b in self.ma_calls if m == method and p.startswith(prefix)]


class Line(TypedDict):
    experiment: str
    arm: str
    item: str
    metrics: dict[str, object]


@dataclass
class Rig:
    api: WatchApi
    clock: WallClock
    recorder: ExperimentRecorder
    labels: ExperimentRecorder
    results: Path
    runs: list[LiveRun] = field(default_factory=list)

    def dispatch(
        self, *, cancel: bool = False, cap: float | None = None
    ) -> wm.Dispatch:
        run = LiveRun(
            f"dry-{len(self.runs)}",
            wm.watch_need() if cap is None else cap,
            wire=httpx2.MockTransport(self.api),
        )
        self.runs.append(run)
        with ExperimentClient(
            run, recorder=self.recorder, clock=self.clock.mono, sleep=self.clock.sleep
        ) as client:
            watch = wm.Watch(
                client,
                self.recorder,
                self.labels,
                now=self.clock,
                sleep=self.clock.sleep,
            )
            return watch.dispatch(cancel=cancel)

    def next_day(self) -> None:
        self.clock.at += timedelta(hours=23)

    def rows(self, arm: str | None = None) -> list[Line]:
        lines = [
            cast(Line, json.loads(line))
            for line in self.results.read_text().splitlines()
        ]
        return [line for line in lines if arm is None or line["arm"] == arm]


@pytest.fixture
def rig(tmp_path: Path, host_key: str) -> Iterator[Rig]:
    clock = WallClock()
    results = tmp_path / "results.jsonl"
    env = {"LIVE_RESULTS_PATH": str(results)}
    made = Rig(
        WatchApi(clock, tmp_path / "hosted"),
        clock,
        ExperimentRecorder("A3", env),
        ExperimentRecorder("A3 labels", env),
        results,
    )
    yield made
    for run in made.runs:
        assert run.spent_usd <= run.cap_usd


# ---------------------------------------------------------------------------
# The design pins
# ---------------------------------------------------------------------------


def test_the_decision_names_the_pilot_its_question_and_its_cheapest_arm() -> None:
    assert wm.PILOT == "A3"
    for words in ("P3", "O18", "WATCH", "Haiku 5.5", "Cheapest arm", "worst case"):
        assert words in wm.DECISION, words
    assert wm.MANAGED_AGENTS_BETA == "managed-agents-2026-04-01"


def test_the_hosted_worst_case_is_the_budget_one_maximal_request_and_the_watch() -> (
    None
):
    """D24: one hosted run's worst case is its 25-cent budget, one maximal
    Haiku 5.5 request past it (1M prompt tokens at the long-context 1-hour
    write rate, 128K output) and the running time the watch allows."""
    worst = {
        "input_tokens": 0,
        "output_tokens": 128_000,
        "cache_creation_input_tokens": 1_000_000,
        "cache_creation": {
            "ephemeral_5m_input_tokens": 0,
            "ephemeral_1h_input_tokens": 1_000_000,
        },
    }
    assert (
        wm.REQUEST_WORST_USD
        == response_cost(worst, settings.MODEL_PRICING, model=HAIKU)[0]
    )
    assert wm.REQUEST_WORST_USD == pytest.approx(1.00 + 0.32)
    assert wm.RUNTIME_WORST_USD == pytest.approx((1200 + 120) / 3600 * 0.08)
    assert wm.BUDGET_CENTS == 25 and wm.RUN_GATE_USD == 0.25
    assert wm.HOSTED_RUN_WORST_USD == pytest.approx(
        0.25 + wm.REQUEST_WORST_USD + wm.RUNTIME_WORST_USD
    )
    assert wm.DISPATCH_CAP_USD == pytest.approx(
        wm.HOSTED_RUN_WORST_USD + wm.TRIAGE_CAP_USD
    )
    assert wm.watch_need() == wm.DISPATCH_CAP_USD <= wm.A3_CAP_USD == 3.0
    assert wm.cleanup_need() == wm.HOSTED_RUN_WORST_USD
    assert (
        wm.JOB_MINUTES * 60
        >= (
            wm.ARM_LEAD_S
            + 60
            + wm.JITTER_MAX_S
            + wm.FIRE_MARGIN_S
            + wm.SESSION_WAIT_S
            + wm.INTERRUPT_GRACE_S
            + wm.OUTPUT_TRIES * wm.POLL_S
            + wm.TRIAGE_WAIT_S
        )
        * 1.3
    )


def test_a_full_listing_s_triage_fits_its_cap_with_the_counts_failing(
    host_key: str,
) -> None:
    """Every paper at the longest title and abstract, sync and in a batch,
    with no count (the structural bound): within ``TRIAGE_CAP_USD``."""
    api = TriageApi()
    api.count_status = 500
    run = LiveRun("dry", 100.0, wire=httpx2.MockTransport(api))
    client = ExperimentClient(run)
    longest = Entry("2610.01001v1", "T" * 300, "A" * 3000, "2026-10-26", "cs.PF")
    params = triage_params(longest, Fence.new())
    assert params is not None
    each = client.estimate(params, batch=True) + client.estimate(params)
    assert wm.LISTING_MAX * each <= wm.TRIAGE_CAP_USD
    config = wm.triage_config(wm.LISTING_MAX)
    assert (config.count, config.sync_count, config.resubmit_max) == (50, 50, 0)
    assert config.wait_s == wm.TRIAGE_WAIT_S


def test_the_environment_allows_the_arxiv_api_host_and_nothing_else() -> None:
    config = wm.environment_config()
    assert config == {
        "type": "cloud",
        "networking": {
            "type": "limited",
            "allowed_hosts": ["export.arxiv.org"],
            "allow_package_managers": False,
            "allow_mcp_servers": False,
        },
    }
    assert wm.BLOCKED_HOST not in json.dumps(config)
    assert urlsplit(wm.LISTING_URL).hostname in wm.ALLOWED_HOSTS
    assert urlsplit(wm.BLOCKED_URL).hostname == wm.BLOCKED_HOST == "pypi.org"


def test_the_agent_is_haiku_at_low_effort_offered_bash_alone() -> None:
    params = wm.agent_params()
    assert params["model"] == {"id": "claude-haiku-5-5", "effort": "low"}
    assert set(params) == {
        "name",
        "model",
        "system",
        "tools",
        "metadata",
    }  # no MCP, skills, multiagent
    (toolset,) = cast(list[Json], params["tools"])
    assert toolset["type"] == "agent_toolset_20260401"
    assert toolset["default_config"] == {
        "enabled": False,
        "permission_policy": {"type": "always_allow"},
    }
    assert toolset["configs"] == [
        {"name": "bash", "enabled": True, "permission_policy": {"type": "always_allow"}}
    ]
    assert params["system"] == wm.SYSTEM_PROMPT and params["name"] == wm.NAME
    assert params["metadata"] == {"pilot": "A3", "experiment": "watch_managed"}


def test_the_listing_is_an_allowlisted_arxiv_query_for_the_three_categories() -> None:
    assert check_url(wm.LISTING_URL) == "metadata"
    query = parse_qs(urlsplit(wm.LISTING_URL).query)
    assert query["search_query"] == ["cat:cs.PF OR cat:cs.PL OR cat:cs.DS"]
    assert query["max_results"] == ["50"] and query["sortBy"] == ["submittedDate"]
    assert query["sortOrder"] == ["descending"]


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (
            datetime(2026, 10, 27, 6, 50, tzinfo=UTC),
            datetime(2026, 10, 27, 6, 55, tzinfo=UTC),
        ),
        (
            datetime(2026, 10, 27, 6, 50, 1, tzinfo=UTC),
            datetime(2026, 10, 27, 6, 56, tzinfo=UTC),
        ),
        (
            datetime(2026, 12, 31, 23, 58, tzinfo=UTC),
            datetime(2027, 1, 1, 0, 3, tzinfo=UTC),
        ),
    ],
)
def test_the_cron_is_armed_ahead_and_pinned_to_one_date(
    now: datetime, expected: datetime
) -> None:
    at = wm.fire_time(now)
    assert at == expected and (at - now).total_seconds() >= wm.ARM_LEAD_S
    assert wm.cron_for(at) == f"{at.minute} {at.hour} {at.day} {at.month} *"
    assert wm.schedule(at) == {
        "type": "cron",
        "expression": wm.cron_for(at),
        "timezone": "UTC",
    }


def test_the_deployment_carries_the_budget_the_task_and_the_program() -> None:
    at = datetime(2026, 10, 27, 6, 55, tzinfo=UTC)
    params = wm.deployment_params(
        "env_1", "agent_1", "file_1", at, {"spent_usd": "0.0000"}
    )
    assert params["budget"] == {
        "type": "limit",
        "max_list_cost": {"amount": "25", "currency": "USD"},
    }
    assert params["initial_events"] == [
        {"type": "user.message", "content": [{"type": "text", "text": wm.TASK_TEXT}]}
    ]
    assert params["resources"] == [
        {"type": "file", "file_id": "file_1", "mount_path": f"/{wm.SCRIPT_NAME}"}
    ]
    assert params["schedule"] == wm.schedule(at)
    assert params["metadata"] == {
        "pilot": "A3",
        "experiment": "watch_managed",
        "spent_usd": "0.0000",
    }
    assert (params["agent"], params["environment_id"], params["name"]) == (
        "agent_1",
        "env_1",
        wm.NAME,
    )
    assert "vault_ids" not in params  # no credential reaches a session


def test_only_engine_constants_reach_the_hosted_agent() -> None:
    """The prompt, the task and the program name no path outside the
    session's mounts, and the program prints exactly one line (counts, never
    paper text): no repository content and no abstract reach the model."""
    for text in (wm.SYSTEM_PROMPT, wm.TASK_TEXT):
        for path in re.findall(r"(?<!\S)/\S+", text):
            assert path.startswith("/mnt/session/"), path
    for literal in re.findall(r"[\"'](/[^\"']*)", wm.SCRIPT):
        assert literal.startswith("/mnt/session/"), literal
    assert wm.SCRIPT_PATH in wm.TASK_TEXT
    assert wm.SCRIPT.count("print(") == 1 and "MARK + " in wm.SCRIPT
    compile(wm.SCRIPT, wm.SCRIPT_NAME, "exec")
    assert f"LISTING_URL = {wm.LISTING_URL!r}" in wm.SCRIPT
    assert f"BLOCKED_URL = {wm.BLOCKED_URL!r}" in wm.SCRIPT


def _env(**net: object) -> Json:
    base: Json = {
        "type": "limited",
        "allowed_hosts": ["export.arxiv.org"],
        "allow_package_managers": False,
        "allow_mcp_servers": False,
    }
    base.update(net)
    return {"config": {"type": "cloud", "networking": base, "packages": {"pip": []}}}


@pytest.mark.parametrize(
    ("env", "problem"),
    [
        (_env(), None),
        ({"config": {"type": "self_hosted"}}, "not a cloud"),
        (
            {"config": {"type": "cloud", "networking": {"type": "unrestricted"}}},
            "not limited",
        ),
        (_env(allowed_hosts=["export.arxiv.org", "arxiv.org"]), "allowed_hosts"),
        (_env(allow_package_managers=True), "package managers"),
        (_env(allow_mcp_servers=True), "MCP"),
        (
            {
                "config": {
                    **cast(Json, _env()["config"]),
                    "packages": {"pip": ["requests"]},
                }
            },
            "packages",
        ),
    ],
)
def test_the_environment_is_read_back_before_it_is_trusted(
    env: Json, problem: str | None
) -> None:
    found = wm.networking_problem(env)
    assert (
        (found is None) if problem is None else (found is not None and problem in found)
    )


def _deployment(
    at: datetime,
    *,
    first: timedelta = timedelta(0),
    second: timedelta = timedelta(days=365),
    amount: str = "25",
) -> Json:
    upcoming = [iso(at + first), iso(at + second)]
    return {
        "schedule": {"expression": wm.cron_for(at), "upcoming_runs_at": upcoming},
        "budget": {"max_list_cost": {"amount": amount, "currency": "USD"}},
    }


def test_the_armed_schedule_must_fire_once_at_the_armed_minute() -> None:
    at = datetime(2026, 10, 27, 6, 55, tzinfo=UTC)
    assert wm.schedule_problem(_deployment(at), at) is None
    assert "within the year" in str(
        wm.schedule_problem(_deployment(at, second=timedelta(days=1)), at)
    )
    jittered = _deployment(at, first=timedelta(minutes=9))
    assert wm.schedule_problem(jittered, at) is None  # a listed jitter is fine
    late = _deployment(at, first=timedelta(minutes=15))
    assert "not 2026-10-27T06:55Z" in str(wm.schedule_problem(late, at))
    early = _deployment(at, first=-timedelta(minutes=2))
    assert "not 2026-10-27T06:55Z" in str(wm.schedule_problem(early, at))
    assert "budget" in str(wm.schedule_problem(_deployment(at, amount="2500"), at))
    assert "no upcoming" in str(
        wm.schedule_problem(
            {"schedule": {"expression": wm.cron_for(at), "upcoming_runs_at": []}}, at
        )
    )
    assert "not the armed" in str(wm.schedule_problem({"schedule": None}, at))


# ---------------------------------------------------------------------------
# The program, offline
# ---------------------------------------------------------------------------


def test_the_program_writes_a_listing_the_engine_accepts(tmp_path: Path) -> None:
    calls: list[str] = []
    listing, feed, stdout = run_script(tmp_path, opener(atom(), calls=calls))
    assert calls == [wm.LISTING_URL, wm.BLOCKED_URL]
    check = wm.check_outputs(listing, feed)
    assert check.ok and check.listed == 3 and check.problem is None
    assert [e.arxiv_id for e in check.entries] == list(IDS)
    assert check.entries == parse_feed(atom())
    (line,) = stdout.splitlines()
    report = wm.script_report(tool_events(stdout))
    assert report is not None and line.startswith("A3-RESULT ")
    assert (report.fetch_status, report.entries, report.feed_bytes) == (
        200,
        3,
        len(atom()),
    )
    assert wm.probe_verdict(report) == "refused"
    assert "Paper" not in stdout and "faster" not in stdout  # no paper text


def test_the_program_retries_a_busy_arxiv_then_records_the_failure(
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    run_script(tmp_path / "a", opener(atom(), statuses=(429, 200), calls=calls))
    assert calls == [wm.LISTING_URL, wm.LISTING_URL, wm.BLOCKED_URL]
    listing, feed, stdout = run_script(tmp_path / "b", opener(atom(), statuses=(503,)))
    report = wm.script_report(tool_events(stdout))
    assert report is not None and (report.fetch_status, report.entries) == (503, 0)
    assert feed == b"" and not wm.check_outputs(listing, feed).ok
    _, _, stdout = run_script(
        tmp_path / "c",
        opener(atom(), blocked=TimeoutError("timed out"), statuses=(200,)),
    )
    lost = wm.script_report(tool_events(stdout))
    assert lost is not None and wm.probe_verdict(lost) == "unclear"


def test_the_program_refuses_a_feed_that_declares_a_doctype(tmp_path: Path) -> None:
    hostile = atom(extra='<!DOCTYPE feed [<!ENTITY x "y">]>')
    listing, feed, stdout = run_script(tmp_path, opener(hostile))
    report = wm.script_report(tool_events(stdout))
    assert (
        report is not None
        and report.parse_problem == "ValueError"
        and report.entries == 0
    )
    assert not wm.check_outputs(listing, feed).ok  # the engine's parser refuses it too


@pytest.mark.parametrize(
    ("blocked", "verdict"),
    [
        (TUNNEL_403, "refused"),
        (403, "refused"),
        (200, "reached"),
        (404, "reached"),
        (urllib.error.URLError(OSError("Name or service not known")), "unclear"),
    ],
    ids=["tunnel-403", "http-403", "reached", "reached-404", "dns"],
)
def test_the_probe_classes(
    tmp_path: Path, blocked: Exception | int, verdict: str
) -> None:
    _, _, stdout = run_script(tmp_path, opener(atom(), blocked=blocked))
    assert wm.probe_verdict(wm.script_report(tool_events(stdout))) == verdict


# ---------------------------------------------------------------------------
# The readers
# ---------------------------------------------------------------------------


def _line(**probe: object) -> str:
    report = {
        "version": 1,
        "fetch_status": 200,
        "fetch_error": None,
        "parse_problem": None,
        "feed_bytes": 10,
        "entries": 3,
        "probe": {"url": wm.BLOCKED_URL, "status": None, "error": "403", **probe},
    }
    return "A3-RESULT " + json.dumps(report)


def test_the_summary_line_counts_only_from_the_program_s_own_bash_output() -> None:
    assert wm.probe_verdict(None) == "missing"
    forged: list[Json] = [
        {"type": "agent.message", "content": [{"type": "text", "text": _line()}]}
    ]
    assert wm.script_report(forged) is None
    other = tool_events(_line(), command="echo hi")
    assert wm.script_report(other) is None and not wm.obeyed(other)
    wrapped = tool_events(_line(), command=f"echo; python3 {wm.SCRIPT_PATH}")
    assert wm.script_report(wrapped) is None  # printed by another command
    spaced = tool_events(_line(), command=f"  python3   {wm.SCRIPT_PATH}\n")
    assert wm.script_report(spaced) is not None and wm.obeyed(spaced)
    assert not wm.obeyed([]) and not wm.obeyed([*spaced, *other])
    read: list[Json] = [
        {"type": "agent.tool_use", "id": "x", "name": "read", "input": {}}
    ]
    assert wm.tool_uses(read) == [("x", "read", "")] and not wm.obeyed(read)
    broken = tool_events("A3-RESULT {not json")
    assert wm.script_report(broken) is None
    extra = tool_events(_line().replace('"entries": 3', '"entries": 3, "x": 1'))
    assert wm.script_report(extra) is None  # the strict shape
    twice = [
        *tool_events(_line(status=403, error=None)),
        *tool_events(_line(status=200, error=None)),
    ]
    last = wm.script_report(twice)
    assert last is not None and wm.probe_verdict(last) == "reached"


@pytest.mark.parametrize(
    ("list_cost", "costs", "ok"),
    [
        (0.04, [0.02, 0.02], True),
        (0.27, [0.20, 0.07], True),  # the last request crossed the cap
        (0.27, [0.26, 0.01], False),  # a request began at the cap
        (0.40, [0.24, 0.02], False),  # more than one request's worth past it
        (0.30, [], False),
        (0.255, [], True),  # rounding
    ],
)
def test_the_overshoot_rule(list_cost: float, costs: list[float], ok: bool) -> None:
    assert wm.overshoot_ok(list_cost, 0.25, costs) is ok


def test_request_costs_and_stop_reasons_come_from_the_events() -> None:
    events = [
        span(USAGES[0]),
        span({"input_tokens": -1, "output_tokens": 1}),
        span(USAGES[1]),
        idle("budget_reached"),
    ]
    costs = wm.request_costs(events)
    assert costs == [
        response_cost(u, settings.MODEL_PRICING, model=HAIKU)[0] for u in USAGES
    ]
    assert wm.stop_reason(events) == "budget_reached"
    assert wm.stop_reason([{"type": "session.status_terminated"}]) == "terminated"
    assert wm.stop_reason([{"type": "session.status_idle"}]) == "idle"
    assert wm.stop_reason([]) is None


def _listing(entries: list[str], **changes: object) -> bytes:
    body: Json = {
        "version": 1,
        "query_url": wm.LISTING_URL,
        "fetched_at": "2026-10-27T06:55:30Z",
        "http_status": 200,
        "entries": [
            {
                "arxiv_id": i,
                "title": f"Paper {i}",
                "published": "x",
                "primary_category": "cs.PF",
            }
            for i in entries
        ],
    }
    body.update(changes)
    return json.dumps(body).encode()


@pytest.mark.parametrize(
    ("listing", "feed", "problem"),
    [
        (_listing(list(IDS)), b"", "no feed"),
        (_listing(list(IDS)), b"<feed", "well-formed"),
        (_listing([]), atom(()), "no paper"),
        (None, atom(), "no listing"),
        (b"x" * (wm.LISTING_MAX_BYTES + 1), atom(), "no listing"),
        (b"[]", atom(), "strict shape"),
        (_listing(list(IDS), extra=1), atom(), "strict shape"),
        (
            _listing(list(IDS), query_url="https://export.arxiv.org/api/query"),
            atom(),
            "another query",
        ),
        (_listing(["2613.01001"]), atom(), "bad id"),
        (_listing(list(IDS[:2])), atom(), "disagree"),
        (_listing([*IDS, IDS[0]]), atom(), "disagree"),
    ],
)
def test_the_output_check_refuses(
    listing: bytes | None, feed: bytes, problem: str
) -> None:
    check = wm.check_outputs(listing, feed)
    assert not check.ok and check.problem is not None and problem in check.problem


def _result(index: int, **changes: object) -> wm.RunResult:
    base = wm.RunResult(
        index,
        f"sesn_{index}",
        f"2026-10-2{6 + index}T06:55:00+00:00",
        "end_turn",
        True,
        50,
        "refused",
        0.04,
        True,
    )
    return dataclasses.replace(base, **changes)  # type: ignore[arg-type]


def test_the_state_round_trips_through_the_metadata() -> None:
    state = wm.PilotState(
        (_result(1), _result(2, stop="budget/reached")),
        0.0812,
        START,
        ("sesn_1", "sesn_2"),
    )
    meta = wm.state_metadata(state)
    assert (
        all(len(k) <= 64 and len(v) <= 512 for k, v in meta.items()) and len(meta) <= 16
    )
    back = wm.read_state(meta)
    assert back.runs[0] == state.runs[0] and back.runs[1].stop == "budget_reached"
    assert (back.spent_usd, back.last_fire, back.recorded) == (
        0.0812,
        START,
        ("sesn_1", "sesn_2"),
    )
    assert wm.read_state({"pilot": "A3"}) == wm.PilotState()


@pytest.mark.parametrize(
    "meta",
    [
        {},
        {"pilot": "A2"},
        {"pilot": "A3", "run2": _result(2).summary()},
        {"pilot": "A3", "run1": "listing=1;probe=refused"},
        {
            "pilot": "A3",
            "run1": _result(1).summary().replace("probe=refused", "probe=maybe"),
        },
        {"pilot": "A3", "run1": "listing=1;entries=x y"},
        {"pilot": "A3", "spent_usd": "nan"},
        {"pilot": "A3", "last_fire": "yesterday"},
    ],
)
def test_a_state_that_is_not_ours_is_refused(meta: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        wm.read_state(meta)


@pytest.mark.parametrize(
    ("changes", "passed"),
    [
        ({}, True),
        ({"listing_ok": False}, False),
        ({"probe": "reached"}, False),
        ({"overshoot_ok": False}, False),
        ({"cost_usd": 0.26}, False),
    ],
)
def test_the_gate(changes: dict[str, object], passed: bool) -> None:
    runs = [_result(1), _result(2, probe="unclear"), _result(3, **changes)]
    metrics, note = wm.gate(runs)
    assert metrics["passed"] is passed and note.startswith(
        "A3 gate: " + ("passed" if passed else "failed")
    )
    assert wm.gate(runs[:2])[0]["passed"] is False
    assert (
        wm.gate([_result(i, probe="unclear") for i in (1, 2, 3)])[0]["passed"] is False
    )


# ---------------------------------------------------------------------------
# The dispatches
# ---------------------------------------------------------------------------


def test_the_first_dispatch_creates_arms_watches_records_and_keeps_the_objects(
    rig: Rig,
) -> None:
    report = rig.dispatch()
    api = rig.api
    assert report.failures == [] and report.cleanup is None and report.gate is None
    (env_body,) = api.ma("POST", "/v1/environments")
    assert env_body == {
        "name": wm.NAME,
        "config": wm.environment_config(),
        "metadata": dict(wm.OBJECT_METADATA),
    }
    (agent_body,) = api.ma("POST", "/v1/agents")
    assert agent_body == wm.agent_params()
    dep_body = api.ma("POST", "/v1/deployments")[0]
    at = wm.fire_time(START)
    assert (
        dep_body["schedule"] == wm.schedule(at)
        and dep_body["budget"] == wm.deployment_params("e", "a", "f", at, {})["budget"]
    )
    (upload,) = [
        r for r in api.requests if r.url.path == "/v1/files" and r.method == "POST"
    ]
    assert wm.SCRIPT.encode() in upload.read()
    assert api.uploads == {}  # the program file is deleted after the run
    (dep,) = api.deployments.values()
    assert dep["status"] == "paused" and not dep["archived_at"]
    assert (
        api.sessions == {} and len(api.envs) == 1
    )  # the session is gone, the rest stays
    run = report.run
    assert run is not None and (run.index, run.listing_ok, run.entries, run.probe) == (
        1,
        True,
        3,
        "refused",
    )
    assert run.cost_usd == 0.04 and run.overshoot_ok and run.stop == "end_turn"
    state = wm.read_state(cast(dict[str, str], dep["metadata"]))
    assert state.runs == (run,) and state.recorded == (run.session,)
    assert state.last_fire == at and state.spent_usd >= 0.04
    (hosted,) = [r for r in rig.runs[0].records if r.outcome.startswith("hosted_")]
    assert (hosted.cost_usd, hosted.estimate_usd, hosted.outcome) == (
        0.04,
        wm.HOSTED_RUN_WORST_USD,
        "hosted_end_turn",
    )
    assert (hosted.model, hosted.input_tokens, hosted.cache_write_tokens) == (
        HAIKU,
        3500,
        4000,
    )
    triaged = api.sent()
    assert len(triaged) == 3 and all(
        b["model"] == HAIKU for b in triaged
    )  # sync arm, fenced
    assert all("untrusted_abstract" in json.dumps(b) for b in triaged)
    scoped = [
        r for r in api.requests if r.url.path == "/v1/files" and r.method == "GET"
    ]
    assert scoped and all(
        "managed-agents-2026-04-01" in r.headers["anthropic-beta"] for r in scoped
    )
    labels = [r for r in rig.rows("label")]
    assert len(labels) == 3
    row = rig.rows("run1")[0]["metrics"]
    assert (row["probe"], row["obeyed"], row["tools"], row["tool_calls"]) == (
        "refused",
        True,
        "bash",
        1,
    )
    assert row["model_requests"] == 2


def test_a_second_dispatch_within_the_day_is_refused_before_any_change(
    rig: Rig,
) -> None:
    rig.dispatch()
    before = len(rig.api.ma_calls)
    rig.clock.at += timedelta(hours=5)
    with pytest.raises(wm.WatchRefusedError, match="a run a day"):
        rig.dispatch()
    assert all(m == "GET" for m, _, _ in rig.api.ma_calls[before:])


def test_three_daily_dispatches_pass_the_gate_and_clean_up_verified(rig: Rig) -> None:
    reports = []
    for _ in range(3):
        reports.append(rig.dispatch())
        rig.next_day()
    first, second, third = reports
    assert first.cleanup is None and second.cleanup is None
    assert [r.run.index for r in reports if r.run] == [1, 2, 3]
    assert third.gate is not None and third.gate[0]["passed"] is True
    cleanup = third.cleanup
    assert cleanup is not None and cleanup.verified and cleanup.reason == "finished"
    assert cleanup.environment == "deleted" and cleanup.late_records == []
    api = rig.api
    assert api.envs == {} and api.sessions == {}
    assert all(d["archived_at"] for d in api.deployments.values())
    assert all(a["archived_at"] for a in api.agents.values())
    assert len(api.ma("POST", "/v1/environments")) == 1  # created once
    updates = [b for b in api.ma("POST", "/v1/deployments/") if "schedule" in b]
    assert len(updates) == 2  # re-armed on days 2 and 3
    assert rig.rows("summary")[0]["metrics"]["passed"] is True
    assert rig.rows("cleanup")[0]["metrics"]["verified"] is True
    with pytest.raises(wm.WatchRefusedError, match="finished"):
        rig.dispatch()


def _cleaned(report: wm.Dispatch, rig: Rig) -> wm.CleanupReport:
    cleanup = report.cleanup
    assert cleanup is not None and cleanup.verified, cleanup
    assert rig.api.envs == {} and rig.api.sessions == {}
    assert all(d["archived_at"] for d in rig.api.deployments.values())
    assert all(a["archived_at"] for a in rig.api.agents.values())
    return cleanup


def test_a_run_without_its_listing_fails_and_cleans_up(rig: Rig) -> None:
    rig.api.outputs_missing = True
    report = rig.dispatch()
    assert report.run is not None and not report.run.listing_ok
    assert any("fetched no listing" in f for f in report.failures)
    assert _cleaned(report, rig).reason == "a run failed"
    assert report.gate is not None and report.gate[0]["passed"] is False
    assert rig.api.sent() == []  # nothing to triage


def test_a_run_that_fails_to_start_cleans_up(rig: Rig) -> None:
    rig.api.run_error = {"type": "session_rate_limited_error", "message": "slow down"}
    report = rig.dispatch()
    assert report.run is None and "session_rate_limited_error" in report.failures[0]
    _cleaned(report, rig)


def test_no_fire_by_the_deadline_cleans_up(rig: Rig) -> None:
    rig.api.fire = False
    report = rig.dispatch()
    assert "no run fired" in report.failures[0]
    _cleaned(report, rig)


def test_a_session_that_overruns_is_interrupted_then_recorded(rig: Rig) -> None:
    rig.api.hang = True
    report = rig.dispatch()
    assert report.failures == [] and report.run is not None
    interrupts = rig.api.ma("POST", "/v1/sessions/")
    assert interrupts == [{"events": [{"type": "user.interrupt"}]}]
    assert any("interrupted after 1200 s" in n for n in rig.runs[0].notes)


def test_a_session_that_never_stops_fails_and_stays_listed(rig: Rig) -> None:
    rig.api.hang = rig.api.hang_after_interrupt = True
    report = rig.dispatch()
    assert "did not stop" in report.failures[0]
    cleanup = report.cleanup
    assert cleanup is not None and not cleanup.verified and cleanup.sessions_left
    assert cleanup.late_records == cleanup.sessions_left  # its cost reached the ledger
    assert any(r.outcome == "hosted_late" for r in rig.runs[0].records)


def test_cancel_records_a_session_no_ledger_saw_then_cleans_up(rig: Rig) -> None:
    rig.dispatch()
    rig.api.cents = "9"
    rig.api._start(
        next(iter(rig.api.deployments.values()))
    )  # a dispatch died watching it
    rig.next_day()
    report = rig.dispatch(cancel=True, cap=wm.cleanup_need())
    assert report.mode == "cancel" and report.run is None
    cleanup = _cleaned(report, rig)
    assert cleanup.reason == "cancelled" and len(cleanup.late_records) == 1
    (late,) = [r for r in rig.runs[1].records if r.outcome == "hosted_late"]
    assert late.estimate_usd == wm.HOSTED_RUN_WORST_USD


def test_cancel_with_nothing_on_the_account_is_verified(rig: Rig) -> None:
    report = rig.dispatch(cancel=True, cap=wm.cleanup_need())
    assert report.cleanup is not None and report.cleanup.verified
    assert report.cleanup.environment == "none"


def test_the_pilot_cap_refuses_a_dispatch_that_could_pass_it(rig: Rig) -> None:
    rig.dispatch()
    dep = next(iter(rig.api.deployments.values()))
    cast(dict[str, str], dep["metadata"])["spent_usd"] = "1.5000"
    rig.next_day()
    with pytest.raises(wm.WatchRefusedError, match="A3_CAP_USD"):
        rig.dispatch()


def test_the_reservation_refuses_before_anything_is_created(rig: Rig) -> None:
    with pytest.raises(BudgetExceeded):
        rig.dispatch(cap=wm.HOSTED_RUN_WORST_USD - 0.01)
    assert all(m == "GET" for m, _, _ in rig.api.ma_calls)
    assert not rig.api.uploads and rig.api.envs == {}


def test_a_triage_the_budget_refuses_fails_the_run_and_cleans_up(rig: Rig) -> None:
    """A hosted run that spends nearly all its reservation leaves fifty
    papers' triage reservation refused: the dispatch records the refusal,
    archives, deletes and lists to verify."""
    rig.api.feed = atom(tuple(f"2610.{n:05d}v1" for n in range(1001, 1051)))
    rig.api.cents = str(math.floor(wm.HOSTED_RUN_WORST_USD * 100))
    report = rig.dispatch(cap=wm.HOSTED_RUN_WORST_USD)
    assert report.run is not None and report.run.listing_ok
    assert any("triage" in f and "BudgetExceeded" in f for f in report.failures)
    assert _cleaned(report, rig).reason == "a run failed"
    assert report.gate is not None and report.gate[0]["passed"] is False
    assert rig.api.sent() == []  # nothing sent past the refused reservation
    assert any("failure: triage" in n for n in rig.runs[0].notes)


def test_a_triage_refused_after_spending_keeps_its_spend_and_cleans_up(
    rig: Rig,
) -> None:
    """Batch results off the API host are refused after the sync arm spent:
    that spend still joins the pilot's state, and the pilot cleans up."""
    rig.api.results_url = "https://evil.example/results"
    report = rig.dispatch()
    assert any("triage" in f and "ExperimentRefusedError" in f for f in report.failures)
    _cleaned(report, rig)
    (dep,) = rig.api.deployments.values()
    saved = float(cast(dict[str, str], dep["metadata"])["spent_usd"])
    assert rig.api.sent() and saved == pytest.approx(rig.runs[0].spent_usd, abs=1e-4)


def test_an_unexpected_triage_error_cleans_up_then_raises(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_: object, **__: object) -> None:
        raise RuntimeError("dry: triage broke")

    monkeypatch.setattr(wm, "run_triage", broken)
    with pytest.raises(RuntimeError, match="triage broke"):
        rig.dispatch()
    assert rig.api.envs == {} and rig.api.sessions == {}
    assert all(d["archived_at"] for d in rig.api.deployments.values())


def test_an_environment_whose_delete_is_refused_is_archived(rig: Rig) -> None:
    rig.api.outputs_missing = True
    rig.api.env_delete_status = 409
    report = rig.dispatch()
    cleanup = report.cleanup
    assert (
        cleanup is not None and cleanup.verified and cleanup.environment == "archived"
    )
    assert any("delete environment" in p for p in cleanup.problems)


def test_a_misconfigured_environment_stops_before_any_deployment(rig: Rig) -> None:
    rig.api.env_echo = {"type": "cloud", "networking": {"type": "unrestricted"}}
    report = rig.dispatch()
    assert "not limited" in report.failures[0]
    assert rig.api.deployments == {} and rig.api.ma("POST", "/v1/agents") == []
    _cleaned(report, rig)


def test_a_schedule_that_would_fire_twice_stops_and_cleans_up(rig: Rig) -> None:
    rig.api.second_fire = timedelta(days=1)
    report = rig.dispatch()
    assert "within the year" in report.failures[0]
    _cleaned(report, rig)
    assert rig.api.runs == []


def test_a_leftover_session_fails_the_dispatch_and_is_recorded(rig: Rig) -> None:
    rig.dispatch()
    rig.api.session_delete_status = 500
    rig.next_day()
    report = rig.dispatch()
    assert "not verified deleted" in report.failures[0]
    rig.api.session_delete_status = 200
    rig.next_day()
    leftover = rig.dispatch(cancel=True, cap=wm.cleanup_need())
    assert (
        leftover.cleanup is not None and leftover.cleanup.late_records == []
    )  # in a ledger already


def test_a_state_that_cannot_be_read_cleans_up(rig: Rig) -> None:
    rig.dispatch()
    dep = next(iter(rig.api.deployments.values()))
    cast(dict[str, str], dep["metadata"])["run1"] = "garbage"
    rig.next_day()
    report = rig.dispatch()
    assert report.failures and report.failures[0].startswith("run 1")
    _cleaned(report, rig)


def test_an_unexpected_error_cleans_up_then_propagates(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_: object) -> tuple[bytes | None, bytes | None]:
        raise RuntimeError("bug")

    monkeypatch.setattr(wm.Watch, "_outputs", boom)
    with pytest.raises(RuntimeError, match="bug"):
        rig.dispatch()
    assert rig.api.envs == {} and rig.api.sessions == {}
    assert rig.rows("cleanup")[0]["metrics"]["reason"] == "aborted"


def test_an_api_failure_mid_run_cleans_up(rig: Rig) -> None:
    rig.dispatch()
    rig.next_day()
    rig.api.fail_path = "/v1/deployments/"  # the re-arm update is refused
    report = rig.dispatch()
    assert report.failures and "ExperimentAPIError" in report.failures[0]
    rig.api.fail_path = None


def test_transient_failures_are_absorbed_and_the_run_goes_on(rig: Rig) -> None:
    """A refused poll, pause, status read (no answer at all), output listing
    or state save is noted or retried; the run still passes, and the next
    day's re-arm finds the deployment active (no unpause needed)."""
    rig.api.failing = [
        Fail("GET", r"/v1/deployment_runs"),
        Fail("POST", r"/v1/deployments/depl_\d+/pause"),
        Fail("GET", r"/v1/sessions/sesn_\d+", drop=True),
        Fail("GET", r"/v1/files"),
        Fail("POST", r"/v1/deployments/depl_\d+", skip=1),  # the triage's save
    ]
    report = rig.dispatch()
    assert report.failures == [] and report.run is not None and report.run.listing_ok
    notes = rig.runs[0].notes
    assert any("not paused" in n for n in notes)
    assert any("triage spend not saved" in n for n in notes)
    assert all(rule.count == 0 for rule in rig.api.failing)
    (dep,) = rig.api.deployments.values()
    assert dep["status"] == "active"
    rig.next_day()
    second = rig.dispatch()
    assert second.failures == [] and second.run is not None and second.run.index == 2
    assert rig.api.ma("POST", "/v1/deployments/depl_") and not [
        p for _, p, _ in rig.api.ma_calls if p.endswith("/unpause")
    ]


def test_two_runs_for_one_arming_fail_and_both_sessions_are_recorded(
    rig: Rig,
) -> None:
    rig.api.double_fire = True
    report = rig.dispatch()
    assert report.run is None and "2 runs fired" in report.failures[0]
    cleanup = _cleaned(report, rig)
    assert len(cleanup.late_records) == 2 == len(cleanup.deleted_sessions)
    late = [r for r in rig.runs[0].records if r.outcome == "hosted_late"]
    assert len(late) == 2 and all(r.cost_usd == 0.04 for r in late)


def test_a_long_transcript_still_shows_its_stop(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The stop is read from the status events alone: a transcript longer
    than ``EVENTS_MAX`` neither hides it nor stalls the watch."""
    monkeypatch.setattr(wm, "EVENTS_MAX", 3)  # 5 events a dry session
    report = rig.dispatch()
    assert report.failures == [] and report.run is not None
    assert report.run.stop == "end_turn" and report.run.listing_ok
    assert not rig.api.ma("POST", "/v1/sessions/")  # never interrupted
    assert any("up to EVENTS_MAX" in n for n in rig.runs[0].notes)
    stops = [
        r
        for r in rig.api.requests
        if r.url.path.endswith("/events") and "types" in str(r.url)
    ]
    assert stops and all(
        parse_qs(urlsplit(str(r.url)).query)["types[]"] == list(wm.STOP_EVENTS)
        for r in stops
    )


def test_a_terminated_session_is_recorded_as_terminated(rig: Rig) -> None:
    rig.api.terminate = True
    report = rig.dispatch()
    assert report.failures == [] and report.run is not None
    assert report.run.stop == "terminated" and rig.api.sessions == {}


@pytest.mark.parametrize(
    ("knob", "note"),
    [("oversize", "is over"), ("download", "not downloaded")],
)
def test_outputs_that_cannot_be_read_fail_the_run(
    rig: Rig, knob: str, note: str
) -> None:
    if knob == "oversize":
        rig.api.oversize = True
    else:
        rig.api.failing = [Fail("GET", r"/v1/files/file_out_.*_listing\.json/content")]
    report = rig.dispatch()
    assert report.run is not None and not report.run.listing_ok
    assert any("no listing" in f for f in report.failures)
    assert any(note in n for n in rig.runs[0].notes)
    _cleaned(report, rig)


@pytest.mark.parametrize(
    ("change", "problem"),
    [("second-environment", "2 environment(s)"), ("rewired", "another environment")],
)
def test_objects_that_are_not_one_pilot_are_cleaned_up(
    rig: Rig, change: str, problem: str
) -> None:
    rig.dispatch()
    (env,) = rig.api.envs.values()
    if change == "second-environment":
        rig.api.envs["env_9999"] = {**env, "id": "env_9999"}
    else:
        next(iter(rig.api.deployments.values()))["environment_id"] = "env_other"
    rig.next_day()
    report = rig.dispatch()
    assert report.run is None and problem in report.failures[0]
    _cleaned(report, rig)


def test_a_pilot_that_has_its_runs_is_refused(rig: Rig) -> None:
    rig.dispatch()
    meta = cast(dict[str, str], next(iter(rig.api.deployments.values()))["metadata"])
    meta.update({f"run{i}": _result(i).summary() for i in (2, 3)})
    rig.next_day()
    with pytest.raises(wm.WatchRefusedError, match="has its 3 runs"):
        rig.dispatch()


def test_an_interrupt_that_is_refused_leaves_the_session_failed(rig: Rig) -> None:
    rig.api.hang = True
    rig.api.failing = [Fail("POST", r"/v1/sessions/sesn_\d+/events", count=99)]
    report = rig.dispatch()
    assert "did not stop" in report.failures[0]
    assert any("interrupt refused" in n for n in rig.runs[0].notes)


@pytest.mark.parametrize(
    ("rules", "env_status", "verified", "environment", "problem"),
    [
        ([Fail("GET", r"/v1/deployments", skip=1)], 200, False, "unread", "listing"),
        ([Fail("GET", r"/v1/deployments", skip=2)], 200, False, "unread", "verif"),
        ([Fail("GET", r"/v1/sessions")], 200, True, "deleted", "sessions not"),
        (
            [Fail("POST", r"/v1/environments/env_\d+/archive")],
            409,
            False,
            "left",
            "archive environment",
        ),
    ],
    ids=["unlisted", "unverified", "sessions-unlisted", "environment-left"],
)
def test_a_cleanup_that_cannot_finish_says_so_and_a_cancel_recovers(
    rig: Rig,
    rules: list[Fail],
    env_status: int,
    verified: bool,
    environment: str,
    problem: str,
) -> None:
    rig.api.outputs_missing = True
    rig.api.failing = rules
    rig.api.env_delete_status = env_status
    report = rig.dispatch()
    cleanup = report.cleanup
    assert cleanup is not None and cleanup.verified is verified
    assert cleanup.environment == environment
    assert any(problem in p for p in cleanup.problems), cleanup.problems
    assert rig.rows("cleanup")[0]["metrics"]["verified"] is verified
    rig.api.env_delete_status = 200
    rig.next_day()
    again = rig.dispatch(cancel=True, cap=wm.cleanup_need())
    assert again.cleanup is not None and again.cleanup.verified


def test_a_late_record_past_the_cap_is_noted_and_the_cleanup_goes_on(
    rig: Rig,
) -> None:
    rig.dispatch()
    rig.api.cents = "9"
    rig.api._start(next(iter(rig.api.deployments.values())))
    rig.next_day()
    report = rig.dispatch(cancel=True, cap=0.05)
    cleanup = _cleaned(report, rig)
    assert any("budget overrun" in p for p in cleanup.problems)
    assert len(cleanup.late_records) == 1
    over = rig.runs.pop()  # the fixture's cap check: this run is over by design
    assert over.spent_usd == pytest.approx(0.09) and over.spent_usd > over.cap_usd


def test_the_readers_of_the_api_s_shapes() -> None:
    assert wm._dump({"id": "x"}) == {"id": "x"}
    assert wm._text(None) == "" and wm._text("text") == ""
    assert wm._cents({"list_cost": {"amount": "4", "currency": "EUR"}}) is None
    assert wm._cents({"list_cost": {"amount": "4.5", "currency": "USD"}}) is None
    assert wm._cents({}) is None
    assert wm._cents({"list_cost": {"amount": "12", "currency": "USD"}}) == 12
    usage: Json = {
        "input_tokens": 5,
        "output_tokens": True,
        "cache_creation": {
            "ephemeral_5m_input_tokens": 2,
            "ephemeral_1h_input_tokens": 3,
        },
    }
    assert wm._tokens(usage) == (5, 0, 0, 5)
    noisy = tool_events("starting\n" + _line())
    assert wm.script_report(noisy) is not None
    empty = [*tool_events(_line())[:1], {**tool_events("")[1], "content": None}]
    assert wm.script_report(empty) is None


# ---------------------------------------------------------------------------
# The live module, dry
# ---------------------------------------------------------------------------


def test_the_live_test_is_marked_live_and_takes_the_live_fixture() -> None:
    assert live_wm.pytestmark == pytest.mark.live
    assert "live" in inspect.signature(live_wm.test_a3_watch).parameters
    assert live_wm.watch_cap({}) == wm.watch_need()
    assert live_wm.watch_cap({live_wm.CANCEL_ENV: "1"}) == wm.cleanup_need()
    with pytest.raises(ValueError, match=live_wm.CANCEL_ENV):
        live_wm.watch_cap({live_wm.CANCEL_ENV: "yes"})


def test_the_live_body_runs_dry(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    def start(cap: float) -> LiveRun:
        run = LiveRun(f"dry-{len(rig.runs)}", cap, wire=httpx2.MockTransport(rig.api))
        rig.runs.append(run)
        return run

    monkeypatch.setattr(live_wm, "utc_now", rig.clock)
    monkeypatch.setattr(live_wm, "pause", rig.clock.sleep)
    monkeypatch.delenv(live_wm.CANCEL_ENV, raising=False)
    live_wm.test_a3_watch(start, rig.recorder, rig.labels)
    assert rig.runs[0].cap_usd == wm.watch_need()
    monkeypatch.setenv(live_wm.CANCEL_ENV, "1")
    live_wm.test_a3_watch(start, rig.recorder, rig.labels)
    assert rig.runs[1].cap_usd == wm.cleanup_need() and rig.api.envs == {}


# ---------------------------------------------------------------------------
# The CI wiring (fails until the Lead applies the A3-lead patches)
# ---------------------------------------------------------------------------


def _ci_run_step() -> str:
    text = CI_WORKFLOW.read_text(encoding="utf-8")
    start = text.index("      - name: Run live tests")
    return text[start : text.index("      - name: Upload live corpus", start)]


def test_ci_runs_the_watch_suites_with_room_for_their_caps() -> None:
    """``watch`` (one hosted run a dispatch) and ``watch-cleanup`` (cleanup
    only, ``LIVE_WATCH_CANCEL=1``) run this pilot's live module alone, each
    need its cap (D24), under Step 2's noise rule; ``watch`` with its own
    timeout."""
    step = _ci_run_step()
    for suite, need in (
        ("watch", wm.watch_need()),
        ("watch-cleanup", wm.cleanup_need()),
    ):
        found = re.search(
            rf"^ *{suite}\) paths=\({re.escape(LIVE_MODULE)}\); need=(\d+) ;;$",
            step,
            re.M,
        )
        assert found is not None, "apply the A3-lead ci.yml patch"
        assert need <= int(found.group(1)) < need + 1
        rule = re.search(rf"^ *(.*\b{suite}\b.*)\) noise_rule=(\w+) ;;$", step, re.M)
        assert rule is not None and rule.group(2) == "step2"
        assert f"{suite} {found.group(1)}" in CI_WORKFLOW.read_text(encoding="utf-8")
    assert re.search(
        r'^ *if \[ "\$\{INPUT_SUITE\}" = watch-cleanup \]; then\n.*\n *export LIVE_WATCH_CANCEL=1$',
        step,
        re.M,
    )
    text = CI_WORKFLOW.read_text(encoding="utf-8")
    assert f"inputs.suite == 'watch' && {wm.JOB_MINUTES}" in text
    assert (SERVICE_DIR / LIVE_MODULE).exists()


def test_the_corpus_guards_know_the_suites() -> None:
    guards = (TESTS_DIR / "live" / "test_corpus_guards.py").read_text(encoding="utf-8")
    assert '    "watch",\n    "watch-cleanup",\n' in guards, (
        "apply the A3-lead test_corpus_guards patch"
    )
    assert '"watch": watch.watch_need(),' in guards
    assert '"watch-cleanup": watch.cleanup_need(),' in guards
    assert f'"watch": {wm.JOB_MINUTES},' in guards
