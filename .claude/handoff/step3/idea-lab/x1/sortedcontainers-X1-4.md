# X1 ideas: sortedcontainers, X1-4

Floor 2.0%; ceilings predicted from E1's profile.

These rows are the raw list behind unique mechanisms and the share new to today's generator (upper bound, the dedupe under-merges (O39)).

| # | title | mechanism | target lines | ceiling | audit | duplicate of | trial | gain / floor | op count | lane | model | returned |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Inline _expand fast path into SortedList.add to avoid a method call per add | remove_work | sortedcontainers/sortedlist.py\:278-281 | 26.4% | - | - | - | - | - | obvious | claude-sonnet-5-5 | True |
| 2 | Inline _expand fast path into SortedKeyList.add | remove_work | sortedcontainers/sortedlist.py\:1810-1813 | 21.6% | - | - | - | - | - | obvious | claude-sonnet-5-5 | True |
| 3 | SortedDict.__setitem__\: skip redundant double lookup via dict.__contains__ and bound locals | specialised_fast_path | sortedcontainers/sorteddict.py\:298-300 | - | - | - | - | - | - | obvious | claude-sonnet-5-5 | True |

## Proposals (rule-relaxing, never scored or trialled)

| title | relaxes | lane | model | returned | rationale |
| --- | --- | --- | --- | --- | --- |
| Replace SortedList sublist storage with a compiled blist/C-backed sorted container for add paths | new_dependency | relax_dependency | claude-sonnet-5-5 | False | - |
| Defer SortedKeyList/SortedList sorting\: buffer adds and merge in sorted batches lazily | output_order | relax_output_order | claude-sonnet-5-5 | False | - |
| Install-time generated specialised SortedList.add with the expand check inlined and bisect locals bound | install_precompute | relax_precompute | claude-sonnet-5-5 | True | Add a build or install step that generates a flattened module variant of SortedList.add. The variant contains the fast path of _expand (index increment loop, load-based split check) inline and uses a… |
| SortedDict\: add private fused add-if-absent entry in SortedList to skip bound-method indirection | api_change | relax_api | claude-sonnet-5-5 | True | Give SortedList a new public method that takes a value plus a precomputed 'known absent' guarantee and does the append/insort and the length-bookkeeping in one frame, with the load-split check perfor… |
| Add SortedList.add_many_sorted bulk insert to replace repeated add for batched inputs | api_change | relax_api | claude-sonnet-5-5 | False | - |
