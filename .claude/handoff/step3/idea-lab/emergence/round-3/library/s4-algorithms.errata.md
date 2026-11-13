# s4-algorithms errata (full-text check, 2026-11-13)

**Checked against:** the filed notes `library/s4-algorithms.md`, which carry the Lead's redaction.
- Nothing below restores any redacted material.
- No commit was re-opened for this check. Claims about the commits still in [14] rest on my reading earlier in this session.

**Status at the first pass, before this check:**
- **Read in full:** [5], [6], [7], [8], [9], [11], [14], [17], plus the open parts of [2] (lectures) and [3] (booksite).
- **Summary or abstract only:** [10], [12], and [4] (metadata only).
- **Not accessed:** [1], [13] (landing page only), [15], [16], and the books behind [2] and [3].

## Sources

| # | citation (short) | status: full text / open substitute / unverified | file under sources/s4-algorithms/ or why none |
| --- | --- | --- | --- |
| 1 | Cormen et al., *Introduction to Algorithms* 4e, 2022 | open substitute | commercial book with no open full text; substitute is [5], `5-mit6046-lec05.pdf` |
| 2 | Skiena, *Algorithm Design Manual* 3e, 2020 | open substitute | book has no open full text; author's lectures `2-skiena-lec4.pdf`, `2-skiena-lec5.pdf`, `2-skiena-lec6.pdf` |
| 3 | Sedgewick and Wayne, *Algorithms* 4e, 2011 | open substitute | book has no open full text; authors' booksite `3-algs4-13stacks.html`, `3-algs4-14analysis.html` |
| 4 | Tarjan, "Amortized Computational Complexity", 1985 | unverified | Semantic Scholar reports CLOSED. The only copies found are course-site reposts of the publisher PDF, not downloaded (treated as mirrors). Secondary source filed: `4-substitute-wikipedia-amortized-analysis.txt` |
| 5 | MIT 6.046J S15 Lecture 5 notes | full text | `5-mit6046-lec05.pdf` |
| 6 | Python docs, time complexity of built-in types; psf/wiki e069e07 | full text | `6-python-time-complexity.html`, `6-psfwiki-timecomplexity-e069e07.txt`; also `6-substitute-python-bisect.html` (see corrections) |
| 7 | CPython source ab48ba8 | full text | `7-cpython-ab48ba8-excerpts.txt` (the seven files named in [7]) |
| 8 | Python docs: re, collections, Design FAQ | full text | `8-python-re.html`, `8-python-collections.html`, `8-python-design-faq.html` |
| 9 | Cox, regexp1, 2007 | full text | `9-cox-regexp1.html` |
| 10 | Davis, Coghlan, Servant, Lee, ESEC/FSE 2018 | full text | `10-davis-redos-fse18.pdf`, the author's own copy (davisjam.github.io). The ACM PDF returned 403 and was not retried |
| 11 | CommonMark Spec 0.31.2 | full text | `11-commonmark-0.31.2.html` |
| 12 | Ford, "Packrat Parsing", ICFP 2002 | full text | `12-ford-packrat.pdf` (arXiv cs/0603077) |
| 13 | Crosby and Wallach, USENIX Security 2003 | full text | `13-crosby-wallach.pdf` (USENIX open PDF) |
| 14 | Library git histories (commits still listed in the filed [14]) | full text | not copied: the git objects are in my read-only clones under `work/s4-algorithms/src/`. I did not re-dump commits, to avoid re-studying history next to the sealed set |
| 15 | Aho, Lam, Sethi, Ullman, *Compilers* 2e, 2006 | open substitute | commercial book with no open full text. Stanford CS143 notes failed TLS verification (not worked around); MIT 6.035 lectures 2, 3 and 3b have no longest-match passage. Secondary source filed: `15-substitute-wikipedia-maximal-munch.txt`, which cites Aho et al. p. 168 |
| 16 | Bentley, *Programming Pearls* 2e, 2000 | unverified | commercial book with no open full text; the notes attribute no claim to it |
| 17 | PEP 8 | full text | `17-pep8.html` |

