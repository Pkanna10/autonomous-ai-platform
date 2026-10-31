# Message Batches API: does it matter for the engine and its experiments?

Investigated 2026-10-26. Read-only. No Anthropic API call was made. Every doc
page was fetched live from platform.claude.com on 2026-10-26; none failed, so
the bundled claude-api skill's cached docs were used only for cross-checks
(noted where they disagree). Code citations are `file:line` in
`/home/user/step3-research` (branch `claude/step3-research`, head `bc08cba`,
with other agents' uncommitted Wave 2 edits in the working tree).

---

## Summary for the product owner

**What batches are.** Instead of asking Claude a question and waiting for the
answer, you hand Anthropic a pile of up to 100,000 independent questions. They
answer them when they have capacity, usually within an hour, at most within 24
hours. In exchange every token costs **half price**, and the discount stacks
with prompt caching.

**Do they matter for us? Not much, and not inside the engine.** The engine's
spend is a conversation: the editor calls a tool, sees the result, then calls
again. A batch request is one-shot, so that conversation cannot be batched.
The other engine calls (understand, generator, matcher, the planned idea
lanes and reviewer) each block the next step of a run that a user is waiting
on, so they cannot wait hours either. **Batches never belong in the engine's
run loop.**

**Where they fit:** experiments where nobody is waiting and the requests are
independent (blind hypothesis sweeps, grader passes, paper extraction), and
the future WATCH stage (nightly arXiv triage, paper extraction).

**The money involved.**

| Spend | Total | Could have been batched | Saving at 50 % |
| --- | --- | --- | --- |
| Window 0 (52 runs) | $77.78 | about $15.2 (sweeps, grader, papers, web, probes, heal, build specs) | about $7.6 at most, realistically $5-7 |
| Window 1 so far (L0-L2b) | $18.15 | $0 (all whole engine runs) | $0 |
| Wave 2 plan (expected) | $103-140 | about $7 without redesign (E1b, L3, L4, the auditor pass); about $35 if E1's arms were also batched | $3-4 without redesign; about $17 with it |
| WATCH, Haiku triage | cents a day | all of it | a few dollars a year |
| WATCH, paper extraction (only if the paper pipeline is ever revived) | about $0.30 a paper | all of it | about $1.50 a week at 10 papers a week |

**What to do.**

1. **Engine run loop: never.** No change to `src`.
2. **Wave 2 experiments: do not build anything for batches now.** The
   realistic saving is $3-4 against $103-140, and batching E1 would measure a
   different path (no synchronous cache, no lane reservation) than the one the
   engine will run. The experiment harness already has a working, tested
   batch path (`tests/live/experiments/harness.py`) for any raw-SDK experiment
   that wants it.
3. **Later:** adopt batches with the WATCH stage (the arXiv monitor moves to
   the Step 4 CLI on the user's machine) and with paper extraction if the paper
   pipeline is ever revived. Also reconsider for any future idea-only sweep
   expected to cost $10 or more.
4. **Fix two small harness gaps first, before any batch is used.** A batch
   submit that times out reserves nothing (a cost-cap hole). The paper
   scale-up's default wait equals its CI job's whole timeout. See section 6.
5. We have **never measured a batch end to end**. E1's probe was refused at
   creation, E2 triage failed before spend (arXiv blocks GitHub runners), and
   E7's 50-paper scale-up was skipped. The first real use should record
   latency and cache-hit rate.

---

## 1 What the documentation says

### 1.1 Pages read (all fetched 2026-10-26)

- Batch processing guide:
  https://platform.claude.com/docs/en/build-with-claude/batch-processing
- API reference, create:
  https://platform.claude.com/docs/en/api/messages/batches/create
- API reference, results:
  https://platform.claude.com/docs/en/api/messages/batches/results
- API reference, list:
  https://platform.claude.com/docs/en/api/messages/batches/list
- API reference, delete:
  https://platform.claude.com/docs/en/api/messages/batches/delete
- Retrieve and cancel are described with examples in the guide; their
  reference pages are https://platform.claude.com/docs/en/api/messages/batches/retrieve
  and https://platform.claude.com/docs/en/api/messages/batches/cancel (same
  `MessageBatch` object as create).
- Pricing: https://platform.claude.com/docs/en/about-claude/pricing (batch
  section `#batch-processing`)
- Prompt caching: https://platform.claude.com/docs/en/build-with-claude/prompt-caching
- Rate limits: https://platform.claude.com/docs/en/api/rate-limits (`#message-batches-api`)
- Refusals and fallback (section "Refusals in Message Batches"):
  https://platform.claude.com/docs/en/build-with-claude/refusals-and-fallback
- API and data retention:
  https://platform.claude.com/docs/en/manage-claude/api-and-data-retention
- Structured outputs (checked for batch notes; none found in the readable
  part): https://platform.claude.com/docs/en/build-with-claude/structured-outputs
- Cross-checks: `/tmp/claude-0/bundled-skills/2.1.310/947917b13c4c2f0c5ee95a69f40ea7c6/claude-api/python/claude-api/batches.md`
  and `.../shared/cost-optimization.md` section 2.5.

### 1.2 Discount, and how it stacks with caching

- **50 % off all usage**: "All usage is charged at 50 percent of the standard
  API prices" (guide, Pricing). The FAQ: "This applies to input tokens, output
  tokens, and any special tokens."
- **It stacks with prompt caching.** Guide: "The pricing discounts from prompt
  caching and Message Batches can stack". Pricing page: cache multipliers
  "stack with other pricing modifiers, including the Batch API discount and
  data residency". The skill's cost guide says the same: "50% off every token
  in the request, including cache reads and writes".
