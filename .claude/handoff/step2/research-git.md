# Git worktree trials and delivery: verified facts (git 2.43, Linux)

I ran every experiment in scratch repos under `.claude/handoff/step2/git/`. `$U` is the scratch "user" repo on `main`, left dirty on purpose with ` M src/app.py`, `A staged.txt` and `?? untracked.txt`. A throwaway helper prototype is at `.claude/handoff/step2/gitproto/gitws.py`. I made no changes to the project repo.

## 1. Isolated trial worktree

```
git -C $U worktree add --detach -- $WT/run1/h1 $BASE^{commit}   # 34 ms
  -> "Preparing worktree (detached HEAD 416e588)"
```

- **Your checkout is untouched.** HEAD stayed `refs/heads/main`, `sha1(.git/index)` stayed `1a1de07…` and the status output was the same before and after.
- **What git does write in `$U/.git`:** `worktrees/<basename>/`, objects, and later `refs/heads/engine/*` plus their reflogs.
- **Name collisions:** a second worktree with the same basename was registered as `worktrees/h11`. Use a unique leaf name, `trial-<run>-<hyp>`.
- **Bad targets fail with exit 128:** an existing non-empty path ("already exists") or a bad commit ("invalid reference").
- **Your uncommitted work is not in the trial.** The worktree contains the HEAD commit only, so none of the three dirty entries were present.
  - To show it, run `GIT_OPTIONAL_LOCKS=0 git -C $U status --porcelain=v1 -z --untracked-files=normal`. Report it as an event and a report line: "N uncommitted changes ignored; run measures <sha>".
- **Plain `git status` rewrites your index.** After a `touch`, a normal `git status` changed the index hash `1a1de07…` to `3fa49f9…`. With `GIT_OPTIONAL_LOCKS=0` it stayed the same.
- **`git stash create` also changes the index**, even with `GIT_OPTIONAL_LOCKS=0`. If a dirty snapshot is ever needed, this worked with your index unchanged and includes untracked files: `cp .git/index $T; GIT_INDEX_FILE=$T git add -A; git write-tree; git commit-tree <tree> -p HEAD`.
- **Cleanup:**
  - `worktree remove` refuses when the tree has changes ("contains modified or untracked files"). `remove --force` works (exit 0).
  - After an `rm -rf`, `worktree prune -v` printed "Removing worktrees/h1: gitdir file points to non-existent location".
- **Paths:** git stores the real path (a symlinked parent was resolved), so compare against `Path.resolve()`. This matters on macOS, where `/tmp` is really `/private/tmp`.
- **Ignored files stay behind.** `.venv`, data files and other gitignored content are absent from worktrees. Measure the baseline in its own worktree at the base commit so the comparison is like-for-like. Workload data has to be passed explicitly.
- **SECURITY (verified):** the worktree's `.git` file points at your gitdir. Inside it, `git update-ref refs/heads/main …` and `git config core.hooksPath /tmp/x` both succeeded against `$U`. A fingerprint of `for-each-ref`, `symbolic-ref HEAD`, `.git/config` and `hooks/` changed from `21d207de` to `dc7a8fb6`, so tampering can be detected.
- **Submodules:** `worktree add` does not initialise them, and `submodule update` needs the network.
- **LFS:** with filters neutralised (section 5), `w.bin` checked out as a 129-byte pointer.
  - `unshare -rn git lfs checkout` restored all 2000 bytes from the shared `.git/lfs` store with the network off.
  - The neutralised capture then reports ` M w.bin`, so LFS paths must be read-only for trials.

**RECOMMENDATION:**
- Run `worktree add --detach -- <dir>/<run_id>/trial-<hyp> <sha>^{commit}` under `~/.cache/aip/worktrees` (configurable).
- Measure the baseline in a worktree too.
- Run `worktree prune` at the start and end of each run, and `remove --force` per trial.
- Use `GIT_OPTIONAL_LOCKS=0` for every read in `$U`.
- Fingerprint `$U` before and after each trial; a change means reject the trial and alert.
- Step 2 refuses repos with `.gitmodules` or `filter=lfs` (checked with `git check-attr`). Support comes in Step 5.

## 2. Capturing the diff without trusting the editor

The trial renamed `tests/test_app.py`, deleted a file, ran `chmod -x`, symlinked `/etc/passwd`, replaced `tests/` with a symlink, and added a binary and an untracked file. Then:

```
git add -A
git diff --cached --raw -z --no-renames --no-abbrev $BASE
:100644 000000 … D  bench/bench.py
:100755 100644 … M  run.sh                 # mode change
:000000 120000 … A  src/leak               # symlink -> /etc/passwd
:000000 120000 … A  tests                  # dir replaced by symlink
:000000 100644 … A  src/test_moved.py
:100644 000000 … D  tests/test_app.py
```

