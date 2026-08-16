#!/usr/bin/env bash
# Phase 5 acceptance test: long video -> download -> transcribe -> analyze -> 5 candidates.
set -euo pipefail
BASE="http://localhost:8080"
URL="https://www.youtube.com/watch?v=dQw4w9WgXcQ"   # Rick Astley, 3:33 — long enough for 5 windows

echo "=== import long video ==="
curl -sS -X POST "$BASE/api/videos/import" -H "Content-Type: application/json" \
  -d "{\"url\":\"$URL\",\"upload_to_drive\":false}"
echo
sleep 40
echo "=== videos after download ==="
curl -sS "$BASE/api/videos" | grep -o '"status":"[^"]*"' | head -5

VIDEO_ID=$(curl -sS "$BASE/api/videos" | grep -o '"id":[0-9]*' | head -1 | cut -d: -f2)
echo "=== transcribe video $VIDEO_ID ==="
curl -sS -X POST "$BASE/api/videos/$VIDEO_ID/transcribe"
echo
echo "waiting 120s for transcription..."
sleep 120
echo "=== analyze video $VIDEO_ID ==="
curl -sS -X POST "$BASE/api/videos/$VIDEO_ID/analyze"
echo
sleep 15
echo "=== candidates ==="
curl -sS "$BASE/api/videos/$VIDEO_ID/candidates" > /tmp/cands.json
head -c 1600 /tmp/cands.json
echo
echo "candidate count: $(grep -o '"id":' /tmp/cands.json | wc -l)"
