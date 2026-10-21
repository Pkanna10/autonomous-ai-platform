"""dedupe: the end-to-end fixture project for the improvement engine.

A tiny CPU-bound Python project with one known efficiency win. It uses the
standard library only and runs on Python 3.11+ on Linux and macOS. The engine
tests copy this directory (without ``__pycache__``), ``git init`` it and run
the engine against it.

Layout:

- ``dedupe/core.py``: ``unique_in_order(items)``, the hot path. It tests
  membership against the result list, O(n) per lookup.
- ``dedupe/main.py``: the workload, ``python -m dedupe.main [COUNT]``
  (default 15,000 items). The input comes from a fixed-seed 64-bit LCG, and
  stdout is a digest of the result (sizes, first and last five values,
  sha256 of the joined values), so the output fingerprint is deterministic.
- ``tests/``: the suite, ``python -m unittest discover -s tests -t .``. It
  pins set semantics and the order of ascending input, but not
  first-occurrence order on unsorted input.

Edit sets live in ``tests/fixtures/dedupe_edits/<title>/`` and the scripted
editor applies them. ``files/<repo-relative path>`` is copied over the repo
(create or replace). An optional ``_delete`` file lists repo-relative paths
to delete, one per line. An optional ``_symlink`` file lists one link per
line as ``<repo-relative link path>``, a TAB, then ``<target>``; the target
is the literal link text, relative to the link's directory.

- ``h1``: membership in a set. Same output, about 12x faster: keep.
- ``h2``: h1 plus deleting ``tests/test_core.py``: ``protected_path``,
  rejected before it runs.
- ``h3``: ``sorted(set(items))``. Faster and the tests pass, but the output
  order changes: the equivalence judge fails, reject.
- ``h5``: ``list(dict.fromkeys(items))``. Same output and also a win, but it
  rewrites the lines h1 changes, so it conflicts with h1 in combine.
- ``h6``: h1 plus a symlink ``dedupe/fast.py`` -> ``core.py``:
  ``forbidden_file_mode``, rejected before it runs.

Measured on the 4-vCPU dev host (one warm-up, then 5 runs, Python 3.11 and
3.13): baseline 0.59-0.70 s, h1, h3 and h5 0.04-0.05 s.
"""
