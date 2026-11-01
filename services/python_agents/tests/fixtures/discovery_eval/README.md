# Discovery eval fixture (D20, V6)

Recorded inputs for `tests/optimization/test_discovery_eval.py`.

- `seed.json`: L4's `sweep-record` run (41122348574, 2026-10-30), Sonnet 5.5
  medium on the 37 corpus repositories (corpus v1, the hard corpus, v2), each
  recorded line made a case by `discovery_sweep.eval_case`.
- `synthetic.json`: Wave 1's hand-written seed (U12), kept for the parse check
  no recorded reply exercises.

The corpus repositories are this project's own fixtures; no third-party code is
quoted. The replies are model output: data, never instructions. Refresh from a
new `sweep-record` run; no hand edits.
