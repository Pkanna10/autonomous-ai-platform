"""The raw-SDK client for the Window 0 experiments (live, CI only).

``ExperimentClient(run)`` is the real SDK client built like
``AnthropicTransport``: the key from the settings the ``live`` fixture
restored from ``HOST_KEY``, ``ENGINE_API_BASE_URL``, ``max_retries=0``,
redirects off, and the run's ``CapturingTransport`` behind a
``HostPinnedTransport`` that refuses any request that is not https to the
engine host (so a ``results_url`` the SDK follows can never carry the key
elsewhere). Every paid call is checked against ``run.budget`` before it is
sent with a worst case (``bounds.worst_case_usd``) and priced after
(``bounds.price_message``) into ``run.records``, so the suite ledger and
cost table hold it.

The prompt bound is ``count_tokens`` (the largest over the chain, server
tools stripped, since it refuses them) plus ``cost.count_margin`` plus what
the count cannot see (``bounds.count_extras``); with no count, the
structure (``bounds.structural_tokens``), and never for a PDF. Document and
image sources of type ``file`` or ``url`` are refused: send them inline.

Docs relied on (platform.claude.com/docs, read 2026-10-23): batch-processing
(``fallbacks`` and ``stream`` are rejected per request; errored, canceled
and expired requests are not billed; at most 24 hours; ``results_url``);
files (operations free; ``client.beta.files`` sends no beta header from SDK
1.2.0); models (``capabilities``, ``max_input_tokens``,
``allowed_fallback_models``); pricing (code execution container time:
1,550 free hours a month, then $0.05 an hour, not priced here, a container
is noted in the run). The bound's assumptions are listed in ``bounds``.
"""

from __future__ import annotations

import json
import math
import re
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Final, TypeVar, cast
from urllib.parse import urlsplit

import anthropic
import httpx2
from anthropic.types.beta import BetaMessage
from anthropic.types.beta.message_count_tokens_params import MessageCountTokensParams
from anthropic.types.beta.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.beta.messages.batch_create_params import Request
from pydantic import BaseModel

from autonomous_ai_agents.clients.cost import count_margin
from autonomous_ai_agents.common.config import Settings, settings
from autonomous_ai_agents.common.errors import BudgetExceeded

from ..conftest import LiveRun, RequestRecord, usage_tokens
from .bounds import (
    ExperimentRefusedError,
    Json,
    ToolAllowance,
    UploadedFile,
    billed_models,
    check_sources,
    count_body,
    count_extras,
    has_pdf,
    pdf_pages,
    price_message,
    server_allowance,
    structural_tokens,
    worst_case_usd,
)
from .recorder import ExperimentRecorder, Metric, excerpt

MAX_WAIT_S: Final = 5.5 * 3600  # a GitHub job stops at 6 hours
PLACEHOLDER_KEYS: Final = ("your-api-key-here", "test-key-12345")
_COUNT_KEYS: Final = frozenset(
    MessageCountTokensParams.__required_keys__
    | MessageCountTokensParams.__optional_keys__
)
_CUSTOM_ID: Final = r"[A-Za-z0-9_-]{1,64}"
_FILE_NAME: Final = r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}"
T = TypeVar("T")


class ExperimentAPIError(Exception):
    """A free call the API refused or never answered (status ``None``)."""

    def __init__(self, status: int | None, text: str) -> None:
        super().__init__(text)
        self.status = status


class HostRefusedError(httpx2.TransportError):
    """A request to anything but https on the engine host; never sent."""


class HostPinnedTransport(httpx2.BaseTransport):
    """Forwards only https requests to ``base_url``'s host and port."""

    def __init__(
        self, inner: httpx2.BaseTransport, base_url: str, run: LiveRun
    ) -> None:
        parts = urlsplit(base_url)
        self._inner, self._run = inner, run
        self._host, self._port = parts.hostname, parts.port or 443

    def handle_request(self, request: httpx2.Request) -> httpx2.Response:
        url = request.url
        if (
            url.scheme != "https"
            or url.host != self._host
            or (url.port or 443) != self._port
        ):
            where = excerpt(f"{url.scheme}://{url.host}:{url.port or ''}", limit=120)
            self._run.note(f"refused a request to {where}: not the engine host")
            raise HostRefusedError(f"refused a request to {where}", request=request)
        return self._inner.handle_request(request)

    def close(self) -> None:
        self._inner.close()


