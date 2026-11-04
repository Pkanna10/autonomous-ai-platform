# X1 ideas: more_itertools, X1-1

Floor 2.0%; ceilings predicted from E1's profile.

These rows are the raw list behind unique mechanisms and the share new to today's generator (upper bound, the dedupe under-merges (O39)).

| # | title | mechanism | target lines | ceiling | audit | duplicate of | trial | gain / floor | op count | lane | model | returned |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Hoist attribute lookups and local bindings in bucket._get_values | remove_work | more_itertools/more.py\:1198-1199 | - | infeasible | Speed up _get_values in islice_extended / bucket path (A) | - | - | - | obvious | claude-sonnet-5-5 | True |
| 2 | Avoid tuple allocation and repeated indexing in windowed running min/max | allocation_or_copying | more_itertools/recipes.py\:1468-1471 | - | infeasible | Avoid tuple allocation and index arithmetic in _windowed_running_min deque (X1-0) | - | - | - | obvious | claude-sonnet-5-5 | True |
| 3 | Cache bound methods and drop len calls in windowed running mean | specialised_fast_path | more_itertools/recipes.py\:1425-1429 | - | infeasible | Cut per-item overhead in the windowed running min/max/mean generators (A) | - | - | - | obvious | claude-sonnet-5-5 | True |
| 4 | Fast path for non-iterable ints in collapse using a type check | specialised_fast_path | more_itertools/more.py\:1433-1436 | - | feasible | - | - | - | - | obvious | claude-sonnet-5-5 | True |
| 5 | Use bound locals and fewer lookups in windowed running median | loop_or_control_flow | more_itertools/recipes.py\:1372-1376 | - | - | - | - | - | - | obvious | claude-sonnet-5-5 | True |
| 6 | Replace collapse's deque stack with a plain list stack in more.py | data_structure | more_itertools/more.py\:1418-1423 | - | feasible | - | - | - | - | eliminate | claude-sonnet-5 | True |
| 7 | Add per-type iterability memoization cache in collapse's try/except path | precompute_or_cache | more_itertools/more.py\:1438-1442 | - | - | - | - | - | - | eliminate | claude-sonnet-5 | False |
| 8 | Specialise collapse's main loop to skip level bookkeeping when levels is None | specialised_fast_path | more_itertools/more.py\:1422-1429 | - | - | - | - | - | - | eliminate | claude-sonnet-5 | False |
| 9 | Replace sorted-list median window with two heaps and lazy deletion in _running_median_windowed | algorithm | more_itertools/recipes.py\:1373-1373 | - | - | - | - | - | - | assume_less | claude-haiku-5-5 | False |
| 10 | Iterate with a stack of iterators in collapse instead of re-pushing node tuples | loop_or_control_flow | more_itertools/more.py\:1445-1445 | - | - | - | - | - | - | assume_less | claude-haiku-5-5 | False |
| 11 | Block-decomposed (van Herk/Gil-Werman) sliding min/max built from C-level accumulate in running_min/running_max | algorithm | more_itertools/recipes.py\:1467-1472 | - | - | - | - | - | - | name_the_problem | claude-opus-5-5 | False |
| 12 | Windowed running_mean as a C-level pipeline\: tee + interleaved add/negated-subtract accumulate + truediv map | loop_or_control_flow | more_itertools/recipes.py\:1424-1429 | - | - | - | - | - | - | name_the_problem | claude-opus-5-5 | False |
| 13 | Replace try/next loop with a resumable for-loop over the parent iterator in bucket._get_values | loop_or_control_flow | more_itertools/more.py\:1203-1208 | - | feasible | - | - | - | - | name_the_problem | claude-opus-5-5 | True |
| 14 | Single-shift replace instead of insort-then-delete in _running_median_windowed steady state | data_structure | more_itertools/recipes.py\:1372-1377 | - | - | - | - | - | - | name_the_problem | claude-opus-5-5 | False |
| 15 | Block-based (two-stack) windowed min/max via itertools.accumulate in _windowed_running_min/_windowed_running_max | algorithm | more_itertools/recipes.py\:1468-1473 | - | - | - | - | - | - | recombine | claude-fable-5 | False |
| 16 | Windowed running mean as C-level prefix-sum difference (accumulate + tee + islice + map) in _windowed_running_mean | loop_or_control_flow | more_itertools/recipes.py\:1424-1429 | - | infeasible | Windowed running mean\: use accumulate-difference pipeline instead of per-item generator with deque (X1-1) | - | - | - | recombine | claude-fable-5 | False |
| 17 | Phase-split _running_median_windowed\: fill phase, then fixed-size steady loop with precomputed parity and ring buffer | loop_or_control_flow | more_itertools/recipes.py\:1376-1381 | - | feasible | - | - | - | - | recombine | claude-fable-5 | True |
| 18 | Flat iterator-stack fast path in collapse when levels is None\: drop (level, nodes) tuples and re-push churn | specialised_fast_path | more_itertools/more.py\:1444-1449 | - | - | - | - | - | - | recombine | claude-fable-5 | False |
| 19 | Restructure bucket._get_values\: drain cache in an inner loop and iterate parent with for-in instead of try/next | loop_or_control_flow | more_itertools/more.py\:1203-1208 | - | - | - | - | - | - | recombine | claude-fable-5 | False |
| 20 | Block-based (van Herk) sliding min/max via C-level accumulate/map instead of per-item deque loop | algorithm | more_itertools/recipes.py\:1470-1472 | - | unknown | - | - | - | - | resolve_tradeoff | claude-fable-5-1 | True |
| 21 | Windowed running mean as accumulate over (value, evicted) pairs from tee, dividing via map(truediv) | loop_or_control_flow | more_itertools/recipes.py\:1425-1429 | - | - | - | - | - | - | resolve_tradeoff | claude-fable-5-1 | False |
| 22 | bucket._get_values\: batch-pull parent items and compute keys with map(key) in C before caching | batching | more_itertools/more.py\:1208-1213 | - | - | - | - | - | - | resolve_tradeoff | claude-fable-5-1 | False |
| 23 | bucket\: skip the validator call entirely when no validator was supplied (default accept-all) | specialised_fast_path | more_itertools/more.py\:1208-1213 | - | - | - | - | - | - | resolve_tradeoff | claude-fable-5-1 | False |
| 24 | collapse\: memoise per exact type whether iter() succeeds, avoiding a raised TypeError per leaf | precompute_or_cache | more_itertools/more.py\:1439-1442 | - | - | - | - | - | - | resolve_tradeoff | claude-fable-5-1 | False |
| 25 | Windowed running median\: warm-up/steady-state split with fixed median index and equal-value skip | loop_or_control_flow | more_itertools/recipes.py\:1375-1380 | - | - | - | - | - | - | resolve_tradeoff | claude-fable-5-1 | False |
| 26 | Windowed running mean\: use accumulate-difference pipeline instead of per-item generator with deque | loop_or_control_flow | more_itertools/recipes.py\:1425-1429 | - | unknown | - | - | - | - | far | claude-sonnet-5-5 | True |
| 27 | Running median window\: replace per-item deque with index into the input via a lagged tee | loop_or_control_flow | more_itertools/recipes.py\:1372-1377 | - | - | - | - | - | - | far | claude-sonnet-5-5 | False |
| 28 | Van Herk/Gil-Werman block algorithm for windowed running_min/max using C-level accumulate and map(min/max) | algorithm | more_itertools/recipes.py\:1467-1470 | - | - | - | - | - | - | leap | claude-opus-5-5 | False |
| 29 | Recast windowed running_mean as a C-level accumulate over an interleaved add/negated-lagged stream | representation | more_itertools/recipes.py\:1424-1429 | - | - | - | - | - | - | leap | claude-opus-5-5 | False |

## Proposals (rule-relaxing, never scored or trialled)

| title | relaxes | lane | model | returned | rationale |
| --- | --- | --- | --- | --- | --- |
