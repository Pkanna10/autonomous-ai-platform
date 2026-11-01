# Step 3: the user's decisions (binding inputs for the synthesis)

Recorded by the Lead from the user's messages of 2026-10-24.

1. **Behaviour changes: a separate review branch per run, no pause.** A verdict
   of class `behaviour` is delivered to its own local branch,
   `engine/review-<run_id>`, never merged into `engine/run-<run_id>`, and the
   run does not stop at the approval gate for it. Align CLAUDE.md ("flagged")
   and the code (today `derive_verdict` gives `needs_approval` and the gate
   interrupts, `optimization/judges.py`) to this. `novel` changes still need the
   user's approval.
2. **pip-audit in CI.** Today only the stage gate runs it; add it to a CI job
   (the Python job or `security.yml`) so a vulnerable lock fails a PR.
3. **The non-UUID Postgres id fix is Step 3's first unit** (STATUS, Known
   gaps): caller ids such as `h1` and playbook slugs as `technique_id` must not
   fail `save_lesson` after a run has spent. No more code lands in Step 2.
4. **3b, same environment on both sides.** Baseline and trial run in
   environments built from the same lockfile, differing only by the acquired
   package and its new dependencies. A resolver upgrade or downgrade of any
   existing dependency is a separate change, shown in the report and measured
   on its own. The delivered branch's report says the user must install the
   new dependency.
5. **3b, no wheel means ask.** A package or transitive dependency available
   only as an sdist fails the automatic policy (building runs code) and goes to
   the user, never to an automatic build.
6. **3c, reproducer integrity.** The reproducer is written in a separate
   request before any fix is attempted and frozen as a protected file; it must
   fail on the baseline N of N runs; it must fail for the reported reason (same
   exception type and same frame or message as the error report); the fix's
   trial may not touch it; the report shows the reproducer next to the fix.
7. **The A/B (E5) result sets the paper pipeline's priority** by its
   pre-registered rule: c - b >= 3, or the paper pipeline is deprioritised
   behind the playbook and lessons.
8. **Process:** the spec and its build plan by wave are shown to the user;
   nothing is built until the user approves them. The Step 3 branch is
   `claude/step3-research`; its draft PR targets `master` once PR #12 merges.
9. **Live spend: useful, not capped at $200.** The `live` environment keeps
   running without required reviewers. Spend past the $200 windows is fine when
   each run is effective and efficient: it names what it measures and what
   decision or build step it feeds, takes the cheapest arm that answers it,
   and lands its cost and finding in the ledger. Step 3's live-test plan follows
   this rule (STATUS, Guardrails).
