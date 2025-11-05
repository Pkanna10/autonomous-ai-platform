#!/bin/bash

# Comprehensive Trivy Security Scan with Enhanced Summary
# Mimics the GitHub Actions CI workflow for local execution

set -e

# Docker auto-start flag (initialized early for trap handler)
AUTO_START=false

# Trap handler to ensure Docker cleanup on unexpected exit
trap 'cleanup_docker_on_exit' EXIT INT TERM

cleanup_docker_on_exit() {
  # Only cleanup if AUTO_START was set to true
  if [ "$AUTO_START" = true ]; then
    echo ""
    echo "🧹 Cleaning up: Stopping docker-compose services..."
    docker compose -f docker-compose.dev.yml down --remove-orphans 2>/dev/null || true
    echo "🧹 Cleaning up: Stopping Docker daemon..."
    osascript -e 'quit app "Docker"' 2>/dev/null || true
  fi
}

echo "🔒 Trivy Comprehensive Security Scan"
echo "===================================="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# Check if Trivy is installed
if ! command -v trivy &> /dev/null; then
  echo -e "${RED}Error: Trivy is not installed${NC}"
  echo "Install with:"
  echo "  macOS: brew install trivy"
  echo "  Linux: See https://aquasecurity.github.io/trivy/latest/getting-started/installation/"
  exit 1
fi

# Create reports directory
REPORTS_DIR="./trivy-reports"
mkdir -p "$REPORTS_DIR"

# Timestamp for reports
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")

# Report files
REPORT_HIGH_CRITICAL="$REPORTS_DIR/trivy-high-critical-$TIMESTAMP.txt"
REPORT_MEDIUM_LOW="$REPORTS_DIR/trivy-medium-low-$TIMESTAMP.txt"
REPORT_JSON="$REPORTS_DIR/trivy-results-$TIMESTAMP.json"
REPORT_SUMMARY="$REPORTS_DIR/trivy-summary-$TIMESTAMP.md"

echo "📁 Reports will be saved to: $REPORTS_DIR"
echo ""

# Function to scan and generate reports
run_trivy_scan() {
  local scan_type=$1
  local scan_target=$2
  local description=$3

  echo -e "${BLUE}${BOLD}🔍 Scanning: $description${NC}"
  echo "   Type: $scan_type | Target: $scan_target"
  echo "   ----------------------------------------"

  # Scan for HIGH/CRITICAL
  echo "   Checking HIGH/CRITICAL severity..."
  trivy "$scan_type" \
    --severity CRITICAL,HIGH \
    --format table \
    --quiet \
    "$scan_target" >> "$REPORT_HIGH_CRITICAL" 2>&1 || true

  # Scan for MEDIUM/LOW
  echo "   Checking MEDIUM/LOW severity..."
  trivy "$scan_type" \
    --severity MEDIUM,LOW \
    --format table \
    --quiet \
    "$scan_target" >> "$REPORT_MEDIUM_LOW" 2>&1 || true

  # Generate JSON for detailed analysis
  echo "   Generating detailed JSON report..."
  trivy "$scan_type" \
    --severity CRITICAL,HIGH,MEDIUM,LOW \
    --format json \
    --quiet \
    "$scan_target" >> "$REPORT_JSON" 2>&1 || true

  echo -e "   ${GREEN}✓ Scan complete${NC}"
  echo ""
}

# Function to wait for Docker to be ready
wait_for_docker_ready() {
  local timeout=60  # 60 seconds max
  local elapsed=0

  echo "⏳ Waiting for Docker to be ready..."

  while [ $elapsed -lt $timeout ]; do
    if docker ps &> /dev/null 2>&1; then
      echo -e "${GREEN}✅ Docker is ready (took ${elapsed}s)${NC}"
      return 0
    fi
    sleep 2
    elapsed=$((elapsed + 2))
    echo -n "."
  done

  echo ""
  echo -e "${RED}❌ Docker failed to start within ${timeout}s${NC}"
  return 1
}

