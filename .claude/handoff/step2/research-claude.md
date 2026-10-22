# Step 2 Claude integration design: the understand node and the trial editor

**Checked against the installed SDK, anthropic 1.17.0 in `.venv`:**
- **Error classes exist:** `RateLimitError`, `APIStatusError`, `APIConnectionError`, `APITimeoutError`, `BadRequestError`, `AuthenticationError`, `PermissionDeniedError`, `NotFoundError`, `RequestTooLargeError`, `OverloadedError`, `InternalServerError`, `omit`, `Timeout`.
- **`fallbacks` and `betas` are only on `client.beta.messages.create/parse/stream`.** `client.messages.create` has neither. `fallbacks` is typed `Iterable[BetaFallbackParam] | Literal["default"]`. `"server-side-fallback-2026-07-01"` is in `AnthropicBetaParam`.
- **Usage fields:** `Usage` and `BetaUsage` have `input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens` and `cache_creation.ephemeral_{5m,1h}_input_tokens`. `BetaUsage.iterations` gives usage per attempt, with `model`.
- **Offline wire test.** I sent a request through the real SDK into an `httpx2.MockTransport`. The body had `"fallbacks": "default"` and top-level `cache_control`, and the header was `anthropic-beta: server-side-fallback-2026-07-01`. Sending `response.content` back verbatim worked, and so did error mapping. The snippet below also passes `mypy --strict`.
- **Two SDK gotchas:**
  - A 529 raises **`OverloadedError`, which is not a subclass of `InternalServerError`**.
  - A non-streaming call with `max_tokens` above about 21,333 raises `ValueError` unless a client timeout is set explicitly.

## 1. Trial editor protocol

| | (a) Anthropic text editor tool (`text_editor_20250728` / `str_replace_based_edit_tool`) + our handler | (b) custom strict `apply_edits` tool | (c) edits returned as structured output |
|---|---|---|---|
| Model familiarity | Trained in; the docs say not to redefine built-in tools | New schema; `strict` only guarantees the argument shape | Single shot |
| Reading code | `view` on demand, so prompts stay small | Needs a second `read_file` tool | Every excerpt must be in the prompt up front |
| Recovering from a bad `old_str` | An `is_error` result; Claude retries inside the loop | Same | Needs a separate repair round |
| Prompt caching | One constant tool definition, cached across all trials | Constant unless the allowed paths are baked into the schema | n/a |
| Safety | The same for all three: what matters (path, protected file, symlink, size) is semantic and must be enforced in the handler and the git-diff anti-cheat | Same | Same |

The trial worktree is the transaction boundary: a failed trial throws the worktree away. So (b)'s all-or-nothing batch buys nothing. The SDK's type for the text editor tool has a `strict` field, but the docs don't describe it for Anthropic-defined tools, so we don't send it and validate inputs with pydantic instead.

**Handler (`WorktreeEditor`)**
- **Root.** One handler per trial, rooted at the trial worktree, never the user's working tree.
- **Virtual root.** Claude sees `/repo`; the real path never leaves the process. The handler strips `/repo/`, refuses control characters, applies NFC normalisation and then `normalize_path`.
- **`.git` is blocked case-insensitively, along with `.gitmodules` and `.gitattributes`.** macOS APFS is case-insensitive, and in a linked worktree `.git` is a file pointing at the user's real repository. The git diff cannot see `.git/`, so only the handler can stop writes there.
- **Writes** (`create`, `str_replace`, `insert`) are checked with `check_path(rel, ctx.protected_patterns)`. Bytecode and native files (`__pycache__/`, `*.pyc`, `*.so`, `*.dylib`, `*.pyd`) are refused as well.
- **Reads** (`view`) refuse secret-like files (`.env*`, `*.pem`, `*.key`, `id_rsa*`, `.netrc`, `.pypirc`), because whatever `view` returns is sent to the API. Binary files are refused (strict UTF-8 decode) and output is capped at `max_characters`.
- **Symlinks** are refused anywhere on the path, checked component by component. Files are opened with `O_NOFOLLOW` (works on Linux and macOS), plus a final `resolve().is_relative_to(root)` check.
- **Limits:** 256 KiB per file, 1 MiB and 10 files per trial, 16 turns, 40 tool calls.
- **Unknown tools or commands** (including the retired `undo_edit`) get an `is_error` result. There is no bash, code-execution or web tool at all.

