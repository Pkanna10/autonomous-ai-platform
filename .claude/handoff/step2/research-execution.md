# Step 2 process runner: measured facts and design choices

Every experiment below ran in this sandbox: Linux 6.18 Firecracker VM, Python 3.13.16, 4 vCPU, running as root. A few runs used `setpriv` to drop to uid 65534. The scripts are in `.claude/handoff/step2/execution/` and each one runs with `python3 <file>`.

Three findings change the design:
- **Peak RSS starts at the engine's own RSS on Linux.** A child's `ru_maxrss` can never read lower than the engine's memory size when it was spawned (§1). The runner has to start workloads through a small launcher process.
- **This host is very noisy.** Run-to-run variation (CV) is 9–28% (§6). The E2E fixture needs a speedup of at least 3x to clear the noise floor.
- **The judge's noise floor does not shrink when N grows**, because it uses the sample stdev (§6).

## 1. Per-run measurement (wall, CPU, peak RSS)

`exp1_wait4.py`. The 200 MiB run goes first, so cumulative values would show up as ≥200 in later rows:
```
alloc 200 MiB -> ru_maxrss= 213440 (=208.4 MiB if KiB)   alloc 10 MiB -> 18732   alloc 100 MiB -> 110900
spin 0.5s cpu -> cpu=0.520s wall=0.536s   sleep 0.5s -> cpu=0.029s wall=0.532s
RUSAGE_CHILDREN maxrss = 213440      exit 3 -> 3 ; SIGKILL -> -9
```
- **The values are per child.** `RUSAGE_CHILDREN` is cumulative, so it is the wrong source.
- **Units differ by platform.** Linux man7 getrusage(2) gives `ru_maxrss` "(in KiB)". Apple's xnu `bsd/man/man2/getrusage.2` gives it "(in bytes)". Use `MAXRSS_SCALE = 1 if sys.platform == "darwin" else 1024`.

**Popen pitfall** (`exp1b_pitfall.py`): `true exit code: 3 | Popen.wait() after raw reap w/o returncode: 0`. CPython's `_try_wait` swallows `ChildProcessError` and sets `sts = 0`, so the exit code is silently wrong. After `wait4` you must set `p.returncode = os.waitstatus_to_exitcode(status)` yourself. With that set, `wait()`, `poll()` and `kill()` become safe no-ops. `Popen.wait(timeout)` is a sleep-polling loop capped at 50 ms and returns no rusage. Measured walls: `wait4 0.143–0.151s` vs `Popen.wait(timeout) 0.165s` for a 0.123 s sleep.

**RSS floor** (`exp1e_rss_floor.py`), measuring `/bin/true`:
```
parent RSS ~ 311.5 MiB | /bin/true maxrss: Popen=311.5 fork+exec=308.7 posix_spawn=311.5 via small launcher=6.5 MiB
```
The kernel keeps the old address space's high-water mark across exec. With vfork and posix_spawn, that old address space is the parent's. An engine with LangGraph loaded would therefore floor every `peak_rss_bytes` at its own size. That makes the memory judge meaningless, and if the engine grows between baseline and trial it produces fake results.

