#!/bin/bash

# Security Scanning Script for Local Development
# Run this before pushing code to catch security issues early

set -e

echo "🔒 Running Security Scans..."
echo "================================"
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Track failures
FAILURES=0

# 1. npm audit
echo "📦 Step 1/4: Running pnpm audit..."
if pnpm audit --audit-level=moderate; then
  echo -e "${GREEN}✓ pnpm audit passed${NC}"
else
  echo -e "${RED}✗ pnpm audit found vulnerabilities${NC}"
  FAILURES=$((FAILURES + 1))
fi
echo ""

# 2. OSV-Scanner (Google's vulnerability database)
# The scanner is a Go binary; install a release from
# https://github.com/google/osv-scanner/releases (or `brew install osv-scanner`).
# Never `npx -y <name>`: there is no @google/osv-scanner on npm, and a
# fetch-and-run of an unknown package name is exactly how typosquats execute.
echo "🔍 Step 2/4: Running OSV-Scanner..."
if command -v osv-scanner &> /dev/null; then
  if osv-scanner scan source --recursive .; then
    echo -e "${GREEN}✓ OSV-Scanner found no vulnerabilities${NC}"
  else
    EXIT_CODE=$?
    if [ $EXIT_CODE -eq 1 ]; then
      echo -e "${RED}✗ OSV-Scanner found vulnerabilities${NC}"
      FAILURES=$((FAILURES + 1))
    else
      echo -e "${YELLOW}⚠ OSV-Scanner completed with warnings (exit ${EXIT_CODE})${NC}"
    fi
  fi
else
  echo -e "${YELLOW}⚠ osv-scanner not installed (see the comment above); CI runs it on every push${NC}"
fi
echo ""

# 3. Trivy filesystem scan
echo "🐳 Step 3/4: Running Trivy filesystem scan..."
if command -v trivy &> /dev/null; then
  if trivy fs --severity HIGH,CRITICAL --exit-code 1 .; then
    echo -e "${GREEN}✓ Trivy scan passed${NC}"
  else
    echo -e "${RED}✗ Trivy found vulnerabilities${NC}"
    FAILURES=$((FAILURES + 1))
  fi
else
  echo -e "${YELLOW}⚠ Trivy not installed (install: brew install trivy)${NC}"
fi
echo ""

# 4. Check for secrets in code
echo "🔑 Step 4/4: Scanning for secrets..."
if command -v gitleaks &> /dev/null; then
  if gitleaks detect --no-git; then
    echo -e "${GREEN}✓ No secrets detected${NC}"
  else
    echo -e "${RED}✗ Potential secrets found in code${NC}"
    FAILURES=$((FAILURES + 1))
  fi
else
  echo -e "${YELLOW}⚠ gitleaks not installed (install: brew install gitleaks)${NC}"
fi
echo ""

# Summary
echo "================================"
if [ $FAILURES -eq 0 ]; then
  echo -e "${GREEN}🎉 All security scans passed!${NC}"
  exit 0
else
  echo -e "${RED}❌ $FAILURES security check(s) failed${NC}"
  echo "Please fix the issues above before committing."
  exit 1
fi