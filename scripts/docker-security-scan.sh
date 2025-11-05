#!/bin/bash

# Docker Image Security Scanning Script
# Scans all Docker images used in docker-compose.dev.yml

set -e

echo "🐳 Docker Image Security Scan"
echo "================================"
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if Trivy is installed
if ! command -v trivy &> /dev/null; then
  echo -e "${RED}Error: Trivy is not installed${NC}"
  echo "Install with: brew install trivy (macOS) or see https://aquasecurity.github.io/trivy/"
  exit 1
fi

# Docker images to scan (from docker-compose.dev.yml)
IMAGES=(
  "pgvector/pgvector:pg15"
  "redis:7-alpine"
  "qdrant/qdrant:latest"
)

TOTAL_CRITICAL=0
TOTAL_HIGH=0
TOTAL_MEDIUM=0
TOTAL_LOW=0

# Scan each image
for IMAGE in "${IMAGES[@]}"; do
  echo "📦 Scanning: $IMAGE"
  echo "--------------------------------"

  # Pull image if not present
  if ! docker image inspect "$IMAGE" &> /dev/null; then
    echo "Pulling $IMAGE..."
    docker pull "$IMAGE"
  fi

  # Run Trivy scan
  SCAN_OUTPUT=$(trivy image --quiet --format json "$IMAGE")

  # Parse results
  CRITICAL=$(echo "$SCAN_OUTPUT" | jq '[.Results[]?.Vulnerabilities[]? | select(.Severity=="CRITICAL")] | length')
  HIGH=$(echo "$SCAN_OUTPUT" | jq '[.Results[]?.Vulnerabilities[]? | select(.Severity=="HIGH")] | length')
  MEDIUM=$(echo "$SCAN_OUTPUT" | jq '[.Results[]?.Vulnerabilities[]? | select(.Severity=="MEDIUM")] | length')
  LOW=$(echo "$SCAN_OUTPUT" | jq '[.Results[]?.Vulnerabilities[]? | select(.Severity=="LOW")] | length')

  # Update totals
  TOTAL_CRITICAL=$((TOTAL_CRITICAL + CRITICAL))
  TOTAL_HIGH=$((TOTAL_HIGH + HIGH))
  TOTAL_MEDIUM=$((TOTAL_MEDIUM + MEDIUM))
  TOTAL_LOW=$((TOTAL_LOW + LOW))

  # Display results
  echo "Results:"
  echo "  🔴 Critical: $CRITICAL"
  echo "  🟠 High: $HIGH"
  echo "  🟡 Medium: $MEDIUM"
  echo "  🟢 Low: $LOW"

  # Show detailed report for critical/high
  if [ "$CRITICAL" -gt 0 ] || [ "$HIGH" -gt 0 ]; then
    echo ""
    echo "Detailed vulnerabilities:"
    trivy image --severity CRITICAL,HIGH --no-progress "$IMAGE" | head -50
  fi

  echo ""
done

# Summary
echo "================================"
echo "📊 Overall Summary"
echo "================================"
echo "Total vulnerabilities across all images:"
echo "  🔴 Critical: $TOTAL_CRITICAL"
echo "  🟠 High: $TOTAL_HIGH"
echo "  🟡 Medium: $TOTAL_MEDIUM"
echo "  🟢 Low: $TOTAL_LOW"
echo ""

# Exit with error if critical or high vulnerabilities found
if [ "$TOTAL_CRITICAL" -gt 0 ]; then
  echo -e "${RED}❌ CRITICAL vulnerabilities found!${NC}"
  echo "Action required: Update Docker images or apply patches"
  exit 1
elif [ "$TOTAL_HIGH" -gt 0 ]; then
  echo -e "${YELLOW}⚠️  HIGH severity vulnerabilities found${NC}"
  echo "Recommendation: Update Docker images soon"
  exit 0
else
  echo -e "${GREEN}✅ No critical or high severity vulnerabilities found${NC}"
  exit 0
fi
