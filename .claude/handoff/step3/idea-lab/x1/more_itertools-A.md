# X1 ideas: more_itertools, A

Floor 2.0%; ceilings predicted from E1's profile.

These rows are the raw list behind unique mechanisms and the share new to today's generator (upper bound, the dedupe under-merges (O39)).

| # | title | mechanism | target lines | ceiling | audit | duplicate of | trial | gain / floor | op count | lane | model | returned |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Cut per-item overhead in the windowed running min/max/mean generators | - | - | - | feasible | - | - | - | - | today | claude-sonnet-5-5 | True |
| 2 | Speed up _get_values in islice_extended / bucket path | - | - | - | feasible | - | - | - | - | today | claude-sonnet-5-5 | True |
| 3 | Optimise the running median windowed generator | - | - | - | unknown | - | - | - | - | today | claude-sonnet-5-5 | True |
| 4 | Streamline collapse's per-item type checks and stack handling | - | - | - | feasible | - | - | - | - | today | claude-sonnet-5-5 | True |
| 5 | Reduce generator overhead in set_partitions_helper and its genexpr | - | - | - | unknown | - | - | - | - | today | claude-sonnet-5-5 | True |

## Proposals (rule-relaxing, never scored or trialled)

| title | relaxes | lane | model | returned | rationale |
| --- | --- | --- | --- | --- | --- |
