"""Tests for the shared path rules (Step 2, unit U1).

``matches_pattern`` is the single matcher behind the protected-path check,
the editor's read and write deny lists and the capture rules, so it keeps
every case the old private ``anticheat._matches`` handled. The pattern
constants are shared by the editor handler (U7) and the capture rules (U9),
so both enforce one definition.
"""

from __future__ import annotations

import pytest

from autonomous_ai_agents.common.paths import (
    GIT_METADATA_NAMES,
    READ_DENY_PATTERNS,
    WRITE_DENY_PATTERNS,
    matches_pattern,
)
from autonomous_ai_agents.optimization import anticheat


def _any(path: str, patterns: tuple[str, ...]) -> bool:
    return any(matches_pattern(path, pattern) for pattern in patterns)


# ---------------------------------------------------------------------------
# matches_pattern: the cases the old anticheat._matches covered
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "pattern"),
    [
        pytest.param("tests/test_x.py", "**/tests/**", id="root-level dir via **/"),
        pytest.param("src/pkg/tests/test_y.py", "**/tests/**", id="nested dir"),
        pytest.param("conftest.py", "**/conftest.py", id="root-level file via **/"),
        pytest.param("a/b/conftest.py", "**/conftest.py", id="nested file"),
        pytest.param("src/Conftest.py", "**/conftest.py", id="path case folded"),
        pytest.param("PYPROJECT.TOML", "**/pyproject.toml", id="upper-case path"),
        pytest.param("pyproject.toml", "**/PyProject.toml", id="pattern case folded"),
        pytest.param("Tests/Test_Case.py", "**/tests/**", id="mixed case dir"),
        pytest.param(".GitHub/workflows/CI.yml", ".github/**", id="anchored dir"),
        pytest.param("Jenkinsfile", "Jenkinsfile", id="exact name"),
        pytest.param("src/x/test_data_loader.py", "**/test_*.py", id="glob name"),
        pytest.param("pkg/m.pyc", "*.pyc", id="star crosses slashes"),
    ],
)
def test_matches_pattern_matches(path: str, pattern: str) -> None:
    """
    GIVEN a path and a pattern that should cover it
    WHEN matches_pattern compares them
    THEN it matches, case-insensitively, with ``**/x`` also matching a root ``x``
    """
    assert matches_pattern(path, pattern)


@pytest.mark.parametrize(
    ("path", "pattern"),
    [
        pytest.param("src/attestsrc.py", "**/tests/**", id="substring is not a dir"),
        pytest.param("src/contest/results.py", "**/conftest.py", id="similar name"),
        pytest.param("docs/testing.md", "**/test_*.py", id="different suffix"),
        pytest.param("sub/Jenkinsfile", "Jenkinsfile", id="anchored name nested"),
        pytest.param("workflows/ci.yml", ".github/**", id="anchored dir missing"),
        pytest.param("src/engine_toolkit.py", "**/engine.toml", id="prefix only"),
    ],
)
def test_matches_pattern_does_not_match(path: str, pattern: str) -> None:
    """
    GIVEN a path that merely resembles the pattern
    WHEN matches_pattern compares them
    THEN it does not match
    """
    assert not matches_pattern(path, pattern)


def test_root_fallback_applies_only_to_a_leading_double_star() -> None:
    """
    GIVEN a pattern with ``/**/`` in the middle rather than a leading ``**/``
    WHEN a path with no directory between the two parts is matched
    THEN the root fallback does not apply (only a leading ``**/`` is stripped)
    """
    assert not matches_pattern("src/core.py", "src/**/core.py")
    assert matches_pattern("src/pkg/core.py", "src/**/core.py")


def test_anticheat_uses_the_shared_matcher() -> None:
    """
    GIVEN the anticheat module after the move
    WHEN its namespace is inspected
    THEN the private matcher is gone and check_path still folds case
    """
    assert not hasattr(anticheat, "_matches")
    violation = anticheat.check_path("src/Conftest.py")
    assert violation is not None
    assert violation.pattern == "**/conftest.py"


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_git_metadata_names_are_the_spec_tuple() -> None:
    """
    GIVEN the git metadata names the editor and the capture rules block
    WHEN inspected
    THEN they are exactly .git, .gitattributes, .gitmodules and .lfsconfig
    """
    assert GIT_METADATA_NAMES == (".git", ".gitattributes", ".gitmodules", ".lfsconfig")
    assert ".gitignore" not in GIT_METADATA_NAMES