The fix is a launcher (`launcher.py`): `python -I -S -c LAUNCHER <fd> <lo> argv...`, freshly exec'd and single-threaded. It forks and execs the workload, calls `wait4`, and writes JSON to a `pass_fds` pipe. Output of `exp1f_launcher.py` while the engine holds about 300 MiB: `workload 0MiB -> maxrss=8.5 MiB`, `50MiB -> 58.4 MiB`, `missing command -> 127`. Its wall time also leaves out interpreter startup.
```python
os.set_inheritable(fd, False)
t0 = time.perf_counter_ns(); pid = os.fork()
if pid == 0:
    try: os.execvp(argv[0], argv)
    finally: os._exit(127)
_, status, ru = os.wait4(pid, 0); t1 = time.perf_counter_ns()
os.write(fd, json.dumps({"wall_ns": t1-t0, "utime": ru.ru_utime, "stime": ru.ru_stime,
                          "maxrss": ru.ru_maxrss, "exit": os.waitstatus_to_exitcode(status)}).encode())
```
**Timeout handling** (engine side, `procrun.py`): a blocking `wait4` plus a watchdog thread, rather than WNOHANG polling. Polling adds latency jitter to the wall time.
```python
p = subprocess.Popen(argv, cwd=cwd, env=env, stdin=DEVNULL, stdout=PIPE, stderr=PIPE,
                     start_new_session=True, close_fds=True)          # pgid == p.pid
done = threading.Event()
def watchdog():
    if not done.wait(timeout_s): flags["timeout"] = True; _killpg(p.pid)   # SIGKILL group
threading.Thread(target=watchdog, daemon=True).start()
_, status, ru = os.wait4(p.pid, 0); done.set()                          # PEP 475 retries EINTR
p.returncode = os.waitstatus_to_exitcode(status)
_killpg(p.pid)                      # always: clean leftover group members; ignore ESRCH/EPERM
```
What happened in `exp1c_timeout.py` and `exp1d_group_drain.py`:
- A 0.5 s timeout on `sh -c 'sleep 30 & sleep 30 & ...'` ended with `timed_out=True wall=0.503`. The killed grandchildren stayed briefly as zombies under pid 1.
- `group empty after 1.358s`. pid 1 here reaps orphans lazily, so the runner should poll `os.killpg(pgid, 0)` until it raises ESRCH before starting the next timed run.
- A grandchild that calls `setsid` survives `killpg`. That is a documented limitation.
- `start_new_session` keeps the terminal's Ctrl-C from reaching the child, so the CLI must `killpg` in a `finally` block.

RECOMMENDATION: Use engine-side `Popen(start_new_session=True)` with a watchdog thread that sends SIGKILL to the group and a blocking `wait4` on the launcher. Set `returncode` manually. Take wall, CPU and peak RSS from the launcher's report, and scale maxrss by platform. Always `killpg` and wait for the group to empty after each run.

## 2. Grandchildren

`exp2_grandchildren.py`:
```
A child alone                                  maxrss=  10.9 MiB cpu=0.02s
B child waits for 200MiB grandchild            maxrss= 208.5 MiB cpu=1.98s
C child spawns 200MiB grandchild, no wait      maxrss=  11.3 MiB cpu=0.04s
D 4 parallel 200MiB workers (joined)           maxrss= 210.0 MiB cpu=7.41s
```
Descendants that were waited for are included: CPU time is summed, but RSS is the **maximum** over them, not the sum. Unwaited orphans are not counted at all. Linux man7 confirms this: "the resident set size of the largest child, not the maximum resident set size of the process tree".

Options, none of them free:
- `prctl(PR_SET_CHILD_SUBREAPER)` in the launcher. Linux only; catches orphans, but the value is still a maximum, not a sum.
- Sampling the `/proc` tree, or adding psutil as a dependency. Gives sums, but misses short spikes.
- cgroup v2 `memory.peak`. Needs delegation; Linux only.

RECOMMENDATION: Define `peak_rss_bytes` honestly as "largest single process among waited descendants" and say so in the report. Flag trial diffs that introduce process pools (`multiprocessing`, `ProcessPoolExecutor`, `subprocess`) as making the memory judge inconclusive, because splitting work across processes can game this metric.

## 3. Capture limits and fingerprints

`exp1c_timeout.py` (`yes | head -c 2G` with a 100 MiB limit):
```
flood case: flood=True bytes_seen=104882176 head_len=65536 wall=0.61   parent maxrss MiB: 17.5
big output: exit 2 bytes 10000000 head 65536 stderr tail ends b'EEEND' 8192   sha matches full stream: True
```
Design: reader threads drain both pipes, which avoids the 64 KiB pipe deadlock. Stdout goes through a streaming `sha256` over the **full** stream while keeping only the first 64 KiB. Stderr keeps its last 8 KiB. A hard cap of 256 MiB kills the group and marks the trial failed with "output flood".

