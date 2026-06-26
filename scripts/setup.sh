#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

require_cmd() {
	if ! command -v "$1" >/dev/null 2>&1; then
		echo "Error: required command not found: $1" >&2
		exit 1
	fi
}

echo "==> Checking prerequisites..."
require_cmd python3
require_cmd node
require_cmd npm
require_cmd docker

echo "==> Starting Redis (for local venv dev)..."
cd "$ROOT"
docker compose up -d redis

echo "==> Setting up backend..."
cd "$ROOT/backend"

if [[ ! -d venv ]]; then
	python3 -m venv venv
	echo "Created backend/venv"
fi

# shellcheck disable=SC1091
source venv/bin/activate
python -m pip install -q --upgrade pip
pip install -r requirements.txt

if [[ ! -f .env ]]; then
	cp .env.example .env
	echo "Created backend/.env from .env.example"
fi

echo "==> Setting up frontend..."
cd "$ROOT/frontend"
npm install

cat <<EOF

Setup complete.

Start each service in a separate terminal (from project root):

  make api       # http://localhost:8000  (Swagger: /docs)
  make worker    # Celery worker
  make frontend  # http://localhost:5173

First Whisper run downloads the model (~150MB). Requires network once.

EOF
