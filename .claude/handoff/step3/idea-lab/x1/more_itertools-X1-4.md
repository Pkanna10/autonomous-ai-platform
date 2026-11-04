# X1 ideas: more_itertools, X1-4

Floor 2.0%; ceilings predicted from E1's profile.

These rows are the raw list behind unique mechanisms and the share new to today's generator (upper bound, the dedupe under-merges (O39)).

| # | title | mechanism | target lines | ceiling | audit | duplicate of | trial | gain / floor | op count | lane | model | returned |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Hoist attribute lookups and use local cache bindings in bucket._get_values | remove_work | more_itertools/more.py\:1198-1199 | - | - | - | - | - | - | obvious | claude-sonnet-5-5 | True |
| 2 | Avoid tuple allocation and repeated indexing in _windowed_running_min/max via parallel deques | allocation_or_copying | more_itertools/recipes.py\:1470-1472 | - | - | - | - | - | - | obvious | claude-sonnet-5-5 | True |
| 3 | Cheaper windowed running mean with local method binding | loop_or_control_flow | more_itertools/recipes.py\:1425-1429 | - | - | - | - | - | - | obvious | claude-sonnet-5-5 | True |
| 4 | Fast path in collapse for leaf nodes without isinstance tuple checks per item | specialised_fast_path | more_itertools/more.py\:1433-1436 | - | - | - | - | - | - | obvious | claude-sonnet-5-5 | True |
| 5 | Localise method lookups in _running_median_windowed | loop_or_control_flow | more_itertools/recipes.py\:1379-1381 | - | - | - | - | - | - | obvious | claude-sonnet-5-5 | True |

## Proposals (rule-relaxing, never scored or trialled)

| title | relaxes | lane | model | returned | rationale |
| --- | --- | --- | --- | --- | --- |
| Use sortedcontainers SortedList for windowed running median instead of list insort/del | new_dependency | relax_dependency | claude-sonnet-5-5 | True | Replace the plain list kept sorted with bisect.insort and del by index with a SortedList from the sortedcontainers package. Insertion, removal and indexed median lookup would then be sublinear for la… |
| Bucket\: drain parent once into per-key lists when order of emission may differ | output_order | relax_output_order | claude-sonnet-5-5 | True | Change bucket value retrieval so that on the first request for any key the parent iterator is consumed eagerly in one tight loop, partitioning all items into per-key lists. Later requests then return… |
| Collapse\: process nested children depth-first with a single flat loop instead of a deque of iterators | output_order | relax_output_order | claude-sonnet-5-5 | True | Replace the deque-of-(level, iterator) stack with a plain list stack. Where output order may be relaxed, flatten sibling leaf items of each node in a batch (for example by partitioning a node's child… |
| Install-time compiled (C-extension) versions of the windowed running min/max/mean kernels | install_precompute | relax_precompute | claude-sonnet-5-5 | True | Let the package build a small compiled artefact at install time that implements the sliding-window min, max and mean kernels as C-level iterators. running_min, running_max and running_mean would use … |
| Install-time generated, compiled collapse flattening for common nested list/tuple shapes | install_precompute | relax_precompute | claude-sonnet-5-5 | True | Ship an optional compiled helper built at install time that implements collapse's depth-first traversal with an explicit stack in C. It would special-case str, bytes and base_type, and would keep the… |
| Windowed running_min/max\: monotonic deque of values plus a parallel index deque, removing per-item tuples | api_change | relax_api | claude-sonnet-5-5 | True | Change the internal contract of the windowed min helper so the monotonic queue stores bare values in one deque and the matching indices in a second one. The expiry check then compares the front of th… |
