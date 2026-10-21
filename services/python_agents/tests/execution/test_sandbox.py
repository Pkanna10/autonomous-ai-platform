"""Sandbox policy: the child environment, the wrapper argv and the launcher argv.

Everything here is pure and platform-independent: the darwin wrapper and
its SBPL profile are built and checked on Linux through an explicit
``platform`` on the policy, so the macOS CI job only has to confirm the
kernel side.
"""

from __future__ import annotations

import dataclasses
import json
import os
import sys
from pathlib import Path
from typing import TypedDict, get_args

import pytest

from autonomous_ai_agents.common.config import IsolationMode
from autonomous_ai_agents.execution import launcher
from autonomous_ai_agents.execution.sandbox import (
    DENY_PATTERNS,
    LAUNCHER_PATH,
    MODES,
    PASS_THROUGH,
    PLATFORMS,
    SandboxPolicy,
    child_env,
    launcher_argv,
    macos_profile,
    wrapper_argv,
)

UNSHARE = ["unshare", "-rn", "-p", "-f", "--"]


def policy(
    tmp_path: Path,
    *,
    network: IsolationMode = "required",
    fs: IsolationMode = "required",
    platform: str = "linux",
) -> SandboxPolicy:
    wt, scratch, probe = (tmp_path / "wt", tmp_path / "scratch", tmp_path / "probe")
    for path in (wt, scratch, probe):
        path.mkdir(exist_ok=True)
    return SandboxPolicy(
        network=network,
        fs=fs,
        writable=(wt, scratch),
        probe_dir=probe,
        platform=platform,
    )


# ---------------------------------------------------------------------------
# SandboxPolicy
# ---------------------------------------------------------------------------


def test_modes_and_platforms_match_the_settings_and_the_launcher() -> None:
    """
    GIVEN the isolation modes in settings and in the stdlib-only launcher
    WHEN they are compared with the sandbox module's
    THEN all three agree, so a mode cannot be valid on one side only
    """
    assert MODES == get_args(IsolationMode) == launcher.MODES
    assert PLATFORMS == launcher.PLATFORMS == ("linux", "darwin")


def test_policy_realpaths_its_paths_and_is_frozen(tmp_path: Path) -> None:
    """
    GIVEN writable and probe paths reached through a symlink
    WHEN a policy is built
    THEN it stores their realpaths (macOS /var -> /private/var) and is frozen
    """
    real = tmp_path / "real"
    (real / "wt").mkdir(parents=True)
    (real / "probe").mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)

    built = SandboxPolicy(
        network="off",
        fs="best_effort",
        writable=(link / "wt",),
        probe_dir=link / "probe",
        platform="darwin",
    )

    assert built.writable == (real.resolve() / "wt",)
    assert built.probe_dir == real.resolve() / "probe"
    with pytest.raises(dataclasses.FrozenInstanceError):
        built.fs = "off"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("network", "on", "network mode"),
        ("fs", "strict", "fs mode"),
        ("platform", "win32", "platform"),
        ("writable", (Path("rel/wt"),), "absolute"),
        ("writable", (Path("/"),), "filesystem root"),
        ("probe_dir", Path("rel/probe"), "absolute"),
    ],
)
def test_policy_refuses_invalid_fields(
    tmp_path: Path, field: str, value: object, message: str
) -> None:
    """
    GIVEN one invalid policy field
    WHEN the policy is built
    THEN ValueError names the problem
    """
    fields: dict[str, object] = {
        "network": "required",
        "fs": "required",
        "writable": (tmp_path / "wt",),
        "probe_dir": tmp_path / "probe",
        "platform": "linux",
        field: value,
    }

    with pytest.raises(ValueError, match=message):
        SandboxPolicy(**fields)  # type: ignore[arg-type]


@pytest.mark.parametrize("inside", ["wt", "wt/sub"])
def test_policy_refuses_a_probe_dir_inside_a_writable_dir(
    tmp_path: Path, inside: str
) -> None:
    """
    GIVEN a probe dir equal to or below a writable dir
    WHEN the policy is built
    THEN ValueError: the write self-check could never prove confinement
    """
    with pytest.raises(ValueError, match="probe_dir"):
        SandboxPolicy(
            network="off",
            fs="required",
            writable=(tmp_path / "wt",),
            probe_dir=tmp_path / inside,
            platform="linux",
        )