@dataclass(frozen=True)
class Answer:
    """One paid call: the HTTP status (``None``: no answer), the message,
    a redacted error excerpt, what it was charged and its worst case."""

    status: int | None
    message: BetaMessage | None
    error: str | None
    cost_usd: float
    estimate_usd: float
    outcome: str  # stop reason, http_<status>, no_answer, unpriced, lost, errored...

    @property
    def accepted(self) -> bool:
        return self.message is not None


@dataclass(frozen=True)
class BatchItem:
    custom_id: str
    params: Json
    allowance: ToolAllowance | None = None  # required with server tools


@dataclass
class Batch:
    batch_id: str
    estimates: dict[str, float]
    models: dict[str, str]
    status: str = "in_progress"
    settled: set[str] = field(default_factory=set)


def _dump(value: object) -> object:
    """SDK objects (content blocks echoed back) as the API wrote them."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", by_alias=True, exclude_none=True)
    raise TypeError(f"{type(value).__name__} is not JSON")


def _plain(params: Mapping[str, object]) -> Json:
    """The body as plain JSON (what is bounded is exactly what is sent),
    refused when it streams or holds a source no count can size."""
    try:
        body = cast(
            Json, json.loads(json.dumps(params, allow_nan=False, default=_dump))
        )
    except (TypeError, ValueError) as exc:
        raise ExperimentRefusedError(
            f"the request is not JSON: {type(exc).__name__}"
        ) from None
    if "stream" in body:
        raise ExperimentRefusedError("stream is not supported: send without it")
    check_sources(body)
    return body


def _api_text(exc: anthropic.APIError) -> tuple[int | None, str]:
    """Status and the API's own reason; never the request or its headers."""
    if not isinstance(exc, anthropic.APIStatusError):
        return None, f"no answer: {type(exc).__name__}"
    body = exc.body if isinstance(exc.body, Mapping) else {}
    error = body.get("error")
    error = error if isinstance(error, Mapping) else {}
    return (
        exc.status_code,
        f"HTTP {exc.status_code}: {error.get('type')}: {error.get('message')}",
    )


