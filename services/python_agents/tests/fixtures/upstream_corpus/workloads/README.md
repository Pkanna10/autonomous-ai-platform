# Upstream corpus workloads (V9b)

One benchmark workload per candidate of the upstream performance-fix corpus (V9,
owner decision O20): `<id>.py` for each `id` in `../manifest.json`, installed
into the cloned repository as `benchmarks/bench_<lib>.py`, the way
`tests/live/oss.py` installs the OSS corpus workloads (the whole `benchmarks/`
directory is protected from trial edits). The attempter (the engine) reads the
copied file, so everything in it names the library only: the header is
`OSS corpus benchmark: <lib> ...`, as in `tests/fixtures/live_oss/workloads/`.

## What the writer saw (O19)

These workloads were written under the setter / attempter / marker rule (O19,
`CLAUDE.md`). The writer (Fable 5.1, a different model from the miner and from
the engine) saw the **before**-commit source trees of the candidates (the exam
questions), the candidate list naming the touched files and functions, and the
miner's ids. The writer did not open the maintainers' fixes (the sealed answer
keys), the clones' git history, any upstream changelog, commit or pull request,
and did not search the web for them.

**The ids are a leak the reader must know about.** The miner named each
candidate after its fix (`idna-uts46-ascii-fastpath`,
`packaging-marker-str-cache`, `sqlglot-unnest-type-memo`), so the writer was
blind to the diff, not to the idea, and shaped several inputs toward it (an
ASCII-heavy name list, a collision-heavy heading list). The 2026-10-30 review of
the first version also found that the module docstrings carried the touched
private functions and files and hints at the mechanism; they were rewritten (see
below). Live hits on the candidates whose id names the idea are to be reported
separately from the rest:

- idea-naming ids: `attrs-astuple-atomic`, `boltons-multireplace-lastgroup`,
  `idna-uts46-ascii-fastpath`, `markdown-inline-rescan`,
  `markdown-toc-unique-ids`, `markdown_it-inline-pending`,
  `mistune-footnote-membership`, `mistune-renderer-method-lookup`,
  `mpmath-bin-to-radix-pow2`, `mpmath-fpp2-exponent`,
  `networkx-edmonds-karp-reset`, `networkx-smallworld-has-path`,
  `packaging-marker-literal-eval`, `packaging-marker-str-cache`,
  `packaging-simple-version-fastpath`, `pycparser-no-early-peek`,
  `pyparsing-results-copy`, `pypdf-clone-direct-objects`,
  `soupsieve-tag-before-namespace`, `sqlglot-unnest-type-memo`,
  `sqlparse-group-comments`, `wcwidth-wcswidth-ascii`;
- area-naming ids (the function or feature only): `markdown-hash-header-regex`,
  `mistune-nested-lists`, `more_itertools-nth-permutation`,
  `networkx-full-rary-tree`, `pygments-html-format-lines`,
  `sqlglot-merge-subqueries`, `sqlparse-reindent-offset`,
  `tomlkit-inline-table-render`.

The line between the two groups is a judgement call; a second writer who sees
only the library and the touched paths could rewrite the first group's inputs
before a live run, if the owner wants a cleaner exam.

## What the copied file may say

