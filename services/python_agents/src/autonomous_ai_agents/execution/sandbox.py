"""Sandbox policy for workload and test runs: environment, wrapper, launcher argv.

A ``SandboxPolicy`` holds the network and write modes (``required`` fails
closed, ``best_effort`` records, ``off``), the dirs a workload may write
(worktree, ``_scratch/<phase>``), the ``_probe/<phase>`` dir it must not
write (the launcher's self-check) and the platform, injected so the darwin
path is tested on Linux. ``launcher_argv`` turns it into::

    [unshare -rn -p -f --ipc --mount-proc -- | sandbox-exec -p PROFILE]
        python -I -S launcher.py <fd> <spec-json> -- argv...

``child_env`` builds the environment from an allowlist; deny patterns win
even over explicit extras.
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path
from typing import get_args

from autonomous_ai_agents.common.config import IsolationMode
from autonomous_ai_agents.execution import launcher

LAUNCHER_PATH: Path = Path(launcher.__file__).resolve()
"""The stdlib-only launcher, run by path as ``python -I -S``."""

MODES: tuple[str, ...] = get_args(IsolationMode)
PLATFORMS: tuple[str, ...] = ("linux", "darwin")

UNSHARE_ARGV: tuple[str, ...] = (
    "unshare",
    "-rn",
    "-p",
    "-f",
    "--ipc",
    "--mount-proc",
    "--",
)
"""User, network, PID and IPC namespaces. ``-f`` makes the launcher PID 1
there; ``--ipc`` gives every run its own SysV IPC and POSIX message queues, so
a warm-up cannot leave a memoised answer for a timed run; ``--mount-proc``
gives a private ``/proc`` that lists only this namespace's PIDs (it also hides
the ``unshare`` process, which still holds the report pipe). The last assumes
this ``/proc`` is the only procfs the sandbox can see: another procfs of the
outer PID namespace mounted elsewhere (a ``/host/proc`` bind, say) would show
the ``unshare`` process again, and the defensive tests walk every procfs mount
so such a host fails them."""

PASS_THROUGH: tuple[str, ...] = tuple(
    "PATH LANG LC_ALL LC_CTYPE TERM TZ SYSTEMROOT VIRTUAL_ENV CONDA_PREFIX".split()
)
"""The only parent variables a workload sees (research §4)."""

DENY_PATTERNS: tuple[str, ...] = tuple(
    # Secrets by shape.
    """*_TOKEN *_KEY *_KEY_* *APIKEY* *_SECRET *_PASSWORD *_PASS *_URL *_URI
    *_DSN *TOKEN* *SECRET* *PASSW* *CREDENTIAL* *AUTH* *COOKIE* *SESSION*
    *PRIVATE* *PROXY*"""
    # Secrets by owner.
    """ ANTHROPIC_* CLAUDE* OPENAI_* AWS_* AZURE_* GOOGLE_* GCP_* GCLOUD_* GH_*
    GITHUB_* GITLAB_* GIT_* HF_* HUGGING* NPM_* PYPI_* TWINE_* DOCKER_* KUBE*
    VAULT_* SSH_* GPG_* GNUPG* DATABASE* PG* POSTGRES* MYSQL* REDIS* QDRANT*"""
    # Loader and interpreter hijacks.
    """ LD_* DYLD_* PYTHONPATH PYTHONSTARTUP PYTHONHOME PYTHONINSPECT
    PYTHONBREAKPOINT PYTHONUSERBASE PYTHONEXECUTABLE PYTHONWARNINGS""".split()
)
"""Matched case-insensitively; a match drops the variable, extras included."""

FORCED: Mapping[str, str] = {"PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1"}

_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _realpath(what: str, path: Path) -> Path:
    if not path.is_absolute():
        raise ValueError(f"{what} path {str(path)!r} must be absolute")
    return Path(os.path.realpath(path))


@dataclass(frozen=True)
class SandboxPolicy:
    """How one run is isolated; every path is absolute and realpath'd."""

    network: IsolationMode
    fs: IsolationMode
    writable: tuple[Path, ...]
    probe_dir: Path
    platform: str

    def __post_init__(self) -> None:
        for what, mode in (("network", self.network), ("fs", self.fs)):
            if mode not in MODES:
                raise ValueError(f"{what} mode {mode!r} is not one of {MODES}")
        if self.platform not in PLATFORMS:
            raise ValueError(f"platform {self.platform!r} is not one of {PLATFORMS}")
        writable = tuple(_realpath("writable", path) for path in self.writable)
        probe_dir = _realpath("probe_dir", self.probe_dir)
        for path in writable:
            if path == Path(path.anchor):
                raise ValueError("writable must not hold the filesystem root")
            if probe_dir.is_relative_to(path):
                raise ValueError(f"probe_dir {probe_dir} is inside writable {path}")
        object.__setattr__(self, "writable", writable)
        object.__setattr__(self, "probe_dir", probe_dir)