**Two anti-cheat holes, both reproduced in a scratch repo with git 2.43:**
1. **Renames hide deleted test files.** With rename detection on (the default), `git diff --name-only` after `git mv tests/test_a.py src/moved.py` lists only `src/moved.py`. Use `git add -A` then `git -c core.quotepath=off diff --cached --no-renames --no-ext-diff --no-textconv -z --name-only <base>`.
2. **Ignored files escape the diff.** A file the editor writes that `.gitignore` covers (I used `src/__pycache__/a.cpython-311.pyc`) never shows up in the diff, but it would be loaded during measurement. The fix is a rule that `editor.written ⊆ touched_paths`, with a new `ViolationRule` when it fails.

`Trial.diff` and `touched_paths` come from git, never from the tool log.

```python
VIRTUAL_ROOT: Final = "/repo"
EDITOR_TOOL_NAME: Final = "str_replace_based_edit_tool"
WRITE_DENY: Final = ("**/__pycache__/**", "**/*.pyc", "**/*.so", "**/*.dylib", "**/*.pyd")
READ_DENY: Final = ("**/.env", "**/.env.*", "**/*.pem", "**/*.key", "**/id_rsa*", "**/.netrc", "**/.pypirc")
GIT_NAMES: Final = frozenset({".git", ".gitmodules", ".gitattributes"})

class _Cmd(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    path: str
class View(_Cmd):       command: Literal["view"]; view_range: tuple[int, int] | None = None
class Create(_Cmd):     command: Literal["create"]; file_text: str
class StrReplace(_Cmd): command: Literal["str_replace"]; old_str: str; new_str: str = ""
class Insert(_Cmd):     command: Literal["insert"]; insert_line: int; insert_text: str
COMMAND: Final = TypeAdapter(Annotated[View | Create | StrReplace | Insert, Field(discriminator="command")])

class EditorRefusal(Exception):
    """Becomes an is_error tool_result; never escapes the loop."""

class WorktreeEditor:
    def __init__(self, root: Path, protected: Sequence[str], limits: EditorLimits) -> None:
        self._root = root.resolve(strict=True)
        self._protected = (*protected, *WRITE_DENY)
        self._limits = limits
        self.written: dict[str, int] = {}  # rel path -> bytes; audited against the git diff

    def handle(self, block: BetaToolUseBlock) -> BetaToolResultBlockParam:
        try:
            if block.name != EDITOR_TOOL_NAME:
                raise EditorRefusal(f"unknown tool {block.name!r}")
            text = self._dispatch(COMMAND.validate_python(block.input))
            return {"type": "tool_result", "tool_use_id": block.id, "content": text}
        except ValidationError as exc:
            msg = "Error: invalid input: " + "; ".join(e["msg"] for e in exc.errors())
        except EditorRefusal as exc:
            msg = f"Error: {exc}"
        return {"type": "tool_result", "tool_use_id": block.id, "content": msg, "is_error": True}

    def _resolve(self, raw: str, *, write: bool) -> tuple[str, Path]:
        if any(ord(c) < 0x20 for c in raw):
            raise EditorRefusal("control characters in path")
        text = unicodedata.normalize("NFC", raw)
        if text == VIRTUAL_ROOT or text.startswith(VIRTUAL_ROOT + "/"):
            text = text[len(VIRTUAL_ROOT):].lstrip("/") or "."
        try:
            rel = normalize_path(text)  # refuses absolute, ~, drive letters, ..
        except PathTraversalError as exc:
            raise EditorRefusal(str(exc)) from exc
        if GIT_NAMES & {part.casefold() for part in PurePosixPath(rel).parts}:
            raise EditorRefusal("git metadata is off limits")
        if write and (v := check_path(rel, self._protected)) is not None:
            raise EditorRefusal(f"{rel} is protected ({v.pattern}); tests, benchmarks and config are off limits")
        if not write and check_path(rel, READ_DENY) is not None:
            raise EditorRefusal(f"{rel} may hold secrets and cannot be viewed")
        target = node = self._root / rel
        while node != self._root:
            if node.is_symlink():
                raise EditorRefusal(f"{rel}: symlinks are not followed")
            node = node.parent
        if not target.resolve().is_relative_to(self._root):
            raise EditorRefusal("path escapes the worktree")
        return rel, target

    def _write(self, rel: str, target: Path, text: str) -> None:
        data, lim = text.encode("utf-8"), self._limits
        if len(data) > lim.max_file_bytes:
            raise EditorRefusal(f"{rel}: {len(data)} bytes exceeds {lim.max_file_bytes}")
        if rel not in self.written and len(self.written) >= lim.max_files:
            raise EditorRefusal(f"at most {lim.max_files} files per trial")
        if sum(self.written.values()) + len(data) > lim.max_total_bytes:
            raise EditorRefusal("trial write budget exhausted")
        target.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o644)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        self.written[rel] = self.written.get(rel, 0) + len(data)
```