# ---------------------------------------------------------------------------
# child_env
# ---------------------------------------------------------------------------


class EnvPaths(TypedDict):
    home: Path
    tmpdir: Path
    worktree: Path


def env_paths(tmp_path: Path) -> EnvPaths:
    return {
        "home": tmp_path / "scratch" / "home",
        "tmpdir": tmp_path / "scratch" / "tmp",
        "worktree": tmp_path / "wt",
    }


def test_child_env_keeps_only_allowlisted_parent_variables(tmp_path: Path) -> None:
    """
    GIVEN a parent environment with safe and unrelated variables
    WHEN the child environment is built
    THEN only the allowlist passes, plus the forced engine values
    """
    (tmp_path / "wt").mkdir()
    base = {name: f"v-{name}" for name in PASS_THROUGH if name != "PATH"}
    base |= {"PATH": "/usr/bin:/bin", "EDITOR": "vim", "OMP_NUM_THREADS": "4"}

    env = child_env(**env_paths(tmp_path), base=base)

    paths = env_paths(tmp_path)
    expected = {name: f"v-{name}" for name in PASS_THROUGH if name != "PATH"}
    expected |= {
        "PATH": "/usr/bin:/bin",
        "PYTHONHASHSEED": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
        "HOME": str(paths["home"]),
        "TMPDIR": str(paths["tmpdir"]),
        "PYTHONPATH": str(paths["worktree"]),
    }
    assert env == expected


def test_child_env_adds_src_to_pythonpath_only_when_it_is_a_directory(
    tmp_path: Path,
) -> None:
    """
    GIVEN a worktree with a src/ directory, and one where src is a file
    WHEN the child environment is built
    THEN PYTHONPATH is <wt>:<wt>/src for the first and <wt> for the second
    """
    paths = env_paths(tmp_path)
    (paths["worktree"] / "src").mkdir(parents=True)
    other = tmp_path / "other"
    other.mkdir()
    (other / "src").write_text("not a package dir")

    with_src = child_env(**paths, base={})
    with_file = child_env(home=paths["home"], tmpdir=paths["tmpdir"], worktree=other)

    wt = paths["worktree"]
    assert with_src["PYTHONPATH"] == f"{wt}{os.pathsep}{wt / 'src'}"
    assert with_file["PYTHONPATH"] == str(other)


@pytest.mark.parametrize(
    "name",
    [
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_BASE_URL",
        "MY_API_KEY",
        "GITHUB_TOKEN",
        "GH_TOKEN",
        "AWS_REGION",
        "AWS_SECRET_ACCESS_KEY",
        "DATABASE_URL",
        "DATABASE",
        "PGPASSWORD",
        "PGHOST",
        "GIT_DIR",
        "GIT_CONFIG_GLOBAL",
        "SSH_AUTH_SOCK",
        "DB_PASSWORD",
        "CLIENT_SECRET",
        "SERVICE_URL",
        "HTTPS_PROXY",
        "https_proxy",
        "my_secret",
        "PYTHONPATH",
        "PYTHONSTARTUP",
        "PYTHONHOME",
        "PYTHONUSERBASE",
        "PYTHONINSPECT",
        "LD_PRELOAD",
        "LD_LIBRARY_PATH",
        "DYLD_INSERT_LIBRARIES",
        "CLAUDE_CODE_OAUTH_TOKEN",
        "REDIS_URL",
    ],
)
def test_child_env_deny_patterns_win_over_parent_and_extras(
    tmp_path: Path, name: str
) -> None:
    """
    GIVEN a secret-looking or interpreter-hijacking variable in the parent
        and as an explicit extra
    WHEN the child environment is built
    THEN it is absent (PYTHONPATH is the engine's own, never the user's)
    """
    env = child_env(
        **env_paths(tmp_path), base={name: "leak"}, extra={name: "leak-extra"}
    )

    assert name not in env or name == "PYTHONPATH"
    assert "leak" not in " ".join(env.values())


