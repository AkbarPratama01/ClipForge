#!/usr/bin/env bash
# Create .env from .env.example if it does not exist yet.
set -euo pipefail

if [[ -f .env ]]; then
  echo "==> .env already exists — leaving it untouched."
  exit 0
fi

cp .env.example .env
echo "==> Created .env from .env.example."
echo "    Edit the MySQL passwords before running: docker compose up -d"
