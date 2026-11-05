# X1 ideas: idna, X1-0

Floor 2.0%; ceilings predicted from E1's profile.

These rows are the raw list behind unique mechanisms and the share new to today's generator (upper bound, the dedupe under-merges (O39)).

| # | title | mechanism | target lines | ceiling | audit | duplicate of | trial | gain / floor | op count | lane | model | returned |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Inline range decoding in intranges_contain to avoid two helper calls per codepoint | remove_work | idna/intranges.py\:42-47 | 10.4% | infeasible | Remove per-call range encode/decode in intranges_contain (A) | - | - | - | obvious | claude-sonnet-5-5 | True |
| 2 | Hoist codepoint_classes lookups and cache per-codepoint PVALID results in check_label | precompute_or_cache | idna/core.py\:482-483 | 24.8% | infeasible | Cache per-codepoint validity results in check_label to skip repeated intranges bisect (A) | - | - | - | obvious | claude-sonnet-5-5 | True |
| 3 | Fuse bidi direction scan\: skip full check for labels with only LTR characters | precompute_or_cache | idna/core.py\:224-227 | 3.4% | feasible | - | - | - | - | obvious | claude-sonnet-5-5 | True |
| 4 | Skip the ASCII-label ulabel round trip in alabel by validating once | remove_work | idna/core.py\:544-545 | 36.0% | infeasible | Skip the ASCII re-encode and re-check in alabel by running check_label directly on the ASCII str (X1-2) | - | - | - | eliminate | claude-sonnet-5-5 | False |
| 5 | Skip decode/re-encode duplicate work\: ASCII-encode check in alabel avoids ulabel on already validated label | remove_work | idna/core.py\:575-579 | 50.7% | - | - | - | - | - | assume_less | claude-sonnet-5-5 | False |
| 6 | Replace encode try/except in alabel with isascii test | remove_work | idna/core.py\:539-544 | 36.0% | - | - | - | - | - | assume_less | claude-sonnet-5-5 | False |
| 7 | Single-pass bidirectional lookup in check_bidi | precompute_or_cache | idna/core.py\:190-192 | 3.4% | infeasible | Fuse bidi direction scan\: skip full check for labels with only LTR characters (X1-0) | - | - | - | assume_less | claude-sonnet-5-5 | False |
| 8 | Memoize per-codepoint PVALID membership with a lazily filled dict in check_label | precompute_or_cache | idna/core.py\:481-483 | 24.8% | - | - | - | - | - | name_the_problem | claude-sonnet-5-5 | False |
| 9 | Skip ASCII-only labels in check_bidi by using str.isascii and a precomputed ASCII path | specialised_fast_path | idna/core.py\:189-191 | 3.4% | feasible | - | - | - | - | name_the_problem | claude-sonnet-5-5 | True |
| 10 | Memoize per-codepoint PVALID class as a lazily filled dict across check_label calls | precompute_or_cache | idna/core.py\:481-483 | 24.8% | infeasible | Cache per-codepoint validity results in check_label to skip repeated intranges bisect (A) | - | - | - | recombine | claude-sonnet-5-5 | False |
| 11 | Cache whole-label validation results in check_label for repeated labels | precompute_or_cache | idna/core.py\:476-478 | 24.8% | - | - | - | - | - | recombine | claude-sonnet-5-5 | False |
| 12 | Replace bisect-based uts46 lookup for BMP with a lazily built per-codepoint dict cache | precompute_or_cache | idna/core.py\:684-684 | 4.9% | infeasible | Speed up uts46_remap with a per-character mapping cache and a fast path for already-valid text (A) | - | - | - | recombine | claude-sonnet-5-5 | True |
| 13 | Cache bidi direction per codepoint and fuse the two scans in check_bidi | loop_or_control_flow | idna/core.py\:190-192 | 3.4% | infeasible | Fuse bidi direction scan\: skip full check for labels with only LTR characters (X1-0) | - | - | - | recombine | claude-sonnet-5-5 | False |
| 14 | Memoize per-codepoint PVALID classification in a dict shared across check_label calls | precompute_or_cache | idna/core.py\:482-483 | 24.8% | - | - | - | - | - | resolve_tradeoff | claude-sonnet-5-5 | False |
| 15 | Per-codepoint bidi direction cache and single-pass bidi scan in check_bidi | precompute_or_cache | idna/core.py\:190-192 | 3.4% | infeasible | Fuse the two bidi passes and cache bidirectional class lookups in check_bidi (X1-2) | - | - | - | resolve_tradeoff | claude-sonnet-5-5 | False |
| 16 | Memoize per-label check_label verdicts for labels already validated successfully | precompute_or_cache | idna/core.py\:476-478 | 24.8% | - | - | - | - | - | far | claude-sonnet-5-5 | False |
| 17 | Cache intranges_contain answers per codepoint and table in a dict | precompute_or_cache | idna/intranges.py\:42-43 | 10.4% | - | - | - | - | - | far | claude-sonnet-5-5 | False |
| 18 | Memoize per-codepoint bidi direction lookups via a dict in check_bidi | precompute_or_cache | idna/core.py\:190-192 | 3.4% | - | - | - | - | - | far | claude-sonnet-5-5 | False |
| 19 | Skip the punycode re-encode round trip in ulabel via encode-side cache of A-label to U-label | precompute_or_cache | idna/core.py\:605-607 | 50.7% | infeasible | Seed a reverse A-label to U-label cache in alabel so ulabel skips punycode decode, re-encode and check_label (X1-0) | - | - | - | far | claude-sonnet-5-5 | False |
| 20 | Seed a reverse A-label to U-label cache in alabel so ulabel skips punycode decode, re-encode and check_label | precompute_or_cache | idna/core.py\:605-608 | 50.7% | feasible | - | - | - | - | leap | claude-opus-5-5 | True |
| 21 | Validate whole label against a lazily compiled PVALID regex character class before the per-codepoint loop | representation | idna/core.py\:480-483 | 24.8% | infeasible | Validate whole label at C speed with a lazily compiled PVALID character-class regex in check_label (X1-2) | - | - | - | leap | claude-opus-5-5 | False |
| 22 | Memoise labels that already passed check_label so repeated validation of the same label string is skipped | precompute_or_cache | idna/core.py\:476-478 | 24.8% | - | - | - | - | - | leap | claude-opus-5-5 | False |

## Proposals (rule-relaxing, never scored or trialled)

| title | relaxes | lane | model | returned | rationale |
| --- | --- | --- | --- | --- | --- |
