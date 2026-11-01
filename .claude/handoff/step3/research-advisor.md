# Advisor tool: investigation and fit for the Autonomous AI Platform engine

Date: 2026-10-26. Investigator: read-only research agent (no file under /home/user
edited, no Anthropic API call made). Docs read live as raw markdown (the `.md`
form of each docs URL, 200 OK), copies under
`scratchpad/advisor/raw/`.
Code cited at `/home/user/step3-research` HEAD `bc08cba` **plus the uncommitted
working tree** that other agents are building (config.py line numbers can move).

---

## 1. Summary for the product owner (plain English)

**What it is.** The advisor tool lets a cheaper model (the "executor", e.g.
Sonnet 5.5) that is doing a multi-step job ask a stronger model (the "advisor",
e.g. Opus 5.5 or Fable 5.1) for a short plan or course correction, in the middle
of the same API request. The executor decides when to ask. The advisor sees the
**whole conversation so far** (system prompt, tool definitions, every file the
editor viewed, every tool result), thinks, and returns a few hundred words of
advice. Anthropic runs this server-side and bills the advisor's tokens at the
advisor's price.

**Is it worth it for us? Not as a product feature now; at most one small,
gated experiment.** Four reasons:

1. **It probably will not save money on our trials.** Our editor trials are
   short (about 5 turns, a 10-13k-token conversation, about $0.11 on Opus and
   $0.055 on Sonnet). One Opus advisor call re-reads the whole conversation
   uncached and writes 1.4-1.8k tokens: about **$0.07 a call**. At Anthropic's
   measured 1.4 calls a task, Sonnet + Opus advisor is about **$0.15 a trial,
   ~1.4x the Opus editor alone** ($0.78 vs $0.55 per library run). With a Fable
   advisor it is about **$0.30 a trial, ~2.7x**. Anthropic's own measurement says
   the same: a pairing cost about 2.1x the executor alone for a gain at the edge
   of noise.
2. **Sonnet may not call it at all.** In Anthropic's check on 20 SWE-bench Pro
   problems, Sonnet 5.5 at its default effort called the advisor on **0 of 20**,
   with or without the recommended prompt (3-4 of 20 at `xhigh`). Our cheap
   editor arm runs Sonnet at `low`, where consult rates fall further. On Sonnet
   5.5 we cannot force the call (`tool_choice` tool/any returns 400).
3. **It breaks our hard cost cap as built.** Our budget reserves a worst-case
   price before every request, from the request's own model chain and
   `max_tokens`. Advisor tokens are not bounded by `max_tokens`, are billed on a
   second model and are invisible to `count_tokens`. Today the engine refuses to
   send the tool at all (fail closed). Making it safe is real engineering.
4. **It opens two trust gaps.** The advice comes back **encrypted** for every
   advisor a Sonnet 5.5 executor accepts, so we cannot log or audit what the
   advisor told the editor. And the advisor reads the user's code: a Fable
   advisor would send private code to a 30-day-retention model, which O15
   forbids outside the public OSS arm (our D63 guard would not catch it today).

**What it would cost and save.** Saving: none expected per trial; the hope is
quality (Sonnet + advisor delivering as often as Opus). Cost of finding out: a
gated experiment of about **$4 (probe) then about $25-30 (A/B)**, plus about one
build unit (~300 lines) to make the editor budget-safe with the tool.

**What to do next (recommendation).**

- Do **not** add the advisor tool to product runs.
- Test the underlying idea ("a stronger model's plan lifts the cheap editor")
  the cheap way first: **the Wave 2 reviewer already writes an Opus plan per
  idea** that the editor reads (D49). Add one arm to E2 (Sonnet editor with
  reviewer plans vs the Opus editor). Also measure **Sonnet 5.5 at `medium` or
  `high` as editor** (never measured on OSS; L2a was `low`); Anthropic's guide
  says to sweep effort before adding a second model, and the advisor must beat
  that anyway.
- Only if the owner still wants the advisor: run the $4 consult-rate probe
  (section 6). If Sonnet consults on fewer than half the trials, stop there.

---

## 2. What the docs say, precisely

Primary page: https://platform.claude.com/docs/en/agents-and-tools/tool-use/advisor-tool
(read in full, 1,854 lines). Linked pages read: optimizing-for-cost-and-intelligence,
server-tools, api-and-data-retention, pricing, prompt-caching, tool-reference,
define-tools, effort, task-budgets, context-editing, beta-headers,
managed-agents/multiagent-orchestration (URLs in section 9). The claude-api
skill's cached docs (`/tmp/claude-0/bundled-skills/2.1.310/.../claude-api/shared/tool-use-concepts.md`,
`model-migration.md`, `platform-availability.md`) agree with the live page
where they overlap; the live page was used, so no fallback to the cache was
needed.

### 2.1 What it is

- A **server tool**, beta. Header `anthropic-beta: advisor-tool-2026-03-01`.
  Tool definition `{"type": "advisor_20260301", "name": "advisor", "model": "<advisor id>"}`
  in `tools` (tool-reference lists it as type `advisor_20260301`, Server,
  beta `advisor-tool-2026-03-01`).
- Flow: the executor emits a `server_tool_use` block (`name: "advisor"`, input
  **always empty**; "Nothing the executor puts in `input` reaches the advisor");
  Anthropic runs a separate inference on the advisor model "under its own
  Anthropic-supplied system prompt" and the advisor "receives the executor's
  full transcript as quoted context ... your system prompt, the tool
  definitions, the prior turns and tool results, and the text the executor has
  produced so far in this turn"; the result returns as an `advisor_tool_result`
  block; the executor continues. All inside one `/v1/messages` request.