# Function to cleanup and exit
cleanup_and_exit() {
  local exit_code=$1

  # Stop Docker services and daemon if we auto-started them
  if [ "$AUTO_START" = true ]; then
    echo ""
    echo -e "${BLUE}🧹 Stopping docker-compose services...${NC}"
    docker compose -f docker-compose.dev.yml down --remove-orphans 2>/dev/null || {
      echo -e "${YELLOW}⚠️  Warning: Failed to stop docker-compose services (non-fatal)${NC}"
    }
    echo -e "${GREEN}✅ Docker services stopped${NC}"

    echo -e "${BLUE}🧹 Stopping Docker daemon (was auto-started for scan)...${NC}"
    osascript -e 'quit app "Docker"' 2>/dev/null || {
      echo -e "${YELLOW}⚠️  Warning: Failed to stop Docker daemon (non-fatal)${NC}"
    }
    echo -e "${GREEN}✅ Docker daemon stopped${NC}"

    # Prevent trap from trying to stop again
    AUTO_START=false
  fi

  exit $exit_code
}

# 1. Scan filesystem/config
echo -e "${BOLD}Step 1/4: Scanning Configuration Files${NC}"
echo ""
run_trivy_scan "config" "." "Configuration files and IaC"

# Check Docker status before Step 2
echo -e "${BOLD}🐳 Checking Docker Status${NC}"
echo ""

DOCKER_WAS_STOPPED=false

if ! docker ps &> /dev/null 2>&1; then
  echo -e "${YELLOW}⚠️  Docker daemon is not running${NC}"
  echo "🚀 Starting Docker daemon..."
  DOCKER_WAS_STOPPED=true

  # On macOS, we need to start Docker Desktop to get the daemon
  # Using --hide to minimize disruption
  open -a Docker --hide || {
    echo -e "${RED}❌ ERROR: Failed to start Docker daemon${NC}"
    echo "Please ensure Docker Desktop is installed on your system."
    cleanup_and_exit 1
  }

  # Wait for Docker daemon to be ready
  if ! wait_for_docker_ready; then
    echo -e "${RED}❌ ERROR: Docker daemon failed to start within timeout${NC}"
    cleanup_and_exit 1
  fi

  echo -e "${GREEN}✅ Docker daemon started successfully${NC}"
  echo ""
fi

# Start docker-compose services if Docker was stopped
if [ "$DOCKER_WAS_STOPPED" = true ]; then
  echo "🚀 Starting docker-compose services..."

  # Start services in detached mode
  if docker compose -f docker-compose.dev.yml up -d --quiet-pull 2>&1; then
    echo -e "${GREEN}✅ Docker services started successfully${NC}"
    # Only set AUTO_START after successful service startup
    AUTO_START=true
    echo ""
  else
    echo -e "${RED}❌ ERROR: Failed to start docker-compose services${NC}"
    cleanup_and_exit 1
  fi
else
  echo -e "${GREEN}✅ Docker daemon is already running${NC}"
  AUTO_START=false
  echo ""
fi

# 2. Scan Docker images from docker-compose
echo -e "${BOLD}Step 2/4: Scanning Docker Images${NC}"
echo ""

DOCKER_IMAGES=(
  "pgvector/pgvector:pg15|PostgreSQL with pgvector"
  "redis:7-alpine|Redis Cache"
  "qdrant/qdrant:latest|Qdrant Vector DB"
)

for img_info in "${DOCKER_IMAGES[@]}"; do
  IFS='|' read -r image description <<< "$img_info"

  # Pull image if not present
  if ! docker image inspect "$image" &> /dev/null 2>&1; then
    echo "   Pulling $image..."
    docker pull "$image" > /dev/null 2>&1
  fi

  run_trivy_scan "image" "$image" "$description ($image)"
done

# 3. Scan filesystem for vulnerabilities
echo -e "${BOLD}Step 3/4: Scanning Filesystem${NC}"
echo ""
run_trivy_scan "fs" "." "Local filesystem dependencies"

# 4. Generate Enhanced Security Summary
echo -e "${BOLD}Step 4/4: Generating Enhanced Security Summary${NC}"
echo ""

