# X1 ideas: idna, X1-4

Floor 2.0%; ceilings predicted from E1's profile.

These rows are the raw list behind unique mechanisms and the share new to today's generator (upper bound, the dedupe under-merges (O39)).

| # | title | mechanism | target lines | ceiling | audit | duplicate of | trial | gain / floor | op count | lane | model | returned |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Inline range decode/encode in intranges_contain to cut helper calls | remove_work | idna/intranges.py\:42-47 | 10.4% | - | - | - | - | - | obvious | claude-sonnet-5-5 | True |
| 2 | Cache PVALID membership per codepoint in check_label loop | precompute_or_cache | idna/core.py\:481-483 | 24.8% | - | - | - | - | - | obvious | claude-sonnet-5-5 | True |
| 3 | Skip unicodedata.bidirectional second pass for LTR-only labels in check_bidi | precompute_or_cache | idna/core.py\:224-228 | 3.4% | - | - | - | - | - | obvious | claude-sonnet-5-5 | True |

## Proposals (rule-relaxing, never scored or trialled)

| title | relaxes | lane | model | returned | rationale |
| --- | --- | --- | --- | --- | --- |
| Replace bisect-based intranges_contain with a C-backed interval lookup (intervaltree/pyroaring-style bitmap) for PVALID checks | new_dependency | relax_dependency | claude-sonnet-5-5 | False | - |
| Memoise per-label validation results across repeated labels in check_label | output_order | relax_output_order | claude-sonnet-5-5 | True | Keep a bounded module-level cache of labels that already passed check_label. When a str label is seen again, return at once without re-running NFC, hyphen, combiner, per-codepoint and bidi checks. On… |
| Fuse the two bidirectional passes and the PVALID loop in check_label/check_bidi via a per-codepoint class cache | output_order | relax_output_order | claude-sonnet-5-5 | True | Add a module-level dict mapping a codepoint to its bidi class, filled lazily on first use. check_bidi calls unicodedata.bidirectional once per distinct codepoint and uses the dict lookup afterwards. … |
| Build-time frozenset of PVALID codepoints for check_label per-codepoint validity test | install_precompute | relax_precompute | claude-sonnet-5-5 | True | Add to the generated idnadata module (produced at build/install time from the existing range tuples) a frozenset of every PVALID codepoint. In check_label, replace the per-codepoint PVALID bisect cal… |
| Precomputed bidi-class lookup table for check_bidi, built at install time | install_precompute | relax_precompute | claude-sonnet-5-5 | True | Generate at build time a compact table mapping codepoint to bidi category (or a precomputed flag for RTL-ness), matching the Unicode version that idna targets. In check_bidi, use it to detect RTL lab… |
| Skip redundant ulabel re-validation of ASCII labels in alabel via an internal flag parameter | api_change | relax_api | claude-sonnet-5-5 | True | alabel calls the public ulabel on pure-ASCII labels, which lowercases, then runs check_label on the bytes. Add an optional keyword-only parameter or private helper so alabel calls a validation-only p… |
