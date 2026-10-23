# Live hard corpus

Repositories that `tests/live/test_hard_corpus_live.py` copies one at a time
into a temporary git repository and hands to the real engine, as the benchmark
corpus in `../live_corpus` is handled (same conventions: stdlib only, a
deterministic workload `python -m <package>.main`, a unittest suite run with
`python -m unittest discover -s tests -t .`, a README with no hint of the fix).
They are data, not engine tests: the root `conftest.py` never collects them and
mypy skips them. `tests/live/test_hard_corpus_guards.py` checks them offline.

- `multi` (`shipmerge`, `ledgerclose`, `deliveryround`): two or three
  independent hot spots. `_solutions/<name>.patch` removes all of them, and
  `<name>.part<k>.patch` removes hot spot `k` alone. `fix_gain` in the manifest
  is a gain that only removing every hot spot reaches: the guards prove the full
  fix reaches it and every fix that leaves one hot spot in place does not.
- `large` (`invoicekit`, `fleetsim`, `textindex`): about 800-900 lines over ten
  or more modules; the cost sits in a module the workload's `main.py` does not
  import.
- `trap` (`topicmerge`, `sensormean`): the obvious fix changes the printed
  output (set iteration order; float summation order) while the tests still
  pass, so only the equivalence judge can reject it. `<name>.naive.patch` holds
  that naive fix; the guards prove it changes stdout and keeps the tests green.
- `memory` (`eventagg`, `distmatrix`): the run's objective is minimize peak RSS;
  the reference fix cuts the workload's peak RSS by well over 30% with identical
  output.

`manifest.json` lists every repository with its category, goal, `fix_gain` and
two candidate hypotheses (one aimed at the real cost, one neutral or wrong), so
the aimed, blind and decoy modes (`LIVE_CORPUS_MODE`) all apply.