- "The advisor itself runs without tools and without context management. Its
  thinking blocks are dropped ... Only the advice text reaches the executor."
- **Context the advisor sees: the full transcript, not a question.** The
  executor cannot narrow it.

### 2.2 Supported pairs (advisor must be Sonnet 4.6+ and at least as capable)

| Executor | Valid advisors (from the compatibility table) |
| --- | --- |
| Sonnet 5.5 | Mythos 5.1, **Fable 5.1**, Mythos 5, Fable 5, **Opus 5.5**, Opus 5, Sonnet 5.5 (not Opus 4.8/4.7/4.6, Sonnet 5, Sonnet 4.6: 400) |
| Haiku 5.5 | Mythos/Fable 5.1 and 5, Opus 5.5, Opus 5, Opus 4.8, Opus 4.7, Sonnet 5.5, Sonnet 5, Haiku 5.5 |
| Opus 5.5 | Mythos 5.1, Fable 5.1, Mythos 5, Fable 5, Opus 5.5, Opus 5 |
| Fable 5.1 | Mythos 5.1, Fable 5.1 only |

Invalid pair: `400 invalid_request_error`. So Sonnet 5.5 + Opus 5.5 or + Fable
5.1 is valid; Opus 5.5 + Fable 5.1 is valid; Fable 5.1 can only be advised by
Fable/Mythos 5.1.

### 2.3 Result variants: encrypted advice

`advisor_tool_result.content` is `advisor_result` (plaintext `text`) or
`advisor_redacted_result` (`encrypted_content`, opaque). **Sonnet 5.5, Fable
5.1, Mythos 5.1, Opus 5.5, Opus 5, Fable 5, Mythos 5 and Haiku 5.5 advisors
return the encrypted form**; "Claude Sonnet 5.5, ... Claude Opus 5.5 ...
executors pair only with advisors that return the encrypted form, so on those
executors the advice text isn't readable in the response." Plaintext needs an
older advisor (e.g. Opus 4.8), which a Sonnet 5.5 executor rejects. Round-trip
the blocks verbatim; the server decrypts on the next turn.

### 2.4 How the executor decides; forcing and limiting

- The executor calls it "like any other tool"; the tool "ships with a built-in
  description that nudges the executor to call it near the start of complex
  tasks and when it hits difficulty".
- **Forcing:** `tool_choice: {"type":"tool","name":"advisor"}` works on older
  executors, but "Claude Opus 5.5, Claude Sonnet 5.5, Claude Fable 5.1, and
  Claude Mythos 5.1 executors reject `tool_choice` types `tool` and `any`, so
  use the prompt nudge." Not combinable with manual extended thinking.
- **Limiting:** `max_uses` is **per request**, not per conversation; past it a
  call returns `advisor_tool_result_error` `max_uses_exceeded` and the executor
  continues. Conversation-level caps: count client-side and remove the tool
  from `tools` (history blocks may stay; the beta header must still be sent).
- **Steering:** a suggested coding system prompt (call before substantive work,
  when stuck, before declaring done; weigh advice seriously); a Haiku "Hard
  rule" variant (first write must follow an advisor call; +7.5 points on
  Haiku coding, -4 on browse); an Opus checkpoint (only if under-calling); a
  turn-2 user nudge (+7 points on Haiku 4.5, no measurable effect on Sonnet,
  slightly negative on Opus; a turn-2 nudge where the baseline first call was
  turn 7+ cost 3-4 points).
- **Effort:** there is **no effort or thinking parameter for the advisor**;
  only `max_tokens` (total advisor output, thinking plus text, min 1024) and
  `caching`. Executor effort matters: "pairing a Sonnet executor at medium
  effort with an Opus advisor achieves intelligence comparable to Sonnet at
  default effort, at lower cost", and the cost guide warns that lowering
  executor effort collapsed the consult rate in one earlier-model pairing,
  which then scored below the executor alone.

### 2.5 Billing and usage reporting

- Advisor calls are a sub-inference "billed at the advisor model's rates".
  `usage.iterations[]` lists `{"type":"message"}` (executor, executor rates) and
  `{"type":"advisor_message","model":...}` (advisor rates) entries. **Top-level
  `usage` covers executor tokens only**, summed over executor iterations (so
  input is counted once per executor iteration).
- Typical advisor output: 400-700 text tokens, **1,400-1,800 with thinking**.
- "The top-level `max_tokens` applies to executor output only. It does not
  bound advisor sub-inference tokens." Advisor tokens do not draw from a task
  budget. Priority Tier applies per model.
- The tool definition itself costs about **1,000 prompt tokens per request**
  (cost guide), even when never called.
- Token counting "Returns the executor's first-iteration input tokens only"; for
  an advisor estimate, call `count_tokens` with `model` = advisor model.
- Batches supported; `usage.iterations` per item.
- Pricing (pricing page, per MTok): Sonnet 5.5 $2 in / $10 out / $2.50 5m write
  / $0.10 hit; Opus 5.5 $4 / $20 / $5 / $0.20; Fable 5.1 $10 / $50 / $12.50 /
  $0.25. (The skill's cache says Sonnet 5.5 hits $0.20; the live page says
  $0.10, which config.py already uses.)

### 2.6 Caching

