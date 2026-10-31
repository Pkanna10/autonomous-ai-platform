# E0b: Amdahl headroom audit of the 10 OSS libraries

Date 2026-10-26. Free and offline: no API call, no git write in the repo.

## Status: partial. The measurement step was blocked

- **Done:** all 10 libraries cloned at their pinned tags into
  `.claude/handoff/step3/e0/amdahl/<lib>`. Every `HEAD` equals the manifest's 40-hex
  commit. The workload is copied in as `benchmarks/bench_<lib>.py`, the way
  `install_workload` does it (no commit, since the clones are scratch).
- **Blocked:** running the workloads. The auto-mode permission classifier
  denied running the cloned third-party code ("Code from External"). So the
  three timed runs, the cProfile run and the sampled run were **not** done
  locally. Downloading the CI `live-results-*` artifacts of L0, L2a and L2b
  through `gh` was also refused: the proxy returned 403 on blob storage.
- **So the numbers below are recorded, not re-measured.** The profiled
  shares come from each library's `profile` note in
  `tests/fixtures/live_oss/manifest.json` (cProfile at pin time; plain wall
  time as noted there). Each share is a function's cumulative time divided
  by the profiled total. "Proven headroom" means gains the engine actually
  delivered and re-tested, from STATUS.md (rows O, O-ed, E5o, Ev, L2a, L2b).
  The process_spawn column is new evidence. It comes from running the
  engine's own `anticheat._spawn_problem` over every `.py` file of each
  pinned checkout. That check is an AST parse that reads the files and never
  runs them.
- **Ready to finish once allowed** (locally with a Bash allow rule, or in a
  CI job with no API calls). Each run takes about 10 s per library:
  `.claude/handoff/step3/e0/amdahl_scripts/run_one.sh <lib>`, then
  `python3.11 -I analyze.py .claude/handoff/step3/e0/amdahl_out/<lib> .claude/handoff/step3/e0/amdahl/<lib> <module_root> <floor>`.
  `run_one.sh` does 3 timed runs the harness way: Python 3.11 as in CI,
  `PYTHONPATH=<wt>[:<wt>/src]`, `PYTHONHASHSEED=0`, run from the worktree.
  It then does one cProfile run and one sampled run through `driver.py`
  under `-I`. The profile comes out as JSON, never pstats, so nothing is
  unmarshalled from an untrusted process. `analyze.py` passes library time
  down the caller graph, so C builtins and stdlib called from library code
  count as library time. It reports each library's self share, its
  inclusive share and the stdlib/C split, the top 10 functions by
  cumulative time, and the top functions by self time. I self-tested it on
  a toy package I wrote (library inclusive 53 %, matching `hot` + `cold`
  cumulative). Known limit: the SIGPROF sampler gets about 40 samples per
  second (kernel timer granularity), so its shares are only a rough check
  on cProfile's overhead.

