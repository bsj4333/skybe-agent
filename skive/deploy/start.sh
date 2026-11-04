#!/bin/sh
# One container runs the web server and the extraction worker.
# The worker restarts on crash so uploads keep being read.
(
  while true; do
    python -m skive.drive_worker
    echo "drive worker exited, restarting in 5s" >&2
    sleep 5
  done
) &

exec uvicorn skive.server:app --host 0.0.0.0 --port "${PORT:-8000}"