- Executor side: `advisor_tool_result` blocks cache like any block.
- Advisor side: `caching: {"type":"ephemeral","ttl":"5m"|"1h"}` is an on/off
  switch (not a breakpoint). Breaks even at about **three advisor calls per
  conversation**; keep it constant. `clear_thinking` with `keep` other than
  `"all"` causes advisor cache misses (cost only). Anthropic's measured runs
  priced "each advisor call, which uses no cache".

### 2.7 Streaming, latency, pause_turn

- The advisor sub-inference **does not stream**: the executor stream pauses
  after `server_tool_use` closes (SSE pings ~30 s), the result arrives in one
  `content_block_start`, then a `message_delta` with updated `usage.iterations`.
- Latency: "about one or two extra frontier-model calls per task, each on the
  task's critical path" (cost guide). Error `execution_time_exceeded` exists.
- A response can end `stop_reason: "pause_turn"` with a pending advisor
  `server_tool_use` and no result: re-send the assistant message unchanged with
  the same tool and header (omitting the tool is a 400). If the executor also
  called a client tool in that turn, the response ends `tool_use` and the
  pending advisor call runs at the start of the next request.

### 2.8 Errors, limits, platforms, other interactions

- Errors are in-band (`advisor_tool_result_error`: `max_uses_exceeded`,
  `too_many_requests`, `overloaded`, `prompt_too_long`,
  `execution_time_exceeded`, `model_not_found`, `unavailable`); the request
  does not fail. Advisor rate limits share the advisor model's per-model
  bucket; an executor rate limit is a normal HTTP 429.
- Composes with other server and client tools in one `tools` array.
  `clear_tool_uses` is "not fully compatible" with advisor blocks.
- Accepts generic tool properties `cache_control`, `allowed_callers`,
  `defer_loading`, `strict`. No statement on `output_config.format`
  (structured outputs) combined with the advisor beyond `strict`.
- Platforms: Claude API, Claude Platform on AWS, Claude Models on Google Cloud
  (Anthropic managed). **Not** Bedrock, Vertex (Google managed), Foundry.
