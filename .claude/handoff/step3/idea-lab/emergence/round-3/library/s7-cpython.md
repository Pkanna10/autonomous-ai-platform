# s7-cpython: Python internals and profiling

## Core sources (5-12, each: citation, what it covers, why it is standard)

1. **CPython docs, "profiling", "profiling.tracing" (cProfile) and "profile"** [1]. These cover deterministic and statistical profiling, self and cumulative time, the timer-latency limits and the "not for benchmarking" warning. They are the reference for what cProfile measures.
2. **CPython docs, "profiling.sampling" (Tachyon), and What's New 3.15 / PEP 799** [2]. Tachyon is the stdlib sampling profiler that ships with 3.15. The docs cover sampling error, `--native`, `--opcodes` and where C time is attributed. It is the new reference design.
3. **M. Shannon, PEP 659** [3] and **What's New 3.11, "Faster CPython"** [4]. These cover the specialising adaptive interpreter, the measured speed-ups and inlined Python calls. They define what lookups and calls cost on 3.11+.
4. **M. Shannon, PEP 669** [5] and **CPython `Modules/_lsprof.c`** on the 3.11 and 3.12/main branches [6]. These show how cProfile hooks the interpreter and that the hooks interfere with specialisation. They are the primary source for cProfile's own distortion.
5. **Berger, Stern, Altmayer Pizzorno, "Triangulating Python Performance Issues with Scalene", OSDI 2023** [7]. It measures the overhead of 16 Python profilers on pyperformance and gives the split between Python time and native time. It is the most complete published comparison of Python profilers.
6. **Curtsinger and Berger, "Coz: Finding Code that Counts with Causal Profiling", SOSP 2015** [8]. It argues that where time is spent is not where optimising pays. Its case studies place the fix away from the hot function.
7. **Jin, Song, Shi, Scherpelz, Lu, "Understanding and Detecting Real-World Performance Bugs", PLDI 2012** [9]. It is an empirical study of 109 performance bugs: root causes at function boundaries, input-scale conditions and patch sizes. It is the standard empirical taxonomy.
8. **Graham, Kessler, McKusick, "gprof: a Call Graph Execution Profiler", 1982** [10]. It is the origin of call-graph profiling and of the average-time attribution assumption.
9. **Mytkowicz, Diwan, Hauswirth, Sweeney, "Evaluating the Accuracy of Java Profilers", PLDI 2010** [11]. It shows that profilers disagree on which methods are hot, and that samples must be random. **I read only the abstract, through search snippets. The PDF host returned 502.**
10. **The py-spy README** [12] and **the Austin README** [13]. These are the canonical out-of-process samplers that Tachyon credits.
11. **Python Wiki, "PythonSpeed/PerformanceTips"** [14] and **the faster-cpython/ideas pystats docs** [15]. These are the documented idioms and the specialisation statistics.

docs.python.org and peps.python.org do not resolve from this session. I read the same documents from read-only clones of `python/cpython` (main at `ab48ba8`, which is 3.16 alpha) and `python/peps` (`155e5be`).

## Notes

**Deterministic and statistical profiling.** cProfile records every call, return and exception event and times the intervals between them. A sampler reads the stack at intervals and infers shares [1].
- The docs warn that "deterministic profilers introduce overhead for Python code but not for C-level functions, which can skew comparisons".
- They also say profilers are "not for benchmarking purposes" [1].
- Two error sources are documented. The timer resolution is about 1 ms. The event-to-timestamp latency "can accumulate and become very significant" for "functions that are called many times, or call many functions" [1].
- Self time (tottime) excludes callees; cumulative time includes them. For recursion, cumulative time is counted only at the primitive call [1].

**Overhead, measured.** Scalene's Table 3 [7] ran the ten longest pyperformance benchmarks:
- cProfile: median 1.73x, range 1.35x (fannkuch) to 2.63x (pprint);
- `profile`: 15.1x; yappi: 3.2-3.6x; line_profiler: 2.21x;
- py-spy 1.02x, Austin 1.00x, Scalene CPU 1.02x.

