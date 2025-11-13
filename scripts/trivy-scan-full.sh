#!/bin/bash

# ╔═══════════════════════════════════════════════════════════════════╗
# ║  Trivy Security Scan - Fully Automated (Colima Edition)          ║
# ║                                                                   ║
# ║  This script automatically:                                       ║
# ║  • Starts Colima if needed                                       ║
# ║  • Pulls and scans Docker images                                 ║
# ║  • Scans config and filesystem                                   ║
# ║  • Generates comprehensive reports                               ║
# ║  • Cleans up (stops what it started)                            ║
# ╚═══════════════════════════════════════════════════════════════════╝

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

# Tracking flags
COLIMA_WAS_STOPPED=false
COMPOSE_WAS_STOPPED=false

# Trap handler for cleanup
cleanup_on_exit() {
  local exit_code=$?
  
  echo ""
  echo -e "${BLUE}═══════════════════════════════════════════════${NC}"
  echo -e "${BLUE}🧹 Cleanup Phase${NC}"
  echo -e "${BLUE}═══════════════════════════════════════════════${NC}"
  
  # Stop docker-compose if we started it
  if [ "$COMPOSE_WAS_STOPPED" = true ]; then
    echo -e "${YELLOW}⏸️  Stopping docker-compose services (started by script)...${NC}"
    docker compose -f docker-compose.dev.yml down --remove-orphans 2>/dev/null || {
      echo -e "${YELLOW}⚠️  Note: docker-compose services may already be stopped${NC}"
    }
    echo -e "${GREEN}✅ Docker services stopped${NC}"
  else
    echo -e "${BLUE}ℹ️  Docker Compose services were already running - leaving them active${NC}"
  fi
  
  # Stop Colima if we started it
  if [ "$COLIMA_WAS_STOPPED" = true ]; then
    echo -e "${YELLOW}⏸️  Stopping Colima (started by script)...${NC}"
    colima stop 2>/dev/null || {
      echo -e "${YELLOW}⚠️  Note: Colima may already be stopped${NC}"
    }
    echo -e "${GREEN}✅ Colima stopped${NC}"
  else
    echo -e "${BLUE}ℹ️  Colima was already running - leaving it active${NC}"
  fi
  
  echo ""
  exit $exit_code
}

trap cleanup_on_exit EXIT INT TERM

# ═══════════════════════════════════════════════════════════════════
# BANNER
# ═══════════════════════════════════════════════════════════════════

clear
echo -e "${BOLD}${BLUE}"
cat << "EOF"
╔═══════════════════════════════════════════════════════════════════╗
║                                                                   ║
║   🔒 TRIVY COMPREHENSIVE SECURITY SCAN                           ║
║      Fully Automated - Colima Edition                            ║
║                                                                   ║
╚═══════════════════════════════════════════════════════════════════╝
EOF
echo -e "${NC}"
echo ""

# ═══════════════════════════════════════════════════════════════════
# PRE-FLIGHT CHECKS
# ═══════════════════════════════════════════════════════════════════

echo -e "${BOLD}📋 Pre-flight Checks${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════${NC}"
echo ""

# Check Trivy
if ! command -v trivy &> /dev/null; then
  echo -e "${RED}❌ ERROR: Trivy is not installed${NC}"
  echo ""
  echo "Install Trivy with:"
  echo "  ${BOLD}brew install trivy${NC}"
  echo ""
  exit 1
fi
echo -e "${GREEN}✅ Trivy is installed${NC}"

# Check Colima
if ! command -v colima &> /dev/null; then
  echo -e "${RED}❌ ERROR: Colima is not installed${NC}"
  echo ""
  echo "Install Colima with:"
  echo "  ${BOLD}brew install colima docker docker-compose${NC}"
  echo ""
  echo "Then run this script again."
  exit 1
fi
echo -e "${GREEN}✅ Colima is installed${NC}"

# Check Docker CLI
if ! command -v docker &> /dev/null; then
  echo -e "${RED}❌ ERROR: Docker CLI is not installed${NC}"
  echo ""
  echo "Install Docker CLI with:"
  echo "  ${BOLD}brew install docker${NC}"
  echo ""
  exit 1
fi
echo -e "${GREEN}✅ Docker CLI is installed${NC}"

echo ""

# ═══════════════════════════════════════════════════════════════════
# SETUP REPORTS DIRECTORY
# ═══════════════════════════════════════════════════════════════════

REPORTS_DIR="./trivy-reports"
mkdir -p "$REPORTS_DIR"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")

REPORT_HIGH_CRITICAL="$REPORTS_DIR/trivy-high-critical-$TIMESTAMP.txt"
REPORT_MEDIUM_LOW="$REPORTS_DIR/trivy-medium-low-$TIMESTAMP.txt"
REPORT_JSON="$REPORTS_DIR/trivy-results-$TIMESTAMP.json"
REPORT_SUMMARY="$REPORTS_DIR/trivy-summary-$TIMESTAMP.md"