- Data retention table: advisor tool ZDR-eligible **Yes**, HIPAA **No**
  ("Advisor model output is returned in the API response; nothing is stored
  server-side after the response"). Fable 5.1/Mythos 5.1/Fable 5/Mythos 5 are
  Covered Models requiring 30-day retention regardless of feature.
- Managed Agents equivalent: `"advisor": {"type":"enabled","model":...}` in the
  agent's `multiagent` block; no `max_uses`, `max_tokens` or `caching`.
- Python SDK: `anthropic` 1.17.0 in the service venv already has
  `BetaAdvisorTool20260301Param` (model, name, type, `max_uses`, `max_tokens`,
  `caching`, ...), `BetaAdvisorMessageIterationUsage` (`type:
  "advisor_message"`, `model`, token fields) and the beta literal
  `advisor-tool-2026-03-01` (`.venv/.../anthropic/types/beta/beta_advisor_tool_20260301_param.py`).

### 2.9 Anthropic's own measurements (cost guide, references 3, 9, 11, 13)

- Internal agentic-coding benchmark (370 repo tasks): Opus 5.5 `high` + Fable
  5.1 advisor 90.1 %, +1.7 points over Opus `high` alone "at the edge of
  run-to-run noise", $2.92/attempt, ~2.1x; 1.39 consults requested per attempt;
  "the advice saved almost no executor cost" ($1.36 vs $1.38) while
  consultations cost $1.55. It "lands about on Claude Opus 5.5's own effort
  curve, so the advisor bought about what more effort does."
- Same benchmark: Sonnet 5.5 alone 77.8 % at `high` for $0.33, 62.7 % at
  `medium` for $0.16; Opus 5.5 86.6 % at `medium` for $0.84.
- SWE-bench Pro consult check: Sonnet 5.5 + Opus 5.5 advisor, 20 problems: at
  `high`, **0/20 consults** with or without the suggested prompt; at `xhigh`,
  3/20 and 4/20.
- GPQA (single-turn): neither Haiku 5.5 nor Sonnet 5.5 called the advisor on
  any question; +12 % / +25 % cost for the tool definition alone.
- Chartography: Opus 5.5 `low` + Fable advisor consulted 1/300 and scored 7
  points lower. An earlier pairing that consulted on 88 % "matched Fable alone
  at about 1.8 times the cost": "a consult that fires on most tasks costs more
  than running the stronger model itself." In that Managed Agents run, 4 of
  219 advisor replies came from Opus 5 after a safety filter stopped the
  advisor (a substitute model the caller did not name).
- DeepSWE: a low-effort Sonnet 5 executor with an advisor scored 23 points
  above the executor alone (client-side advisor loop, earlier model).
- The guide's rule: "Tune one model before you add a second ... Build a
  pairing only if it beats the single model's whole curve of score against
  spend."

---

## 3. The engine today (read-only, file:line)

Paths relative to
`/home/user/step3-research/services/python_agents/src/autonomous_ai_agents/`.

### 3.1 Editor loop

- `execution/editor.py:1-27` design: one hypothesis, one worktree, hand-written
  loop; reaches Claude only through `clients.transport.call` and files only
  through `WorktreeEditor`; same system prompt and **one tool** cached across
  turns and trials; messages only appended; "no `thinking`, `temperature` or
  `tool_choice` is sent"; `output_config` = `{"effort": EDITOR_EFFORT}` or
  absent.
- Tool: `text_editor_20250728`, name `str_replace_based_edit_tool`,
  `max_characters` 20,000 (`editor.py:72-77`, `editor_tools.py:74`); the tools
  tuple is built once per editor (`editor.py:218-220`).
- Stop handling: `_CONTINUED = {"tool_use","end_turn","max_tokens"}`
  (`editor.py:91`); any other stop reason ends the edit with an error
  (`editor.py:325-327`). **`pause_turn`, which the advisor can produce, would
  today end a trial as an error.**
- Turn and call limits: `EDITOR_MAX_TURNS` 16, `EDITOR_MAX_TOOL_CALLS` 40,
  `EDITOR_MAX_TOKENS` 8,000 per request (`common/config.py:383-390`);
  enforced in `_ended`/`_reply` (`editor.py:334-341`, `390-404`). Only
  `BetaToolUseBlock` counts as a call (`editor.py:299`), so `server_tool_use`
  advisor calls would be uncounted by these limits.
- Echo rule: `_echoable` keeps everything after the last `fallback` block and
  only text before it (`editor.py:459-462`); advisor blocks after a fallback
  would be echoed verbatim (as the docs require), before one they would be
  dropped together with their `server_tool_use` (untested shape).
- Prompt-injection fence: repo text inside
  `<untrusted_repo_content boundary=TOKEN>`, crash feedback inside
  `<untrusted_run_output ...>`, engine text only in
  `<engine_notice nonce=TOKEN>`; text holding the token is withheld
  (`editor.py:94-136`, `426-445`, `560-579`). The token is in the first user
  message (`editor.py:138-141`, `488-504`), so **the advisor sees it too**.
- Fix retry: `EDITOR_FIX_RETRIES` and `_PER_RUN` both 0-1, default 1
  (`config.py:392-396`, `FIX_RETRIES_MAX` `config.py:136`); the retry re-runs
  the editor with `feedback=feedback.render()`
  (`execution/trial_runner.py:1057`), shown as the `_RETRY` notice plus fenced
  run output (`editor.py:170-173`, `502-503`). The feedback is deliberately
  limited to about 147 bits of closure-only text because trial code can read
  secrets and raise them (`execution/retry.py:1-40`).

### 3.2 Model selection per role

- `ENGINE_MODEL` `claude-opus-5-5` (`config.py:202`), `ENGINE_FALLBACKS` on with
  `ENGINE_FALLBACK_MODELS` `("claude-opus-4-8",)` (`config.py:208-217`).
- `EDITOR_MODEL: str | None = None`: `None` keeps the engine chain with
  fallbacks; a set model runs alone (`config.py:254-255`; `role_chain`
  `config.py:634-654`). `EDITOR_EFFORT` default `None` (`config.py:231-233`).
- Generator and matcher Sonnet 5.5 `medium` (`config.py:238-244`); Wave 2 lanes
  Sonnet 5.5 `medium`, leap and reviewer Opus 5.5 `high`
  (`config.py:269-283`).
- Prices: `_DEFAULT_PRICING` has Opus 5.5, Opus 5, Opus 4.8, Sonnet 5.5, Fable
  5.1, Haiku 5.5 (`config.py:98-125`); every model of every active role's chain
  must be priced (`_every_billed_model_is_priced`, `config.py:515-533`).
- Retention guard (D63): `RETENTION_REQUIRED_MODELS = {"claude-fable-5-1"}`
  (`config.py:141-143`); the validator walks **role chains and the engine
  fallbacks only** (`config.py:571-588`). An advisor model is a new place a
  model can receive repository text that this validator does not look at; and
  the set omits Fable 5, Mythos 5 and Mythos 5.1, all valid Sonnet 5.5
  advisors and all Covered Models.

### 3.3 The cost cap: reserve worst case, then record

- `Budget.check(estimate)` before every attempt raises `BudgetExceeded` if
  `spent + estimate > cap` (`clients/budget.py:67-74`); `record` adds what was
  billed and raises if the total passes the cap (`budget.py:76-86`): with a
  true worst-case estimate that "cannot happen".
- `call()` computes `preflight_estimate(count_input_tokens(request),
  request.max_tokens, transport.chain, transport.prices)` once and checks it
  before each attempt (`clients/transport.py:323-331`); a timeout or lost
  connection is charged the **full estimate** (`transport.py:341-346`).
- The bound (`clients/cost.py:11-22`, `171-199`): `len(chain) x (prompt x
  dearest input-side rate + max_tokens x dearest output rate)`, taken over the
  request's chain. Its premises: one attempt per chain model, each reading the
  same prompt and writing at most `max_tokens`.
- `response_cost` prices **each `usage.iterations` entry at its own `model`**
  (an unknown model at the dearest listed rates) (`cost.py:122-168`,
  `_attempt_model` `cost.py:315-322`), so **post-hoc accounting of
  `advisor_message` iterations already works** and is an over-count in the safe
  direction for unpriced models.
- `prompt_token_bound` adds the tool-use system prompt (804) and each server
  tool's documented definition size; **an unknown server tool type raises**
  (`cost.py:94-97`, `234-251`). `advisor_20260301` is not listed, so today the
  engine cannot send the advisor tool at all: fail closed.
- `AnthropicTransport.send` sends only the fallback beta
  (`transport.py:61`, `239-252`); `count_input_tokens` counts each chain model
  (`transport.py:209-235`), which for an advisor request returns only the
  executor's first-iteration input (docs). `_has_long_ttl` checks
  `cache_control` keys only (`transport.py:482-491`); the advisor's own
  `caching: {"ttl":"1h"}` field would slip past the 5-minute-only rule.
- `min_trial_budget()` is one worst-case editor request on the editor's chain
  (`orchestrator/factory.py:149-158`); `role_transport` checks a transport bills
  exactly the role's chain (`factory.py:172-191`).

### 3.4 Does a server tool that bills a second model mid-call fit the pre-check?

**Not as built.** Four premises break:

1. Advisor output is not bounded by `max_tokens`; without the tool's own
   `max_tokens` the bound is the advisor model's output cap (128k on Opus 5.5:
   up to $2.56 a call).
