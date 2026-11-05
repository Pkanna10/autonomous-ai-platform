# X1 owner-read sample: the reader's marks against the key

Reader: a separate session that saw only owner-sample.md (no key, report or repository); an Opus-family model, the same family as the leap lane. Marks recorded in owner-sample-marks.json; this join is the Lead's, against owner-sample-key.json and the slice and pool rows (by repo, configuration, label and position). Novelty was itemised only for insightful (S13, S20); the other 22 are obvious (12) or considered (10), not itemised.

| sample | mark | size | library | source (configuration, lane, model) | slice | pool top 3 | title |
| --- | --- | --- | --- | --- | --- | --- | --- |
| S01 | skip | micro | mistune | X1-1 far on fable-5 | not a slice library | - | Join token renders from a list comprehension instead of a generator in BaseRenderer.render_tokens |
| S02 | maybe | moderate | pyparsing | X1-1 eliminate on haiku-5-5 | eligible, picked (rank 1), keep +3.5 % (floor 3.5 %) | opus-5-5, opus-5 (unvalidated) | Skip infix operator attempts whose first character cannot match, in _InfixNotation.parseImpl |
| S03 | maybe | moderate | mistune | X1-1 leap on opus-5-5 | not a slice library | not pooled (S1 or leap) | Evaluate nested-link check on demand over openers inside the label, not via a whole-source range index |
| S04 | would try | moderate | sqlparse | X1-0 name_the_problem on sonnet-5-5 | not eligible | - | Statement splitter\: precomputed keyword-type fast reject and skip Token double construction work |
| S05 | maybe | large | mistune | X1-1 name_the_problem on sonnet-5 | not a slice library | opus-5-5 | Replace backward opener scan in _process_emphasis_delimiters with per-key opener stacks |
| S06 | skip | micro | pyparsing | X1-2 eliminate (lane-8) on sonnet-5-5 | eligible, picked (rank 3), inconclusive +1.2 % (floor 2.5 %) | - | Avoid redundant as_list() calls on ParseResults in infix operator token extraction |
| S07 | would try | moderate | mistune | X1-2 name_the_problem (lane-9) on sonnet-5-5 | not a slice library | - | Fast-path _parse_link_href with a regex for plain href runs |
| S08 | maybe | large | idna | X1-1 far on sonnet-5 | not a slice library | - | Replace uts46_remap's per-character bisect with a dense status array indexed by codepoint |
| S09 | would try | moderate | tomli | X1-2 obvious on sonnet-5-5 | not eligible | not pooled (S1 or leap) | Replace skip_chars per-character loop with compiled regex match for whitespace skipping |
| S10 | maybe | micro | tomli | X1-1 name_the_problem on fable-5-1 | eligible, not picked | - | Newline fast path in the loads statement loop after a key/value or table rule |
| S11 | skip | micro | pyparsing | X1-0 eliminate on sonnet-5-5 | eligible, picked (rank 1), inconclusive +0.5 % (floor 3.1 %) | opus-5-5 | Avoid redundant second parse of base_expr lookahead and as_list conversions in infix operator handling |
| S12 | would try | moderate | sqlparse | X1-1 name_the_problem on haiku-5-5 | not eligible | - | Flatten TokenList via an explicit stack instead of nested recursive generators in sql.py |
| S13 | would try | large | more_itertools | X1-1 resolve_tradeoff on fable-5-1 | not a slice library | opus-5-5, opus-5 (unvalidated) | Block-based (van Herk) sliding min/max via C-level accumulate/map instead of per-item deque loop |
| S14 | maybe | micro | sqlparse | X1-3 eliminate on sonnet-5-5 | eligible, not picked | - | Memoise keyword lookup results in lexer per uppercase value |
| S15 | skip | micro | markdown | X1-1 far on sonnet-5-5 | not a slice library | - | Cache lowercased tag names to avoid repeated str.lower in ancestors building and serializer |
| S16 | maybe | micro | sqlparse | X1-3 resolve_tradeoff on sonnet-5-5 | not eligible | opus-5-5 | Hoist per-token whitespace and group checks out of _group's loop via a precomputed match gate |
| S17 | skip | micro | markdown | X1-0 far on sonnet-5-5 | not a slice library | opus-5-5, opus-5 (unvalidated) | Cache sorted pattern list in Registry so __getitem__ skips _sort and isinstance checks on int keys |
| S18 | skip | micro | more_itertools | X1-0 assume_less on sonnet-5-5 | not a slice library | - | bucket._get_values\: bind cache deque and key lookup once per generator, avoid repeated dict lookup |
| S19 | skip | micro | markdown | X1-3 assume_less on sonnet-5-5 | not a slice library | - | Skip ancestor-exclude scan in __applyPattern for patterns with no excludes |
| S20 | would try | large | sqlparse | X1-1 resolve_tradeoff on fable-5 | eligible, not picked | opus-5 (unvalidated) | Compute TokenList.value lazily to avoid O(n²) string joins during grouping |
| S21 | maybe | large | more_itertools | X1-2 leap (leap-2) on opus-5-5 | not a slice library | not pooled (S1 or leap) | Rewrite _windowed_running_mean as a C-level pipeline\: interleave value and negated lagged value, accumulate with add |
| S22 | skip | micro | idna | X1-0 recombine on sonnet-5-5 | not a slice library | - | Replace bisect-based uts46 lookup for BMP with a lazily built per-codepoint dict cache |
| S23 | would try | moderate | more_itertools | X1-1 obvious on sonnet-5-5 | not a slice library | not pooled (S1 or leap) | Fast path for non-iterable ints in collapse using a type check |
| S24 | skip | micro | more_itertools | X1-1 recombine on fable-5 | not a slice library | opus-5-5 | Phase-split _running_median_windowed\: fill phase, then fixed-size steady loop with precomputed parity and ring buffer |