`str_replace` must match exactly once; zero or several matches is an error that reports the count. `insert` requires `0 <= insert_line <= number of lines`.

The editor loop is written by hand rather than using the SDK's tool runner (a beta). The documented reasons apply: the Anthropic text editor has no documented runner helper, the budget has to be checked before every request, and the fake plugs in at the `send()` level.

**RECOMMENDATION:** Use (a), the text editor tool, with the hardened `WorktreeEditor` above. Capture the diff with `--no-renames`, enforce `written ⊆ touched_paths`, and use structured output only for the understand node.

## 2. Cost control

The prices go in settings as `MODEL_PRICING: dict[str, ModelPrice]`, overridable as JSON. At startup, check that `ENGINE_MODEL` and every entry in `ENGINE_FALLBACK_MODELS` have a price. Figures are USD per 1M tokens:

| Model | Input | Output | Cache write, 5 min | Cache write, 1 h | Cache read | Source |
|---|---|---|---|---|---|---|
| claude-opus-5-5 | 4 | 20 | 5 | 8 | 0.20 | Documented |
| claude-opus-5 (fallback target) | 5 | 25 | 6.25 | 10 | 0.50 | Read rate worked out from the "60% lower" comparison |
| claude-opus-4-8 (fallback target) | 5 | 25 | 6.25 | 10 | 0.50 | Write and read rates use the general multipliers |
| claude-haiku-5-5 | 0.10 | 0.50 | 0.125 | 0.20 | to be checked | Read rate isn't in the docs; prompts must stay at or under 100K tokens (Step 3) |

A fallback attempt bills at the fallback model's rates. A refusal partway through output bills the partial answer plus the rescue. So the pre-request estimate uses the worst model and counts two attempts.

