# X1 ideas: more_itertools, X1-3

Floor 2.0%; ceilings predicted from E1's profile.

These rows are the raw list behind unique mechanisms and the share new to today's generator (upper bound, the dedupe under-merges (O39)).

| # | title | mechanism | target lines | ceiling | audit | duplicate of | trial | gain / floor | op count | lane | model | returned |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Windowed running min/max\: store parallel index and value deques, avoid tuple allocation | allocation_or_copying | more_itertools/recipes.py\:1468-1472 | 7.3% | infeasible | Avoid tuple allocation and index arithmetic in _windowed_running_min deque (X1-0) | - | - | - | obvious | claude-sonnet-5-5 | True |
| 2 | Windowed running mean\: avoid len(window) calls by tracking the count and using local method bindings | loop_or_control_flow | more_itertools/recipes.py\:1425-1429 | - | infeasible | Cut per-item overhead in the windowed running min/max/mean generators (A) | - | - | - | obvious | claude-sonnet-5-5 | True |
| 3 | bucket._get_values\: bind cache deque and hoist attribute lookups | loop_or_control_flow | more_itertools/more.py\:1198-1202 | 10.3% | infeasible | Speed up _get_values in islice_extended / bucket path (A) | - | - | - | obvious | claude-sonnet-5-5 | True |
| 4 | collapse\: fast path for non-iterable scalars and local bindings | specialised_fast_path | more_itertools/more.py\:1433-1435 | 5.5% | - | - | - | - | - | obvious | claude-sonnet-5-5 | True |
| 5 | bucket._get_values\: replace try/next/except StopIteration with a for loop over the shared iterator | loop_or_control_flow | more_itertools/more.py\:1204-1207 | 10.3% | - | - | - | - | - | eliminate | claude-sonnet-5-5 | False |
| 6 | bucket._get_values\: skip the key-equality lookup by caching the per-value deque once per generator | remove_work | more_itertools/more.py\:1198-1199 | 10.3% | - | - | - | - | - | assume_less | claude-sonnet-5-5 | False |
| 7 | bucket._get_values\: skip the validator call for already-cached keys by using a per-key seen set | precompute_or_cache | more_itertools/more.py\:1212-1213 | 10.3% | unknown | - | - | - | - | name_the_problem | claude-sonnet-5-5 | True |
| 8 | set_partitions\: hoist the block-size filter lambda and skip it when size limits are trivial | remove_work | more_itertools/more.py\:3538-3541 | 5.4% | unknown | - | - | - | - | recombine | claude-sonnet-5-5 | True |
| 9 | Windowed running min/max\: skip enumerate and tuple storage by using a monotonic deque with a countdown expiry | specialised_fast_path | more_itertools/recipes.py\:1468-1471 | 7.3% | infeasible | Cut per-item overhead in the windowed running min/max/mean generators (A) | - | - | - | resolve_tradeoff | claude-sonnet-5-5 | True |
| 10 | bucket._get_values\: skip cache check for the value being scanned by caching per-value deque once | remove_work | more_itertools/more.py\:1198-1199 | 10.3% | infeasible | Speed up _get_values in islice_extended / bucket path (A) | - | - | - | far | claude-sonnet-5-5 | False |
| 11 | Windowed running min/max\: van Herk/Gil-Werman block algorithm driven by C-level accumulate and map | algorithm | more_itertools/recipes.py\:1467-1472 | 7.3% | - | - | - | - | - | leap | claude-opus-5-5 | False |
| 12 | Windowed running mean\: drop the deque by pairing the stream with a tee-lagged copy in a two-phase loop | representation | more_itertools/recipes.py\:1424-1429 | - | feasible | - | - | - | - | leap | claude-opus-5-5 | True |

## Proposals (rule-relaxing, never scored or trialled)

| title | relaxes | lane | model | returned | rationale |
| --- | --- | --- | --- | --- | --- |
