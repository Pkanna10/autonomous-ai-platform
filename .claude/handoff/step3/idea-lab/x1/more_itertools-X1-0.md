# X1 ideas: more_itertools, X1-0

Floor 2.0%; ceilings predicted from E1's profile.

These rows are the raw list behind unique mechanisms and the share new to today's generator (upper bound, the dedupe under-merges (O39)).

| # | title | mechanism | target lines | ceiling | audit | duplicate of | trial | gain / floor | op count | lane | model | returned |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Avoid tuple allocation and index arithmetic in _windowed_running_min deque | allocation_or_copying | more_itertools/recipes.py\:1468-1472 | 7.3% | feasible | - | - | - | - | obvious | claude-sonnet-5-5 | True |
| 2 | Same parallel-deque optimization for _windowed_running_max | allocation_or_copying | more_itertools/recipes.py\:1509-1513 | 6.4% | feasible | - | - | - | - | obvious | claude-sonnet-5-5 | True |
| 3 | Speed up _windowed_running_mean by hoisting method lookups and avoiding len() calls | loop_or_control_flow | more_itertools/recipes.py\:1425-1429 | - | infeasible | Cut per-item overhead in the windowed running min/max/mean generators (A) | - | - | - | obvious | claude-sonnet-5-5 | True |
| 4 | Optimize collapse inner loop\: cache isinstance tuple and bound methods | specialised_fast_path | more_itertools/more.py\:1433-1436 | 5.5% | infeasible | Streamline collapse's per-item type checks and stack handling (A) | - | - | - | obvious | claude-sonnet-5-5 | True |
| 5 | Skip redundant cache lookups in bucket._get_values by binding the per-value deque once | remove_work | more_itertools/more.py\:1198-1199 | 10.3% | - | - | - | - | - | eliminate | claude-sonnet-5-5 | False |
| 6 | Median window\: skip the insort-then-delete step by using bisect-based replace when the window is full | algorithm | more_itertools/recipes.py\:1373-1377 | - | unknown | - | - | - | - | eliminate | claude-sonnet-5-5 | True |
| 7 | Running median window\: skip window deque by using ordered-list only via bisect on arrival order | loop_or_control_flow | more_itertools/recipes.py\:1375-1380 | - | - | - | - | - | - | assume_less | claude-sonnet-5-5 | False |
| 8 | bucket._get_values\: bind cache deque and key lookup once per generator, avoid repeated dict lookup | loop_or_control_flow | more_itertools/more.py\:1198-1201 | 10.3% | feasible | - | - | - | - | assume_less | claude-sonnet-5-5 | True |
| 9 | Running min/max\: drop the enumerate index tuples by storing indices in a parallel counter and evicting by count | allocation_or_copying | more_itertools/recipes.py\:1470-1473 | 7.3% | infeasible | Avoid tuple allocation and index arithmetic in _windowed_running_min deque (X1-0) | - | - | - | assume_less | claude-sonnet-5-5 | False |
| 10 | Running median window\: replace window deque with index-based eviction from the input via a second tee-free ring list | loop_or_control_flow | more_itertools/recipes.py\:1379-1381 | - | - | - | - | - | - | name_the_problem | claude-sonnet-5-5 | False |
| 11 | bucket._get_values\: bind cache deque and key lookups locally, fetch cache entry once per loop | remove_work | more_itertools/more.py\:1198-1201 | 10.3% | - | - | - | - | - | name_the_problem | claude-sonnet-5-5 | False |
| 12 | Windowed running min/max\: store values and indices in two parallel deques with a monotonic-index fast path | representation | more_itertools/recipes.py\:1511-1514 | 6.4% | infeasible | Same parallel-deque optimization for _windowed_running_max (X1-0) | - | - | - | name_the_problem | claude-sonnet-5-5 | False |
| 13 | Fuse bucket._get_values cache lookup into a local deque, avoiding repeated dict indexing and attribute access | specialised_fast_path | more_itertools/more.py\:1198-1199 | 10.3% | infeasible | Speed up _get_values in islice_extended / bucket path (A) | - | - | - | recombine | claude-sonnet-5-5 | False |
| 14 | Replace tuple-and-index deque in windowed running min/max with a monotonic deque over a value deque and a counter | representation | more_itertools/recipes.py\:1470-1472 | 7.3% | infeasible | Avoid tuple allocation and index arithmetic in _windowed_running_min deque (X1-0) | - | - | - | recombine | claude-sonnet-5-5 | False |
| 15 | Skip eviction work in _running_median_windowed until the window is full | specialised_fast_path | more_itertools/recipes.py\:1372-1377 | - | infeasible | Running median window\: avoid second bisect by tracking via sorted insertion index (X1-0) | - | - | - | resolve_tradeoff | claude-sonnet-5-5 | False |
| 16 | bucket._get_values\: bind cache deque once per call and skip repeated dict lookups | remove_work | more_itertools/more.py\:1198-1202 | 10.3% | - | - | - | - | - | resolve_tradeoff | claude-sonnet-5-5 | False |
| 17 | Running median window\: avoid second bisect by tracking via sorted insertion index | loop_or_control_flow | more_itertools/recipes.py\:1372-1377 | - | feasible | - | - | - | - | far | claude-sonnet-5-5 | True |
| 18 | bucket._get_values\: hoist cache lookup and self attribute access out of the loop | remove_work | more_itertools/more.py\:1198-1199 | 10.3% | - | - | - | - | - | far | claude-sonnet-5-5 | False |
| 19 | Rebuild _windowed_running_mean as a C-level accumulate pipeline over the sample stream interleaved with its negated lagged copy | representation | more_itertools/recipes.py\:1424-1429 | - | - | - | - | - | - | leap | claude-opus-5-5 | False |
| 20 | bucket._get_values\: drain cached deque through a local reference and scan the parent with a for-loop and hoisted key/validator | loop_or_control_flow | more_itertools/more.py\:1198-1203 | 10.3% | - | - | - | - | - | leap | claude-opus-5-5 | False |

## Proposals (rule-relaxing, never scored or trialled)

| title | relaxes | lane | model | returned | rationale |
| --- | --- | --- | --- | --- | --- |
