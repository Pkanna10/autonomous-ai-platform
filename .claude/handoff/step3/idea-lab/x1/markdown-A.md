# X1 ideas: markdown, A

Floor 2.0%; ceilings predicted from E1's profile.

These rows are the raw list behind unique mechanisms and the share new to today's generator (upper bound, the dedupe under-merges (O39)).

| # | title | mechanism | target lines | ceiling | audit | duplicate of | trial | gain / floor | op count | lane | model | returned |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Cache the ordered inline pattern list and skip patterns that cannot match in __applyPattern | - | - | - | unknown | - | - | - | - | today | claude-sonnet-5-5 | True |
| 2 | Make Registry __getitem__ cheaper by caching the sorted list and fast-pathing string-key lookup | - | - | - | feasible | - | - | - | - | today | claude-sonnet-5-5 | True |
| 3 | Speed up abbr iter_element by avoiding recursive generator and per-node work | - | - | - | unknown | - | - | - | - | today | claude-sonnet-5-5 | True |
| 4 | Optimize __processPlaceholders and __build_ancestors with early exits and cached lookups | - | - | - | feasible | - | - | - | - | today | claude-sonnet-5-5 | True |
| 5 | Speed up the serializer and is_block_level with fast checks | - | - | - | unknown | - | - | - | - | today | claude-sonnet-5-5 | True |

## Proposals (rule-relaxing, never scored or trialled)

| title | relaxes | lane | model | returned | rationale |
| --- | --- | --- | --- | --- | --- |
