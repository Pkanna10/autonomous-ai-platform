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

## Addendum O64: Round 3, the academy round (owner, 2026-11-13)

Recorded before the round starts. The round runs on the Lead's own agents,
with no API key.

- Stages 1 to 4 may run beside the X2-DT build.
- Stage 5 opens only after the noise report is in. The owner named it O62
  item 4; it is O63 item 4, reported in `w2-sprint/floors/`, `95e323e`.

**Goal:** raise the engine's delivered, proven gain by attacking where gain is
lost, not by adding ideation variants. A claim against the expert benchmark
is still made only at a sealed rung.

### Stage 0: the loss ledger (the Lead)

One table, with one row per stage of loss. Each row gives the measured loss
and its source file:
- ideas that never become trials (the fate counts);
- truncated leaps;
- inconclusive trials whose gain is above the baseline floor;
- combine conflicts and repeats;
- unique keeps per round;
- the spread between identical runs.

A "floor" column is left empty for the first-principles seats to fill.

### Stage 1: the university

14 student seats, each with one speciality. Each seat finds the standard
textbooks, courses and papers for its speciality (public sources only) and
writes cited notes into the library.

- **First principles (3):** the method of breaking a cost into its atoms and
  pricing each, taken from documented cases. These seats fill the ledger's
  floor column and rank the rows by gap.
- **Zero to one (3):** distant-field analogy; contradiction resolution; "what
  is true here that few believe". These seats propose mechanisms the engine
  does not have.
- **Specialists (8):**
  - performance engineering;
  - benchmarking and measurement statistics;
  - program analysis and equivalence;
  - algorithms and data structures;
  - search methods (archives, islands, evolutionary and bandit search);
  - patch composition and merging;
  - Python internals and profiling;
  - expert practice: the real performance commits in the four development
    libraries' own histories, set against what the engine found there.

### Stage 2: the exam

- The examiner runs on Fable 5.2, a different model from the students.
- It writes each speciality's paper before reading any notes. The questions
  are practical tasks whose answers are run or computed. Examples: make a
  fixture function faster with equivalence shown; find the flaw in a
  benchmark harness; compute the power of a sign test at a given n; resolve a
  three-way patch conflict.
- It marks by executing the answers.
- Each student writes a mistake log and re-sits failed questions once.
- The pass mark is 70 %; only seats that pass may propose.
- Students never see the marking scheme.

**Exam addendum (owner, 2026-11-13).** The examiner builds each practical paper
by planting reversible slowdowns in real code (fixtures, or copies of the
development libraries), hidden as hard as it can:
- away from the profiler's hot spot: in a caller, in set-up, or in data
  preparation;
- spread over several functions or files, none of which looks wrong alone;
- in the choice of data structure, not in the loop;
- visible only at realistic input sizes.

