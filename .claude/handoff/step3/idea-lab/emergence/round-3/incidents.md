# Round 3 incident log: sealed-set (V9, O53) exposure, 2026-11-13

V9 = `services/python_agents/tests/fixtures/upstream_corpus/` (30 sealed maintainer-fix tasks, 18 libraries; 9 of the 30 are on the four development libraries). O53 seals `_keys` and `_notes`; the charter's limits say sealed sets are never read. The upstream commits named in the manifest are the public form of the sealed fixes.

| # | seat | what happened | contents of `_keys`/`_notes` read? | Lead action |
| - | ---- | ------------- | ---------------------------------- | ----------- |
| 1 | s4-algorithms | a grep over `tests/` printed V9 workload file names and one manifest `commit_url`; its notes then cited 6 of the 9 dev-library V9 commits (found independently in the public histories), with worked numbers and fix sites; it read their messages and diffs with `git show`, but did not check them out or benchmark them | no | self-reported; notes filed with that material redacted; unredacted copy in `r3/quarantine/s4-algorithms.raw.md` |
| 2 | s8-expert | listed `_keys`/`_notes` (names only), read STATUS lines saying V9 is sealed, then extracted the four libraries' `commit_url`s from `manifest.json` and checked out and A/B-timed 7 of the 9 commits | no | agent stopped before filing; its work moved to `r3/quarantine/s8-expert-work/`; no notes filed |
| 3 | fp-compose | a content grep over `tests/` printed 8 lines of `manifest.json` (3 Python-Markdown commit ids, a PR number, workload file names) | no | self-reported; nothing used in its notes or errata (checked: no V9 id in its files) |
| 4 | s7-cpython | cloned the four libraries at their default heads without checking the manifest | no | heads 09dbe1e, f7ec702, 43a86ad, a4d4428 checked: none is a V9 commit |
| 5 | s3-equivalence | a `grep -rln sqlparse` over the service listed 3 V9 file names (two sqlparse workloads and the manifest) | no | self-reported; tomli clone at tag 2.5.0 (tomli is not a V9 library); no V9 id in its files |

Checks run: every file under `r3/library/` and `r3/work/` grepped for all 30 V9 commit prefixes; hits only in s8's work (now quarantined) and s4's raw notes (now redacted).

**For the owner:** whether incident 2 counts as misconduct (-3), whether V9's 9 dev-library tasks are still valid as the K4 rung for proposals from this round, and whether the quarantined material is deleted or kept sealed. s8-expert restarts only after that ruling, with an allowed-commit list the Lead computes.

## O67: the owner's rulings (2026-11-13)

1. **No misconduct penalty** for s8-expert or s4-algorithms. The O64 brief told the expert-practice seat to study the development libraries' performance commits and did not exclude V9's. The misconduct list does not cover this, and no penalty is added after the fact. **s8's case is recorded as the more serious:** it read that V9 is sealed and then used its manifest.
2. **Both seats are retired as running contexts and restarted fresh.** s4 restarts from its redacted filed notes. s8 restarts from its brief and an allowed-commit list the Lead computes by script: the development libraries' performance commits with every V9 commit excluded, and the V9 ids never shown to any seat. Neither old context is resumed for the exam, the seminar or a proposal. fp-compose, s7-cpython and s3-equivalence continue, since they opened nothing.
3. **K4 for any claim is the 21 V9 tasks on the other libraries.** The retired tasks are removed from every claim and, if ever run, reported separately and labelled "exposed". All of them are treated as exposed, whichever seat saw which. V9 stays sealed (O53), and the retired tasks are not opened as study material.
4. **The quarantine stays sealed** in the Lead's scratch area. It is never committed, and it is listed here by hash only. If the container is lost, it is lost.
5. **The door is closed technically** before stage 2's sittings (see below).
6. **Stage 4 is screened.** Any proposal whose mechanism or example matches a retired V9 fix is flagged to the owner before it is scored. The statistician does this from the commit ids by script, without reading the diffs.

Nothing from the quarantine or from s4's unredacted notes enters a prompt, lesson, example bank or exam paper.

### Count correction (Lead's error)

The incident log first said that 9 of V9's 30 tasks are on the four development libraries. That is wrong: **8 are**, 3 on Python-Markdown, 3 on mistune and 2 on sqlparse, and none on tomli. The ninth match was markdown-it-py, a different library whose URL matched a substring search for "markdown". No seat's files contain its id.

The Lead applies the owner's numbers conservatively: **9 retired** (the 8 plus markdown-it-py) and **K4 = 21**, until the owner says otherwise.

### Quarantine, by hash only

| item | sha256 | size |
| ---- | ------ | ---- |
| `s4-algorithms.raw.md` (s4's unredacted notes) | `2eef72e15aafaee7f44484ffb38da63ecc30294973e5183c8845c73f08a11ecf` | 23,595 bytes |
| `s8-expert-work/` (s8's clones, checkouts, A/B outputs, scripts) | tree hash `4a3c7f0743768f9bf90c658fb3573664cd89ae72a997527e5ade854ba33f541e` (the sha256 of the sorted per-file sha256 list) | 12,147 files |

Also sealed by the guard, not copied: the agents' own transcripts and saved tool results under `~/.claude/projects/` and the session's `tasks/` folder. Those include s4's and s8's old contexts and the search output that printed manifest lines.

### Item 5: what closes the door

- **A PreToolUse hook** (`.claude/settings.local.json` in the session's checkout; the guard script is in the Lead's scratch area). It applies to every call that carries an `agent_id`: seats, examiners, builders, reviewers and workflow agents. The Lead's own calls pass.
  - It covers Bash, Read, Grep, Glob, Write, Edit, NotebookEdit and LS.
  - `onFailure: block`, so a guard that crashes denies the call.
- **Denied when named** in any tool input (after shell-variable expansion):
  - the V9 directory, `tests/fixtures/upstream_corpus/`, in any copy;
  - the held-out brief and hash list (`heldout*`);
  - `tests/fixtures/ideas_probe/views.jsonl`, a committed probe fixture whose data block quotes the commit subject of one K4 task's fix (idna);
  - the Lead's sealed folder, the quarantine, the exam's `key/` and `build/` (the examiner is exempt until the key is sealed), the gate copy, the hook folder, the session's `tasks/` folder, and `~/.claude`.
- **Denied as listings:**
  - any recursive search or listing (grep -r, rg, find, fd, tree, du, ls -R, Python os.walk, glob and scandir, the Grep and Glob tools) rooted at an ancestor of any on-disk copy of the above;
  - `git grep`, `ls-files`, `ls-tree`, `archive`, `cat-file`;
  - `git log` or `git show` with a patch or stat listing and no pathspec;
  - `git show REV:<dir>` of a directory that holds sealed files.
- **Removed from disk** by sparse checkout in every git worktree except the gate's: the V9 directory, the views fixture and the held-out files, so an ordinary search of a worktree cannot print their names.
- **Proven:**
  - 29 synthetic allow and deny cases;
  - a live subagent, which was denied six of six sealed probes, while a recursive search of a builder worktree printed no corpus name.
- **Residual:**
  - a deliberately obfuscated path, for example one built by string concatenation inside a script the agent writes, is not caught by text matching;
  - 50 stale copies of V9 remain on disk: 49 in old scratch folders and the untracked leftovers of one in the `step3-research` worktree. The guard covers them, but they were not deleted: the deletion was refused by the session's safety classifier, and the owner decides.
