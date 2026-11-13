# s8-expert: expert practice (the four development libraries' own performance commits, set against the engine's finds)

## Core sources (5-12, each: citation, what it covers, why it is standard)

1. **Ma et al., "SWE-fficiency", arXiv:2511.06090v3, 2025.** 498 performance PRs from nine Python repositories, with a function-level attribution of expert gain (Appendix I). It is the closest published measurement of ledger row L10: the share of expert gain in functions the agent never edits.
2. **He et al., "SWE-Perf", arXiv:2507.12415v2 (ICML 2026).** 140 performance PRs with expert patches. It reports expert patch sizes and the expert-to-agent gap.
3. **Shetty et al., "GSO", arXiv:2505.23671v3, 2025.** 102 optimization tasks mined from commit histories. It names three agent failure modes: low-level code, "lazy" optimizations and localization.
4. **Curtsinger and Berger, "Coz: Finding Code that Counts with Causal Profiling", SOSP 2015 (arXiv:1608.03676).** The standard demonstration that the code a profiler ranks highest is often not the code whose change pays.
5. **Bhuiyan, Çakar, Burmane, Davis and Staicu, "SoK: ... ReDoS", arXiv:2406.11618v4.** The survey of the bug class behind about a third of the expert commits here.
6. **Leiserson and Shun, MIT 6.172 (Fall 2018), Lecture 2, "Bentley Rules for Optimizing Work", MIT OpenCourseWare.** The standard teaching taxonomy of work-reducing transformations: data structures, logic, loops, functions. It is the open substitute for Bentley's book.
7. **Python Software Foundation, "The Python Profilers" (Python 3.11 docs).** What cProfile charges to which function.
8. **Berger, Stern and Altmayer Pizzorno, "Triangulating Python Performance Issues with Scalene", arXiv:2212.07597.** The overhead and attribution limits of Python profilers.
9. **Baltes, Moseler, Beck and Diehl, "Navigate, Understand, Communicate: How Developers Locate Performance Bugs", arXiv:1706.10118.** How 12 developers locate real performance bugs with a profiler.
10. **The primary data: 124 commits of sqlparse, tomli, mistune and Python-Markdown (this seat's allowed list).** Read only from the given patches and before/after trees.
11. **The engine's archive and source (internal):** the manifest, `w2-sprint/live/` (974 trial rows, 284 keeps, 345 diffs), and the grounding and profiling code.

## Notes (the methods and results, cited inline as [n])

**What the 124 "performance" commits are** (every commit read; `work/classify.tsv`):
- **84 change speed:**
  - 51 cut runtime on ordinary input;
  - 29 remove superlinear (quadratic, cubic or ReDoS) behaviour on adversarial input;
  - 4 cut import or start-up time.
- **6 are guards:** caps that add cost.
- **34 change nothing in the library's speed:** 13 CI or lint, 10 tests or benchmarks, 3 docs, 2 output size, 6 correctness or feature changes.

A keyword-selected "performance" history is a third noise, so expert-practice mining must read each commit.

**Techniques (84 speed commits).** Remove work 17, precompute or cache 17, algorithm 15, regex rewrite 10, loop or branch reordering 8, data-structure change 7, fewer copies 4, lazy evaluation 2, a specialised fast path 2, other 2. In Bentley's terms these fall mostly in "data structures" (precomputation, caching, augmentation, lazy evaluation) and "loops" (hoisting, eliminating wasted iterations) [6].

**Maintainers rarely give a number: 7 of 84 do.**
- tomli 1852743, "~10%"; tomli e419201, "over 5%".
- markdown 86d1e46, "up to ~10x"; markdown c5f1395, "~5x" with about 30,000 placeholders.
- markdown 3f2c551: 125 KB took about 5 s and 250 KB about 22 s before the fix. markdown 5d1363c: an eight-second call before the fix.
- tomli 5aecb99 sits in a release whose CHANGELOG says "~3%"; that attribution is my inference.

**Where the changes sit.** By hand, relative to the function whose work falls:
- 48 of 84 (57 %) change that function itself.
- 36 (43 %) change something else:
  - a module- or class-level regex constant (10);
  - several functions or files at once (9);
  - a data structure built elsewhere (8);
  - import or set-up (5);
  - a caller (4).

**What the published studies find:**
- **SWE-Perf** experts edit on average 131.1 lines, 4.3 files and 7.6 functions [2]. The commits here are smaller: a mean of 1.6 files and 4.5 functions, and a median of 23 changed lines.
- **GSO** human commits average 3.9 files [3]. Its table gives a mean of 250 lines and a median of 110, while its text says "averaging 108 lines": the paper is inconsistent.
- **SWE-fficiency**, from flame graphs, finds that "over 68% of expert gains occur in functions the LM never edits", although "LM and expert modify the same files over 55% of the time" [1].
  - The agents' function-level coverage of expert gain (ERCfunc) is 0.246-0.314.
  - Their wrong-file loss is about 37-45 %.
  - Experts work deeper in the call tree: a weighted depth of 4.5-4.9 against 3.8-4.2 for the agents (Tables 9-10).
- **Agent failure modes** in these studies are the engine's own:
  - "shortcut bias: caches and fast paths instead of structural cost reduction" [1];
  - "lazy optimizations" and "input-specific fast paths" [3];
  - a gap that widens as the number of target functions grows [2].

**Why a profiler hides the location.**
- "Code that runs for a long time is not necessarily a good choice for optimization" [4]. In Coz's studies:
  - in dedup, the hot line was a hash-bucket search, but the fix was three lines in the hash function: 8.95 % ± 0.27 %;
  - in SQLite, perf put the three functions that mattered at 0.15 % of runtime; replacing indirect calls set up at start-up with direct calls gave 25.60 % ± 1.00 %.
- cProfile is deterministic, and "the profilers introduce overhead for Python code, but not for C-level functions, and so the C code would seem faster than any Python one" [7].
  - Scalene measures cProfile at a 1.7x slowdown [8]; the engine's manifest records 2.8-3.4x on these benchmarks (for example, 5.1 s profiled against 1.5 s plain for sqlparse) [11].
  - A regex constant therefore never appears as a hotspot. Its matching time is a C builtin charged under the calling frame: `InlineProcessor.__applyPattern` in markdown, `Lexer.get_tokens` in sqlparse.
- Developers chase "the largest quantities of runtime consumption" through the call graph. The more complex the bug, the less the profiler helped them [9].

**ReDoS.**
- CPython's `re` is a backtracking engine with "neither built-in engine optimizations against ReDoS vulnerabilities nor a native timeout-like mechanism" [5].
- The experts' fixes take three forms:
  - **pattern rewrites:** markdown 18b17e1, 5d1363c, b29a5b6, cb47805, eacff47, 97c1edd; sqlparse 5a3164d;
  - **possessive quantifiers:** markdown 7a29324;
  - **a linear scanner in place of the regex:** markdown 7be0cff, sqlparse d1d8060 and be3b7a6, mistune 96d0f57.
- Mistune's other DoS fixes add a high-water mark (a record of where a failed scan stopped, so it is not repeated): b6b499d, d68b0d0, b3af85d, c2228a2, ae7e9d5.

**Timed sample.**
- **Design:** 32 commits plus 4 A/A controls (identical library code on both sides), on the engine's own four benchmarks, Python 3.11, with both sides' trees.
  - Pass 1: ABBA, 4 blocks, 8 runs a side, one warm-up per side discarded.
  - Pass 2: 14 commits and the 4 controls again, 6 blocks, 12 runs a side.
  - cProfile call counts give a noise-free cross-check.
- **Noise:** the CPU was shared, with a load average of 6-13 on 4 cores while other seats' benchmarks ran.
  - The A/A means were +0.2, +6.5, +9.2 and +3.8 % in pass 1, and -1.0 to +1.4 % in pass 2.
  - A/A single blocks ranged from -17 to +27 %.
  - The per-side coefficient of variation was 2-28 %.
  - One commit that does not touch the benchmark's code path read -8.6 % with all four blocks negative. It is tomli 5aecb99, a timezone cache, and every date in the benchmark is `Z`. At 8 runs a side this host can show a false 8 % effect.
- **Gains that survive both passes,** with every pass-2 block of the same sign:

  | commit | pass 1 / pass 2 | what changed |
  | --- | --- | --- |
  | tomli 7e7658c | +80.9 / +79.6 % | the frozen-key set of tuples, scanned linearly, becomes a nested-dict trie; calls -92.1 % |
  | tomli a7da759 | +7.2 / +12.5 % | a `src[pos:]` slice copy per value removed |
  | sqlparse 012c9f1 | +10.6 / +10.1 % | `imt()` |
  | mistune 56cd21e | +12.0 / +11.2 % | a delimiter scanner across 13 files |
  | sqlparse d1d8060 | +12.1 / +4.4 % | a delimiter pre-pass before lexing |

- **One confirmed loss:** mistune e001d51, a DoS fix that precomputes a bracket map and a link index, reads -18.9 / -11.7 %, with calls +17.1 %. The engine's speed judge would reject it.
- **Gains lost in the noise:**
  - markdown 4b83620 removes 13.8 % of all calls (800,000 `len` calls) yet reads only +6.7 / +2.4 %;
  - mistune bf95c32 removes 13.6 % of calls and reads -0.8 %;
  - tomli 1852743 removes 22.1 % of calls and reads +1.0 %, against its claimed "~10%".
- The other 23 commits read between -9 % and +8 % with mixed blocks.

**Well established:**
- Expert speed-ups often sit outside the profiler's top functions [4][1].
- Agents favour fast paths and caches [1][3].
- Python's regex engine backtracks [5].

**Contested or thin:**
- **The direction of depth.** SWE-fficiency's Figure 7 shows an agent editing deeper than the expert, while its Table 10 shows experts deeper on average [1].
- **Changed lines as a stand-in for gain within one commit.**

## Bearing on the ledger (per row you touch: L#, what your field says, numbers)

- **L10 (measured; full tables below).**
  - **Against the engine's edits:** 85.4 % of the experts' changed library lines lie outside every function the engine edited in any archived run (4,494 lines, 78 speed commits). 52 of the 78 commits touch none of them.
  - **Against the profiler:** I applied the engine's own display rule to the profile at each commit's parent. The rule takes the 30 hotspots by self time and shows the top 8 of them by cumulative time [11]. 86.7 % of changed lines (56 profiled commits) lie outside the shown functions, and 42 of the 56 commits touch none.
  - **Published analogue:** SWE-fficiency's 68 % [1].
- **L1.** The 31 `read:ungrounded` drops come from `idea_lanes._ground`, which drops any non-obvious idea whose quote "lies outside every hot function" [11].
  - Expert fixes in a regex constant, a structure's builder, set-up or a caller can be grounded only when the quoted line happens to sit in a shown hot function.
  - By the profile measure, that held for 14 of the 56 profiled expert commits.
- **L5 / L8.** The engine's 284 keeps:
  - **by mechanism:** fast path 33 %, precompute/cache 28 %, remove work 14 %, loop 10 %, algorithm 7 %;
  - **missing kinds:** no data-structure keep (21 trials) and no copying keep (14 trials);
  - **by file:** sqlparse `lexer.py` 32 of 75 keeps, tomli `_parser.py` 53 of 53, mistune `_inline/links.py` 23 of 80, markdown `treeprocessors.py` 43 of 76.
  - The same fast path is re-implemented inside the same few shown functions, which is the repeat-conflict loss of L5 (21 of 57 conflicts) [11]. The experts' commits spread over 1-13 files.
- **L3 / L4 / L9.** The experts' constant-factor commits (claims of 3-10 %) are below what this host resolves at 8-12 runs a side, which is L3's band. Call counts separated 4b83620 and bf95c32, about 14 % fewer calls each, where wall time could not. That suggests a deterministic co-signal for L4's confirmations.

## Open questions for the seminar

1. **Grounding.** Should grounding also accept a quote in a caller, a constructor or a regex constant reachable from a shown hot function? About 43 % of expert speed commits are of that kind, and the cost is a larger shown context.
2. **Scaling probes.** Should the engine time each hot path at input size n and 2n to find superlinear behaviour as an idea source?
   - 29 of 84 expert commits are superlinear fixes.
   - The exam's "visible only at realistic sizes" plants are this class.
   - tomli 7e7658c (+80 %) is one on the engine's own benchmark.
3. **Trades.** Expert DoS fixes can cost typical-input speed (mistune e001d51, -12 %). Should the objectives ever allow that trade?
4. **Post-mortem metric.** Should the engine adopt SWE-fficiency's function attribution (ERC) as a post-mortem metric on delivered patches?

## Expert commits vs engine finds

**Method.**
- **Expert lines:** each changed line is mapped to its innermost enclosing function with `ast`, on the before and after trees (`work/funcmap.py`).
- **Engine lines:** each kept-trial and delivered hunk is anchored in a tree close to the engine's base (`work/enginemap.py`; 1,016 of 1,077 hunks anchored).
- **Engine-edited functions** (the union over all archived runs): tomli 9, mistune 24, sqlparse 31, markdown 19.
- **hot8:** the engine's display rule, applied to a cProfile run of the same benchmark on the commit's parent tree.

**One expert fix the engine found itself.** sqlparse 939b129 (2026-06-01) builds a group's value from its children's values instead of from `str(self)` of the new subtree.
- It postdates the engine's base, 0.5.5 (2025-12-19).
- The engine found it independently in two runs: X2-0 43093767768 and X2-D 43159147698. The second run's delivered patch also edits `group_tokens`, as the expert's commit does.
- It is a CALLER fix: the cost is charged to `__str__`/`flatten`, but the change sits in `TokenList.__init__`.

**The 12 expert speed commits made after the engine's base,** the ones it could have found:
- 92.6 % of their changed lines lie outside the functions the engine edits, and 8 of the 12 touch none of them.
- 97.1 % lie outside hot8.
- Their measurable gains here, mistune 56cd21e (+11 %) and sqlparse d1d8060 (+4 %), lie mostly outside both.

**L10 per library** (share of changed lines outside):

| library | commits | lines | outside engine-edited | outside hot8 (commits profiled) |
| --- | --- | --- | --- | --- |
| sqlparse | 22 | 611 | 78.7 % | 82.7 % (7) |
| tomli | 16 | 1,209 | 71.1 % | 66.8 % (16) |
| mistune | 13 | 1,381 | 87.8 % | 95.4 % (13) |
| markdown | 27 | 1,293 | 99.4 % | 99.7 % (20) |
| all | 78 | 4,494 | 85.4 % (83.1 % lenient) | 86.7 % (56) |

The lenient count treats module-level lines in a file whose module level the engine also edited as inside.

**Cuts.**
- Runtime-only commits: 82.1 % outside the engine's functions, 83.5 % outside hot8. DoS commits: 96.0 % and 96.4 %.
- Without the three largest rewrites: 86.0 % and 85.6 %.
- The median commit is 100 % outside on both measures.
- **Weighted by the five confirmed gains** (117.8 points):
  - 84 % lies outside the engine-edited functions (by each commit's line share), dominated by 7e7658c, whose function no longer exists at the base;
  - 48 % lies outside hot8;
  - counting whole commits instead, 13 % (41 % without 7e7658c).

**Table columns.**
- **kind:** perf, dos (superlinear on adversarial input), startup.
- **loc:** IN (the function whose work falls), CALLER, CONST (a module- or class-level constant), DATA (a structure built elsewhere), SETUP, SPREAD (several functions or files).
- **A/B:** mean gain, pass 1 / pass 2.
- **eng / hot8:** changed lines inside the engine-edited functions / inside hot8, out of all the commit's changed lines.
- **no tree:** the library source is missing from the given trees.

**sqlparse**

| commit | kind | technique | main place | maintainers' claim | loc | A/B | eng | hot8 |
|---|---|---|---|---|---|---|---|---|
| 012c9f1 | perf | remove work | utils.py:imt | - | IN | +11 / +10% | 24/24 | 24/24 |
| 2bde1b9 | perf | algorithm | grouping.py:group_identifier_list, sql.py:token_index | "much faster when starting in the middle" | CALLER |  | 10/28 | n/a |
| 377031a | perf | algorithm | utils.py:split_unquoted_newlines | "much, much faster" | IN |  | 0/69 | n/a |
| 3a7da1c | perf | data structure | utils.py:Cache | - | DATA |  | 0/47 | n/a |
| 50de51a | perf | algorithm | sql.py:TokenList.group_tokens | "LOOP(list.remove()) is O(n**2)" | IN |  | 3/3 | n/a |
| 52e02fd | perf | remove work | sql.py:Token.match | - | IN |  | 27/46 | n/a |
| 5a3164d | dos | regex rewrite | keywords.py:module | - | CONST | +6 / -2% | 0/2 | 0/2 |
| 6145070 | perf | other | grouping.py:_group_left_right +1 file | "does not solve the problem" | SPREAD |  | 6/52 | n/a |
| 7d43d73 | perf | remove work | sql.py:Token.match | "minor" | IN |  | 2/2 | n/a |
| 7f422d3 | perf | loop/branch | filters.py:IncludeStatement.process | - | IN |  | 0/8 | n/a |
| 8238a9e | perf | regex rewrite | others.py:StripCommentsFilter._process | - | IN |  | 0/5 | 0/5 |
| 848973f | perf | remove work | grouping.py:group_identifier, sql.py:token_next_by_instance | "significantly" (long ID lists) | CALLER |  | 0/9 | n/a |
| 8b3e88e | perf | precompute/cache | utils.py:memoize_generator, filters.py | - | SETUP |  | 0/39 | n/a |
| 939b129 | dos | remove work | sql.py:TokenList.__init__ | quadratic grouping | CALLER | +1 / +2% | 4/4 | 0/4 |
| 95ae0ac | perf | remove work | filters.py:OutputPythonFilter._process | - | IN |  | 0/14 | n/a |
| a16c087 | perf | precompute/cache | sql.py:Token.__init__/match +1 file | - | DATA |  | 20/30 | n/a |
| a3e19f1 | dos | copying | sql.py:TokenList._token_matching | quadratic -> linear | IN | -4% | 5/5 | 5/5 |
| bac3c51 | perf | lazy | filters.py:ReindentFilter._get_offset | "a bit" | IN |  | 0/14 | n/a |
| be3b7a6 | dos | algorithm | utils.py:split_unquoted_newlines | quadratic (GHSA) | IN | +4% | 0/65 | 0/65 |
| d1d8060 | dos | precompute/cache | keywords.py:find_delimited_spans +2 files | O(n^2) -> linear (GHSA) | SPREAD | +12 / +4% | 6/97 | 6/97 |
| d4cc064 | perf | algorithm | grouping.py:_group_matching +2 files | "more efficient" | IN |  | 23/39 | n/a |
| dba96a1 | perf | algorithm | lexer.py:get_tokens_unprocessed | faster for CLOB/BLOB | IN |  | 0/9 | n/a |

Not a speed change (13): 04a3b58, 135bfad, 40ed3aa (guard, -8% in pass 1), 480e52f, 519e416, 5753f15, 7e532bc (guard), 8e50361, 9e4feb2, b9588d9, c9f87f1, da67ac1 (guard), f0708f9.

**tomli**

| commit | kind | technique | main place | maintainers' claim | loc | A/B | eng | hot8 |
|---|---|---|---|---|---|---|---|---|
| 05fafa5 | perf | remove work | _parser.py:parse_inline_table | - | IN |  | 0/9 | 0/9 |
| 0724e2a | perf | other (Final, mypyc only) | _parser.py, _re.py:module | "compiled code" | CONST |  | 0/36 | 0/36 |
| 0dc3cda | perf | loop/branch | ltoml/_parser.py | - | IN |  | no tree | n/a |
| 1852743 | perf | data structure | _parser.py: every parse function | "~10%" | SPREAD | +1% | 187/513 | 203/513 |
| 21061b9 | perf | loop/branch | _parser.py:loads | - | IN |  | 12/13 | 12/13 |
| 3b07bd7 | perf | loop/branch | _parser.py:skip_until | "significant boost to comment parsing" | IN | -4% | 0/43 | 0/43 |
| 45fe156 | perf | loop/branch | ltoml/_parser.py | "free" | IN |  | no tree | n/a |
| 5aecb99 | perf | precompute/cache | _re.py:match_to_datetime | ~3% (CHANGELOG, inferred) | IN | -9% | 0/22 | 0/22 |
| 620ad70 | perf | remove work | _parser.py:parse_hex_char | - | IN |  | 0/3 | 0/3 |
| 64525d7 | perf | remove work | _parser.py:suffix_location (error path) | - | IN |  | 0/9 | 0/9 |
| 6995621 | perf | remove work | _parser.py:parse_value +1 file | - | IN | +4% | 43/112 | 43/112 |
| 716b682 | perf | algorithm | _parser.py: string parsers | "increased parsing speed" | SPREAD | +1% | 4/178 | 4/178 |
| 7e7658c | perf | data structure | _parser.py:NestedDict.is_frozen/mark_frozen/reset | - | DATA | +81 / +80% | 0/42 | 22/42 |
| 809a8ae | perf | loop/branch | _parser.py:parse_value | "slightly" | IN | -2% | 13/13 | 13/13 |
| 9e56735 | perf | data structure | _parser.py:Flags, key_value_rule | "fix performance regression" | DATA |  | 13/32 | 13/32 |
| a7da759 | perf | copying | _parser.py:parse_value | - | IN | +7 / +12% | 77/143 | 91/143 |
| ac7bc05 | perf | algorithm | _parser.py:skip_until | - | IN | +2% | 0/33 | 0/33 |
| e419201 | perf | loop/branch | _parser.py:skip_chars | "over 5%" | IN | +6% | 0/8 | 0/8 |

Not a speed change (7): 4f0299e, 5e2265e, 7026fc9, 920e20b, b4702dd, caf63fe (guard), e1fdb94 (guard).

**mistune**

| commit | kind | technique | main place | maintainers' claim | loc | A/B | eng | hot8 |
|---|---|---|---|---|---|---|---|---|
| 1bc60f6 | perf | copying (tuple for list) | mistune.py | - | IN |  | no tree | n/a |
| 25f2503 | dos | algorithm | inline_parser.py:_is_link_like | - | IN |  | 0/30 | 0/30 |
| 2b04d7b | dos | precompute/cache | block_parser.py:_find_next_blank_line | quadratic | IN | +5 / -1% | 0/19 | 0/19 |
| 56cd21e | perf | algorithm | _inline/delimiters.py +12 files | - | SPREAD | +12 / +11% | 115/832 | 45/832 |
| 8baf90b | startup | precompute/cache | __init__.py:_cached_markdown | - | SETUP |  | 0/22 | 0/22 |
| 96d0f57 | dos | algorithm | formatting.py:_find_end_marker | quadratic | IN | +3% | 0/47 | 0/47 |
| ad8d3c0 | perf | fast path | mistune3/block_parser.py rule | - | DATA |  | no tree | n/a |
| ae7e9d5 | dos | precompute/cache | footnotes.py, ruby.py, spoiler.py | near-linear tests | IN |  | 0/54 | 0/54 |
| b3af85d | dos | precompute/cache | helpers.py:parse_link_text +2 files | O(n^2) -> linear | IN |  | 1/12 | 0/12 |
| b4dd328 | dos | data structure | inline_parser.py:_DelimiterIndex +2 files | - | SPREAD |  | 16/147 | 19/147 |
| b6b499d | dos | precompute/cache | helpers.py:parse_link_text +1 file | O(n^2) -> linear | IN | +2% | 0/20 | 0/20 |
| b909b64 | perf | precompute/cache | mistune.py (compile once) | - | IN |  | no tree | n/a |
| bf95c32 | perf | precompute/cache | inline_parser.py:_find_fast_text_end +2 files | - | SPREAD | -1% | 33/42 | 0/42 |
| c2228a2 | dos | precompute/cache | formatting.py:_parse_to_end +1 file | near-linear tests | IN |  | 2/7 | 0/7 |
| d68b0d0 | dos | precompute/cache | helpers.py:parse_link_text +1 file | O(n^2) -> linear | IN |  | 0/9 | 0/9 |
| e001d51 | dos | data structure | inline_parser.py:_get_link_range_index +1 file | near-linear tests | DATA | -19 / -12% | 2/140 | 0/140 |
| eabd2a7 | perf | fast path | mistune3 "speed" plugin | "mismatch is too slow" | DATA |  | no tree | n/a |

Not a speed change (6): 41aadef, 618ebfb, 7b0194c, 8aac3da, f553dbb, fad026f.

**markdown**

| commit | kind | technique | main place | maintainers' claim | loc | A/B | eng | hot8 |
|---|---|---|---|---|---|---|---|---|
| 07177ce | perf | remove work | inlinepatterns.py:LinkPattern.sanitize_url | - | IN |  | 0/25 | n/a |
| 0bfd8c3 | dos | algorithm | blockprocessors.py:ReferenceProcessor.run +1 file | quadratic | CALLER | +4 / +4% | 0/38 | 0/38 |
| 102e01c | startup | precompute/cache | core.py:build_extension, util.py | "should be more performant" | SETUP | +8 / +3% | 0/15 | 0/15 |
| 11c9e17 | perf | data structure (lists -> sets) | md_in_html.py, htmlparser.py | "much faster when comparing" | DATA |  | 0/48 | 0/48 |
| 18b17e1 | dos | regex rewrite | blockprocessors.py:HRProcessor | - | CONST |  | 0/9 | 0/9 |
| 1caf028 | perf | lazy | postprocessors.py:RawHtmlPostprocessor.run | - | IN | +7 / +2% | 0/36 | 0/36 |
| 35930e0 | perf | remove work | inlinepatterns.py:LinkPattern.sanitize_url | - | IN |  | 0/25 | n/a |
| 3f2c551 | dos | precompute/cache | htmlparser.py:parse_comment | 125 KB about 5 s, 250 KB about 22 s before | IN |  | 0/11 | 0/11 |
| 429cc98 | dos | algorithm | postprocessors.py:RawHtmlPostprocessor.run | "linear iso quadratic" | IN |  | 0/15 | n/a |
| 481e507 | perf | remove work | inlinepatterns.py, postprocessors.py:unescape | "no longer slow" | IN |  | 0/24 | n/a |
| 4b83620 | perf | loop/branch (hoist len) | treeprocessors.py:__handleInline | "tiny ... sizeable" | IN | +7 / +2% | 3/3 | 3/3 |
| 524e4da | dos | precompute/cache | htmlparser.py:line_offset | quadratic line counting | IN | +2% | 0/19 | 0/19 |
| 5d1363c | dos | regex rewrite | blockprocessors.py:ReferenceProcessor.RE | 8 s before | CONST |  | 0/3 | 0/3 |
| 63720f2 | startup | remove work | smarty.py:canonicalize | "module load a bit faster" | SETUP |  | 0/62 | n/a |
| 6f825aa | perf | algorithm (emphasis rewrite) | inlinepatterns.py +2 files | - | SPREAD |  | 5/649 | 0/649 |
| 790aeb5 | perf | remove work (revert) | preprocessors.py:HtmlBlockPreprocessor | "too slow" | SPREAD |  | 0/128 | n/a |
| 7a29324 | perf | regex rewrite | inlinepatterns.py:module | - | CONST |  | 0/12 | 0/12 |
| 7be0cff | dos | algorithm | inlinepatterns.py:BACKTICK_RE, find_code_spans | - | CONST | -3% | 0/55 | 0/55 |
| 82d2b25 | startup | remove work | __meta__.py:_get_version | "high memory and startup time cost" | SETUP |  | 0/27 | 0/27 |
| 86d1e46 | dos | copying | fenced_code.py:FencedBlockPreprocessor.run | "up to ~10x faster" | IN | +1 / +3% | 0/10 | 0/10 |
| 97c1edd | dos | regex rewrite | inlinepatterns.py:HTML_RE | quadratic -> linear | CONST | -3% | 0/2 | 0/2 |
| a4d4428 | dos | remove work | tables.py:TableProcessor.test | quadratic for long blocks | IN | +0% | 0/11 | 0/11 |
| b29a5b6 | dos | regex rewrite | attr_list.py:BASE_RE | O(n^2) -> linear | CONST |  | 0/2 | 0/2 |
| c5f1395 | perf | precompute/cache | postprocessors.py:RawHtmlPostprocessor.run | ~5x with ~30,000 placeholders | IN |  | 0/2 | 0/2 |
| cb47805 | dos | regex rewrite | inlinepatterns.py:several RE | quadratic -> linear | CONST |  | 0/10 | 0/10 |
| eacff47 | dos | regex rewrite | blockprocessors.py, fenced_code.py RE | cubic ReDoS | CONST |  | 0/16 | 0/16 |
| ef9a229 | dos | regex rewrite | blockprocessors.py:HRProcessor.run | - | IN |  | 0/36 | n/a |

Not a speed change (14): 0145c9e, 43d9167, 5706258 (guard), 5c00f59, 65d6566, 6f024f5, 6f69248, 96d5efc, 9e3e50f, 9eab105, a0cf768, beff310, eda5d19, f0b7f98.

c5f1395 changed the benchmark's output (889,226 -> 889,976 bytes in a single run), so it is not equivalence-preserving there.

## Sources (numbered list, full citations with URL or ISBN)

1. Jeffrey Jian Ma, Milad Hashemi, Amir Yazdanbakhsh, Kevin Swersky, Ofir Press, Enhui Li, Vijay Janapa Reddi, Parthasarathy Ranganathan. "SWE-fficiency: Can Language Models Optimize Real-World Repositories on Real Workloads?" arXiv:2511.06090v3, 2025. https://arxiv.org/abs/2511.06090
2. Xinyi He, Qian Liu, Mingzhe Du, Lin Yan, Zhijie Fan, Yiming Huang, Yin Zheng, Zejian Yuan, Zejun Ma. "SWE-Perf: Can Language Models Optimize Code Performance on Real-World Repositories?" arXiv:2507.12415v2 (ICML 2026, PMLR 306). https://arxiv.org/abs/2507.12415
3. Manish Shetty, Naman Jain, Jinjian Liu, Vijay Kethanaboyina, Koushik Sen, Ion Stoica. "GSO: Challenging Software Optimization Tasks for Evaluating SWE-Agents." arXiv:2505.23671v3, 2025. https://arxiv.org/abs/2505.23671
4. Charlie Curtsinger, Emery D. Berger. "Coz: Finding Code that Counts with Causal Profiling." SOSP 2015; arXiv:1608.03676. https://arxiv.org/abs/1608.03676
5. Masudul Hasan Masud Bhuiyan, Berk Çakar, Ethan H. Burmane, James C. Davis, Cristian-Alexandru Staicu. "SoK: A Literature and Engineering Review of Regular Expression Denial of Service (ReDoS)." arXiv:2406.11618v4. https://arxiv.org/abs/2406.11618
6. Charles Leiserson, Julian Shun. MIT 6.172 Performance Engineering of Software Systems, Fall 2018, Lecture 2, "Bentley Rules for Optimizing Work." MIT OpenCourseWare. https://ocw.mit.edu/courses/6-172-performance-engineering-of-software-systems-fall-2018/resources/mit6_172f18_lec2/
7. Python Software Foundation. "The Python Profilers." Python 3.11 documentation. https://docs.python.org/3.11/library/profile.html
8. Emery D. Berger, Sam Stern, Juan Altmayer Pizzorno. "Triangulating Python Performance Issues with Scalene." arXiv:2212.07597, 2022. https://arxiv.org/abs/2212.07597
9. Sebastian Baltes, Oliver Moseler, Fabian Beck, Stephan Diehl. "Navigate, Understand, Communicate: How Developers Locate Performance Bugs." arXiv:1706.10118, 2017. https://arxiv.org/abs/1706.10118
10. The 124 allowed commits of sqlparse, tomli, mistune and Python-Markdown, read only from this seat's `r3/s8/patches/` and `r3/s8/trees/`. The upstream repositories were not accessed.
11. Engine sources (internal):
    - `services/python_agents/tests/fixtures/live_oss/manifest.json`;
    - `idea-lab/w2-sprint/live/` (`ideas-x2-*.jsonl`, `patches-*`) and `w2-sprint/zero-credit/README.md`;
    - `optimization/idea_lanes.py` (`_ground`) and `optimization/idea_context.py` (the top `hot_functions` by cumulative time);
    - `execution/profiler.py` (self-time ranking, `MAX_HOTSPOTS` = 30) and `common/config.py` (`IDEAS_HOT_FUNCTIONS` = 8);
    - `emergence/round-3/ledger.md`.

Work files (scripts, raw timings, profiles): `/tmp/claude-0/-home-user-autonomous-ai-platform/b0055c45-9f04-5276-ac4b-c180c851948e/scratchpad/r3/s8/work/`.
