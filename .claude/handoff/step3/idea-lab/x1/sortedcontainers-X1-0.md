# X1 ideas: sortedcontainers, X1-0

Floor 2.0%; ceilings predicted from E1's profile.

These rows are the raw list behind unique mechanisms and the share new to today's generator (upper bound, the dedupe under-merges (O39)).

| # | title | mechanism | target lines | ceiling | audit | duplicate of | trial | gain / floor | op count | lane | model | returned |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Inline _expand fast path into SortedList.add | remove_work | sortedcontainers/sortedlist.py\:279-283 | 26.4% | feasible | - | inconclusive | 0.4% / 9.9% | 5836421 → 5543790 calls (-5.0%) | obvious | claude-sonnet-5-5 | True |
| 2 | Inline _expand fast path into SortedKeyList.add | remove_work | sortedcontainers/sortedlist.py\:1811-1815 | 21.6% | feasible | - | inconclusive | 1.9% / 6.7% | 5836421 → 5686549 calls (-2.6%) | obvious | claude-sonnet-5-5 | True |
| 3 | SortedDict.__setitem__\: skip redundant membership overhead | specialised_fast_path | sortedcontainers/sorteddict.py\:298-300 | - | unknown | - | inconclusive | -4.5% / 16.3% | 5836421 → 5986421 calls (+2.6%) | obvious | claude-sonnet-5-5 | True |
| 4 | SortedKeyList.add\: skip key call and key-list work when key is identity-like | remove_work | sortedcontainers/sortedlist.py\:1809-1811 | 21.6% | infeasible | SortedKeyList.add\: fuse key bisect into maxes path and skip _keys lookups via local sublist refs (X1-3) | - | - | - | eliminate | claude-sonnet-5-5 | False |
| 5 | SortedKeyList.discard\: avoid repeated _keys\[pos\] lookups and len() calls in first-probe path | remove_work | sortedcontainers/sortedlist.py\:1933-1936 | - | infeasible | SortedKeyList.discard\: drop per-step re-lookups and skip scan loop for exact first match (X1-0) | - | - | - | eliminate | claude-sonnet-5-5 | False |
| 6 | SortedKeyList.discard\: skip per-step tuple/while scan setup when the first key hit matches | remove_work | sortedcontainers/sortedlist.py\:1933-1940 | - | - | - | - | - | - | assume_less | claude-sonnet-5-5 | False |
| 7 | SortedKeyList._delete\: skip the key-list deletion double lookup and use a local for self._load | remove_work | sortedcontainers/sortedlist.py\:2068-2073 | 3.0% | - | - | - | - | - | assume_less | claude-sonnet-5-5 | False |
| 8 | SortedKeyList.discard\: skip the duplicate-key scan loop when the located element matches | specialised_fast_path | sortedcontainers/sortedlist.py\:1933-1939 | - | infeasible | SortedKeyList.discard\: drop per-step re-lookups and skip scan loop for exact first match (X1-0) | - | - | - | name_the_problem | claude-sonnet-5-5 | False |
| 9 | SortedList._delete\: replace leaf-to-root index decrement loop with a combined walk using cached locals | loop_or_control_flow | sortedcontainers/sortedlist.py\:493-498 | 4.2% | unknown | - | - | - | - | name_the_problem | claude-sonnet-5-5 | True |
| 10 | SortedList.add\: append fast path comparing against last max before bisect | specialised_fast_path | sortedcontainers/sortedlist.py\:272-277 | 26.4% | - | - | - | - | - | name_the_problem | claude-sonnet-5-5 | False |
| 11 | SortedKeyList.discard\: drop per-step re-lookups and skip scan loop for exact first match | specialised_fast_path | sortedcontainers/sortedlist.py\:1933-1939 | - | feasible | - | - | - | - | recombine | claude-sonnet-5-5 | True |
| 12 | SortedKeyList.add\: append fast path when key &gt;= last max, skipping bisect_right and expand | loop_or_control_flow | sortedcontainers/sortedlist.py\:1809-1813 | 21.6% | infeasible | Inline _expand fast path into SortedKeyList.add (X1-0) | - | - | - | recombine | claude-sonnet-5-5 | False |
| 13 | Lazy positional index\: stop maintaining _index in add/delete, rebuild only on demand | precompute_or_cache | sortedcontainers/sortedlist.py\:493-498 | 4.2% | infeasible | Skip index maintenance walk lazily\: mark index dirty instead of incrementing tree path per add/delete (X1-0) | - | - | - | recombine | claude-sonnet-5-5 | False |
| 14 | SortedDict.__setitem__\: single dict.setdefault-style insert avoiding double hashing | specialised_fast_path | sortedcontainers/sorteddict.py\:298-300 | - | infeasible | SortedDict.__setitem__\: skip redundant membership overhead (X1-0) | - | - | - | recombine | claude-sonnet-5-5 | False |
| 15 | Skip index-update loop in _expand when no positional index is built, by merging the pop-heavy index maintenance | specialised_fast_path | sortedcontainers/sortedlist.py\:490-494 | 4.2% | - | - | - | - | - | resolve_tradeoff | claude-sonnet-5-5 | False |
| 16 | SortedKeyList.discard\: avoid duplicate _keys\[pos\] lookups and len calls on the common single-match path | specialised_fast_path | sortedcontainers/sortedlist.py\:1933-1939 | - | - | - | - | - | - | resolve_tradeoff | claude-sonnet-5-5 | False |
| 17 | SortedKeyList.discard\: skip key-list scan loop bookkeeping with direct single-probe fast path | remove_work | sortedcontainers/sortedlist.py\:1933-1936 | - | infeasible | SortedKeyList.discard\: drop per-step re-lookups and skip scan loop for exact first match (X1-0) | - | - | - | far | claude-sonnet-5-5 | False |
| 18 | Skip index maintenance walk lazily\: mark index dirty instead of incrementing tree path per add/delete | precompute_or_cache | sortedcontainers/sortedlist.py\:316-320 | 8.2% | unknown | - | - | - | - | far | claude-sonnet-5-5 | False |
| 19 | Replace heap-shaped positional tree with a two-level block-count index so add/delete touch one counter | data_structure | sortedcontainers/sortedlist.py\:315-320 | 8.2% | unknown | - | - | - | - | leap | claude-opus-5-5 | True |
| 20 | Leaf-only index updates with lazy bottom-up refresh of internal tree nodes before _pos/_loc | lazy_or_streaming | sortedcontainers/sortedlist.py\:493-498 | 4.2% | - | - | - | - | - | leap | claude-opus-5-5 | False |

## Proposals (rule-relaxing, never scored or trialled)

| title | relaxes | lane | model | returned | rationale |
| --- | --- | --- | --- | --- | --- |