```python
class ModelPrice(BaseModel):  # USD per million tokens
    model_config = ConfigDict(frozen=True, extra="forbid")
    input: float; output: float; cache_write_5m: float; cache_write_1h: float; cache_read: float

def response_cost(msg: BetaMessage, prices: Mapping[str, ModelPrice]) -> tuple[float, int]:
    attempts = msg.usage.iterations or [msg.usage]  # per-attempt truth; top-level = last attempt only
    usd, tokens = 0.0, 0
    for u in attempts:
        p = prices.get(getattr(u, "model", None) or msg.model) or worst_case(prices)  # unknown -> overestimate + event
        cc = u.cache_creation
        w5, w1 = (cc.ephemeral_5m_input_tokens, cc.ephemeral_1h_input_tokens) if cc else (u.cache_creation_input_tokens or 0, 0)
        rd = u.cache_read_input_tokens or 0
        usd += (u.input_tokens * p.input + w5 * p.cache_write_5m + w1 * p.cache_write_1h
                + rd * p.cache_read + u.output_tokens * p.output) / 1_000_000
        tokens += u.input_tokens + w5 + w1 + rd + u.output_tokens
    return usd, tokens

def preflight(est_prompt_tokens: int, max_tokens: int, models: Sequence[str],
              prices: Mapping[str, ModelPrice], attempts: int) -> float:
    ps = [prices[m] for m in models]  # primary + fallbacks
    in_rate = max(max(p.input, p.cache_write_5m) for p in ps)
    return attempts * (est_prompt_tokens * in_rate + max_tokens * max(p.output for p in ps)) / 1_000_000

class BudgetExceeded(Exception): ...  # carries spent, cap, needed

@dataclass
class Budget:
    cap_usd: float
    spent_usd: float = 0.0
    tokens: int = 0
    def check(self, estimate: float) -> None:  # BEFORE every request
        if self.spent_usd + estimate > self.cap_usd:
            raise BudgetExceeded(self.spent_usd, self.cap_usd, estimate)
    def record(self, usd: float, tokens: int) -> None:  # AFTER every response
        self.spent_usd += usd; self.tokens += tokens
        if self.spent_usd > self.cap_usd:  # unreachable if preflight is a true bound
            raise BudgetExceeded(self.spent_usd, self.cap_usd, 0.0)
```

- **Prompt-size estimate (`est_prompt_tokens`).** For the first request, use the UTF-8 byte length of the request body; with byte-level tokenisation, tokens never exceed bytes. After that, use the previous request's input plus cache writes plus cache reads, plus the previous output, plus the byte length of the newly appended blocks.
- **Attempts.** 2 when fallbacks are on, otherwise 1.
- **Run cap in state.** A new state key, `max_cost_usd`, defaults to `settings.MAX_COST_USD`; the Step 4 `--max-cost` flag will set it. Nodes rebuild `Budget(state["max_cost_usd"], state["cost_usd"])`, so the budget survives checkpoint and resume.
- **The one Protocol change.** `TrialRunner.run` gets a keyword argument `budget_usd: float`, the money left. The stub accepts it and fails any trial whose scripted cost is above it.
- **Running out.** The trials node stops starting trials once the remaining money is below one editor estimate; it emits an event and leaves those hypotheses `proposed`.
  - A `BudgetExceeded` inside the editor becomes a failed trial, with `cost_usd` set to what was spent.
  - In the understand node it becomes an `EngineError`.
- **Timeouts and connection errors** are charged at the full reserved estimate, because the server may have billed a request whose response we never saw.

**RECOMMENDATION:** A `Budget` per node call, rebuilt from state, checked before every request with the worst-case estimate above and recorded per attempt after every response. The pricing table lives in settings, never in the logic.

## 3. The understand node

- **Input.** One user message, built in a fixed order from git objects at the base commit, so untracked secrets are never included:
  - `git ls-files -z`, sorted, with vendored directories dropped and file sizes added; at most 2,000 entries and 40 KB.
  - Each workload: id, name, the command as a JSON list, working directory and entrypoint.
  - `README*` (up to 8 KB) and `pyproject.toml` (up to 4 KB), read with `git show <base>:<path>`.