- **Cache hits inside a batch are best effort.** Guide: "because batch
  requests are processed asynchronously and concurrently, cache hits are
  provided on a best-effort basis. Users typically experience cache hit rates
  ranging from 30 percent to 98 percent". Advice: identical `cache_control`
  blocks in every request; keep a steady stream so 5-minute entries do not
  expire; share as much prefix as possible. The tip: "consider using the
  1-hour cache duration". `max_tokens: 0` pre-warming is rejected inside a
  batch "because an ephemeral cache entry written during batch processing
  would likely expire before the follow-up request runs".
- **Not documented:** whether the $10 per 1,000 web searches fee is
  discounted. The harness assumes full price (`bounds.py:444-451`), which is
  the safe reading.
- `inference_geo: "us"` adds 1.1x on top (pricing, Data residency); the
  engine does not use it.

### 1.3 Batch prices for the models we use (USD per million tokens)

The batch input and output prices are quoted from the pricing table. The cache
columns are **derived**: the list cache price times 0.5, per the stacking rule
above.

| Model | Batch input | Batch output | Batch 5 m cache write | Batch 1 h cache write | Batch cache read |
| --- | --- | --- | --- | --- | --- |
| Claude Opus 5.5 | $2 | $10 | $2.50 | $4 | $0.10 |
| Claude Sonnet 5.5 | $1 | $5 | $1.25 | $2 | $0.05 |
| Claude Fable 5.1 | $5 | $25 | $6.25 | $10 | $0.125 |
| Claude Haiku 5.5, prompt up to 100K | $0.05 | $0.25 | $0.0625 | $0.10 | $0.005 |
| Claude Haiku 5.5, prompt over 100K | $0.25 | $1.25 | $0.3125 | $0.50 | $0.025 |
| Claude Opus 4.8 (our grader) | $2.50 | $12.50 | $3.125 | $5 | $0.25 |

List prices behind the derivation (pricing page): Opus 5.5 $4 / $20, 5 m
write $5, 1 h write $8, read $0.20 (0.05x). Sonnet 5.5 $2 / $10, $2.50, $4,
$0.10 (0.05x). Fable 5.1 $10 / $50, $12.50, $20, $0.25 (0.025x). Haiku 5.5
$0.10 / $0.50, $0.125, $0.20, $0.01 (over 100K: $0.50 / $2.50, $0.625, $1,
$0.05).

### 1.4 Limits, latency, retention

- **Size:** "limited to either 100,000 Message requests or 256 MB in size,
  whichever is reached first"; over the size you get 413 `request_too_large`.
  The create reference requires between 1 and 100,000 items.
- **Latency:** "most batches completing within 1 hour"; "Batches expire if
  processing does not complete within 24 hours". `expires_at` is 24 h after
  creation. FAQ: "It is possible for a batch to expire and not complete
  within 24 hours", and under heavy demand "you might see more requests
  expiring after 24 hours". There is no SLA and no documented figure for small
  batches.
- **When results are readable:** "You can access batch results when all
  messages have completed or after 24 hours, whichever comes first." There are
  **no partial reads while a batch runs**. `request_counts` other than
  `processing` stay 0 "until processing of the entire Message Batch has
  ended". The only partial results come from a cancelled batch: "Canceled
  batches end up with a status of `ended` and may contain partial results".
- **Retention:** "Batch results are available for 29 days after creation"
  (counted from `created_at`, not `ended_at`). After that the batch is still
  visible, its results are not (`archived_at`).
- **Immutable:** a submitted batch cannot be changed; cancel and resubmit, and
  cancellation "might not take immediate effect".
- **Workspace-scoped:** batches and their results are visible to anyone with
  access to the workspace. Our key is workspace-scoped (STATUS ledger row
  2026-10-23, run 39958890445).
- **Spend limit overshoot:** "batches may go slightly over the spend limit
  configured in the Claude Console". This matters for STATUS's optional
  workspace spend-limit backstop: our own reservation, not the Console limit,
  is the real guard.

### 1.5 What can and cannot be batched

- **Supported:** "All active models support the Message Batches API".
  Included: vision; tool use, including every server tool (web search, web
  fetch, code execution, MCP connector, advisor, tool search); system
  messages; multi-turn *conversations as input*; extended (adaptive) thinking
  and effort (`output_config` is a normal param); "Most beta features". You
  can mix request types in one batch.
- **Structured outputs and citations:** not named, but "Almost any request you
  can make to the Messages API can be included in a batch", and
  `output_config` (including the JSON schema `format`) is listed in the create
  reference's `params`. The structured-outputs page says nothing about batches
  in its readable part. **Unverified live**; the E7 scale-up was designed to
  send a citation pass in a batch but never ran.
- **Rejected:** `stream: true`, `speed` (fast mode), `fallbacks` (server-side
  fallback), and `max_tokens: 0`. Refusals doc: "a batch request that includes
  `fallbacks` produces a per-item errored result".
- **Multi-turn tool loops: no.** Each request is one turn. A batch can carry a
  history, but our tools run locally between turns, so each turn would be a
  separate batch with up to 24 h between turns.
- **Server-tool loops inside a turn:** "the batch loop can run **more
  iterations in a turn** than a synchronous request before it returns
  `stop_reason: "pause_turn"`" (no number given), and `web_search` is
  throttled per organization in batches.