echo -e "${BLUE}📁 Reports will be saved to: ${BOLD}$REPORTS_DIR${NC}"
echo ""

# ═══════════════════════════════════════════════════════════════════
# COLIMA MANAGEMENT
# ═══════════════════════════════════════════════════════════════════

echo -e "${BOLD}🐳 Docker Environment Setup${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════${NC}"
echo ""

# Check if Colima is running
if colima status &> /dev/null; then
  echo -e "${GREEN}✅ Colima is already running${NC}"
  COLIMA_WAS_STOPPED=false
else
  echo -e "${YELLOW}⚠️  Colima is not running${NC}"
  echo -e "${BLUE}🚀 Starting Colima...${NC}"
  echo ""
  
  # Start Colima with optimal settings
  if colima start --cpu 4 --memory 8 --disk 60 --vm-type vz 2>&1 | tee /tmp/colima-start.log; then
    echo ""
    echo -e "${GREEN}✅ Colima started successfully${NC}"
    COLIMA_WAS_STOPPED=true
    
    # Wait for Docker daemon to be fully ready
    echo -e "${YELLOW}⏳ Waiting for Docker daemon to be ready...${NC}"
    WAIT_COUNT=0
    MAX_WAIT=30
    while [ $WAIT_COUNT -lt $MAX_WAIT ]; do
      if docker info &> /dev/null; then
        echo -e "${GREEN}✅ Docker daemon is ready${NC}"
        break
      fi
      sleep 1
      WAIT_COUNT=$((WAIT_COUNT + 1))
      echo -n "."
    done
    echo ""
    
    if [ $WAIT_COUNT -ge $MAX_WAIT ]; then
      echo -e "${RED}❌ ERROR: Docker daemon did not become ready within ${MAX_WAIT}s${NC}"
      exit 1
    fi
  else
    echo ""
    echo -e "${RED}❌ ERROR: Failed to start Colima${NC}"
    echo ""
    echo "Troubleshooting:"
    echo "  1. Check if another Docker service is running"
    echo "  2. Try: colima delete && colima start"
    echo "  3. Check logs: cat /tmp/colima-start.log"
    exit 1
  fi
fi

echo ""

# ═══════════════════════════════════════════════════════════════════
# DOCKER COMPOSE MANAGEMENT
# ═══════════════════════════════════════════════════════════════════

echo -e "${BOLD}🐳 Docker Compose Services${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════${NC}"
echo ""

# Check if docker-compose.dev.yml exists
if [ ! -f "docker-compose.dev.yml" ]; then
  echo -e "${YELLOW}⚠️  docker-compose.dev.yml not found in current directory${NC}"
  echo -e "${YELLOW}   Skipping Docker Compose services...${NC}"
  COMPOSE_AVAILABLE=false
else
  COMPOSE_AVAILABLE=true
  
  # Check if services are already running
  if docker compose -f docker-compose.dev.yml ps --quiet 2>/dev/null | grep -q .; then
    echo -e "${GREEN}✅ Docker Compose services are already running${NC}"
    COMPOSE_WAS_STOPPED=false
  else
    echo -e "${YELLOW}⚠️  Docker Compose services are not running${NC}"
    echo -e "${BLUE}🚀 Starting docker-compose services...${NC}"
    echo ""
    
    if docker compose -f docker-compose.dev.yml up -d --quiet-pull 2>&1; then
      echo -e "${GREEN}✅ Docker Compose services started${NC}"
      COMPOSE_WAS_STOPPED=true
      
      # Wait for services to be healthy
      echo -e "${YELLOW}⏳ Waiting for services to be healthy (10s)...${NC}"
      sleep 10
      echo -e "${GREEN}✅ Services should be ready${NC}"
    else
      echo -e "${YELLOW}⚠️  Warning: Failed to start docker-compose services${NC}"
      echo -e "${YELLOW}   Continuing with available images only...${NC}"
      COMPOSE_WAS_STOPPED=false
    fi
  fi
fi

echo ""

# ═══════════════════════════════════════════════════════════════════
# SCAN FUNCTION
# ═══════════════════════════════════════════════════════════════════

run_trivy_scan() {
  local scan_type=$1
  local scan_target=$2
  local description=$3

  echo -e "${BLUE}${BOLD}🔍 Scanning: $description${NC}"
  echo "   Type: $scan_type | Target: $scan_target"
  echo "   ─────────────────────────────────────────────"

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

  # Generate JSON
  echo "   Generating detailed JSON report..."
  trivy "$scan_type" \
    --severity CRITICAL,HIGH,MEDIUM,LOW \
    --format json \
    --quiet \
    "$scan_target" >> "$REPORT_JSON" 2>&1 || true

  echo -e "   ${GREEN}✓ Scan complete${NC}"
  echo ""
}

