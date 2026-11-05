# X1 ideas: tomli, X1-2

Floor 2.0%; ceilings predicted from E1's profile.

These rows are the raw list behind unique mechanisms and the share new to today's generator (upper bound, the dedupe under-merges (O39)).

| # | title | mechanism | target lines | ceiling | audit | duplicate of | trial | gain / floor | op count | lane | model | returned |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Replace skip_chars per-character loop with compiled regex match for whitespace skipping | specialised_fast_path | src/tomli/_parser.py\:334-339 | 8.2% | infeasible | Replace skip_chars loop with compiled regex matching for whitespace skipping (A) | - | - | - | obvious | claude-sonnet-5-5 | True |
| 2 | Fast-path key parsing for single bare keys in parse_key/parse_key_part | specialised_fast_path | src/tomli/_parser.py\:479-482 | 11.0% | infeasible | Streamline key_value_rule and parse_key_value_pair, avoiding redundant flag and namespace work (A) | - | - | - | obvious | claude-sonnet-5-5 | True |
| 3 | Avoid generator and tuple building in key_value_rule for single-part keys | remove_work | src/tomli/_parser.py\:435-436 | 80.5% | infeasible | Streamline key_value_rule and parse_key_value_pair, avoiding redundant flag and namespace work (A) | - | - | - | obvious | claude-sonnet-5-5 | True |
| 4 | Fast-path for whitespace-only and empty skips in skip_comments_and_array_ws | specialised_fast_path | src/tomli/_parser.py\:378-381 | 10.1% | infeasible | Skip comments and array whitespace with one regex in skip_comments_and_array_ws (X1-0) | inconclusive | -2.7% / 3.0% | 2509071 → 2515632 calls (+0.3%) | obvious | claude-sonnet-5-5 | True |
| 5 | Skip the trailing skip_comment/skip_chars calls in loads when the next char is already a newline | remove_work | src/tomli/_parser.py\:202-203 | 94.2% | - | - | - | - | - | eliminate | claude-sonnet-5-5 | False |
| 6 | Skip flag recursion for scalar values in key_value_rule | specialised_fast_path | src/tomli/_parser.py\:456-457 | 80.5% | - | - | - | - | - | eliminate | claude-sonnet-5-5 | False |
| 7 | Skip nest_lvl check and char dispatch via dict-of-first-char in parse_value for common string/number starts | remove_work | src/tomli/_parser.py\:706-708 | 50.6% | - | - | - | - | - | assume_less | claude-sonnet-5-5 | False |
| 8 | Cheap prefix test before number regex in parse_value, order number match ahead of localtime | specialised_fast_path | src/tomli/_parser.py\:764-766 | 50.6% | infeasible | Skip the dispatch of datetime and localtime regexes for values that cannot start with a date or time (X1-3) | - | - | - | assume_less | claude-sonnet-5-5 | False |
| 9 | Replace parse_array's slice c = src\[pos\:pos+1\] with indexed char check | allocation_or_copying | src/tomli/_parser.py\:535-538 | 25.8% | - | - | - | - | - | assume_less | claude-sonnet-5-5 | False |
| 10 | Skip Flags FROZEN set call in key_value_rule for scalar values via isinstance ordering and early frozen check | precompute_or_cache | src/tomli/_parser.py\:450-452 | 80.5% | unknown | - | - | - | - | assume_less | claude-sonnet-5-5 | True |
| 11 | Scan bare-key text with one compiled regex match in parse_key_part | specialised_fast_path | src/tomli/_parser.py\:505-508 | 5.7% | infeasible | Streamline key_value_rule and parse_key_value_pair, avoiding redundant flag and namespace work (A) | - | - | - | name_the_problem | claude-sonnet-5-5 | False |
| 12 | Parse basic strings by scanning to the next special character with a regex | algorithm | src/tomli/_parser.py\:583-586 | - | - | - | - | - | - | name_the_problem | claude-sonnet-5-5 | False |
| 13 | Replace the array separator skip with a single regex for whitespace, newlines and comments | loop_or_control_flow | src/tomli/_parser.py\:531-533 | 25.8% | infeasible | Skip comments and array whitespace with one regex in skip_comments_and_array_ws (X1-0) | - | - | - | name_the_problem | claude-sonnet-5-5 | False |
| 14 | Dispatch parse_value on the first character with a digit/sign test before trying the regexes | specialised_fast_path | src/tomli/_parser.py\:757-759 | 50.6% | - | - | - | - | - | name_the_problem | claude-sonnet-5-5 | False |
| 15 | Cache single-char dispatch in parse_value via dict of first-char handlers for string/array/table starts | specialised_fast_path | src/tomli/_parser.py\:741-746 | 50.6% | - | - | - | - | - | recombine | claude-sonnet-5-5 | False |
| 16 | Skip Flags/pending bookkeeping in key_value_rule when value is scalar\: defer FROZEN check by precomputed isinstance | specialised_fast_path | src/tomli/_parser.py\:432-435 | 80.5% | - | - | - | - | - | recombine | claude-sonnet-5-5 | False |
| 17 | Skip Flags and NestedDict bookkeeping for plain top-level scalar key/values in key_value_rule | specialised_fast_path | src/tomli/_parser.py\:435-436 | 80.5% | infeasible | Streamline key_value_rule and parse_key_value_pair, avoiding redundant flag and namespace work (A) | - | - | - | resolve_tradeoff | claude-sonnet-5-5 | False |
| 18 | Slice-based fast path in parse_basic_str for runs of plain characters | algorithm | src/tomli/_parser.py\:608-610 | - | - | - | - | - | - | resolve_tradeoff | claude-sonnet-5-5 | False |
| 19 | Dispatch parse_value on a leading-digit check before the regexes | specialised_fast_path | src/tomli/_parser.py\:750-751 | 50.6% | infeasible | Skip the dispatch of datetime and localtime regexes for values that cannot start with a date or time (X1-3) | inconclusive | 1.3% / 3.0% | 2509071 → 2515471 calls (+0.3%) | resolve_tradeoff | claude-sonnet-5-5 | True |
| 20 | Memoize tuple key/Flags path checks\: skip flag lookups when no flags are set for a header | remove_work | src/tomli/_parser.py\:444-447 | 80.5% | - | - | - | - | - | far | claude-sonnet-5-5 | False |
| 21 | Cache single-char dispatch in parse_value via leading-char check before regex chain for numbers | specialised_fast_path | src/tomli/_parser.py\:750-753 | 50.6% | infeasible | Skip the dispatch of datetime and localtime regexes for values that cannot start with a date or time (X1-3) | - | - | - | far | claude-sonnet-5-5 | False |
| 22 | Bind hot globals as default-less locals in loads loop and hoist skip_chars of TOML_WS via startswith check | remove_work | src/tomli/_parser.py\:201-203 | 94.2% | - | - | - | - | - | far | claude-sonnet-5-5 | False |
| 23 | Cache the section's target dict and frozen verdict once per table header instead of per key/value in key_value_rule | precompute_or_cache | src/tomli/_parser.py\:444-450 | 80.5% | - | - | - | - | - | leap | claude-opus-5-5 | False |
| 24 | Fuse bare-key, whitespace and '=' scanning into one compiled regex at the head of parse_key_value_pair | specialised_fast_path | src/tomli/_parser.py\:465-470 | 63.1% | infeasible | Fuse key, '=' and surrounding whitespace into one regex match at the top of parse_key_value_pair (X1-3) | keep (graded by opus-5, unvalidated) | 7.0% / 3.3% | 2509071 → 2388482 calls (-4.8%) | leap | claude-opus-5-5 | True |

## Proposals (rule-relaxing, never scored or trialled)

| title | relaxes | lane | model | returned | rationale |
| --- | --- | --- | --- | --- | --- |