- **Extended output beta** (`output-300k-2026-03-24`): `max_tokens` up to
  300,000, batches only, Opus 5.5 / Sonnet 5.5 / Haiku 5.5 among others. We
  have no use for it.

### 1.6 Rate limits

Batches have their own limits, shared across models. They "do not affect rate
limits in the Messages API":

| Tier | Requests per minute (all batch endpoints) | Batch requests in the processing queue | Requests per batch |
| --- | --- | --- | --- |
| Start | 1,000 | 200,000 | 100,000 |
| Build | 2,000 | 300,000 | 100,000 |
| Scale | 4,000 | 500,000 | 100,000 |

Our volumes are orders of magnitude below these.

### 1.7 Results, errors, partial results, `custom_id`

- Flow: `create` returns `processing_status: "in_progress"`. Poll `retrieve`
  until `"ended"` (`"canceling"` in between after a cancel). Then stream
  `results` as JSONL, one `MessageBatchIndividualResponse` per line.
- Result types: `succeeded` (a full `Message` with `usage`, where
  `usage.service_tier` is `"batch"`), `errored`, `canceled`, `expired`.
  "You will not be billed" for errored, canceled or expired requests.
- `errored` carries the standard error shape. `invalid_request_error` means
  fix the body. Other types (`api_error`, `overloaded_error`,
  `rate_limit_error`, `timeout_error`...) can be retried as they are.
  Validation runs **asynchronously**: errors only come back when the whole
  batch has ended. The guide's tip is to dry-run one request shape on the
  Messages API first.
- **Refusals:** "A refused request in a Message Batch comes back as
  `result.type: "succeeded"` with `stop_reason: "refusal"`"; "batch refusals
  don't mint fallback credits". To retry, collect the refused items and
  resubmit them on a fallback model, as a new batch or as direct requests.
- **Order:** "Batch results can be returned in any order"; match by
  `custom_id`.
- **`custom_id`:** required and unique within a batch, matching
  `^[a-zA-Z0-9_-]{1,64}$`.
- **Not documented:** an idempotency key for `create`. A lost create response
  can leave a batch you do not know about (it still bills).
- "Batch results use the API version of the request that created the batch"
  (the 2026-10-21 version's `temperature` removal applies to batch params
  too).

### 1.8 Data retention

- "Batch processing stores request and response data for up to 29 days after
  batch creation." `DELETE /v1/messages/batches/{id}` deletes an ended batch
  ("To delete an in-progress batch, cancel it first").
- Feature table (data-retention page): Batch processing is **ZDR: No, HIPAA:
  No**, "29-day retention; async storage required". Under ZDR the API does not
  block it; using it "is a choice to step outside your ZDR arrangement for that
  specific data".
- Relevance: in Step 5 the prompts carry the user's own source code (the VLM
  bridge). Any batch carrying user code should be deleted after it is
  collected. Fable 5.1 already requires 30-day retention, so batching changes
  nothing there.

### 1.9 SDK calls (Python SDK 1.x, as the harness uses them)

```python
from anthropic.types.beta.messages.batch_create_params import Request
created = client.beta.messages.batches.create(requests=[...], betas=[...])  # or client.messages.batches.*
batch   = client.beta.messages.batches.retrieve(batch_id)   # .processing_status, .request_counts, .results_url
for r in client.beta.messages.batches.results(batch_id):    # streams JSONL; r.custom_id, r.result.type
    ...                                                     # succeeded -> r.result.message; errored -> r.result.error.error.type
client.beta.messages.batches.cancel(batch_id)
client.beta.messages.batches.list(limit=20)                 # auto-paginates; after_id / before_id, limit 1-1000
client.beta.messages.batches.delete(batch_id)               # ended batches only
```

The harness uses exactly these (`harness.py:447, 468, 488, 497, 536`).

### 1.10 Discrepancies and notes

- **`fallbacks` in a batch.** The refusals doc says it "produces a per-item
  errored result". STATUS records E1 as "`fallbacks` in a batch are refused
  (400)" (ledger 2026-10-24, run 39998493959; the harness records a refusal
  at submit, `test_probes_live.py:290-300`). Either way nothing is billed.
  The live behaviour seen was a create-time 400.
- **`max_tokens` minimum.** The create reference's `params` says "Minimum `0`"
  (the generic Messages schema); the guide says `max_tokens: 0` is a
  validation error inside a batch. The guide wins.
