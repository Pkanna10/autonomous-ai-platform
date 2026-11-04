# X1 ideas: sortedcontainers, X1-2

Floor 2.0%; ceilings predicted from E1's profile.

These rows are the raw list behind unique mechanisms and the share new to today's generator (upper bound, the dedupe under-merges (O39)).

| # | title | mechanism | target lines | ceiling | audit | duplicate of | trial | gain / floor | op count | lane | model | returned |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Inline _expand's common no-split path into SortedList.add | remove_work | sortedcontainers/sortedlist.py\:279-282 | - | infeasible | Inline _expand fast path into SortedList.add (X1-0) | inconclusive | 5.8% / 9.2% | 5836421 → 5393918 calls (-7.6%) | obvious | claude-sonnet-5-5 | True |
| 2 | Inline _expand's no-split path into SortedKeyList.add | remove_work | sortedcontainers/sortedlist.py\:1811-1814 | - | infeasible | Inline _expand fast path into SortedKeyList.add (X1-0) | inconclusive | 0.3% / 7.8% | 5836421 → 5686549 calls (-2.6%) | obvious | claude-sonnet-5-5 | True |
| 3 | SortedDict.__setitem__\: use dict.__contains__ and skip the redundant lookup | specialised_fast_path | sortedcontainers/sorteddict.py\:298-300 | - | infeasible | SortedDict.__setitem__\: skip redundant membership overhead (X1-0) | inconclusive | 3.2% / 7.5% | 5836421 → 5986421 calls (+2.6%) | obvious | claude-sonnet-5-5 | True |
| 4 | SortedList.add\: skip the _maxes truthiness and len() recompute by using pos comparison on cached length | specialised_fast_path | sortedcontainers/sortedlist.py\:274-277 | - | infeasible | Inline _expand fast path into SortedList.add (X1-0) | - | - | - | eliminate | claude-sonnet-5-5 | False |
| 5 | SortedList.pop\: avoid double _pos tree walk by deferring index build for deletes via direct (pos, idx) lookup | specialised_fast_path | sortedcontainers/sortedlist.py\:669-675 | - | - | - | - | - | - | eliminate | claude-sonnet-5-5 | False |
| 6 | SortedKeyList.add\: skip key-list bisect indirection by using insort-style append path when key is the new max | specialised_fast_path | sortedcontainers/sortedlist.py\:1809-1811 | - | infeasible | SortedKeyList.add\: fuse key bisect into maxes path and skip _keys lookups via local sublist refs (X1-3) | - | - | - | assume_less | claude-sonnet-5-5 | True |
| 7 | SortedKeyList.add\: skip key-list bisect by using one insort on a paired structure when key is identity | specialised_fast_path | sortedcontainers/sortedlist.py\:1809-1811 | - | unknown | - | - | - | - | name_the_problem | claude-sonnet-5-5 | False |
| 8 | Cache _lists\[pos\] and key reuse in SortedKeyList.discard via bisect on keys then direct compare | loop_or_control_flow | sortedcontainers/sortedlist.py\:1987-1991 | - | infeasible | Hoist per-bucket key/value list lookups out of the scan loop in SortedKeyList.discard (X1-1) | - | - | - | name_the_problem | claude-sonnet-5-5 | False |
| 9 | SortedKeyList.discard\: remove per-iteration double indexing and hoist sublist lookups | remove_work | sortedcontainers/sortedlist.py\:1933-1939 | - | infeasible | Hoist per-bucket key/value list lookups out of the scan loop in SortedKeyList.discard (X1-1) | - | - | - | recombine | claude-sonnet-5-5 | True |
| 10 | SortedList._delete\: skip index update loop via early-exit tree walk with local alias | loop_or_control_flow | sortedcontainers/sortedlist.py\:494-498 | - | infeasible | SortedList._delete\: replace leaf-to-root index decrement loop with a combined walk using cached locals (X1-0) | - | - | - | recombine | claude-sonnet-5-5 | False |
| 11 | SortedList._pos\: skip the tree-walk loop's per-iteration len check with a fixed-depth descent | loop_or_control_flow | sortedcontainers/sortedlist.py\:681-688 | - | - | - | - | - | - | resolve_tradeoff | claude-sonnet-5-5 | False |
| 12 | Replace the positional index tree with a lazily refreshed prefix-sum array and a low-water dirty mark | data_structure | sortedcontainers/sortedlist.py\:315-320 | - | infeasible | Replace the positional tree index with a lazily repaired flat prefix-sum array plus a dirty watermark (X1-1) | - | - | - | leap | claude-opus-5-5 | True |

## Proposals (rule-relaxing, never scored or trialled)

| title | relaxes | lane | model | returned | rationale |
| --- | --- | --- | --- | --- | --- |