## Per mark

Insightful (2): S13 X1-1 resolve_tradeoff on fable-5-1 (more_itertools); S20 X1-1 resolve_tradeoff on fable-5 (sqlparse). Both are X1-1 Fable lens lanes (resolve_tradeoff).

Skip (9): S01 X1-1 far on fable-5 (mistune); S06 X1-2 eliminate (lane-8) on sonnet-5-5 (pyparsing); S11 X1-0 eliminate on sonnet-5-5 (pyparsing); S15 X1-1 far on sonnet-5-5 (markdown); S17 X1-0 far on sonnet-5-5 (markdown); S18 X1-0 assume_less on sonnet-5-5 (more_itertools); S19 X1-3 assume_less on sonnet-5-5 (markdown); S22 X1-0 recombine on sonnet-5-5 (idna); S24 X1-1 recombine on fable-5 (more_itertools).

By configuration: X1-0 4, X1-1 3, X1-2 1, X1-3 1 of the skips; by model: fable-5 2, sonnet-5-5 7.

## Would try against the slice's keeps

No overlap: none of the 7 would-try ideas was trialled. S07 (mistune) and S13 and S23 (more_itertools) are outside the slice's four libraries. S04, S09 and S12 were not eligible: the slice picks only returned efficiency ideas new to today's generator by the auditor's links. S20 was eligible (sqlparse X1-1, 6 eligible) but the marker did not rank it in the top 3. The one sampled idea the slice kept, S02 (pyparsing X1-1 eliminate on Haiku 5.5, +3.5 % on a 3.5 % floor), was marked maybe. The two sampled skips that were trialled, S06 and S11, were inconclusive (+1.2 % and +0.5 %), as the reader predicted.

Pool against the reader: both insightful ideas reached a pooled top 3 (S13 for both rankers, S20 for Opus 5 only); so did three skips (S17 for both rankers, S11 and S24 for Opus 5.5).
