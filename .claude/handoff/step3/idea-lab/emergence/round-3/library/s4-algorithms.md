# s4-algorithms: algorithms and data structures as they bear on performance work

> **Lead's redaction (2026-11-13).** Commit-level material that overlaps a sealed set (O53) was removed before filing: two rows of the §3 table, two worked examples in §4, two rows of the L10 table, and the matching commit ids in [14]. The unredacted notes are held in quarantine pending the owner's ruling.



Scratch work, read-only clones and my measurement scripts are under `/tmp/claude-0/-home-user-autonomous-ai-platform/b0055c45-9f04-5276-ac4b-c180c851948e/scratchpad/r3/work/s4-algorithms/`. The doubling probe script is at `/tmp/claude-0/-home-user-autonomous-ai-platform/b0055c45-9f04-5276-ac4b-c180c851948e/scratchpad/r3/work/s4-algorithms/bench/doubling.py`.

## Core sources (5-12, each: citation, what it covers, why it is standard)

1. **Cormen, Leiserson, Rivest, Stein, *Introduction to Algorithms*, 4th ed. [1].** It covers asymptotic analysis, hashing, dynamic tables and the three methods of amortised analysis. It is the standard graduate reference. *I could not access the text.* The method claims I attribute to it below were checked against [5], which teaches the same material.
2. **Skiena, *The Algorithm Design Manual*, 3rd ed. [2], with his public CSE 373 lectures 4-6 (read).** It covers choosing a dictionary implementation by its operation mix. It is standard because it is the practitioner's catalogue of structures and their trade-offs.
3. **Sedgewick and Wayne, *Algorithms*, 4th ed. [3], booksite §1.3-1.4 (read).** It covers tilde notation, the doubling-ratio experiment, and resizing arrays with amortised bounds. It is standard because it is the empirical method for finding an order of growth by measurement.
4. **Tarjan, "Amortized Computational Complexity", 1985 [4].** This is the origin of the potential method. The paper is closed access, so I confirmed only its metadata.
5. **MIT 6.046J (Spring 2015), Lecture 5 "Amortization" [5] (read).** It covers the aggregate, accounting, charging and potential methods, and table doubling and halving.
6. **Python docs, "Time complexity of operations on built-in types" [6].** This page replaced the TimeComplexity wiki page in October 2026. I read it, and the last wiki revision through psf/wiki git history. It is the documented cost of list, dict, set, str and deque operations.
7. **CPython source at `ab48ba8`, 2026-11-13 [7] (read).** It shows the real growth rules, probing, the `+=` fast path, the `re` cache and sre alternation.
8. **Python `re`, `collections` and Design FAQ docs [8], and PEP 8 [17] (read).**
9. **Cox, "Regular Expression Matching Can Be Simple And Fast", 2007 [9] (read),** and **Davis et al., ESEC/FSE 2018, on ReDoS [10] (abstract read).** They cover backtracking blow-up and how it is found and repaired in practice.
10. **CommonMark Spec 0.31.2, appendix "A parsing strategy" [11] (read).** It gives the two-phase block/inline parse and the delimiter-stack algorithm with `openers_bottom`.
11. **Ford, "Packrat Parsing", ICFP 2002 [12] (abstract read).** It shows that memoised backtracking recursive descent runs in linear time.
12. **The four development libraries' public git histories [14] (read).** These are the field's results applied to exactly our code.

## Notes (the methods and results, cited inline as [n])

