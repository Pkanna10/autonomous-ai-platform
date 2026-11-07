# X1 ideas: tomli, X1-3

Floor 2.0%; ceilings predicted from E1's profile.

These rows are the raw list behind unique mechanisms and the share new to today's generator (upper bound, the dedupe under-merges (O39)).

| # | title | mechanism | target lines | ceiling | audit | duplicate of | trial | gain / floor | op count | lane | model | returned |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Skip the dispatch of datetime and localtime regexes for values that cannot start with a date or time | specialised_fast_path | src/tomli/_parser.py\:750-753 | 50.6% | feasible | - | - | - | - | obvious | claude-sonnet-5-5 | True |
| 2 | Inline skip_chars loops for whitespace in hot callers using a fast path check | specialised_fast_path | src/tomli/_parser.py\:334-339 | 8.2% | infeasible | Replace skip_chars loop with compiled regex matching for whitespace skipping (A) | - | - | - | obvious | claude-sonnet-5-5 | True |
| 3 | Fast path in key_value_rule for single-part keys | specialised_fast_path | src/tomli/_parser.py\:435-436 | 80.5% | infeasible | Streamline key_value_rule and parse_key_value_pair, avoiding redundant flag and namespace work (A) | - | - | - | obvious | claude-sonnet-5-5 | True |
| 4 | Scan array whitespace/comments with a single regex in skip_comments_and_array_ws | algorithm | src/tomli/_parser.py\:379-381 | 10.1% | infeasible | Skip comments and array whitespace with one regex in skip_comments_and_array_ws (X1-0) | inconclusive | -1.7% / 3.0% | 2509071 → 2515632 calls (+0.3%) | obvious | claude-sonnet-5-5 | True |
| 5 | Scan bare key parts with a precompiled regex in parse_key_part | algorithm | src/tomli/_parser.py\:506-508 | 5.7% | - | - | - | - | - | obvious | claude-sonnet-5-5 | True |
| 6 | Skip the nest_lvl guard and try/except in parse_value for non-nested scalar calls via a char-first dispatch | remove_work | src/tomli/_parser.py\:706-708 | 50.6% | - | - | - | - | - | eliminate | claude-sonnet-5-5 | False |
| 7 | Reorder parse_value so digit-leading values try RE_NUMBER before date/time regexes via a one-char lookahead | specialised_fast_path | src/tomli/_parser.py\:750-753 | 50.6% | - | - | - | - | - | eliminate | claude-sonnet-5-5 | False |
| 8 | Avoid slice allocation in parse_array's separator check | allocation_or_copying | src/tomli/_parser.py\:535-538 | 25.8% | - | - | - | - | - | eliminate | claude-sonnet-5-5 | False |
| 9 | Dispatch parse_value on first character to skip date/time regexes for non-digit starts | specialised_fast_path | src/tomli/_parser.py\:750-753 | 50.6% | infeasible | Dispatch parse_value on first character to skip datetime/localtime regexes for non-digit starts (X1-3) | - | - | - | assume_less | claude-sonnet-5-5 | False |
| 10 | Dispatch parse_value on first character via a lookup table of start-char classes | specialised_fast_path | src/tomli/_parser.py\:750-753 | 50.6% | - | - | - | - | - | name_the_problem | claude-sonnet-5-5 | False |
| 11 | Use a combined single-regex value-prefix classifier to skip failed matches for digits | specialised_fast_path | src/tomli/_parser.py\:757-759 | 50.6% | - | - | - | - | - | name_the_problem | claude-sonnet-5-5 | False |
| 12 | Skip the Flags bookkeeping in key_value_rule for single-part keys with scalar values | specialised_fast_path | src/tomli/_parser.py\:435-436 | 80.5% | infeasible | Streamline key_value_rule and parse_key_value_pair, avoiding redundant flag and namespace work (A) | - | - | - | recombine | claude-sonnet-5-5 | False |
| 13 | Cache parsed key tuples per distinct key text in parse_key_part to skip repeated scanning | specialised_fast_path | src/tomli/_parser.py\:479-481 | 11.0% | - | - | - | - | - | recombine | claude-sonnet-5-5 | False |
| 14 | Fast path in parse_basic_str using str.find for the closing quote when the span has no backslash or illegal chars | algorithm | src/tomli/_parser.py\:698-700 | 5.7% | infeasible | Fast path for basic strings without escapes using regex or str.find (A) | - | - | - | recombine | claude-sonnet-5-5 | True |
| 15 | Skip per-cont-key flag checks when the key is single-part in key_value_rule's frozen-parent check | specialised_fast_path | src/tomli/_parser.py\:435-436 | 80.5% | infeasible | Streamline key_value_rule and parse_key_value_pair, avoiding redundant flag and namespace work (A) | - | - | - | resolve_tradeoff | claude-sonnet-5-5 | False |
| 16 | Make skip_chars fast for str whitespace sets using a precomputed string and local bindings | specialised_fast_path | src/tomli/_parser.py\:335-337 | 8.2% | infeasible | Replace skip_chars loop with compiled regex matching for whitespace skipping (A) | - | - | - | resolve_tradeoff | claude-sonnet-5-5 | False |
| 17 | Dispatch parse_value on first character to skip datetime/localtime regexes for non-digit starts | remove_work | src/tomli/_parser.py\:750-753 | 50.6% | feasible | - | inconclusive | 0.5% / 4.0% | 2509071 → 2509071 calls (+0.0%) | far | claude-sonnet-5-5 | True |
| 18 | Bulk-parse flat scalar arrays in parse_array with one anchored regex match instead of per-element dispatch | specialised_fast_path | src/tomli/_parser.py\:530-533 | 25.8% | - | - | - | - | - | leap | claude-opus-5-5 | False |
| 19 | Fuse key, '=' and surrounding whitespace into one regex match at the top of parse_key_value_pair | specialised_fast_path | src/tomli/_parser.py\:465-470 | 63.1% | feasible | - | inconclusive (graded by opus-5, unvalidated) | 3.8% / 4.8% | 2509071 → 2449092 calls (-2.4%) | leap | claude-opus-5-5 | True |
| 20 | Escape-free basic strings in parse_value\: find closing quote with str.find and validate slice via one regex search | specialised_fast_path | src/tomli/_parser.py\:722-725 | 50.6% | - | - | - | - | - | leap | claude-opus-5-5 | False |

## Proposals (rule-relaxing, never scored or trialled)

| title | relaxes | lane | model | returned | rationale |
| --- | --- | --- | --- | --- | --- |