- **Skill's cached batches.md.** It checks `result.result.error.type ==
  "invalid_request"`. The results reference nests it as
  `result.error.error.type == "invalid_request_error"`. The harness reads the
  nested shape correctly (`harness.py:514`).

---

## 2 Every Claude call, classified

Classes: **(a)** needs an answer within the run: synchronous, blocks the next
step. **(b)** independent single-shot requests that could wait minutes to
hours. **(c)** multi-turn tool loop: cannot be batched.

### 2.1 The engine (`services/python_agents/src/autonomous_ai_agents`)

All engine calls go through one door, `clients/transport.py:306-360`
(`call()`), and `AnthropicTransport.send` (`transport.py:237-259`). That door
**always sends `fallbacks` when the chain has more than one model**
(`:239-252`), which a batch rejects. `LLMRequest` refuses 1-hour cache TTLs
(`:122-126`). `clients/cost.py` has no batch price.

| Call | Where | Model (default) | Class | Why |
| --- | --- | --- | --- | --- |
| Understand (includes the D40 `quality_proposal`; not a separate request) | `orchestrator/understand.py:294-317`, called from `orchestrator/nodes.py:2515`; proposal parsed at `understand.py:126, 382, 681` | `ENGINE_MODEL` Opus 5.5 (`common/config.py:202`) | (a) | One request at connect; everything downstream reads its output |
| Hypothesis generator | `optimization/generate.py:245-253` via `optimization/hypothesis_source.py:99`, invoked at `nodes.py:996` | `GENERATOR_MODEL` Sonnet 5.5 medium (`config.py:238-242`) | (a) | The hypotheses node waits on it; at most `GENERATOR_MAX_CALLS` 2 a run |
| Technique matcher (`matched` retrieval, off by default) | `research/playbook.py:392-400` via `hypothesis_source.py:142`, invoked at `nodes.py:1089` | `MATCHER_MODEL` Sonnet 5.5 medium (`config.py:243-245`) | (a) | Feeds the generator in the same node |
| Editor (trial edits) | `execution/editor.py:289-360` (`run`, `_ask`), called from `execution/trial_runner.py:928` | `EDITOR_MODEL` or `ENGINE_MODEL` (`config.py:254`) | **(c)** | Tool loop: `tool_use` → local tool → `tool_result` → next turn |
| Bounded self-retry (D12/D13) | `execution/retry.py` (classifies the crash; the retry is another editor run) | as editor | (c) | It is an editor loop with the crash fed back |
| Idea pipeline (Wave 2, planned): S1 obvious lane, six lens lanes, leap lane, reviewer | spec `.claude/handoff/step3/spec-wave2-ideas.md` §3.4 (`optimization/idea_lanes.py`, `idea_review.py`, `idea_pipeline.py`, lines 931-959); settings already in `config.py:269-283` | Sonnet 5.5 medium lanes, Opus 5.5 high leap and reviewer | (a) | Replaces one `generate()` inside the run. Lanes depend on S1, the reviewer on the lanes. Lanes run in parallel (`IDEAS_LANE_WORKERS` 4) under D48's reservation and read S1's cache |
| arXiv monitor, PDF parser | `research/arxiv_monitor.py`, `research/pdf_parser.py` | none | n/a | 2025 placeholders with no Claude call (research-research.md F7) |

**There is no engine call of class (b) today.** The engine never waits for
anything that is not on a run's critical path.

### 2.2 The live harnesses and experiments (`services/python_agents/tests/live`)

Two clients are used. The engine's own `call()` on a recording transport
(`tests/live/conftest.py:397-476`), and the raw-SDK `ExperimentClient`
(`tests/live/experiments/harness.py:193-617`). The raw-SDK client **already
implements batches**: `submit` (`:415-457`) reserves each item's worst case at
batch price, `wait` (`:459-479`) is capped at `MAX_WAIT_S` 5.5 h (`:74`),
`results` (`:481-533`) prices successes at half and charges errored, canceled
and expired requests 0, and `close` (`:258-282`) charges any uncollected
request its worst case. `bounds.py:66, 439, 444-451` hold `BATCH_DISCOUNT` 1/2.
It has offline tests: `test_harness.py:664-905, 1242`, `test_triage.py:255,
424, 441`, `test_extraction.py:597-904`.

| Experiment | Call sites | Class | Batchable? |
| --- | --- | --- | --- |
| Whole-loop suites: `corpus`, `hard`, `oss`, `oss-ab`, `ab` loops, `attack`, `escalation`, `evolve`, L1a/L1b/L2a/L2b `wired`, Stage A E2E | `corpus.py`, `oss.py`, `discovery.py:517` `run_engine`, `discovery_oss.py:1020`, `evolution.py:838` | (a) + (c) | No: understand, generator and editor loop inside each run |
| Blind sweep (E3, `sweep`, `sweep-fable`, `sweep-record`; L4) | `discovery_sweep.py:357` (`generate_hypotheses`), grader `discovery_grader.py:313, 338` | (b) | Yes, as two staged batches (generate, then grade). Replay pattern already exists: `discovery_sweep.py:876-927` (`scripted_reply` + `ScriptedTransport`) |
| Grader agreement (L3) | `discovery_grader.py:338` `grade` | (b) | Yes: about 10 independent requests |
| A/B generation phase (E5, E5o) | `discovery_ab.py:180, 193`; `discovery_oss.py:425, 437` | (a) for the following loop | Technically a pre-loop batch, but the money is tiny ($0.014 a generation) |
| Evolution round generation | `evolution.py:1275` | (a) | No: each round reads the previous round's improved code |
| Triage (E2) | `experiments/triage.py:312` (sync arm), `:352-368` (batch arm + resubmit) | (b) | **Built as a batch**; never ran (arXiv 429 from runners) |
| Papers (E7) pass 1, pass 2, screen | `experiments/extraction.py:137` (pass 1), `experiments/cards.py:266` (pass 2), `cards.py:412` (screen); live `test_extraction_live.py:130, 151, 182`; scale-up batch `:345-409` | (b), staged (pass 2 needs pass 1 plus local quote checks) | Yes. **The scale-up is built as a batch** but was skipped |
| Web research and screen (E6) | `experiments/web.py:314`, `experiments/web_screen.py:123`, `test_web_live.py:323, 354, 382` | (b) with server tools | Allowed by the docs. The harness needs an explicit `ToolAllowance` in a batch (`bounds.py:164-186`: "no documented iteration limit") |
| Probes (E1) | `test_probes_live.py:167-361`; batch probe `:276-305` | (b) | Its own batch probe |
| Pre-screen (E8b) | `test_prescreen_live.py:69` | (b), code execution | Yes, but it measures container timings |
| Package suggestions (3b) | `test_acquire_live.py:167` | (b) | Yes, trivially small |
| Self-healing (3c, `heal`, `heal-hard`) | `test_heal_live.py:140-179`: reproducer request, local sandbox runs, fix request, bounded retry | (a) within a repo; (b) across repos stage by stage | Stage-wise only: one batch per stage across the 8-10 repos |
| Build then improve | `build_improve.py:376-398` (build and tests requests, independent of each other), `:515`; then `run_engine` `:1238` | (b) for the two spec requests, then (a)+(c) | Only the two spec requests |
| Wave 2 E0b (`count` mode) | spec §3.6, §6 E0b | measures the sync cache (`cache_read_input_tokens > 0` on a lens lane) | No: batching changes what is measured |
| Wave 2 E1 arms A-E | spec §6 E1 row | (a)-shaped pipeline, stage-batchable across 8 libraries x 5 arms (S1 → lanes and leap → reviewer) | Possible, but it would bypass the engine's `IdeaPipelineGenerator` path and its cache behaviour |
| Wave 2 E1 auditor pass | spec §6 "a fixed auditor (Opus 5.5 `high` ... once per library)" | (b) | Yes: 8 independent requests after the arms |
| Wave 2 E1b | spec §6 E1b row ("on E1's recorded facts, no phase 1") | (b), staged | Yes, 3 staged batches |
| Wave 2 E2, E2c, E3, E4 | spec §6 | (a) + (c) whole loops | No |
| Recorded replies for offline fixtures (V6 amended, `tests/fixtures/idea_eval/`) | spec §6 "Offline eval" | byproduct of E1 | Batch results are full `BetaMessage`s, so they can be recorded and replayed the same way. A replay through `call()` would price them at full rate (`cost.response_cost` is not batch-aware); harmless, since the replay has its own budget (`discovery_sweep.py:802` `REPLAY_CAP_USD`) |

### 2.3 What earlier work already said about batches

- **Research report** (`scratchpad/reports/Claude API capabilities for the
  engine.md`): recommended adopting "**Message Batches** for paper triage and
  extraction (50% off, stacks with caching)" (line 3). Its capability table
  (line 20) proposed a "500-abstract Haiku triage batch, under $0.30". It
  listed the constraints: "Batches reject `fallbacks`", Haiku has no
  server-side fallback, "batched jobs need client-side retry of failed
  `custom_id`s" (line 35). Its plan item 2 was to submit batches early
  (lines 43, 48). Its design advice: "Batches with 1 h caching and client-side
  refusal retry for triage and extraction" (line 59).
- **STATUS.md**:
  - Register rows E1 "batch fallbacks" and E2 "Haiku batch triage of ~500
    abstracts ... batch latency" (`STATUS.md:1482-1483`).
  - Outcome: E1 "batch fallbacks refused" (`:1580`, ledger `:1628`). E2
    "Triage ... No: arXiv blocks GitHub runners (429); the monitor runs on the
    user's machine", $0.00 over 3 runs, all failing before any spend.
  - Decisions: "batches reject `fallbacks`" (`:1718`). The raw-SDK harness
    exists so "batches, citations, web tools and code execution" are measured
    "before they are designed in" (`:1745-1749`). "the SDK follows a batch's
    `results_url` by itself", hence host pinning (`:1753`).
  - Open item: "batch pricing for generation" is listed under "Open, for
    later windows" (register text after the table).
  - **No record named "X5" or "triage batch" exists** in STATUS or the Step 3
    handoff (grep). The triage batch is E2.
- **Step 3 design** chose not to batch. research-research.md:87: "Step 3
  triage is synchronous with the 5-minute cache. Batches and 1 h caching are a
  later transport extension. At Haiku prices the difference is cents a week."
  F6 (`:24`): `LLMRequest` "refuses 1 h cache TTLs and has no batch path".
  design-a.md:237 lists "batches and 1 h caching" as non-goals. spec.md:838
  and :1491-1497 defer the paper pipeline and the arXiv monitor (the monitor
  moves to the Step 4 CLI).

---

## 3 Quantification

### 3.1 Past spend

Source: `services/python_agents/tests/live/experiments/usage_window0.json`
(52 runs, $77.7771, which matches the Console) and STATUS's Window 1 ledger.

| Suite | Runs | USD | Class | Batchable USD |
| --- | --- | --- | --- | --- |
| `sweep` | 1 | 6.0111 | (b), 2 stages | 6.0111 |
| `sweep-fable` | 1 | 2.6608 | (b) | 2.6608 |
| `sweep-record` | 1 | 1.1210 | (b) | 1.1210 |
| `papers` | 1 | 1.3189 | (b), staged | 1.3189 |
| `web` | 3 | 3.4178 | (b), server tools | 3.4178 |
| `probes`, `prescreen`, `acquire` | 3 | 0.0593 | (b) | 0.0593 |
| `heal`, `heal-hard` | 2 | 0.3025 | stage-wise (b) | 0.3025 |
| `build` (only the BUILD rows) | 1 | 0.4872 | partly (b) | 0.2788 |
| `oss-ab`, `ab`, `oss`, `evolve`, `evolve-more`, `corpus`, `hard`, `stage-a`, `escalation`, `attack` | 36 | 62.40 | (a)+(c) | 0 |
| `triage`, `noise` | 4 | 0 | | 0 |
| **Window 0** | 52 | **77.78** | | **15.17 (19.5 %)** |
| **Window 1 to date** (L0 0, L1a 2.21 + 2.11, L1b 2.42, L2a 5.94, L2b 5.46) | | **18.15** | (a)+(c) | **0** |

- **Maximum saving:** 0.5 x $15.17 = **$7.59**, which is 7.9 % of the $95.93
  spent so far.
- **Realistic saving: $5-7.** Batch cache hits are best effort (30-98 %),
  which costs some of the sweeps' cache reads. Web search fees (about 30 % of
  the batchable dollars are the web runs) may not be discounted. And the
  cleanly batchable subset without staging or server tools (sweeps, papers,
  probes, acquire, prescreen) is $11.18, which saves $5.59.
- **Nothing in the engine's own spend was batchable.** About 80 % of
  Window 0's money and 100 % of Window 1's is whole engine runs, dominated by
  the editor's tool loop. For example, L2b alone wrote 450,599 cache tokens
  and read 1,529,350, all in editor conversations.

### 3.2 The Wave 2 plan

Expected costs are from spec §6, `spec-wave2-ideas.md:1561-1588`.

| Run | Expected | Batchable part | Saving at 50 % | Should it be batched? |
| --- | --- | --- | --- | --- |
| E0b (count mode) | ~0.5 | none | 0 | No: it measures the sync cache on a lens lane |
| E1 phase 1 (oss phase one, about 0.5 a library) | ~4 | none (understand + profile) | 0 | No |
| E1 arms A-E (8 libraries) | ~24 | all, as 3 staged batches | ~12 | **No** (see 4.7). It would measure a different execution path; 3 dependent batch stages plus the auditor do not reliably fit a 120-minute `ideas-probe` job (spec §6 "timeout 120") |
| E1 auditor pass (8 requests; worst case 0.66 each, `spec-wave2-ideas.md:1565`) | ~1.5-2 (estimate: E1's expected/cap ratio, 30/90, times the 5.28 worst case) | all | ~0.9 | Optional. Only via the raw-SDK harness, and the money is trivial |
| E1b (4 libraries x 2 effort levels, recorded facts) | ~4 | all, staged | ~2 | Optional, same reasoning |
| L3 grader (about 10 labels) | < 0.5 | all | < 0.25 | Not worth the code |
| L4 `sweep-record` (37 repos, Sonnet medium + grader) | ~1.8 | all, 2 stages | ~0.9 | Not worth the code now |
| E2, E2c, E3, E4, L5a-c, W1 refresh | ~84-94 | none | 0 | No: whole loops |
| **Total** | **$103-140** | **about $7 (or about $35 with E1's arms)** | **$3-4 (or about $17)** | |

Recorded replies for the offline fixtures cost nothing extra: they are
recorded from E1's replies, batched or not.

### 3.3 The future WATCH stage

These are estimates, labelled as such; there is no measured triage run.

- **Haiku triage of abstracts.** Assume a 1,500-token cached rubric, a
  350-token abstract and about 300 output tokens at low effort. Sync cost per
  abstract: 350 x $0.10/M + 1,500 x $0.01/M + 300 x $0.50/M ≈ **$0.0002**.
  Batch: about $0.0001.
  - At 200 abstracts a day: $0.04 a day sync against $0.02 batched, a saving
    of **about $7 a year**. This agrees with research-research.md:87 ("cents a
    week").
  - The real reasons to batch triage are operational, not money: it is a
    nightly job nobody waits on, and it has its own rate-limit pool.
  - Haiku 5.5 rejects `fallbacks`, and so do batches, so a triage route
    already runs with `ENGINE_FALLBACKS` off (`STATUS.md:1718`).
- **Paper extraction (pass 1 PDF + citations, the screen, pass 2).** E7
  measured $1.32 for 4 papers plus the injection tests, about $0.26-0.33 a
  paper. The paper-intake condition is at most $0.35 a paper
  (`spec.md:1491`).
  - Batched: about $0.13-0.17 a paper.
  - At 10 papers a week: about **$1.50 a week, about $80 a year**, saved. At
    50 a week, about $400 a year.
  - This is the only future use where batching is worth real money. It exists
    only if the paper pipeline is revived; D2 currently keeps it deprioritised
    (STATUS 2026-10-24: "The paper pipeline stays deprioritised").
- **arXiv monitoring itself** (fetch, filter) makes no Claude calls.

---

## 4 Engineering impact

### 4.1 How results flow back

The flow is submit, poll `retrieve`, stream `results`, then match by
`custom_id`. Results come only at the end (section 1.4), so a consumer must
tolerate a single delayed drop of all answers.

The harness pattern is the right shape:

- reserve at submit;
- poll with a deadline under the job limit;
- refuse a `results_url` not on the engine host (`harness.py:490-495`; the SDK
  follows it with the key);
- settle each `custom_id` exactly once (`:502-503`, `settled` set);
- charge each id missing from the results its worst case (`:522-532`).

### 4.2 Idempotency by `custom_id`

- Use deterministic ids built from the run, the stage and the item, for
  example `w2-e1b-<lib>-<effort>-<lane>`, within 64 characters of
  `[A-Za-z0-9_-]`.
- Settling by id makes result processing idempotent and replayable from the
  29-day results.
- **Create is not idempotent.** No idempotency key is documented. After a
  create with no answer (timeout or lost connection), the batch may exist and
  bill. The safe rule mirrors the engine's own sync rule ("a timeout is charged
  the full estimate", `clients/budget.py:10-13`): reserve or charge the
  batch's worst case, then try `list` (newest first, `created_at` window) to
  find and cancel it.
- **The harness does not do this today** (section 6, gap 1).

### 4.3 The Budget pre-check and cost accounting

- The engine's `Budget` (`clients/budget.py:38-86`) has `check` before and
  `record` after, with no notion of money in flight.
- A batch needs a reservation:
  - `check(sum of per-item worst cases at batch price + already reserved)` at
    submit;
  - `record` actual usage per succeeded item;
  - 0 for errored, canceled and expired items (documented as not billed);
  - the worst case for anything never collected.
- The Wave 2 idea pipeline already introduces exactly this parent/child
  reservation for parallel lanes (D48, `spec-wave2-ideas.md:293-305`), so a
  batch path in `src` would reuse it.
- Price from the response, not the caller's flag. `usage.service_tier ==
  "batch"` is in every batch result (results reference, `Usage.service_tier`).
  `cost.response_cost` would need a batch multiplier keyed on it.
- For an engine run (not an experiment), the reservation and batch id would
  have to be persisted in the LangGraph state, so a checkpoint and resume
  collects the batch instead of resubmitting it and paying twice.
- Worst-case bounds stay valid at half price, except for server tools in a
  batch: "more iterations in a turn", no number, which is why
  `bounds.py:182-186` demands an explicit allowance.

### 4.4 Failure and expiry handling

| Outcome | Billed | Action |
| --- | --- | --- |
| `errored` / `invalid_request_error` | no | Fix the body. Resubmitting the same body fails again |
| `errored` / other types | no | Resubmit (sync or a new batch) |
| `expired` (24 h) | no | Resubmit |
| `canceled` | no | Resubmit if still wanted |
| `succeeded` + `stop_reason: "refusal"` | yes | No fallback credit and no server-side fallback: resubmit on a fallback model |
| `succeeded` + `pause_turn` (server tools) | yes | Continue the turn in a follow-up request |
| `succeeded` + `max_tokens` | yes | Treat as a failed attempt (as `structured.read_reply` already does) |
| Batch not ended by the job deadline | unknown yet | Cancel; keep the id; charge the worst case (as `harness.close` does) |

### 4.5 CI timeouts against batch latency

- GitHub-hosted jobs stop at 360 minutes. The live job's per-suite timeouts
  are in `.github/workflows/ci.yml:577`: `ab` 360, `sweep` 240, `evolve` and
  `oss` 300, `sweep-record` 150, `triage` 90, `papers` 60, default 30. The
  Wave 2 `ideas-probe` suite gets 120 (spec §6).
- Typical batch latency (under 1 h) fits a one-stage batch; a 24-hour expiry
  does not. A job killed by its timeout never runs `ExperimentClient.close()`,
  so the ledger never records the reservation, while the batch keeps
  processing and billing.
- Rules if batches are used in CI:
  1. `wait_s` plus everything after it must be well below the suite timeout,
     and the harness should cancel on its own deadline.
  2. Multi-stage batches (S1 → lanes → reviewer → auditor) should not run in
     one job.
  3. For anything that can take hours, split into a **submit job** and a
     **collect job** (scheduled or manual, by batch id, within the 29-day
     retention), with the reservation recorded in the ledger in between. That
     needs a small ledger entry for "reserved, pending" across jobs. The
     harness already writes pending batch ids into results (`harness.py:278-282`).

### 4.6 Offline testing with `ScriptedTransport`

- `ScriptedTransport` (`transport.py:265-303`) scripts one attempt at a time,
  in order. A batch path in `src` needs its own protocol (submit, status,
  results), and a scripted fake that returns results **shuffled**, with
  errored, canceled, expired and missing ids, refusals and `pause_turn`.
- The harness's `FakeApi` tests already cover most of that for the raw-SDK
  path (`test_harness.py:664-905`).
- For experiments that use `src` logic (sweep, grader, idea lanes), the
  lowest-risk pattern is **plan, batch, replay**:
  1. Build each `LLMRequest` with the real `src` function on a capturing
     transport.
  2. Convert it to batch params (the body `AnthropicTransport.send` builds,
     minus `fallbacks`).
  3. Submit through `ExperimentClient`.
  4. Replay each result through `ScriptedTransport` into the same `src`
     parser, as `discovery_sweep.py:876-927` already does for recorded
     replies.

  That keeps parsing and validation identical to production and needs no
  `src` change.

### 4.7 Could the idea pipeline's lanes use batches?

**In a run: no.**

- The lanes sit inside the hypotheses node of a run the user waits for.
- They depend on S1's output and cache: S1 writes the cache that every lens
  lane reads, "parallel lanes read because S1 has completed before the
  fan-out" (`spec-wave2-ideas.md:678-679`). Batches make that cache read best
  effort, which defeats the D46 cache design.
- The reviewer depends on all lanes.
- D48's failure rule (drop a failed lane, never re-send) presumes answers
  within the node.

So a batch would add minutes to hours to every run to save about half of a
pipeline whose worst case is about $2.37 a call (arm C) and whose real cost is
a fraction of that.

**For E1 as an experiment: possible but not advised.** It would measure a
batch-run, cache-best-effort variant rather than the synchronous pipeline that
E2 then flips into the engine, which undermines E1's purpose (choosing E2's
arm, `max_tokens` budgets, cache-hit rows).

### 4.8 Transport constraints a `src` batch path would hit

- `fallbacks` must go: use a single-model chain, as the Haiku triage route
  already does, plus client-side refusal resubmission.
- 1-hour cache, which the docs advise for batches, is refused by
  `LLMRequest`, and `cost.py` does not price 1 h writes (`transport.py:122-126`).
- `cost.py` has no batch rate.
- The live docs win over the skill where they disagree (STATUS:1735-1738).

---

## 5 Recommendations

| Use | Verdict | Smallest implementation |
| --- | --- | --- |
| Engine run loop: understand, generator, matcher, editor, self-retry, idea lanes/leap/reviewer, in-run heal and build | **Never** | None. Keep `src` synchronous |
| Weekly live regression, dogfood (Stage D, E, Step 5) | **Never** | They test the synchronous contract and whole loops |
| Wave 2 E0b, E1 arms, E2, E2c, E3, E4 | **No** | n/a |
| Wave 2 E1 auditor pass, E1b, L3, L4 | **Not now** (optional) | If wanted later: the plan-batch-replay pattern (4.6) in `tests/live`, through `ExperimentClient.submit/wait/results`, with deterministic `custom_id`s and single-model chains. About 150-250 lines plus tests; saves $3-4 in total. Not worth it before Window 1 ends |
| Future idea-only probes or sweeps expected to cost $10 or more a dispatch, where the question does not depend on sync cache or latency | **Later** | The same pattern, built once in `tests/live` and reused |
| WATCH: arXiv abstract triage on Haiku 5.5 | **Later**, with the Step 4 CLI monitor (runs on the user's machine) | `ExperimentClient`'s batch code promoted into a small `clients/batch.py`: submit, poll, collect, reservation, `service_tier`-based pricing. A single-model Haiku chain, 1 h cached rubric (needs `LLMRequest` and `cost.py` to accept and price 1 h TTL), resubmit errored and expired ids once. Value is operational; the money is cents |
| WATCH: paper extraction (screen, pass 1, pass 2) | **Later, only if** the paper pipeline is revived (D2 and the $0.35/paper condition) | The same module, 3 staged batches (screen + pass 1, local quote verification, pass 2), delete each batch after collection. About $80-400 a year saved depending on volume |
| Self-healing production intake (Step 6), many error reports overnight | **Later, maybe** | Stage-wise batches across reports (reproducer stage, then fix stage). Revisit when volume exists |

**Before any of the "later" items: measure one batch.** Re-run E2 triage from
the user's machine or on a cached abstract corpus (it is built). Record batch
latency, cache hit rate with 1 h TTL, and sync-against-batch agreement. Today
we have no measured batch latency at all.

---

## 6 Findings worth fixing (none applied; read-only)

1. **A batch submit that gets no answer reserves nothing.**
   `harness.py:446-452` maps every `anthropic.APIError`, timeouts included
   (status `None`), to `ExperimentAPIError` without a reservation or charge.
   The server may have created and started billing the batch. The sync path
   charges the worst case on no answer (`harness.py:342-344`;
   `budget.py:10-13`). Only an HTTP 400 is tested
   (`test_harness.py:880-885`). Fix:
   - on status `None`, charge or reserve the batch's worst case, and try
     `list` to find and cancel it;
   - add a timeout test.
2. **The E7 scale-up cannot finish inside its job.**
   `test_extraction_live.py:356` defaults `LIVE_EXTRACT_WAIT_S` to 3,600 s,
   which equals the whole `papers` suite timeout of 60 minutes
   (`ci.yml:577`), before pass 2 even starts. A killed job skips `close()`, so
   the ledger misses the reservation. Also, `ci.yml` never passes
   `LIVE_EXTRACT_SCALE` (grep finds no `LIVE_EXTRACT` in the workflow), so the
   scale-up cannot be enabled from a dispatch as it stands.
3. **The `fallbacks`-in-batch fact is recorded as a create-time 400**
   (STATUS:1628), while the docs describe a per-item errored result. Both are
   unbilled. A future batch path should handle both shapes.
4. **The skill's cached `python/claude-api/batches.md` checks the wrong error
   field** (`error.type == "invalid_request"`). The correct check is
   `error.error.type == "invalid_request_error"`. The harness already does it
   right (`harness.py:514`); do not copy from the skill.

---

## Sources

- https://platform.claude.com/docs/en/build-with-claude/batch-processing
- https://platform.claude.com/docs/en/api/messages/batches/create
- https://platform.claude.com/docs/en/api/messages/batches/results
- https://platform.claude.com/docs/en/api/messages/batches/list
- https://platform.claude.com/docs/en/api/messages/batches/delete
- https://platform.claude.com/docs/en/api/messages/batches/retrieve
- https://platform.claude.com/docs/en/api/messages/batches/cancel
- https://platform.claude.com/docs/en/about-claude/pricing
- https://platform.claude.com/docs/en/build-with-claude/prompt-caching
- https://platform.claude.com/docs/en/api/rate-limits
- https://platform.claude.com/docs/en/build-with-claude/refusals-and-fallback
- https://platform.claude.com/docs/en/manage-claude/api-and-data-retention
- https://platform.claude.com/docs/en/build-with-claude/structured-outputs
- https://claude.com/pricing#anthropic-api (linked from the guide's FAQ)
- Bundled skill (cross-check only): `/tmp/claude-0/bundled-skills/2.1.310/947917b13c4c2f0c5ee95a69f40ea7c6/claude-api/python/claude-api/batches.md`, `.../shared/cost-optimization.md`
- Earlier report: `scratchpad/reports/Claude API capabilities for the engine.md`
- Repository: `/home/user/step3-research/STATUS.md`, `/home/user/step3-research/.claude/handoff/step3/spec-wave2-ideas.md`, `.../spec.md`, `.../research-research.md`, `.../design-a.md`, `/home/user/step3-research/services/python_agents/tests/live/experiments/usage_window0.json`, and the source files cited inline
