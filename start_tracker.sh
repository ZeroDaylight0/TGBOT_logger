#!/usr/bin/env sh
# Linux / macOS launcher: creates a virtual environment on first run, then starts the tracker.
set -eu
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/python -m pip install --quiet -r requirements.txt
fi

exec .venv/bin/python -m uvicorn app.main:app \
  --host "${TG_TRACKER_HOST:-127.0.0.1}" --port "${TG_TRACKER_PORT:-8000}"