# Count vulnerabilities from JSON report
if [ -f "$REPORT_JSON" ] && command -v jq &> /dev/null; then
  # Use -s (slurp) to read all JSON objects as array, then count across all
  CRITICAL_COUNT=$(jq -s 'map(.Results[]?.Vulnerabilities[]? | select(.Severity=="CRITICAL")) | length' "$REPORT_JSON" 2>/dev/null || echo 0)
  HIGH_COUNT=$(jq -s 'map(.Results[]?.Vulnerabilities[]? | select(.Severity=="HIGH")) | length' "$REPORT_JSON" 2>/dev/null || echo 0)
  MEDIUM_COUNT=$(jq -s 'map(.Results[]?.Vulnerabilities[]? | select(.Severity=="MEDIUM")) | length' "$REPORT_JSON" 2>/dev/null || echo 0)
  LOW_COUNT=$(jq -s 'map(.Results[]?.Vulnerabilities[]? | select(.Severity=="LOW")) | length' "$REPORT_JSON" 2>/dev/null || echo 0)
else
  # Fallback: count unique vulnerabilities from text files using proper parsing
  CRITICAL_COUNT=$(grep -o "CRITICAL" "$REPORT_HIGH_CRITICAL" 2>/dev/null | wc -l | tr -d ' ' || echo 0)
  HIGH_COUNT=$(grep -o "HIGH" "$REPORT_HIGH_CRITICAL" 2>/dev/null | wc -l | tr -d ' ' || echo 0)
  MEDIUM_COUNT=$(grep -o "MEDIUM" "$REPORT_MEDIUM_LOW" 2>/dev/null | wc -l | tr -d ' ' || echo 0)
  LOW_COUNT=$(grep -o "LOW" "$REPORT_MEDIUM_LOW" 2>/dev/null | wc -l | tr -d ' ' || echo 0)
fi

# Ensure counts are single integers (remove any whitespace/newlines)
CRITICAL_COUNT=$(echo "$CRITICAL_COUNT" | tr -d '\n\r\t ' | grep -o '^[0-9]*$' || echo 0)
HIGH_COUNT=$(echo "$HIGH_COUNT" | tr -d '\n\r\t ' | grep -o '^[0-9]*$' || echo 0)
MEDIUM_COUNT=$(echo "$MEDIUM_COUNT" | tr -d '\n\r\t ' | grep -o '^[0-9]*$' || echo 0)
LOW_COUNT=$(echo "$LOW_COUNT" | tr -d '\n\r\t ' | grep -o '^[0-9]*$' || echo 0)

# Set to 0 if empty
CRITICAL_COUNT=${CRITICAL_COUNT:-0}
HIGH_COUNT=${HIGH_COUNT:-0}
MEDIUM_COUNT=${MEDIUM_COUNT:-0}
LOW_COUNT=${LOW_COUNT:-0}

TOTAL_ISSUES=$((CRITICAL_COUNT + HIGH_COUNT + MEDIUM_COUNT + LOW_COUNT))

# Generate Markdown summary
cat > "$REPORT_SUMMARY" << EOF
# 🔒 Trivy Security Scan Report

**Scan Date:** $(date -u '+%Y-%m-%d %H:%M:%S UTC')
**Repository:** autonomous-ai-platform
**Scan Type:** Comprehensive (Config + Docker + Filesystem)

---

## 📊 Vulnerability Summary

| Severity | Count | Status |
|----------|-------|--------|
| 🔴 CRITICAL | $CRITICAL_COUNT | $([ $CRITICAL_COUNT -eq 0 ] && echo "✅ PASS" || echo "❌ FAIL") |
| 🟠 HIGH | $HIGH_COUNT | $([ $HIGH_COUNT -eq 0 ] && echo "✅ PASS" || echo "⚠️ WARNING") |
| 🟡 MEDIUM | $MEDIUM_COUNT | $([ $MEDIUM_COUNT -eq 0 ] && echo "✅ PASS" || echo "ℹ️ INFO") |
| 🟢 LOW | $LOW_COUNT | ℹ️ INFO |
| **Total** | **$TOTAL_ISSUES** | |

---

## 🎯 Overall Status

EOF

# Determine overall status
if [ $CRITICAL_COUNT -gt 0 ]; then
  cat >> "$REPORT_SUMMARY" << EOF
