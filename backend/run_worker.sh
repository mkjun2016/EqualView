#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
export PYTHONPATH="$(pwd)"

source venv/bin/activate
exec celery -A celery_app worker --loglevel=info --concurrency="${CELERY_WORKER_CONCURRENCY:-2}"