**The rule applied.** A single change clears the noise only if
`share x fraction removed >= 1.5 x floor`. When the plain-time share is
below 1.5 x floor, the change cannot pass at all. cProfile inflates
call-heavy code by 2.5-4.5x here (profiled vs plain), so a profiled share
overstates the plain-time share of tiny, call-heavy functions. The floor is
also not fixed: each run recalibrates it from 3 A/A blocks. L0's values are
one draw (L2b delivered `sortedcontainers` at 2.6 %, under L0's 5.94 %).

## Table

| Library | Floor (1.5x) | Plain / profiled s | Top library hotspot, cumulative share (profiled) | Largest single self share (recorded) | Pure-Python, output-identical ceiling (estimate) | Hotspot > 1.5x floor? | Stdlib/C dominated? | process_spawn-locked files | Proven headroom (delivered) | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| **more_itertools** | 2.00 (3.0) | 1.0 / 4.5 | recipes rolling stats 27.8 % (4 generators: `_windowed_running_mean` 7.3, `_running_median_windowed` 7.3, `_windowed_running_min` 7.1, `_windowed_running_max` 6.0); locked `more.py`: `set_partitions` 15.3, `bucket._get_values` 10.0, `split_when` 5.6 | <= 7.3 % (the four rolling stats have 0.85 s of own time together, 18.9 %) | Editable scope is `recipes.py` only, about 28 % profiled. Its loops are already minimal monotonic-deque/`insort` code. Plausible gain 3-6 % from stacking micro-optimisations. The 100k frozen-slots `Stats` constructions run in dataclass-generated code (`<string>`), which the engine's hotspot filter cannot show. | Yes on share, **marginal on removable time** (about 1-2x the 3.0 % bar) | No (pure Python, plus C `deque`, `insort`, `tee`) | **`more.py` (line 4078 `__import__`)**: 14 of the 20 workload calls, about 31 % of the profile, are off limits | None in 6 attempts (W0 aimed, E5o A and B, L2a x2, L2b) | **Guard-limited plus marginal.** Headroom exists, but most of it sits in a file the rule refuses. |
| **pyparsing** | 2.12 (3.18) | 0.6 / 1.6 | `_parseNoCache` 77.5 %; `infix_notation` `parseImpl` 68.8 %; `ParseResults` construction 12.5 % | **22.5 %** (`_parseNoCache` own) | High. Nearly all profiled time is pure-Python library code (exception-driven backtracking). A 15 % cut of `_parseNoCache`'s own time, or a per-level memo in `infix_notation`, would clear 3.2 %. Fixed cost (interpreter start, `import pyparsing`, building the grammar) is a larger share of a 0.6 s run. Unmeasured, my estimate is 10-20 %. | **Yes** (by about 20x) | No | none | None in 6 attempts | **Not Amdahl-limited.** The misses come from the hypotheses and the edit difficulty: time is spread across many element classes, and the output must stay identical, parse actions included. |
| **tomli** | 2.00 (3.0) | 0.6 / 1.7 | `key_value_rule` 82.9 %; `parse_value` 52.9 %; `parse_array` 27.6 %; `skip_comments_and_array_ws` 10.6 % | 7.1 % (`skip_chars` own; others not recorded) | High. A pure-Python per-character loop. | **Yes** | No | **none** in the pinned source | 13.3 % (W0 O), 12-13 % twice (O-ed Opus), 10.6 % (Ev, re-test 8.6 %) | **Not Amdahl-limited.** No pinned file trips process_spawn, so the L2a refusals (both reps) came from code the editor wrote: a new import of `os`, `subprocess` or `importlib`, or `__import__`. The Sonnet editor also missed tomli 2/2 in O-ed. |
| **sortedcontainers** | 5.94 (8.91) | 1.6 / 4.1 | `SortedList.add` 26.1 % (insort and bisect in C); `SortedKeyList.add` 22.0 %; `SortedDict.__setitem__` 15.1 %; `_expand` 7.1 + 4.6 % | not recorded | Low. `add` is already the minimal bisect/insort path, and much of its time is C list work plus the benchmark's key lambda. Inlining the `_expand` fast-path check saves about 450k calls x 60-80 ns, roughly 30 ms (about 2 % of 1.6 s). Plausible total 2-4 %. | **No.** No single change plausibly removes 8.9 %. | **Partly** (bisect, insort, list.insert in C) | none | 2.6 % (L2b, under a lower per-run floor); none in W0 O (combination failed the re-test) or L2a | **FLAGGED: noise-limited.** The highest floor of the set on an already-tuned, C-backed library. The manifest itself calls it a real-code control. |
| tabulate | 4.26 (6.39) | 0.8 / 3.6 | column type inference 50.0 %; padding and alignment 23.6 % | not recorded | Very high (`re._compile` lookups 110k, redundant string parsing of numeric cells) | Yes | No | none | 61.6 % (Ev), 47.2 (L2b), delivered in both L2a reps (the L2a row lists 41.0, 12.0, 9.1, 13.1 % for tabulate and idna together) | Not limited |
| mistune | 2.20 (3.30) | 1.4 / 3.9 | `InlineParser.parse` 57.9 %; renderer dispatch 20.0 %; emphasis finalisation 19.2 %; `build_closing_bracket_map` 5.6 % | not recorded | Medium. Regex scanning is C, but the Python dispatch around it can be removed. | Yes | Partly (`re`) | `src/mistune/plugins/__init__.py` (`importlib.import_module`), not hot | 9.4 % (L2a), 6.1 (L2b), 3.2 (W0) | Not limited. One L2a refusal: a trial touched the locked file, or its own code tripped the rule. |
| sqlparse | 2.25 (3.38) | 1.5 / 5.1 | grouping 51.0 %; statement splitter 34.5 %; `Lexer.get_tokens` 23.5 % | 9.8 % (`get_tokens` own) | Medium-high (`utils.imt` 524k calls, token matching 21.6 %) | Yes | Partly (`re` in the lexer) | none | 10.1 % (L2a), 8.8 (L2b), 4.0 (W0) | Not limited |
| markdown | 2.90 (4.35) | 1.2 / 3.4 | inline tree processor 60.6 %; `__handleInline` 47.1 %; `__applyPattern` 34.7 % | **15.0 %** (`__applyPattern` own) | High | Yes | Partly (`re`) | `markdown/core.py` (`importlib.import_module`), not hot | 30.5 % (Ev), 10.2 (W0), 9.5 (L2b), 5.6 (L2a) | Not limited |
| idna | 2.71 (4.07) | 1.0 / 3.3 | `ulabel` 49.1 %; `check_label` 23.9 %; `intranges_contain` 9.7 %; `uts46_remap` 5.5 % | not recorded | Medium. About a third of the time is the stdlib `punycode` codec, which cannot be edited. | Yes | **Partly** (about 1/3 stdlib codec, plus `unicodedata`) | none | 15.5 % (L2b), both L2a reps (9-13 %), 10.1 (W0) | Not limited |
| pycparser | 2.00 (3.0) | 0.8 / 2.5 | `CParser._peek` 48.8 %; `_TokenStream.peek` 44.0 %; `_fill` 41.6 %; `_match_token` 25.6 % | not recorded | High (token lookahead overhead) | Yes | Partly (lexer `re`) | `pycparser/__init__.py` (`subprocess.check_output`), not hot | 27.7 % (L2b), 2.9 (L2a) | Not limited |

## Findings

1. **One library is noise-limited.** For `sortedcontainers`, no single
   pure-Python change plausibly removes 1.5 x 5.94 % = 8.9 %. It is already
   tuned and backed by C. Treat it as an expected no-win control in success
   rates and E-stage budgets. Do not use it to judge the idea pipeline.
2. **One is guard-limited.** In `more_itertools`, the hot code that could be
   edited sits mostly in `more.py`, about 31 % of the profile. The
   process_spawn capture rule refuses any edit to that file because of one
   existing line (4078, `__import__('concurrent.futures')`). The rule scans
   the new blob, not the diff, so it flags code that was already there. What
   remains, `recipes.py`, gives a marginal 3-6 % ceiling against a 3.0 % bar.
3. **Two are not Amdahl-limited at all.** `pyparsing`'s largest self-time
   share is about 22 %, with about 77 % in library code. That calls for
   better ideas, not more headroom. `tomli` has 8.6-13.3 % gains delivered
   before. Its Step 3 misses are process_spawn refusals of content the
   editor wrote, since none of its pinned files trips the rule.
4. **Stdlib/C share.** `idna` (about 1/3 in the `punycode` codec) and
   `sortedcontainers` are the most C/stdlib-bound. `mistune`, `sqlparse`,
   `markdown` and `pycparser` are regex-assisted, but Python dispatch
   dominates, and all have delivered at least 6 %.
5. **The profile digest has blind spots.** The engine's hotspot filter keeps
   frames from tracked files only, so time in generated code (dataclass
   `__init__`, e.g. more_itertools' `Stats`) and in C or stdlib functions
   called by library code is not attributed to the library function that
   causes it. `analyze.py` shows a way to do that (caller-graph
   propagation).

## Implication for the Wave 2 idea pipeline

- **Add an Amdahl pre-check at no token cost.** Before spending on a
  hypothesis, require `target share x claimed fraction >= 1.5 x floor` on
  the plain-time share (sampled, or cProfile corrected by the
  profiled/plain ratio), with C and stdlib time charged to the library
  caller. This would drop `sortedcontainers`-style ideas before any editor
  call.
- **Show the generator the editable scope.** List the process_spawn-locked
  files with their reason, and give the editor the rule's import list, so
  it does not trip the rule (tomli). As a separate, security-reviewed
  option, make the rule diff-aware: refuse only findings that are new
  compared with the base blob. That would unlock `more.py`.
- **Score E0-E4 gates on the 8 libraries with headroom.** Count
  `sortedcontainers` as a control. Read `pyparsing` and `more_itertools` as
  the real test of idea novelty. Count `tomli` only after the refusal cause
  is fixed, so a guard artefact is not booked as an idea failure.
- **Before any $ is spent:** re-run this audit with real measurements
  (scripts are ready, no API cost) to replace the recorded shares and my
  ranged estimates.
