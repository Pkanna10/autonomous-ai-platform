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

## Society rules, from round 2 (O55, owner, 2026-11-06)

### Seats

Each round has ten seats, plus a bench of three.

- **Round 2's seats:**
  - the eight current frameworks;
  - **Scaling:** shadow scaling-judge rows and slope-changing ideas;
  - **Contrarian:** reads all of wave 1's proposals and names the shared belief
    most likely to be wrong, with its test.
- **The bench, in order:** Memory & allocation, Verifier-designer, Interpreter
  specialist, then Editor's advocate, Workload designer, Diversity archivist,
  Budget economist.

### Memory

- **Library files:** each seat has `emergence/library/<seat>.md`, append-only
  across rounds. It holds the seat's proposals, their fates, the critics'
  objections and the judges' refutation notes.
- **Reading before posting:** a seat reads its own file and the round's top
  scorer's file. It also reads the university pack: the charter, the last
  round report and the judges' refutation patterns.

### Office hours

Each proposer may ask the facts agent one factual question per wave. The answer
goes on the board.

### Mentoring

For each proposal it refutes, a judge writes into that seat's library file what
evidence would have saved it.

### Points

Points come from verified outcomes only.

| Outcome | Points |
| --- | ---: |
| Survives the judges | +1 |
| Built, reviewed and gated | +3 |
| A live run beats its pre-registered bar against the twin's band | +10 (from round 2: +5 for a record-only proposal, +10 for a gain-bearing one; O58) |
| A critic's critique led to a withdrawal, or to a merge the judges kept | +2 |
| A fabricated number, or a touch of the FIXED list | −3 |

- Merged proposals split the credit.
- Points halve each round.
- Judges earn nothing for refutations.

### Points control

- The bottom three seats rotate out against the bench.
- The top two seats get the Fable budget.
- The top scorer's library file is required reading for all seats.
- Points never touch the judges, the bars, the band, the FIXED list or what
  counts as a win.
- A seat that survives the judges three rounds running without a live win stops
  earning survival points.
