#!/usr/bin/env bash
# Health check for the WoW Achievement Optimizer stack.
#
# Exits 0 when all services healthy, 1 on any failure.

set -uo pipefail

PASS=0
FAIL=0

check() {
    local name="$1"
    local url="$2"
    local expected="$3"

    response=$(curl -sf -o /dev/null -w "%{http_code}" "${url}" 2>/dev/null || echo "000")
    if [ "${response}" = "${expected}" ]; then
        echo "✓ ${name} (${response})"
        PASS=$((PASS + 1))
    else
        echo "✗ ${name} (expected ${expected}, got ${response})"
        FAIL=$((FAIL + 1))
    fi
}

echo "=== WoW Achievement Optimizer Health Check ==="
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo ""

check "Nginx (root)"             "http://localhost/"           200
check "Backend API /health"      "http://localhost/api/health" 200
check "Frontend"                 "http://localhost/"           200
check "Flower Dashboard"         "http://localhost/flower/"    200

echo ""
echo "=== Docker Services ==="
docker-compose ps --format "table {{.Name}}\t{{.Status}}" 2>/dev/null || echo "docker-compose not available"

echo ""
echo "=== Summary ==="
echo "Passed: ${PASS} | Failed: ${FAIL}"

if [ "${FAIL}" -gt 0 ]; then
    exit 1
fi