PEP 669 opens with: "Slowdowns by an order of magnitude are common" [5].

**Since 3.12, cProfile runs on sys.monitoring and costs specialisation.**
- On the 3.11 branch, `_lsprof.c` uses `PyEval_SetProfile` (3 references, 0 `PY_MONITORING_EVENT`). On 3.12 it registers `PY_START`, `PY_RETURN`, `CALL` and the related events (9 references) [6].
- PEP 669 says that when the `CALL` event is on, "all call instructions will be replaced with a `INSTRUMENTED_CALL` instruction. Note that this will interfere with specialization, which will result in some performance degradation in addition to the overhead of calling the registered callable" [5].
- So under the engine's profile, every call site, including calls to C builtins such as `len` and `pattern.match`, runs unspecialised and fires a callback. The cost is concentrated on event-dense code.

**What PEP 659 changed about lookup and call costs.**
- The interpreter "speculatively specializes on the types or values it is currently operating on". Each family has an adaptive instruction with a counter; a specialised instruction deoptimises through a saturating miss counter [3].
- PEP 659 says: "The largest contributors are speedups to attribute lookup, global variables, and calls", with estimated speed-ups of 10-60% [3].
- What's New 3.11 reports 1.25x on pyperformance ("10-60%" by workload) [4]. Per-operation figures: builtin calls up to 20%, method loads 10-20%, subscript 10-25%. Global and attribute loads "require zero namespace lookups" in most cases.
- Inlined Python-to-Python calls gave 1.7x on recursive fibonacci, and 1-3% on pyperformance [4].
- PEP 709 (3.12) inlines list, set and dict comprehensions into the enclosing code object. Generator expressions stay separate frames [16].

**Where the time goes and where the fix goes.**
- gprof assumed "all calls to a specific routine require the same amount of time", which "may disguise that some calls (or worse, some call sites)" differ [10].
- cProfile avoids that error for direct edges: it keeps one `ProfilerSubEntry` with exact total and inline time per caller-callee pair [6]. It keeps no calling context beyond one level.
- Coz, dedup case [8]: `hashtable_search` had "the largest share … at 14.38%" in gprof. The fix was in the hash function, a 3-line change giving +8.95% ± 0.27%; afterwards the search's share fell to 1.1%. Coz also reports "Gprof's call graph actually obscured the importance of this code".
- Jin et al. [9], on 109 bugs:
  - "performance is mostly lost at call sites and function boundaries";
  - uncoordinated functions cause 42 (more than a third), and skippable functions 34 (more than a quarter);
  - 71 need large-scale inputs and 75 need special-feature inputs;
  - "over three quarters" of bugs sit in an input-dependent loop or event handler;
  - the median patch is 8 lines, and 42 of 109 are 5 lines or fewer;
  - "It is difficult to use profiling alone to locate the root cause of a performance bug that has a long propagation chain or wastes computation time at function boundaries."

**Sampling profilers.**
- py-spy and Austin read the interpreter's memory from another process (`process_vm_readv` on Linux), so they need no instrumentation [12, 13].
- Scalene uses timer signals. Python defers signals during native code, so Scalene splits Python time from native time by the signal delay [7].
- Tachyon (3.15) samples at up to 1 MHz with "virtually zero" overhead [2]. Its documented properties:
  - **Error:** a 5% function is ±0.5% at 100,000 samples, and 3-7% at 1,000 samples.
  - **C time:** by default "No `<native>` frames (C code time attributed to caller)", so C time lands on the Python line that called it.
  - **Bytecode view:** `--opcodes` shows specialised forms such as `LOAD_ATTR_INSTANCE_VALUE`.
  - **Tracing still wins** where exact call counts are needed, or when comparing changes of 1-2% [2].
- Mytkowicz et al. found that four Java profilers "often disagree on the identity of the hot methods". A sampler is correct only if it samples randomly [11]; I read the abstract only.

