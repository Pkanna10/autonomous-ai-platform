# X1 ideas: sortedcontainers, A

Floor 2.0%; ceilings predicted from E1's profile.

These rows are the raw list behind unique mechanisms and the share new to today's generator (upper bound, the dedupe under-merges (O39)).

| # | title | mechanism | target lines | ceiling | audit | duplicate of | trial | gain / floor | op count | lane | model | returned |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Trim attribute lookups and branching in SortedList.add and _expand fast paths | - | - | - | unknown | - | - | - | - | today | claude-sonnet-5-5 | True |
| 2 | Streamline SortedKeyList.add and _expand with locals and a single key computation | - | - | - | unknown | - | - | - | - | today | claude-sonnet-5-5 | True |
| 3 | Cheaper SortedDict.__setitem__ path for new and existing keys | - | - | - | infeasible | - | - | - | - | today | claude-sonnet-5-5 | True |
| 4 | Optimize _delete and discard fast paths in SortedList | - | - | - | unknown | - | - | - | - | today | claude-sonnet-5-5 | True |
| 5 | Speed up _pos index traversal with local variables | - | - | - | unknown | - | - | - | - | today | claude-sonnet-5-5 | True |

## Proposals (rule-relaxing, never scored or trialled)

| title | relaxes | lane | model | returned | rationale |
| --- | --- | --- | --- | --- | --- |
