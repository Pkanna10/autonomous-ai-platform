#!/bin/bash

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

cd "$ROOT"
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
run_check "ruff check" must bash -c "cd '$PY_DIR' && uv run ruff check ."
run_check "ruff format" must bash -c "cd '$PY_DIR' && uv run ruff format --check ."
run_check "mypy" must bash -c "cd '$PY_DIR' && uv run mypy src"
run_check "pytest (coverage >= 90%)" must bash -c "cd '$PY_DIR' && uv run pytest"

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