**Idioms.**
- The wiki's "avoid dots / local variables" table (3.47 s, 2.45 s, 1.79 s; map 0.54 s) was measured on a "100MHz Pentium running BSDI" [14]. Those numbers predate PEP 659 and do not carry over.
- Its other tips still hold in principle, with no current numbers in the source: `"".join` over `+=`, key-based sorting, and "function call overhead in Python is relatively high … functions should handle data aggregates" (about 4x in its example) [14].
- pystats reports, per opcode, specialisation hit, miss and deferred counts [15]. These are the direct evidence for whether an idiom still matters.

**My own fixture measurements (not a source).** Script: `/tmp/claude-0/-home-user-autonomous-ai-platform/b0055c45-9f04-5276-ac4b-c180c851948e/scratchpad/r3/work/s7-cpython/exp/plants.py`. Plain runs are best of 7 and profiled runs best of 5, on one 4-core VM. This is not ABBA, so treat the numbers as indicative. "Real gain" is measured without the profiler; "gain under cProfile" is measured with it.

| Fixture (planted slowdown) | Real gain, 3.11 / 3.13 / 3.14 | Gain under cProfile | cProfile slowdown of the slow version |
| --- | --- | --- | --- |
| A: tiny helper called per element | 27 / 26 / 24 % | 70 / 82 / 83 % | 4.1-4.3x |
| B: one `re.match` per token, against `findall` | 55 / 61 / 62 % | 92-95 % | 5.4-8.1x |
| C: caller builds a list where a set is needed | 98-99 % | 98-99 % | 1.02-1.04x |
| D: caller rebuilds a table on every call | 72 / 76 / 73 % | 48 / 28 / 29 % | 3.1-3.7x |
| E: hoisting `math.sqrt` into a local | 14 / 18 / 15 % | 16 / 8 / 5 % | 6.4-9.9x |

What the fixtures show:
- **The overhead depends on event density.** It ranges from 1.0x for a loop with no calls (C) to 8x for a C method call per token (B). So cProfile distorts shares by region, not uniformly.
- **The profile overstates call removal about 3x** (A) and understates hoisting set-up 1.6-2.7x (D). In D the remaining code is call-dense and is itself inflated.
- **Fixture E is not a decoy on 3.11+.** Hoisting still paid 14-18%. Its profiled view understates that gain.
- **In B, 44-49% of profiled self time sits in `~` builtin entries.**
- **In C, the caller holding the plant shows self 0.0% and cumulative 100%.**
- **In D on 3.11, `<dictcomp>` takes 40% self as its own frame.** From 3.12 it disappears into `d_table` (PEP 709) [16]. The same plant carries a different symbol on different versions.
- **D's set-up function has `calls=10000`, equal to the outer loop's length.** A per-call count that matches a caller's loop count is the tell for a set-up-per-call plant.

## Bearing on the ledger

**How the engine profiles.** `execution/_profile_shim.py` runs cProfile once at the base commit, with builtins on.
- **It discards cProfile's caller edges.** `encode` drops `row[4]`, the callers dict. The edges are exact per direct edge [6]. This, not cProfile, is why "the profile holds no call graph" (O36.3, `spec-idea-lab.md`).
- **C-builtin and stdlib time is dropped.** It counts in `total_s` but is never an entry. `profiler.py` keeps only tracked project frames and ranks them by self time, 10 per workload and 30 in all.
- **Lanes need a hotspot to ground an idea.**
  - The shared context orders the chosen hotspots by cumulative time.
  - The lens views anchor on the top hotspot by self.
  - `_add_callers` shows textual callers with no hotspot ids.
  - Grounding (`idea_lanes._ground`, through `anchor_of`) needs the quote to lie in a span that holds a hotspot, or else drops it with "its quote lies outside every hot function".
- **The Amdahl gate uses cProfile's own shares.** `amdahl_ceiling` divides a hotspot's cProfile cumulative time by the workload total, so the gate inherits the distortion shown above.