The module docstring is prose the attempter reads. It describes the library, the
public calls and the input shape and size, nothing else: no private function
names, no file paths, no mechanism ("the ids are made unique", "every quoted
value is evaluated"), no input-distribution rationale ("most names are ASCII"),
and no word that says a known fix exists ("upstream", "exercises",
"maintainer"). `tests/live/test_upstream_guards.py` fails on a touched file or a
private touched function anywhere in the file, on a public touched function the
code does not itself call through the library's API, on any `.py` name other
than the bench file, and on a header other than `OSS corpus benchmark: <lib>`.
The coverage notes (which touched function each workload reaches, how, and the
measured share of the run) live in `../_notes/workloads.md`, beside the sealed
keys, and are never copied into a clone.

## Conventions (copied from `tests/fixtures/live_oss/workloads/`)

- `ROOT = Path(__file__).resolve().parents[1]` and `_checked()`: the library
  timed is exactly the checkout's package (`PACKAGE_INIT`), never an installed
  copy or a copy beside the script.
- Deterministic: a fixed `random.Random(seed)`, no clock, no network, no
  randomness without a seed; sets never reach the digest unordered.
- The output is one line ending in `sha256=<digest>` of the results, so the
  output-equivalence judge can compare runs; counts on the line help the Lead
  see what a run did.
- Sized by running each workload against its before-tree under CPython 3.11
  (2026-10-30, a 4-core container): 1 to 3.5 s each. The upstream suites run
  CPython 3.12 (`upstream.UPSTREAM_PYTHON`, inside every candidate's
  `requires_python`: the networkx before-trees need 3.12). Where the review
  found that the input never reached the shape the candidate's fix speeds up,
  the input was changed and the share of the run spent in that shape measured by
  ablation (`../_notes/workloads.md`); the Lead's CI verification
  (`upstream-verify`) measures the keys themselves.

## Admission: the key must pass the frozen judges first

No candidate reaches the engine until its own answer key has been measured on
its workload, by the marker and never by the attempter (the CI `upstream-verify`
suite, `tests/live/upstream_verify.py`, no Claude request): the key applied to
the before-tree as a commit beside it, the Step 3 noise calibration (A/A blocks,
floor `max(2 %, 2 x the largest gap)`), then three ABBA blocks of at least five
timed runs a side, and the project's own tests on both sides. It is verified
only if the gain of the pooled means clears `max(2 x floor, 10 %)`, both suites
pass, every run prints one and the same output digest and the licence text is
there. The Lead copies a verified row into the manifest's `verified` record (the
CI run id, gain, floor, threshold and this workload's sha256);
`upstream.live_cases` hands the live suite only such candidates, and a workload
resized after its verification no longer matches the record, so the manifest
refuses to load until the record is cleared or the candidate verified again.

## Dependencies outside the standard library

Most candidates need only the checkout on `PYTHONPATH` (root and `src/`).
Exceptions, pinned in `../requirements.txt` (exact versions, hashes, wheels):

- `soupsieve-tag-before-namespace`: `beautifulsoup4` (`bs4`), which imports
  `typing_extensions`; the standard library `html.parser` is the tree builder.
  Installing `bs4` with its dependencies would pull `soupsieve` from PyPI, so
  the job installs with `--no-deps` and the checkout comes first on the path
  (`_checked()` refuses an installed copy).
- `markdown_it-inline-pending`: `mdurl` (a runtime dependency of
  markdown-it-py).
- `networkx-smallworld-has-path`: `numpy` for `lattice_reference` and `sigma`;
  without it those parts are skipped and the printed line says `lattice=skipped`
  (the output stays identical between baseline and trial on one machine).
- `mpmath-*`: the checkout has no `mpmath/_version.py` (setuptools-scm writes it
  at build time), so `import mpmath` from a bare checkout fails until the job
  provides that file (the manifest's `setup_files` commits a one-line stand-in).
- `mpmath-bin-to-radix-pow2` is a **control** (owner decision O21): with the
  pure-Python backend the digit conversion, not the radix change the candidate's
  fix is about, takes nearly all of each base-2/8/16 conversion (measured on the
  before-tree: about 2 % against 98 % at 20,000 hex digits), so no fix of that
  function can clear the floor. `gmpy2` is not installed; the item is reported
  as "control, no win expected" (`upstream.CONTROLS`), where a claimed win is a
  warning.
- `packaging-simple-version-fastpath` and `wcwidth-wcswidth-ascii` run but are
  never scored (O21, `upstream.EXCLUDED`): their fixes were in release notes
  before the training cutoff.