## Corrections

- **[6] Core sources item 6.** Written: "the documented cost of list, dict, set, str and deque operations".
  - The current docs page has no deque section. It covers list, tuple, dict/frozendict, set/frozenset, str/bytes/bytearray, memoryview and range.
  - Deque costs come from the old wiki revision e069e07 ("collections.deque" table) and from [8].
- **[6] §4 list.** Written: "`x in l`, `l.index`, `l.remove`, `del l[0]` and `l.insert(0, x)` are all O(n) [6]".
  - [6] lists `x in l` O(n), delete item O(n − k) and insert O(n − k).
  - `l.index` and `l.remove` are not in [6] or in the wiki revision, so their O(n) is unverified from these sources.
- **[6] §3 table, `bisect.insort` row.** Written: "O(n) shift per insert [6]".
  - [6] gives only list insert O(n − k).
  - The insort statement is in the `bisect` docs: "the O(log n) search is dominated by the slow O(n) insertion step" (`6-substitute-python-bisect.html`). Cite that instead.
- **[6] §4 dict and set.** Written: "still iterates at the old size until it is reinserted into".
  - [6] note 7: "until a later insertion triggers a resize". Not every later insertion resizes.
- **[8] §4 re.** Written: "`^` matches at the real start of the string, not at `pos`".
  - The docs say `^` "matches at the real beginning of the string and at positions just after a newline, but not necessarily at the index where the search is to start".
  - So `^` can still match at `pos` when `pos` follows a newline in MULTILINE mode. The trap stands, but the rule is "not necessarily at pos".
- **[3] §1.** Written: "A ratio near 2^b gives the exponent b", attributed to [3].
  - The booksite §1.4 gives the tilde model g(N) ~ a·f(N) with f(N) = N^b log^c N, and the DoublingRatio program that "output[s] the ratios in running times from one size to the next".
  - The 2^b reading is my derivation from that model, not a sentence on the page.
- **[4] Core sources item 4.** Written: "This is the origin of the potential method".
  - Unverified. The only open text I read (Wikipedia, secondary) says the paper "first formally introduced" amortized analysis. Nothing open I read credits it with originating the potential method.
- **[4] §2.** Written: "An amortised bound is a worst-case bound on a *sequence* of operations [3][4][5]".
  - Confirmed by [3] ("a worst-case performance guarantee on a sequence of operations") and by [5].
  - [4] is unverified. Drop it from this citation.
- **[11] §5 Markdown.** Written: "`openers_bottom` is kept per delimiter type and length mod 3", and "This is the field's standard device against quadratic emphasis matching".
  - The spec indexes `openers_bottom` "to the length of the closing delimiter run (modulo 3) and to whether the closing delimiter can also be an opener", per delimiter type.
  - The spec says only that it "puts a lower bound on future searches". "Against quadratic matching" is my inference.
- **[12] §5 recursive descent.** Written: "backtracking recursive descent becomes linear when memoised (packrat)".
  - Confirmed: linear time, assuming constant-time table lookup.
  - Missing caveat: Ford calls space consumption "the main disadvantage of packrat parsing", since the memo table is linear in the input with a large constant.
  - "Matters less in tomli than in sqlparse's grouping passes" is my inference, not Ford's.
- **No source; a residue of the redaction (L8).** Written: "pathological or large inputs (8k to 200k characters)".
  - The 8k lower end came from a commit the Lead removed.
  - With only the filed commits, the range is about 50k to 200k characters (5d1363c, b29a5b6).
- **No source; a residue of the redaction (L1).** Written: "Nearly every upstream fix I read (16 commits across the four histories)".
  - 16 counts commits that were redacted. The filed [14] lists 13 commits.
- **Confirmed: [10].**
  - Abstract and §1: "thousands of super-linear regexes affecting over 10,000 modules". The wording should be "affecting", not "across".
  - The anti-patterns "appear to be necessary, but not sufficient".
  - Developers "favor revising" the regex.
  - The paper adds two figures: "over 4,000 unique SL regexes across npm and pypi", and "about 1% of all unique regexes".