- **Renames:** `--name-status -z -M` reports `R100|tests/test_app.py|src/test_moved.py`, so both paths are present. `--no-renames` reports D old plus A new, which is simpler to parse.
- **Patch text:** `git diff --cached --binary --full-index --no-ext-diff --no-textconv --no-color --no-renames $BASE`.
- **Ignored-file hole (verified):** a trial wrote `.gitignore: cache/` and `cache/answer.txt`. The diff showed only `A .gitignore`, while `ls-files --others --ignored --exclude-standard` listed `cache/answer.txt`. Running `commit` then `git clean -ffdxq` deleted it, so the measured tree equals the captured commit.
- **Non-UTF-8 text:** a latin-1 file appears as raw bytes in the patch, and `text=True` raised `UnicodeDecodeError`.
- **Files outside the worktree** are invisible to git. Blocking writes there is the sandbox's job; git cannot help.

**RECOMMENDATION:**
- Capture with `add -A`, then `diff --raw -z --no-renames --no-abbrev`. Feed every path to anticheat.
- Reject new mode `120000` (symlink) or `160000` (gitlink), and any change touching an LFS path.
- Commit, then run `clean -ffdx` before measuring.
- Read the diff as bytes, decode strict UTF-8, and fail the trial if decoding fails.
- Run the editor with `PYTHONDONTWRITEBYTECODE=1`.

## 3. Combine

Trials A and B are independent; C edits the same line as A.

```
git merge-tree --write-tree --merge-base=$X^ $ACC $X   # 0 clean, 1 conflict, else error
git commit-tree <tree> -p $ACC -m "aip: apply trial …"
-> apply 701992d ok; apply a910e3f ok; skip 60f00c4 (exit 1, conflicts: src/app.py)
```

- **`merge-tree`/`commit-tree` touch no worktree:** your status was unchanged afterwards.
- **Cherry-pick in a fresh worktree:** A and B returned exit 0. C returned exit 1, `UU src/app.py`, which `diff --diff-filter=U` also lists. `cherry-pick --abort` restored a clean tree.
- **Gotcha:** `git apply --check --3way c.patch` returned **exit 0** ("Applied patch with conflicts"). Plain `--check` returned 1, and a real `apply --3way` returned 1 with `UU`.
- **Stable identity:** `git patch-id --stable` gave the same id for a stored patch and for a freshly generated diff.

**RECOMMENDATION:**
- Combine greedily in a deterministic order: score descending, then hypothesis id.
- Use `merge-tree --write-tree` plus `commit-tree` with an `Engine-Trial:` trailer.
- On exit 1, skip and record the conflict. On any other non-zero exit, raise.
- Check out only the final commit in one combine worktree for the re-test.
- Never use `apply --check --3way` to detect conflicts.

## 4. Delivery

```
git -C $WT commit --no-verify -q -m …   # with -c identity/hooks/sign overrides (§5)
git -C $U update-ref -m "aip deliver r4" refs/heads/engine/run-r4 $TIP 0000…0000   # exit 0
second create-only        -> "reference already exists" (128)
wrong expected old value  -> "is at 1659f64… but expected 416e588…" (128)
git branch -f main $TIP   -> "cannot force update the branch 'main' used by worktree" (128)
git update-ref refs/heads/main $TIP   # on a scratch clone: exit 0, NOT refused;
                                      # status then shows "M src/app.py; D src/extra.py"
```

- **Your repo was unchanged:** HEAD `refs/heads/main 416e5883`, index `3fa49f95`, file-tree hash `4a9960b9` and status were identical before and after.
- **Branch name check:** `git check-ref-format --branch engine/run-r4` passes.
- **Checked-out branches:** read them from `git worktree list --porcelain` lines starting with `branch`.
- **Signing must be disabled explicitly:** this sandbox's global config has `commit.gpgsign=true` with `gpg.ssh.program=/tmp/code-sign`, which would run on every commit.

**RECOMMENDATION:**
- The Python guard runs first: the ref must start with `refs/heads/<prefix>`, must not be the default branch, and must not be any checked-out branch.
- Then run `update-ref <ref> <new> <old>`, with the zeros value for create-only or the previous tip when resuming.
- Use fixed `GIT_AUTHOR_DATE`/`GIT_COMMITTER_DATE` so a resumed run reproduces the same SHAs.
- Never push; `protocol.allow=never` enforces this.

## 5. Security of git in an untrusted repo

The scratch repo had a malicious config: `core.fsmonitor`, filter, diff and merge drivers, `diff.external`, `gpg.program`, seven hooks, and `a.py filter=evil diff=evil merge=evil`.

