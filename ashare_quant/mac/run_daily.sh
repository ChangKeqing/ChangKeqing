#!/bin/bash
# One daily step. Called by launchd; safe to run by hand.
set -u
DIR="$(cd "$(dirname "$0")/.." && pwd)"   # .../ashare_quant
cd "$DIR/.."
mkdir -p "$DIR/logs"
LABEL="com.ashare-quant.daily"
{
  echo "=== $(date '+%Y-%m-%d %H:%M:%S') ==="
  set -a; [ -f "$DIR/.env" ] && . "$DIR/.env"; set +a
  "$DIR/.venv/bin/python" -m ashare_quant.run "$@"
  echo "exit=$?"
} >> "$DIR/logs/run.log" 2>&1

# API credit used up: stop the schedule for good.
if [ -f "$DIR/state/HALTED" ]; then
  launchctl bootout "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || true
fi
