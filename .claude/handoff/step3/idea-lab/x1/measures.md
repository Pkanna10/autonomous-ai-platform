# X1 idea measures (spec-idea-lab 6.2)

Sources (O44): more_itertools: X1-1's probe, idea and reply rows from x1-1-rerun.jsonl; every audit-based figure (share-new, self/cross, good counts, auditor-feasible) from ideas-reaudit-41772132719.jsonl; the rest from ideas-probe-x1-run1-41679255224.jsonl; pyparsing: X1-1's probe, idea and reply rows from x1-1-rerun.jsonl; every audit-based figure (share-new, self/cross, good counts, auditor-feasible) from ideas-reaudit-41772132719.jsonl; the rest from ideas-probe-x1-run1-41679255224.jsonl; tomli: X1-1's probe, idea and reply rows from x1-1-rerun.jsonl; every audit-based figure (share-new, self/cross, good counts, auditor-feasible) from ideas-reaudit-41772132719.jsonl; the rest from ideas-probe-x1-run1-41679255224.jsonl; sortedcontainers: X1-1's probe, idea and reply rows from x1-1-rerun.jsonl; every audit-based figure (share-new, self/cross, good counts, auditor-feasible) from ideas-reaudit-41772132719.jsonl; the rest from ideas-probe-x1-run1-41679255224.jsonl; mistune: ideas-probe-x1-run2a-41773968543.jsonl; sqlparse: ideas-probe-x1-run2a-41773968543.jsonl; markdown: ideas-probe-x1-run2a-41773968543.jsonl; idna: ideas-probe-x1-run2b-41780421911.jsonl

| dedupe (G4) | verdict |
| --- | --- |
| Vc's validation | not passed\: agreement 78.9% is under 90% |

Vc's 380 labelled pairs are the dedupe's development set for a fix before X2 (O39); X1 is not held for it.

Ideas: each configuration's result (returned, not a proposal: ideas-probe's and the slice's population); lane ideas: every lane-reply idea, its reviewers' removals included; audited: reviewed audits with in_result. Only auditor-feasible has an A/A band (tables.md, Table 4); unique, new, ceilings and families have no A/A band offline, so a ranking on them is provisional (6.3).

| configuration | ideas proposed | lane ideas | unique mechanisms (upper bound, the dedupe under-merges (O39)) | raw titles | new to today's generator (upper bound, the dedupe under-merges (O39)) | ceiling at least 10 points over the floor (of known) | mechanism families | auditor-feasible (of audited) | USD |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A | 39 | 39 | 39 | 39 | - | 0/0 | 0 | 37/39 | 0.2049 |
| X1-0 | 51 | 187 | 51 | 51 | 31/49 | 18/37 | 7 | 26/49 | 5.2029 |
| X1-1 | 63 | 201 | 62 | 63 | 42/59 | 25/45 | 8 | 32/59 | 21.5962 |
| X1-2 | 56 | 162 | 56 | 56 | 32/50 | 27/40 | 8 | 15/50 | 5.0823 |
| X1-3 | 53 | 130 | 53 | 53 | 32/50 | 21/42 | 7 | 19/50 | 5.3761 |
| X1-4 | 30 | 30 | 30 | 30 | 0/0 | 9/18 | 6 | 0/0 | 1.0886 |

## X1-4 proposals by rule relaxed (no score)

| rule | proposals |
| --- | --- |
| api_change | 16 |
| install_precompute | 15 |
| new_dependency | 10 |
| output_order | 8 |

## Cost per configuration

Ideas USD excludes the pooled auditor (its own line per library); the slice's USD is its engine runs', D64's seeded calls included.

| configuration | ideas USD | slice USD | seeded calls | seeded USD | wins | slice USD per win |
| --- | --- | --- | --- | --- | --- | --- |
| A | 0.2049 | 0.0000 | 0 | 0.0000 | 0 | - |
| X1-0 | 5.2029 | 1.2899 | 0 | 0.0000 | 2 | 0.6450 |
| X1-1 | 21.5962 | 1.7188 | 0 | 0.0000 | 3 | 0.5729 |
| X1-2 | 5.0823 | 1.6355 | 0 | 0.0000 | 1 | 1.6355 |
| X1-3 | 5.3761 | 1.8328 | 0 | 0.0000 | 3 | 0.6109 |
| X1-4 | 1.0886 | 0.0000 | 0 | 0.0000 | 0 | - |

## Slice wins by lane (O47)

Each kept ideas-slice-trial row counted once, under the lane that produced it (its idea row's lane: X1-2's sequential labels, leap-2 and lane-8 to lane-12, read through it). A configuration's win count credits a leap or S1 win to its lever; this table does not.

| configuration | leap | S1 (obvious) | lens lanes | wins |
| --- | --- | --- | --- | --- |
| X1-0 | 1 | 1 | 0 | 2 |
| X1-1 | 2 | 0 | 1 (eliminate) | 3 |
| X1-2 | 1 | 0 | 0 | 1 |
| X1-3 | 1 | 1 | 1 (far) | 3 |
| all configurations | 5 | 2 | 2 (far, eliminate) | 9 |

| library | configuration | group | lane | label | model | gain / floor |
| --- | --- | --- | --- | --- | --- | --- |
| sqlparse | X1-1 | leap | leap | leap | claude-opus-5-5 | 14.57% / 6.16% |
| tomli | X1-1 | leap | leap | leap | claude-opus-5-5 | 9.93% / 2.28% |
| tomli | X1-0 | leap | leap | leap | claude-opus-5-5 | 9.89% / 3.23% |
| tomli | X1-2 | leap | leap | leap-2 | claude-opus-5-5 | 6.97% / 3.32% |
| pyparsing | X1-3 | leap | leap | leap | claude-opus-5-5 | 4.40% / 3.01% |
| sqlparse | X1-3 | S1 (obvious) | obvious | obvious | claude-sonnet-5-5 | 3.60% / 2.00% |
| sqlparse | X1-0 | S1 (obvious) | obvious | obvious | claude-sonnet-5-5 | 3.38% / 2.62% |
| sqlparse | X1-3 | lens lanes | far | far | claude-sonnet-5-5 | 9.52% / 2.00% |
| pyparsing | X1-1 | lens lanes | eliminate | eliminate | claude-haiku-5-5 | 3.54% / 3.53% |

## Marker-feasible ideas (6.2, O40, O41)

