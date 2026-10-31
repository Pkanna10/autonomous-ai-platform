# Prompt caching in the engine: how it works today, what it costs, what to change

Investigation date 2026-10-26. Read-only. No API calls were made. Code was read on
`/home/user/step3-research` (branch `claude/step3-research`). Analysis scripts:
`scratchpad/caching/scripts/analyze.py`
and `.../scripts/console.py`.

---

## 0. Summary for the product owner

**What the banner means for us.** The Console's message is a generic hint. It
fires because about 20 % of what we pay for input is billed at the full,
uncached price. For this engine, almost all of that uncached input is content
sent only once: the one "understand" snapshot of each repository, web-search
results and PDFs in the experiments, and the grader's one-off checks. Caching
something sent once costs more, not less (a cache write is 1.25x the normal
price), so most of the "up to 11 %" cannot be had.

**What caching already does.** It already works well. Over the 7 days the
Console counts, caching cut about **$60-69 off the bill** (the Console says
"~$70"). That is gross: about $54-62 after the cache-write surcharge. Without
it, Window 0 alone would have cost about $120, not $78. The editor (the
multi-turn code-changing loop) follows the documented best pattern exactly.
The "77 %" hit rate is low only because each editor conversation is short
(4-6 turns), so every new token has to be written once before it can be read.
That is structural, not a bug.

**Where the money goes.** On a typical Opus-editor run (the OSS wired run at
$0.55) the split is roughly: **output 42-50 %** (caching cannot touch it),
cache writes 37-39 %, uncached input 7-14 %, cache reads 4-5 %.

**Realistic savings from caching changes: about 5 % of upcoming spend.** That
is roughly **$5-8 of the planned $100-140 Wave 2** and about 2-4 cents per
$0.55 run. Most of it comes from one fix in the Wave 2 design, plus a few small
plumbing fixes.