- **Confirmed: [13].**
  - The paper "focuses on hash chaining", and says the attacks "will be at least as effective on open addressing hash tables". CPython's dict and set use open addressing [7], so the note's use of it stands.
- **Confirmed: [9].** Perl takes "over sixty seconds" on a 29-character string, against "twenty microseconds" for the Thompson NFA. Python is named among the backtracking implementations.
- **Confirmed: [5].**
  - Table doubling: total cost 2^0 + … + 2^⌈lg n⌉ = Θ(n), so Θ(1) amortised.
  - Halving at a quarter full keeps Θ(1).
  - "amortized cost of an operation = actual cost of this operation + ΔΦ".
- **Confirmed: [3].**
  - Tilde approximations and f(N) = N^b log^c N.
  - "Any sequence of N operations takes time proportional to N in the worst case" for resizing arrays.
  - Authorship (Sedgewick and Kevin Wayne) is confirmed on the booksite.
- **Confirmed: [2].**
  - The lecture 4 quote is verbatim ("There is an inherent tradeoff… no single implementation will achieve the best time bound for all operations").
  - Lecture 5 lists the dictionary operations and compares implementations. "List the operation mix first, then pick" is my paraphrase of that method.
- **Confirmed: [6], every other claim.**
  - Slices are O(j − i).
  - Note 1: amortised, "depending on the history of the container".
  - The note 7 quote is verbatim.
  - Note 10: quadratic concatenation "in the total length".
  - `rfind` is O(n × len(x)) worst case; forward search is linear (two-way).
  - `s - t` is O(len(s1)).
  - The current doc gives O(min(len(s1), len(s2))) for `difference_update`, against the wiki's O(len(t)).
  - Dict worst case O(n).
  - The page moved from the wiki in psf/wiki 492ff17 (2026-10-23).
- **Confirmed: [7].**
  - List growth formula and the comment's growth pattern.
  - gh-158592 does not shrink a list at or below `LIST_SMALL_ALLOCATED`, which is 32.
  - `USABLE_FRACTION` is two-thirds, `GROWTH_RATE` is `ma_used*3`, `PyDict_MINSIZE` is 8, `PERTURB_SHIFT` is 5 with `j = 5j + 1 + perturb`.
  - `LINEAR_PROBES` is 9 and `BLOCKLEN` is 64.
  - The in-place `+=` comment is verbatim.
  - `_MAXCACHE` 512 (LRU) and `_MAXCACHE2` 256 (FIFO).
  - The sre BRANCH literal and charset skip.
  - The 8x switch in `set_difference_update_internal`.
- **Confirmed: [8].**
  - The alternation quote is verbatim.
  - Possessive quantifiers and atomic groups were added in 3.11.
  - The master-regex tokenizer uses `lastgroup`.
  - Deque: "Indexed access is O(1) at both ends but slows to O(n) in the middle".
- **Confirmed: [17].** "Do not rely on CPython's efficient implementation of in-place string concatenation…".
- **Confirmed: [14], the remaining commits, from my earlier reading in this session.**
  - a3e19f1: a slice copy made matching quadratic in tokens.
  - 939b129: the group value is built from the child tokens instead of `str(self)`.
  - 2b04d7b: sorted blank-line positions cached in `state.env`, queried with `bisect_left`.
  - 0bfd8c3: quoted passages.
  - b29a5b6: about 10 s to about 20 ms on 200k spaces.
  - 5d1363c: about 8 s on 50,000 spaces.
  - tomli 1852743: "~10% performance boost".
  - ac7bc05: title.

## Claims still unverified

- [1] Core sources item 1: that CLRS covers asymptotic analysis, hashing, dynamic tables and "the three methods" of amortised analysis. The open substitute [5] teaches four methods: aggregate, accounting, charging and potential.
- [4] Tarjan as the origin of the potential method. The Wikipedia secondary source supports only "first formally introduced amortized analysis".
- [15] Longest match ("maximal munch") as the lexer rule. It is supported only by a secondary source (Wikipedia, citing Aho et al. p. 168). The primary text is not accessed.
- [6] O(n) for `l.index` and `l.remove`: not in the sources read.
- [16] Bentley: listed only, with no claim attributed.
- My own observations on mistune f7ec702 (`tuple(sorted(chars))` per call; the `None` sentinel conflated) are unmeasured. They are my reading, not a source's claim.

