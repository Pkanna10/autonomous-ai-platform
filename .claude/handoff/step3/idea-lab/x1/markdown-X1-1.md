# X1 ideas: markdown, X1-1

Floor 2.0%; ceilings predicted from E1's profile.

These rows are the raw list behind unique mechanisms and the share new to today's generator (upper bound, the dedupe under-merges (O39)).

| # | title | mechanism | target lines | ceiling | audit | duplicate of | trial | gain / floor | op count | lane | model | returned |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Skip Registry sort check by snapshotting inline patterns once per InlineProcessor.run | precompute_or_cache | markdown/treeprocessors.py\:136-138 | 49.6% | infeasible | Hoist inline pattern registry lookup out of the per-pattern loop in __handleInline (X1-0) | - | - | - | obvious | claude-sonnet-5-5 | True |
| 2 | Use collections.deque or index pointer for the work stack in InlineProcessor.run | data_structure | markdown/treeprocessors.py\:376-376 | 62.1% | feasible | - | - | - | - | obvious | claude-sonnet-5-5 | True |
| 3 | Avoid per-call list copies and lowercasing in __applyPattern ancestor-exclusion check | remove_work | markdown/treeprocessors.py\:276-278 | 36.2% | infeasible | Avoid per-call lower() and tag work in __applyPattern for ancestor excludes (X1-0) | - | - | - | obvious | claude-sonnet-5-5 | True |
| 4 | Make abbr iter_element avoid list(parent).index and run regex only when text could match | remove_work | markdown/extensions/abbr.py\:119-121 | - | - | - | - | - | - | obvious | claude-sonnet-5-5 | True |
| 5 | Skip the tail-index search in InlineProcessor.run when no tail placeholders were created | specialised_fast_path | markdown/treeprocessors.py\:404-405 | 62.1% | - | - | - | - | - | obvious | claude-sonnet-5-5 | True |
| 6 | Remove always-false isString(node) guard inside __applyPattern's child loop | remove_work | markdown/treeprocessors.py\:307-311 | 36.2% | - | - | - | - | - | eliminate | claude-sonnet-5 | False |
| 7 | Collapse membership-check-then-get into a single dict lookup in __processPlaceholders | remove_work | markdown/treeprocessors.py\:214-215 | 6.1% | - | - | - | - | - | eliminate | claude-sonnet-5 | False |
| 8 | Drop redundant inner None-check inside InlineProcessor.__build_ancestors loop | remove_work | markdown/treeprocessors.py\:341-344 | 3.0% | - | - | - | - | - | eliminate | claude-sonnet-5 | False |
| 9 | Cache tag.lower() once per element in _serialize_html instead of recomputing it twice | remove_work | markdown/serializers.py\:158-163 | - | - | - | - | - | - | eliminate | claude-sonnet-5 | False |
| 10 | Drop the per-node parent_map walk in InlineProcessor.run by carrying the ancestor chain down the work stack | remove_work | markdown/treeprocessors.py\:379-379 | 62.1% | feasible | - | - | - | - | assume_less | claude-haiku-5-5 | True |
| 11 | Required-character prefilter per inline pattern in InlineProcessor.__handleInline to skip patterns that cannot match | specialised_fast_path | markdown/treeprocessors.py\:135-140 | 49.6% | - | - | - | - | - | name_the_problem | claude-opus-5-5 | False |
| 12 | Whole-node early exit in __handleInline when the text contains no inline-markup trigger character at all | specialised_fast_path | markdown/treeprocessors.py\:132-135 | 49.6% | unknown | - | - | - | - | name_the_problem | claude-opus-5-5 | False |
| 13 | Keep a sorted item list inside Registry so __getitem__ by int is a single list index | precompute_or_cache | markdown/util.py\:341-343 | 10.0% | infeasible | Make Registry __getitem__ cheaper by caching the sorted list and fast-pathing string-key lookup (A) | - | - | - | recombine | claude-fable-5 | False |
| 14 | Cache per-pattern compiled regex and new-style flag in InlineProcessor instead of re-deriving per match attempt | precompute_or_cache | markdown/treeprocessors.py\:280-285 | 36.2% | - | - | - | - | - | recombine | claude-fable-5 | False |
| 15 | Replace regex placeholder parsing in __processPlaceholders with fixed-width slicing and a regex fallback | specialised_fast_path | markdown/treeprocessors.py\:210-212 | 6.1% | - | - | - | - | - | recombine | claude-fable-5 | False |
| 16 | Bypass __processPlaceholders and dummy-element machinery when inline output contains no placeholder prefix | remove_work | markdown/treeprocessors.py\:389-391 | 62.1% | - | - | - | - | - | recombine | claude-fable-5 | False |
| 17 | Hoist repeated tag.lower() and attribute sorting overhead out of _serialize_html's per-element path | loop_or_control_flow | markdown/serializers.py\:158-163 | - | - | - | - | - | - | recombine | claude-fable-5 | False |
| 18 | Plain-text fast path in InlineProcessor.__handleInline\: skip all patterns when no trigger character is present | specialised_fast_path | markdown/treeprocessors.py\:132-134 | 49.6% | - | - | - | - | - | resolve_tradeoff | claude-fable-5-1 | False |
| 19 | Skip __processPlaceholders in InlineProcessor.run when the handled text contains no inline placeholder prefix | specialised_fast_path | markdown/treeprocessors.py\:389-391 | 62.1% | - | - | - | - | - | resolve_tradeoff | claude-fable-5-1 | False |
| 20 | Replace the parent_map chain walk in __build_ancestors with a single tag append, since parents already carry the chain | remove_work | markdown/treeprocessors.py\:341-344 | 3.0% | infeasible | Drop the per-node parent_map walk in InlineProcessor.run by carrying the ancestor chain down the work stack (X1-1) | - | - | - | resolve_tradeoff | claude-fable-5-1 | False |
| 21 | Registry keeps a materialised sorted item list so __getitem__ by index and __iter__ are a single list access | data_structure | markdown/util.py\:341-343 | 10.0% | infeasible | Make Registry __getitem__ cheaper by caching the sorted list and fast-pathing string-key lookup (A) | - | - | - | resolve_tradeoff | claude-fable-5-1 | True |
| 22 | Skip inline pattern scan for text without trigger characters via per-pattern prefilter in __handleInline | remove_work | markdown/treeprocessors.py\:135-138 | 49.6% | - | - | - | - | - | far | claude-sonnet-5-5 | False |
| 23 | Replace Registry.__getitem__ in the pattern loop with a cached tuple of patterns in __handleInline | precompute_or_cache | markdown/util.py\:335-337 | 10.0% | infeasible | Make Registry __getitem__ cheaper by caching the sorted list and fast-pathing string-key lookup (A) | - | - | - | far | claude-sonnet-5-5 | False |
| 24 | Cache lowercased tag names to avoid repeated str.lower in ancestors building and serializer | remove_work | markdown/serializers.py\:162-164 | - | feasible | - | - | - | - | far | claude-sonnet-5-5 | True |
| 25 | Trigger-character prefilter in __handleInline\: skip inline patterns whose required literal char is absent from the text | specialised_fast_path | markdown/treeprocessors.py\:135-140 | 49.6% | infeasible | Cache the ordered inline pattern list and skip patterns that cannot match in __applyPattern (A) | - | - | - | leap | claude-opus-5-5 | True |
| 26 | Carry ancestor tags down the InlineProcessor.run stack; drop whole-tree parent_map and __build_ancestors walks | remove_work | markdown/treeprocessors.py\:372-376 | 62.1% | - | - | - | - | - | leap | claude-opus-5-5 | False |

## Proposals (rule-relaxing, never scored or trialled)

| title | relaxes | lane | model | returned | rationale |
| --- | --- | --- | --- | --- | --- |
