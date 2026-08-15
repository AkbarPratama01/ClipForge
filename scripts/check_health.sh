#!/usr/bin/env bash
# Quick health check against a running ClipForge stack.
# Usage: ./scripts/check_health.sh [base_url]
set -euo pipefail

BASE_URL="${1:-http://localhost}"

echo "==> GET $BASE_URL/api/health"
curl -fsS -w "\n(HTTP %{http_code})\n" "$BASE_URL/api/health"
