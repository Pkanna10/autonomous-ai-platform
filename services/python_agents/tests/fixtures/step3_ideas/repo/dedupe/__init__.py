"""dedupe, one quadratic hot path: the idea-pipeline E2E fixture (Step 3 Wave 2, N5).

The Step 3 ``dedupe`` fixture grown for the idea pipeline. ``python -m
dedupe.main [COUNT]`` (default 12,000) de-duplicates generated integers in
order (``unique_in_order``, which asks ``contains`` to scan the result list
once per item: O(n^2)), sums the distinct values prefix by prefix
(``running_totals``) and counts the items in 4,096 even buckets
(``summarise`` sweeps the sorted items across ``bucket_bounds``). The two
scripted wins remove the same quadratic scan from different functions (a set
in ``unique_in_order``, ``dict.fromkeys`` in ``summarise``), so each alone
gains over 90 % and the two stack in combine without a conflict.
``bucket_bounds`` runs once per workload, the cold helper the Amdahl gate
drops. ``dedupe/main.py`` is the workload, so the engine protects it and
never shows it to a model; ``main`` builds the report inline so the profile
lists ten functions (the profiler's cap per workload) and ``bucket_bounds``
stays among the eight hottest by cumulative time (the hot functions an idea
may anchor in). The suite is ``python -m unittest discover -s tests -t .``;
it pins the totals and the bounds exactly, but not first-occurrence order on
unsorted input, nor the histogram of input with repeats.

Measured with cProfile, six runs each under CPython 3.11 and 3.13
(cumulative shares): ``summarise`` 99.2-99.5 %, ``unique_in_order``
98.2-99.0 %, ``contains`` 97.4-98.4 %, ``build_input`` 0.4-0.7 %,
``running_totals`` 0.13-0.37 %, ``bucket_bounds`` 0.08-0.22 %. Unprofiled the
workload runs 0.48-0.53 s under 3.11 and 1.0-1.05 s under 3.13; each win
gains 92.6-97.0 % (ABAB, five runs a side, four repeats per version). In 21
E2E scenarios (seven runs of tests/e2e/test_step3_ideas.py, four with the
workload on 3.11, three on 3.13) the calibrated floor read 2.0-24.4 %, every
look at a keep 90.7-96.6 % (3.9x the floor at the worst) and
``bucket_bounds`` at most 0.31 %.
"""
