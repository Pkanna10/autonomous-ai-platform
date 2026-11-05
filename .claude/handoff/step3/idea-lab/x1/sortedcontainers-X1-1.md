# X1 ideas: sortedcontainers, X1-1

Floor 2.0%; ceilings predicted from E1's profile.

These rows are the raw list behind unique mechanisms and the share new to today's generator (upper bound, the dedupe under-merges (O39)).

| # | title | mechanism | target lines | ceiling | audit | duplicate of | trial | gain / floor | op count | lane | model | returned |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Inline the non-split index update from _expand into SortedList.add | remove_work | sortedcontainers/sortedlist.py\:279-284 | 26.4% | infeasible | Inline _expand fast path into SortedList.add (X1-0) | inconclusive | 2.6% / 9.9% | 5836421 → 5543790 calls (-5.0%) | obvious | claude-sonnet-5-5 | True |
| 2 | Inline the non-split path of _expand into SortedKeyList.add | remove_work | sortedcontainers/sortedlist.py\:1811-1815 | 21.6% | infeasible | Inline _expand fast path into SortedKeyList.add (X1-0) | inconclusive | -0.6% / 9.1% | 5836421 → 5686549 calls (-2.6%) | obvious | claude-sonnet-5-5 | True |
| 3 | SortedDict.__setitem__\: single dict insert via len check instead of the membership test | remove_work | sortedcontainers/sorteddict.py\:298-300 | - | unknown | - | inconclusive | 0.8% / 6.6% | 5836421 → 5836421 calls (+0.0%) | obvious | claude-sonnet-5-5 | True |
| 4 | SortedKeyList.discard\: fast-path first-candidate check, defer duplicate-scan setup | remove_work | sortedcontainers/sortedlist.py\:1933-1936 | - | infeasible | SortedKeyList.discard\: drop per-step re-lookups and skip scan loop for exact first match (X1-0) | - | - | - | eliminate | claude-fable-5 | False |
| 5 | Fuse index decrement into the _pos descent for SortedList.pop by index | loop_or_control_flow | sortedcontainers/sortedlist.py\:684-688 | 3.0% | unknown | - | - | - | - | eliminate | claude-fable-5 | True |
| 6 | Raise the default load factor to shrink the index tree and per-op Python loops | data_structure | sortedcontainers/sortedlist.py\:302-302 | 8.2% | - | - | - | - | - | eliminate | claude-fable-5 | False |
| 7 | Skip redundant _maxes writes in SortedList._delete and SortedKeyList._delete when the deleted item was not last | remove_work | sortedcontainers/sortedlist.py\:490-491 | 4.2% | - | - | - | - | - | eliminate | claude-fable-5 | False |
| 8 | Cache leaf-to-root ancestor paths so _expand's index increment is a flat loop over a precomputed tuple | precompute_or_cache | sortedcontainers/sortedlist.py\:316-319 | 8.2% | - | - | - | - | - | assume_less | claude-fable-5-1 | False |
| 9 | Cache leaf-to-root ancestor paths for the index decrement walk in SortedList/SortedKeyList _delete | precompute_or_cache | sortedcontainers/sortedlist.py\:494-497 | 4.2% | - | - | - | - | - | assume_less | claude-fable-5-1 | False |
| 10 | Skip the index traversal in _delete when index is empty via cheaper fast path ordering | remove_work | sortedcontainers/sortedlist.py\:483-488 | 4.2% | - | - | - | - | - | name_the_problem | claude-sonnet-5-5 | False |
| 11 | SortedKeyList.discard\: skip the duplicate-key scan setup via direct first-probe equality | remove_work | sortedcontainers/sortedlist.py\:1933-1940 | - | - | - | - | - | - | name_the_problem | claude-sonnet-5-5 | False |
| 12 | Hoist per-bucket key/value list lookups out of the scan loop in SortedKeyList.discard | algorithm | sortedcontainers/sortedlist.py\:1933-1939 | - | feasible | - | - | - | - | recombine | claude-sonnet-5 | True |
| 13 | Patch the position index incrementally on sublist split instead of fully invalidating it in _expand | data_structure | sortedcontainers/sortedlist.py\:310-313 | 8.2% | unknown | - | - | - | - | recombine | claude-sonnet-5 | False |
| 14 | Defer positional index upkeep on SortedList.add by invalidating the index instead of walking it per insert | lazy_or_streaming | sortedcontainers/sortedlist.py\:315-320 | 8.2% | - | - | - | - | - | resolve_tradeoff | claude-haiku-5-5 | False |
| 15 | Defer index decrement on SortedKeyList._delete by clearing the index instead of walking ancestors | lazy_or_streaming | sortedcontainers/sortedlist.py\:493-498 | 4.2% | unknown | - | - | - | - | resolve_tradeoff | claude-haiku-5-5 | True |
| 16 | Precomputed leaf-to-root node paths for index increments/decrements in _expand and both _delete methods | precompute_or_cache | sortedcontainers/sortedlist.py\:315-320 | 8.2% | infeasible | Replace per-add index tree arithmetic walk with memoised ancestor-path tuples (leaf node -&gt; root) in _expand/_delete (X1-3) | - | - | - | far | claude-opus-5-5 | False |
| 17 | Raise DEFAULT_LOAD_FACTOR so sublists are fewer\: shallower index tree, fewer splits and index rebuilds | representation | sortedcontainers/sortedlist.py\:302-307 | 8.2% | unknown | - | - | - | - | far | claude-opus-5-5 | False |
| 18 | Replace the positional tree index with a lazily repaired flat prefix-sum array plus a dirty watermark | data_structure | sortedcontainers/sortedlist.py\:315-320 | 8.2% | unknown | - | - | - | - | leap | claude-opus-5-5 | True |

## Proposals (rule-relaxing, never scored or trialled)

| title | relaxes | lane | model | returned | rationale |
| --- | --- | --- | --- | --- | --- |