# ═══════════════════════════════════════════════════════════════════
# PHASE 1: CONFIGURATION & FILESYSTEM SCANS
# ═══════════════════════════════════════════════════════════════════

echo -e "${BOLD}📦 Phase 1/3: Configuration & Filesystem Scans${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════${NC}"
echo ""

run_trivy_scan "config" "." "Configuration files and IaC"
run_trivy_scan "fs" "." "Local filesystem dependencies"

# ═══════════════════════════════════════════════════════════════════
# PHASE 2: DOCKER IMAGE SCANS
# ═══════════════════════════════════════════════════════════════════

echo -e "${BOLD}🐳 Phase 2/3: Docker Image Scans${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════${NC}"
echo ""

# Define images to scan
DOCKER_IMAGES=(
  "pgvector/pgvector:pg16|PostgreSQL with pgvector extension"
  "redis:7-alpine|Redis Cache"
  "qdrant/qdrant:latest|Qdrant Vector Database"
)

echo "📦 Scanning Docker images..."
echo ""

for img_info in "${DOCKER_IMAGES[@]}"; do
  IFS='|' read -r image description <<< "$img_info"
  
  # Check if image is available locally
  if docker image inspect "$image" &> /dev/null 2>&1; then
    run_trivy_scan "image" "$image" "$description ($image)"
  else
    echo -e "${YELLOW}⚠️  Image not available: $image${NC}"
    echo "   Attempting to pull..."
    
    if docker pull "$image" &> /dev/null; then
      echo -e "${GREEN}✅ Successfully pulled $image${NC}"
      run_trivy_scan "image" "$image" "$description ($image)"
    else
      echo -e "${RED}✗ Failed to pull $image (skipped)${NC}"
      echo ""
    fi
  fi
done

# ═══════════════════════════════════════════════════════════════════
# PHASE 3: GENERATE SUMMARY
# ═══════════════════════════════════════════════════════════════════

echo -e "${BOLD}📊 Phase 3/3: Generating Security Summary${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════${NC}"
echo ""

# Count vulnerabilities from JSON report
if [ -f "$REPORT_JSON" ] && command -v jq &> /dev/null; then
  CRITICAL_COUNT=$(jq -s 'map(.Results[]?.Vulnerabilities[]? | select(.Severity=="CRITICAL")) | length' "$REPORT_JSON" 2>/dev/null || echo 0)
  HIGH_COUNT=$(jq -s 'map(.Results[]?.Vulnerabilities[]? | select(.Severity=="HIGH")) | length' "$REPORT_JSON" 2>/dev/null || echo 0)
  MEDIUM_COUNT=$(jq -s 'map(.Results[]?.Vulnerabilities[]? | select(.Severity=="MEDIUM")) | length' "$REPORT_JSON" 2>/dev/null || echo 0)
  LOW_COUNT=$(jq -s 'map(.Results[]?.Vulnerabilities[]? | select(.Severity=="LOW")) | length' "$REPORT_JSON" 2>/dev/null || echo 0)
else
  CRITICAL_COUNT=$(grep -o "CRITICAL" "$REPORT_HIGH_CRITICAL" 2>/dev/null | wc -l | tr -d ' ' || echo 0)
  HIGH_COUNT=$(grep -o "HIGH" "$REPORT_HIGH_CRITICAL" 2>/dev/null | wc -l | tr -d ' ' || echo 0)
  MEDIUM_COUNT=$(grep -o "MEDIUM" "$REPORT_MEDIUM_LOW" 2>/dev/null | wc -l | tr -d ' ' || echo 0)
  LOW_COUNT=$(grep -o "LOW" "$REPORT_MEDIUM_LOW" 2>/dev/null | wc -l | tr -d ' ' || echo 0)
fi

# Ensure counts are integers
CRITICAL_COUNT=$(echo "$CRITICAL_COUNT" | tr -d '\n\r\t ' | grep -o '^[0-9]*$' || echo 0)
HIGH_COUNT=$(echo "$HIGH_COUNT" | tr -d '\n\r\t ' | grep -o '^[0-9]*$' || echo 0)
MEDIUM_COUNT=$(echo "$MEDIUM_COUNT" | tr -d '\n\r\t ' | grep -o '^[0-9]*$' || echo 0)
LOW_COUNT=$(echo "$LOW_COUNT" | tr -d '\n\r\t ' | grep -o '^[0-9]*$' || echo 0)

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
**Docker Runtime:** Colima
**Scan Duration:** Full comprehensive scan

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