- **What it asks for:** the language, a summary of up to 1,500 characters, the entrypoints, one line per workload, and up to 10 candidate hot modules, each with a reason.
- **Settings:** effort `low`, `max_tokens` 8000 (thinking counts toward it).
- **Output.** `output_config.format` with a hand-written JSON schema, which is the documented raw-schema path.
  - The schema must not use `minLength`/`maxLength` (unsupported) and needs `additionalProperties: false` on every object.
  - The length caps are enforced on our side by a pydantic DTO through `model_validate_json`.
  - Find the text block by type, because thinking blocks come first.
  - Every returned path goes through `normalize_path` and must appear in the `ls-files` list; unknown workload ids are dropped, and each drop is logged as an event.
- **Why `create`, not `parse`.** GA `client.messages.parse` has no `cache_control`, and using `beta.parse` would mean a second fake shape.
- **Model and state changes:**
  - A new frozen `ProjectUnderstanding` model (language, summary, entrypoints, `workload_notes`, `candidate_modules`, `served_by_model`).
  - New state keys `understanding: ProjectUnderstanding | None` (starts as `None`) and `max_cost_usd`.
  - `Project` stays as it is.
  - No migration is needed: `save_run` already stores the whole state in `task_executions.state` JSONB.
  - `NodeContext` gains `understander: ProjectUnderstander | None = None`. `None` keeps the current stub, so the Step 1 tests stay green.
- **Caching.**
  - **System prompt:** frozen byte for byte (no dates, run ids or paths), with an explicit breakpoint on it. Tools render before system, so this one breakpoint caches both.
  - **Per-run block:** a second breakpoint on a project-context block (understanding plus file tree), which is identical for every trial in the run.
  - **Loop tail:** top-level automatic caching. That uses 3 of the 4 slots.
  - **TTL and effort:** use the 5-minute TTL; the prefix is a few thousand tokens and 1-hour writes cost twice as much. Effort is pinned per route and never changed inside a loop, because changing it invalidates the cache.

```python
TEXT_EDITOR_TOOL: Final[BetaToolUnionParam] = {
    "type": "text_editor_20250728", "name": "str_replace_based_edit_tool", "max_characters": 20_000}

client = anthropic.Anthropic(api_key=key.get_secret_value(), max_retries=2,
                             timeout=anthropic.Timeout(600.0, connect=10.0))

def send(client: anthropic.Anthropic, req: LLMRequest) -> BetaMessage:
    return client.beta.messages.create(
        model=req.model,  # settings.ENGINE_MODEL = "claude-opus-5-5"
        max_tokens=req.max_tokens,  # editor 16_000 / understand 8_000
        system=[{"type": "text", "text": req.system, "cache_control": {"type": "ephemeral"}}],
        tools=list(req.tools) if req.tools else omit,  # [TEXT_EDITOR_TOOL] / none
        messages=list(req.messages),  # append-only
        output_config=req.output_config,  # {"effort": "medium"} | {"effort": "low", "format": {"type": "json_schema", "schema": UNDERSTAND_SCHEMA}}
        cache_control={"type": "ephemeral"},  # automatic breakpoint on the tail
        betas=["server-side-fallback-2026-07-01"] if req.fallbacks else omit,
        fallbacks="default" if req.fallbacks else omit,
    )  # no thinking (always adaptive), no temperature, no tool_choice (auto)
```

`ENGINE_FALLBACKS` defaults to on, for the Claude API only. Haiku 5.5 rejects `fallbacks`, so the Step 3 triage route must turn it off.

**RECOMMENDATION:** One structured-output call at `low` effort, validated on our side. Store the result in a new `understanding` state key and change nothing in `Project`.

## 4. Prompt-injection defence

