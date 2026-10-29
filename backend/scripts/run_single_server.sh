#!/usr/bin/env bash
# ==============================================================================
# Single-Server Runner for Meeting Intelligence Summarizer
# Supervised concurrent execution of FastAPI Web server and Celery background worker
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ROOT_DIR="$(cd "${BACKEND_DIR}/.." && pwd)"

cd "${BACKEND_DIR}"

VENV_BIN="${BACKEND_DIR}/.venv/bin"
if [[ ! -d "${VENV_BIN}" ]]; then
    if [[ -d "${ROOT_DIR}/.venv/bin" ]]; then
        VENV_BIN="${ROOT_DIR}/.venv/bin"
    else
        echo "Virtual environment not detected. Using system python."
        VENV_BIN=""
    fi
fi

PYTHON_CMD="${VENV_BIN:+$VENV_BIN/}python"
UVICORN_CMD="${VENV_BIN:+$VENV_BIN/}uvicorn"
CELERY_CMD="${VENV_BIN:+$VENV_BIN/}celery"

echo "======================================================================"
echo " Starting Meeting Intelligence Summarizer (Single-Server Mode)        "
echo " Web UI & REST API + Background Worker                                "
echo "======================================================================"

trap 'echo "Terminating services..."; kill $(jobs -p) 2>/dev/null || true; exit 0' SIGINT SIGTERM EXIT

# 1. Start Celery worker in background
echo "[1/2] Starting Celery worker with FFmpeg media processing..."
${CELERY_CMD} -A app.core.celery_app worker --loglevel=INFO --concurrency=2 --prefetch-multiplier=1 -O fair &
WORKER_PID=$!

# 2. Start FastAPI Web application
echo "[2/2] Starting FastAPI Web & REST Server on http://0.0.0.0:8000..."
${UVICORN_CMD} app.main:app --host 0.0.0.0 --port 8000 &
WEB_PID=$!

wait ${WEB_PID} ${WORKER_PID}

