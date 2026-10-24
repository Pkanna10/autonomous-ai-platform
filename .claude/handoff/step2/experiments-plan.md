# Window 0 experiments: build plan (Lead, 2026-10-23)

Source: the research report "Spend the expiring credit testing discovery"
(`/tmp/claude-0/-home-user-autonomous-ai-platform/b0055c45-9f04-5276-ac4b-c180c851948e/scratchpad/reports/Claude API capabilities for the engine.md`,
read the "30-hour plan" and "Eight constraints" sections). The user approved
all nine experiments. Experiments run ONLY in CI (`live-smoke`, environment
`live`, user approval); nothing here ever calls the API from the container.

SVC = /home/user/autonomous-ai-platform/services/python_agents

## Units and file ownership (disjoint)

| Unit | Wave | Owns | Depends on |
| --- | --- | --- | --- |
| X1 effort + Haiku long tier | 1 | src common/config.py, common/models.py (ModelPrice only), clients/cost.py, orchestrator/understand.py, execution/editor.py; tests/common/test_config.py, tests/common/test_models.py, tests/clients/test_cost.py, tests/orchestrator/test_understand.py, tests/execution/test_editor.py | - |
| X2 generator + matcher | 1 | src research/playbook.py, optimization/generate.py; tests/research/test_playbook.py, tests/optimization/test_generate.py | - |
| X3 experiment harness + probes (E1) | 1 | tests/live/experiments/ (__init__.py, harness.py, test_harness.py, test_probes_live.py); additive-only edits to tests/live/conftest.py if strictly needed | - |
| X4 playbook cards (blind) | 1 | src research/playbook.json, tests/research/test_playbook_cards.py | - |
| X5 triage batch + paper extraction (E2, E7) | 2 | tests/live/experiments/ arxiv_fetch.py, triage.py, extraction.py + their tests | X3 |
| X6 web research + sandbox pre-screen (E6, E8b) | 2 | tests/live/experiments/ web.py, prescreen.py + their tests | X3 |
| X7 discovery: sweep, A/B, escalation (E3, E5, E8a) | 3 | tests/live/experiments/ discovery.py + their tests | U23 corpus.py, X1, X2, X4 |
| Lead | - | .github/workflows/ci.yml (suites), pyproject/uv.lock (an `experiments` extra with pymupdf if X5 needs it), usage reconcile (E9), docs | all |

U23/U24 (hard and OSS corpus) are still being built in this tree and own
.github/workflows/ci.yml, tests/live/corpus.py, tests/live/oss.py,
tests/live/test_*corpus*, tests/live/test_oss*, tests/fixtures/live_corpus_hard/,
tests/fixtures/live_oss/. Never edit, format or stage them.

## Interfaces fixed by the Lead

### X1
- `Effort = Literal["low", "medium", "high", "xhigh", "max"]` in common/config.py.
- `Settings.UNDERSTAND_EFFORT: Effort | None = None` and
  `Settings.EDITOR_EFFORT: Effort | None = None`. `None` sends no `effort`
  key at all, so today's requests stay byte-identical (assert this).
- understand: `output_config = {"format": ..., "effort": x}` when set.
  editor: `output_config = {"effort": x}` when set, else as today. Same value
  on every turn of one editor conversation (cache stays valid).
- Validate against the docs (claude-api skill, platform.claude.com effort
  page) which models in the chain (`ENGINE_MODEL` + `ENGINE_FALLBACK_MODELS`,
  default fallback `claude-opus-4-8`) accept which levels; if a configured
  level is not accepted by a model the request may be served by, fail at
  Settings validation with a message naming the model and the level. Cite
  the doc in a comment. If the docs are silent, do not guess: report it.
- `ModelPrice.long_context: LongContextPrice | None = None` with
  `threshold_tokens`, `input`, `output`, `cache_write`, `cache_read`.
  Haiku 5.5: above 100K prompt tokens $0.50 / $2.50, cache write 0.625,
  cache read 0.05 (check the pricing page for the exact rule: which tokens
  count toward the threshold and whether the whole request is re-priced).
  `response_cost` uses the long rates when an attempt's prompt crosses the
  threshold; `preflight_estimate` uses them whenever the prompt bound can
  cross it. Update the pricing comment in config.py (drop "not modelled").

