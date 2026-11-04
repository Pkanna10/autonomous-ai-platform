# X1 ideas: idna, X1-3

Floor 2.0%; ceilings predicted from E1's profile.

These rows are the raw list behind unique mechanisms and the share new to today's generator (upper bound, the dedupe under-merges (O39)).

| # | title | mechanism | target lines | ceiling | audit | duplicate of | trial | gain / floor | op count | lane | model | returned |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Inline range decoding in intranges_contain to cut helper calls | remove_work | idna/intranges.py\:42-43 | - | infeasible | Remove per-call range encode/decode in intranges_contain (A) | - | - | - | obvious | claude-sonnet-5-5 | True |
| 2 | Memoise per-codepoint PVALID classification in check_label loop | precompute_or_cache | idna/core.py\:481-483 | - | - | - | - | - | - | eliminate | claude-sonnet-5-5 | False |
| 3 | Skip redundant re-validation in alabel/ulabel ASCII path by fast-pathing check_label for pure-ASCII LDH labels | specialised_fast_path | idna/core.py\:480-483 | - | infeasible | ASCII fast path in check_label\: lowercase letters/digits/hyphen skip NFC, combiner, per-codepoint and bidi checks (X1-1) | - | - | - | eliminate | claude-sonnet-5-5 | False |
| 4 | Hoist codepoint_classes lookups and cache PVALID ranges in check_label loop | remove_work | idna/core.py\:482-483 | - | - | - | - | - | - | assume_less | claude-sonnet-5-5 | False |
| 5 | ASCII fast path in check_label loop for lowercase letters, digits and hyphen | specialised_fast_path | idna/core.py\:481-483 | - | feasible | - | - | - | - | assume_less | claude-sonnet-5-5 | False |
| 6 | Memoise per-codepoint PVALID result in a dict cache in check_label | precompute_or_cache | idna/core.py\:482-483 | - | - | - | - | - | - | assume_less | claude-sonnet-5-5 | False |
| 7 | Hoist PVALID range table lookup and use a per-codepoint class memo in check_label | precompute_or_cache | idna/core.py\:482-484 | - | infeasible | Cache per-codepoint validity results in check_label to skip repeated intranges bisect (A) | - | - | - | name_the_problem | claude-sonnet-5-5 | True |
| 8 | Fast-path check_label with a precomputed set of all PVALID codepoints seen to pass whole labels | specialised_fast_path | idna/core.py\:480-483 | - | feasible | - | - | - | - | name_the_problem | claude-sonnet-5-5 | False |
| 9 | Cache per-label validity result in check_label via a bounded memo of already-validated labels | precompute_or_cache | idna/core.py\:476-480 | - | - | - | - | - | - | recombine | claude-sonnet-5-5 | False |
| 10 | Fuse check_bidi's two bidirectional passes into one by caching per-label direction list | loop_or_control_flow | idna/core.py\:190-192 | - | infeasible | Fuse bidi direction scan\: skip full check for labels with only LTR characters (X1-0) | - | - | - | recombine | claude-sonnet-5-5 | True |
| 11 | Fast path in check_label\: ASCII-lowercase labels validated by regex, skipping per-codepoint bisect | precompute_or_cache | idna/core.py\:482-483 | - | infeasible | ASCII fast path in check_label loop for lowercase letters, digits and hyphen (X1-3) | - | - | - | recombine | claude-sonnet-5-5 | False |
| 12 | Avoid redundant ASCII A-label re-validation and double punycode in ulabel for decode path | precompute_or_cache | idna/core.py\:605-606 | - | unknown | - | - | - | - | recombine | claude-sonnet-5-5 | False |
| 13 | Single-pass bidi direction scan with early skip for LTR-only labels in check_bidi | remove_work | idna/core.py\:207-208 | - | infeasible | Fuse bidi direction scan\: skip full check for labels with only LTR characters (X1-0) | - | - | - | resolve_tradeoff | claude-sonnet-5-5 | False |
| 14 | Memoise intranges_contain results per (codepoint, table) with a dict cache | precompute_or_cache | idna/intranges.py\:42-43 | - | unknown | - | - | - | - | resolve_tradeoff | claude-sonnet-5-5 | True |
| 15 | Hoist PVALID range table lookup and use a per-label memo of validated codepoints in check_label | precompute_or_cache | idna/core.py\:482-483 | - | - | - | - | - | - | far | claude-sonnet-5-5 | False |
| 16 | Memoise alabel's A-label to U-label results so ulabel skips Punycode decode, re-encode and check_label on round trips | precompute_or_cache | idna/core.py\:605-608 | - | - | - | - | - | - | leap | claude-opus-5-5 | False |
| 17 | Replace per-codepoint PVALID/CONTEXTJ/CONTEXTO bisects in check_label with a lazily filled codepoint-class dict | precompute_or_cache | idna/core.py\:480-484 | - | infeasible | Cache per-codepoint validity results in check_label to skip repeated intranges bisect (A) | - | - | - | leap | claude-opus-5-5 | False |
| 18 | Remember labels that already passed check_label and return early on repeats | precompute_or_cache | idna/core.py\:476-478 | - | - | - | - | - | - | leap | claude-opus-5-5 | False |

## Proposals (rule-relaxing, never scored or trialled)

| title | relaxes | lane | model | returned | rationale |
| --- | --- | --- | --- | --- | --- |