- **Change now (cheap, low risk, before Wave 2's E0b/E1):**
  1. Stop writing a cache for requests that are sent once: Wave 2's leap,
     reviewer and auditor, plus the end of every one-off structured request.
     Saves about $0.06 per idea-pipeline call on Opus and $0.15 on Fable, so
     about $5-7 over Wave 2.
  2. Fix E0b's pre-registered gate. As written ("0 cache reads on S1") it
     will fail for every library after the first, for a harmless reason.
  3. Log cache usage per role (understand, generator, lanes, leap, reviewer,
     editor) in the live cost tables, so a broken cache shows up at once.
- **Later (needs design or a security review):** share the repeated part of
  the editor's opening message across trials (about 4 % of an editor run), and
  continue the conversation on a self-retry instead of starting over (small,
  rare).
- **Bigger levers that are not caching**, for your call: run the multi-stage
  idea-probe experiments (E1/E1b) through the Batch API at half price (about
  $15 saved on E1). Reuse one repository "understanding" across the arms and
  repetitions of an experiment (about $2-3 on E2). Test a lower editor effort
  on Opus, because output is the largest cost.
- **Do not:** switch to the 1-hour cache, cache the understand request, or
  chase the hit-rate number itself.

---

## 1. What the documentation says (sources)

The official page https://platform.claude.com/docs/en/build-with-claude/prompt-caching
loaded (WebFetch, both halves). I cross-checked it against the bundled
claude-api skill
(`/tmp/claude-0/bundled-skills/2.1.310/c4e330aaacf94b7e041336c8d60376d4/claude-api/shared/prompt-caching.md`,
`.../shared/cost-optimization.md` and `.../shared/models.md`).

| Topic | Fact |
| --- | --- |
| Enabling | Explicit `cache_control: {"type":"ephemeral"}` on a block (a breakpoint), or **automatic caching**: a top-level `cache_control` that places one breakpoint on the last cacheable block and moves it forward as a conversation grows. Automatic caching uses one of the **4** breakpoint slots. |
| TTL | Default 5 min, refreshed free on every read. 1 h is optional (`"ttl":"1h"`). The lifetime runs from the **start** of the request that writes or reads. A 1 h entry must come before any 5 min entry. |
| Multipliers | 5 min write 1.25x base input. 1 h write 2x. Read 0.05x on Opus 5.5 and Sonnet 5.5, 0.025x on Fable 5.1, 0.1x elsewhere (Haiku 5.5 $0.01). |
| Prices ($/MTok: in / 5 m write / 1 h write / read / out) | Opus 5.5 4 / 5 / 8 / 0.20 / 20. Sonnet 5.5 2 / 2.50 / 4 / 0.10 / 10. Fable 5.1 10 / 12.50 / 20 / 0.25 / 50. Haiku 5.5 (prompt <= 100K) 0.10 / 0.125 / 0.20 / 0.01 / 0.50. Opus 4.8 5 / 6.25 / 10 / 0.50 / 25. The engine's table (`common/config.py:96-125`) matches. *Discrepancy:* the bundled skill's `models.md` gives Sonnet 5.5 reads as $0.20. The live page says $0.10 (0.05x), and the engine uses $0.10 (fixed in `f02e2e7`). |
| Minimum cacheable prefix | 512 tokens on Opus 5.5, Sonnet 5.5, Fable 5.1 and Haiku 5.5; 1,024 on Opus 4.8 (the editor's fallback). Shorter prefixes are silently not cached. |
| Lookback | Each breakpoint looks back at most 20 positions. A run of tool_use blocks, or of tool_result blocks, counts as one position. |
| Invalidation | Prefix order is tools -> system -> messages, and a change invalidates its level and everything after it. A tool-definition or **model** change invalidates everything (caches are model-scoped). `tool_choice`, images and thinking or `effort` changes invalidate messages (on some models also system and tools). Setting or changing a structured-output format is listed as a cache-breaker (cost-optimization.md). |
| Concurrency | An entry can be read only once the first response **begins streaming**. Parallel requests on the same prefix all pay full price. |
| Usage fields | `input_tokens` = tokens **after the last breakpoint** (uncached). `cache_creation_input_tokens` = written (split by TTL in `cache_creation.ephemeral_5m/1h_input_tokens`). `cache_read_input_tokens` = read. Total prompt = the sum of the three. |
| Anti-pattern | "The prompt ends in unique per-request content: the automatic breakpoint lands after the unique tail, so every request pays the write premium on bytes that are never read back - a pure surcharge. Put an explicit marker at the end of the shared portion instead." |
| Break-even | 5 m: 2 uses (1.25 + 0.05-0.1 < 2). 1 h: at least 3 uses. Requests that share a prefix and start less than 5 min apart keep the 5 m entry warm indefinitely, so 1 h buys nothing there. |
| Console "hit rate" | **Not defined in the docs.** The page points to the cache-diagnosis beta (`cache-diagnosis-2026-04-07`) for finding misses. |

---

## 2. How the engine caches today (file:line, `services/python_agents/src/autonomous_ai_agents`)

### 2.1 The plumbing

- `clients/transport.py:103-114`: `LLMRequest.cache: bool = True`. When true,
  the system prompt is sent as one text block with a 5 min breakpoint
  (`_system`, `:464-471`; `_ephemeral` `:460-461`), **and** top-level automatic
  caching is turned on (`cache_control=` on `create`, `:249`; also on
  `count_tokens`, `:225`). So every cached request gets two breakpoints:
  system, plus the last block of the conversation.
- `:117-126` and `_has_long_ttl` `:482-491`: any `ttl` other than 5 m is
  refused, because the cost bound does not cover 1 h writes.
- `:239-251`: the server-side fallback chain (`ENGINE_FALLBACK_MODELS` =
  `claude-opus-4-8`, `common/config.py:203`). A fallback answer is billed and
  cached on another model (caches are model-scoped). It was seen once, in an
  attack run.
- `:209-235`: `count_tokens` runs once per chain model before every request.
  It is free, so it costs latency, not money.
- `clients/cost.py:171-199`: `preflight_estimate` charges **every prompt token
  at max(input, cache_write, cache_read)** (`:197`), that is the 5 m write
  rate, times the chain length. Caching therefore never lowers the reservation,
  and a 1 h TTL would break the bound (precondition, `:37-43`).
  `response_cost` (`:122-168`) prices writes by TTL from `cache_creation`.
- `clients/budget.py:67-74`: `check` refuses an attempt whose estimate passes
  the cap, and `record` adds the actual spend.
- `common/config.py:223-225`: `EDITOR_EFFORT`, one value for the whole
  conversation, "keeps the cache". `:230-237`: generator and matcher on
  Sonnet 5.5 at `medium`. There is no cache or TTL setting anywhere.

### 2.2 Each request type

| Caller | Shape | Caching | Verdict |
| --- | --- | --- | --- |
| `orchestrator/understand.py:297-313` (`ClaudeUnderstander`) | 1 request per run, Opus 5.5 (engine chain), ~2k-token system + a repo snapshot of up to 24 KB listing + 40 KB contents (~16-20k tokens on OSS) | `cache=False` (`:312`; docstring `:16`). A fresh `secrets.token_hex(8)` per request opens the user message (`:297`), so no two snapshots share a prefix. | Correct: single use. Its ~$0.076 per OSS run is uncached input, 13-14 % of a $0.55 run. |
| `optimization/generate.py:214-252` (`generate_hypotheses`), via `clients/structured.py:214-237` | 1 structured request per call (`GENERATOR_MAX_CALLS` 2), Sonnet 5.5 medium. System = instructions (+ playbook when matched). User = fresh-token repo block + hotspots + ask. | `cache=True` (`:251`): system breakpoint (useful when another call with the same system, model, effort and schema follows within 5 min, e.g. the next repo in a CI suite), **plus the automatic breakpoint on the unique user message: a write that is never read.** | Mostly fine. The tail write is the documented anti-pattern, but small (~3-5k tokens x $0.50/MTok premium = ~$0.002 a call). |
| `research/playbook.py:350-402` (`match_techniques`) | 1 request, Sonnet, system = instructions + the whole playbook (36 techniques, ~80 KB JSON, ~20k tokens) under `STABLE_TOKENS` (`:176-198`, one secret token per technique set **per process**) | `cache=True` (`:398`). Same tail anti-pattern. | Good: the large system part is reused across calls in one process within 5 min. It is not reused across CI dispatches (new process, new token), which does not matter because dispatches are more than 5 min apart. Off by default (`RESEARCH_RETRIEVAL="blind"`). |
| `execution/editor.py:289-376` (`ClaudeEditor`, `_Session`) | Multi-turn tool loop. Tools = `text_editor_20250728` (974 tokens + 286-token tool-use prompt, `:73-77`), fixed `SYSTEM_PROMPT` (~550 tokens, `:94-136`): a ~1.8k-token prefix. Messages are only appended (`:307-308`), thinking blocks echoed unchanged (`_echoable` `:459-462`), effort constant (`:268-275`), no `tool_choice`. | `LLMRequest(...)` with the default `cache=True` (`:346-352`): system breakpoint (tools + system shared across turns **and across trials** within 5 min) plus the automatic breakpoint moving to the newest block each turn. This is the docs' "robust combination for agent loops". | **Healthy.** Each turn reads the whole prior conversation and writes only the new delta. The only structural waste is the last request's tail (written, never read). |
| `execution/editor.py:488-504` (`_task_text`) | The opening message: the per-trial token notice **first**, then the hypothesis, then the brief (understanding, per-hypothesis hotspots `orchestrator/nodes.py:2755-2761`, protected patterns) | All of it sits after the token, so nothing beyond the ~1.8k system + tools prefix is shared between trials. | The understanding and the protected patterns (~1-1.5k tokens) are written again for every trial. |
| Self-retry (`execution/retry.py`, `editor.py:502-503`) | A fresh editor conversation with the crash feedback | Re-writes the opening and re-views files. The previous conversation's cache goes unused. | Bounded to 1 a run (`config.py:296-297`), so small. |
| `tests/live/discovery_grader.py:247-260` (grader, Opus 4.8) | 1 request per repo | `cache=False` | Correct. |
| `tests/live/experiments/triage.py:48`, `:186` | Haiku batch with a 1 h breakpoint on the rubric | 1 h TTL | Never billed (arXiv blocked the runner). Leave as is. |
| `tests/live/experiments/web.py:226-229` | Web search loop, Opus and Haiku | No `cache_control` at all | Experiment-only (E6, closed): 1.03M uncached input ($2.11). Turn caching on if web research ever lands in `src`. |
| `tests/live/build_improve.py:382-404`, `experiments/heal.py:862` | Single-shot structured requests | `cache=False` / none | Correct. |

**Prefixes that change between calls:** every understand, generator, matcher
and grader request has a fresh per-request fence token at the top of its user
message, so nothing after the system prompt can be shared between calls (by
design; it is a prompt-injection defence). The editor's per-trial token does
the same between trials. Playbook tokens are per process.

**Model and effort splits:** roles on different models (Opus understand and
editor, Sonnet generator, Opus 4.8 grader) never share caches, and they also
use different system prompts, so nothing is lost by this. Effort is pinned per
route, so no effort-induced misses.

**TTL:** 5 m everywhere in `src`. Editor turns and trials are minutes apart
(an L2b repo took about 4.2 min in all), so 5 m stays warm and 1 h would only
double the write price.

---

## 3. The numbers

### 3.1 Window 0 (52 runs, $77.78), by suite and model, from `usage_window0.json`

Components are priced at the doc rates, all writes 5 m. Rows billing more than
one model are scaled to the recorded total, so their split is approximate.
"hit" = read / (read + write); "read share" = read / (input + read + write).

| Suite (model) | input | output | read | write | $ in | $ out | $ write | $ read | $ total | hit | read share | read:write |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| oss-ab (Sonnet) | 1.98M | 836k | 10.33M | 4.41M | 3.96 | 8.36 | 11.03 | 1.03 | 24.38 | 70 % | 62 % | 2.34 |
| ab (Sonnet) | 484k | 484k | 4.10M | 1.59M | 0.97 | 4.84 | 3.98 | 0.41 | 10.20 | 72 % | 66 % | 2.58 |
| evolve + evolve-more (Sonnet) | 1.67M | 487k | 5.61M | 2.07M | 3.35 | 4.88 | 5.17 | 0.56 | 13.95 | 73 % | 60 % | 2.71 |
| oss (Opus) | 371k | 108k | 1.53M | 414k | 1.48 | 2.15 | 2.07 | 0.31 | 6.01 | 79 % | 66 % | 3.69 |
| oss (Sonnet) | 371k | 93k | 1.23M | 436k | 0.74 | 0.93 | 1.09 | 0.12 | 2.88 | 74 % | 60 % | 2.82 |
| corpus (Opus) | 34k | 40k | 309k | 102k | 0.13 | 0.79 | 0.51 | 0.06 | 1.50 | 75 % | 70 % | 3.04 |
| hard (Opus) | 47k | 29k | 163k | 66k | 0.19 | 0.58 | 0.33 | 0.03 | 1.14 | 71 % | 59 % | 2.47 |
| sweep / sweep-fable / sweep-record (mixed) | ~0.6M | ~0.3M | ~0.36M | ~0.5M | ~1.9 | ~5.4 | ~1.9 | ~0.05 | 9.79 | ~42 % | ~25 % | ~0.7 |
| web (Opus + Haiku) | 1.03M | 98k | 0 | 0 | 2.11 | 0.87 | 0 | 0 | 3.42 (incl. search fees) | 0 | 0 | - |
| papers, heal, probes, prescreen, acquire (uncached) | ~0.76M | ~33k | ~11k | ~2k | ~1.3 | ~0.4 | ~0 | ~0 | ~2.0 | - | - | - |
| **All Window 0** | **7.45M** | **2.64M** | **24.46M** | **9.85M** | **16.0** | **29.2** | **26.5** | **2.7** | **77.78** | **71 %** | **59 %** | **2.48** |

By model: Opus 5.5 hit 77 %, read share 56 %, read:write 3.36. Sonnet 5.5 hit
71 %, read share 62 %, read:write 2.50.

Window 0 without any caching (reads and writes at base input): about $120
against about $74 of priced tokens. Caching cut that bill by about 38 %.

### 3.2 Window 1 / Wave 1 (STATUS.md "Live spend ledger", lines 1657-1662)

The model split is not recorded. Below, everything is priced at Opus (an upper
bound; the Sonnet generator and L2a's Sonnet editor make the real figures
5-6 % lower).

| Run | $ billed | input | output | read | write | $ in | $ out | $ write | $ read | hit |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| L1a (hard, wired) | 2.21 | 50.8k | 61.1k | 409k | 176k | 0.20 | 1.22 | 0.88 | 0.08 | 70 % |
| L1a re-run | 2.11 | 50.8k | 57.8k | 405k | 168k | 0.20 | 1.16 | 0.84 | 0.08 | 71 % |
| L1b (corpus, wired) | 2.42 | 39.3k | 68.3k | 512k | 205k | 0.16 | 1.37 | 1.02 | 0.10 | 71 % |
| L2a (OSS, Sonnet editor, 2 reps) | 5.94 | 379k | 192k | 2.08M | 828k | (mixed) | | | | 72 % |
| L2b (OSS, Opus editor) | 5.46 | 189k | 121k | 1.53M | 451k | 0.76 | 2.43 | 2.25 | 0.31 | 77 % |
| **Wave 1** | **18.14** | 709k | 501k | 4.94M | 1.83M | | | | | **73 %** |

**A typical OSS wired run (L2b, per repo-run, $0.55):** 18.9k input, 12.1k
output, 153k read, 45k write. At Opus rates: output $0.243 (42 %), writes
$0.225 (39 %), uncached input $0.076 (13 %, essentially the understand
request), reads $0.031 (5 %). Without caching it would cost about $1.11.

### 3.3 Reconstructing the Console's figures (the 7 days hold all of Window 0 and Wave 1)

- **"~$70 est. saved"**: reads x (base input - read rate) = Window 0 $50.6 +
  Wave 1 $9.4-18.8 (all-Sonnet / all-Opus bounds; Wave 1 is mostly the Opus
  editor) = **$60-69**. This matches the Console if it counts gross read
  savings. Net of the write premium (Window 0 $5.3, Wave 1 $0.9-1.8) it is
  **$54-62**.
- **"77 % hit rate"**: token-based read / (read + write) over the 7 days is
  **71.6 %**, and read / (all input) is **59.7 %**. 77 % equals exactly Opus
  5.5's read / (read + write) in Window 0 (and L2b's), and it is also roughly
  what a request-weighted rate (share of requests with any read) would give.
  The docs do not define the metric, so treat 77 % as "about 72-77 % of
  cacheable input was read rather than written".
- **"up to 11 %"**: uncached input is about $18.9 (Window 0 $16.0 + Wave 1
  ~$2.8), 19-20 % of $95.93 spend. Caching ~55-60 % of it, read a few times,
  gives about 11 %, which is presumably the banner's heuristic. **But this
  input is almost all single-use:** understand snapshots under per-request
  tokens (the bulk of oss-ab, evolve, oss and ab input), web-search results
  ($2.1), PDFs ($1.1), the Opus 4.8 grader and heal prompts. A single-use
  prompt cached costs 1.25x, so the realistic share of the 11 % is close to
  zero. The savings found below come from elsewhere.

### 3.4 What the read:write ratio says

In an append-only loop every new token is written once (1.25x) and read once
per later turn. A T-turn trial with a base prefix S and per-turn delta d gives
reads ~ (T-1)·S + d·T(T-1)/2 and writes ~ S + T·d. With T = 5 and S ~ d ~ 4k,
read:write ~ 2.3, which matches the measured 2.3-3.7. So the cache is not
being broken. Conversations are just short. The ratio, and hence the hit
rate, rises only with longer conversations or more cross-trial sharing. The
"low hit rate" is not a defect to fix.

### 3.5 Where the avoidable cost is (ranked by dollars)

1. **Output tokens (42-50 % of an Opus-editor run): caching cannot help.**
   These are the editor's thinking plus tool calls at $20/MTok (`effort`
   unset, so Opus's default `medium`).
2. **Cache writes (37-39 %): mostly unavoidable.** They are the first and only
   time a conversation token is processed. The avoidable parts:
   - the last request of each trial writes its tail and nothing reads it;
   - the brief part of every trial's opening message (~1-1.5k tokens) is
     re-written per trial;
   - a self-retry re-writes the opening and re-views files;
   - one-off structured requests write their unique tail (generator and
     matcher today; in Wave 2 the leap, reviewer, auditor and S1-only second
     call, which are larger and partly on Opus or Fable).
3. **Uncached input (7-14 %): the understand snapshot.** It is correctly
   uncached because it is used once. Reducing it means a smaller snapshot,
   Sonnet as the understander, or reusing one understanding across experiment
   arms.
4. **No issue found** with: tools or system changing between turns, effort
   switching, prompts under the 512-token minimum (every cached prefix is
   >= 1.8k), the 20-block lookback (tool runs collapse to one position), TTL
   expiry inside the editor loop, or the 1 h TTL (not used in `src`).

---

## 4. Recommendations, ranked

Savings are given for a typical $0.55 OSS wired run and for the planned Wave 2
($103-113 unconditional, $130-140 with E3/E4; spec section 6). Wave 2's mix:
roughly $85-95 of editor-heavy wired runs (E2, E2c, E3, E4, L-rows) and about
$35 of idea-pipeline probes (E0b, E1, E1b).

| # | Change | Where | Saves | Risk |
| --- | --- | --- | --- | --- |
| 1 | **Split "cache the system block" from "auto-cache the tail".** Give `LLMRequest` a top-level-automatic knob (e.g. `cache: Literal["none","system","conversation"]`, or `auto_cache: bool`). The editor keeps `conversation`. One-off structured requests use `system` (generator, matcher, Wave 2 S1 and lanes, whose shared part has its own explicit `prefix` breakpoint). Requests sent once with nothing to share (Wave 2 leap, reviewer and auditor's data block, the S1-only second call's prefix) send **no data-block breakpoint**. | `clients/transport.py:103-114, 225, 249, 464-471`; `clients/structured.py:214-237` (with Wave 2's `prefix=`); the call sites `generate.py:251`, `playbook.py:398`, Wave 2 `lane_request`/`review_request` | Today about $0.002 per generate or match call (<0.5 % of a run). **Wave 2: ~$0.06 per idea-pipeline call with an Opus leap and reviewer (~5-6 % of a ~$1.1 call), ~$0.15 with the Fable arm, ~$0.03 with the all-Sonnet arm. About $2.7 on E1, $0.5 on E1b, $1.5 on E2 arm P, $2 on E3/E4: ~$5-7 in all (~5 %).** | Low. No correctness effect. The budget estimate is unchanged (it already charges the write rate), and the cost bound still holds because 5 m writes and reads are unchanged. Cache-busting risk: none, since fewer breakpoints never invalidate a read. A unit test pins the breakpoint count per request kind. |
| 2 | **Fix E0b's gate** (spec line ~1574: "`cache_read_input_tokens` > 0 on the lens lane and 0 on S1"). The lane system prompt is byte-stable across libraries and carries the system breakpoint (`transport.py:469-470`), so S1 of library 2+ will read ~1.2-3k system tokens written by the previous library's S1 within 5 min. As written the gate fails for the wrong reason. Use instead: S1 `cache_creation_input_tokens` >= the counted data block; lane `cache_read_input_tokens` >= the counted data block (about S1's read + creation); S1 `cache_read_input_tokens` <= the counted system-prefix size. | `.claude/handoff/step3/spec-wave2-ideas.md` E0b row; `tests/live/ideas_probe.py` (V7) | Avoids a failed gate and a re-run (~$0.5-5). | None. |
| 3 | **Per-role cache telemetry and a standing check.** The live cost tables already carry in/out/read/write per run. Add a per-role split (understand, generator, lane, leap, reviewer, editor) and assert in the Stage A suite that a second editor turn shows `cache_read_input_tokens` >= the first turn's prompt. Optionally send the `cache-diagnosis-2026-04-07` beta header on live runs only, to name the point of divergence when a read collapses. | `tests/live/conftest.py` / harness recorders; `tests/live/test_contract.py:397` (already has a cache probe) | $0 directly. Catches silent regressions, which the docs call the costliest caching failure. | Low. The beta header only in live suites. |
| 4 | **Share the run-level part of the editor's opening message across trials.** Reorder `_task_text` as [run notice + understanding + protected patterns, under a run-level token, **explicit 5 m breakpoint**] then [per-trial token notice, hypothesis, its hotspots, ask]. Only ~1-1.5k tokens are shareable, because hotspots are per hypothesis (`nodes.py:2757`). | `execution/editor.py:488-527`; the token plumbing in `EditTask` | ~$0.006 per trial after the first, ~$0.02-0.03 per OSS run (~4-5 %), ~$3 on Wave 2's editor-heavy runs. Only while trials start less than 5 min apart. | **Medium (security).** D11 fences all repository text with the per-trial token, and a run-level token is shared by trials and, on a retry, by a worktree the previous edit changed. It needs the security Reviewer and the fence tests extended. Cache-busting risk: the shared block must be byte-identical (render the understanding deterministically, as `_understanding_lines` already sorts notes). |
| 5 | **On a self-retry, continue the trial's conversation** (append the fenced crash feedback as a user turn) instead of a fresh session, when the retry starts within 5 min of the last turn. | `execution/editor.py:232-255, 488-504`; `execution/retry.py` | The prior conversation (~10-20k tokens) is read at $0.20 instead of re-written at $5/MTok (plus the re-views): ~$0.05-0.10 per retry. At most 1 retry per run, rate unknown (E2 measures it). <1-2 % of spend. | Medium. It conflicts with D13/D14's "closed feedback in a fresh context" design. Thinking blocks stay valid only if history is unchanged (append-only is fine). The turn limits must then count the earlier turns. Revisit after E2's retry rate. |
| 6 | **Keep 5 m TTL; do not adopt 1 h.** Turns are seconds to minutes apart, trials within one repo under 5 min, and dispatches hours apart. A 1 h write costs 2x for no extra reads, and the transport refuses it while `cost.py` assumes 5 m. | - | Avoids a +60 % write premium. | - |

**Non-caching levers.** These are bigger than anything above, listed for
completeness (each needs an experiment or an owner decision):

- **Batch API for the idea-probe experiments (E1/E1b).** 50 % off input,
  output and cache rates. The pipeline is staged (S1, then lanes, then
  reviewer), so each stage would be one batch across the libraries. Lanes run
  without fallbacks, which batches require (STATUS E1: fallbacks in a batch are
  a 400). Cache hits in batches are best-effort, so lane reads may miss.
  Potential: ~$15 of E1's ~$30. Not for wired runs (interactive editor).
  STATUS already lists "batch pricing for generation" as open.
- **Reuse one understanding per (library, commit) across the arms and reps of
  an experiment** (harness-level memoization, not prompt caching). E2 has 40
  loops but only 10 libraries: ~$2.3 saved, and similar for E2c and E4. This
  makes arms more tightly paired, which is arguably better for the A/B. Owner
  decision.
- **Editor output (42-50 % of an Opus run).** Opus `EDITOR_EFFORT=low` is
  untested on real code (Sonnet low lost: 2/10 and 6/10 against Opus 7/10).
  One OSS dispatch (~$5) would show whether output drops without losing wins.
- **Understand on Sonnet** would halve its ~13 % share (~7 % of a run). It is
  a quality question, so it needs an A/B.

---

## 5. Wave 2 caching design (D59, spec-wave2-ideas.md lines 659-684, 1114-1160, 528-575)

**Sound, and worth keeping:**

- The data block (`<untrusted_repo_content boundary=T>` ... close) as its own
  content block with a 5 m breakpoint, and everything per-lane after it
  (`<already_on_the_table>`, lens, examples, the Sonnet "think line", the
  ask).
- S1 and the six lenses on one model (Sonnet 5.5), one effort (medium), one
  byte-stable system prompt (section 4.2b.1) and one schema (D45/D46).
- The fan-out starting only after S1 completes, so all lanes, including 4 in
  parallel, can read (the docs' concurrency rule).
- Value: without D59 each lane would pay the ~22k-token data block at $2/MTok
  (~$0.26 per call for 6 lanes). With it the lanes pay ~$0.013 in reads. That
  is ~$0.25 saved per pipeline call, and the spec's "about 0.02 after S1 wrote
  the cache" is right.
- A fresh `T` per pipeline call means no reuse across calls. That is
  intended, and correct for the fence.
- TTL: S1 at 12k `max_tokens` finishes in a few minutes, and each lane read
  refreshes the entry, so 5 m suffices.
- Model-scoped caches are respected: the leap (Opus) and reviewer (Opus,
  own system and fence R) cannot share the lanes' Sonnet cache, as the spec
  says.

**Should change:**

1. **The leap, reviewer and auditor should not write a data-block cache**
   ("its own cache write", lines 258 and 1220-1223). Each is sent once per
   call. The leap shares no prefix with anything else on Opus. The reviewer
   has a different system prompt and schema. The auditor is once per library,
   over a different block. So each write is never read, a pure +25 % on a
   ~25-35k-token prompt: ~$0.025-0.035 each on Opus, ~$0.06-0.09 on Fable
   (arm D). Keep only the system breakpoint (cheap; consecutive libraries
   within 5 min read it) and drop the `prefix` breakpoint and the top-level
   auto-cache for these roles. ~$5-7 over Wave 2 (recommendation 1). The only
   way to make the leap's write pay would be for another Opus request to share
   the leap's system, schema, effort and the T-fenced data block, and the
   reviewer's design (own system prompt, own schema) deliberately does not.
   Keep the design and drop the write.
2. **The S1-only second call** (`call_index >= 1`, lines 318 and 1279) is a
   single request with a fresh T: no `prefix` breakpoint (~$0.01 a call).
3. **Lanes and S1: turn off top-level automatic caching** once the explicit
   `prefix` breakpoint exists. Otherwise each lane also writes its own ~1-2k
   tail (`transport.py:249`), which nothing reads (~$0.005 a call, but it is
   also a third breakpoint in each request for no benefit).
4. **E0b's gate**: fix as in recommendation 2. As written, "0 on S1" fails
   whenever the previous library's S1 ran less than 5 min earlier.
5. **The structured-output system addition**: the spec correctly marks as
   unverified whether it sits before the user turn. The docs list a change of
   `output_config.format` as a cache-breaker, which supports the spec's choice
   of one schema for S1 and the lanes. It also means **any per-lane schema
   variation would silently kill the lane reads**. Pin "one `IDEAS_SCHEMA`
   object, byte-identical, for S1 and every lens" in N2's tests (line 1384
   already pins the bytes before the breakpoint; add the `output_config`
   equality).
6. **Arm B's Sonnet leap at `high`** cannot read the lanes' cache (top-level
   effort differs). Optional: Sonnet 5.5 supports per-message effort (beta
   `mid-conversation-output-config-2026-07-01`: a `role:"system"` message with
   `output_config.effort` placed after the cached prefix), which would let it
   read the data block. It saves ~$0.05 only in arm B. Not worth a beta
   dependency for an experiment arm.
7. **Budget pre-check**: D55's staged arithmetic is right to charge every lane
   prompt at the write rate. A read is not guaranteed (eviction, a byte
   difference), so the 0.40 share stays. Caching lowers actual spend, not the
   reservation. No change.

---

## 6. Caveats

- The model split inside Window 1 runs is not recorded, so Wave 1 figures
  are Opus-priced upper bounds.
- Mixed-model rows in Window 0 are split by scaling.
- The web-suite totals include web-search fees (calculated tokens ~$0.3
  below the recorded total).
- Per-trial, per-turn token sizes (trials per repo, turns per trial) were
  inferred from totals and prompt sizes, not from request logs. The CI logs
  hold them for 90 days.
- The Console's hit-rate definition is not documented. Section 3.3 is a
  reconstruction.
- Wave 2 per-call costs use the spec's prompt sizes (data block ~22k, lane
  output ~6k, leap and reviewer output ~8k), which are unverified until E0b.
