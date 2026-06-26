.PHONY: help setup up down logs redis api worker frontend

help:
	@echo "EqualView local development"
	@echo ""
	@echo "Docker (recommended):"
	@echo "  make up        Start backend (API + Worker + Redis)"
	@echo "  make down      Stop backend containers"
	@echo "  make logs      Follow api/worker logs"
	@echo ""
	@echo "Local venv (alternative):"
	@echo "  make setup     Install deps (venv, npm, Redis only)"
	@echo "  make redis     Start Redis container only"
	@echo "  make api       Start FastAPI (port 8000)"
	@echo "  make worker    Start Celery worker on host"
	@echo "  make frontend  Start Vite dev server (port 5173)"
	@echo ""
	@echo "Full UI: make up + make frontend"

up:
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f api worker

setup:
	@./scripts/setup.sh

redis:
	docker compose up -d redis

api:
	cd backend && ./venv/bin/uvicorn api.main:app --reload --host 127.0.0.1 --port 8000

worker:
	cd backend && ./run_worker.sh

frontend:
	cd frontend && npm run dev