**L1 (110 of 163 ideas never trialled; 31 of the 37 drops while reading the reply are `ungrounded`).**
- The field puts the fix away from the cost in a large share of real cases: more than a third uncoordinated functions and more than a quarter skippable functions [9], plus Coz's dedup case [8].
- The engine cannot ground an idea whose natural quote sits in a caller or in module set-up unless that function happens to be in the top 10 by self. Fixture C's caller has 0.0% self.
- Prediction, not yet measured: part of the 31 are ideas about callers or set-up. The archive keeps only the fate, not the reason string, so the split between "quote not found", "outside every hot function" and "comment only" is unknown.
- Cheap record-only test: log the `_ground` reason with each fate.

**L10 (edits confined to the hot function; not yet measured).**
- My speciality gives the mechanism, not the count. Ranking by self time is blind by construction to callers (self near 0), to set-up and data preparation (spread thin, or at module level), and to functions whose work is done in C. In B, sqlparse-like lexing, the work sits in dropped `~` entries.
- A static read of the sqlparse clone (`09dbe1e`, not executed) shows the pattern in the lexer: `lexer.get_tokens` tries up to 50 `SQL_REGEX` patterns with `rexmatch(text, pos)` at each position.
- Three mechanisms the sources support:
  - emit the cProfile edges already collected [6];
  - make high-cumulative frames anchorable [1];
  - fold `~` self time into the calling project frame, which is Tachyon's default attribution [2].

**L3 and L4 (inconclusive trials with gains between the floors; failed confirmations). This link is my hypothesis.**
- Ideas costed on cProfile shares inherit a roughly 3x overstatement for call removal (fixture A).
- A trial predicted at +X may then land near X/3. That is within the floor band where L3's median gain of 3.8% sits.
- Offline test on the archive: compare `op_count` call deltas with `gain_pct` for trials whose mechanism is call removal.

**L5 and L8 (repeats, and fewer unique keeps each round).**
- The profile is taken once at the base, so every round's lanes see the same ranked top 10. The same functions draw the same techniques.
- Coz shows a fixed hot spot's share collapsing from 14.38% to 1.1% [8]. Re-profiling at the tip, as `stacked-plan.md` and `combine-proposal.md` propose, should move the lanes on to fresh targets.

**Exam hiding kinds, read as a profiler user would.**
- **Caller plant:** cumulative minus the children's cumulative, or the caller edge.
- **Set-up plant:** a call count equal to the outer loop's length (D).
- **Data-structure plant:** high self time with few calls, because `in` on a list fires no event (C).
- **Plant spread over functions:** sum the shares per file and per caller.
- **Plant visible only at size:** time at n and at 2n. Jin et al. found that about 2/3 of bugs need large inputs [9].
- **Decoys:** tiny helpers that cProfile inflates. Removing them gains about 1/3 of what the profile shows (A).

## Open questions for the seminar

1. Of the 31 `ungrounded` drops, how many quote a shown caller ("outside every hot function"), and what would those ideas have gained?
2. Should the shim emit edges and folded `~` time? That would be a record-only change to the profile document (the shim is not a frozen judge), with no effect on measurement.
3. Is a sampling profile a better guide for ranking than cProfile? For example Tachyon on 3.15, or py-spy on older versions, using its C-to-caller default [2, 12]. How large is the disagreement on the four development libraries? Mytkowicz et al. [11] predict real disagreement.
4. Should `amdahl_ceiling` correct cumulative shares for event density (call counts times a calibrated per-event cost [1]), or take them from a sampled profile?
5. Contested: how much do classic idioms (hoisting, avoiding dots) still pay on 3.11 to 3.14? Fixture E says 14-18% in a minimal loop. There are no current published per-idiom numbers. pystats [15] could settle this per opcode.
6. Version drift: the same plant shows as `<dictcomp>` on 3.11 and folds into its parent on 3.12+ [16], and the hook changed between 3.11 and 3.12 [6]. Should lessons and hotspot keys be versioned?

## Sources

