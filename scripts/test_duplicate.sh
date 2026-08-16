#!/usr/bin/env bash
# Duplicate-detection test (§67): re-import the same URL, expect status=duplicate.
set -euo pipefail
BASE="http://localhost:8080"

echo "=== re-import same video ==="
curl -sS -X POST "$BASE/api/videos/import" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://www.youtube.com/watch?v=jNQXAC9IVRw","upload_to_drive":false}'
echo
echo "=== waiting 50s for worker duplicate check ==="
sleep 50
echo "=== videos list ==="
curl -sS "$BASE/api/videos"
echo
echo "=== worker duplicate log ==="
docker compose logs clipforge-worker 2>&1 | grep -E 'duplicate_detected|job_completed' | tail -4