`exp3_determinism.py`:
```
no PYTHONHASHSEED    distinct stdout fingerprints over 8 runs: 8
PYTHONHASHSEED=0     distinct stdout fingerprints over 8 runs: 1
timestamp/unseeded-random output: distinct fps: 3
```
For an optional declared output file:
- Validate the path with `normalize_path`, resolve symlinks, and require the result to stay inside the worktree.
- Cap its size.
- Compute the fingerprint as `sha256(len-prefixed stdout ‖ len-prefixed file)`.

RECOMMENDATION: Fingerprint the raw bytes of stdout plus the optional declared file, with `PYTHONHASHSEED=0` forced. If the N baseline runs disagree among themselves, report "nondeterministic output" (an event, with the equivalence judge inconclusive). Do not normalise the output, and ask the user for a seed or an output file.

## 4. Environment hygiene

`childenv.py`:
```python
PASS_THROUGH = ("PATH","LANG","LC_ALL","LC_CTYPE","TZ","TERM","VIRTUAL_ENV","CONDA_PREFIX","SYSTEMROOT")
FORCED = {"PYTHONHASHSEED":"0","PYTHONDONTWRITEBYTECODE":"1","PYTHONUNBUFFERED":"1","NO_COLOR":"1"}
SECRET = re.compile(r"(KEY|TOKEN|SECRET|PASSW|CREDENTIAL|AUTH|COOKIE|SESSION|PRIVATE|DSN|_URL$|PROXY)"
  r"|^(ANTHROPIC|OPENAI|AWS|AZURE|GOOGLE|GCP|GH|GITHUB|GITLAB|HF|HUGGING|NPM|PYPI|TWINE|DOCKER|KUBE|"
  r"VAULT|SSH|GPG|DATABASE|PG|REDIS|QDRANT|LD_|DYLD_)|^PYTHON(PATH|STARTUP|INSPECT|BREAKPOINT|HOME|"
  r"USERBASE|WARNINGS|EXECUTABLE)$", re.I)
def child_env(parent, *, home, tmpdir, extra=()):
    env = {n: parent[n] for n in (*PASS_THROUGH, *extra) if n in parent and not SECRET.search(n)}
    env.setdefault("PATH", os.defpath)
    env.update(HOME=home, TMPDIR=tmpdir, **FORCED)
    return env
```
`exp4_env.py`, with fake `ANTHROPIC_API_KEY`, `AWS_SECRET_ACCESS_KEY`, `DATABASE_URL`, `GITHUB_TOKEN`, `LD_PRELOAD`, `PYTHONSTARTUP`, and `MY_API_KEY` passed as an explicit extra:
```
child sees: ["HOME","LC_CTYPE","NO_COLOR","PATH","PYTHONDONTWRITEBYTECODE","PYTHONHASHSEED","PYTHONUNBUFFERED","TERM","TMPDIR"]
EMPTY env python works: 0 1 1 utf-8 utf-8 /usr     (utf8_mode=1 via PEP 538/540 coercion)
```
- Python needs no variables on Linux. macOS should behave the same, but verify on the M4.
- UTF-8 mode differs between an empty env and an inherited `LC_CTYPE`, so baseline and trial must get the identical env.
- A fresh `HOME` hides `~/.aws`, `~/.netrc` and `~/.config/gh` from naive reads. That is not a sandbox: absolute paths are still readable.

RECOMMENDATION: Build the env from an allowlist; pattern-deny wins even over user extras. Use a fresh `HOME` and `TMPDIR` per trial, outside the worktree. Resolve `command[0]` to an absolute path at CONNECT and drop relative `PATH` entries, so a trial cannot plant binaries.

## 5. Network isolation