### X2
- `research/playbook.py`: `PLAYBOOK_PATH = Path(__file__).with_name("playbook.json")`;
  file format `{"version": 1, "techniques": [<Technique JSON>, ...]}` using
  the existing `common.models.Technique` / `Precondition` (id given
  explicitly in the file, equal to the slug; slugs unique and match
  `^[a-z0-9][a-z0-9-]{1,62}$`). `load_playbook(path: Path = PLAYBOOK_PATH) -> tuple[Technique, ...]`
  refuses unknown versions, duplicate slugs, id != slug, unknown fields.
  Tests use their own fixture file (X4 writes the shipped one in parallel).
- `match_techniques(transport, budget, *, understanding, hotspots, techniques, k=3, effort=None) -> tuple[TechniqueMatch, ...]`:
  one engine `call()` with `output_config.format` (JSON schema) and the
  optional effort; returns at most k matches sorted by fit, dropping any
  slug not in `techniques` (model output is untrusted). `TechniqueMatch`:
  slug, fit (0..1), justification_summary, unmet_preconditions.
- `optimization/generate.py`: `generate_hypotheses(transport, budget, *, project, understanding, hotspots, objective, techniques=(), n=5, effort=None) -> tuple[Hypothesis, ...]`:
  one engine `call()` with a JSON schema; maps to engine `Hypothesis`
  (source `playbook` with `technique_id` when the item names a provided
  technique, else `novel`; `hotspot_ids` mapped from file+symbol, unknown
  dropped; numbers clamped to the model's bounds; at most n). Hypotheses
  are intent-level (what to change and why, never code), and the prompt
  says trials may never touch tests, benchmarks or judge files.
- Use the type the understand step really produces for `understanding`
  (read orchestrator/understand.py). No schema field may be named or
  described as reasoning, thinking or trace (billed refusal): use
  `justification_summary`. Not wired into the graph (Step 3 does that).

### X3 (harness for raw-SDK experiments)
- `tests/live/experiments/` is a package; its tests use the `live` marker
  and the same skip guard, `live` fixture and suite ledger as tests/live.
- `ExperimentClient(run: LiveRun)`: the real SDK client built like
  `AnthropicTransport` (key from `HOST_KEY`, `ENGINE_API_BASE_URL`,
  `max_retries=0`, redirects off, the `CapturingTransport` wire), exposing
  only what the experiments need: `messages(**params)`, `count_tokens`,
  `models_get(id)`, batches (`submit`, `wait(timeout_s, poll_s)`, `results`),
  files (`upload`, `delete`, always deleted in `finally` by the caller's
  context manager). Every paid call is checked BEFORE it is sent against a
  worst-case bound (prompt bound from count_tokens or bytes, plus
  `max_tokens` at the output rate, plus server-tool fees at `max_uses`,
  1-hour cache writes at 2x input, a PDF at a documented per-page bound)
  and refused when it would exceed the run's cap; every answer is priced
  (batch 0.5x, cache 5 m 1.25x / 1 h 2x / read, web search $10 per 1,000,
  code execution container hours recorded) and recorded into the LiveRun
  so the suite cost table includes it. Reuse clients/cost.py where it fits.
- `ExperimentRecorder`: JSON lines to `$LIVE_RESULTS_PATH` (experiment, arm,
  item, metrics) and a sanitised markdown section to `$GITHUB_STEP_SUMMARY`
  (cells sanitised like the cost table; never raw model or web text beyond
  a capped, sanitised excerpt).
- E1 probes (`test_probes_live.py`, total cap 0.50 USD): GET /v1/models for
  Opus 5.5, Sonnet 5.5, Haiku 5.5, Fable 5.1 (record capabilities);
  citations + `output_config.format`; citations + a `strict: true` tool;
  a PDF `document` block inside a `tool_result` (tiny PDF built in code);
  `fallbacks` inside a one-request batch; web search + `output_config.format`
  (Haiku, `max_uses: 1`); effort `xhigh` and `max` on `claude-opus-4-8` and
  Haiku 5.5. Each probe asserts only that the API answered (a status) and
  records accepted / rejected with a capped error excerpt. Prompts tiny,
  `max_tokens` tiny.

### X4 (blind playbook author)
- 24-30 techniques for CPU-bound pure-Python workloads (runtime and peak
  memory), plus 4-6 plausible distractors whose preconditions rarely hold
  (process pools, C extensions, PyPy, numpy where it is not a dependency,
  async I/O for CPU work). Intent-level summaries, checkable preconditions
  (`check` is a dotted machine key, e.g. `hotspot.membership_test_in_loop`),
  honest expected_gain / provability / risk, references to canonical docs.
- BLIND: never read tests/fixtures/** , tests/live/** , STATUS.md, the
  research report, or anything describing the corpus. Write from general
  Python performance knowledge only.

## Common rules (every Builder and Reviewer)

Read services/python_agents/CLAUDE.md. Then the HARD RULES, SEAMS and REPORT
FORMAT blocks of `.claude/handoff/step2/build-wave.workflow` (lines 16-34)
apply verbatim. Additionally: the Lead commits; one unit = one commit; cite
the doc for every API fact you rely on (claude-api skill or
platform.claude.com; WebFetch is allowed for docs, never the API).

## Lead notes (state that must survive a context reset)

- X1 reviewed (Fable): no blockers; fixing count-margin-near-threshold cap hole + 2 nits. Lead did README/CLAUDE.md docs for the effort knobs.
- X2 built; refactor round: shared plumbing -> clients/structured.py, UnusableReplyError -> common/errors.py, playbook in the cached SYSTEM block behind a per-process stable token. Review after that.
- X4 reviewed (Fable): no leakage, no blockers; fixing 4 contra-indications + distractors.json. NEVER pass corpus details to the X4 author.
- Playbook coverage ceiling (reviewer, from the solutions): live_corpus 12/12 slowdowns and 3/3 attack repos have a plausible card; live_corpus_hard 7/10 repos fully (ledgerclose window max, deliveryround prefix sums: partial; sensormean: none). Use when reading the A/B: arm B cannot beat A where no card fits.
- Persisting playbook cards later: 003_engine.sql techniques.id is UUID; id == slug needs a mapping or a migration (Step 3).
- pyproject has a dead [tool.hatchling.build.targets.wheel] key (hatch reads [tool.hatch...]); playbook.json ships anyway (wheel checked). Fix in the Lead commit.
- CI Compose Init (Postgres) red on 92cefe7: init-log grep matched benign "FATAL: the database system is starting up". Fix with the U23 ci.yml commit.
- X1 committed 12ab3a4; X4 committed 74d0d93.
- X3 reviewed (correctness + security, Fable): 1 blocker (web fetch PDFs ignore max_content_tokens), server-tool passes=10, explicit allowance must not undercut, PDF sizing via count (refuse on count failure; no file/url sources), strip server tools from count_tokens, use X1 long_context, host-pinning transport (results_url TOCTOU), refuse stream, total _priced, hermetic FakeApi, conftest error redaction, E1 web probe on web_search_20260318. Fix round sent; split into harness/bounds/recorder.
- TODO X7: live probe that the second generator/matcher call with the same playbook gets cache_read_input_tokens > 0.
- X2 reviewed (Fable): no blockers; fix round (per-model effort check via config.EFFORT_LEVELS, real StableTokens test, nits). Flaky under -x -n 2: tests/live/test_corpus_guards.py::test_the_blind_hypothesis_states_an_intent_never_a_fix[runtime] (U23 file) - check at U23 verification.
- X2 committed f9487cc. U23 a204fc4 (incl. Compose Init grep fix), U24 b7d3437, pushed. CI suites now: stage-a, corpus, attack, hard, oss (no "all").
- Blind-mode seam (U23 decision 2): trials node passes only hotspots named in hypothesis.hotspot_ids; caller candidates have none, so blind runs get no profile. X7's generated hypotheses DO carry hotspot ids. Decide: engine change (attach top hotspots to candidates without ids) vs STATUS note. Currently documented in service CLAUDE.md.
- When adding the experiments suite to ci.yml: stage-a runs tests/live minus corpus files, so it MUST also --ignore tests/live/experiments.
- Wave 3 started: X7 (discovery.py, test_sweep_live, test_ab_live, test_escalation_live, test_discovery_guards; additive corpus.py) and X8 (nodes.py brief fallback: top-5 hotspots by share when a hypothesis names none of this run; BRIEF_FALLBACK_HOTSPOTS=5).
- X3 fix round done (harness/bounds/recorder split); verification by the correctness reviewer running. Wave 2 started: X5 (arxiv_fetch, triage, extraction) and X6 (web, prescreen). Lead added extra 'experiments' = pypdf>=6,<7 (6.21.2) in pyproject + uv.lock (uncommitted; commit with X3 or X5; CI live job must sync --extra experiments).
- X8 committed 546782e (brief fallback top-5 hotspots; CLAUDE.md updated). X3 verified (all 14 confirmed); last fixes A (close() overrun note + fixture fails on overrun) and C (2 assumption lines) in progress, then commit X3 + pypdf extra. X6 told: web bound is huge (Opus search+fetch 26.69 USD/request worst) -> Opus arms search only, Haiku arms with fetch, E6 need up to ~40 USD accepted.
- X3 committed 93b46e2 with ci.yml suite 'probes' (need 1), stage-a ignores tests/live/experiments, --extra experiments in python + live jobs, test_corpus_guards updated (SUITES, EXPERIMENTS, _suite_needs probes). Pattern for later suites: add case line + options + needs text + SUITES + _suite_needs + dispatch cases. E1 ready to dispatch: suite=probes, cap 1.
- X7 built (needs: sweep 15.45, ab 115 @2 reps, escalation 24.3; expected ~7, 12-18, ~1 USD). In review (Fable). CI TODO with X7 commit: stage-a corpus=() must also ignore test_sweep_live.py, test_ab_live.py, test_escalation_live.py; suites sweep/ab/escalation; LIVE_AB_REPS max 2 (3 = 172.5 > ceiling). X7 ran ruff format over tests/live once (X5 files reformatted; X5 told).
- X5 built (E2 triage cap 1.25, worst 0.39-0.96, expected ~0.1; E7 core cap 10, worst 8.92, expected ~3.3; scale-up opt-in cap 10). Splitting extraction.py -> extraction.py + cards.py, then a combined correctness+security Fable review. Suites to add: triage (need 2), papers (need 10; 20 with LIVE_EXTRACT_SCALE=1).
- X7 reviewed: 2 blockers (E3 shared cap 0.60 << 1.73 worst sum; E5 gen cap 0.30 < 0.475) -> caps = computed worst sums (sweep ~50, ab ~125 @2 reps max), grader -> Opus 4.8 low (not an arm), E8a escalation fallbacks off, McNemar pairs guard-ok only. Fix round sent.
- X5 reviewed (Fable): no blockers; 4 should-fix (screen truncation by sent size + per-call BudgetExceeded, hyphenation loose verify, per-reason counts, write-watch) + nits; fix round sent.
- X6 built: E6 need 39.01 (expected 2-3 USD), E8b need 2.22 (expected ~0.1). In review (Fable, correctness+security; open question: price echoed raw results as output in filtered arm?). Suites to add: web (need 40), prescreen (need 3).
- X7 fix round done: needs sweep 76.15 (92.95 w/ Fable), ab 140 @2 reps, escalation 26.7 (expected ~10-11, 12-18, ~1). Prompt-bound constants per request type; E8a caps from U22 measured worst. Verification by the X7 reviewer running.
- X6 reviewed: no blockers; S1 price echoed raw results as output (filtered arms), S2 MAX_TOKENS 3000, S3 windowed screen + catch, S4 tool_result placement arm, S5 injected-block citations; nits. E6 need accepted up to 55. Fix round sent.
- X5 committed b7146f9 with suites triage (need 2, timeout 90) and papers (need 10, timeout 60); guards updated (SUITES, EXPERIMENT_MINUTES, _suite_needs). X7 verified (all confirmed); last small round: budget_exhausted/trial_budget_error in rows, ESCALATED_CAP 2x (need ~43), docstrings. Then wire sweep/ab/escalation + stage-a ignores.
- X6 committed 81cac62 with suites web (need 52, timeout 90) and prescreen (need 3). Remaining: X7 last round -> commit with suites sweep/ab/escalation + stage-a ignores; then STATUS/README docs; E9 (admin key question pending with user).
- X7 committed bbeb1cb with suites sweep (77, 240 min), ab (140, 360), escalation (43, 90); stage-a ignores DISCOVERY files; options guard wrap-tolerant. ALL 9 experiments' code pushed. Remaining Lead: STATUS/README docs; E9 pending Admin key.
- 2026-10-24 02:56 E1 probes run 39998493959: 7/7 passed, 0.0152 USD (7% of worst case). citations+format -> 400 (confirmed); batch fallbacks -> 400 "not supported for batch requests"; citations+strict tool accepted; PDF in tool_result accepted; web_search_20260318+format on Haiku accepted; xhigh/max accepted on opus-4-8 and haiku-5-5; models API 10 capabilities each. STATUS ledger row TODO.
- Dispatched 02:58: triage 40056352236 (#146), papers 40056353986 (#147), prescreen 40056355592 (#148), escalation 40056357297 (#149); all waiting for the user's approval.
- 2026-10-24 ~03:20: triage #146 FAILED before spend (arXiv search returned 0; error only in job summary). papers #147 PASSED 1.32 USD (4 papers carded, 1602.00602 likely >30 pages skipped; injection test passed). prescreen #148 PASSED. escalation #149 in progress. Fix a02e55e: arXiv retries/backoff, timeout 90, pages 50, error in message; ALL summaries now echoed to the log. Triage re-dispatched.
- Follow-up: tests/live/test_hard_corpus_guards.py::test_a_fix_that_leaves_one_hot_spot_falls_short[ledgerclose] fails deterministically in the container now (partial gain 0.92 vs fix_gain 0.67); passed earlier and on CI. Machine-dependent threshold: re-measure ledgerclose parts / recalibrate.
- User asked (2026-10-24) to dispatch CI runs without waiting; approval gate is the 'live' environment's required reviewers: user must remove it (steps given). Pending their confirmation; then update STATUS guardrail.
- ~03:35: escalation #149 PASSED (cost unread; need its log). triage #151 FAILED: HTTP 429 on every arXiv search attempt (CI IP throttled; id lookups work). Push CI #150 red: orderlookup baseline 0.24 s < 0.3 floor on a fast runner. Fixes: 7b85a50 (orderlookup 44,000 orders), 51a6beb (E2 id-sample fallback, SAMPLE_MONTH 2509). Triage re-dispatched.
- 03:31 escalation #149 (40056357297): 15/15, 0.5930 USD; Sonnet 5.5 EDITOR_EFFORT=low delivered 12/12 slowdowns first pass (no escalation needed), 0/3 controls delivered. ~0.04 USD/run (vs Sonnet default effort 0.045, Opus 0.10). Prescreen #148 passed (log not yet read). Dispatched sweep (cap 77) and web (cap 52) on 51a6beb.
- E9: user has an individual account, Admin API unavailable (docs: individual accounts excluded). Builder X9 stopped; discard its partial files. E9 = manual: user exports Console Cost/Usage CSV (or screenshot) after the runs; Lead reconciles against the cost tables.
- 2026-10-24: org-scoped (non-workspace) key on cost_report -> 403 permission_error 'Missing permissions' (request req_011CgLNUmxpAMpAXz7zhaa1h). Admin/usage API not available on this individual account. E9 = manual Console Cost page reconciliation, final.
