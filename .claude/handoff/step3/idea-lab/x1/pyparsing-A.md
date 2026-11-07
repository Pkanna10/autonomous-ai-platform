# X1 ideas: pyparsing, A

Floor 2.0%; ceilings predicted from E1's profile.

These rows are the raw list behind unique mechanisms and the share new to today's generator (upper bound, the dedupe under-merges (O39)).

| # | title | mechanism | target lines | ceiling | audit | duplicate of | trial | gain / floor | op count | lane | model | returned |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Slim down _parseNoCache fast path for the no-packrat, no-debug case | - | - | - | feasible | - | - | - | - | today | claude-sonnet-5-5 | True |
| 2 | Inline whitespace skipping in preParse and skip it when there are no ignorables or whitespace chars | - | - | - | feasible | - | - | - | - | today | claude-sonnet-5-5 | True |
| 3 | Cheaper ParseResults construction via a fast path in __new__ and __init__ | - | - | - | feasible | - | - | - | - | today | claude-sonnet-5-5 | True |
| 4 | Avoid building full ParseException objects for failed alternatives in the inner loops | - | - | - | infeasible | - | - | - | - | today | claude-sonnet-5-5 | True |
| 5 | Optimise the infix_notation operator-level parseImpl and And/MatchFirst loops | - | - | - | unknown | - | - | - | - | today | claude-sonnet-5-5 | True |

## Proposals (rule-relaxing, never scored or trialled)

| title | relaxes | lane | model | returned | rationale |
| --- | --- | --- | --- | --- | --- |