`exp5_netns.py` sets up a listener on the parent's 127.0.0.1 and has the child connect to it, then to 1.1.1.1:
```
control (no sandbox)        CONNECTED INTERNET local-bind-ok
unshare -rn (root)          BLOCKED OSError 101  NO-INTERNET 101  local-bind-ok
unshare -rn as uid 65534    BLOCKED OSError 101  NO-INTERNET 101  local-bind-ok
maxrss plain 158.6 / unshare -rn 158.6 MiB  (exec in place: same pid)
startup plain 25.70±4.50 ms / unshare -rn 26.31±3.64 ms
```
- **Loopback** is down inside the new namespace, so even connecting to the workload's own listener fails with error 101. iproute2 (`ip`) is not installed here.
- **The launcher brings `lo` up** via `fcntl.ioctl(SIOCSIFFLAGS)`. Result: `loopback-self-connect OK / no internet 101`, also as uid 65534.
- **Linux overhead:** `unshare -rn true` costs 4.6 ms against 2.9 ms for plain `true`.
- **The namespace's loopback is private**, so trials cannot reach the user's localhost Postgres or Redis.

GitHub runners:
- **ubuntu-22.04:** expected to work. In [runner-images#10443](https://github.com/actions/runner-images/issues/10443), `unshare` worked there and failed on 24.04 with "Operation not permitted". That is a contributor statement, not maintainer documentation.
- **ubuntu-24.04:** Ubuntu's AppArmor restriction since 23.10 ([Canonical](https://ubuntu.com/blog/ubuntu-23-10-restricted-unprivileged-user-namespaces)) blocks it. The workaround is `sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0`.
- **Not confirmed:** the current state of the GitHub runner images themselves.

macOS: `sandbox-exec` is deprecated but reported working on 15.x and 26 ([gastown notes](https://gastown.dev/docs/research/macos-sandbox-exec), [claude-code#26095](https://github.com/anthropics/claude-code/issues/26095)). Anthropic's [sandbox-runtime](https://github.com/anthropic-experimental/sandbox-runtime) uses `sandbox-exec` on macOS and bubblewrap on Linux. macOS has no private loopback, so deny it too: `sandbox-exec -p '(version 1)(allow default)(deny network*)' launcher...`. This was not tested here and must be checked on the M4.

RECOMMENDATION: Wrap as `[unshare, -rn, --, py, -I, -S, -c, LAUNCHER, fd, "1", *argv]` on Linux and `[sandbox-exec, -p, PROFILE, py, ...LAUNCHER, fd, "0", *argv]` on macOS. Baseline and trials use the same wrapper.
- Add a setting `NETWORK_ISOLATION = required | best_effort | off`, default `required`, which fails closed.
- `best_effort` emits an event and marks the report.
- Probe availability once with `<wrapper> true`.
- Portable test: the parent listens on 127.0.0.1 and the sandboxed child must fail to connect, with a control run that succeeds. No internet needed. CI sets `REQUIRE_NETWORK_SANDBOX=1` so the test fails rather than skips, plus a CI probe step.

## 6. Warm-up, N runs, noise

`exp6_noise.py`, N=10, one warm-up run:
```
idle:    28.8ms CV=18.6% | 123.6ms 19.7% | 634.2ms 28.0% | 2719.6ms 7.2%
loaded (3 hogs/4 vCPU): 20.8ms 9.0% | 125.4ms 19.5% | 573.9ms 21.9% | 3350.1ms 8.9%
loaded + taskset -c 3:  24.7ms 16.8% | 122.6ms 21.8% | 659.8ms 22.7% | 3181.3ms 9.3%
```
`exp6b_samples.py`: wall CV is 15.8–19.6% and CPU-time CV is 16.5–19.2% too, with steal ticks of 8 and 25 during the series. So the noise comes from the host, and pinning does not help.

`noise_floor` uses `2 × sample stdev`, not the standard error, so a larger N only stabilises the estimate and does not lower the floor.

Fixture check (`exp6c_fixture.py`, N=5): `baseline 0.831s (CV 8.6%) -> trial 0.180s (CV 11.3%), gain 78.3% vs floor 17.3% -> passes=True; outputs equal=True` (O(n²) list membership replaced by `dict.fromkeys`).

GitHub runner noise is not known yet. Hosted Linux runners have 2 vCPU on private repos and 4 on public ones. Log the baseline CV in CI.

RECOMMENDATION:
- One discarded warm-up, then N = max(MIN_RUNS, workload.runs).
- Measure the baseline once per run, as designed, but have the combine re-test re-measure baseline and combination interleaved ABAB to control drift.
- Recommend at least 0.5–1 s per run; startup jitter is about 4 ms sd.
- Emit a `noisy_host` event reporting the smallest provable gain, max(2·CV, MIN_RELATIVE_GAIN).
- The E2E fixture needs a win of at least 3x.
- Do not pin CPUs: `sched_setaffinity` is Linux-only, showed no benefit here, and macOS has no equivalent.

## 7. cProfile profiler

`pyprof.py` (`profiled_argv`) and `pyprof2.py` (`hotspots`):
```python
_PY = re.compile(r"^python(\d+(\.\d+)?)?(\.exe)?$")
def profiled_argv(argv, out):
    if not argv or not _PY.match(Path(argv[0]).name): return None        # non-Python: skip + event
    i, opts = 1, []
    while i < len(argv) and argv[i].startswith("-") and argv[i] not in ("-m", "-c", "-"):
        opts.append(argv[i]); i += 1
        if opts[-1] in {"-W", "-X"}: opts.append(argv[i]); i += 1
    if i >= len(argv) or argv[i] in ("-c", "-"): return None              # cProfile has no -c
    return [argv[0], *opts, "-m", "cProfile", "-o", out, *argv[i:]]

def hotspots(prof, root, top=10):
    stats = pstats.Stats(prof).stats      # {(file,line,func): (cc, nc, tt, ct, callers)}
    total = sum(v[2] for v in stats.values()) or 1e-12
    rel = {k: _repo_rel(k[0], Path(root).resolve()) for k in stats}   # None for '~', '<frozen>', stdlib,
    charged = {k: v[2] for k, v in stats.items() if rel[k]}           # purelib/platlib, .venv, site-packages
    for callee, (*_, callers) in stats.items():                       # charge external callees to the
        if not rel[callee]:                                           # repo function that called them
            for caller, (_, _, _, ct) in callers.items():
                if caller in charged: charged[caller] += ct
    rows = [Row(rel[k], k[2], k[1], charged[k], stats[k][3], min(1.0, charged[k]/total), stats[k][1]) for k in charged]
    return sorted(rows, key=lambda r: r.self_time_s, reverse=True)[:top]
```
`exp7b.py` on the toy repo (`python -m app.main 20000`):
```
app/main.py  slow_unique  L3   self+ext= 0.579s cum= 0.579s share= 82.7% calls=1
app/text.py  tokenize     L2   self+ext= 0.097s cum= 0.097s share= 13.8% calls=20000
app/main.py  main         L11  self+ext= 0.011s cum= 0.691s share=  1.6% calls=1
```
`exp7_profile.py`: `-m mod` and `-X utf8 script.py` are wrapped correctly. `-c`, `pytest -q` and `./bench.sh` are skipped. Without charging external callees, `tokenize` showed only 10% because `re.findall` was booked as a builtin.

Caveats:
- Subprocess and multiprocessing workers are not profiled.
- A repo callback invoked from a builtin is double-counted, hence the `min(1, ...)` cap.
- cProfile overhead distorts call-heavy functions.

RECOMMENDATION: Profile in a separate, untimed run under the same env and sandbox, with the `.prof` file in a temp dir outside the worktree. Produce hotspots with paths relative to the repo, ranked by self time plus external-callee time, top N. For a non-Python command or `-c`, emit a `profile_skipped` event with the reason and continue with no hotspots.