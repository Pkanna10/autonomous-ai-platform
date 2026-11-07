# Launching emergence round 2

Everything a session needs to run round 2 is here and in
`round-2/university-pack.md`. The owner approved the launch on 2026-11-07, and
the window's live balance is 21.08 USD. No live run is dispatched without the
owner's approval.

## Files

| File                | What it is                                                                                                                    |
| ------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `university-pack.md` | What every seat reads: the seats, round 1's builds and the three carry-forwards                                              |
| `gen_briefs.py`     | Renders every agent brief for phases 0-2 into `briefs/` (shared rules read word for word from `tail.js`)                      |
| `briefs/`           | The rendered briefs (42) and `seats.json` (each seat's name, tag, library file and model)                                     |
| `tail.js`           | The Workflow script for phases 3-6: synthesis, three judges, top-2 builds, review, fix, and the two-part verifier             |
| `post.sh`           | The only way to write the board: `bash post.sh "<agent>" "<role>" <<'MSG' ... MSG`; it numbers and timestamps each entry under a lock |
| `builder-rules.md`  | The rules every builder in the tail follows                                                                                   |
| `board.md`          | The round-2 board, append-only, created by the first post                                                                     |

## From a fresh session

1. Clone the repository and check out `claude/step3-emergence-r1`.
2. Set the two paths and render the briefs:

   ```bash
   EMERGENCE_W=<the worktree> EMERGENCE_SCRATCH=<a scratch dir> python3 gen_briefs.py
   ```

3. Edit `W` and `S` at the top of `tail.js` to match.

## The sequence (O57, O58, the owner's launch message)

**Phases 0-2 run as background agents from the main session**, each given one
brief file. The workflow runner caps concurrency at CPUs minus 2. Every agent
hands back one line.

1. **Lead:** post an opening entry to `board.md`.
2. **Facts:** one agent, `briefs/facts.md`.
3. **Phase 1:** the nine wave-1 seats at once, `briefs/propose_<seat>.md`.
   - Models are from `seats.json`: Bounds first, Pre-mortem and the
     Contrarian on Fable; the rest on the session model.
4. **Phase 1c:** the Contrarian, `briefs/propose_contrarian.md`, after the
   nine have posted.
5. **Phase 1b:** all ten, `briefs/cross_<seat>.md`.
6. **Debate round 1:** all ten, `briefs/critique_<seat>.md`. Each seat
   critiques the seats one and three places after it in `seats.json`.
7. **Debate round 2:** all ten, `briefs/revise_<seat>.md`.
8. **Phases 3-6:** run `tail.js` as one Workflow.
   - The Workflow tool loads scripts only from directories the session can
     read: copy `tail.js` byte for byte into the scratch directory, check it
     with `cmp`, and pass that copy as `scriptPath`. Round 2 ran this way as
     `wf_2f6da9da-bfb`.
   - Synthesis is on Sonnet.
   - Judges are on Opus and Fable.
   - Builders are on Opus and reviewers on Fable.
   - Verification is two Fable verifiers, units then measures. Each runs in
     the foreground to completion; the Lead never completes a verifier
     (O57).

**Office hours (O55)** apply in waves 1, 1b and debate round 1.

- A proposer that asks posts a `QUESTION for Facts:` entry and stops,
  returning `QUESTION [n]`.
- Run `briefs/facts_answer.md` with `{QUESTIONS}` replaced by the open entry
  numbers.
- Then resume each asking agent with its answer's entry number.

**After the tail:**

1. Gate each build with the lab gate and make one commit each.
2. Write the round report to `board.md` and `round-2.md`.
3. Update the library files: fates, objections, the judges' mentoring notes
   and points under O55 as amended by O58.
4. Ask the owner to approve the live plans. Plans must fit 21.08 USD with
   several runs on fewer libraries, and are never dispatched without the
   owner.