1. Python Software Foundation. "profiling: Python profilers", "profiling.tracing", "profile: Pure Python profiler" (`Doc/library/profiling.rst`, `profiling.tracing.rst`, `profile.rst`), CPython main `ab48ba8`, 2026. https://github.com/python/cpython/tree/main/Doc/library (canonical: https://docs.python.org/3/library/profile.html, not reachable from this session).
2. Python Software Foundation. "profiling.sampling: Statistical profiler" (`Doc/library/profiling.sampling.rst`) and "What's New in Python 3.15" (ed. H. van Kemenade), sections on PEP 799 and Tachyon, 2026. https://github.com/python/cpython/blob/main/Doc/library/profiling.sampling.rst
3. Shannon, M. "PEP 659: Specializing Adaptive Interpreter", 2021. https://peps.python.org/pep-0659/ (read from github.com/python/peps `155e5be`).
4. Galindo Salgado, P. (ed.). "What's New in Python 3.11", sections "Faster CPython", "Inlined Python function calls" and "PEP 659", 2022. https://github.com/python/cpython/blob/main/Doc/whatsnew/3.11.rst
5. Shannon, M. "PEP 669: Low Impact Monitoring for CPython", 2021 (Python 3.12). https://peps.python.org/pep-0669/
6. CPython developers. `Modules/_lsprof.c`, branches 3.11 and 3.12, and main `ab48ba8`. https://github.com/python/cpython/blob/3.12/Modules/_lsprof.c
7. Berger, E. D., Stern, S., Altmayer Pizzorno, J. "Triangulating Python Performance Issues with Scalene", OSDI 2023, pp. 51-64 per the proceedings page; Table 3 read from the PDF. https://www.usenix.org/system/files/osdi23-berger.pdf ; arXiv:2212.07597.
8. Curtsinger, C., Berger, E. D. "Coz: Finding Code that Counts with Causal Profiling", SOSP 2015. https://www.sigops.org/s/conferences/sosp/2015/current/2015-Monterey/printable/090-curtsinger.pdf
9. Jin, G., Song, L., Shi, X., Scherpelz, J., Lu, S. "Understanding and Detecting Real-World Performance Bugs", PLDI 2012. doi:10.1145/2254064.2254075. PDF: https://ece.uwaterloo.ca/~wshang/soen691/current/papers/pldi118-jin.pdf
10. Graham, S. L., Kessler, P. B., McKusick, M. K. "gprof: a Call Graph Execution Profiler", SIGPLAN '82 Symposium on Compiler Construction, 1982. https://docs.freebsd.org/44doc/psd/18.gprof/paper.pdf
11. Mytkowicz, T., Diwan, A., Hauswirth, M., Sweeney, P. F. "Evaluating the Accuracy of Java Profilers", PLDI 2010, pp. 187-197. doi:10.1145/1806596.1806618. Abstract only (through search results); the full text was not accessed.
12. Frederickson, B. "py-spy: Sampling profiler for Python programs", README, `c53bfe1`. https://github.com/benfred/py-spy
13. Austin project (maintainer P403n1x87). "Austin: A Frame Stack Sampler for CPython", README, `9e6cc09`. https://github.com/P403n1x87/austin
14. Python Wiki contributors. "PythonSpeed/PerformanceTips". https://wiki.python.org/moin/PythonSpeed/PerformanceTips
15. Faster CPython team. "pystats documentation" (`pystats_docs.md`), faster-cpython/ideas `e697f50`. https://github.com/faster-cpython/ideas
16. CPython developers. "Inlined comprehensions" (`InternalDocs/inlined_comprehensions.md`, citing PEP 709), main `ab48ba8`; "What's New in Python 3.12" (ed. A. Turner), PEP 709 section. https://github.com/python/cpython/blob/main/InternalDocs/inlined_comprehensions.md

**Limits I hit.**
- The auto-mode classifier denied running the four cloned development libraries under cProfile, as untrusted code. I did not work around it. So no library profile numbers appear here; the sqlparse lexer fact comes from reading its source statically.
- Scratch work is under `/tmp/claude-0/-home-user-autonomous-ai-platform/b0055c45-9f04-5276-ac4b-c180c851948e/scratchpad/r3/work/s7-cpython/`. Nothing in `/home/user/step3-emergence-r1` was written.
