# X1 ideas: tomli, X1-1

Floor 2.0%; ceilings predicted from E1's profile.

These rows are the raw list behind unique mechanisms and the share new to today's generator (upper bound, the dedupe under-merges (O39)).

| # | title | mechanism | target lines | ceiling | audit | duplicate of | trial | gain / floor | op count | lane | model | returned |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Replace per-char skip_chars loops with a precompiled regex match for whitespace | specialised_fast_path | src/tomli/_parser.py\:334-339 | - | infeasible | Replace skip_chars loop with compiled regex matching for whitespace skipping (A) | - | - | - | obvious | claude-sonnet-5-5 | True |
| 2 | Fast paths in skip_comments_and_array_ws to avoid redundant loop iteration | specialised_fast_path | src/tomli/_parser.py\:378-382 | - | feasible | - | inconclusive | 2.9% / 2.8% | 2509071 → 2224271 calls (-11.4%) | obvious | claude-sonnet-5-5 | True |
| 3 | Reorder parse_value dispatch and fast-path digits to RE_NUMBER before date/time regexes | specialised_fast_path | src/tomli/_parser.py\:750-753 | - | infeasible | Skip the dispatch of datetime and localtime regexes for values that cannot start with a date or time (X1-3) | inconclusive | 3.0% / 4.0% | 2509071 → 2515471 calls (+0.3%) | obvious | claude-sonnet-5-5 | True |
| 4 | Avoid generator and tuple building in key_value_rule for single-part keys | specialised_fast_path | src/tomli/_parser.py\:435-436 | - | infeasible | Streamline key_value_rule and parse_key_value_pair, avoiding redundant flag and namespace work (A) | - | - | - | obvious | claude-sonnet-5-5 | True |
| 5 | Fast path for single bare-key parts in parse_key/parse_key_part using a regex match | algorithm | src/tomli/_parser.py\:506-508 | - | - | - | - | - | - | obvious | claude-sonnet-5-5 | True |
| 6 | Cache the current table's nest and FROZEN verdict across key/value lines of one \[header\] section | precompute_or_cache | src/tomli/_parser.py\:444-450 | - | - | - | - | - | - | eliminate | claude-opus-5-5 | False |
| 7 | Regex fast path for escape-free one-line basic and literal strings in parse_value | specialised_fast_path | src/tomli/_parser.py\:722-725 | - | - | - | - | - | - | eliminate | claude-opus-5-5 | False |
| 8 | Skip redundant skip_chars/skip_comment calls in the loads statement loop when the next char is already decisive | remove_work | src/tomli/_parser.py\:201-203 | - | - | - | - | - | - | eliminate | claude-opus-5-5 | False |
| 9 | Cache the current header's target nest dict and FROZEN verdict across key/value lines in key_value_rule | precompute_or_cache | src/tomli/_parser.py\:444-450 | - | - | - | - | - | - | assume_less | claude-fable-5 | False |
| 10 | Fast path in loads statement loop\: skip trailing-ws and comment calls when the next char is already a newline | specialised_fast_path | src/tomli/_parser.py\:201-203 | - | - | - | - | - | - | assume_less | claude-fable-5 | False |
| 11 | Fuse '= ' recognition in parse_key_value_pair to drop the try/except char fetch and skip_chars call | specialised_fast_path | src/tomli/_parser.py\:470-473 | - | feasible | - | - | - | - | assume_less | claude-fable-5 | True |
| 12 | Inline parse_key_value_pair's body into key_value_rule to remove 51200 call and tuple round trips | loop_or_control_flow | src/tomli/_parser.py\:431-433 | - | - | - | - | - | - | assume_less | claude-fable-5 | False |
| 13 | Plain-dict fast path in parse_inline_table\: defer NestedDict and Flags until a dotted key or container value appears | specialised_fast_path | src/tomli/_parser.py\:745-747 | - | - | - | - | - | - | assume_less | claude-fable-5 | False |
| 14 | Cache the current section's nest dict and FROZEN check across key_value_rule calls under one header | precompute_or_cache | src/tomli/_parser.py\:449-452 | - | - | - | - | - | - | name_the_problem | claude-fable-5-1 | False |
| 15 | Scan basic strings in chunks with str.find/regex instead of per-character loop in parse_basic_str | loop_or_control_flow | src/tomli/_parser.py\:722-725 | - | - | - | - | - | - | name_the_problem | claude-fable-5-1 | False |
| 16 | Single combined scalar regex in parse_value (datetime\|localtime\|number) dispatched by lastgroup | specialised_fast_path | src/tomli/_parser.py\:750-755 | - | - | - | - | - | - | name_the_problem | claude-fable-5-1 | False |
| 17 | Newline fast path in the loads statement loop after a key/value or table rule | specialised_fast_path | src/tomli/_parser.py\:201-203 | - | feasible | - | - | - | - | name_the_problem | claude-fable-5-1 | True |
| 18 | Skip flag bookkeeping for single-part keys with scalar values in key_value_rule | specialised_fast_path | src/tomli/_parser.py\:435-436 | - | infeasible | Streamline key_value_rule and parse_key_value_pair, avoiding redundant flag and namespace work (A) | - | - | - | recombine | claude-sonnet-5-5 | False |
| 19 | Fuse parse_key_value_pair into key_value_rule via a top-level key/value fast path | loop_or_control_flow | src/tomli/_parser.py\:431-432 | - | - | - | - | - | - | recombine | claude-sonnet-5-5 | False |
| 20 | Fast-scan basic string bodies with a regex for runs of ordinary characters | algorithm | src/tomli/_parser.py\:586-588 | - | - | - | - | - | - | recombine | claude-sonnet-5-5 | False |
| 21 | Bind module-level regex/converter globals as function-local names in parse_value | precompute_or_cache | src/tomli/_parser.py\:750-753 | - | feasible | - | - | - | - | resolve_tradeoff | claude-sonnet-5 | True |
| 22 | Cache the last resolved table nest object across consecutive key_value_rule calls sharing a header | precompute_or_cache | src/tomli/_parser.py\:449-454 | - | infeasible | Skip Flags FROZEN set call in key_value_rule for scalar values via isinstance ordering and early frozen check (X1-2) | - | - | - | resolve_tradeoff | claude-sonnet-5 | False |
| 23 | Bind list.append as a local alias before the parse_array accumulation loop | precompute_or_cache | src/tomli/_parser.py\:530-536 | - | - | - | - | - | - | resolve_tradeoff | claude-sonnet-5 | False |
| 24 | In loads statement loop, skip the comment-skip call when the next character is not a hash mark (src/tomli/_parser.py) | remove_work | src/tomli/_parser.py\:219-219 | - | - | - | - | - | - | far | claude-haiku-5-5 | False |
| 25 | Cache the current section's target dict in loads so single-part keys skip the FROZEN check and nest walk | precompute_or_cache | src/tomli/_parser.py\:449-453 | - | - | - | - | - | - | leap | claude-opus-5-5 | False |
| 26 | Whole-array shape recogniser in parse_array\: one regex matches simple int/plain-string arrays, else fall back | specialised_fast_path | src/tomli/_parser.py\:530-535 | - | infeasible | Approximate-then-verify whole-array fast path in parse_array for flat arrays of simple scalars (X1-0) | keep (graded by opus-5, unvalidated) | 9.9% / 2.3% | 2509071 → 1849632 calls (-26.3%) | leap | claude-opus-5-5 | True |

## Proposals (rule-relaxing, never scored or trialled)

| title | relaxes | lane | model | returned | rationale |
| --- | --- | --- | --- | --- | --- |
