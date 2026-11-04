# X1 ideas: markdown, X1-2

Floor 2.0%; ceilings predicted from E1's profile.

These rows are the raw list behind unique mechanisms and the share new to today's generator (upper bound, the dedupe under-merges (O39)).

| # | title | mechanism | target lines | ceiling | audit | duplicate of | trial | gain / floor | op count | lane | model | returned |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Skip sorted-check overhead in Registry.__getitem__ for int keys via fast path | precompute_or_cache | markdown/treeprocessors.py\:135-138 | - | infeasible | Hoist inline pattern registry lookup out of the per-pattern loop in __handleInline (X1-0) | - | - | - | obvious | claude-sonnet-5-5 | True |
| 2 | Replace stack.pop(0) with deque in InlineProcessor.run and drop redundant list(node) scans | data_structure | markdown/treeprocessors.py\:376-376 | - | infeasible | Use collections.deque or index pointer for the work stack in InlineProcessor.run (X1-1) | - | - | - | obvious | claude-sonnet-5-5 | True |
| 3 | Cache per-pattern compiled regex and ancestor-exclude checks in __applyPattern | precompute_or_cache | markdown/treeprocessors.py\:274-277 | - | infeasible | Avoid per-call lower() and tag work in __applyPattern for ancestor excludes (X1-0) | - | - | - | obvious | claude-sonnet-5-5 | True |
| 4 | Abbr iter_element\: avoid list(parent).index and skip regex on text-less nodes | remove_work | markdown/extensions/abbr.py\:119-121 | - | - | - | - | - | - | obvious | claude-sonnet-5-5 | True |
| 5 | Skip child/tail reprocessing loops in __applyPattern for nodes with no children, text or tail | remove_work | markdown/treeprocessors.py\:310-312 | - | feasible | - | - | - | - | eliminate | claude-sonnet-5-5 | True |
| 6 | Avoid per-iteration list copy and index scan in __processPlaceholders for Element nodes without text or tail | specialised_fast_path | markdown/treeprocessors.py\:222-224 | - | - | - | - | - | - | eliminate | claude-sonnet-5-5 | False |
| 7 | Skip placeholder scanning for text that contains no placeholder prefix in __processPlaceholders | specialised_fast_path | markdown/treeprocessors.py\:210-212 | - | infeasible | Optimize __processPlaceholders and __build_ancestors with early exits and cached lookups (A) | - | - | - | assume_less | claude-sonnet-5-5 | True |
| 8 | Cache sorted inline pattern list as a plain Python list in InlineProcessor instead of Registry.__getitem__ per index | precompute_or_cache | markdown/treeprocessors.py\:134-137 | - | infeasible | Hoist inline pattern registry lookup out of the per-pattern loop in __handleInline (X1-0) | - | - | - | assume_less | claude-sonnet-5-5 | False |
| 9 | Avoid re-walking whole tree in abbr iter_element via early skip of empty-text, tail-less leaf elements | specialised_fast_path | markdown/extensions/abbr.py\:111-112 | - | unknown | - | - | - | - | assume_less | claude-sonnet-5-5 | False |
| 10 | Cache lowercased tag in serializer\: replace tag.lower() list-membership checks with one lower call | remove_work | markdown/serializers.py\:163-166 | - | - | - | - | - | - | assume_less | claude-sonnet-5-5 | False |
| 11 | Build parent_map without iterating every element twice; reuse a single pass in InlineProcessor.run | precompute_or_cache | markdown/treeprocessors.py\:340-344 | - | infeasible | Drop the per-node parent_map walk in InlineProcessor.run by carrying the ancestor chain down the work stack (X1-1) | - | - | - | name_the_problem | claude-sonnet-5-5 | False |
| 12 | Fuse the three text-only checks in __processPlaceholders into a fast return when data has no placeholder prefix | specialised_fast_path | markdown/treeprocessors.py\:210-211 | - | - | - | - | - | - | name_the_problem | claude-sonnet-5-5 | False |
| 13 | Skip placeholder-processing machinery for child tails/texts without placeholder prefix in InlineProcessor.run | specialised_fast_path | markdown/treeprocessors.py\:398-401 | - | - | - | - | - | - | recombine | claude-sonnet-5-5 | False |
| 14 | Fuse parent_map construction and avoid rebuilding ancestors by storing ancestors with queue entries | algorithm | markdown/treeprocessors.py\:378-379 | - | infeasible | Drop the per-node parent_map walk in InlineProcessor.run by carrying the ancestor chain down the work stack (X1-1) | - | - | - | recombine | claude-sonnet-5-5 | False |
| 15 | Skip per-child list(currElement).index scan for tails in InlineProcessor.run | remove_work | markdown/treeprocessors.py\:404-406 | - | feasible | - | - | - | - | resolve_tradeoff | claude-sonnet-5-5 | True |
| 16 | Avoid rebuilding ancestor chain and list copy for leaf-only elements in __build_ancestors/run | precompute_or_cache | markdown/treeprocessors.py\:378-379 | - | - | - | - | - | - | resolve_tradeoff | claude-sonnet-5-5 | False |
| 17 | Prettify\: precompute block-level set for is_block_level lookups | precompute_or_cache | markdown/treeprocessors.py\:431-433 | - | - | - | - | - | - | resolve_tradeoff | claude-sonnet-5-5 | False |
| 18 | Skip empty/placeholder-free checks\: replace Registry.__getitem__ int path in __handleInline with a pre-snapshotted pattern list | specialised_fast_path | markdown/util.py\:335-338 | - | - | - | - | - | - | far | claude-sonnet-5-5 | False |
| 19 | Skip inline patterns whose required trigger character is absent from the text in __handleInline | specialised_fast_path | markdown/treeprocessors.py\:135-138 | - | - | - | - | - | - | leap | claude-opus-5-5 | False |

## Proposals (rule-relaxing, never scored or trialled)

| title | relaxes | lane | model | returned | rationale |
| --- | --- | --- | --- | --- | --- |
