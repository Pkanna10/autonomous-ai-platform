# X1 ideas: idna, X1-2

Floor 2.0%; ceilings predicted from E1's profile.

These rows are the raw list behind unique mechanisms and the share new to today's generator (upper bound, the dedupe under-merges (O39)).

| # | title | mechanism | target lines | ceiling | audit | duplicate of | trial | gain / floor | op count | lane | model | returned |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Inline range decode/encode in intranges_contain to drop helper calls | remove_work | idna/intranges.py\:42-43 | 10.4% | infeasible | Remove per-call range encode/decode in intranges_contain (A) | - | - | - | obvious | claude-sonnet-5-5 | True |
| 2 | Cache PVALID ranges in a local and add a per-codepoint fast cache in check_label | precompute_or_cache | idna/core.py\:482-483 | 24.8% | infeasible | Cache per-codepoint validity results in check_label to skip repeated intranges bisect (A) | - | - | - | obvious | claude-sonnet-5-5 | True |
| 3 | Fuse the two bidi passes and cache bidirectional class lookups in check_bidi | precompute_or_cache | idna/core.py\:190-192 | 3.4% | feasible | - | - | - | - | obvious | claude-sonnet-5-5 | True |
| 4 | Skip second bidi pass and bidi entirely for labels with no RTL characters via early-return in check_bidi | specialised_fast_path | idna/core.py\:189-192 | 3.4% | - | - | - | - | - | eliminate | claude-sonnet-5-5 | False |
| 5 | Resolve uts46data tables once instead of re-running the from-import on every uts46_remap call | precompute_or_cache | idna/core.py\:674-674 | 4.9% | - | - | - | - | - | assume_less | claude-sonnet-5-5 | False |
| 6 | Skip the ASCII re-encode and re-check in alabel by running check_label directly on the ASCII str | remove_work | idna/core.py\:544-545 | 36.0% | feasible | - | - | - | - | name_the_problem | claude-sonnet-5-5 | True |
| 7 | Memoise full-label validation results in check_label keyed by label string | precompute_or_cache | idna/core.py\:476-478 | 24.8% | - | - | - | - | - | recombine | claude-sonnet-5-5 | False |
| 8 | Fast path in ulabel\: skip the redundant re-encode via a cache of alabel results | precompute_or_cache | idna/core.py\:605-608 | 50.7% | unknown | - | - | - | - | recombine | claude-sonnet-5-5 | True |
| 9 | Seed the ulabel cache from alabel during encode so decode skips punycode and validation | precompute_or_cache | idna/core.py\:549-550 | 36.0% | infeasible | Seed a reverse A-label to U-label cache in alabel so ulabel skips punycode decode, re-encode and check_label (X1-0) | - | - | - | recombine | claude-sonnet-5-5 | False |
| 10 | Cache uts46_remap results for non-ASCII domains and batch status lookups per run | precompute_or_cache | idna/core.py\:684-685 | 4.9% | unknown | - | - | - | - | recombine | claude-sonnet-5-5 | False |
| 11 | Skip separate contextj/contexto range tests by testing PVALID via a precomputed frozenset-free bytearray bitmap for BMP | representation | idna/core.py\:482-483 | 24.8% | - | - | - | - | - | resolve_tradeoff | claude-sonnet-5-5 | False |
| 12 | Replace per-char NFC/hyphen/bidi work for ASCII-LDH-free labels\: ASCII-only fast path in check_bidi entry | precompute_or_cache | idna/core.py\:190-192 | 3.4% | infeasible | Fuse the two bidi passes and cache bidirectional class lookups in check_bidi (X1-2) | - | - | - | resolve_tradeoff | claude-sonnet-5-5 | False |
| 13 | Memoise whole-label validation verdicts so repeated check_label calls on identical labels return immediately | precompute_or_cache | idna/core.py\:476-481 | 24.8% | - | - | - | - | - | far | claude-sonnet-5-5 | False |
| 14 | Validate whole label at C speed with a lazily compiled PVALID character-class regex in check_label | representation | idna/core.py\:480-483 | 24.8% | feasible | - | - | - | - | leap | claude-opus-5-5 | True |
| 15 | ASCII-label fast path in ulabel\: skip NFC/combiner/codepoint/bidi checks for lowercase LDH labels | specialised_fast_path | idna/core.py\:592-594 | 50.7% | - | - | - | - | - | leap | claude-opus-5-5 | False |

## Proposals (rule-relaxing, never scored or trialled)

| title | relaxes | lane | model | returned | rationale |
| --- | --- | --- | --- | --- | --- |