def test_deny_patterns_cover_the_lead_contract() -> None:
    """
    GIVEN the deny patterns the contract lists
    WHEN the module's patterns are read
    THEN every listed pattern is present verbatim
    """
    contract = {
        "*_TOKEN",
        "*_KEY",
        "*_SECRET",
        "*_PASSWORD",
        "*_URL",
        "ANTHROPIC_*",
        "AWS_*",
        "GITHUB_*",
        "GIT_*",
        "DATABASE*",
        "PG*",
        "SSH_*",
        "PYTHONSTARTUP",
        "PYTHONPATH",
    }

    assert contract <= set(DENY_PATTERNS)


def test_child_env_forced_values_win_over_extras_and_safe_extras_pass(
    tmp_path: Path,
) -> None:
    """
    GIVEN extras that try to override HOME, TMPDIR and the hash seed, and a
        harmless extra
    WHEN the child environment is built
    THEN the forced values win and the harmless extra passes
    """
    paths = env_paths(tmp_path)
    extra = {
        "HOME": "/root",
        "TMPDIR": "/tmp",
        "PYTHONHASHSEED": "random",
        "PYTHONDONTWRITEBYTECODE": "",
        "OMP_NUM_THREADS": "1",
    }

    env = child_env(**paths, base={}, extra=extra)

    assert env["HOME"] == str(paths["home"])
    assert env["TMPDIR"] == str(paths["tmpdir"])
    assert env["PYTHONHASHSEED"] == "0"
    assert env["PYTHONDONTWRITEBYTECODE"] == "1"
    assert env["OMP_NUM_THREADS"] == "1"


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/usr/bin:/bin", "/usr/bin:/bin"),
        (".:/usr/bin::bin:/bin:", "/usr/bin:/bin"),
        ("relative:./x", os.defpath),
        ("", os.defpath),
    ],
)
def test_child_env_drops_relative_path_entries(
    tmp_path: Path, path: str, expected: str
) -> None:
    """
    GIVEN a PATH with empty or relative entries (they resolve against the
        worktree, where a trial could plant a binary)
    WHEN the child environment is built
    THEN only absolute entries remain, or os.defpath when none does
    """
    env = child_env(**env_paths(tmp_path), base={"PATH": path})

    assert env["PATH"] == expected


def test_child_env_uses_defpath_when_path_is_missing(tmp_path: Path) -> None:
    """
    GIVEN a parent environment without PATH
    WHEN the child environment is built
    THEN PATH is os.defpath
    """
    assert child_env(**env_paths(tmp_path), base={})["PATH"] == os.defpath