## Overview sources

| # | source (short) | kind: TOC / chapter summaries / syllabus / topic list / reading list | file under sources/s4-algorithms/overview/, or "refused: <code>" |
| --- | --- | --- | --- |
| 1 | Sedgewick and Wayne, *Algorithms* 4e booksite home | TOC | `1-algs4-home.html` |
| 2 | Skiena, algorist.com (author's site, 3e) | chapter summaries (book description: Techniques and Resources parts) | `2-algorist-home.html` |
| 3 | Springer page for *The Algorithm Design Manual* 3e | TOC (22 chapters) | `3-springer-adm3.html` |
| 4 | MIT Press page for CLRS 4e | TOC | refused: 403 |
| 5 | MIT 6.046J Spring 2015, lecture notes list | topic list | `5-mit6046-s15-lecture-notes.html` |
| 6 | MIT 6.006 Spring 2020, lecture notes list | topic list | `6-mit6006-s20-lecture-notes.html` |
| 7 | Princeton COS 226 Spring 2024 | syllabus (course description only, no topic list on that page) | `7-princeton-cos226-syllabus.html` |
| 8 | MIT 6.851 Advanced Data Structures, Spring 2012, lectures | topic list | `8-mit6851-s12-lectures.html` |

## Not yet covered

- **Priority queues and binary heaps** (overview #1 §2.4, #6 lecture 8). They bear on "keep sorted under inserts" plants (heapq versus repeated `sorted`/`insort`). Relevant to the exam.
- **Tries and symbol tables** (#1 §3.1, §5.2). sqlparse's `is_keyword` tries several keyword dicts in turn per Name token. Merging the lookups is a possible "structure, not loop" site. Relevant to L10 and the plants.
- **Substring search, KMP and Boyer-Moore** (#1 §5.3). This is the theory behind `str.find`'s two-way search and the linear scanners that replace regex rescans. Relevant to the tokeniser plants.
- **Regular expressions as NFA simulation** (#1 §5.4). Covered only through Cox [9]. It bears on when a regex can be made linear. Relevant.
- **Dynamic programming and memoisation** (#3 "Dynamic Programming", #6 lectures 15-18). Caches and fast paths are the exam's named trap class, and memo correctness conditions (pure functions, complete keys) decide them. Relevant to L1's idea classes.
- **Universal and perfect hashing, randomised algorithms** (#5 lecture 8, #3 "Hashing and Randomized Algorithms"). They bear on the hash-collision worst case of dict and set. Marginal.
- **Cache-oblivious algorithms and memory-hierarchy models** (#5 lectures 23-24, #8 sessions 7-9). Constant-factor gains in CPython are dominated by pointer chasing and allocation. This may bear on L3 and L8 once asymptotic wins are exhausted.
- **Combinatorial search and backtracking** (#3 "Combinatorial Search"). Choosing which keeps to combine is a subset search. Bears on L5 and L6 (the merge seat's ground).
- **Graph algorithms: conflict graphs, independent sets** (#1 §4, #3 "Graph Traversal"). Keeps that conflict textually form a graph, and the best held combine is a maximum-weight independent set. Bears on L5 and L6.
- **NP-completeness and approximation algorithms** (#5 lectures 16-17, #3 "NP-Completeness", "Dealing with Hard Problems"). Maximum-weight independent set is NP-hard in general, so the greedy combine is an approximation with known gaps. Bears on L6.
- **Persistent and retroactive data structures** (#8 sessions 1-2). An analogy for stacked-round tips (X2-DT) and for undoing one keep inside a combine. Probably not relevant beyond analogy.
- **Union-find, suffix arrays, B-trees, succinct structures, dynamic graphs** (#1 §1.5, §6.2-6.3; #8 sessions 17-21). Probably not relevant.
