# X1 ideas: markdown, X1-0

Floor 2.0%; ceilings predicted from E1's profile.

These rows are the raw list behind unique mechanisms and the share new to today's generator (upper bound, the dedupe under-merges (O39)).

| # | title | mechanism | target lines | ceiling | audit | duplicate of | trial | gain / floor | op count | lane | model | returned |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Hoist inline pattern registry lookup out of the per-pattern loop in __handleInline | precompute_or_cache | markdown/treeprocessors.py\:134-137 | - | feasible | - | - | - | - | obvious | claude-sonnet-5-5 | True |
| 2 | Avoid per-call lower() and tag work in __applyPattern for ancestor excludes | remove_work | markdown/treeprocessors.py\:276-278 | - | feasible | - | - | - | - | obvious | claude-sonnet-5-5 | True |
| 3 | Replace stack.pop(0) with a deque and drop per-element list copies in InlineProcessor.run | data_structure | markdown/treeprocessors.py\:376-376 | - | infeasible | Use collections.deque or index pointer for the work stack in InlineProcessor.run (X1-1) | - | - | - | obvious | claude-sonnet-5-5 | True |
| 4 | Skip abbr regex scanning and list copies in AbbrTreeprocessor.iter_element when no match exists | remove_work | markdown/extensions/abbr.py\:118-120 | - | - | - | - | - | - | obvious | claude-sonnet-5-5 | True |
| 5 | Skip __processPlaceholders and dummy Element when inline result has no placeholder prefix | remove_work | markdown/treeprocessors.py\:398-403 | - | - | - | - | - | - | eliminate | claude-sonnet-5-5 | False |
| 6 | Cache sorted-state fast path in Registry.__getitem__ for int keys | specialised_fast_path | markdown/util.py\:335-341 | - | - | - | - | - | - | eliminate | claude-sonnet-5-5 | False |
| 7 | Skip abbr tail processing list(parent).index when tail has no regex match | remove_work | markdown/extensions/abbr.py\:118-121 | - | infeasible | Abbr treeprocessor\: compute the sibling index only when the tail actually contains an abbreviation (X1-3) | - | - | - | eliminate | claude-sonnet-5-5 | False |
| 8 | Cache sorted Registry list so __getitem__ by int skips _sort and NamedTuple lookup | precompute_or_cache | markdown/util.py\:335-342 | - | - | - | - | - | - | assume_less | claude-sonnet-5-5 | False |
| 9 | Skip quick no-match patterns in __handleInline using cheap substring prefilter | remove_work | markdown/treeprocessors.py\:136-140 | - | infeasible | Cache the ordered inline pattern list and skip patterns that cannot match in __applyPattern (A) | - | - | - | assume_less | claude-sonnet-5-5 | True |
| 10 | Avoid list(parent).index in abbr tail handling; only compute index when a match exists | remove_work | markdown/extensions/abbr.py\:118-121 | - | - | - | - | - | - | assume_less | claude-sonnet-5-5 | False |
| 11 | Skip AbbrTreeprocessor regex via cheap prefilter and avoid list(parent).index for tails | remove_work | markdown/extensions/abbr.py\:118-121 | - | infeasible | Abbr treeprocessor\: compute the sibling index only when the tail actually contains an abbreviation (X1-3) | - | - | - | name_the_problem | claude-sonnet-5-5 | False |
| 12 | Replace list(node).index(child) lookups in InlineProcessor.run tail handling with an enumerated position | remove_work | markdown/treeprocessors.py\:404-406 | - | infeasible | Skip per-child list(currElement).index scan for tails in InlineProcessor.run (X1-2) | - | - | - | name_the_problem | claude-sonnet-5-5 | True |
| 13 | Make Registry.__getitem__ int fast path avoid isinstance slice check and _sort call | precompute_or_cache | markdown/util.py\:335-338 | - | infeasible | Make Registry __getitem__ cheaper by caching the sorted list and fast-pathing string-key lookup (A) | - | - | - | name_the_problem | claude-sonnet-5-5 | False |
| 14 | Skip serialization escaping calls by fast-path tag checks in _serialize_html | remove_work | markdown/serializers.py\:162-166 | - | - | - | - | - | - | name_the_problem | claude-sonnet-5-5 | False |
| 15 | Memoise per-pattern ancestor-exclude check with precomputed lowercase tuples in __applyPattern | specialised_fast_path | markdown/treeprocessors.py\:274-278 | - | infeasible | Avoid per-call lower() and tag work in __applyPattern for ancestor excludes (X1-0) | - | - | - | recombine | claude-sonnet-5-5 | False |
| 16 | Cache sorted registry data so Registry.__getitem__ int lookups skip the _sort call and double indexing | precompute_or_cache | markdown/util.py\:335-342 | - | - | - | - | - | - | resolve_tradeoff | claude-sonnet-5-5 | False |
| 17 | Skip build_ancestors parent walk by computing ancestors incrementally from the parent's list in InlineProcessor.run | remove_work | markdown/treeprocessors.py\:378-379 | - | - | - | - | - | - | resolve_tradeoff | claude-sonnet-5-5 | False |
| 18 | Fast-path __processPlaceholders for text without placeholder prefix | specialised_fast_path | markdown/treeprocessors.py\:210-211 | - | - | - | - | - | - | resolve_tradeoff | claude-sonnet-5-5 | False |
| 19 | Cache sorted pattern list in Registry so __getitem__ skips _sort and isinstance checks on int keys | precompute_or_cache | markdown/util.py\:341-343 | - | infeasible | Make Registry __getitem__ cheaper by caching the sorted list and fast-pathing string-key lookup (A) | - | - | - | far | claude-sonnet-5-5 | True |
| 20 | Skip full-tree abbr regex work by testing for abbreviation presence per text with a cheap precheck | remove_work | markdown/extensions/abbr.py\:118-120 | - | - | - | - | - | - | far | claude-sonnet-5-5 | False |
| 21 | Avoid repeated list(node).index in inline tail handling by tracking position during run | algorithm | markdown/treeprocessors.py\:404-405 | - | feasible | - | - | - | - | far | claude-sonnet-5-5 | False |
| 22 | Trigger-substring prefilter\: skip inline patterns whose required literal is absent from the text in __handleInline | specialised_fast_path | markdown/treeprocessors.py\:135-140 | - | - | - | - | - | - | leap | claude-opus-5-5 | False |

## Proposals (rule-relaxing, never scored or trialled)

| title | relaxes | lane | model | returned | rationale |
| --- | --- | --- | --- | --- | --- |
