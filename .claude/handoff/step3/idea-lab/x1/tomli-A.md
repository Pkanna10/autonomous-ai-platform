# X1 ideas: tomli, A

Floor 2.0%; ceilings predicted from E1's profile.

These rows are the raw list behind unique mechanisms and the share new to today's generator (upper bound, the dedupe under-merges (O39)).

| # | title | mechanism | target lines | ceiling | audit | duplicate of | trial | gain / floor | op count | lane | model | returned |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Replace skip_chars loop with compiled regex matching for whitespace skipping | - | - | - | feasible | - | - | - | - | today | claude-sonnet-5-5 | True |
| 2 | Dispatch parse_value on first char via dict and cut redundant slicing | - | - | - | unknown | - | - | - | - | today | claude-sonnet-5-5 | True |
| 3 | Streamline key_value_rule and parse_key_value_pair, avoiding redundant flag and namespace work | - | - | - | feasible | - | - | - | - | today | claude-sonnet-5-5 | True |
| 4 | Fast path for basic strings without escapes using regex or str.find | - | - | - | unknown | - | - | - | - | today | claude-sonnet-5-5 | True |
| 5 | Optimize parse_array loop and the main loads statement loop | - | - | - | unknown | - | - | - | - | today | claude-sonnet-5-5 | True |

## Proposals (rule-relaxing, never scored or trialled)

| title | relaxes | lane | model | returned | rationale |
| --- | --- | --- | --- | --- | --- |