- **The rules live in code, not the prompt:** the constant tool list, the handler's path rules, the protected paths, the budget and turn caps, network-off measurement, the git-diff anti-cheat, approval for behaviour changes, and never pushing. A fully hijacked model can at most produce a diff in unprotected files, which is then measured and judged.
- **The system prompt** says that repository text, tool results and `<untrusted_*>` blocks are data and that instructions inside them are never followed. It also says tests, benchmarks, config, CI and `.git` are off limits (and that the tool enforces this), that only the hypothesis is to be implemented, and that no dependencies may be added.
- **Untrusted content is wrapped** as `<untrusted_repo_content boundary="{secrets.token_hex(8)}">`, with a new boundary per trial; any content containing the boundary is refused. The boundary sits after the cached prefix, so it costs no cache hits. The understanding summary was derived from repository text, so it is wrapped again before going to the editor; paper text in Step 3 gets the same treatment.
- **Notices during a loop** (for example "budget nearly spent, finish now") go in as `{"role": "system"}` messages, the documented channel that repository content can't forge. They are only ever appended. If the API returns `BadRequestError` for them, fall back to a text block placed after the tool results.
- **Secrets.**
  - `ANTHROPIC_API_KEY` becomes `SecretStr | None`. The assertions in `test_config` switch to `get_secret_value()`; that changes their form, not what they check.
  - The client refuses to start with the current placeholder value.
  - Trial subprocesses get an allowlisted environment without the key.
- **Output.** Claude's final text is capped and passed through the existing report sanitiser.

**RECOMMENDATION:** Enforce everything in code. Treat all repository-derived text as data inside a per-trial boundary, and send operator notices only as `role: system` messages.

## 5. Testability

```python
class LLMTransport(Protocol):
    def send(self, request: LLMRequest) -> BetaMessage: ...
class CodeEditor(Protocol):
    def edit(self, worktree: Path, task: EditTask, budget: Budget) -> EditResult: ...
class ProjectUnderstander(Protocol):
    def understand(self, inputs: UnderstandInputs, budget: Budget) -> ProjectUnderstanding: ...
```

- **One SDK module.** `AnthropicTransport` is the only module that imports the SDK client.
- **`ScriptedTransport`** replays `BetaMessage.model_validate(fixture)` objects or raises real SDK exceptions, and records every request. For example: `anthropic.RateLimitError("..", response=httpx2.Response(429, request=httpx2.Request("POST", URL)), body=None)`. Tests then assert:
  - tools and system are identical on every request;
  - each request's messages extend the previous request's (append-only);
  - no `thinking`, `temperature` or `tool_choice` is sent;
  - `fallbacks` is present exactly when it is enabled;
  - a budget refusal happens before anything is sent;
  - turns ending in refusal or `max_tokens` write nothing.
- **Adapter tests** use a real `anthropic.Anthropic(max_retries=0, http_client=DefaultHttpxClient(transport=httpx2.MockTransport(h)))` and assert the request body, headers and error mapping. I ran this offline here and it works.
- **Handler attack cases**, parametrised:
  - `../x`, `/etc/passwd`, `/repo/../x`, `~/.ssh/id_rsa`, `C:\x`, a NUL byte;
  - `TESTS/Test_A.py`, `a/conftest.py`, `pyproject.toml`, `.env`, `.GIT/hooks/pre-commit`, the `.git` file;
  - a symlinked file and a symlinked directory pointing outside, `src/__pycache__/x.pyc`;
  - zero or two matches for `old_str`, and oversize writes.
- **CI E2E:** `ScriptedTransport` replays the `str_replace` that implements the fixture's known win. The real loop, handler, git diff, anti-cheat and runner all run, with no network.
- **Live smoke test.** A `live` marker has to be registered because `--strict-markers` is on, and `addopts` gets `-m "not live"`.
  - Skip unless the `ANTHROPIC_API_KEY` environment variable is set. Don't test `settings`, which has a placeholder default.
  - Use a one-file repo, effort `low`, `max_tokens` 1500 and `Budget(0.10)`. The budget check itself enforces the cap.
  - Run it by hand or from a `workflow_dispatch` job only.

**RECOMMENDATION:** Fake at `LLMTransport.send` with real `BetaMessage` fixtures, run adapter tests through `httpx2.MockTransport`, script the CI E2E edit, and keep the live test behind the marker.