Per library, every configuration's lens-lane ideas (X1-0 to X1-3, their results; never S1, the leap or the rule-relaxing lanes) form one pool, ranked by a tournament, not one ranking of the whole pool (O41): in sorted idea-id order (an id hashed from the idea's row, carrying no configuration, lane or model) the pool is split into ceil(n/6) sets as equal as possible; each set is ranked in one blind request (titles, class and the library's hot code, shown in an order shuffled by a recorded seed); the top 2 of each set advance, round after round, until the advancing ideas fit one set, whose ranking gives the top 3. Every request showed 4 to 6 ideas, at most 6: the set size the marker was validated on (Vb's 48 scored sets: 3 to 8 ideas, 4.6 on average). The count is how many of that top 3 each configuration supplied (O40). The validated marker (Vb's verdict) never ranks its own model's ideas (O39): those are listed apart, not ranked. The other candidate ranks the whole pool, its counts marked unvalidated (opus-5 failed O37), so X1-1 has a comparable number.

| library | ranked by | X1-0 | X1-1 | X1-2 | X1-3 | pooled | not ranked (the marker's own model) | requests | rounds |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| idna | opus-5-5 (validated) | 0 | 2 | 0 | 1 | 10 | 0 | 3 | 2 |
| idna | opus-5 (unvalidated) | 0 unvalidated | 1 unvalidated | 1 unvalidated | 1 unvalidated | 10 | 0 | 3 | 2 |
| markdown | opus-5-5 (validated) | 2 | 0 | 0 | 1 | 11 | 0 | 3 | 2 |
| markdown | opus-5 (unvalidated) | 1 unvalidated | 1 unvalidated | 0 unvalidated | 1 unvalidated | 11 | 0 | 3 | 2 |
| mistune | opus-5-5 (validated) | 1 | 1 | 0 | 1 | 12 | 0 | 3 | 2 |
| mistune | opus-5 (unvalidated) | 1 unvalidated | 1 unvalidated | 0 unvalidated | 1 unvalidated | 12 | 0 | 3 | 2 |
| more_itertools | opus-5-5 (validated) | 0 | 3 | 0 | 0 | 11 | 1 | 3 | 2 |
| more_itertools | opus-5 (unvalidated) | 0 unvalidated | 2 unvalidated | 0 unvalidated | 1 unvalidated | 12 | 0 | 3 | 2 |
| pyparsing | opus-5-5 (validated) | 1 | 2 | 0 | 0 | 12 | 0 | 3 | 2 |
| pyparsing | opus-5 (unvalidated) | 1 unvalidated | 2 unvalidated | 0 unvalidated | 0 unvalidated | 12 | 0 | 3 | 2 |
| sortedcontainers | opus-5-5 (validated) | 0 | 0 | 1 | 2 | 9 | 0 | 3 | 2 |
| sortedcontainers | opus-5 (unvalidated) | 0 unvalidated | 0 unvalidated | 1 unvalidated | 2 unvalidated | 9 | 0 | 3 | 2 |
| sqlparse | opus-5-5 (validated) | 0 | 0 | 1 | 2 | 11 | 0 | 3 | 2 |
| sqlparse | opus-5 (unvalidated) | 1 unvalidated | 1 unvalidated | 0 unvalidated | 1 unvalidated | 11 | 0 | 3 | 2 |
| tomli | opus-5-5 (validated) | 2 | 0 | 0 | 1 | 10 | 0 | 3 | 2 |
| tomli | opus-5 (unvalidated) | 1 unvalidated | 0 unvalidated | 1 unvalidated | 1 unvalidated | 10 | 0 | 3 | 2 |
| all libraries | opus-5-5 (validated) | 6 | 8 | 2 | 8 | 86 | 1 | 24 | 2 |
| all libraries | opus-5 (unvalidated) | 5 unvalidated | 8 unvalidated | 3 unvalidated | 8 unvalidated | 87 | 0 | 24 | 2 |

### idna

#### Ranked by opus-5-5 (claude-opus-5-5), validated: 10 ideas, 3 requests in 2 rounds

| rank | id | title | configuration | lane | model |
| --- | --- | --- | --- | --- | --- |
| 1 | p6cc034bc50a7 | Hoist PVALID range table lookup and use a per-codepoint class memo in check_label | X1-3 | name_the_problem | claude-sonnet-5-5 |
| 2 | p7f9cbaa79fb6 | ASCII fast path in check_label\: lowercase letters/digits/hyphen skip NFC, combiner, per-codepoint and bidi checks | X1-1 | recombine | claude-fable-5-1 |
| 3 | p8204f867b182 | Memoize successful check_label results across calls so decode does not revalidate labels encode already validated | X1-1 | name_the_problem | claude-fable-5 |

Every set (ids in the order shown; the marker's order, most likely first):

| round | set | shown | seed | the marker's order | advanced |
| --- | --- | --- | --- | --- | --- |
| 1 | 1 | p3cc306ee36f7, p2e46e6ac64f2, p70b8e2b736ad, p6e8e6a64a456, p6cc034bc50a7 | 20261103\:idna\:1\:opus-5-5-r1-s1 | p6cc034bc50a7, p6e8e6a64a456, p3cc306ee36f7, p70b8e2b736ad, p2e46e6ac64f2 | p6cc034bc50a7, p6e8e6a64a456 |
| 1 | 2 | p8204f867b182, p997d0163560a, pc68f1ff34eff, pfa8f4880de9e, p7f9cbaa79fb6 | 20261103\:idna\:1\:opus-5-5-r1-s2 | p8204f867b182, p7f9cbaa79fb6, p997d0163560a, pfa8f4880de9e, pc68f1ff34eff | p8204f867b182, p7f9cbaa79fb6 |
| 2 | 1 | p6e8e6a64a456, p8204f867b182, p6cc034bc50a7, p7f9cbaa79fb6 | 20261103\:idna\:1\:opus-5-5-r2-s1 | p6cc034bc50a7, p7f9cbaa79fb6, p8204f867b182, p6e8e6a64a456 | final, the top 3 |

The pool:

| id | title | configuration | lane | model |
| --- | --- | --- | --- | --- |
| p2e46e6ac64f2 | Skip the ASCII re-encode and re-check in alabel by running check_label directly on the ASCII str | X1-2 | name_the_problem | claude-sonnet-5-5 |
| p3cc306ee36f7 | Fuse check_bidi's two bidirectional passes into one by caching per-label direction list | X1-3 | recombine | claude-sonnet-5-5 |
| p6cc034bc50a7 | Hoist PVALID range table lookup and use a per-codepoint class memo in check_label | X1-3 | name_the_problem | claude-sonnet-5-5 |
| p6e8e6a64a456 | Skip ASCII-only labels in check_bidi by using str.isascii and a precomputed ASCII path | X1-0 | name_the_problem | claude-sonnet-5-5 |
| p70b8e2b736ad | Fast path in ulabel\: skip the redundant re-encode via a cache of alabel results | X1-2 | recombine | claude-sonnet-5-5 |
| p7f9cbaa79fb6 | ASCII fast path in check_label\: lowercase letters/digits/hyphen skip NFC, combiner, per-codepoint and bidi checks | X1-1 | recombine | claude-fable-5-1 |
| p8204f867b182 | Memoize successful check_label results across calls so decode does not revalidate labels encode already validated | X1-1 | name_the_problem | claude-fable-5 |
| p997d0163560a | Memoise intranges_contain results per (codepoint, table) with a dict cache | X1-3 | resolve_tradeoff | claude-sonnet-5-5 |
| pc68f1ff34eff | Replace bisect-based uts46 lookup for BMP with a lazily built per-codepoint dict cache | X1-0 | recombine | claude-sonnet-5-5 |
| pfa8f4880de9e | Replace uts46_remap's per-character bisect with a dense status array indexed by codepoint | X1-1 | far | claude-sonnet-5 |

Not ranked (written by claude-opus-5-5, the marker's own model):

none

#### Ranked by opus-5 (claude-opus-5), unvalidated: 10 ideas, 3 requests in 2 rounds

| rank | id | title | configuration | lane | model |
| --- | --- | --- | --- | --- | --- |
| 1 | p7f9cbaa79fb6 | ASCII fast path in check_label\: lowercase letters/digits/hyphen skip NFC, combiner, per-codepoint and bidi checks | X1-1 | recombine | claude-fable-5-1 |
| 2 | p6cc034bc50a7 | Hoist PVALID range table lookup and use a per-codepoint class memo in check_label | X1-3 | name_the_problem | claude-sonnet-5-5 |
| 3 | p70b8e2b736ad | Fast path in ulabel\: skip the redundant re-encode via a cache of alabel results | X1-2 | recombine | claude-sonnet-5-5 |

Every set (ids in the order shown; the marker's order, most likely first):

| round | set | shown | seed | the marker's order | advanced |
| --- | --- | --- | --- | --- | --- |
| 1 | 1 | p6cc034bc50a7, p3cc306ee36f7, p2e46e6ac64f2, p6e8e6a64a456, p70b8e2b736ad | 20261103\:idna\:1\:opus-5-r1-s1 | p6cc034bc50a7, p70b8e2b736ad, p6e8e6a64a456, p3cc306ee36f7, p2e46e6ac64f2 | p6cc034bc50a7, p70b8e2b736ad |
| 1 | 2 | p997d0163560a, pc68f1ff34eff, p7f9cbaa79fb6, pfa8f4880de9e, p8204f867b182 | 20261103\:idna\:1\:opus-5-r1-s2 | p7f9cbaa79fb6, p8204f867b182, p997d0163560a, pc68f1ff34eff, pfa8f4880de9e | p7f9cbaa79fb6, p8204f867b182 |
| 2 | 1 | p6cc034bc50a7, p8204f867b182, p7f9cbaa79fb6, p70b8e2b736ad | 20261103\:idna\:1\:opus-5-r2-s1 | p7f9cbaa79fb6, p6cc034bc50a7, p70b8e2b736ad, p8204f867b182 | final, the top 3 |

The pool:

| id | title | configuration | lane | model |
| --- | --- | --- | --- | --- |
| p2e46e6ac64f2 | Skip the ASCII re-encode and re-check in alabel by running check_label directly on the ASCII str | X1-2 | name_the_problem | claude-sonnet-5-5 |
| p3cc306ee36f7 | Fuse check_bidi's two bidirectional passes into one by caching per-label direction list | X1-3 | recombine | claude-sonnet-5-5 |
| p6cc034bc50a7 | Hoist PVALID range table lookup and use a per-codepoint class memo in check_label | X1-3 | name_the_problem | claude-sonnet-5-5 |
| p6e8e6a64a456 | Skip ASCII-only labels in check_bidi by using str.isascii and a precomputed ASCII path | X1-0 | name_the_problem | claude-sonnet-5-5 |
| p70b8e2b736ad | Fast path in ulabel\: skip the redundant re-encode via a cache of alabel results | X1-2 | recombine | claude-sonnet-5-5 |
| p7f9cbaa79fb6 | ASCII fast path in check_label\: lowercase letters/digits/hyphen skip NFC, combiner, per-codepoint and bidi checks | X1-1 | recombine | claude-fable-5-1 |
| p8204f867b182 | Memoize successful check_label results across calls so decode does not revalidate labels encode already validated | X1-1 | name_the_problem | claude-fable-5 |
| p997d0163560a | Memoise intranges_contain results per (codepoint, table) with a dict cache | X1-3 | resolve_tradeoff | claude-sonnet-5-5 |
| pc68f1ff34eff | Replace bisect-based uts46 lookup for BMP with a lazily built per-codepoint dict cache | X1-0 | recombine | claude-sonnet-5-5 |
| pfa8f4880de9e | Replace uts46_remap's per-character bisect with a dense status array indexed by codepoint | X1-1 | far | claude-sonnet-5 |

Not ranked (written by claude-opus-5, the marker's own model):

none


### markdown

#### Ranked by opus-5-5 (claude-opus-5-5), validated: 11 ideas, 3 requests in 2 rounds

| rank | id | title | configuration | lane | model |
| --- | --- | --- | --- | --- | --- |
| 1 | p1b0cf0f8740e | Skip quick no-match patterns in __handleInline using cheap substring prefilter | X1-0 | assume_less | claude-sonnet-5-5 |
| 2 | p5ba9ae5ea5e0 | Cache sorted pattern list in Registry so __getitem__ skips _sort and isinstance checks on int keys | X1-0 | far | claude-sonnet-5-5 |
| 3 | pb40bb38566f4 | Skip Registry._sort check cost in __getitem__ by fast-pathing int keys on a sorted registry | X1-3 | resolve_tradeoff | claude-sonnet-5-5 |

Every set (ids in the order shown; the marker's order, most likely first):

| round | set | shown | seed | the marker's order | advanced |
| --- | --- | --- | --- | --- | --- |
| 1 | 1 | p5ba9ae5ea5e0, p2e3a25884355, p8e7d7be00bbb, p1b0cf0f8740e, p34c85643c6fa, p61f94cdcacb9 | 20261103\:markdown\:1\:opus-5-5-r1-s1 | p1b0cf0f8740e, p5ba9ae5ea5e0, p34c85643c6fa, p8e7d7be00bbb, p61f94cdcacb9, p2e3a25884355 | p1b0cf0f8740e, p5ba9ae5ea5e0 |
| 1 | 2 | p97cd62a6e87e, pb40bb38566f4, pe1065209acdc, pbbe27544018e, pcaa2e1c085e8 | 20261103\:markdown\:1\:opus-5-5-r1-s2 | pb40bb38566f4, pbbe27544018e, pe1065209acdc, p97cd62a6e87e, pcaa2e1c085e8 | pb40bb38566f4, pbbe27544018e |
| 2 | 1 | p5ba9ae5ea5e0, p1b0cf0f8740e, pbbe27544018e, pb40bb38566f4 | 20261103\:markdown\:1\:opus-5-5-r2-s1 | p1b0cf0f8740e, p5ba9ae5ea5e0, pb40bb38566f4, pbbe27544018e | final, the top 3 |

The pool:

| id | title | configuration | lane | model |
| --- | --- | --- | --- | --- |
| p1b0cf0f8740e | Skip quick no-match patterns in __handleInline using cheap substring prefilter | X1-0 | assume_less | claude-sonnet-5-5 |
| p2e3a25884355 | Replace list(node).index(child) lookups in InlineProcessor.run tail handling with an enumerated position | X1-0 | name_the_problem | claude-sonnet-5-5 |
| p34c85643c6fa | Registry keeps a materialised sorted item list so __getitem__ by index and __iter__ are a single list access | X1-1 | resolve_tradeoff | claude-fable-5-1 |
| p5ba9ae5ea5e0 | Cache sorted pattern list in Registry so __getitem__ skips _sort and isinstance checks on int keys | X1-0 | far | claude-sonnet-5-5 |
| p61f94cdcacb9 | Skip per-child list(currElement).index scan for tails in InlineProcessor.run | X1-2 | resolve_tradeoff | claude-sonnet-5-5 |
| p8e7d7be00bbb | Skip ancestor-exclude scan in __applyPattern for patterns with no excludes | X1-3 | assume_less | claude-sonnet-5-5 |
| p97cd62a6e87e | Drop the per-node parent_map walk in InlineProcessor.run by carrying the ancestor chain down the work stack | X1-1 | assume_less | claude-haiku-5-5 |
| pb40bb38566f4 | Skip Registry._sort check cost in __getitem__ by fast-pathing int keys on a sorted registry | X1-3 | resolve_tradeoff | claude-sonnet-5-5 |
| pbbe27544018e | Skip child/tail reprocessing loops in __applyPattern for nodes with no children, text or tail | X1-2 | eliminate | claude-sonnet-5-5 |
| pcaa2e1c085e8 | Cache lowercased tag names to avoid repeated str.lower in ancestors building and serializer | X1-1 | far | claude-sonnet-5-5 |
| pe1065209acdc | Skip placeholder scanning for text that contains no placeholder prefix in __processPlaceholders | X1-2 | assume_less | claude-sonnet-5-5 |

Not ranked (written by claude-opus-5-5, the marker's own model):

none

#### Ranked by opus-5 (claude-opus-5), unvalidated: 11 ideas, 3 requests in 2 rounds

| rank | id | title | configuration | lane | model |
| --- | --- | --- | --- | --- | --- |
| 1 | p34c85643c6fa | Registry keeps a materialised sorted item list so __getitem__ by index and __iter__ are a single list access | X1-1 | resolve_tradeoff | claude-fable-5-1 |
| 2 | p5ba9ae5ea5e0 | Cache sorted pattern list in Registry so __getitem__ skips _sort and isinstance checks on int keys | X1-0 | far | claude-sonnet-5-5 |
| 3 | pb40bb38566f4 | Skip Registry._sort check cost in __getitem__ by fast-pathing int keys on a sorted registry | X1-3 | resolve_tradeoff | claude-sonnet-5-5 |

Every set (ids in the order shown; the marker's order, most likely first):

| round | set | shown | seed | the marker's order | advanced |
| --- | --- | --- | --- | --- | --- |
| 1 | 1 | p34c85643c6fa, p61f94cdcacb9, p5ba9ae5ea5e0, p1b0cf0f8740e, p8e7d7be00bbb, p2e3a25884355 | 20261103\:markdown\:1\:opus-5-r1-s1 | p5ba9ae5ea5e0, p34c85643c6fa, p1b0cf0f8740e, p8e7d7be00bbb, p2e3a25884355, p61f94cdcacb9 | p5ba9ae5ea5e0, p34c85643c6fa |
| 1 | 2 | pe1065209acdc, pb40bb38566f4, pcaa2e1c085e8, p97cd62a6e87e, pbbe27544018e | 20261103\:markdown\:1\:opus-5-r1-s2 | pb40bb38566f4, pbbe27544018e, pe1065209acdc, pcaa2e1c085e8, p97cd62a6e87e | pb40bb38566f4, pbbe27544018e |
| 2 | 1 | p5ba9ae5ea5e0, pbbe27544018e, p34c85643c6fa, pb40bb38566f4 | 20261103\:markdown\:1\:opus-5-r2-s1 | p34c85643c6fa, p5ba9ae5ea5e0, pb40bb38566f4, pbbe27544018e | final, the top 3 |

The pool:

| id | title | configuration | lane | model |
| --- | --- | --- | --- | --- |
| p1b0cf0f8740e | Skip quick no-match patterns in __handleInline using cheap substring prefilter | X1-0 | assume_less | claude-sonnet-5-5 |
| p2e3a25884355 | Replace list(node).index(child) lookups in InlineProcessor.run tail handling with an enumerated position | X1-0 | name_the_problem | claude-sonnet-5-5 |
| p34c85643c6fa | Registry keeps a materialised sorted item list so __getitem__ by index and __iter__ are a single list access | X1-1 | resolve_tradeoff | claude-fable-5-1 |
| p5ba9ae5ea5e0 | Cache sorted pattern list in Registry so __getitem__ skips _sort and isinstance checks on int keys | X1-0 | far | claude-sonnet-5-5 |
| p61f94cdcacb9 | Skip per-child list(currElement).index scan for tails in InlineProcessor.run | X1-2 | resolve_tradeoff | claude-sonnet-5-5 |
| p8e7d7be00bbb | Skip ancestor-exclude scan in __applyPattern for patterns with no excludes | X1-3 | assume_less | claude-sonnet-5-5 |
| p97cd62a6e87e | Drop the per-node parent_map walk in InlineProcessor.run by carrying the ancestor chain down the work stack | X1-1 | assume_less | claude-haiku-5-5 |
| pb40bb38566f4 | Skip Registry._sort check cost in __getitem__ by fast-pathing int keys on a sorted registry | X1-3 | resolve_tradeoff | claude-sonnet-5-5 |
| pbbe27544018e | Skip child/tail reprocessing loops in __applyPattern for nodes with no children, text or tail | X1-2 | eliminate | claude-sonnet-5-5 |
| pcaa2e1c085e8 | Cache lowercased tag names to avoid repeated str.lower in ancestors building and serializer | X1-1 | far | claude-sonnet-5-5 |
| pe1065209acdc | Skip placeholder scanning for text that contains no placeholder prefix in __processPlaceholders | X1-2 | assume_less | claude-sonnet-5-5 |

Not ranked (written by claude-opus-5, the marker's own model):

none


### mistune

#### Ranked by opus-5-5 (claude-opus-5-5), validated: 12 ideas, 3 requests in 2 rounds

| rank | id | title | configuration | lane | model |
| --- | --- | --- | --- | --- | --- |
| 1 | p2b4bbf802dd8 | Skip _split_text_token character scanning for text tokens without emphasis markers | X1-0 | eliminate | claude-sonnet-5-5 |
| 2 | p1b6c41a6c96a | Replace backward opener scan in _process_emphasis_delimiters with per-key opener stacks | X1-1 | name_the_problem | claude-sonnet-5 |
| 3 | ped36104bf1eb | Skip per-call compile_sc lookup and finalize work for pure-text inline strings | X1-3 | eliminate | claude-sonnet-5-5 |

Every set (ids in the order shown; the marker's order, most likely first):

| round | set | shown | seed | the marker's order | advanced |
| --- | --- | --- | --- | --- | --- |
| 1 | 1 | p2ca480dd852f, p0b85ce9d39a5, p2b4bbf802dd8, p514fdb43dea3, p1b6c41a6c96a, p349dd5d1544b | 20261103\:mistune\:1\:opus-5-5-r1-s1 | p2b4bbf802dd8, p1b6c41a6c96a, p514fdb43dea3, p2ca480dd852f, p0b85ce9d39a5, p349dd5d1544b | p2b4bbf802dd8, p1b6c41a6c96a |
| 1 | 2 | p9dcd74acbbff, pf931c09d3301, pb336f7684533, pee1aeccfa875, ped36104bf1eb, pe935740208b7 | 20261103\:mistune\:1\:opus-5-5-r1-s2 | ped36104bf1eb, pee1aeccfa875, p9dcd74acbbff, pf931c09d3301, pe935740208b7, pb336f7684533 | ped36104bf1eb, pee1aeccfa875 |
| 2 | 1 | p1b6c41a6c96a, ped36104bf1eb, p2b4bbf802dd8, pee1aeccfa875 | 20261103\:mistune\:1\:opus-5-5-r2-s1 | p2b4bbf802dd8, p1b6c41a6c96a, ped36104bf1eb, pee1aeccfa875 | final, the top 3 |

The pool:

| id | title | configuration | lane | model |
| --- | --- | --- | --- | --- |
| p0b85ce9d39a5 | Buffer text pieces in process_text and join once per text token | X1-3 | recombine | claude-sonnet-5-5 |
| p1b6c41a6c96a | Replace backward opener scan in _process_emphasis_delimiters with per-key opener stacks | X1-1 | name_the_problem | claude-sonnet-5 |
| p2b4bbf802dd8 | Skip _split_text_token character scanning for text tokens without emphasis markers | X1-0 | eliminate | claude-sonnet-5-5 |
| p2ca480dd852f | Fuse _can_open/_can_close emphasis checks into one neighbour computation per delimiter run | X1-2 | recombine | claude-sonnet-5-5 |
| p349dd5d1544b | Regex fast path for plain link destinations in helpers._parse_link_href, falling back to the char loop | X1-1 | eliminate | claude-fable-5-1 |
| p514fdb43dea3 | Avoid per-token source string build when no emphasis delimiter can be opened or closed | X1-2 | eliminate | claude-sonnet-5-5 |
| p9dcd74acbbff | Cache the compiled fast-trigger regex lookup in InlineParser._find_fast_text_end | X1-0 | assume_less | claude-sonnet-5-5 |
| pb336f7684533 | Fast-path _parse_link_href with a regex for plain href runs | X1-2 | name_the_problem | claude-sonnet-5-5 |
| pe935740208b7 | Join token renders from a list comprehension instead of a generator in BaseRenderer.render_tokens | X1-1 | far | claude-fable-5 |
| ped36104bf1eb | Skip per-call compile_sc lookup and finalize work for pure-text inline strings | X1-3 | eliminate | claude-sonnet-5-5 |
| pee1aeccfa875 | Fuse fast-trigger search into InlineParser.parse by caching the compiled trigger regex locally | X1-0 | recombine | claude-sonnet-5-5 |
| pf931c09d3301 | Fast-path _split_text_token for text tokens without emphasis markers | X1-1 | assume_less | claude-sonnet-5-5 |

Not ranked (written by claude-opus-5-5, the marker's own model):

none

#### Ranked by opus-5 (claude-opus-5), unvalidated: 12 ideas, 3 requests in 2 rounds

| rank | id | title | configuration | lane | model |
| --- | --- | --- | --- | --- | --- |
| 1 | p2b4bbf802dd8 | Skip _split_text_token character scanning for text tokens without emphasis markers | X1-0 | eliminate | claude-sonnet-5-5 |
| 2 | pf931c09d3301 | Fast-path _split_text_token for text tokens without emphasis markers | X1-1 | assume_less | claude-sonnet-5-5 |
| 3 | ped36104bf1eb | Skip per-call compile_sc lookup and finalize work for pure-text inline strings | X1-3 | eliminate | claude-sonnet-5-5 |

Every set (ids in the order shown; the marker's order, most likely first):

| round | set | shown | seed | the marker's order | advanced |
| --- | --- | --- | --- | --- | --- |
| 1 | 1 | p2b4bbf802dd8, p2ca480dd852f, p1b6c41a6c96a, p349dd5d1544b, p514fdb43dea3, p0b85ce9d39a5 | 20261103\:mistune\:1\:opus-5-r1-s1 | p2b4bbf802dd8, p514fdb43dea3, p2ca480dd852f, p1b6c41a6c96a, p0b85ce9d39a5, p349dd5d1544b | p2b4bbf802dd8, p514fdb43dea3 |
| 1 | 2 | pee1aeccfa875, pb336f7684533, pe935740208b7, ped36104bf1eb, p9dcd74acbbff, pf931c09d3301 | 20261103\:mistune\:1\:opus-5-r1-s2 | ped36104bf1eb, pf931c09d3301, p9dcd74acbbff, pee1aeccfa875, pe935740208b7, pb336f7684533 | ped36104bf1eb, pf931c09d3301 |
| 2 | 1 | p2b4bbf802dd8, ped36104bf1eb, p514fdb43dea3, pf931c09d3301 | 20261103\:mistune\:1\:opus-5-r2-s1 | p2b4bbf802dd8, pf931c09d3301, ped36104bf1eb, p514fdb43dea3 | final, the top 3 |

The pool:

| id | title | configuration | lane | model |
| --- | --- | --- | --- | --- |
| p0b85ce9d39a5 | Buffer text pieces in process_text and join once per text token | X1-3 | recombine | claude-sonnet-5-5 |
| p1b6c41a6c96a | Replace backward opener scan in _process_emphasis_delimiters with per-key opener stacks | X1-1 | name_the_problem | claude-sonnet-5 |
| p2b4bbf802dd8 | Skip _split_text_token character scanning for text tokens without emphasis markers | X1-0 | eliminate | claude-sonnet-5-5 |
| p2ca480dd852f | Fuse _can_open/_can_close emphasis checks into one neighbour computation per delimiter run | X1-2 | recombine | claude-sonnet-5-5 |
| p349dd5d1544b | Regex fast path for plain link destinations in helpers._parse_link_href, falling back to the char loop | X1-1 | eliminate | claude-fable-5-1 |
| p514fdb43dea3 | Avoid per-token source string build when no emphasis delimiter can be opened or closed | X1-2 | eliminate | claude-sonnet-5-5 |
| p9dcd74acbbff | Cache the compiled fast-trigger regex lookup in InlineParser._find_fast_text_end | X1-0 | assume_less | claude-sonnet-5-5 |
| pb336f7684533 | Fast-path _parse_link_href with a regex for plain href runs | X1-2 | name_the_problem | claude-sonnet-5-5 |
| pe935740208b7 | Join token renders from a list comprehension instead of a generator in BaseRenderer.render_tokens | X1-1 | far | claude-fable-5 |
| ped36104bf1eb | Skip per-call compile_sc lookup and finalize work for pure-text inline strings | X1-3 | eliminate | claude-sonnet-5-5 |
| pee1aeccfa875 | Fuse fast-trigger search into InlineParser.parse by caching the compiled trigger regex locally | X1-0 | recombine | claude-sonnet-5-5 |
| pf931c09d3301 | Fast-path _split_text_token for text tokens without emphasis markers | X1-1 | assume_less | claude-sonnet-5-5 |

Not ranked (written by claude-opus-5, the marker's own model):

none


### more_itertools

#### Ranked by opus-5-5 (claude-opus-5-5), validated: 11 ideas, 3 requests in 2 rounds

| rank | id | title | configuration | lane | model |
| --- | --- | --- | --- | --- | --- |
| 1 | pc034c7e27d86 | Windowed running mean\: use accumulate-difference pipeline instead of per-item generator with deque | X1-1 | far | claude-sonnet-5-5 |
| 2 | pb5b7823ea935 | Block-based (van Herk) sliding min/max via C-level accumulate/map instead of per-item deque loop | X1-1 | resolve_tradeoff | claude-fable-5-1 |
| 3 | p02a4b74a3fac | Phase-split _running_median_windowed\: fill phase, then fixed-size steady loop with precomputed parity and ring buffer | X1-1 | recombine | claude-fable-5 |

Every set (ids in the order shown; the marker's order, most likely first):

| round | set | shown | seed | the marker's order | advanced |
| --- | --- | --- | --- | --- | --- |
| 1 | 1 | p652bfec556a4, p882aeb7d2041, p48b03724d79d, p02a4b74a3fac, pb3f8c19d3d11, p97b76f89fe91 | 20261103\:more_itertools\:1\:opus-5-5-r1-s1 | p882aeb7d2041, p02a4b74a3fac, p97b76f89fe91, pb3f8c19d3d11, p48b03724d79d, p652bfec556a4 | p882aeb7d2041, p02a4b74a3fac |
| 1 | 2 | pd4243def207d, pfaf154792c95, pb5b7823ea935, pc034c7e27d86, pf4df4416c1fd | 20261103\:more_itertools\:1\:opus-5-5-r1-s2 | pb5b7823ea935, pc034c7e27d86, pf4df4416c1fd, pd4243def207d, pfaf154792c95 | pb5b7823ea935, pc034c7e27d86 |
| 2 | 1 | p882aeb7d2041, p02a4b74a3fac, pc034c7e27d86, pb5b7823ea935 | 20261103\:more_itertools\:1\:opus-5-5-r2-s1 | pc034c7e27d86, pb5b7823ea935, p02a4b74a3fac, p882aeb7d2041 | final, the top 3 |

The pool:

| id | title | configuration | lane | model |
| --- | --- | --- | --- | --- |
| p02a4b74a3fac | Phase-split _running_median_windowed\: fill phase, then fixed-size steady loop with precomputed parity and ring buffer | X1-1 | recombine | claude-fable-5 |
| p48b03724d79d | Running median window\: avoid second bisect by tracking via sorted insertion index | X1-0 | far | claude-sonnet-5-5 |
| p652bfec556a4 | Replace collapse's deque stack with a plain list stack in more.py | X1-1 | eliminate | claude-sonnet-5 |
| p882aeb7d2041 | Windowed running min/max\: skip enumerate and tuple storage by using a monotonic deque with a countdown expiry | X1-3 | resolve_tradeoff | claude-sonnet-5-5 |
| p97b76f89fe91 | Median window\: skip the insort-then-delete step by using bisect-based replace when the window is full | X1-0 | eliminate | claude-sonnet-5-5 |
| pb3f8c19d3d11 | bucket._get_values\: skip the validator call for already-cached keys by using a per-key seen set | X1-3 | name_the_problem | claude-sonnet-5-5 |
| pb5b7823ea935 | Block-based (van Herk) sliding min/max via C-level accumulate/map instead of per-item deque loop | X1-1 | resolve_tradeoff | claude-fable-5-1 |
| pc034c7e27d86 | Windowed running mean\: use accumulate-difference pipeline instead of per-item generator with deque | X1-1 | far | claude-sonnet-5-5 |
| pd4243def207d | Running median windowed\: avoid the deque by deriving the evicted value from the source with a ring list | X1-2 | recombine | claude-sonnet-5-5 |
| pf4df4416c1fd | set_partitions\: hoist the block-size filter lambda and skip it when size limits are trivial | X1-3 | recombine | claude-sonnet-5-5 |
| pfaf154792c95 | bucket._get_values\: bind cache deque and key lookup once per generator, avoid repeated dict lookup | X1-0 | assume_less | claude-sonnet-5-5 |

Not ranked (written by claude-opus-5-5, the marker's own model):

| title | configuration | lane | model |
| --- | --- | --- | --- |
| Replace try/next loop with a resumable for-loop over the parent iterator in bucket._get_values | X1-1 | name_the_problem | claude-opus-5-5 |

#### Ranked by opus-5 (claude-opus-5), unvalidated: 12 ideas, 3 requests in 2 rounds

| rank | id | title | configuration | lane | model |
| --- | --- | --- | --- | --- | --- |
| 1 | pc034c7e27d86 | Windowed running mean\: use accumulate-difference pipeline instead of per-item generator with deque | X1-1 | far | claude-sonnet-5-5 |
| 2 | pb5b7823ea935 | Block-based (van Herk) sliding min/max via C-level accumulate/map instead of per-item deque loop | X1-1 | resolve_tradeoff | claude-fable-5-1 |
| 3 | p882aeb7d2041 | Windowed running min/max\: skip enumerate and tuple storage by using a monotonic deque with a countdown expiry | X1-3 | resolve_tradeoff | claude-sonnet-5-5 |

Every set (ids in the order shown; the marker's order, most likely first):

| round | set | shown | seed | the marker's order | advanced |
| --- | --- | --- | --- | --- | --- |
| 1 | 1 | p02a4b74a3fac, p882aeb7d2041, p48b03724d79d, p197f5e868819, p97b76f89fe91, p652bfec556a4 | 20261103\:more_itertools\:1\:opus-5-r1-s1 | p882aeb7d2041, p197f5e868819, p02a4b74a3fac, p97b76f89fe91, p48b03724d79d, p652bfec556a4 | p882aeb7d2041, p197f5e868819 |
| 1 | 2 | pb3f8c19d3d11, pfaf154792c95, pf4df4416c1fd, pd4243def207d, pb5b7823ea935, pc034c7e27d86 | 20261103\:more_itertools\:1\:opus-5-r1-s2 | pc034c7e27d86, pb5b7823ea935, pf4df4416c1fd, pfaf154792c95, pd4243def207d, pb3f8c19d3d11 | pc034c7e27d86, pb5b7823ea935 |
| 2 | 1 | p197f5e868819, p882aeb7d2041, pb5b7823ea935, pc034c7e27d86 | 20261103\:more_itertools\:1\:opus-5-r2-s1 | pc034c7e27d86, pb5b7823ea935, p882aeb7d2041, p197f5e868819 | final, the top 3 |

The pool:

| id | title | configuration | lane | model |
| --- | --- | --- | --- | --- |
| p02a4b74a3fac | Phase-split _running_median_windowed\: fill phase, then fixed-size steady loop with precomputed parity and ring buffer | X1-1 | recombine | claude-fable-5 |
| p197f5e868819 | Replace try/next loop with a resumable for-loop over the parent iterator in bucket._get_values | X1-1 | name_the_problem | claude-opus-5-5 |
| p48b03724d79d | Running median window\: avoid second bisect by tracking via sorted insertion index | X1-0 | far | claude-sonnet-5-5 |
| p652bfec556a4 | Replace collapse's deque stack with a plain list stack in more.py | X1-1 | eliminate | claude-sonnet-5 |
| p882aeb7d2041 | Windowed running min/max\: skip enumerate and tuple storage by using a monotonic deque with a countdown expiry | X1-3 | resolve_tradeoff | claude-sonnet-5-5 |
| p97b76f89fe91 | Median window\: skip the insort-then-delete step by using bisect-based replace when the window is full | X1-0 | eliminate | claude-sonnet-5-5 |
| pb3f8c19d3d11 | bucket._get_values\: skip the validator call for already-cached keys by using a per-key seen set | X1-3 | name_the_problem | claude-sonnet-5-5 |
| pb5b7823ea935 | Block-based (van Herk) sliding min/max via C-level accumulate/map instead of per-item deque loop | X1-1 | resolve_tradeoff | claude-fable-5-1 |
| pc034c7e27d86 | Windowed running mean\: use accumulate-difference pipeline instead of per-item generator with deque | X1-1 | far | claude-sonnet-5-5 |
| pd4243def207d | Running median windowed\: avoid the deque by deriving the evicted value from the source with a ring list | X1-2 | recombine | claude-sonnet-5-5 |
| pf4df4416c1fd | set_partitions\: hoist the block-size filter lambda and skip it when size limits are trivial | X1-3 | recombine | claude-sonnet-5-5 |
| pfaf154792c95 | bucket._get_values\: bind cache deque and key lookup once per generator, avoid repeated dict lookup | X1-0 | assume_less | claude-sonnet-5-5 |

Not ranked (written by claude-opus-5, the marker's own model):

none


### pyparsing

#### Ranked by opus-5-5 (claude-opus-5-5), validated: 12 ideas, 3 requests in 2 rounds

| rank | id | title | configuration | lane | model |
| --- | --- | --- | --- | --- | --- |
| 1 | p86d1e44dea3f | Skip infix operator attempts whose first character cannot match, in _InfixNotation.parseImpl | X1-1 | eliminate | claude-haiku-5-5 |
| 2 | pcb3aa39f0d68 | Avoid redundant second parse of base_expr lookahead and as_list conversions in infix operator handling | X1-0 | eliminate | claude-sonnet-5-5 |
| 3 | p7944155f7dd2 | ParseResults construction fast path\: skip deprecate_argument when no kwargs and use exact-type list check in __new__ | X1-1 | recombine | claude-fable-5-1 |

Every set (ids in the order shown; the marker's order, most likely first):

| round | set | shown | seed | the marker's order | advanced |
| --- | --- | --- | --- | --- | --- |
| 1 | 1 | p7944155f7dd2, p25d872310202, p7bdeeb047e7a, p071a4fc34104, p4387183b55a9, p434f1a9c74c3 | 20261103\:pyparsing\:1\:opus-5-5-r1-s1 | p4387183b55a9, p7944155f7dd2, p071a4fc34104, p7bdeeb047e7a, p434f1a9c74c3, p25d872310202 | p4387183b55a9, p7944155f7dd2 |
| 1 | 2 | pf779fd3673d1, pfacc149d6dc9, p86d1e44dea3f, pcb3aa39f0d68, p81c071f6f955, pbedf28074ad4 | 20261103\:pyparsing\:1\:opus-5-5-r1-s2 | p86d1e44dea3f, pcb3aa39f0d68, pbedf28074ad4, pf779fd3673d1, pfacc149d6dc9, p81c071f6f955 | p86d1e44dea3f, pcb3aa39f0d68 |
| 2 | 1 | p4387183b55a9, p7944155f7dd2, p86d1e44dea3f, pcb3aa39f0d68 | 20261103\:pyparsing\:1\:opus-5-5-r2-s1 | p86d1e44dea3f, pcb3aa39f0d68, p7944155f7dd2, p4387183b55a9 | final, the top 3 |

The pool:

| id | title | configuration | lane | model |
| --- | --- | --- | --- | --- |
| p071a4fc34104 | Hoist per-call ParseResults construction checks\: bypass __init__ kwargs deprecation lookup | X1-0 | name_the_problem | claude-sonnet-5-5 |
| p25d872310202 | Skip exception-and-reduction scaffolding\: hoist per-iteration preParse try/except in infix loop to first-char dispatch | X1-2 | name_the_problem | claude-sonnet-5-5 |
| p434f1a9c74c3 | Cache whitespace-skip decision in infix parse loop\: avoid preParse call when next char is not whitespace | X1-2 | recombine | claude-sonnet-5-5 |
| p4387183b55a9 | Cache the whitespace-set emptiness check\: skip preParse call when nothing can be skipped in _parseNoCache | X1-0 | far | claude-sonnet-5-5 |
| p7944155f7dd2 | ParseResults construction fast path\: skip deprecate_argument when no kwargs and use exact-type list check in __new__ | X1-1 | recombine | claude-fable-5-1 |
| p7bdeeb047e7a | MatchFirst.parseImpl\: avoid exception-object bookkeeping with locals and first-element fast path | X1-3 | recombine | claude-sonnet-5-5 |
| p81c071f6f955 | Replace char-by-char whitespace skipping in ParserElement.preParse with a precompiled character-class regex | X1-1 | name_the_problem | claude-fable-5 |
| p86d1e44dea3f | Skip infix operator attempts whose first character cannot match, in _InfixNotation.parseImpl | X1-1 | eliminate | claude-haiku-5-5 |
| pbedf28074ad4 | Skip ParseResults wrapping when parseImpl already returns a ParseResults and no results name is set | X1-3 | name_the_problem | claude-sonnet-5-5 |
| pcb3aa39f0d68 | Avoid redundant second parse of base_expr lookahead and as_list conversions in infix operator handling | X1-0 | eliminate | claude-sonnet-5-5 |
| pf779fd3673d1 | Avoid redundant as_list() calls on ParseResults in infix operator token extraction | X1-2 | eliminate | claude-sonnet-5-5 |
| pfacc149d6dc9 | Avoid ParseResults allocation of throwaway list/set in __new__ via lazily created _all_names | X1-3 | resolve_tradeoff | claude-sonnet-5-5 |

Not ranked (written by claude-opus-5-5, the marker's own model):

none

#### Ranked by opus-5 (claude-opus-5), unvalidated: 12 ideas, 3 requests in 2 rounds

| rank | id | title | configuration | lane | model |
| --- | --- | --- | --- | --- | --- |
| 1 | p86d1e44dea3f | Skip infix operator attempts whose first character cannot match, in _InfixNotation.parseImpl | X1-1 | eliminate | claude-haiku-5-5 |
| 2 | p7944155f7dd2 | ParseResults construction fast path\: skip deprecate_argument when no kwargs and use exact-type list check in __new__ | X1-1 | recombine | claude-fable-5-1 |
| 3 | p4387183b55a9 | Cache the whitespace-set emptiness check\: skip preParse call when nothing can be skipped in _parseNoCache | X1-0 | far | claude-sonnet-5-5 |

Every set (ids in the order shown; the marker's order, most likely first):

| round | set | shown | seed | the marker's order | advanced |
| --- | --- | --- | --- | --- | --- |
| 1 | 1 | p4387183b55a9, p071a4fc34104, p25d872310202, p434f1a9c74c3, p7bdeeb047e7a, p7944155f7dd2 | 20261103\:pyparsing\:1\:opus-5-r1-s1 | p7944155f7dd2, p4387183b55a9, p071a4fc34104, p7bdeeb047e7a, p434f1a9c74c3, p25d872310202 | p7944155f7dd2, p4387183b55a9 |
| 1 | 2 | p81c071f6f955, pbedf28074ad4, p86d1e44dea3f, pcb3aa39f0d68, pf779fd3673d1, pfacc149d6dc9 | 20261103\:pyparsing\:1\:opus-5-r1-s2 | pbedf28074ad4, p86d1e44dea3f, p81c071f6f955, pfacc149d6dc9, pcb3aa39f0d68, pf779fd3673d1 | pbedf28074ad4, p86d1e44dea3f |
| 2 | 1 | p86d1e44dea3f, pbedf28074ad4, p7944155f7dd2, p4387183b55a9 | 20261103\:pyparsing\:1\:opus-5-r2-s1 | p86d1e44dea3f, p7944155f7dd2, p4387183b55a9, pbedf28074ad4 | final, the top 3 |

The pool:

| id | title | configuration | lane | model |
| --- | --- | --- | --- | --- |
| p071a4fc34104 | Hoist per-call ParseResults construction checks\: bypass __init__ kwargs deprecation lookup | X1-0 | name_the_problem | claude-sonnet-5-5 |
| p25d872310202 | Skip exception-and-reduction scaffolding\: hoist per-iteration preParse try/except in infix loop to first-char dispatch | X1-2 | name_the_problem | claude-sonnet-5-5 |
| p434f1a9c74c3 | Cache whitespace-skip decision in infix parse loop\: avoid preParse call when next char is not whitespace | X1-2 | recombine | claude-sonnet-5-5 |
| p4387183b55a9 | Cache the whitespace-set emptiness check\: skip preParse call when nothing can be skipped in _parseNoCache | X1-0 | far | claude-sonnet-5-5 |
| p7944155f7dd2 | ParseResults construction fast path\: skip deprecate_argument when no kwargs and use exact-type list check in __new__ | X1-1 | recombine | claude-fable-5-1 |
| p7bdeeb047e7a | MatchFirst.parseImpl\: avoid exception-object bookkeeping with locals and first-element fast path | X1-3 | recombine | claude-sonnet-5-5 |
| p81c071f6f955 | Replace char-by-char whitespace skipping in ParserElement.preParse with a precompiled character-class regex | X1-1 | name_the_problem | claude-fable-5 |
| p86d1e44dea3f | Skip infix operator attempts whose first character cannot match, in _InfixNotation.parseImpl | X1-1 | eliminate | claude-haiku-5-5 |
| pbedf28074ad4 | Skip ParseResults wrapping when parseImpl already returns a ParseResults and no results name is set | X1-3 | name_the_problem | claude-sonnet-5-5 |
| pcb3aa39f0d68 | Avoid redundant second parse of base_expr lookahead and as_list conversions in infix operator handling | X1-0 | eliminate | claude-sonnet-5-5 |
| pf779fd3673d1 | Avoid redundant as_list() calls on ParseResults in infix operator token extraction | X1-2 | eliminate | claude-sonnet-5-5 |
| pfacc149d6dc9 | Avoid ParseResults allocation of throwaway list/set in __new__ via lazily created _all_names | X1-3 | resolve_tradeoff | claude-sonnet-5-5 |

Not ranked (written by claude-opus-5, the marker's own model):

none


### sortedcontainers

#### Ranked by opus-5-5 (claude-opus-5-5), validated: 9 ideas, 3 requests in 2 rounds

| rank | id | title | configuration | lane | model |
| --- | --- | --- | --- | --- | --- |
| 1 | pbc463918b2cf | SortedKeyList.add\: fuse key bisect into maxes path and skip _keys lookups via local sublist refs | X1-3 | recombine | claude-sonnet-5-5 |
| 2 | p5fab9f6dd27b | SortedList.add\: skip the per-insert len(_maxes) call by testing the bisect result against a cached length | X1-3 | eliminate | claude-sonnet-5-5 |
| 3 | p6ac504bac67d | SortedKeyList.add\: skip key-list bisect indirection by using insort-style append path when key is the new max | X1-2 | assume_less | claude-sonnet-5-5 |

Every set (ids in the order shown; the marker's order, most likely first):

| round | set | shown | seed | the marker's order | advanced |
| --- | --- | --- | --- | --- | --- |
| 1 | 1 | p5a25eb4c421a, p560431657f7a, p6ac504bac67d, p5fab9f6dd27b, p32e0c95258af | 20261103\:sortedcontainers\:1\:opus-5-5-r1-s1 | p5fab9f6dd27b, p6ac504bac67d, p560431657f7a, p5a25eb4c421a, p32e0c95258af | p5fab9f6dd27b, p6ac504bac67d |
| 1 | 2 | pc0eccdd2ad6d, pbc463918b2cf, pf43e272b9507, pf5cbbe7aea67 | 20261103\:sortedcontainers\:1\:opus-5-5-r1-s2 | pbc463918b2cf, pf43e272b9507, pf5cbbe7aea67, pc0eccdd2ad6d | pbc463918b2cf, pf43e272b9507 |
| 2 | 1 | pbc463918b2cf, p6ac504bac67d, p5fab9f6dd27b, pf43e272b9507 | 20261103\:sortedcontainers\:1\:opus-5-5-r2-s1 | pbc463918b2cf, p5fab9f6dd27b, p6ac504bac67d, pf43e272b9507 | final, the top 3 |

The pool:

| id | title | configuration | lane | model |
| --- | --- | --- | --- | --- |
| p32e0c95258af | SortedKeyList.discard\: remove per-iteration double indexing and hoist sublist lookups | X1-2 | recombine | claude-sonnet-5-5 |
| p560431657f7a | SortedList._delete\: replace leaf-to-root index decrement loop with a combined walk using cached locals | X1-0 | name_the_problem | claude-sonnet-5-5 |
| p5a25eb4c421a | Fuse index decrement into the _pos descent for SortedList.pop by index | X1-1 | eliminate | claude-fable-5 |
| p5fab9f6dd27b | SortedList.add\: skip the per-insert len(_maxes) call by testing the bisect result against a cached length | X1-3 | eliminate | claude-sonnet-5-5 |
| p6ac504bac67d | SortedKeyList.add\: skip key-list bisect indirection by using insort-style append path when key is the new max | X1-2 | assume_less | claude-sonnet-5-5 |
| pbc463918b2cf | SortedKeyList.add\: fuse key bisect into maxes path and skip _keys lookups via local sublist refs | X1-3 | recombine | claude-sonnet-5-5 |
| pc0eccdd2ad6d | Hoist per-bucket key/value list lookups out of the scan loop in SortedKeyList.discard | X1-1 | recombine | claude-sonnet-5 |
| pf43e272b9507 | Defer index decrement on SortedKeyList._delete by clearing the index instead of walking ancestors | X1-1 | resolve_tradeoff | claude-haiku-5-5 |
| pf5cbbe7aea67 | SortedKeyList.discard\: drop per-step re-lookups and skip scan loop for exact first match | X1-0 | recombine | claude-sonnet-5-5 |

Not ranked (written by claude-opus-5-5, the marker's own model):

none

#### Ranked by opus-5 (claude-opus-5), unvalidated: 9 ideas, 3 requests in 2 rounds

| rank | id | title | configuration | lane | model |
| --- | --- | --- | --- | --- | --- |
| 1 | pbc463918b2cf | SortedKeyList.add\: fuse key bisect into maxes path and skip _keys lookups via local sublist refs | X1-3 | recombine | claude-sonnet-5-5 |
| 2 | p5fab9f6dd27b | SortedList.add\: skip the per-insert len(_maxes) call by testing the bisect result against a cached length | X1-3 | eliminate | claude-sonnet-5-5 |
| 3 | p6ac504bac67d | SortedKeyList.add\: skip key-list bisect indirection by using insort-style append path when key is the new max | X1-2 | assume_less | claude-sonnet-5-5 |

Every set (ids in the order shown; the marker's order, most likely first):

| round | set | shown | seed | the marker's order | advanced |
| --- | --- | --- | --- | --- | --- |
| 1 | 1 | p560431657f7a, p5fab9f6dd27b, p32e0c95258af, p6ac504bac67d, p5a25eb4c421a | 20261103\:sortedcontainers\:1\:opus-5-r1-s1 | p5fab9f6dd27b, p6ac504bac67d, p560431657f7a, p5a25eb4c421a, p32e0c95258af | p5fab9f6dd27b, p6ac504bac67d |
| 1 | 2 | pf43e272b9507, pc0eccdd2ad6d, pf5cbbe7aea67, pbc463918b2cf | 20261103\:sortedcontainers\:1\:opus-5-r1-s2 | pbc463918b2cf, pf5cbbe7aea67, pc0eccdd2ad6d, pf43e272b9507 | pbc463918b2cf, pf5cbbe7aea67 |
| 2 | 1 | p6ac504bac67d, p5fab9f6dd27b, pbc463918b2cf, pf5cbbe7aea67 | 20261103\:sortedcontainers\:1\:opus-5-r2-s1 | pbc463918b2cf, p5fab9f6dd27b, p6ac504bac67d, pf5cbbe7aea67 | final, the top 3 |

The pool:

| id | title | configuration | lane | model |
| --- | --- | --- | --- | --- |
| p32e0c95258af | SortedKeyList.discard\: remove per-iteration double indexing and hoist sublist lookups | X1-2 | recombine | claude-sonnet-5-5 |
| p560431657f7a | SortedList._delete\: replace leaf-to-root index decrement loop with a combined walk using cached locals | X1-0 | name_the_problem | claude-sonnet-5-5 |
| p5a25eb4c421a | Fuse index decrement into the _pos descent for SortedList.pop by index | X1-1 | eliminate | claude-fable-5 |
| p5fab9f6dd27b | SortedList.add\: skip the per-insert len(_maxes) call by testing the bisect result against a cached length | X1-3 | eliminate | claude-sonnet-5-5 |
| p6ac504bac67d | SortedKeyList.add\: skip key-list bisect indirection by using insort-style append path when key is the new max | X1-2 | assume_less | claude-sonnet-5-5 |
| pbc463918b2cf | SortedKeyList.add\: fuse key bisect into maxes path and skip _keys lookups via local sublist refs | X1-3 | recombine | claude-sonnet-5-5 |
| pc0eccdd2ad6d | Hoist per-bucket key/value list lookups out of the scan loop in SortedKeyList.discard | X1-1 | recombine | claude-sonnet-5 |
| pf43e272b9507 | Defer index decrement on SortedKeyList._delete by clearing the index instead of walking ancestors | X1-1 | resolve_tradeoff | claude-haiku-5-5 |
| pf5cbbe7aea67 | SortedKeyList.discard\: drop per-step re-lookups and skip scan loop for exact first match | X1-0 | recombine | claude-sonnet-5-5 |

Not ranked (written by claude-opus-5, the marker's own model):

none


### sqlparse

#### Ranked by opus-5-5 (claude-opus-5-5), validated: 11 ideas, 3 requests in 2 rounds

| rank | id | title | configuration | lane | model |
| --- | --- | --- | --- | --- | --- |
| 1 | pf93fca630e46 | Skip per-pass _group recursion into subtrees without any possible match using a cheap token-type precheck | X1-2 | name_the_problem | claude-sonnet-5-5 |
| 2 | p87a8bb7b8f6b | Lexer\: use one combined alternation regex with named groups instead of looping rules per character | X1-3 | far | claude-sonnet-5-5 |
| 3 | p27ec68faede3 | Hoist per-token whitespace and group checks out of _group's loop via a precomputed match gate | X1-3 | resolve_tradeoff | claude-sonnet-5-5 |

Every set (ids in the order shown; the marker's order, most likely first):

| round | set | shown | seed | the marker's order | advanced |
| --- | --- | --- | --- | --- | --- |
| 1 | 1 | p3e407f0e0fe8, p1957a826c284, p27ec68faede3, p230f38d4a02e, p1a8ccabdd295, p67770fa96b32 | 20261103\:sqlparse\:1\:opus-5-5-r1-s1 | p67770fa96b32, p27ec68faede3, p1957a826c284, p1a8ccabdd295, p3e407f0e0fe8, p230f38d4a02e | p67770fa96b32, p27ec68faede3 |
| 1 | 2 | pa54003f40395, p87a8bb7b8f6b, p9ed96fbe15a2, pade90263dbf2, pf93fca630e46 | 20261103\:sqlparse\:1\:opus-5-5-r1-s2 | pf93fca630e46, p87a8bb7b8f6b, p9ed96fbe15a2, pa54003f40395, pade90263dbf2 | pf93fca630e46, p87a8bb7b8f6b |
| 2 | 1 | p67770fa96b32, pf93fca630e46, p87a8bb7b8f6b, p27ec68faede3 | 20261103\:sqlparse\:1\:opus-5-5-r2-s1 | pf93fca630e46, p87a8bb7b8f6b, p27ec68faede3, p67770fa96b32 | final, the top 3 |

The pool:

| id | title | configuration | lane | model |
| --- | --- | --- | --- | --- |
| p1957a826c284 | Make _TokenType.__contains__ a precomputed frozenset lookup with ancestry cached per type | X1-0 | recombine | claude-sonnet-5-5 |
| p1a8ccabdd295 | Statement splitter\: precomputed keyword-type fast reject and skip Token double construction work | X1-0 | name_the_problem | claude-sonnet-5-5 |
| p230f38d4a02e | Flatten TokenList via an explicit stack instead of nested recursive generators in sql.py | X1-1 | name_the_problem | claude-haiku-5-5 |
| p27ec68faede3 | Hoist per-token whitespace and group checks out of _group's loop via a precomputed match gate | X1-3 | resolve_tradeoff | claude-sonnet-5-5 |
| p3e407f0e0fe8 | Memoise keyword lookup results in lexer per uppercase value | X1-3 | eliminate | claude-sonnet-5-5 |
| p67770fa96b32 | Compute TokenList.value lazily to avoid O(n²) string joins during grouping | X1-1 | resolve_tradeoff | claude-fable-5 |
| p87a8bb7b8f6b | Lexer\: use one combined alternation regex with named groups instead of looping rules per character | X1-3 | far | claude-sonnet-5-5 |
| p9ed96fbe15a2 | Skip recursion into non-matching groups in _group_matching passes via a cheap pre-scan of the token list | X1-2 | resolve_tradeoff | claude-sonnet-5-5 |
| pa54003f40395 | Cache compiled regexes in Token.match regex branch | X1-0 | assume_less | claude-sonnet-5-5 |
| pade90263dbf2 | Turn grouping.py ttype tuples into frozensets so imt's type membership is a hash lookup | X1-1 | far | claude-fable-5-1 |
| pf93fca630e46 | Skip per-pass _group recursion into subtrees without any possible match using a cheap token-type precheck | X1-2 | name_the_problem | claude-sonnet-5-5 |

Not ranked (written by claude-opus-5-5, the marker's own model):

none

#### Ranked by opus-5 (claude-opus-5), unvalidated: 11 ideas, 3 requests in 2 rounds

| rank | id | title | configuration | lane | model |
| --- | --- | --- | --- | --- | --- |
| 1 | p1957a826c284 | Make _TokenType.__contains__ a precomputed frozenset lookup with ancestry cached per type | X1-0 | recombine | claude-sonnet-5-5 |
| 2 | p87a8bb7b8f6b | Lexer\: use one combined alternation regex with named groups instead of looping rules per character | X1-3 | far | claude-sonnet-5-5 |
| 3 | p67770fa96b32 | Compute TokenList.value lazily to avoid O(n²) string joins during grouping | X1-1 | resolve_tradeoff | claude-fable-5 |

Every set (ids in the order shown; the marker's order, most likely first):

| round | set | shown | seed | the marker's order | advanced |
| --- | --- | --- | --- | --- | --- |
| 1 | 1 | p1a8ccabdd295, p27ec68faede3, p3e407f0e0fe8, p67770fa96b32, p230f38d4a02e, p1957a826c284 | 20261103\:sqlparse\:1\:opus-5-r1-s1 | p1957a826c284, p67770fa96b32, p3e407f0e0fe8, p27ec68faede3, p1a8ccabdd295, p230f38d4a02e | p1957a826c284, p67770fa96b32 |
| 1 | 2 | pf93fca630e46, pa54003f40395, p87a8bb7b8f6b, pade90263dbf2, p9ed96fbe15a2 | 20261103\:sqlparse\:1\:opus-5-r1-s2 | p87a8bb7b8f6b, pf93fca630e46, p9ed96fbe15a2, pade90263dbf2, pa54003f40395 | p87a8bb7b8f6b, pf93fca630e46 |
| 2 | 1 | p67770fa96b32, p87a8bb7b8f6b, pf93fca630e46, p1957a826c284 | 20261103\:sqlparse\:1\:opus-5-r2-s1 | p1957a826c284, p87a8bb7b8f6b, p67770fa96b32, pf93fca630e46 | final, the top 3 |

The pool:

| id | title | configuration | lane | model |
| --- | --- | --- | --- | --- |
| p1957a826c284 | Make _TokenType.__contains__ a precomputed frozenset lookup with ancestry cached per type | X1-0 | recombine | claude-sonnet-5-5 |
| p1a8ccabdd295 | Statement splitter\: precomputed keyword-type fast reject and skip Token double construction work | X1-0 | name_the_problem | claude-sonnet-5-5 |
| p230f38d4a02e | Flatten TokenList via an explicit stack instead of nested recursive generators in sql.py | X1-1 | name_the_problem | claude-haiku-5-5 |
| p27ec68faede3 | Hoist per-token whitespace and group checks out of _group's loop via a precomputed match gate | X1-3 | resolve_tradeoff | claude-sonnet-5-5 |
| p3e407f0e0fe8 | Memoise keyword lookup results in lexer per uppercase value | X1-3 | eliminate | claude-sonnet-5-5 |
| p67770fa96b32 | Compute TokenList.value lazily to avoid O(n²) string joins during grouping | X1-1 | resolve_tradeoff | claude-fable-5 |
| p87a8bb7b8f6b | Lexer\: use one combined alternation regex with named groups instead of looping rules per character | X1-3 | far | claude-sonnet-5-5 |
| p9ed96fbe15a2 | Skip recursion into non-matching groups in _group_matching passes via a cheap pre-scan of the token list | X1-2 | resolve_tradeoff | claude-sonnet-5-5 |
| pa54003f40395 | Cache compiled regexes in Token.match regex branch | X1-0 | assume_less | claude-sonnet-5-5 |
| pade90263dbf2 | Turn grouping.py ttype tuples into frozensets so imt's type membership is a hash lookup | X1-1 | far | claude-fable-5-1 |
| pf93fca630e46 | Skip per-pass _group recursion into subtrees without any possible match using a cheap token-type precheck | X1-2 | name_the_problem | claude-sonnet-5-5 |

Not ranked (written by claude-opus-5, the marker's own model):

none


### tomli

#### Ranked by opus-5-5 (claude-opus-5-5), validated: 10 ideas, 3 requests in 2 rounds

| rank | id | title | configuration | lane | model |
| --- | --- | --- | --- | --- | --- |
| 1 | pec1b62eefc81 | Inline skip_chars loops for whitespace at hot call sites in parse_key_value_pair and loads using a direct char test | X1-0 | resolve_tradeoff | claude-sonnet-5-5 |
| 2 | p59d892372901 | Fast path in parse_basic_str using str.find for the closing quote when the span has no backslash or illegal chars | X1-3 | recombine | claude-sonnet-5-5 |
| 3 | pa0fc5fec16a5 | Fast path for plain basic strings in parse_value using a precompiled regex for the no-escape case | X1-0 | recombine | claude-sonnet-5-5 |

Every set (ids in the order shown; the marker's order, most likely first):

| round | set | shown | seed | the marker's order | advanced |
| --- | --- | --- | --- | --- | --- |
| 1 | 1 | p909b7bcdbaad, p86791644a4dd, p8917b05b7bc7, p42d33d8ddf99, p59d892372901 | 20261103\:tomli\:1\:opus-5-5-r1-s1 | p59d892372901, p909b7bcdbaad, p42d33d8ddf99, p8917b05b7bc7, p86791644a4dd | p59d892372901, p909b7bcdbaad |
| 1 | 2 | pa0fc5fec16a5, pec1b62eefc81, pbbcadacb8a69, pfdb47740b257, pdacb8679ed51 | 20261103\:tomli\:1\:opus-5-5-r1-s2 | pec1b62eefc81, pa0fc5fec16a5, pbbcadacb8a69, pfdb47740b257, pdacb8679ed51 | pec1b62eefc81, pa0fc5fec16a5 |
| 2 | 1 | p59d892372901, p909b7bcdbaad, pa0fc5fec16a5, pec1b62eefc81 | 20261103\:tomli\:1\:opus-5-5-r2-s1 | pec1b62eefc81, p59d892372901, pa0fc5fec16a5, p909b7bcdbaad | final, the top 3 |

The pool:

| id | title | configuration | lane | model |
| --- | --- | --- | --- | --- |
| p42d33d8ddf99 | Dispatch parse_value on first character to skip datetime/localtime regexes for non-digit starts | X1-3 | far | claude-sonnet-5-5 |
| p59d892372901 | Fast path in parse_basic_str using str.find for the closing quote when the span has no backslash or illegal chars | X1-3 | recombine | claude-sonnet-5-5 |
| p86791644a4dd | Skip Flags FROZEN set call in key_value_rule for scalar values via isinstance ordering and early frozen check | X1-2 | assume_less | claude-sonnet-5-5 |
| p8917b05b7bc7 | Memoize repeated key tuples via a per-loads cache of parsed key parts in parse_key | X1-0 | far | claude-sonnet-5-5 |
| p909b7bcdbaad | Bind module-level regex/converter globals as function-local names in parse_value | X1-1 | resolve_tradeoff | claude-sonnet-5 |
| pa0fc5fec16a5 | Fast path for plain basic strings in parse_value using a precompiled regex for the no-escape case | X1-0 | recombine | claude-sonnet-5-5 |
| pbbcadacb8a69 | Fuse '= ' recognition in parse_key_value_pair to drop the try/except char fetch and skip_chars call | X1-1 | assume_less | claude-fable-5 |
| pdacb8679ed51 | Dispatch parse_value on a leading-digit check before the regexes | X1-2 | resolve_tradeoff | claude-sonnet-5-5 |
| pec1b62eefc81 | Inline skip_chars loops for whitespace at hot call sites in parse_key_value_pair and loads using a direct char test | X1-0 | resolve_tradeoff | claude-sonnet-5-5 |
| pfdb47740b257 | Newline fast path in the loads statement loop after a key/value or table rule | X1-1 | name_the_problem | claude-fable-5-1 |

Not ranked (written by claude-opus-5-5, the marker's own model):

none

#### Ranked by opus-5 (claude-opus-5), unvalidated: 10 ideas, 3 requests in 2 rounds

| rank | id | title | configuration | lane | model |
| --- | --- | --- | --- | --- | --- |
| 1 | p42d33d8ddf99 | Dispatch parse_value on first character to skip datetime/localtime regexes for non-digit starts | X1-3 | far | claude-sonnet-5-5 |
| 2 | pdacb8679ed51 | Dispatch parse_value on a leading-digit check before the regexes | X1-2 | resolve_tradeoff | claude-sonnet-5-5 |
| 3 | pec1b62eefc81 | Inline skip_chars loops for whitespace at hot call sites in parse_key_value_pair and loads using a direct char test | X1-0 | resolve_tradeoff | claude-sonnet-5-5 |

Every set (ids in the order shown; the marker's order, most likely first):

| round | set | shown | seed | the marker's order | advanced |
| --- | --- | --- | --- | --- | --- |
| 1 | 1 | p42d33d8ddf99, p8917b05b7bc7, p86791644a4dd, p909b7bcdbaad, p59d892372901 | 20261103\:tomli\:1\:opus-5-r1-s1 | p42d33d8ddf99, p59d892372901, p909b7bcdbaad, p8917b05b7bc7, p86791644a4dd | p42d33d8ddf99, p59d892372901 |
| 1 | 2 | pfdb47740b257, pdacb8679ed51, pbbcadacb8a69, pec1b62eefc81, pa0fc5fec16a5 | 20261103\:tomli\:1\:opus-5-r1-s2 | pec1b62eefc81, pdacb8679ed51, pbbcadacb8a69, pfdb47740b257, pa0fc5fec16a5 | pec1b62eefc81, pdacb8679ed51 |
| 2 | 1 | pdacb8679ed51, p42d33d8ddf99, pec1b62eefc81, p59d892372901 | 20261103\:tomli\:1\:opus-5-r2-s1 | p42d33d8ddf99, pdacb8679ed51, pec1b62eefc81, p59d892372901 | final, the top 3 |

The pool:

| id | title | configuration | lane | model |
| --- | --- | --- | --- | --- |
| p42d33d8ddf99 | Dispatch parse_value on first character to skip datetime/localtime regexes for non-digit starts | X1-3 | far | claude-sonnet-5-5 |
| p59d892372901 | Fast path in parse_basic_str using str.find for the closing quote when the span has no backslash or illegal chars | X1-3 | recombine | claude-sonnet-5-5 |
| p86791644a4dd | Skip Flags FROZEN set call in key_value_rule for scalar values via isinstance ordering and early frozen check | X1-2 | assume_less | claude-sonnet-5-5 |
| p8917b05b7bc7 | Memoize repeated key tuples via a per-loads cache of parsed key parts in parse_key | X1-0 | far | claude-sonnet-5-5 |
| p909b7bcdbaad | Bind module-level regex/converter globals as function-local names in parse_value | X1-1 | resolve_tradeoff | claude-sonnet-5 |
| pa0fc5fec16a5 | Fast path for plain basic strings in parse_value using a precompiled regex for the no-escape case | X1-0 | recombine | claude-sonnet-5-5 |
| pbbcadacb8a69 | Fuse '= ' recognition in parse_key_value_pair to drop the try/except char fetch and skip_chars call | X1-1 | assume_less | claude-fable-5 |
| pdacb8679ed51 | Dispatch parse_value on a leading-digit check before the regexes | X1-2 | resolve_tradeoff | claude-sonnet-5-5 |
| pec1b62eefc81 | Inline skip_chars loops for whitespace at hot call sites in parse_key_value_pair and loads using a direct char test | X1-0 | resolve_tradeoff | claude-sonnet-5-5 |
| pfdb47740b257 | Newline fast path in the loads statement loop after a key/value or table rule | X1-1 | name_the_problem | claude-fable-5-1 |

Not ranked (written by claude-opus-5, the marker's own model):

none


## Good ideas, corrected and strict (O43)

Summed over the libraries (- when one is unknown). Corrected: returned non-obvious ideas the auditor did not mark infeasible, a duplicate taking the verdict of the other arm's idea it repeats; strict: of those, none decided on an arm-A idea. The as-coded count rewards the arm the auditor read first, so it is shown only in the appendix.

| configuration | good corrected | good strict |
| --- | --- | --- |
| A | 37 | - |
| X1-0 | 26 | 19 |
| X1-1 | 32 | 26 |
| X1-2 | 23 | 21 |
| X1-3 | 26 | 20 |
| X1-4 | - | - |

## Self and cross repeats (O43, O44)

Each audit row's duplicate_of link counted once: self when its target is the same configuration's idea, cross otherwise, the target looked up within the same library (audit ids restart in each).

### What the arm handed on (in-result rows)

| library | configuration | self (in-result rows) | cross (in-result rows) | target not found (in-result rows) |
| --- | --- | --- | --- | --- |
| idna | A | 0 (in-result rows) | 0 (in-result rows) | 0 (in-result rows) |
| idna | X1-0 | 0 (in-result rows) | 3 (in-result rows) | 0 (in-result rows) |
| idna | X1-1 | 0 (in-result rows) | 3 (in-result rows) | 0 (in-result rows) |
| idna | X1-2 | 0 (in-result rows) | 2 (in-result rows) | 0 (in-result rows) |
| idna | X1-3 | 0 (in-result rows) | 3 (in-result rows) | 0 (in-result rows) |
| markdown | A | 0 (in-result rows) | 0 (in-result rows) | 0 (in-result rows) |
| markdown | X1-0 | 0 (in-result rows) | 4 (in-result rows) | 0 (in-result rows) |
| markdown | X1-1 | 0 (in-result rows) | 4 (in-result rows) | 0 (in-result rows) |
| markdown | X1-2 | 0 (in-result rows) | 4 (in-result rows) | 0 (in-result rows) |
| markdown | X1-3 | 0 (in-result rows) | 3 (in-result rows) | 0 (in-result rows) |
| mistune | A | 0 (in-result rows) | 0 (in-result rows) | 0 (in-result rows) |
| mistune | X1-0 | 0 (in-result rows) | 4 (in-result rows) | 0 (in-result rows) |
| mistune | X1-1 | 0 (in-result rows) | 5 (in-result rows) | 0 (in-result rows) |
| mistune | X1-2 | 0 (in-result rows) | 5 (in-result rows) | 0 (in-result rows) |
| mistune | X1-3 | 0 (in-result rows) | 6 (in-result rows) | 0 (in-result rows) |
| more_itertools | A | 0 (in-result rows) | 0 (in-result rows) | 0 (in-result rows) |
| more_itertools | X1-0 | 0 (in-result rows) | 2 (in-result rows) | 0 (in-result rows) |
| more_itertools | X1-1 | 0 (in-result rows) | 3 (in-result rows) | 0 (in-result rows) |
| more_itertools | X1-2 | 0 (in-result rows) | 3 (in-result rows) | 0 (in-result rows) |
| more_itertools | X1-3 | 0 (in-result rows) | 4 (in-result rows) | 0 (in-result rows) |
| pyparsing | A | 0 (in-result rows) | 0 (in-result rows) | 0 (in-result rows) |
| pyparsing | X1-0 | 0 (in-result rows) | 2 (in-result rows) | 0 (in-result rows) |
| pyparsing | X1-1 | 0 (in-result rows) | 2 (in-result rows) | 0 (in-result rows) |
| pyparsing | X1-2 | 0 (in-result rows) | 4 (in-result rows) | 0 (in-result rows) |
| pyparsing | X1-3 | 0 (in-result rows) | 3 (in-result rows) | 0 (in-result rows) |
| sortedcontainers | A | 0 (in-result rows) | 0 (in-result rows) | 0 (in-result rows) |
| sortedcontainers | X1-0 | 0 (in-result rows) | 0 (in-result rows) | 0 (in-result rows) |
| sortedcontainers | X1-1 | 0 (in-result rows) | 2 (in-result rows) | 0 (in-result rows) |
| sortedcontainers | X1-2 | 0 (in-result rows) | 6 (in-result rows) | 0 (in-result rows) |
| sortedcontainers | X1-3 | 0 (in-result rows) | 3 (in-result rows) | 0 (in-result rows) |
| sqlparse | A | 0 (in-result rows) | 0 (in-result rows) | 0 (in-result rows) |
| sqlparse | X1-0 | 0 (in-result rows) | 4 (in-result rows) | 0 (in-result rows) |
| sqlparse | X1-1 | 0 (in-result rows) | 4 (in-result rows) | 0 (in-result rows) |
| sqlparse | X1-2 | 0 (in-result rows) | 5 (in-result rows) | 0 (in-result rows) |
| sqlparse | X1-3 | 0 (in-result rows) | 5 (in-result rows) | 0 (in-result rows) |
| tomli | A | 0 (in-result rows) | 0 (in-result rows) | 0 (in-result rows) |
| tomli | X1-0 | 0 (in-result rows) | 4 (in-result rows) | 0 (in-result rows) |
| tomli | X1-1 | 0 (in-result rows) | 4 (in-result rows) | 0 (in-result rows) |
| tomli | X1-2 | 0 (in-result rows) | 6 (in-result rows) | 0 (in-result rows) |
| tomli | X1-3 | 0 (in-result rows) | 4 (in-result rows) | 0 (in-result rows) |
| all libraries | A | 0 (in-result rows) | 0 (in-result rows) | 0 (in-result rows) |
| all libraries | X1-0 | 0 (in-result rows) | 23 (in-result rows) | 0 (in-result rows) |
| all libraries | X1-1 | 0 (in-result rows) | 27 (in-result rows) | 0 (in-result rows) |
| all libraries | X1-2 | 0 (in-result rows) | 35 (in-result rows) | 0 (in-result rows) |
| all libraries | X1-3 | 0 (in-result rows) | 31 (in-result rows) | 0 (in-result rows) |

### Every idea the lanes generated (all audit rows)

| library | configuration | self (all audit rows) | cross (all audit rows) | target not found (all audit rows) |
| --- | --- | --- | --- | --- |
| idna | A | 0 (all audit rows) | 0 (all audit rows) | 0 (all audit rows) |
| idna | X1-0 | 3 (all audit rows) | 7 (all audit rows) | 0 (all audit rows) |
| idna | X1-1 | 2 (all audit rows) | 5 (all audit rows) | 0 (all audit rows) |
| idna | X1-2 | 1 (all audit rows) | 3 (all audit rows) | 0 (all audit rows) |
| idna | X1-3 | 1 (all audit rows) | 6 (all audit rows) | 0 (all audit rows) |
| markdown | A | 0 (all audit rows) | 0 (all audit rows) | 0 (all audit rows) |
| markdown | X1-0 | 1 (all audit rows) | 7 (all audit rows) | 0 (all audit rows) |
| markdown | X1-1 | 1 (all audit rows) | 6 (all audit rows) | 0 (all audit rows) |
| markdown | X1-2 | 0 (all audit rows) | 7 (all audit rows) | 0 (all audit rows) |
| markdown | X1-3 | 0 (all audit rows) | 10 (all audit rows) | 0 (all audit rows) |
| mistune | A | 0 (all audit rows) | 0 (all audit rows) | 0 (all audit rows) |
| mistune | X1-0 | 0 (all audit rows) | 10 (all audit rows) | 0 (all audit rows) |
| mistune | X1-1 | 0 (all audit rows) | 8 (all audit rows) | 0 (all audit rows) |
| mistune | X1-2 | 0 (all audit rows) | 7 (all audit rows) | 0 (all audit rows) |
| mistune | X1-3 | 0 (all audit rows) | 8 (all audit rows) | 0 (all audit rows) |
| more_itertools | A | 0 (all audit rows) | 0 (all audit rows) | 0 (all audit rows) |
| more_itertools | X1-0 | 4 (all audit rows) | 3 (all audit rows) | 0 (all audit rows) |
| more_itertools | X1-1 | 1 (all audit rows) | 3 (all audit rows) | 0 (all audit rows) |
| more_itertools | X1-2 | 0 (all audit rows) | 11 (all audit rows) | 0 (all audit rows) |
| more_itertools | X1-3 | 0 (all audit rows) | 5 (all audit rows) | 0 (all audit rows) |
| pyparsing | A | 0 (all audit rows) | 0 (all audit rows) | 0 (all audit rows) |
| pyparsing | X1-0 | 0 (all audit rows) | 10 (all audit rows) | 0 (all audit rows) |
| pyparsing | X1-1 | 2 (all audit rows) | 7 (all audit rows) | 0 (all audit rows) |
| pyparsing | X1-2 | 0 (all audit rows) | 6 (all audit rows) | 0 (all audit rows) |
| pyparsing | X1-3 | 2 (all audit rows) | 5 (all audit rows) | 0 (all audit rows) |
| sortedcontainers | A | 0 (all audit rows) | 0 (all audit rows) | 0 (all audit rows) |
| sortedcontainers | X1-0 | 6 (all audit rows) | 1 (all audit rows) | 0 (all audit rows) |
| sortedcontainers | X1-1 | 0 (all audit rows) | 4 (all audit rows) | 0 (all audit rows) |
| sortedcontainers | X1-2 | 0 (all audit rows) | 9 (all audit rows) | 0 (all audit rows) |
| sortedcontainers | X1-3 | 0 (all audit rows) | 4 (all audit rows) | 0 (all audit rows) |
| sqlparse | A | 0 (all audit rows) | 0 (all audit rows) | 0 (all audit rows) |
| sqlparse | X1-0 | 0 (all audit rows) | 9 (all audit rows) | 0 (all audit rows) |
| sqlparse | X1-1 | 2 (all audit rows) | 5 (all audit rows) | 0 (all audit rows) |
| sqlparse | X1-2 | 0 (all audit rows) | 6 (all audit rows) | 0 (all audit rows) |
| sqlparse | X1-3 | 0 (all audit rows) | 6 (all audit rows) | 0 (all audit rows) |
| tomli | A | 0 (all audit rows) | 0 (all audit rows) | 0 (all audit rows) |
| tomli | X1-0 | 0 (all audit rows) | 5 (all audit rows) | 0 (all audit rows) |
| tomli | X1-1 | 0 (all audit rows) | 6 (all audit rows) | 0 (all audit rows) |
| tomli | X1-2 | 0 (all audit rows) | 11 (all audit rows) | 0 (all audit rows) |
| tomli | X1-3 | 1 (all audit rows) | 7 (all audit rows) | 0 (all audit rows) |
| all libraries | A | 0 (all audit rows) | 0 (all audit rows) | 0 (all audit rows) |
| all libraries | X1-0 | 14 (all audit rows) | 52 (all audit rows) | 0 (all audit rows) |
| all libraries | X1-1 | 8 (all audit rows) | 44 (all audit rows) | 0 (all audit rows) |
| all libraries | X1-2 | 1 (all audit rows) | 60 (all audit rows) | 0 (all audit rows) |
| all libraries | X1-3 | 4 (all audit rows) | 51 (all audit rows) | 0 (all audit rows) |

## Appendix: per-library raw good counts

| library | configuration | good corrected | good strict | as coded (reading-order artifact) |
| --- | --- | --- | --- | --- |
| idna | A | 4 | - | 4 |
| idna | X1-0 | 3 | 2 | 2 |
| idna | X1-1 | 3 | 3 | 3 |
| idna | X1-2 | 3 | 3 | 3 |
| idna | X1-3 | 3 | 2 | 1 |
| idna | X1-4 | - | - | - |
| markdown | A | 5 | - | 5 |
| markdown | X1-0 | 3 | 1 | 0 |
| markdown | X1-1 | 4 | 2 | 2 |
| markdown | X1-2 | 3 | 2 | 2 |
| markdown | X1-3 | 3 | 2 | 1 |
| markdown | X1-4 | - | - | - |
| mistune | A | 5 | - | 5 |
| mistune | X1-0 | 3 | 2 | 0 |
| mistune | X1-1 | 5 | 3 | 3 |
| mistune | X1-2 | 3 | 2 | 2 |
| mistune | X1-3 | 3 | 2 | 2 |
| mistune | X1-4 | - | - | - |
| more_itertools | A | 5 | - | 5 |
| more_itertools | X1-0 | 3 | 3 | 3 |
| more_itertools | X1-1 | 5 | 5 | 5 |
| more_itertools | X1-2 | 2 | 2 | 2 |
| more_itertools | X1-3 | 4 | 3 | 3 |
| more_itertools | X1-4 | - | - | - |
| pyparsing | A | 4 | - | 4 |
| pyparsing | X1-0 | 3 | 2 | 2 |
| pyparsing | X1-1 | 3 | 2 | 1 |
| pyparsing | X1-2 | 3 | 3 | 2 |
| pyparsing | X1-3 | 4 | 4 | 3 |
| pyparsing | X1-4 | - | - | - |
| sortedcontainers | A | 4 | - | 4 |
| sortedcontainers | X1-0 | 3 | 3 | 3 |
| sortedcontainers | X1-1 | 4 | 4 | 4 |
| sortedcontainers | X1-2 | 3 | 3 | 0 |
| sortedcontainers | X1-3 | 3 | 3 | 3 |
| sortedcontainers | X1-4 | - | - | - |
| sqlparse | A | 5 | - | 5 |
| sqlparse | X1-0 | 4 | 3 | 2 |
| sqlparse | X1-1 | 4 | 3 | 3 |
| sqlparse | X1-2 | 3 | 3 | 2 |
| sqlparse | X1-3 | 3 | 2 | 2 |
| sqlparse | X1-4 | - | - | - |
| tomli | A | 5 | - | 5 |
| tomli | X1-0 | 4 | 3 | 3 |
| tomli | X1-1 | 4 | 4 | 3 |
| tomli | X1-2 | 3 | 3 | 1 |
| tomli | X1-3 | 3 | 2 | 2 |
| tomli | X1-4 | - | - | - |