def test_child_env_reads_os_environ_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    GIVEN os.environ with an allowlisted and a secret variable
    WHEN the child environment is built without a base
    THEN the allowlisted one passes and the secret does not
    """
    monkeypatch.setenv("TZ", "Europe/Berlin")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")

    env = child_env(**env_paths(tmp_path))

    assert env["TZ"] == "Europe/Berlin"
    assert "ANTHROPIC_API_KEY" not in env


@pytest.mark.parametrize("which", ["home", "tmpdir", "worktree"])
def test_child_env_refuses_relative_paths(tmp_path: Path, which: str) -> None:
    """
    GIVEN a relative home, tmpdir or worktree
    WHEN the child environment is built
    THEN ValueError: a relative path would resolve against the run's cwd
    """
    given = env_paths(tmp_path)
    paths = {"home": given["home"], "tmpdir": given["tmpdir"]}
    paths |= {"worktree": given["worktree"], which: Path("relative")}

    with pytest.raises(ValueError, match=which):
        child_env(
            home=paths["home"],
            tmpdir=paths["tmpdir"],
            worktree=paths["worktree"],
            base={},
        )


@pytest.mark.parametrize(
    ("name", "value"),
    [("", "x"), ("A=B", "x"), ("1ABC", "x"), ("A-B", "x"), ("A\0", "x"), ("A", "x\0")],
)
def test_child_env_refuses_malformed_extras(
    tmp_path: Path, name: str, value: str
) -> None:
    """
    GIVEN an extra whose name is not an identifier or whose value holds a NUL
    WHEN the child environment is built
    THEN ValueError
    """
    with pytest.raises(ValueError, match="extra"):
        child_env(**env_paths(tmp_path), base={}, extra={name: value})


# ---------------------------------------------------------------------------
# wrapper_argv and macos_profile
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("network", ["required", "best_effort"])
@pytest.mark.parametrize("fs", ["required", "best_effort", "off"])
def test_linux_wrapper_is_unshare_when_the_network_is_isolated(
    tmp_path: Path, network: IsolationMode, fs: IsolationMode
) -> None:
    """
    GIVEN a Linux policy whose network mode is not off
    WHEN the wrapper is built
    THEN it is unshare with user, network and PID namespaces and a fork
    """
    assert wrapper_argv(policy(tmp_path, network=network, fs=fs)) == UNSHARE


@pytest.mark.parametrize("fs", ["required", "best_effort", "off"])
def test_linux_wrapper_is_empty_when_the_network_is_off(
    tmp_path: Path, fs: IsolationMode
) -> None:
    """
    GIVEN a Linux policy with the network off
    WHEN the wrapper is built
    THEN there is none (Landlock needs no wrapper; the launcher applies it)
    """
    assert wrapper_argv(policy(tmp_path, network="off", fs=fs)) == []


@pytest.mark.parametrize(
    ("network", "fs"),
    [("required", "required"), ("best_effort", "off"), ("off", "best_effort")],
)
def test_darwin_wrapper_is_sandbox_exec_with_the_profile(
    tmp_path: Path, network: IsolationMode, fs: IsolationMode
) -> None:
    """
    GIVEN a darwin policy with any isolation on
    WHEN the wrapper is built
    THEN it is sandbox-exec -p with the policy's profile
    """
    built = policy(tmp_path, network=network, fs=fs, platform="darwin")

    assert wrapper_argv(built) == ["sandbox-exec", "-p", macos_profile(built)]


def test_darwin_wrapper_is_empty_when_everything_is_off(tmp_path: Path) -> None:
    """
    GIVEN a darwin policy with both modes off
    WHEN the wrapper is built
    THEN there is none
    """
    built = policy(tmp_path, network="off", fs="off", platform="darwin")

    assert wrapper_argv(built) == []


def test_macos_profile_denies_network_and_writes_except_the_writable_dirs(
    tmp_path: Path,
) -> None:
    """
    GIVEN a darwin policy with both modes required
    WHEN the profile is built
    THEN it allows by default, denies network* and file-write*, then allows
        writes below the realpath'd writable dirs and to /dev/null
    """
    built = policy(tmp_path, platform="darwin")
    wt, scratch = built.writable

    profile = macos_profile(built)

    assert profile.splitlines() == [
        "(version 1)",
        "(allow default)",
        "(deny network*)",
        "(deny file-write*)",
        f'(allow file-write* (subpath "{wt}") (subpath "{scratch}")'
        ' (literal "/dev/null"))',
    ]


@pytest.mark.parametrize(
    ("network", "fs", "has_network", "has_files"),
    [
        ("required", "off", True, False),
        ("off", "required", False, True),
        ("best_effort", "best_effort", True, True),
    ],
)
def test_macos_profile_only_holds_the_rules_its_modes_ask_for(
    tmp_path: Path,
    network: IsolationMode,
    fs: IsolationMode,
    has_network: bool,
    has_files: bool,
) -> None:
    """
    GIVEN a darwin policy with one or both modes on
    WHEN the profile is built
    THEN it holds the network rule and the file rules only for modes not off
    """
    profile = macos_profile(policy(tmp_path, network=network, fs=fs, platform="darwin"))

    assert ("(deny network*)" in profile) is has_network
    assert ("(deny file-write*)" in profile) is has_files
    assert ("(allow file-write*" in profile) is has_files


@pytest.mark.parametrize("bad", ['quo"te', "back\\slash", "new\nline", "tab\there"])
def test_macos_profile_refuses_paths_it_cannot_quote(tmp_path: Path, bad: str) -> None:
    """
    GIVEN a writable dir whose name holds a double quote, a backslash or a
        control character
    WHEN the profile is built
    THEN ValueError rather than an SBPL string that could be broken out of
    """
    built = SandboxPolicy(
        network="off",
        fs="required",
        writable=(tmp_path / bad,),
        probe_dir=tmp_path / "probe",
        platform="darwin",
    )

    with pytest.raises(ValueError, match="SBPL"):
        macos_profile(built)


# ---------------------------------------------------------------------------
# launcher_argv
# ---------------------------------------------------------------------------


def test_launcher_path_is_the_stdlib_launcher_module() -> None:
    """
    GIVEN the launcher module
    WHEN LAUNCHER_PATH is read
    THEN it is that module's absolute file
    """
    assert LAUNCHER_PATH == Path(launcher.__file__).resolve()
    assert LAUNCHER_PATH.name == "launcher.py"
    assert LAUNCHER_PATH.is_file()


def test_launcher_argv_layout_and_spec_on_linux(tmp_path: Path) -> None:
    """
    GIVEN a Linux policy with both modes required
    WHEN the launcher argv is built
    THEN it is unshare, python -I -S launcher.py fd spec -- argv, and the
        spec JSON carries exactly the contract keys
    """
    built = policy(tmp_path)

    argv = launcher_argv(
        built, fd=7, report_port=40001, argv=["/usr/bin/python3", "bench.py"]
    )

    assert argv[:5] == UNSHARE
    assert argv[5:9] == [sys.executable, "-I", "-S", str(LAUNCHER_PATH)]
    assert argv[9] == "7"
    assert argv[11:] == ["--", "/usr/bin/python3", "bench.py"]
    assert json.loads(argv[10]) == {
        "version": 1,
        "platform": "linux",
        "fs": "required",
        "net": "required",
        "writable": [str(p) for p in built.writable],
        "probe_dir": str(built.probe_dir),
        "probe_port": 40001,
    }


def test_launcher_argv_without_wrapper_and_port(tmp_path: Path) -> None:
    """
    GIVEN a Linux policy with the network off, no probe port and a python
    WHEN the launcher argv is built
    THEN it starts with that python and the spec's probe_port is null
    """
    built = policy(tmp_path, network="off")

    argv = launcher_argv(
        built, fd=3, report_port=None, argv=["/bin/true"], python="/opt/py/bin/python"
    )

    assert argv[:4] == ["/opt/py/bin/python", "-I", "-S", str(LAUNCHER_PATH)]
    assert json.loads(argv[5])["probe_port"] is None
    assert json.loads(argv[5])["net"] == "off"


def test_launcher_argv_on_darwin_starts_with_sandbox_exec(tmp_path: Path) -> None:
    """
    GIVEN a darwin policy
    WHEN the launcher argv is built
    THEN the wrapper is sandbox-exec and the spec says darwin
    """
    built = policy(tmp_path, platform="darwin")

    argv = launcher_argv(built, fd=5, report_port=1, argv=["/bin/true"])

    assert argv[:3] == ["sandbox-exec", "-p", macos_profile(built)]
    assert json.loads(argv[8])["platform"] == "darwin"


def test_launcher_argv_spec_is_accepted_by_the_launcher(tmp_path: Path) -> None:
    """
    GIVEN a launcher argv built by the sandbox module
    WHEN the launcher parses its own arguments from it
    THEN it gets back the fd, the policy and the workload argv unchanged
    """
    built = policy(tmp_path, network="best_effort", fs="required")
    argv = launcher_argv(built, fd=9, report_port=65535, argv=["/bin/echo", "a b"])
    start = argv.index(str(LAUNCHER_PATH)) + 1

    fd, spec, workload = launcher.parse_args(argv[start:])

    assert fd == 9
    assert workload == ["/bin/echo", "a b"]
    assert (spec.platform, spec.fs, spec.net) == ("linux", "required", "best_effort")
    assert spec.writable == tuple(str(p) for p in built.writable)
    assert spec.probe_dir == str(built.probe_dir)
    assert spec.probe_port == 65535


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"fd": 2}, "fd"),
        ({"report_port": 0}, "report_port"),
        ({"report_port": 65536}, "report_port"),
        ({"argv": []}, "argv"),
        ({"argv": ["/bin/echo", "a\0b"]}, "NUL"),
        ({"python": "python3"}, "python"),
    ],
)
def test_launcher_argv_refuses_invalid_arguments(
    tmp_path: Path, kwargs: dict[str, object], message: str
) -> None:
    """
    GIVEN an fd that is a standard stream, a port out of range, an empty or
        NUL-holding argv, or a relative interpreter
    WHEN the launcher argv is built
    THEN ValueError names the argument
    """
    call: dict[str, object] = {
        "fd": 3,
        "report_port": 1234,
        "argv": ["/bin/true"],
    } | kwargs

    with pytest.raises(ValueError, match=message):
        launcher_argv(policy(tmp_path), **call)  # type: ignore[arg-type]