| Configuration | What executed |
| --- | --- |
| Plain `git` (no overrides) | fsmonitor ×12, reference-transaction ×10, post-checkout, pre-commit, prepare-commit-msg, commit-msg, post-commit, smudge ×2, clean ×3, extdiff |
| `-c core.hooksPath=/dev/null -c core.fsmonitor=false -c commit.gpgsign=false -c diff.external=` | smudge ×2, clean ×3 |
| `--attr-source=4b825dc6…` (empty tree, git ≥ 2.40) | nothing, including the merge driver during cherry-pick (without it: mergedriver, fsmonitor ×4, clean) |
| `--attr-source` with `.git/info/attributes` set | smudge, clean (**`--attr-source` does not cover this file**) |
| One `-c <key>=` per driver key from `git config --name-only --get-regexp '^(filter\|diff\|merge)\.'` | nothing |

Other checks:
- `-c protocol.allow=never push` failed with "transport 'file' not allowed".
- A repo owned by `nobody` failed with "detected dubious ownership". `-c safe.directory=<path>` is honoured even with `GIT_CONFIG_GLOBAL=/dev/null`.

**RECOMMENDATION:**
- **Prefix every call with these overrides:** `-c core.hooksPath=/dev/null core.fsmonitor=false core.sshCommand=false commit.gpgsign=false tag.gpgsign=false protocol.allow=never credential.helper= diff.external= core.attributesFile=/dev/null core.excludesFile=/dev/null user.name=aip-engine user.email=engine@aip.invalid`.
- **Neutralise drivers:** add per-key empty overrides for every `(filter|diff|merge).*.(clean|smudge|process|required|textconv|command|driver)` key found. This works on any git. Also pass `--attr-source=<empty tree>` when git ≥ 2.40.
  - Apple's Command Line Tools git has lagged at 2.39.x, so check `git version` at CONNECT. Require ≥ 2.38 for `merge-tree --write-tree`.
- **Build the environment from scratch** (allowlist, not inherited): `PATH`, `HOME`, `LC_ALL=C`, `GIT_CONFIG_NOSYSTEM=1`, `GIT_CONFIG_GLOBAL=/dev/null`, `GIT_TERMINAL_PROMPT=0`, `GIT_OPTIONAL_LOCKS=0`, `GIT_PAGER=cat`, `GIT_EDITOR=true`.
  - No `ANTHROPIC_API_KEY` or `DATABASE_URL`.
  - Drop any inherited `GIT_DIR`/`GIT_WORK_TREE`/`GIT_INDEX_FILE`.
- Use argv only, with `--` before paths, and ids already refname-validated.
- Never set `safe.directory='*'`.

## 6. Python `GitWorkspace` design

```python
class GitError(RuntimeError): argv, returncode, stderr   # never the env
class GitWorkspace:
    def __init__(self, repo: Path, *, home: Path, timeout_s: float = 60.0) -> None
    def git(self, cwd: Path, *args: str, check: bool = True, binary: bool = False) -> CompletedProcess
    def version(self) -> tuple[int, int, int]
    def head(self) -> str; def dirty_entries(self) -> tuple[str, ...]
    def fingerprint(self) -> str
    def add_worktree(self, path: Path, commit: str) -> None
    def capture(self, wt: Path, base: str) -> tuple[str, tuple[Change, ...]]   # Change(status, old_mode, new_mode, path)
    def commit(self, wt: Path, msg: str) -> str           # commit --no-verify + clean -ffdx
    def combine(self, base: str, commits: Sequence[str]) -> tuple[str, tuple[str, ...]]  # (tip, skipped)
    def create_branch(self, ref: str, new: str, old: str = ZERO) -> None   # guard + update-ref
    def remove_worktree(self, wt: Path) -> None           # remove --force + prune
```

- **Internals:** `subprocess.run(["git", *prefix, "-C", cwd, *args], capture_output=True, env=allowlist, timeout=…, check=False)`, mapped to `GitError`. Only `capture` uses bytes.
- **Prototype timing:** 3 runs, 14 git calls each. Setup took 29–32 ms and a full trial cycle (add, edit, capture, commit, branch, remove) took 63–73 ms, about 5 ms per call.
- **Test fixtures:** pytest builds `tmp_path` repos with the same overrides, so no global git config is needed and xdist is safe. CI's ubuntu-22.04 runner already has git.

**RECOMMENDATION:** make this one Builder unit (about 300 lines, `execution/git.py`) with real-repo pytest tests.
- Cover the symlink, rename, ignored-file, conflict, create-only/wrong-old-value, checked-out-branch and malicious-config cases above.
- Add a test asserting your HEAD, index hash and status are unchanged after a full cycle.