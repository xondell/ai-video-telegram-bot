#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

command -v python3 >/dev/null || { echo "Python 3 required"; exit 1; }
python3 - <<'PY'
import sys
assert sys.version_info >= (3,11), "Python 3.11+ required"
PY

python3 -m venv .venv
. .venv/bin/activate
python -m pip install -U pip
python -m pip install -e '.[dev]'

mkdir -p data/temp data/output
[ -f .env ] || cp .env.example .env

echo "Dependencies installed."
echo "For Vercel production, use ./deploy_all.sh (it configures exactly five secrets)."
echo "For local development, fill .env and run ./start.sh."
python -m pytest -q
