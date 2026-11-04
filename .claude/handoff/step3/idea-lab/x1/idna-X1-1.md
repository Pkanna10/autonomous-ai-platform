# X1 ideas: idna, X1-1

Floor 2.0%; ceilings predicted from E1's profile.

These rows are the raw list behind unique mechanisms and the share new to today's generator (upper bound, the dedupe under-merges (O39)).

| # | title | mechanism | target lines | ceiling | audit | duplicate of | trial | gain / floor | op count | lane | model | returned |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Inline range decode and encode in intranges_contain to drop helper calls | remove_work | idna/intranges.py\:42-47 | - | infeasible | Remove per-call range encode/decode in intranges_contain (A) | - | - | - | obvious | claude-sonnet-5-5 | True |
| 2 | Cache PVALID/CONTEXTJ/CONTEXTO tables in locals and add a per-codepoint PVALID memo in check_label | precompute_or_cache | idna/core.py\:481-483 | - | infeasible | Cache per-codepoint validity results in check_label to skip repeated intranges bisect (A) | - | - | - | obvious | claude-sonnet-5-5 | True |
| 3 | Single-pass bidi direction scan in check_bidi with cached direction list | remove_work | idna/core.py\:224-227 | - | infeasible | Fuse bidi direction scan\: skip full check for labels with only LTR characters (X1-0) | - | - | - | obvious | claude-sonnet-5-5 | True |
| 4 | Skip the per-codepoint PVALID scan in check_label for pure lowercase LDH labels (core.py check_label) | remove_work | idna/core.py\:482-482 | - | infeasible | ASCII fast path in check_label\: lowercase letters/digits/hyphen skip NFC, combiner, per-codepoint and bidi checks (X1-1) | - | - | - | eliminate | claude-haiku-5-5 | False |
| 5 | Cache per-codepoint UTS46 status lookups across calls (core.py uts46_remap) | data_structure | idna/core.py\:684-684 | - | infeasible | Speed up uts46_remap with a per-character mapping cache and a fast path for already-valid text (A) | - | - | - | eliminate | claude-haiku-5-5 | False |
| 6 | Memo A-label to U-label in alabel so ulabel skips punycode decode, re-encode and check_label | precompute_or_cache | idna/core.py\:605-608 | - | - | - | - | - | - | assume_less | claude-opus-5-5 | False |
| 7 | Bounded memo of labels that already passed check_label | precompute_or_cache | idna/core.py\:476-481 | - | - | - | - | - | - | assume_less | claude-opus-5-5 | False |
| 8 | LDH-only ASCII fast path in check_label skipping NFC, codepoint-class and bidi scans | specialised_fast_path | idna/core.py\:480-483 | - | - | - | - | - | - | assume_less | claude-opus-5-5 | False |
| 9 | Memoize successful check_label results across calls so decode does not revalidate labels encode already validated | precompute_or_cache | idna/core.py\:605-608 | - | feasible | - | - | - | - | name_the_problem | claude-fable-5 | True |
| 10 | Dense BMP class-index bytearray replacing bisect classification in check_label's per-codepoint loop | representation | idna/core.py\:480-483 | - | infeasible | Replace per-codepoint bisect in check_label with a lazily built dense bytes class table (X1-1) | - | - | - | name_the_problem | claude-fable-5 | False |
| 11 | Per-codepoint status/replacement memo dict in uts46_remap to replace repeated bisect lookups | precompute_or_cache | idna/core.py\:683-685 | - | infeasible | Speed up uts46_remap with a per-character mapping cache and a fast path for already-valid text (A) | - | - | - | name_the_problem | claude-fable-5 | False |
| 12 | Parallel starts/ends arrays for intranges so membership is one bisect with no big-int packing | data_structure | idna/intranges.py\:42-43 | - | - | - | - | - | - | name_the_problem | claude-fable-5 | False |
| 13 | Bounded cross-call memo for alabel and ulabel results to reuse Punycode work on repeated labels | precompute_or_cache | idna/core.py\:549-550 | - | - | - | - | - | - | name_the_problem | claude-fable-5 | False |
| 14 | Cross-call A-label&lt;-&gt;U-label cache shared by alabel and ulabel to skip re-validation on decode | precompute_or_cache | idna/core.py\:605-608 | - | - | - | - | - | - | recombine | claude-fable-5-1 | False |
| 15 | ASCII fast path in check_label\: lowercase letters/digits/hyphen skip NFC, combiner, per-codepoint and bidi checks | specialised_fast_path | idna/core.py\:476-478 | - | feasible | - | - | - | - | recombine | claude-fable-5-1 | True |
| 16 | Replace per-codepoint bisect in check_label with a lazily built dense bytes class table | data_structure | idna/core.py\:481-483 | - | feasible | - | - | - | - | recombine | claude-fable-5-1 | False |
| 17 | check_bidi early exit via a cross-call memo of known non-RTL characters applied with str.translate | precompute_or_cache | idna/core.py\:189-192 | - | - | - | - | - | - | recombine | claude-fable-5-1 | False |
| 18 | uts46_remap\: translate-based whole-domain skip using a cross-call set of known valid/deviation characters | specialised_fast_path | idna/core.py\:684-685 | - | - | - | - | - | - | recombine | claude-fable-5-1 | False |
| 19 | Memoise whole-label validation outcomes in check_label for labels already validated | precompute_or_cache | idna/core.py\:476-478 | - | - | - | - | - | - | resolve_tradeoff | claude-sonnet-5-5 | False |
| 20 | Skip the punycode re-encode check by caching alabel results for decoded labels | precompute_or_cache | idna/core.py\:605-608 | - | - | - | - | - | - | resolve_tradeoff | claude-sonnet-5-5 | False |
| 21 | Precompute dense codepoint-class array for check_label's PVALID/CONTEXTJ/CONTEXTO test | precompute_or_cache | idna/core.py\:482-484 | - | - | - | - | - | - | far | claude-sonnet-5 | False |
| 22 | Replace uts46_remap's per-character bisect with a dense status array indexed by codepoint | precompute_or_cache | idna/core.py\:682-685 | - | unknown | - | - | - | - | far | claude-sonnet-5 | True |
| 23 | Precompute an ASCII bidirectional-category table to skip unicodedata.bidirectional calls in check_bidi | precompute_or_cache | idna/core.py\:190-192 | - | - | - | - | - | - | far | claude-sonnet-5 | False |
| 24 | Remember A-label to U-label pairs produced by alabel so ulabel skips punycode decode, re-encode and check_label | precompute_or_cache | idna/core.py\:605-608 | - | - | - | - | - | - | leap | claude-opus-5-5 | False |
| 25 | Validate whole label against a compiled PVALID character-class regex in C before the per-codepoint loop in check_label | specialised_fast_path | idna/core.py\:480-483 | - | - | - | - | - | - | leap | claude-opus-5-5 | False |

## Proposals (rule-relaxing, never scored or trialled)

| title | relaxes | lane | model | returned | rationale |
| --- | --- | --- | --- | --- | --- |
