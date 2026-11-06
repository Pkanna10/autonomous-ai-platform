# Charter: the engine and its improvement loop

Owner, 2026-11-06. Recorded as decision O54 in `STATUS.md`. The owner's message called it O51,
but that number already held the CI timeout and X2's noise band, and O53 went
to V9's sealing.

## Level 1, the core engine (what we are building)

A multi-agent, multi-framework ideation-and-realisation engine.

- **Ideation.** Many lanes propose improvements to a codebase. The lanes run on
  different models, and each gets different evidence and a different thinking
  framework with a forcing output.
- **Realisation.** The realisation path implements the ideas, judges them,
  compounds them and ships them under frozen judges.
- **Goal.** State-of-the-art improvement ideas produced by design, not by
  accident, shipped with proven, substantial gains.
- **When "state of the art" may be claimed.** Only at a sealed ladder rung,
  never from the development set. The rungs:
  - K2: unseen problems;
  - K3: held-out OSS;
  - K4: V9;
  - K5: SWE-Perf, GSO, SWE-fficiency.

## Level 2, the emergence round (how we improve it)

A society of agents applies the same diverse thinking to the engine itself and
builds what survives. Each round produces engine changes, not ideas for
libraries; the libraries are evidence.

## The chain

```
round N
  -> engine change units (tests first, different-model review, gate, one commit each)
  -> an engine run on the development set, read against the A/A twin
  -> round N+1's facts card
```

- Nothing enters the engine without a build.
- Nothing counts without a measured run.
- Nothing is called state of the art without a sealed rung.

## Fixed and untouchable by any agent

- the frozen judges
- anticheat
- protected paths
- benchmarks
- the libraries' tests
- the sealed sets
- O28: defensive source analysis only; no live or third-party systems; no
  exploits; a human owns disclosure.

The Lead is the only writer to the branch and the only dispatcher. There is no
live spend without the owner's approval.

## Measures of the engine, every round

All are read against the twin's band.

1. Ideas with a named cost model, as a share of all ideas.
2. The share of the physical gap closed by kept ideas.
3. Wins per run, and their size against the floor.
4. The compounding curve over rounds.
5. The hit rate from idea to working diff.
6. Cost per win.
7. Marker misses: kept ideas the marker ranked out of its top 3.
8. The twin gap on combine, per library: the path-dependence measure. The
   owner added it the same day. On sqlparse, identical settings kept 9 ideas
   against 7 and combined +39.8 % against +21.1 %: round 1's keeps shape
   round 2.
