# X1 ideas: tomli, X1-0

Floor 2.0%; ceilings predicted from E1's profile.

These rows are the raw list behind unique mechanisms and the share new to today's generator (upper bound, the dedupe under-merges (O39)).

| # | title | mechanism | target lines | ceiling | audit | duplicate of | trial | gain / floor | op count | lane | model | returned |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Skip whitespace in skip_chars via regex-free fast path in the statement loop and key parsing | specialised_fast_path | src/tomli/_parser.py\:334-339 | - | infeasible | Replace skip_chars loop with compiled regex matching for whitespace skipping (A) | - | - | - | obvious | claude-sonnet-5-5 | True |
| 2 | Fast path for bare keys in parse_key_part and parse_key using a compiled regex | specialised_fast_path | src/tomli/_parser.py\:505-508 | - | infeasible | Streamline key_value_rule and parse_key_value_pair, avoiding redundant flag and namespace work (A) | - | - | - | obvious | claude-sonnet-5-5 | True |
| 3 | Skip comments and array whitespace with one regex in skip_comments_and_array_ws | specialised_fast_path | src/tomli/_parser.py\:378-382 | - | feasible | - | inconclusive | -0.9% / 2.9% | 2509071 → 2515632 calls (+0.3%) | obvious | claude-sonnet-5-5 | True |
| 4 | Avoid generator and tuple slicing in key_value_rule for single-part keys | specialised_fast_path | src/tomli/_parser.py\:435-436 | - | infeasible | Streamline key_value_rule and parse_key_value_pair, avoiding redundant flag and namespace work (A) | - | - | - | obvious | claude-sonnet-5-5 | True |
| 5 | Reorder parse_value dispatch with a dict of first-char handlers for numbers and dates | specialised_fast_path | src/tomli/_parser.py\:750-751 | - | - | - | - | - | - | obvious | claude-sonnet-5-5 | True |
| 6 | Skip FROZEN flag marking in key_value_rule for scalar values only; avoid redundant tuple concat for abs_key_parent | remove_work | src/tomli/_parser.py\:435-436 | - | - | - | - | - | - | eliminate | claude-sonnet-5-5 | False |
| 7 | Replace per-char loop in parse_array trailing-comma checks by avoiding redundant skip_comments_and_array_ws calls | specialised_fast_path | src/tomli/_parser.py\:378-380 | - | - | - | - | - | - | eliminate | claude-sonnet-5-5 | False |
| 8 | Cache flag/namespace work\: skip frozen-flag recursion for scalar values in key_value_rule | precompute_or_cache | src/tomli/_parser.py\:444-447 | - | unknown | - | - | - | - | assume_less | claude-sonnet-5-5 | False |
| 9 | Fuse the value-then-whitespace skipping in parse_array with a single scan for the common separator | specialised_fast_path | src/tomli/_parser.py\:531-535 | - | - | - | - | - | - | assume_less | claude-sonnet-5-5 | False |
| 10 | Inline skip_chars loops for TOML_WS in the loads statement loop using a fast char check | remove_work | src/tomli/_parser.py\:184-186 | - | - | - | - | - | - | assume_less | claude-sonnet-5-5 | False |
| 11 | Replace per-char skip_chars loop with a precompiled regex span match for whitespace runs | specialised_fast_path | src/tomli/_parser.py\:334-339 | - | - | - | - | - | - | name_the_problem | claude-sonnet-5-5 | False |
| 12 | Inline the zero-comment check in skip_comments_and_array_ws to avoid repeated loop iterations | loop_or_control_flow | src/tomli/_parser.py\:378-382 | - | - | - | - | - | - | name_the_problem | claude-sonnet-5-5 | False |
| 13 | Fuse key_value_rule flag/nest handling with a top-level fast path for single-part keys with scalar values | specialised_fast_path | src/tomli/_parser.py\:435-436 | - | infeasible | Streamline key_value_rule and parse_key_value_pair, avoiding redundant flag and namespace work (A) | - | - | - | recombine | claude-sonnet-5-5 | False |
| 14 | Fuse parse_key_value_pair and parse_key for the common single bare-key case with one regex match | specialised_fast_path | src/tomli/_parser.py\:465-470 | - | - | - | - | - | - | recombine | claude-sonnet-5-5 | False |
| 15 | Fast path for plain basic strings in parse_value using a precompiled regex for the no-escape case | specialised_fast_path | src/tomli/_parser.py\:723-725 | - | feasible | - | inconclusive | -0.6% / 2.9% | 2509071 → 2525366 calls (+0.6%) | recombine | claude-sonnet-5-5 | True |
| 16 | Statement loop\: fuse blank-line and whitespace skipping with a single regex jump to next significant char | specialised_fast_path | src/tomli/_parser.py\:184-186 | - | - | - | - | - | - | recombine | claude-sonnet-5-5 | False |
| 17 | Cache bare-key flag/nest checks\: skip Flags checks in key_value_rule for single-part keys under a plain table | specialised_fast_path | src/tomli/_parser.py\:435-436 | - | - | - | - | - | - | resolve_tradeoff | claude-sonnet-5-5 | False |
| 18 | Fast path in parse_value for common first characters using a single check for digit-leading values before regex chain | specialised_fast_path | src/tomli/_parser.py\:750-751 | - | - | - | - | - | - | resolve_tradeoff | claude-sonnet-5-5 | False |
| 19 | Inline skip_chars loops for whitespace at hot call sites in parse_key_value_pair and loads using a direct char test | specialised_fast_path | src/tomli/_parser.py\:472-474 | - | infeasible | Replace skip_chars loop with compiled regex matching for whitespace skipping (A) | - | - | - | resolve_tradeoff | claude-sonnet-5-5 | True |
| 20 | Memoize repeated key tuples via a per-loads cache of parsed key parts in parse_key | precompute_or_cache | src/tomli/_parser.py\:479-481 | - | unknown | - | - | - | - | far | claude-sonnet-5-5 | True |
| 21 | Cache flags/nest lookups for the header across consecutive key_value_rule calls | precompute_or_cache | src/tomli/_parser.py\:444-447 | - | - | - | - | - | - | far | claude-sonnet-5-5 | False |
| 22 | Cache the current table's nest dict and frozen verdict per section in loads/key_value_rule for single-part keys | precompute_or_cache | src/tomli/_parser.py\:449-452 | - | - | - | - | - | - | leap | claude-opus-5-5 | False |
| 23 | Approximate-then-verify whole-array fast path in parse_array for flat arrays of simple scalars | specialised_fast_path | src/tomli/_parser.py\:531-533 | - | feasible | - | keep (graded by opus-5, unvalidated) | 9.9% / 3.2% | 2509071 → 1814960 calls (-27.7%) | leap | claude-opus-5-5 | True |

## Proposals (rule-relaxing, never scored or trialled)

| title | relaxes | lane | model | returned | rationale |
| --- | --- | --- | --- | --- | --- |
