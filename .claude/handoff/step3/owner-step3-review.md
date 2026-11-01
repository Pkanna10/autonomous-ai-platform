# Product owner's answer on the Step 3 spec (2026-10-24, binding)

The owner approves Wave 1 and Wave 2 with the three conditions below and gives the five decisions below. Wave 3 is held until Wave 1's live runs report, which the spec already requires.

## Three conditions (apply before Wave 1's affected units build)

1. Retry feedback channel residual. The spec puts the residual at about 16 bytes per retry. With 2 retries per trial, up to 5 trials per round and 3 rounds, that is up to about 480 bytes per run, enough for a short key. Keep EDITOR_FIX_RETRIES at 1 by default, and cap retries per run as well as per trial (a new setting, e.g. EDITOR_FIX_RETRIES_PER_RUN, with a small default). Restate the residual per run against that cap.
2. Review branch versus the judges. A behaviour change is one whose output differs from the baseline, so the output-equivalence judge must fail on it. The spec does not say how a behaviour hypothesis can pass every judge. State in writing, before U11 is built, which it is: either the equivalence judge is exempted (or replaced) for class behaviour, and by what it is replaced, or no behaviour change can ever reach the review branch. Ground the answer in the current code (optimization/judges.py derive_verdict and the judges), and make D9 (behaviour ideas by default) consistent with it.
3. D13 templates. D13 pins CPython error-message templates for Python 3.8 to 3.12; 3.13 and 3.14 changed several messages, so a user on 3.13 would silently get "type and frames only" on every retry. Add 3.13 and 3.14 templates to U4 (the test matrix installs those interpreters; verify which interpreters the CI matrix and the container actually have).

## Five decisions (spec section 8)

1. Change the CLAUDE.md Step 3 row: yes (as recommended in Q1; done in U15).
2. Behaviour ideas by default: yes, with condition 2 resolved.
3. The retrieval re-test: yes (about 8.50 USD). The pre-registered pooled rule lands in STATUS before the run.
4. 3b lockfiles: yes, hash-pinned requirements first.
5. 3b before 3c: REVERSED. Build 3c (self-healing) before 3b (package acquisition), unless packages block the dogfood on the owner's code. Reason: 3c has no network boundary and reuses the loop and judges; 3b needs a security review of a network-on fetch, an allowlist proxy and an unverified Landlock interaction with uv.

## Smaller points

- Q8 (run-level wall cap): add a cheap total-time line to the report now; the real cap waits for the Step 4 CLI.
- The one-retry limit is per trial. State what happens when the retry itself crashes with a different fixable error: keep the first failure (as the spec does), and say so in the report.
- Live L2a gates the editor default flip (W5) at "at least 5 of 10"; one repo of noise. Run 2 repetitions before the flip (about 1.50 USD more) and restate the gate over 20.

## Second round of answers (2026-10-24, binding; supersedes the Lead's D35 reading and the open items Q12 and Q13)

1. **Step 3 is approved** (Wave 1 and Wave 2; Wave 3 held as before).
2. **Quality check on changed output, in Step 3.** Not only "same output": a change that alters the output is judged by a quality check. The owner notes this is important, and that many good quality measures exist that the engine can draw on. Plan the owner approved:
   - At the start of a run the engine finds the program's quality number (accuracy, an error rate, a match score), or suggests one from known measures for that kind of program; the user confirms it once.
   - A change that alters output passes only if that number stays the same, improves, or drops no more than the user allows (e.g. "accuracy may drop at most 0.5 %").
   - Outputs that differ only cosmetically (numbers in the tenth decimal place, the same items in a different order) can be treated as equal.
   - Such changes always go to the review branch with a clear label (e.g. "changes results: accuracy 91.2 % -> 91.6 %, 30 % faster"); never applied silently.
   - Fully automatic quality judgement with no number at all (e.g. "is this text better?") stays in Step 4.
3. **One second chance per run** (EDITOR_FIX_RETRIES_PER_RUN = 1). Raising it to 2 is a later improvement, allowed only after attack tests and added safeguards show the error-message leak path is closed.
4. **The output check is on by default.** With no quality number, results must stay identical. With a quality number, a change that keeps or improves it is welcome and goes to the review branch marked as a result improvement, not only a speed one.
5. **Real speedups, not luck** (evidence: noise run 40082852536, 11 of 390 identical-code comparisons judged a win at the 2 % floor):
   - old and new versions are measured alternately (old, new, old, new);
   - every winner is re-checked a second time before it is kept;
   - the bar is set per project from how much that project's timings wobble, never below 2 %;
   - the report states each gain with its margin and confirmations (e.g. "18 % faster, give or take 2 %, confirmed twice") and a plain label: small (under 5 %), solid (5-20 %), large (over 20 %).
