# X1 ideas: sortedcontainers, X1-3

Floor 2.0%; ceilings predicted from E1's profile.

These rows are the raw list behind unique mechanisms and the share new to today's generator (upper bound, the dedupe under-merges (O39)).

| # | title | mechanism | target lines | ceiling | audit | duplicate of | trial | gain / floor | op count | lane | model | returned |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Inline _expand fast path into SortedList.add to avoid a method call per insert | remove_work | sortedcontainers/sortedlist.py\:279-283 | 26.4% | infeasible | Inline _expand fast path into SortedList.add (X1-0) | inconclusive | 1.6% / 13.5% | 5836421 → 5543790 calls (-5.0%) | obvious | claude-sonnet-5-5 | True |
| 2 | Inline _expand fast path into SortedKeyList.add | remove_work | sortedcontainers/sortedlist.py\:1810-1813 | 21.6% | infeasible | Inline _expand fast path into SortedKeyList.add (X1-0) | inconclusive | 0.2% / 5.1% | 5836421 → 5686549 calls (-2.6%) | obvious | claude-sonnet-5-5 | True |
| 3 | SortedDict.__setitem__\: single dict insertion path avoiding double hash lookup | specialised_fast_path | sortedcontainers/sorteddict.py\:298-300 | - | infeasible | SortedDict.__setitem__\: skip redundant membership overhead (X1-0) | inconclusive | -0.3% / 5.4% | 5836421 → 5836421 calls (+0.0%) | obvious | claude-sonnet-5-5 | True |
| 4 | SortedList.add\: skip the per-insert len(_maxes) call by testing the bisect result against a cached length | specialised_fast_path | sortedcontainers/sortedlist.py\:272-275 | 26.4% | feasible | - | - | - | - | eliminate | claude-sonnet-5-5 | True |
| 5 | Skip _expand call in SortedList.add unless the sublist reaches double the load | remove_work | sortedcontainers/sortedlist.py\:279-283 | 26.4% | - | - | - | - | - | assume_less | claude-sonnet-5-5 | False |
| 6 | Skip bisect_right when the new value is at or beyond the last max in SortedList.add | specialised_fast_path | sortedcontainers/sortedlist.py\:272-276 | 26.4% | - | - | - | - | - | name_the_problem | claude-sonnet-5-5 | False |
| 7 | Defer positional-index upkeep in _expand\: skip per-add tree increments, rebuild lazily | precompute_or_cache | - | - | - | - | - | - | - | recombine | claude-sonnet-5-5 | False |
| 8 | SortedKeyList.add\: fuse key bisect into maxes path and skip _keys lookups via local sublist refs | specialised_fast_path | sortedcontainers/sortedlist.py\:1809-1811 | 21.6% | feasible | - | - | - | - | recombine | claude-sonnet-5-5 | True |
| 9 | Skip index maintenance walk in _expand by lazily invalidating the positional index | precompute_or_cache | sortedcontainers/sortedlist.py\:315-320 | 8.2% | unknown | - | - | - | - | resolve_tradeoff | claude-sonnet-5-5 | False |
| 10 | Replace per-add index tree arithmetic walk with memoised ancestor-path tuples (leaf node -&gt; root) in _expand/_delete | precompute_or_cache | sortedcontainers/sortedlist.py\:315-320 | 8.2% | unknown | - | - | - | - | leap | claude-opus-5-5 | True |
| 11 | Raise SortedList default load factor so the positional tree is shallower and index rebuilds rarer | representation | sortedcontainers/sortedlist.py\:302-307 | 8.2% | infeasible | Raise DEFAULT_LOAD_FACTOR so sublists are fewer\: shallower index tree, fewer splits and index rebuilds (X1-1) | - | - | - | leap | claude-opus-5-5 | False |

## Proposals (rule-relaxing, never scored or trialled)

| title | relaxes | lane | model | returned | rationale |
| --- | --- | --- | --- | --- | --- |
