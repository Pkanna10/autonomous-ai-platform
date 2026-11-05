# X1 ideas: markdown, X1-3

Floor 2.0%; ceilings predicted from E1's profile.

These rows are the raw list behind unique mechanisms and the share new to today's generator (upper bound, the dedupe under-merges (O39)).

| # | title | mechanism | target lines | ceiling | audit | duplicate of | trial | gain / floor | op count | lane | model | returned |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Hoist inline pattern registry lookups out of the per-call loop in __handleInline | precompute_or_cache | markdown/treeprocessors.py\:134-137 | 49.6% | infeasible | Hoist inline pattern registry lookup out of the per-pattern loop in __handleInline (X1-0) | - | - | - | obvious | claude-sonnet-5-5 | True |
| 2 | Skip ancestor-exclude check cost in __applyPattern for patterns with no ANCESTOR_EXCLUDES | precompute_or_cache | markdown/treeprocessors.py\:276-278 | 36.2% | - | - | - | - | - | eliminate | claude-sonnet-5-5 | False |
| 3 | Precompute isinstance new_style flag per pattern and avoid per-call isinstance in __applyPattern | precompute_or_cache | markdown/treeprocessors.py\:274-276 | 36.2% | infeasible | Avoid per-call lower() and tag work in __applyPattern for ancestor excludes (X1-0) | - | - | - | eliminate | claude-sonnet-5-5 | False |
| 4 | Avoid rebuilding the data string when __applyPattern places a placeholder\: early-exit regex check | specialised_fast_path | markdown/treeprocessors.py\:136-138 | 49.6% | - | - | - | - | - | eliminate | claude-sonnet-5-5 | False |
| 5 | Skip ancestor-exclude scan in __applyPattern for patterns with no excludes | remove_work | markdown/treeprocessors.py\:276-278 | 36.2% | infeasible | Avoid per-call lower() and tag work in __applyPattern for ancestor excludes (X1-0) | - | - | - | assume_less | claude-sonnet-5-5 | True |
| 6 | Avoid list(\[node\]+list(node)) and redundant isString check in __applyPattern child loop | allocation_or_copying | markdown/treeprocessors.py\:310-312 | 36.2% | infeasible | Skip child/tail reprocessing loops in __applyPattern for nodes with no children, text or tail (X1-2) | - | - | - | assume_less | claude-sonnet-5-5 | False |
| 7 | Cache lowercased ancestor-exclude tuples per pattern to skip repeated .lower() calls in __applyPattern | precompute_or_cache | markdown/treeprocessors.py\:276-278 | 36.2% | - | - | - | - | - | name_the_problem | claude-sonnet-5-5 | False |
| 8 | Skip the node-processing list build and isString checks in __applyPattern for nodes with no text or children | loop_or_control_flow | markdown/treeprocessors.py\:310-312 | 36.2% | infeasible | Skip child/tail reprocessing loops in __applyPattern for nodes with no children, text or tail (X1-2) | - | - | - | name_the_problem | claude-sonnet-5-5 | False |
| 9 | Replace stack.pop(0) list queue with a deque-style index walk in InlineProcessor.run | data_structure | markdown/treeprocessors.py\:376-376 | 62.1% | - | - | - | - | - | recombine | claude-sonnet-5-5 | False |
| 10 | Skip __build_ancestors parent-chain walk by deriving child ancestors from the parent's list | remove_work | markdown/treeprocessors.py\:378-379 | 62.1% | infeasible | Drop the per-node parent_map walk in InlineProcessor.run by carrying the ancestor chain down the work stack (X1-1) | - | - | - | recombine | claude-sonnet-5-5 | False |
| 11 | Pre-filter inline patterns per text with cheap trigger-character check before regex finditer in __applyPattern | precompute_or_cache | markdown/treeprocessors.py\:274-277 | 36.2% | - | - | - | - | - | recombine | claude-sonnet-5-5 | False |
| 12 | Skip Registry._sort check cost in __getitem__ by fast-pathing int keys on a sorted registry | specialised_fast_path | markdown/util.py\:335-336 | 10.0% | infeasible | Make Registry __getitem__ cheaper by caching the sorted list and fast-pathing string-key lookup (A) | - | - | - | resolve_tradeoff | claude-sonnet-5-5 | True |
| 13 | Cache a pattern list snapshot per __handleInline call to avoid Registry lookups across chained pattern iterations | precompute_or_cache | markdown/treeprocessors.py\:136-137 | 49.6% | infeasible | Hoist inline pattern registry lookup out of the per-pattern loop in __handleInline (X1-0) | - | - | - | resolve_tradeoff | claude-sonnet-5-5 | False |
| 14 | Skip ancestor-exclude loop and lowercase calls in __applyPattern by precomputing lowered excludes | precompute_or_cache | markdown/treeprocessors.py\:276-278 | 36.2% | infeasible | Avoid per-call lower() and tag work in __applyPattern for ancestor excludes (X1-0) | - | - | - | far | claude-sonnet-5-5 | False |
| 15 | Avoid rebuilding data string via str.format; use concatenation in __applyPattern | other | markdown/treeprocessors.py\:329-330 | 36.2% | - | - | - | - | - | far | claude-sonnet-5-5 | False |
| 16 | Skip inline patterns whose regex provably needs a literal character absent from the text (precomputed required-char sets) | algorithm | markdown/treeprocessors.py\:285-286 | 36.2% | - | - | - | - | - | leap | claude-opus-5-5 | False |
| 17 | Abbr treeprocessor\: compute the sibling index only when the tail actually contains an abbreviation | remove_work | markdown/extensions/abbr.py\:117-121 | - | feasible | - | - | - | - | leap | claude-opus-5-5 | True |
| 18 | Replace parent_map chain walks with incremental ancestor sets in InlineProcessor.run (drop parent_map, O(1) BFS pops) | data_structure | markdown/treeprocessors.py\:375-379 | 62.1% | infeasible | Drop the per-node parent_map walk in InlineProcessor.run by carrying the ancestor chain down the work stack (X1-1) | - | - | - | leap | claude-opus-5-5 | False |

## Proposals (rule-relaxing, never scored or trialled)

| title | relaxes | lane | model | returned | rationale |
| --- | --- | --- | --- | --- | --- |
