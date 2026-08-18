#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
[ -f .venv/bin/activate ] || { echo "Run ./scripts/setup.sh first"; exit 1; }
. .venv/bin/activate
[ -f .env ] || { echo ".env missing"; exit 1; }
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
