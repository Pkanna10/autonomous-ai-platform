#!/bin/bash
# The probe functions run through run_check "$@" (in this shell, so their
# exports reach the later checks); shellcheck cannot see that call.
# shellcheck disable=SC2329

# Stage gate: run at the end of every development step, before a PR is marked
# ready for review. It keeps the repository on current, audited dependencies and
# verifies that the step's code passes every quality check.
#
#   pnpm stage-gate            # full gate (fails on any red check)
#   pnpm stage-gate --quick    # skip the slower audit/outdated checks
#
# Sections:
#   1. Outdated dependencies (report only; upgrades are decided per step)
#   2. Security audits (pnpm audit, pip-audit, bandit) - must pass
#   3. Quality (typecheck, lint, tests, coverage) - must pass
#
# The Python checks match the CI "python" job: the dev and database extras,
# mypy on src and tests, pytest with -m "not live", the Postgres tests when a
# database answers (TEST_DATABASE_URL, else the docker-compose.dev.yml one),
# and the profiler shim tests on every python3.8-3.12 found (uv-managed ones
# included). Missing pieces are warnings here: the tests they need skip, so
# coverage can come out lower than CI's. CI itself fails instead.
#
# The result is recorded in STATUS.md "Development log" for the step.

set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY_DIR="$ROOT/services/python_agents"
QUICK=0
[[ "${1:-}" == "--quick" ]] && QUICK=1

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

FAILURES=0
WARNINGS=0

pass() { echo -e "${GREEN}PASS${NC} $1"; }
warn() { echo -e "${YELLOW}WARN${NC} $1"; WARNINGS=$((WARNINGS + 1)); }
fail() { echo -e "${RED}FAIL${NC} $1"; FAILURES=$((FAILURES + 1)); }

run_check() {
  # run_check <label> <mode:must|warn> <command...>
  local label="$1" mode="$2"; shift 2
  echo ""
  echo "---- $label"
  if "$@"; then
    pass "$label"
  elif [[ "$mode" == "warn" ]]; then
    warn "$label"
  else
    fail "$label"
  fi
}

# docker-compose.dev.yml's database; used only when TEST_DATABASE_URL is unset.
COMPOSE_DATABASE_URL="postgresql://dev:devpass@localhost:5432/ai_platform"
WORKLOAD_PYTHONS="3.8 3.9 3.10 3.11 3.12"

use_test_database() {
  # Export TEST_DATABASE_URL when a database answers; never print the URL.
  if [[ -n "${TEST_DATABASE_URL:-}" ]]; then
    echo "TEST_DATABASE_URL is set: the Postgres tests run against it"
    return 0
  fi
  if (cd "$PY_DIR" && PROBE_URL="$COMPOSE_DATABASE_URL" uv run python -c \
    'import os, psycopg; psycopg.connect(os.environ["PROBE_URL"], connect_timeout=3).close()') \
    >/dev/null 2>&1; then
    export TEST_DATABASE_URL="$COMPOSE_DATABASE_URL"
    echo "Postgres answers at localhost:5432/ai_platform: the Postgres tests run"
    return 0
  fi
  echo "No Postgres at localhost:5432/ai_platform and TEST_DATABASE_URL is unset:"
  echo "the Postgres tests SKIP. Start it: docker compose -f docker-compose.dev.yml up -d postgres"
  return 1
}

use_workload_pythons() {
  # Append uv's managed interpreters (after the system ones), then report gaps.
  local bin_dir version missing=""
  bin_dir="$(cd "$PY_DIR" && uv python dir --bin 2>/dev/null)" || bin_dir=""
  if [[ -n "$bin_dir" && -d "$bin_dir" && ":$PATH:" != *":$bin_dir:"* ]]; then
    export PATH="$PATH:$bin_dir"
  fi
  for version in $WORKLOAD_PYTHONS; do
    command -v "python$version" >/dev/null 2>&1 || missing="$missing $version"
  done
  if [[ -n "$missing" ]]; then
    echo "Not on PATH:$missing (their profiler shim tests skip). Install: uv python install$missing"
    return 1
  fi
  echo "python${WORKLOAD_PYTHONS// /, python}: on PATH"
}