## 6. Error handling

```python
try:
    message = transport.send(request)
except anthropic.BadRequestError as exc:  # 400: our bug
    raise LLMRequestError(describe(exc)) from exc
except (anthropic.AuthenticationError, anthropic.PermissionDeniedError, anthropic.NotFoundError) as exc:
    raise LLMConfigError(describe(exc)) from exc  # -> EngineError
except anthropic.RequestTooLargeError as exc:  # 413 -> this trial fails
    raise LLMRequestError(describe(exc)) from exc
except (anthropic.RateLimitError, anthropic.OverloadedError, anthropic.InternalServerError) as exc:
    raise LLMUnavailable(describe(exc)) from exc  # after SDK retries; 529 is not an InternalServerError
except anthropic.APIStatusError as exc:  # 402 billing and anything unmapped
    raise (LLMConfigError if exc.status_code < 500 else LLMUnavailable)(describe(exc)) from exc
except anthropic.APITimeoutError as exc:  # subclass of APIConnectionError: must come first
    budget.record(reserved, 0); raise LLMUnavailable("timeout") from exc
except anthropic.APIConnectionError as exc:
    budget.record(reserved, 0); raise LLMUnavailable("connection") from exc
```

`describe` logs `status_code`, `type` and `request_id`, never request bodies (they contain the user's code).

What each error becomes:
- **Config errors** always become an `EngineError`.
- **In the editor**, every other error becomes a failed trial.
- **In the understand node**, `BudgetExceeded` also becomes an `EngineError`. Every other failure sets `understanding=None` and emits an event.

**Stop reasons**, checked before reading any content:

| `stop_reason` | What the engine does |
|---|---|
| `end_turn` | Done. If Claude never made an edit, send one nudge, then fail the trial with "no edits". |
| `tool_use` | Append `response.content` verbatim, run the tools in order, and send all results in one user message. |
| `max_tokens` | Never run that turn's tools. Answer each `tool_use` with an `is_error` "not executed, truncated; make smaller edits". In the understand node, it counts as a failure. |
| `refusal` | Stop without running anything; record `stop_details.category`. With fallbacks on, this means every model in the chain refused. |
| `pause_turn`, `compaction`, `model_context_window_exceeded`, `None` | Failed trial. |

- **Which model served the answer:** check `any(i.type == "fallback_message" for i in usage.iterations or [])` and record an event naming `response.model`.
- **Echoing fallback answers back:** a non-streaming response leaves out a partial answer that was declined, so content can be sent back verbatim.
- **Retries and timeouts:** rely on the SDK's own retries (`max_retries=2`, backoff, honours `retry-after`) with no custom retry loop. The client timeout is 600 s, which also lifts the non-streaming guard.
- **Streaming:** Step 2 stays non-streaming. If streaming arrives with the Step 4 live log, follow the eager-input-streaming rules in `streaming.md`.

**RECOMMENDATION:** Catch errors from most specific to least, as above, with `OverloadedError` and `APITimeoutError` placed explicitly. Rely on the SDK's retries, turn transient failures into failed trials and config failures into `EngineError`, and never run tools from a refused or truncated turn.

**Proposed builder units** (disjoint files, each ≤ ~400 lines):
1. `clients/cost.py`: pricing and the budget.
2. `clients/transport.py`: the transport and its errors.
3. `execution/editor_tools.py`: the handler.
4. `execution/editor.py`: the editor loop.
5. `orchestrator/understand.py`, plus the model and state changes.

Probe scripts are in `/tmp/claude-0/-home-user-autonomous-ai-platform/39c2f425-7abe-5723-807b-13f1d65c6f1e/scratchpad/`:
- `probe_sdk.py`: offline wire test through the mock transport.
- `typed_probe.py` and `typed_probe2.py`: `mypy --strict` checks of the call shapes.
- `gitprobe/`: reproduces both anti-cheat holes.