def denied(name: str) -> bool:
    """Whether an environment variable name matches a deny pattern."""
    upper = name.upper()
    return any(fnmatchcase(upper, pattern) for pattern in DENY_PATTERNS)


def _absolute_entries(path: str) -> str:
    """Only absolute PATH entries: empty or relative ones resolve in the worktree."""
    entries = [entry for entry in path.split(os.pathsep) if os.path.isabs(entry)]
    return os.pathsep.join(entries) or os.defpath


def child_env(
    *,
    home: Path,
    tmpdir: Path,
    worktree: Path,
    base: Mapping[str, str] | None = None,
    extra: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """The workload's environment: allowlisted, secret-free, engine-forced.

    ``base`` defaults to ``os.environ``. ``extra`` adds variables, but a deny
    pattern still drops them, and the forced values (hash seed, no bytecode,
    a fresh ``HOME`` and ``TMPDIR``, ``PYTHONPATH=<wt>[:<wt>/src]``) win.
    """
    for what, path in (("home", home), ("tmpdir", tmpdir), ("worktree", worktree)):
        if not path.is_absolute():
            raise ValueError(f"{what} {str(path)!r} must be absolute")
    source = os.environ if base is None else base
    env = {name: source[name] for name in PASS_THROUGH if name in source}
    for name, value in (extra or {}).items():
        if _ENV_NAME.fullmatch(name) is None or "\0" in value:
            raise ValueError(f"extra {name!r} is not a valid environment variable")
        env[name] = value
    env = {name: value for name, value in env.items() if not denied(name)}
    env["PATH"] = _absolute_entries(env.get("PATH", ""))
    pythonpath = [str(worktree)]
    if (worktree / "src").is_dir():
        pythonpath.append(str(worktree / "src"))
    env.update(FORCED)
    env.update(
        HOME=str(home), TMPDIR=str(tmpdir), PYTHONPATH=os.pathsep.join(pythonpath)
    )
    return env


def _sbpl_string(path: Path) -> str:
    text = str(path)
    if any(char in '"\\' or ord(char) < 0x20 or ord(char) == 0x7F for char in text):
        raise ValueError(f"path {text!r} cannot be quoted safely in an SBPL profile")
    return f'"{text}"'


def macos_profile(policy: SandboxPolicy) -> str:
    """The ``sandbox-exec -p`` profile: allow by default, deny what is isolated."""
    rules = ["(version 1)", "(allow default)"]
    if policy.network != "off":
        rules.append("(deny network*)")
    if policy.fs != "off":
        allowed = [f"(subpath {_sbpl_string(path)})" for path in policy.writable]
        allowed.append(f"(literal {_sbpl_string(Path(os.devnull))})")
        rules.append("(deny file-write*)")
        rules.append("(allow file-write* " + " ".join(allowed) + ")")
    return "\n".join(rules)


def wrapper_argv(policy: SandboxPolicy) -> list[str]:
    """The command that wraps the launcher, or ``[]`` when none is needed."""
    if policy.platform == "linux":
        return list(UNSHARE_ARGV) if policy.network != "off" else []
    if policy.network == "off" and policy.fs == "off":
        return []
    return ["sandbox-exec", "-p", macos_profile(policy)]


def launcher_argv(
    policy: SandboxPolicy,
    *,
    fd: int,
    report_port: int | None,
    argv: Sequence[str],
    python: str = sys.executable,
) -> list[str]:
    """``[*wrapper, python, -I, -S, launcher.py, fd, spec, --, *argv]``.

    ``fd`` is the report pipe the caller passes with ``pass_fds``;
    ``report_port`` is the parent's 127.0.0.1 probe listener (the spec's
    ``probe_port``), ``None`` when there is none.
    """
    if fd < 3:
        raise ValueError(f"fd {fd} must not be a standard stream")
    if report_port is not None and not 0 < report_port < 65536:
        raise ValueError(f"report_port {report_port} is not a port number")
    if not argv:
        raise ValueError("argv must name a command")
    if any("\0" in arg for arg in argv):
        raise ValueError("argv must not contain NUL bytes")
    if not os.path.isabs(python):
        raise ValueError(f"python {python!r} must be an absolute path")
    spec = {
        "version": launcher.SPEC_VERSION,
        "platform": policy.platform,
        "fs": policy.fs,
        "net": policy.network,
        "writable": [str(path) for path in policy.writable],
        "probe_dir": str(policy.probe_dir),
        "probe_port": report_port,
    }
    launch = [python, "-I", "-S", str(LAUNCHER_PATH), str(fd)]
    return [*wrapper_argv(policy), *launch, json.dumps(spec), "--", *argv]