sandbox_available() {
  # The host sandbox the engine uses; without it the sandbox tests skip.
  case "$(uname -s)" in
    Linux)
      command -v unshare >/dev/null 2>&1 || { echo "unshare is not installed"; return 1; }
      (cd "$PY_DIR" && uv run python -c '
import subprocess
from autonomous_ai_agents.execution import launcher
from autonomous_ai_agents.execution.sandbox import UNSHARE_ARGV
subprocess.run([*UNSHARE_ARGV, "true"], check=True, capture_output=True, timeout=30)
print("unshare ok, Landlock ABI", launcher.default_ops().syscall(444, (None, 0, 1)))')
      ;;
    Darwin) /usr/bin/sandbox-exec -p '(version 1) (allow default)' /usr/bin/true ;;
    *) echo "no engine sandbox on $(uname -s)"; return 1 ;;
  esac
}

cd "$ROOT" || exit 1
echo "Stage gate: $(date -u +%Y-%m-%dT%H:%M:%SZ)  (quick=$QUICK)"

# ---------------------------------------------------------------------------
# 1. Outdated dependencies (report only)
# ---------------------------------------------------------------------------
if [[ $QUICK -eq 0 ]]; then
  echo ""
  echo "==== 1. Outdated dependencies (review and upgrade as part of the step)"
  run_check "pnpm outdated" warn bash -c 'pnpm outdated -r; [[ $? -eq 0 ]]'
  run_check "uv outdated" warn bash -c "cd '$PY_DIR' && uv tree --outdated --depth 1 2>/dev/null | grep -q 'latest' && exit 1 || exit 0"
fi

# ---------------------------------------------------------------------------
# 2. Security audits (must pass)
# ---------------------------------------------------------------------------
if [[ $QUICK -eq 0 ]]; then
  echo ""
  echo "==== 2. Security audits"
  run_check "pnpm audit (moderate+)" must pnpm audit --audit-level=moderate
  run_check "pip-audit" must bash -c "cd '$PY_DIR' && uv run pip-audit --progress-spinner off"
  run_check "bandit" must bash -c "cd '$PY_DIR' && uv run bandit -q -r src -c pyproject.toml"
  run_check "secret grep" must bash -c "! git grep -nE 'sk-ant-api03-[A-Za-z0-9_-]{20,}' -- ':!*.example' ':!*.md'"
fi

# ---------------------------------------------------------------------------
# 3. Quality (must pass)
# ---------------------------------------------------------------------------
echo ""
echo "==== 3. Quality"
run_check "pnpm typecheck" must pnpm typecheck
run_check "pnpm lint" must pnpm lint
run_check "pnpm format:check" must pnpm format:check
run_check "pnpm test (coverage)" must pnpm test:coverage
# --inexact keeps other extras a developer installed; CI syncs a fresh venv.
run_check "uv sync (dev + database extras)" must bash -c "cd '$PY_DIR' && uv sync --frozen --inexact --extra dev --extra database"
run_check "Postgres for the repository tests" warn use_test_database
run_check "workload interpreters (python3.8-3.12)" warn use_workload_pythons
run_check "engine sandbox (unshare + Landlock / sandbox-exec)" warn sandbox_available
run_check "ruff check" must bash -c "cd '$PY_DIR' && uv run ruff check ."
run_check "ruff format" must bash -c "cd '$PY_DIR' && uv run ruff format --check ."
run_check "mypy" must bash -c "cd '$PY_DIR' && uv run mypy src tests"
run_check "pytest -m 'not live' (coverage >= 90%)" must bash -c "cd '$PY_DIR' && uv run pytest -m 'not live'"

# ---------------------------------------------------------------------------
echo ""
echo "============================================"
if [[ $FAILURES -eq 0 ]]; then
  echo -e "${GREEN}Stage gate passed${NC} ($WARNINGS warning(s))"
  echo "Record the result in STATUS.md > Development log before opening the PR."
  exit 0
else
  echo -e "${RED}Stage gate failed${NC}: $FAILURES failing check(s), $WARNINGS warning(s)"
  exit 1
fi