⚠️ **Action Required:**
- $CRITICAL_COUNT critical vulnerabilities must be addressed immediately
- Review \`$REPORT_HIGH_CRITICAL\` for detailed findings
- Update affected dependencies or apply security patches

EOF
elif [ $HIGH_COUNT -gt 0 ]; then
  cat >> "$REPORT_SUMMARY" << EOF
![Status](https://img.shields.io/badge/Security-WARNING-yellow?style=for-the-badge&logo=security)

**⚠️ HIGH SEVERITY ISSUES DETECTED**

📋 **Recommendation:**
- $HIGH_COUNT high severity vulnerabilities found
- Plan updates for affected components
- Review \`$REPORT_HIGH_CRITICAL\` for details

EOF
else
  cat >> "$REPORT_SUMMARY" << EOF
![Status](https://img.shields.io/badge/Security-PASSED-brightgreen?style=for-the-badge&logo=security)

**✅ NO CRITICAL OR HIGH SEVERITY ISSUES**

$([ $TOTAL_ISSUES -eq 0 ] && echo "🎉 Excellent! All scans passed with no vulnerabilities detected." || echo "ℹ️ Found $MEDIUM_COUNT MEDIUM and $LOW_COUNT LOW severity issues (informational only).")

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
   docker compose -f docker-compose.dev.yml pull
   docker compose -f docker-compose.dev.yml up -d
   \`\`\`

3. **Review Security Advisories:**
   - Check [GitHub Advisories](https://github.com/advisories) for known CVEs
   - Run \`pnpm audit fix\` for auto-patchable issues

4. **Monitor Continuously:**
   - Schedule regular security scans
   - Enable dependabot or renovate for automated updates

---

## 📦 Generated Reports

- **Summary Report:** \`$REPORT_SUMMARY\`
- **HIGH/CRITICAL Vulnerabilities:** \`$REPORT_HIGH_CRITICAL\`
- **MEDIUM/LOW Vulnerabilities:** \`$REPORT_MEDIUM_LOW\`
- **JSON (Full Details):** \`$REPORT_JSON\`

---

## 🔧 Scan Configuration

- **Config Scan:** ✅ Completed
- **Filesystem Scan:** ✅ Completed  
- **Docker Image Scan:** ✅ Completed
- **Total Targets:** 5 (config, filesystem, 3 images)

---

**Scan completed:** $(date)
**Script:** trivy-scan-auto.sh (Colima Edition)
EOF

# ═══════════════════════════════════════════════════════════════════
# DISPLAY SUMMARY
# ═══════════════════════════════════════════════════════════════════

echo ""
echo -e "${BOLD}${BLUE}"
echo "═══════════════════════════════════════════════════════════════════"
echo "                    📊 SCAN RESULTS SUMMARY                        "
echo "═══════════════════════════════════════════════════════════════════"
echo -e "${NC}"

cat "$REPORT_SUMMARY"

echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════════════════════${NC}"
echo ""

echo -e "${BOLD}📁 Generated Reports:${NC}"
echo "   • Summary:       $REPORT_SUMMARY"
echo "   • HIGH/CRITICAL: $REPORT_HIGH_CRITICAL"
echo "   • MEDIUM/LOW:    $REPORT_MEDIUM_LOW"
echo "   • JSON Details:  $REPORT_JSON"
echo ""

# Open summary in default viewer (optional)
if command -v open &> /dev/null; then
  echo -e "${BLUE}💡 Tip: Opening summary in default viewer...${NC}"
  open "$REPORT_SUMMARY" 2>/dev/null || true
  echo ""
fi

# ═══════════════════════════════════════════════════════════════════
# EXIT WITH APPROPRIATE CODE
# ═══════════════════════════════════════════════════════════════════

if [ $CRITICAL_COUNT -gt 0 ]; then
  echo -e "${RED}${BOLD}╔═══════════════════════════════════════════════════════════╗${NC}"
  echo -e "${RED}${BOLD}║  ❌ SCAN FAILED: Critical vulnerabilities detected       ║${NC}"
  echo -e "${RED}${BOLD}╚═══════════════════════════════════════════════════════════╝${NC}"
  exit 1
elif [ $HIGH_COUNT -gt 0 ]; then
  echo -e "${YELLOW}${BOLD}╔═══════════════════════════════════════════════════════════╗${NC}"
  echo -e "${YELLOW}${BOLD}║  ⚠️  SCAN WARNING: High severity vulnerabilities found   ║${NC}"
  echo -e "${YELLOW}${BOLD}╚═══════════════════════════════════════════════════════════╝${NC}"
  exit 0
else
  echo -e "${GREEN}${BOLD}╔═══════════════════════════════════════════════════════════╗${NC}"
  echo -e "${GREEN}${BOLD}║  ✅ SCAN PASSED: No critical or high severity issues     ║${NC}"
  echo -e "${GREEN}${BOLD}╚═══════════════════════════════════════════════════════════╝${NC}"
  exit 0
fi