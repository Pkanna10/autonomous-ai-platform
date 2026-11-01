"""Tests for the Step 3 protected-pattern gaps (U5, spec D23).

Install and interpreter configuration a trial could use to change what is
installed or which Python runs: pip and uv config, pip-tools inputs, pip
constraints, PEP 751 and PDM lockfiles, and interpreter pins. Each new
pattern refuses a diff at any depth and in any case, near-miss source and
data paths stay editable, and the path forms an attacker controls (separators,
``./`` prefixes, renames, symlinks, paths outside the repository) cannot
slip past the rule.
"""

from __future__ import annotations

import pytest

from autonomous_ai_agents.common.models import ViolationRule
from autonomous_ai_agents.execution.protocols import Change
from autonomous_ai_agents.optimization.anticheat import (
    DEFAULT_PROTECTED_PATTERNS,
    check_capture,
    check_diff,
    check_diff_all,
    check_path,
)

INSTALL_CONFIG_FILES: tuple[tuple[str, str], ...] = (
    # D23: each changes what is installed or which interpreter runs.
    ("pip.conf", "**/pip.conf"),  # pip's site config, read from a venv root
    ("uv.toml", "**/uv.toml"),  # uv's project config (index, sources)
    ("requirements.in", "**/requirements*.in"),  # pip-tools input
    ("requirements-dev.in", "**/requirements*.in"),
    ("requirements/base.in", "**/requirements*.in"),  # pip-tools' folder layout
    ("constraints.txt", "**/constraints*.txt"),  # pip -c
    ("constraints-ci.txt", "**/constraints*.txt"),
    ("pylock.toml", "**/pylock*.toml"),  # PEP 751
    ("pylock.dev.toml", "**/pylock*.toml"),
    ("pdm.lock", "**/pdm.lock"),
    (".python-version", "**/.python-version"),  # uv and pyenv interpreter pin
    # Beyond D23's list, same intent (the report names them as a deviation).
    (".python-versions", "**/.python-versions"),  # uv's multi-version pin
    (".pdm-python", "**/.pdm-python"),  # PDM's selected interpreter path
    ("pdm.toml", "**/pdm.toml"),  # PDM project config (sources, venv)
    ("poetry.toml", "**/poetry.toml"),  # Poetry local config (repositories)
    # From the U5 security review: an added file of these overrides config the
    # test command reads, or picks the interpreter a shim on PATH runs.
    ("hatch.toml", "**/hatch.toml"),  # wins over pyproject's [tool.hatch]
    ("tox.toml", "**/tox.toml"),  # tox 4.21+ native config (deps, base_python)
    (".tool-versions", "**/.tool-versions"),  # asdf and mise interpreter pin
    ("mise.toml", "**/mise.toml"),
    (".mise.toml", "**/.mise.toml"),
    ("pip.ini", "**/pip.ini"),  # pip's site config on Windows
    ("pixi.toml", "**/pixi.toml"),  # pixi run installs from these
    ("pixi.lock", "**/pixi.lock"),
    ("requirements.lock", "**/requirements*.lock"),  # rye
    ("requirements-dev.lock", "**/requirements*.lock"),
)


@pytest.mark.parametrize(("name", "pattern"), INSTALL_CONFIG_FILES)
@pytest.mark.parametrize("folder", ["", "sub/", ".venv/", "src/pkg/"])
def test_every_install_config_file_is_protected(
    folder: str, name: str, pattern: str
) -> None:
    """
    GIVEN an install or interpreter config file, at the root or nested (uv,
        pip-tools and pyenv search parent directories; pip reads a venv's
        own pip.conf)
    WHEN checked against the default patterns, as written and upper-cased
        (a case-insensitive checkout reads PIP.CONF as pip.conf)
    THEN it is a protected_path violation naming its own pattern
    """
    assert pattern in DEFAULT_PROTECTED_PATTERNS
    for path in (folder + name, (folder + name).upper()):
        violation = check_path(path)

        assert violation is not None, path
        assert violation.rule is ViolationRule.protected_path
        assert violation.pattern == pattern
        assert violation.path == path


@pytest.mark.parametrize(
    "raw",
    [
        "sub\\uv.toml",  # Windows separators
        "./pip.conf",
        "sub//.python-version",
        "./src/./pylock.toml",
        "Sub\\Requirements-Dev.IN",
    ],
)
def test_install_config_is_protected_in_every_path_spelling(raw: str) -> None:
    """
    GIVEN an install config path spelled with backslashes, ./ or doubled slashes
    WHEN checked
    THEN it is normalised first and still refused as protected_path
    """
    violation = check_path(raw)

    assert violation is not None, raw
    assert violation.rule is ViolationRule.protected_path


@pytest.mark.parametrize(
    "raw", ["../pip.conf", "/etc/pip.conf", "~/.config/uv/uv.toml", "a/../uv.toml"]
)
def test_install_config_outside_the_repository_is_refused(raw: str) -> None:
    """
    GIVEN a config path that leaves the repository (a parent's pip.conf, the
        system or user uv config)
    WHEN checked
    THEN it is refused as path_traversal, never treated as an ordinary file
    """
    violation = check_path(raw)

    assert violation is not None
    assert violation.rule is ViolationRule.path_traversal


def test_a_rename_onto_or_off_an_install_config_is_refused() -> None:
    """
    GIVEN a diff (git diff --no-renames) renaming notes.txt to uv.toml and
        pip.conf to pip.conf.bak: each rename is a delete plus an add
    WHEN checked
    THEN both the added uv.toml and the deleted pip.conf are violations
    """
    touched = ("notes.txt", "uv.toml", "pip.conf", "pip.conf.bak")

    every = check_diff_all(touched)

    assert [(v.path, v.pattern) for v in every] == [
        ("uv.toml", "**/uv.toml"),
        ("pip.conf", "**/pip.conf"),
    ]
    first = check_diff(touched)
    assert first is not None
    assert first.path == "uv.toml"


def test_a_symlink_to_an_install_config_is_refused() -> None:
    """
    GIVEN a trial adding an innocently named symlink whose target is uv.toml
    WHEN its capture is checked
    THEN the link's mode is refused, whatever it points at
    """
    link = Change(status="A", path="src/settings", old_mode="000000", new_mode="120000")

    violations = check_capture(
        (link,), {"src/settings": 7}, {"src/settings": b"uv.toml"}, frozenset()
    )

    assert [v.rule for v in violations] == [ViolationRule.forbidden_file_mode]


@pytest.mark.parametrize(
    "path",
    [
        "src/pip_conf.py",
        "src/pip.conf.py",
        "docs/pip.conf.md",
        "src/mypip.conf",
        "src/uv_toml.py",
        "docs/uv.toml.md",
        "src/requirements.py",
        "src/requirements_in.py",
        "data/requirements.json",
        "src/constraints.py",
        "docs/constraints.md",
        "src/pylock.py",
        "src/pdm_lock.py",
        "src/pdm.lock.py",
        "src/python_version.py",
        "src/python-version.txt",
        ".python-version.bak",
        "src/poetry_toml.py",
    ],
)
def test_install_config_lookalikes_stay_editable(path: str) -> None:
    """
    GIVEN a source or data path that only resembles an install config name
    WHEN checked
    THEN no violation is reported: the trial may still edit it
    """
    assert check_path(path) is None
