# X1 ideas: more_itertools, X1-2

Floor 2.0%; ceilings predicted from E1's profile.

These rows are the raw list behind unique mechanisms and the share new to today's generator (upper bound, the dedupe under-merges (O39)).

| # | title | mechanism | target lines | ceiling | audit | duplicate of | trial | gain / floor | op count | lane | model | returned |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Hoist attribute lookups in bucket._get_values into locals | remove_work | more_itertools/more.py\:1198-1199 | - | infeasible | Speed up _get_values in islice_extended / bucket path (A) | - | - | - | obvious | claude-sonnet-5-5 | True |
| 2 | Cache locals and avoid tuple indexing in _windowed_running_min/max | allocation_or_copying | more_itertools/recipes.py\:1468-1472 | - | infeasible | Avoid tuple allocation and index arithmetic in _windowed_running_min deque (X1-0) | - | - | - | obvious | claude-sonnet-5-5 | True |
| 3 | Speed up _windowed_running_mean with local bindings and a tracked length | loop_or_control_flow | more_itertools/recipes.py\:1425-1429 | - | infeasible | Cut per-item overhead in the windowed running min/max/mean generators (A) | - | - | - | obvious | claude-sonnet-5-5 | True |
| 4 | Fast path in collapse for the common non-iterable, non-str items | remove_work | more_itertools/more.py\:1433-1435 | - | - | - | - | - | - | obvious | claude-sonnet-5-5 | True |
| 5 | Reduce per-item overhead in _running_median_windowed | loop_or_control_flow | more_itertools/recipes.py\:1372-1377 | - | - | - | - | - | - | obvious | claude-sonnet-5-5 | True |
| 6 | Skip the cache-miss re-check in bucket._get_values by draining the cache with a local deque reference | loop_or_control_flow | more_itertools/more.py\:1205-1208 | - | infeasible | Speed up _get_values in islice_extended / bucket path (A) | - | - | - | eliminate | claude-sonnet-5-5 | False |
| 7 | Running min/max window\: replace per-item index tuples with a monotonic deque of values plus an eviction counter | representation | more_itertools/recipes.py\:1468-1472 | - | infeasible | Avoid tuple allocation and index arithmetic in _windowed_running_min deque (X1-0) | - | - | - | assume_less | claude-sonnet-5-5 | False |
| 8 | Running median window\: use sorted-list bisect removal via the evicted value without the deque by indexing into the input | specialised_fast_path | more_itertools/recipes.py\:1379-1381 | - | - | - | - | - | - | assume_less | claude-sonnet-5-5 | False |
| 9 | bucket._get_values\: bind the key function, validator and cache once per generator instead of per item | loop_or_control_flow | more_itertools/more.py\:1205-1209 | - | infeasible | Speed up _get_values in islice_extended / bucket path (A) | - | - | - | assume_less | claude-sonnet-5-5 | False |
| 10 | Replace sorted-list window median with insort-only bisect on a preallocated deque pair (skip redundant bisect via value reuse) | specialised_fast_path | more_itertools/recipes.py\:1379-1381 | - | - | - | - | - | - | name_the_problem | claude-sonnet-5-5 | False |
| 11 | Fuse windowed running min/max sliding-window deque into a monotonic queue storing indices with a parallel values deque | allocation_or_copying | more_itertools/recipes.py\:1470-1472 | - | infeasible | Avoid tuple allocation and index arithmetic in _windowed_running_min deque (X1-0) | - | - | - | name_the_problem | claude-sonnet-5-5 | False |
| 12 | Running min/max windowed\: replace the monotonic deque with a two-parallel-deque layout (indices and values) and no tuples | representation | more_itertools/recipes.py\:1511-1513 | - | - | - | - | - | - | recombine | claude-sonnet-5-5 | False |
| 13 | Running median windowed\: avoid the deque by deriving the evicted value from the source with a ring list | data_structure | more_itertools/recipes.py\:1372-1377 | - | feasible | - | - | - | - | recombine | claude-sonnet-5-5 | True |
| 14 | bucket._get_values\: bind the cache deque once per call and drain it in an inner loop | loop_or_control_flow | more_itertools/more.py\:1198-1201 | - | infeasible | Speed up _get_values in islice_extended / bucket path (A) | - | - | - | recombine | claude-sonnet-5-5 | False |
| 15 | Replace insort/bisect/del median window with bounded-size fast path when window is small | specialised_fast_path | more_itertools/recipes.py\:1379-1381 | - | infeasible | Running median window\: avoid second bisect by tracking via sorted insertion index (X1-0) | - | - | - | resolve_tradeoff | claude-sonnet-5-5 | False |
| 16 | Running min/max window\: replace per-item index comparison with monotonic deque of values plus expiry counts | allocation_or_copying | more_itertools/recipes.py\:1509-1513 | - | infeasible | Same parallel-deque optimization for _windowed_running_max (X1-0) | - | - | - | far | claude-sonnet-5-5 | False |
| 17 | Replace sorted-list window median bookkeeping with index-based deletion using bisect on the popped value only when needed | loop_or_control_flow | more_itertools/recipes.py\:1379-1381 | - | - | - | - | - | - | far | claude-sonnet-5-5 | False |
| 18 | collapse\: skip stack push/pop for flat input by consuming runs of non-iterable leaves with a tight inner loop | precompute_or_cache | more_itertools/more.py\:1433-1435 | - | infeasible | Streamline collapse's per-item type checks and stack handling (A) | - | - | - | far | claude-sonnet-5-5 | False |
| 19 | Rewrite _windowed_running_mean as a C-level pipeline\: interleave value and negated lagged value, accumulate with add | representation | more_itertools/recipes.py\:1424-1429 | - | feasible | - | - | - | - | leap | claude-opus-5-5 | True |
| 20 | Van Herk/Gil-Werman block algorithm for _windowed_running_min/max using C-level accumulate per maxlen block | algorithm | more_itertools/recipes.py\:1467-1472 | - | - | - | - | - | - | leap | claude-opus-5-5 | False |

## Proposals (rule-relaxing, never scored or trialled)

| title | relaxes | lane | model | returned | rationale |
| --- | --- | --- | --- | --- | --- |
