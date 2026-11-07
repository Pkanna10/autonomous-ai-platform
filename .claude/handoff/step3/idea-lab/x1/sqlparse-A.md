# X1 ideas: sqlparse, A

Floor 2.0%; ceilings predicted from E1's profile.

These rows are the raw list behind unique mechanisms and the share new to today's generator (upper bound, the dedupe under-merges (O39)).

| # | title | mechanism | target lines | ceiling | audit | duplicate of | trial | gain / floor | op count | lane | model | returned |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Inline token-type matching in imt and _token_matching to cut per-token call overhead | - | - | - | feasible | - | - | - | - | today | claude-sonnet-5-5 | True |
| 2 | Speed up the token type containment check and Token.match | - | - | - | unknown | - | - | - | - | today | claude-sonnet-5-5 | True |
| 3 | Optimize lexer get_tokens loop with a precompiled combined regex and fewer per-token operations | - | - | - | feasible | - | - | - | - | today | claude-sonnet-5-5 | True |
| 4 | Reduce grouping pass overhead in _group and _group_matching | - | - | - | unknown | - | - | - | - | today | claude-sonnet-5-5 | True |
| 5 | Cache flatten results and slim the statement splitter's per-token work | - | - | - | feasible | - | - | - | - | today | claude-sonnet-5-5 | True |

## Proposals (rule-relaxing, never scored or trialled)

| title | relaxes | lane | model | returned | rationale |
| --- | --- | --- | --- | --- | --- |