2. The advisor model is not in the request's chain, so its (dearer) rates are
   never in the estimate.
3. One request now has several executor iterations (before and after each
   advice), each re-reading the growing prompt, so input is billed more than
   once per attempt; the advisor also reads the transcript plus its own
   undocumented system prompt.
4. `count_tokens` sees only the executor's first iteration.

It can be made to fit, because `max_uses` and the tool's `max_tokens` give hard
per-request bounds. A sound extended estimate per request, for executor `E`
(chain of length 1, as `EDITOR_MODEL` gives) and advisor `A`, with `u =
max_uses`, `m = EDITOR_MAX_TOKENS`, `a = advisor max_tokens`, `P` = the prompt
bound and `S` = an allowance for the advisor's system prompt and the advice
already in the transcript:

```
executor: (u + 1) x (P + m + u x a) x E.input_side_max + m x E.output
          (assumes m bounds total executor output across iterations; unverified,
           so the safe form uses (u + 1) x m x E.output)
advisor:  u x [(P + m + u x a + S) x A.input_side_max + a x A.output]
```

plus the ~1,000-token tool definition in `BUILTIN_TOOL_INPUT_TOKENS`, `S` from
a `count_tokens` pass with `model = A` (as the docs suggest), and the advisor
model in the price-table validator and the D63 validator. Worked example
(Sonnet 5.5 executor, Opus 5.5 advisor, `u = 1`, `a = 2,048`, `P = 40k`, `S =
4k`): executor 2 x 50.2k x 2.5e-6 + 2 x 8k x 10e-6 = 0.251 + 0.160 = $0.41;
advisor 54.2k x 5e-6 + 2,048 x 20e-6 = 0.271 + 0.041 = $0.31; **$0.72 reserved
per request vs $0.18 today** (40k x 2.5e-6 + 8k x 10e-6). The cap still holds
(the run cap is $5, `config.py:441`), but each request reserves ~4x more, so a
run near its cap refuses trials earlier, and every timeout is charged the
bigger estimate. Under-sizing `S` is the one way the bound silently fails;
`Budget.record` would then raise after the fact.

### 3.5 Wave 2 roles and retention (spec-wave2-ideas.md)

- D58 roles: lanes Sonnet 5.5 `medium`, leap and reviewer Opus 5.5 `high`;
  Fable 5.1 only as E1 arm D (`.claude/handoff/step3/spec-wave2-ideas.md:625-655`).
- D49: the reviewer runs **in a fresh context on a different model**, may only
  remove ideas for enumerated, checkable reasons, and writes a <= 500-character
  `change_plan` that the editor reads fenced in the hypothesis rationale
  (`spec-wave2-ideas.md:325-379`). Its *why* includes "fresh-context verifiers
  beat self-critique" and "a plan cuts the editor's rediscovery".
- D63 retention guard and O15: Fable may see code only in the experiment arm
  on the public OSS libraries (`spec-wave2-ideas.md:759-772`; `STATUS.md`
  "owner: the Wave 2 idea-pipeline build plan signed off", O15).