**1. Cost models and measuring the order of growth.**
- Sedgewick defines the order of growth through tilde approximations, g(N) ~ a·f(N) with f(N) = N^b log^c N. To find it empirically, he doubles N and watches T(2N)/T(N) [3]. A ratio near 2^b gives the exponent b.
- This is the right tool for plants that are "visible only at realistic input sizes". A quadratic term hides in the absolute time at small N, but it shows in the ratio.
- My measurements (CPython 3.13.16 on this VM, min of 3; my numbers, not a source's):

| Pattern | T at n | T(2n)/T(n) | T(4n)/T(2n) |
| --- | --- | --- | --- |
| `x in list` dedupe (n = 2,000) | 9.95 ms | 3.90 | 4.14 |
| `x in set` dedupe (n = 2,000) | 0.12 ms | 1.78 | 1.98 |
| `list.pop(0)` drain (n = 20,000) | 33.3 ms | 4.16 | 4.04 |
| `deque.popleft` drain (n = 20,000) | 0.72 ms | 1.98 | 2.22 |
| regex `match(s[pos:])` tokeniser (10k chars) | 1.98 ms | 2.66 | 3.62 |
| regex `match(s, pos)` tokeniser (10k chars) | 1.43 ms | 2.02 | 1.97 |
| `obj.attr += str` (n = 10,000) | 10.95 ms | 3.92 | 4.03 |
| local `+=` (n = 10,000) | 0.40 ms | 1.98 | 2.00 |
| list + `join` (n = 10,000) | 0.24 ms | 2.00 | 1.96 |

- The slicing tokeniser is only 1.4x slower at 10k characters. Its doubling ratio already shows the quadratic term. A benchmark sized like that can rate a real asymptotic fix as a +30 % gain, or as noise.

**2. Amortised analysis.**
- An amortised bound is a worst-case bound on a *sequence* of operations [3][4][5].
- Table doubling: n inserts cost at most 2^0 + … + 2^⌈lg n⌉ = Θ(n), so each insert is Θ(1) amortised. If the table also halves at a quarter full, the amortised cost per insert or delete stays Θ(1) [5].
- With the potential method, amortised cost = actual cost + ΔΦ [5].
- Algs4: in a resizing-array stack or queue, any sequence of N operations takes time proportional to N in the worst case [3].
- Two consequences for us:
  - An "amortised O(1)" operation can still be O(n) on the call that resizes. That matters for latency judges, not throughput judges.
  - A structure's amortised cost depends on its *history* [6, note 1]. A plant can hide in the history, for example a dict that was filled and then emptied.

**3. Choosing a structure by its access pattern.**
- Skiena: "There is an inherent tradeoff between these operations… no single implementation will achieve the best time bound for all operations" [2, lecture 4]. The method is to list the operation mix first (search, insert, delete, min, successor), then pick the structure [2, lecture 5].
- A recipe for "data structure, not loop" plants:

| Access pattern | Wrong structure | Cost | Right structure |
| --- | --- | --- | --- |
| membership test | list or tuple | O(n) per test [6] | set or dict, O(1) average [6] |
| FIFO | `list.pop(0)` or `insert(0, x)` | O(n − k) [6] | deque, O(1) at both ends [8] |
| random index into a queue | deque | "slows to O(n) in the middle" [8] | list |
| keep sorted under inserts | `bisect.insort` on a list | O(n) shift per insert [6] | sort once, or heap |
| "next occurrence after pos" | `re.search` from pos, repeated | O(n) per query | precomputed sorted positions + bisect, O(log n) (mistune 2b04d7b [14]) |
| derived value of a growing tree | recompute from scratch | O(size) per update | maintain incrementally (sqlparse 939b129 [14]) |

**4. Hidden costs of CPython's built-ins [6][7].**
- **list.**
  - Growth is `new_allocated = (newsize + (newsize >> 3) + 6) & ~3`, about 12.5 % over-allocation. The source comment gives the pattern 0, 4, 8, 16, 24, 32, 40, 52, 64, 76 [7].
  - As of gh-158592 a small list is not shrunk [7].
  - `x in l`, `l.index`, `l.remove`, `del l[0]` and `l.insert(0, x)` are all O(n) [6].
  - A slice copies: O(j − i) [6]. sqlparse a3e19f1 removed `enumerate(self.tokens[start:end])` from a loop because that copy made `_token_matching` quadratic in the token count [14].
- **dict and set.**
  - The dict load limit is two-thirds (`USABLE_FRACTION`), growth is `used*3`, the minimum size is 8, and probing is `j = 5j + 1 + perturb` with `PERTURB_SHIFT` 5 [7].
  - Sets do 9 linear probes before a random probe (`LINEAR_PROBES`) [7].
  - The average case is O(1). The worst case, when every key collides, is O(n) [6]. This is the attack in Crosby and Wallach [13].
  - Iterating, copying and the set operations "scan the container's internal hash table, which is not shrunk when elements are removed" [6, note 7]. A dict that once held 1M keys and now holds 10 still iterates at the old size until it is reinserted into.
- **set algebra.** `s - t` is O(len(s)) [6]. The old wiki said `s.difference_update(t)` is O(len(t)) [6, wiki e069e07]. Current source switches to iterating an intersection when `t` is more than 8x larger than `s` [7], and the new doc says O(min) [6]. This is a documented case of a stale cost table.
- **str.**
  - Concatenation builds a new object, so "building a string by concatenating many pieces in a loop is quadratic" [6, note 10].
  - CPython's `BINARY_OP_INPLACE_ADD_UNICODE` extends the string in place only for a *local* that is stored back by the next STORE_FAST and holds no other reference. The source comment says it "attempts to avoid quadratic behavior when one neglects to use str.join()" [7].
  - So `out += s` on a local is linear (measured above), but `self.out += s` is quadratic.
  - PEP 8 says not to rely on this fast path [17].
  - This is a classic decoy and trap pair: the local `+=` *looks* slow and is not.
  - `rfind` is O(n·len(x)) worst case, while forward search is linear (two-way algorithm) [6].
- **deque.** Blocks of 64 slots (`BLOCKLEN`) [7], O(1) at both ends, O(n) in the middle [8].
- **re.**
  - The module caches compiled patterns: 512 entries LRU plus 256 FIFO [7]. A `re.compile` inside a loop over a few fixed patterns is a decoy. More than 512 distinct dynamic patterns would thrash the cache.
  - `pattern.match(s, pos)` avoids the slice copy, but it is "not completely equivalent to slicing": `^` matches at the real start of the string, not at `pos` [8]. A rewrite from `match(s[pos:])` to `match(s, pos)` is wrong for patterns anchored with `^`, which makes it a natural hidden-check trap.

**5. Parsing algorithms in the four libraries.**
- **Regex-driven tokenisers.**
  - Python's documented idiom combines the token rules into one master regex with named groups and dispatches on `lastgroup` [8].
  - Alternation is ordered: "once A matches, B will not be tested further, even if it would produce a longer overall match… the '|' operator is never greedy" [8]. This is first-match semantics, not the longest-match ("maximal munch") rule of compiler lexers [15, not accessed].
  - sqlparse tries its 50 `SQL_REGEX` rules one after another at each position. On a sample of 200 identical SELECT statements (16,600 tokens) I measured a mean of 22.6 regex calls per token. The most frequent winners were rule indexes 3, 46 and 45 (my measurement).
  - A combined alternation keeps the same first-match order, so it preserves semantics when each rule's flags match. Inside sre, a BRANCH already skips an alternative cheaply when it starts with a literal or charset that fails on the current character [7]. The gain is therefore fewer Python-level calls. It is not established and needs measuring.
  - mistune already compiles its rules as one named-group alternation and memoises the compiled scanner in a dict keyed by `"|".join(rules)` (`core.py: compile_sc`) [14].
  - Reading upstream HEAD f7ec702, I saw that `_get_fast_trigger_re` recomputes `tuple(sorted(chars))` on every inline-loop call. I also saw that `_get_fast_trigger_chars` uses `None` both for "not computed" and for "no fast path", so the negative result is never cached. Both are my reading only and are not measured.
- **Backtracking regex.**
  - Backtracking engines (Perl, PCRE, Python) take time exponential in the worst case. Cox: matching `a?ⁿaⁿ` against a 29-character string takes Perl "over sixty seconds", against "twenty microseconds" for a Thompson NFA [9].
  - Davis et al. found thousands of super-linear regexes across more than 10,000 JavaScript and Python modules. The anti-pattern heuristics "appear to be necessary, but not sufficient", and developers prefer revising the regex [10].
  - Python-Markdown's own fixes show the commonest shape: two adjacent quantifiers that match the same run, `[^\n]*` followed by `[ ]*`. That gives n+1 ways to split a run, so O(n²). Worked numbers from those commits [14]:
    - b29a5b6 (attr_list): `text\n{a` followed by 200k spaces went from about 10 s to about 20 ms.
    - 5d1363c: `'[id]:' + ' ' * 50000` took about 8 s.
  - The repair is to remove the ambiguity, or to use the atomic groups and possessive quantifiers added in Python 3.11 [8].
- **Recursive descent.**
  - tomli scans a `str` with an integer `pos`. It tests character classes against `frozenset` constants, skips with `str.index` (ac7bc05 "Improve skip_until performance"), and builds strings with local `+=` and slices [14].
  - Its history records constant-factor wins from data access, not from asymptotics. Example: 1852743, "Move `src` and `pos` out of `State` for ~10% performance boost" [14].
  - Ford shows that backtracking recursive descent becomes linear when memoised (packrat) [12]. tomli does not backtrack much, so this matters less there than in sqlparse's grouping passes.
- **Markdown block and inline parsing.**
  - CommonMark parses in two phases. Blocks are built line by line over the open-block chain. Inlines are parsed later with a doubly linked delimiter stack. `openers_bottom` is kept per delimiter type and length mod 3 and "puts a lower bound on future searches" [11]. This is the field's standard device against quadratic emphasis matching.
  - Python-Markdown runs each inline pattern over the text in priority order and splices placeholders into the string. Each splice rebuilds `data[:start] + placeholder + data[end:]`, which is O(len) per match (treeprocessors.py) [14].
  - 0bfd8c3 records the block-level version of the same mistake. A processor that records one definition per pass and "return[s] the rest of the block" makes "every earlier block processor rescan… the shrinking block once per definition" [14].

## Bearing on the ledger (per row you touch: L#, what your field says, numbers)

**L1 (110 of 163 ideas never become trials; 24 `s3:review_duplicate_of`, 9 `s4a:duplicate`, 31 `read:ungrounded`).**
- *Duplicates.* My field supplies a small, closed vocabulary of asymptotic mechanisms: the table in §3 plus "remove regex ambiguity" and "avoid slice copy". Nearly every upstream fix I read (16 commits across the four histories) falls into one of about nine classes.
- A dedupe key of (file, function, mechanism class) is a structural key, so it does not depend on the reviewer's judgement. The 24 + 9 duplicate drops suggest the engine already sees the collisions but resolves them late.
- *Ungrounded.* An asymptotic claim can be grounded by measurement, with no API call:
  - run the hot path at n, 2n and 4n on scaled copies of the benchmark input, as a triage probe and never as a judge;
  - read the exponent b [3].
- If b ≈ 1 everywhere, "data-structure" ideas have small ceilings. If b ≈ 2 in one call chain, that chain is where the large gain is.
- No source measures what the lost ideas would have gained, so the floor for L1 cannot come from my field.

**L8 (unique keeps per run fall from 1.75 to 0.83 to 0.42 in X2-D; 4-6 repeats per round 2).** The field separates two components:
- **Expected decay (part of a floor).**
  - A given library has finitely many super-linear terms that are visible at the benchmark's input size. Once a round removes them, only constant-factor gains remain.
  - Constant-factor gains are smaller, so more of them fall under the noise floor (L3: 47 trials had a gain above the baseline floor and below their own, median 3.8 %).
  - There is also a benchmark-size effect. Most of the upstream fixes in [14] were motivated by pathological or large inputs (8k to 200k characters). On a fixed, modest benchmark, those terms may be worth a few per cent, as the 1.4x tokeniser above shows, or nothing at all.
  - Since the benchmarks are fixed, this is a true floor on what later rounds can find.
- **Avoidable loss: repeats.**
  - zero-credit §2 shows the same mechanism re-found at the same site: the mistune renderer-method cache, and tomli's single-part key fast path in three versions.
  - That is a lookup-structure failure: the engine keeps earlier keeps as titles in text, not as an index keyed by site and mechanism.
  - The field's answer is the same structural key as for L1. Removing repeats alone lifts X2-D round 3 from 0.42 to 0.67 (zero-credit §2), so repeats are at least that much of the gap.

**L10 (edits confined to the hot function; not yet measured).**
- Algorithms predicts this loss strongly. The cost of a wrong structure is paid where it is *used*: a scan, `re.search`, `__str__`. The profiler charges self time there, often to a C builtin the engine cannot edit. The fix sits where the structure is *chosen* or the loop's contract is set.
- Cases from [14], each with its fix site:

| Commit | Where the cost shows | Where the fix is |
| --- | --- | --- |
| mistune 2b04d7b | `BLANK_LINE.search` | a new helper with a sorted-positions cache in `state.env` |
| Python-Markdown 0bfd8c3 | other processors' rescans | a processor's return contract |
| sqlparse 939b129 | `str(self)` recursion | `TokenList.__init__` and `group_tokens` |

- For the exam's "data structure, not loop" plants, the practical rule is to trace the hot callee's *input* back to where it is built: the constructor, set-up, data preparation, or the caller's loop contract.
- The expert-practice seat should count the share. My sample is qualitative.

## Open questions for the seminar

1. **Size coverage.** Does each development benchmark's input size make its library's known super-linear terms visible at all? A doubling probe on scaled inputs, used for triage only, would tell us whether L8's decay is a property of the code or of the benchmark size.
2. **A mechanism-class key.** Should the engine record a mechanism class with every idea and keep, so that L1's duplicates and L5's and L8's repeats are caught by lookup rather than by review? How many of the 21 same-technique conflicts would one structural key have caught?
3. **Equivalence traps.** Which structure swaps are only nearly equivalent?
   - list to set loses order and duplicates, and merges `1 == 1.0 == True`;
   - `match(s[pos:])` to `match(s, pos)` changes `^`;
   - list to deque makes random indexing O(n);
   - a combined regex is first-match, not longest-match.

   These are where a "fast but wrong on a rare input" shortcut will sit.
4. **Contested.** Does a combined alternation beat sequential `match` calls in CPython, given sre's literal/charset branch skip [7]? No source gives a number. It needs measuring per library.
5. **Stale tables.** The old wiki's set `difference_update` cost is out of date against current source. How much of the engine's prompt-side cost knowledge comes from tables like it?

## Sources (numbered list, full citations with URL or ISBN)

1. T. H. Cormen, C. E. Leiserson, R. L. Rivest, C. Stein. *Introduction to Algorithms*, 4th ed. MIT Press, 2022. ISBN 978-0-262-04630-5 (confirmed through Open Library; text not accessed).
2. S. S. Skiena. *The Algorithm Design Manual*, 3rd ed. Springer, 2020. ISBN 978-3-030-54255-9 (book not accessed). S. Skiena, CSE 373 lectures 4 "Elementary Data Structures", 5 "Dictionaries" and 6 "Hashing", https://www3.cs.stonybrook.edu/~skiena/373/newlectures/ (read).
3. R. Sedgewick, K. Wayne. *Algorithms*, 4th ed. Addison-Wesley, 2011. ISBN 978-0-321-57351-3. Booksite §1.3 https://algs4.cs.princeton.edu/13stacks/ and §1.4 https://algs4.cs.princeton.edu/14analysis/ (read).
4. R. E. Tarjan. "Amortized Computational Complexity." *SIAM J. Algebraic Discrete Methods* 6(2):306-318, 1985. doi:10.1137/0606031 (closed access; metadata only).
5. MIT OpenCourseWare, 6.046J *Design and Analysis of Algorithms*, Spring 2015, Lecture 5 "Amortization" notes. https://ocw.mit.edu/courses/6-046j-design-and-analysis-of-algorithms-spring-2015/resources/lecture-5-notes/ (read).
6. Python Software Foundation. "Time complexity of operations on built-in types", Python 3.15.2 documentation, https://docs.python.org/3/builtins/time-complexity.html (read 2026-11-13). Predecessor: the "TimeComplexity" wiki page, psf/wiki commit e069e07 (2026-02-25), `python/language/TimeComplexity.md`, https://github.com/psf/wiki (read).
7. CPython source, commit ab48ba8 (2026-11-13), https://github.com/python/cpython: `Objects/listobject.c` (`list_resize`), `Objects/dictobject.c`, `Objects/setobject.c`, `Modules/_collectionsmodule.c`, `Python/bytecodes.c` (`_BINARY_OP_INPLACE_ADD_UNICODE`), `Lib/re/__init__.py` (`_MAXCACHE`), `Modules/_sre/sre_lib.h` (`SRE_OP_BRANCH`) (read).
8. Python docs: `re` (alternation, `pos`, "Writing a tokenizer", possessive quantifiers and atomic groups added in 3.11), https://docs.python.org/3/library/re.html; `collections.deque`, https://docs.python.org/3/library/collections.html; Design FAQ, https://docs.python.org/3/faq/design.html (read).
9. R. Cox. "Regular Expression Matching Can Be Simple And Fast (but is slow in Java, Perl, PHP, Python, Ruby, ...)", 2007. https://swtch.com/~rsc/regexp/regexp1.html (read).
10. J. C. Davis, C. A. Coghlan, F. Servant, D. Lee. "The impact of regular expression denial of service (ReDoS) in practice: an empirical study at the ecosystem scale." ESEC/FSE 2018, pp. 246-256. doi:10.1145/3236024.3236027 (abstract read).
11. CommonMark Spec, version 0.31.2, Appendix "A parsing strategy". https://spec.commonmark.org/0.31.2/ (read).
12. B. Ford. "Packrat Parsing: Simple, Powerful, Lazy, Linear Time." ICFP 2002; arXiv:cs/0603077. https://arxiv.org/abs/cs/0603077 (abstract read).
13. S. A. Crosby, D. S. Wallach. "Denial of Service via Algorithmic Complexity Attacks." 12th USENIX Security Symposium, 2003. https://www.usenix.org/conference/12th-usenix-security-symposium/denial-service-algorithmic-complexity-attacks (landing page only; paper not read).
14. Public git histories, cloned read-only:
    - sqlparse, https://github.com/andialbrecht/sqlparse at 09dbe1e: a3e19f1, 939b129, be3b7a6;
    - tomli, https://github.com/hukkin/tomli at 43a86ad: ac7bc05, 1852743, 716b682;
    - mistune, https://github.com/lepture/mistune at f7ec702: 2b04d7b, 96d0f57;
    - Python-Markdown, https://github.com/Python-Markdown/markdown at a4d4428: 0bfd8c3, b29a5b6, 5d1363c, 86d1e46, a4d4428.
15. A. V. Aho, M. S. Lam, R. Sethi, J. D. Ullman. *Compilers: Principles, Techniques, and Tools*, 2nd ed. Addison-Wesley, 2006. ISBN 978-0-321-48681-3 (not accessed).
16. J. Bentley. *Programming Pearls*, 2nd ed. Addison-Wesley, 2000. ISBN 978-0-201-65788-3 (not accessed; listed as a standard text only).
17. G. van Rossum, B. Warsaw, A. Coghlan. PEP 8, "Style Guide for Python Code", Programming Recommendations. https://peps.python.org/pep-0008/ (read).