Each paper also carries decoys (code that looks slow and is not) and tempting
shortcuts (a cache or fast path that is faster but wrong on a rare input that
the paper's hidden checks cover).

Guards:
- **Every plant is proven before the exam.** The examiner applies its own
  reversal and records the measured gain and that equivalence holds. An
  unproven plant is removed.
- **The answer key is sealed until marking.** The key (plants, decoys, traps,
  expected gains) is committed as a hash before any student sees a paper, and
  is revealed only after marking. Students never see it or the marking
  scheme.
- **Four tiers,** from one plain plant up to cross-file plants with decoys and
  a trap.
  - The 70 % pass mark applies to tiers 1 and 2.
  - Tiers 3 and 4 earn points: +1 per tier-3 plant found, +2 per tier-4
    plant, and -1 per trap taken or decoy "fixed".
- **Marking is by execution:**
  - the gain recovered per plant;
  - equivalence on the hidden checks;
  - which plants were missed.

  The mistake log is written per missed plant.
- **The engine sits the same papers after marking.** One unmodified X2-0 run
  per paper, where the budget allows, and only after the owner approves that
  spend.
  - The report gives, per hiding kind, the share of planted gain the engine
    recovered, beside the students' share.
  - This is a diagnostic with known ground truth. It is not a reading against
    the pool and not a claim.
- **The papers and keys stay out of every prompt, lesson and example bank the
  engine reads.**

### Stage 3: the seminar

- Each student teaches one lesson, on the board, to two students from other
  groups.
- Each student co-writes at least one proposal with a seat from another
  group.

### Stage 4: proposals

Each proposal names:
- the ledger row it attacks;
- the mechanism and its source;
- an offline experiment on the archive (zero credit), with the result that
  would kill it, stated before the run.

The reviewer's seeds are treated as proposals like any other:
- (a) the union of all distinct proven diffs per library across every archived
  run, combined and measured offline, as the ceiling of what the engine has
  already found;
- (b) edits wider than one hot function, since most expert gain is in
  functions the model never edits;
- (c) a proven-patch archive carried across runs.

### Stage 5: critics and proof

- Two critics try to refute each proposal.
- The statistician checks that each experiment can detect the effect it
  claims.
- Survivors run their offline experiment.
- Only a proposal that met its own bar offline may ask for a live arm. That
  arm is pre-registered, and the owner approves each one.

### Points (on top of O58)

| Event | Points |
| --- | ---: |
| Exam at 80 % or more | +2 |
| A passed re-sit | +1 |
| A seat you taught cites your lesson in a surviving proposal | +1 |
| An offline experiment that meets its stated bar | +5 |
| A gain-bearing live pass | +10 |
| A claim that a critic or the examiner falsifies | -3 |

The statistician keeps the table.

### Limits (unchanged)

- Public sources and owned code only; no live or third-party systems.
- No judge, anticheat or protected-path change.
- The held-out list and the sealed sets are never read.
- From SWE-Perf, GSO and SWE-fficiency, only their papers' published findings
  are read, never their instances or expert patches.

### Report

- the ledger with its floors;
- the exam marks and the mistake logs;
- the proposals with their critics' verdicts;
- each offline result against its stated bar;
- the points table.

## Addendum O64-2: Round 3 points and communication (owner, 2026-11-13)

**Replaces every earlier round-3 points figure,** including the exam tier
points.

**Timing.** The addendum arrived after stage 0, after the study seats started
(stage 1), and after the examiner began building papers. No post, mark or
point existed yet, so nothing scored is affected. The examiner was told at once
to drop tier points and to build re-sit papers.

**Execution note.** The study seats were launched as 14 persistent background
agents before this addendum. They are kept as they are, because persistent
seats must be resumable with their own context, and workflow agents are not.
- Workflows run the stateless parallel stages: the exam sittings, marking, and
  the offline experiments. Each workflow agent loads its seat's own memo, its
  notes and mistake log.
- The Lead drives the conversation rounds by resuming the persistent seats.

### Points

**Exam.**
- The exam is a gate only (70 % on tiers 1 and 2) and earns no points.
- A re-sit uses a fresh paper, hash-committed separately.
- The board and the library are closed during exams.
- The exam is valid only if its pass rate is between 40 and 80 % and every
  plant reproduces from the key.

**Proposals and experiments.**

| Event | Points |
| --- | ---: |
| A proposal is built | +1 |
| Its offline experiment passes | +3 |
| A well-run failed experiment is written into the library | +1 |
| A live run passes its pre-registered bar | +20 |

- **The offline bar is set by the statistician before the run.** It states a
  minimum effect above the measured noise and a fixed N, and allows one
  attempt.
- **It is scored on held-back data.** The run is scored on a part of the
  archive the statistician holds back from students. Stage-1 seats could read
  the whole archive, so the statistician records which held-back rows were
  read or cited in stage 1, from the seats' own notes. Where none can be held
  back cleanly, the experiment is scored on data that arrives after its
  pre-registration, such as the X2-DT runs.

**Admissibility.**
- A proposal is admissible only with a numeric predicted gain, the archive
  rows it will be tested on, and a deadline.
- Near-duplicate proposals share one payout.

**Authors and teaching.**
- Outcome points are split equally among at most three named authors,
  declared at submission.
- Teaching earns +1 only when:
  - the citing proposal passed its offline experiment, and the lesson is
    load-bearing;
  - it is at most one per teacher per round;
  - it is never between co-authors.

**Critics.**
- +2 for a refutation confirmed by the experiment or the examiner; -2 for one
  that is overturned.
- +1 when a proposal they cleared passes offline.
- Proposals reach critics anonymised.
- The examiner or the statistician accepts refutations, never the critic or
  the proposer.

**Misconduct (-3).** Changing a bar or a kill criterion after the fact; an
experiment not run or not reported by its deadline; a result that does not
reproduce. An honest, pre-registered claim that fails carries no penalty.

**Scoring and the bench.**
- The examiner and the statistician earn no points.
- The points table is recomputed by a script from the append-only board and
  must match the statistician's table.
- A seat goes to the bench after two consecutive rounds with no outcome
  points.

### Communication

**Posts.**
- Every post carries an id, author, to, reply_to, thread, round and status
  (open, revised, withdrawn, closed).
- Agents return posts as text. The Lead is the only writer to the board, an
  append-only `round-3/board.jsonl`.

**Seats.**
- Seats are persistent. Each is resumed with its own context, and only when
  its inbox holds a post addressed to it, an exam mark or an experiment
  result.
- A conversation round ends when every inbox is empty or the turn budget is
  spent.
- Each seat receives its inbox and a short digest of closed threads, never the
  whole board.
- After a fixed number of resumes, a seat is restarted from its own written
  memo.

**Threads.**
- A thread has at most three turns: claim, challenge, reply. The last turn
  ends "concede", "revise" or "stand, because".
- A reply to a superseded post is returned once for a re-answer.
- Blind first: each seat commits its position and prediction privately before
  the thread's other posts are shown to it.
- A change of view must cite the post that caused it.
- Each thread has one assigned dissenter.
- The examiner and one critic run on a different model from the students.

**Parallel stages.** The study, the exams and the offline experiments run in
parallel; see the execution note above. The Lead drives the conversation
rounds.