def test_write_deny_patterns_are_the_spec_tuple() -> None:
    """
    GIVEN the write deny list
    WHEN inspected
    THEN it is the spec's bytecode and native-library tuple
    """
    assert WRITE_DENY_PATTERNS == (
        "**/__pycache__/**",
        "*.pyc",
        "*.pyo",
        "*.so",
        "*.pyd",
        "*.dylib",
        "*.dll",
    )


@pytest.mark.parametrize(
    "path",
    [
        "pkg/__pycache__/m.cpython-311.pyc",
        "__pycache__/x.txt",
        "pkg/__pycache__/m.pyc",
        "m.pyc",
        "pkg/m.pyo",
        "fast.SO",
        "ext.SO",
        "lib/_speedups.so",
        "lib.dylib",
        "native/x.PYD",
        "win/helper.dll",
    ],
)
def test_write_deny_patterns_cover_compiled_artefacts(path: str) -> None:
    """
    GIVEN a compiled artefact at any depth and in any case
    WHEN matched against WRITE_DENY_PATTERNS
    THEN at least one pattern covers it
    """
    assert _any(path, WRITE_DENY_PATTERNS)


@pytest.mark.parametrize(
    "path",
    ["docs/so.md", "src/core.py", "data/table.json", "src/pycache_tools.py", "a.sox"],
)
def test_write_deny_patterns_leave_sources_alone(path: str) -> None:
    """
    GIVEN an ordinary source or data path
    WHEN matched against WRITE_DENY_PATTERNS
    THEN no pattern covers it
    """
    assert not _any(path, WRITE_DENY_PATTERNS)


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        "config/.env",
        ".env.local",
        "deploy/.env.production",
        ".envrc",
        "certs/server.pem",
        "tls.PEM",
        "keys/private.key",
        "id_rsa",
        "home/.ssh/id_rsa.pub",
        "id_ed25519",
        ".ssh/id_ecdsa",
        ".ssh/id_dsa",
        ".ssh/id_ecdsa_sk.pub",
        ".ssh/id_ed25519_sk",
        ".netrc",
        "ci/.npmrc",
        ".pypirc",
        "certs/client.p12",
        "store.pfx",
        "credentials.json",
        "aws/credentials",
        ".aws/credentials",
        "config/credentials.yml",
        "secrets.yaml",
        "config/secrets.toml",
    ],
)
def test_read_deny_patterns_cover_secret_files(path: str) -> None:
    """
    GIVEN a file that commonly holds secrets, at the root or nested
    WHEN matched against READ_DENY_PATTERNS
    THEN at least one pattern covers it, so the editor never sends it to the API
    """
    assert _any(path, READ_DENY_PATTERNS)


@pytest.mark.parametrize(
    "path",
    [
        "src/core.py",
        "README.md",
        "docs/environment.md",
        "src/monkey.py",
        "src/keys.py",
        "src/identity.py",
        "pkg/secret_sauce.py",
        "src/env.py",
        "src/id_generator.py",
        "id_utils/helpers.py",
        "src/id_map/core.py",
        "src/credentials_loader.py",
        "src/config/credentials_schema.json",
        "credentials/store.py",
        "auth/credentials_test_data/fixture.py",
    ],
)
def test_read_deny_patterns_leave_ordinary_sources_alone(path: str) -> None:
    """
    GIVEN an ordinary source path whose name only resembles a secret file,
          including modules and whole directories named id_* or credentials*
    WHEN matched against READ_DENY_PATTERNS
    THEN no pattern covers it ('*' crosses '/' in fnmatch, so a name pattern
         with a trailing '*' would deny a whole subtree of hot code)
    """
    assert not _any(path, READ_DENY_PATTERNS)


def test_pattern_constants_are_tuples_of_strings() -> None:
    """
    GIVEN the three shared pattern constants
    WHEN their types are inspected
    THEN each is an immutable tuple of non-empty strings without duplicates
    """
    for constant in (GIT_METADATA_NAMES, WRITE_DENY_PATTERNS, READ_DENY_PATTERNS):
        assert isinstance(constant, tuple)
        assert all(isinstance(item, str) and item for item in constant)
        assert len(set(constant)) == len(constant)