- **Would the advisor send the user's code to the advisor model? Yes.** It
  receives the full transcript: system prompt, tool definitions, and every
  `view` result (the user's source). A Fable advisor therefore sends private
  code to a 30-day-retention model. D63 would have to cover an advisor model
  field (and the retention set should list every Covered Model).

---

## 4. The evidence (STATUS.md, `/home/user/step3-research`)

| Run | Editor | Delivered | Cost | Source |
| --- | --- | --- | --- | --- |
| Window 0 corpus | Opus vs Sonnet | 12/12 each | Sonnet 0.45x | STATUS.md:1578 (register) |
| E8a escalation (corpus) | Sonnet `low`, Opus `high` on failures | 12/12, no escalation | $0.59 total | STATUS.md:1488, 1585 |
| Window 0 OSS aimed, 2 runs each | Opus vs Sonnet | **Opus 12/20, Sonnet 8/20** | Opus ~$3.0/10 libs, Sonnet ~$1.4-1.5/10 | STATUS.md:1590, 1705-1709; `tests/live/experiments/usage_window0.json` |
| L2a OSS `wired`, 2 reps | Sonnet 5.5 `low` | **8/20** (2/10, 6/10) | $5.94 (3.25 + 2.69): **$0.27-0.33 a library run** | STATUS.md:61-62, 1661 |
| L2b OSS `wired` | Opus 5.5 (default effort) | **7/10** | $5.46: **$0.55 a run, $0.78 a win** | STATUS.md:63-64, 1662 |
| W5 gate | flip editor to Sonnet `low` if L2a >= 10/20 | not met: Opus stays | - | spec.md:351-353, 1375-1376, 1488 |

What it says:

- On synthetic corpora the editor model does not matter (12/12 each). On real
  libraries Opus is ahead: pooled Opus 19/30 (63 %) vs Sonnet 16/40 (40 %), but
  Sonnet `low`'s two reps were 2/10 and 6/10, so the noise is about as large as
  the gap; n = 10 per arm cannot separate differences under ~25-30 points.
- Per trial (inference from the L2b and L2a token totals at ~5 trials per
  library, `spec.md:1375-1376`): an Opus trial is ~5 turns, ending at a
  10-13k-token conversation, costing ~$0.11; a Sonnet `low` trial ~$0.055.
  Most of an Opus trial's cost is output and cache writes, not reads.
- **Where an advisor could help:** the failures are on real libraries
  (`more_itertools`, `pyparsing`, `tomli` never delivered by either editor;
  `sortedcontainers`, `pycparser`, `markdown` swing). That is "hard in spots",
  the advisor's stated fit. But both editors miss the same three libraries, so
  a stronger plan helps only where Opus succeeds and Sonnet does not: at most
  the 3-4 libraries that differ between L2b and L2a.
- **Where it cannot help cheaply:** Sonnet `low` is exactly the regime where
  Anthropic saw consult rates collapse; and the price of one Opus consult
  (~$0.07) is more than the Sonnet trial itself.

---

## 5. Assessment

### 5.1 Where the advisor fits

| Place | Fit | Why |
| --- | --- | --- |
| Editor trials (Sonnet editor + Opus/Fable advisor) | **Possible, the only real candidate.** | Multi-turn tool loop, hard in spots. But the cost case fails (5.2), Sonnet may not consult, and the advice is unauditable. |
| Idea pipeline lanes with an Opus advisor instead of the reviewer stage | **No.** | Lanes are single structured-output requests (the docs' "weaker fit": nothing to plan; GPQA: zero consults). The reviewer's value is a *fresh* context, a removal-only filter and *checkable* reasons (D49); an advisor sees the lane's own transcript and returns encrypted advice we cannot audit or apply as a filter. Structured outputs with the advisor are undocumented. |
| Leap lane (Opus) with a Fable advisor | **No.** | One request, Fable only on public OSS, and Anthropic's Opus + Fable pairing bought "about what more effort does" at 2.1-3.5x. |
| Fix retry (D12-D14) | **Low value, low risk.** | A "when stuck" moment by design, but at most one retry per run (`config.py:395-396`), so the gain is bounded by the retry rate; the advisor sees the same bit-limited feedback, so no new leak channel beyond the second model. Consider only if the editor experiment passes. |
| HEAL (Step 3c) | **Best conceptual fit, later.** | Bug fixing is the SWE-bench-like case. 3c is not built; evaluate there with the same design (5.4), on a harder bug corpus (Window 0: easy 8/8, hard 8/8, not discriminating). |
| Understand, generator, matcher | No. | Single requests. |

### 5.2 Cost model, worked numbers

Assumptions (inferred from L2a/L2b, labelled): a trial is 5 turns; the
advisor's first call comes after orientation at a ~8k-token transcript plus
~2k advisor system prompt (unverified); a final call at ~13k; advisor output
1.6k tokens (docs' 1,400-1,800 with thinking), no advisor cache (1-2 calls per
trial is below the 3-call break-even); 1.4 calls per trial (Anthropic's
coding measurement; our Sonnet `low` would likely call less).

| Configuration | Per advisor call | Per trial | Per library run (5 trials + ~$0.03 fixed) | vs Opus editor |
| --- | --- | --- | --- | --- |
| Opus 5.5 editor alone (L2b) | - | ~$0.11 | **$0.55** (measured) | 1.0x |
| Sonnet 5.5 `low` alone (L2a) | - | ~$0.055 | **$0.27-0.33** (measured) | 0.5-0.6x |
| Sonnet + Opus 5.5 advisor | 10k x $4 + 1.6k x $20 = **$0.072** | 0.055 + 1.4 x 0.072 = **$0.156** | **~$0.81** | ~1.5x |
| Sonnet + Opus advisor, capped (`max_tokens` 1024 + "under 80 words" line, ~0.5k out) | 10k x $4 + 0.5k x $20 = $0.050 | 0.055 + 0.070 = $0.125 | ~$0.66 | ~1.2x |
| Sonnet + Fable 5.1 advisor | 10k x $10 + 1.6k x $50 = **$0.180** | 0.055 + 0.252 = **$0.31** | **~$1.58** | ~2.9x |
| Opus editor + Fable advisor | $0.18-0.21 | ~$0.37 | ~$1.9 | ~3.4x (Anthropic: 2.1x Opus `high`, 3.5x Opus `medium`) |

Break-even for "Sonnet + Opus advisor is cheaper than the Opus editor": advisor
spend under ~$0.055 a trial, i.e. **at most ~0.75 uncapped Opus calls a trial**
(or ~1.1 capped calls). If the executor consults that rarely, the advisor
cannot lift many trials. The saving case is a narrow window; the quality case
is what an experiment would test. Per run, with the default $5 cap and ~5-10
trials, the advisor adds $0.35-1.25 (Opus) or $1.25-2.50 (Fable) of expected
spend, and the per-request reserve rises from ~$0.18 to ~$0.72 (Opus, section
3.4) or ~$1.20 (Fable).

### 5.3 Risks

1. **Cost unpredictability vs the hard cap.** Fixable only with tool
   `max_tokens` and `max_uses` always set, the extended estimate (3.4), an
   allowance for the advisor's undocumented system prompt measured by
   `count_tokens` with the advisor model, the tool's definition size in
   `BUILTIN_TOOL_INPUT_TOKENS`, the advisor model in the pricing validator, and
   `_has_long_ttl` extended to the `caching` field. Unknown and to verify: does
   the top-level `max_tokens` bound total executor output across iterations or
   each iteration; can the advisor's reply be substituted by another model
   after a safety stop (seen on Managed Agents: 4/219 from Opus 5); how
   server-side `fallbacks` interact with a pending advisor call (only relevant
   if the editor keeps the engine chain).
2. **Prompt injection.** The advisor reads untrusted repository text and
   untrusted run output; its advice returns as an `advisor_tool_result` the
   executor is told (by Anthropic's tool description and the suggested prompt)
   to "give serious weight". The advice is **encrypted**, so the editor's
   `_holds` token check (`editor.py:435`) cannot inspect it, and the advisor
   **knows the trial's boundary token** (it is in the transcript), so injected
   text could ask it to emit a forged `<engine_notice nonce=TOKEN>`. The
   tool-enforced rules (no tests, no config, no symlinks, write limits) and the
   git-side capture still hold, so the damage is bounded to wasted or
   misdirected trials; but the D11 fence premise ("only the engine knows the
   token") no longer holds. Mitigations: re-run the attack corpus with the
   advisor on; add a system-prompt line that advice cannot relax rules or carry
   engine notices; or use a client-side advisor (5.4) whose plaintext output
   the engine can check for the token like any tool result.
3. **Data retention.** Opus advisor: standard retention, same as the Opus
   editor today. Fable advisor: user code to a 30-day-retention model, allowed
   only on public OSS (O15); D63 must cover the advisor field and the retention
   set should add Fable 5, Mythos 5 and Mythos 5.1.
4. **Auditability.** Encrypted advice means the run report cannot say what the
   advisor recommended, and STATUS cannot attribute a win or a violation to
   advice. That conflicts with "reports carry evidence, not claims".
5. **Determinism and offline tests.** `ScriptedTransport` replays
   `BetaMessage` fixtures (`transport.py:265-303`), so mechanics can be tested
   offline (`server_tool_use` + `advisor_redacted_result` blocks, `pause_turn`,
   `usage.iterations` with `advisor_message`); real advice is encrypted, so
   fixtures are synthetic and cannot test advice quality. Live, the executor's
   choice of when to consult adds variance: two repetitions per arm are the
   minimum.
6. **Anti-cheating capture: unaffected.** The advisor has no tools and cannot
   write; files change only through `WorktreeEditor`, and capture runs on the
   git diff. `written` stays the handler's record. Advisor calls are not
   counted by `EDITOR_MAX_TOOL_CALLS`; add a per-trial advisor counter.
7. **Latency and timeouts.** Each consult adds a non-streamed Opus or Fable
   call on the critical path (Fable turns can be minutes). `LLM_TIMEOUT_S` is
   300 s per attempt (`config.py:377`); a timeout is charged the
   (now larger) estimate and retried.
8. **Cache churn.** Removing the tool to enforce a per-trial cap changes the
   `tools` prefix and invalidates the editor's cache for the rest of the trial;
   prefer `max_uses` per request plus a removal only on the final turns.

### 5.4 If we ever build it: prefer a client-side advisor

A **client-side "consult" tool** (a custom tool whose handler calls Opus through
the engine's own `call()`, with the transcript or a fenced digest as input)
gives: a plaintext answer the engine can log, fence and token-check; a
per-call `Budget.check` that is exact with today's estimator (the advisor
request is an ordinary request on its own role chain); a role in
`role_chain`, so the pricing and D63 validators cover it with no new rule;
`ScriptedTransport` determinism; and our own control of when it fires (e.g.
the engine forces one consult after the first `view`s, which Sonnet 5.5's
`tool_choice` ban rules out for the server tool). Anthropic's DeepSWE
measurement used exactly such a client-side loop "with identical accounting".
The cost is one extra round trip and the loss of the server's encrypted
advice path, which we do not need. This is also close to what the Wave 2
reviewer's `change_plan` already does once per idea, cheaper.

---

## 6. A cheap live experiment (only if the owner wants the advisor tested)

**Question.** Does "Sonnet 5.5 editor + Opus 5.5 advisor" deliver as often as
the Opus editor on the 10 OSS libraries, at no more cost per win?

**Order, cheapest first, each with a stop rule:**

0. **Free (E0-style, no spend):** `count_tokens` with `model =
   claude-opus-5-5` on recorded editor transcripts to size `S`; offline
   `ScriptedTransport` tests of `pause_turn`, `advisor_redacted_result`
   round-trip and `advisor_message` pricing.
1. **C0, consult-rate probe (~$4, cap $6).** 5 libraries (`tabulate`, `idna`,
   `sqlparse`, `markdown`, `sortedcontainers`: the ones that discriminate),
   1 rep, `wired`, Sonnet 5.5 at **`medium`** (not `low`: the docs tie consult
   rate to effort), Opus 5.5 advisor, tool `max_uses` 1 per request, tool
   `max_tokens` 2048, at most 2 consults per trial (client-side), the docs'
   suggested coding prompt plus the Hard rule (first write after a consult).
   Expected: 25 trials x ~$0.13 + fixed ≈ $3.5-4. **Stop** if fewer than 50 %
   of trials consult at least once, or mean advisor spend exceeds $0.10 a
   trial: then the pairing cannot help at a price we accept.
2. **A/B (~$25, cap $35), only if C0 passes.** 10 libraries, `wired`, same
   noise rule, same day, three arms:
   - **A** Opus 5.5 editor, 1 new rep (~$5.5), pooled with L2b's 7/10 to give
     a same-window control and a drift check.
   - **B** Sonnet 5.5 `medium` editor alone, 2 reps (~$0.35 x 20 = ~$7):
     the effort-curve point the advisor must beat (the cost guide's rule).
   - **C** Sonnet 5.5 `medium` + Opus 5.5 advisor, 2 reps (~$0.70 x 20 =
     ~$14).
   Total ≈ $26.5 expected, $35 cap (suite cap via `LIVE_SUITE_CAP_USD`, run
   cap $5 each). A Fable arm (Sonnet + Fable 5.1 advisor, public OSS only,
   `ALLOW_RETENTION_MODELS` in the harness copy) adds ~$1.6 x 10 = ~$16 for one
   rep; run it only if C passes.

**Pre-registered gate (recorded in STATUS before any run, as L5's rule was):**
adopt "Sonnet + Opus advisor" as the editor default only if all hold:

- delivered(C) over 20 >= delivered(A) rate over its 20 (L2b + new rep), and
  pooled per-library discordance `c - b >= 3` for C against B (C wins a library
  B loses at least three more times than the reverse), so the gain is the
  advisor's and not just the effort;
- cost per delivered win(C) <= 0.9 x cost per win(A) (today $0.78);
- every guard held, 0 control wins, and the attack corpus re-run with the
  advisor on shows 0 violations;
- advisor reserve never refused a trial that the plain editor would have run.

**Not met:** the advisor stays out; record the consult rate, advisor tokens
and per-arm costs in the experiment register. State the power honestly: 20 vs
20 at 40-65 % rates detects only ~25-30-point differences.

**Budget context.** Window 1 had ~$182 left with ~$120 committed to the idea
pipeline's E0-E4 (O13), so ~$60 is uncommitted. The full A/B takes about half
of that; the probe alone is cheap. Running it after E2 (which already measures
editor outcomes on the same libraries, and could add a "Sonnet editor + reviewer
plans" arm for near-zero extra cost) avoids paying twice for the same
question.

---

## 7. Recommendation, in order

1. No product change. Do not add the server advisor to any role.
2. In E2, add (or pre-register) a Sonnet-editor-with-reviewer-plans arm against
   the Opus editor: the cheapest test of "a stronger model's plan lifts the
   cheap editor", with plaintext, audited plans.
3. Measure Sonnet 5.5 `medium`/`high` as editor on OSS (arm B above, ~$7):
   L2a's `low` is the one point measured.
4. Only then, and only if 2-3 leave a gap worth closing, run C0 ($4) and, if it
   passes, the A/B ($25). If the editor is built for it, prefer the client-side
   consult design (5.4) over the server tool.
5. Independent of the advisor: extend `RETENTION_REQUIRED_MODELS` to every
   Covered Model (Fable 5, Mythos 5, Mythos 5.1), since D63 should not depend
   on which Fable version is named.

---

## 8. Open questions the docs do not answer

- Whether the top-level `max_tokens` bounds executor output per iteration or
  in total across an advisor request.
- The size of the advisor's Anthropic-supplied system prompt (needed for `S`).
- Whether a server-side `fallbacks` re-run carries a pending advisor call, and
  whether the advisor's own reply can be substituted after a safety stop on the
  Messages API (observed on Managed Agents).
- Structured outputs (`output_config.format`) combined with the advisor tool.
- Advisor effort: fixed by Anthropic; not settable.

---

## 9. Sources

Docs (read 2026-10-26 as raw markdown):

- https://platform.claude.com/docs/en/agents-and-tools/tool-use/advisor-tool
- https://platform.claude.com/docs/en/about-claude/models/optimizing-for-cost-and-intelligence (advisor strategy; refs 3, 9, 10, 11, 13)
- https://platform.claude.com/docs/en/agents-and-tools/tool-use/server-tools (pause_turn, mixing server and client tools)
- https://platform.claude.com/docs/en/manage-claude/api-and-data-retention (advisor ZDR Yes / HIPAA No; Covered Models)
- https://platform.claude.com/docs/en/about-claude/pricing
- https://platform.claude.com/docs/en/build-with-claude/prompt-caching
- https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-reference
- https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools#forcing-tool-use
- https://platform.claude.com/docs/en/build-with-claude/effort
- https://platform.claude.com/docs/en/build-with-claude/task-budgets
- https://platform.claude.com/docs/en/build-with-claude/context-editing
- https://platform.claude.com/docs/en/api/beta-headers
- https://platform.claude.com/docs/en/managed-agents/multiagent-orchestration#give-the-session-an-advisor
- Linked, not fetched: https://code.claude.com/docs/en/advisor, https://platform.claude.com/docs/en/build-with-claude/structured-outputs, https://platform.claude.com/docs/en/build-with-claude/streaming

Skill cache cross-checked: `/tmp/claude-0/bundled-skills/2.1.310/947917b13c4c2f0c5ee95a69f40ea7c6/claude-api/shared/model-migration.md` (Sonnet 5.5 breaking change 5: fewer advisors, all encrypted), `shared/platform-availability.md:31`.

Code and records: `/home/user/step3-research/services/python_agents/src/autonomous_ai_agents/{execution/editor.py, execution/editor_tools.py, execution/retry.py, execution/trial_runner.py, common/config.py, clients/budget.py, clients/transport.py, clients/cost.py, orchestrator/factory.py}`; `/home/user/step3-research/STATUS.md`; `/home/user/step3-research/.claude/handoff/step3/spec.md`; `/home/user/step3-research/.claude/handoff/step3/spec-wave2-ideas.md`; `/home/user/step3-research/services/python_agents/tests/live/experiments/usage_window0.json`; SDK `/home/user/step3-research/services/python_agents/.venv/lib/python3.13/site-packages/anthropic` 1.17.0.
