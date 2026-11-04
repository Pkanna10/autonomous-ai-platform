# X1 ideas: idna, A

Floor 2.0%; ceilings predicted from E1's profile.

These rows are the raw list behind unique mechanisms and the share new to today's generator (upper bound, the dedupe under-merges (O39)).

| # | title | mechanism | target lines | ceiling | audit | duplicate of | trial | gain / floor | op count | lane | model | returned |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Cache per-codepoint validity results in check_label to skip repeated intranges bisect | - | - | - | feasible | - | - | - | - | today | claude-sonnet-5-5 | True |
| 2 | Remove per-call range encode/decode in intranges_contain | - | - | - | feasible | - | - | - | - | today | claude-sonnet-5-5 | True |
| 3 | Fast path for ASCII and common checks in check_label, check_bidi and check_hyphen_ok | - | - | - | unknown | - | - | - | - | today | claude-sonnet-5-5 | True |
| 4 | Speed up uts46_remap with a per-character mapping cache and a fast path for already-valid text | - | - | - | feasible | - | - | - | - | today | claude-sonnet-5-5 | True |

## Proposals (rule-relaxing, never scored or trialled)

| title | relaxes | lane | model | returned | rationale |
| --- | --- | --- | --- | --- | --- |