class ExperimentClient:
    """The SDK for experiments, every paid call bounded, priced and recorded.

    Use it as a context manager: ``close`` (idempotent) deletes uploads still
    listed and charges each uncollected batch request its worst case once
    (left pending, its batch id in the results). ``sdk`` and ``wire`` are
    exposed for tests only."""

    def __init__(
        self,
        run: LiveRun,
        cfg: Settings = settings,
        *,
        recorder: ExperimentRecorder | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        secret = cfg.ANTHROPIC_API_KEY
        key = "" if secret is None else secret.get_secret_value()
        if not key.strip():
            raise ExperimentRefusedError("ANTHROPIC_API_KEY is not set")
        if any(placeholder in key for placeholder in PLACEHOLDER_KEYS):
            raise ExperimentRefusedError(
                "ANTHROPIC_API_KEY holds a placeholder, not the host key"
            )
        self.run, self.recorder, self._key = run, recorder, key
        self._clock, self._sleep = clock, sleep
        self._prices = MappingProxyType(dict(cfg.MODEL_PRICING))
        self._host = urlsplit(cfg.ENGINE_API_BASE_URL).hostname
        self.wire = HostPinnedTransport(run.capture, cfg.ENGINE_API_BASE_URL, run)
        self.sdk = anthropic.Anthropic(
            api_key=key,
            base_url=cfg.ENGINE_API_BASE_URL,
            max_retries=0,
            timeout=httpx2.Timeout(
                cfg.LLM_TIMEOUT_S, connect=min(10.0, cfg.LLM_TIMEOUT_S)
            ),
            http_client=anthropic.DefaultHttpxClient(
                transport=self.wire, follow_redirects=False
            ),
        )
        self.files: dict[str, UploadedFile] = {}
        self.batches: list[Batch] = []
        if recorder is not None:
            recorder.secrets.add(key)

    def __repr__(self) -> str:
        return f"ExperimentClient(run={self.run.test!r})"

    def __enter__(self) -> ExperimentClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @property
    def reserved_usd(self) -> float:
        """The worst case of every batch request not yet collected."""
        return math.fsum(
            e
            for b in self.batches
            for i, e in b.estimates.items()
            if i not in b.settled
        )

    def close(self) -> None:
        for file_id in list(self.files):
            self.delete(file_id)
        for batch in self.batches:
            pending = sorted(set(batch.estimates) - batch.settled)
            for custom_id in pending:
                try:
                    self._charge(
                        batch.models[custom_id],
                        batch.estimates[custom_id],
                        batch.estimates[custom_id],
                        "batch_pending",
                        None,
                        None,
                        settle=(batch, custom_id),
                    )
                except BudgetExceeded as exc:  # recorded; close must finish
                    self.run.note(
                        f"budget overrun while closing: {excerpt(str(exc), secrets=(self._key,))}"
                    )
            if pending:
                self._log(batch, "pending")
                self.run.note(
                    f"batch {batch.batch_id}: {len(pending)} request(s) not collected, charged their worst case"
                )

    def _error(self, exc: anthropic.APIError) -> tuple[int | None, str]:
        status, text = _api_text(exc)
        return status, excerpt(text, secrets=(self._key,))

    # --- paid calls -------------------------------------------------------

    def estimate(
        self,
        params: Mapping[str, object],
        *,
        allowance: ToolAllowance | None = None,
        batch: bool = False,
        count: bool = True,
    ) -> float:
        """The worst case of ``params``; raises ``ExperimentRefusedError``
        when it cannot be bounded (nothing paid is sent)."""
        body = _plain(params)
        tools = body.get("tools")
        allowed = server_allowance(
            tools if isinstance(tools, list) else [], batch=batch, explicit=allowance
        )
        models = billed_models(body)
        counts = (
            [self.count_tokens({**body, "model": m}) for m in dict.fromkeys(models)]
            if count
            else [None]
        )
        if None not in counts:
            counted = max(cast(list[int], counts))
            prompt = counted + count_margin(counted) + count_extras(body)
        elif has_pdf(body):
            raise ExperimentRefusedError(
                "a PDF needs count_tokens, which did not answer"
            )
        else:
            prompt = structural_tokens(body, self.files)
        return worst_case_usd(
            body, prompt, self._prices, allowance=allowed, batch=batch
        )

    def messages(
        self, params: Mapping[str, object], *, allowance: ToolAllowance | None = None
    ) -> Answer:
        """One ``beta.messages.create``, bounded and recorded. An HTTP
        refusal or a lost answer comes back as an ``Answer``; before the send
        ``ExperimentRefusedError`` or ``BudgetExceeded`` (nothing sent);
        after it, any other exception is charged the worst case, then raised."""
        body = _plain(params)
        estimate = self.estimate(body, allowance=allowance)
        self.run.budget.check(estimate + self.reserved_usd)
        model = billed_models(body)[0]
        try:
            reply = self.sdk.beta.messages.create(
                **cast(MessageCreateParamsNonStreaming, body)
            )
        except anthropic.APIStatusError as exc:
            status, text = self._error(exc)
            return self._charge(model, 0.0, estimate, f"http_{status}", status, text)
        except anthropic.APIError as exc:
            _, text = self._error(exc)
            return self._charge(model, estimate, estimate, "no_answer", None, text)
        except json.JSONDecodeError:
            return self._charge(
                model, estimate, estimate, "unreadable", 200, "the 2xx body is not JSON"
            )
        except Exception:
            self._charge(model, estimate, estimate, "lost", None, None)
            raise
        return self._priced(reply, model, estimate, batch=False)

    def _priced(
        self,
        message: BetaMessage,
        model: str,
        estimate: float,
        *,
        batch: bool,
        settle: tuple[Batch, str] | None = None,
    ) -> Answer:
        """Price and record an answer. Total: an unreadable usage is charged
        the worst case as ``unpriced``; any other failure as ``lost``, then
        re-raised."""
        try:
            usd, outcome = (
                price_message(message, self._prices, batch=batch),
                str(message.stop_reason),
            )
            tokens = usage_tokens(message.usage)
            served = str(message.model)
        except ValueError:
            usd, outcome, tokens, served = estimate, "unpriced", (0, 0, 0, 0), model
        except Exception:
            self._charge(model, estimate, estimate, "lost", None, None, settle=settle)
            raise
        self._record(
            RequestRecord(served, *tokens, usd, estimate, outcome), sum(tokens), settle
        )
        if message.container is not None:  # container time is billed apart
            self.run.note(
                f"code execution container {excerpt(str(message.container.id), limit=64)}"
            )
        return Answer(200, message, None, usd, estimate, outcome)

    def _charge(
        self,
        model: str,
        usd: float,
        estimate: float,
        outcome: str,
        status: int | None,
        error: str | None,
        *,
        settle: tuple[Batch, str] | None = None,
    ) -> Answer:
        self._record(
            RequestRecord(model, 0, 0, 0, 0, usd, estimate, outcome), 0, settle
        )
        return Answer(status, None, error, usd, estimate, outcome)

    def _record(
        self, record: RequestRecord, tokens: int, settle: tuple[Batch, str] | None
    ) -> None:
        """Into the run ledger, the batch request settled, then the budget
        (which may raise once the money is already recorded)."""
        self.run.records.append(record)
        if settle is not None:
            settle[0].settled.add(settle[1])
        self.run.budget.record(record.cost_usd, tokens)

    # --- batches ----------------------------------------------------------

    def submit(
        self,
        items: Sequence[BatchItem],
        *,
        betas: Sequence[str] = (),
        count: bool = True,
    ) -> Batch:
        """Create a batch; its worst case is reserved until it is collected.
        An item with server tools needs an explicit ``allowance``."""
        ids = [item.custom_id for item in items]
        if not items:
            raise ExperimentRefusedError("a batch needs at least one request")
        if len(set(ids)) != len(ids):
            raise ExperimentRefusedError("custom_id values must be unique")
        if not all(re.fullmatch(_CUSTOM_ID, i) for i in ids):
            raise ExperimentRefusedError("a custom_id is 1-64 letters, digits, - or _")
        if any("betas" in item.params for item in items):
            raise ExperimentRefusedError(
                "betas go on submit(betas=...), not in a request's params"
            )
        estimates = {
            i.custom_id: self.estimate(
                i.params, allowance=i.allowance, batch=True, count=count
            )
            for i in items
        }
        self.run.budget.check(math.fsum(estimates.values()) + self.reserved_usd)
        requests = [
            cast(Request, {"custom_id": i.custom_id, "params": _plain(i.params)})
            for i in items
        ]
        try:
            created = self.sdk.beta.messages.batches.create(
                requests=requests, betas=list(betas) or anthropic.omit
            )
        except anthropic.APIError as exc:
            status, text = self._error(exc)
            raise ExperimentAPIError(status, text) from None
        models = {i.custom_id: billed_models(i.params)[0] for i in items}
        batch = Batch(created.id, estimates, models, created.processing_status)
        self.batches.append(batch)
        self._log(batch, "submitted")
        return batch

    def wait(self, batch: Batch, *, timeout_s: float, poll_s: float = 30.0) -> str:
        """Poll until the batch ends or ``timeout_s`` passes; its last status."""
        if not 0 <= timeout_s <= MAX_WAIT_S or not poll_s > 0:
            raise ValueError(
                f"timeout_s must be within 0..{MAX_WAIT_S:g} and poll_s > 0"
            )
        deadline = self._clock() + timeout_s
        while True:
            try:
                batch.status = self.sdk.beta.messages.batches.retrieve(
                    batch.batch_id
                ).processing_status
            except anthropic.APIError:
                pass  # a transient failure: the next poll asks again
            left = deadline - self._clock()
            if batch.status == "ended" or left <= 0:
                break
            self._sleep(min(poll_s, left))
        if batch.status != "ended":
            self._log(batch, "pending")
        return batch.status

    def results(self, batch: Batch) -> dict[str, Answer]:
        """Price every result of an ended batch once (unknown ids ignored);
        a request with no result is charged its worst case. A request is
        settled only once it is charged."""
        if batch.status != "ended":
            raise ValueError(f"batch {batch.batch_id} has not ended: {batch.status}")
        retrieved = self._free(
            lambda: self.sdk.beta.messages.batches.retrieve(batch.batch_id)
        )
        url = retrieved.results_url or ""
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.hostname != self._host:
            raise ExperimentRefusedError(
                f"batch results at {excerpt(url, limit=80)!r} are not on {self._host}"
            )
        entries = self._free(
            lambda: list(self.sdk.beta.messages.batches.results(batch.batch_id))
        )
        answers: dict[str, Answer] = {}
        for entry in entries:
            custom_id, result = entry.custom_id, entry.result
            if custom_id not in batch.estimates or custom_id in batch.settled:
                continue
            model, estimate, settle = (
                batch.models[custom_id],
                batch.estimates[custom_id],
                (batch, custom_id),
            )
            if result.type == "succeeded":
                answers[custom_id] = self._priced(
                    result.message, model, estimate, batch=True, settle=settle
                )
                continue
            reason = getattr(getattr(result, "error", None), "error", None)
            text = excerpt(
                f"{getattr(reason, 'type', None)}: {getattr(reason, 'message', None)}",
                secrets=(self._key,),
            )
            answers[custom_id] = self._charge(
                model, 0.0, estimate, result.type, None, text, settle=settle
            )
        for custom_id in sorted(set(batch.estimates) - batch.settled):
            estimate = batch.estimates[custom_id]
            answers[custom_id] = self._charge(
                batch.models[custom_id],
                estimate,
                estimate,
                "batch_missing",
                None,
                None,
                settle=(batch, custom_id),
            )
        return answers

    def cancel(self, batch: Batch) -> None:
        self._free(lambda: self.sdk.beta.messages.batches.cancel(batch.batch_id))

    def _log(self, batch: Batch, status: str) -> None:
        if self.recorder is not None:
            metrics: dict[str, Metric] = {
                "status": status,
                "processing": batch.status,
                "requests": len(batch.estimates),
            }
            self.recorder.record("harness", "batch", batch.batch_id, metrics)

    # --- free calls -------------------------------------------------------

    def _free(self, call: Callable[[], T]) -> T:
        try:
            return call()
        except anthropic.APIError as exc:
            status, text = self._error(exc)
        raise ExperimentAPIError(status, text)  # outside the handler: no context

    def count_tokens(self, params: Mapping[str, object]) -> int | None:
        """``count_tokens`` for ``params["model"]`` with server tools
        stripped; ``None`` when it fails or counts nothing."""
        body = count_body(_plain(params), _COUNT_KEYS)
        try:
            reply = self._free(
                lambda: self.sdk.beta.messages.count_tokens(
                    **cast(MessageCountTokensParams, body)
                )
            )
        except ExperimentAPIError:
            return None
        counted: object = reply.input_tokens
        return (
            counted
            if isinstance(counted, int)
            and not isinstance(counted, bool)
            and counted > 0
            else None
        )

    def models_get(self, model_id: str) -> Json:
        """``GET /v1/models/{id}`` as JSON (capabilities, limits, fallbacks)."""
        return self._free(lambda: self.sdk.beta.models.retrieve(model_id)).model_dump(
            mode="json"
        )

    def upload(self, filename: str, data: bytes, mime_type: str) -> UploadedFile:
        """Upload a file (for code execution's ``container_upload``; document
        and image blocks must be inline)."""
        if not re.fullmatch(_FILE_NAME, filename):
            raise ExperimentRefusedError(
                f"file name {excerpt(filename, limit=40)!r} is not a plain name"
            )
        meta = self._free(
            lambda: self.sdk.beta.files.upload(file=(filename, data, mime_type))
        )
        pages = pdf_pages(data) if mime_type == "application/pdf" else None
        uploaded = UploadedFile(meta.id, mime_type, len(data), pages)
        self.files[uploaded.file_id] = uploaded
        return uploaded

    def delete(self, file_id: str) -> bool:
        """Delete an upload; a failure is noted in the run, never raised."""
        try:
            self._free(lambda: self.sdk.beta.files.delete(file_id))
        except ExperimentAPIError as exc:
            self.run.note(f"file {file_id} not deleted: {exc}")
            return False
        self.files.pop(file_id, None)
        return True

    @contextmanager
    def uploaded(
        self, filename: str, data: bytes, mime_type: str
    ) -> Iterator[UploadedFile]:
        """An upload deleted in ``finally``, whatever the block does."""
        file = self.upload(filename, data, mime_type)
        try:
            yield file
        finally:
            self.delete(file.file_id)