![Status](https://img.shields.io/badge/Security-FAILED-red?style=for-the-badge&logo=security)

**🚨 CRITICAL ISSUES DETECTED**

Action Required:
- $CRITICAL_COUNT critical vulnerabilities must be fixed immediately
- Review \`$REPORT_HIGH_CRITICAL\` for details
- Update affected dependencies or apply patches

EOF
elif [ $HIGH_COUNT -gt 0 ]; then
  cat >> "$REPORT_SUMMARY" << EOF
![Status](https://img.shields.io/badge/Security-WARNING-yellow?style=for-the-badge&logo=security)

**⚠️ HIGH SEVERITY ISSUES DETECTED**

Recommendation:
- $HIGH_COUNT high severity vulnerabilities found
- Plan updates for affected components
- Review \`$REPORT_HIGH_CRITICAL\` for details

EOF
else
  cat >> "$REPORT_SUMMARY" << EOF
![Status](https://img.shields.io/badge/Security-PASSED-brightgreen?style=for-the-badge&logo=security)

**✅ NO CRITICAL OR HIGH SEVERITY ISSUES**

$([ $TOTAL_ISSUES -eq 0 ] && echo "🎉 All scans passed! No vulnerabilities detected." || echo "ℹ️ $MEDIUM_COUNT MEDIUM and $LOW_COUNT LOW severity issues detected (informational only).")

EOF
fi

# Add detailed sections if issues found
if [ $CRITICAL_COUNT -gt 0 ] || [ $HIGH_COUNT -gt 0 ]; then
  cat >> "$REPORT_SUMMARY" << EOF
---

## 🔍 Detailed Findings

### CRITICAL/HIGH Severity Issues

See full details in: \`$REPORT_HIGH_CRITICAL\`

**Top 10 Issues:**

\`\`\`
$(head -50 "$REPORT_HIGH_CRITICAL")
\`\`\`

EOF
fi

if [ $MEDIUM_COUNT -gt 0 ] || [ $LOW_COUNT -gt 0 ]; then
  cat >> "$REPORT_SUMMARY" << EOF
---

### MEDIUM/LOW Severity Issues (Informational)

See full details in: \`$REPORT_MEDIUM_LOW\`

EOF
fi

# Add recommendations
cat >> "$REPORT_SUMMARY" << EOF
---

## 💡 Recommendations

1. **Update Dependencies:**
   \`\`\`bash
   pnpm update --latest
   \`\`\`

2. **Update Docker Images:**
   \`\`\`bash
   docker-compose -f docker-compose.dev.yml pull
   \`\`\`

3. **Review Snyk/GitHub Security Advisories:**
   - Check https://github.com/advisories for known CVEs
   - Run \`pnpm audit fix\` for auto-patchable issues

4. **Enable Automated Updates:**
   - Renovate bot is configured to auto-update dependencies weekly
   - Review and merge Renovate PRs promptly

---

## 📦 Generated Reports

- **HIGH/CRITICAL:** \`$REPORT_HIGH_CRITICAL\`
- **MEDIUM/LOW:** \`$REPORT_MEDIUM_LOW\`
- **JSON (Full):** \`$REPORT_JSON\`
- **Summary:** \`$REPORT_SUMMARY\`

---

**Scan completed:** $(date)
EOF

# Display summary to console
echo "===================================="
echo ""
cat "$REPORT_SUMMARY"
echo ""
echo "===================================="
echo ""
echo -e "${BOLD}📁 Reports saved to:${NC}"
echo "   - Summary: $REPORT_SUMMARY"
echo "   - HIGH/CRITICAL: $REPORT_HIGH_CRITICAL"
echo "   - MEDIUM/LOW: $REPORT_MEDIUM_LOW"
echo "   - JSON: $REPORT_JSON"
echo ""

# Open summary in browser/viewer (optional)
if command -v open &> /dev/null; then
  echo "💡 Tip: Opening summary in default viewer..."
  open "$REPORT_SUMMARY" 2>/dev/null || true
fi

# Exit with appropriate code (with Docker cleanup)
if [ $CRITICAL_COUNT -gt 0 ]; then
  echo -e "${RED}${BOLD}❌ SCAN FAILED: Critical vulnerabilities detected${NC}"
  cleanup_and_exit 1
elif [ $HIGH_COUNT -gt 0 ]; then
  echo -e "${YELLOW}${BOLD}⚠️  SCAN WARNING: High severity vulnerabilities detected${NC}"
  cleanup_and_exit 0
else
  echo -e "${GREEN}${BOLD}✅ SCAN PASSED: No critical or high severity issues${NC}"
  cleanup_and_exit 0
fi
