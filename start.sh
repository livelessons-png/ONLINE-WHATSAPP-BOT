#!/usr/bin/env bash
set -e

echo "============================================="
echo "  MIVA WhatsApp Bot — Render Start Script"
echo "============================================="

# ── Start the reminder daemon in background ──
echo "[LOG] Starting Reminder Daemon..."
python WAHA_REMINDERV2.py &
REMINDER_PID=$!
echo "[LOG] Reminder Daemon PID: $REMINDER_PID"

# ── Start the unified web server (Gunicorn) ──
# Runs the unified main.py which serves WAHA_INTERACT + DASHBOARD routes
echo "[LOG] Starting Gunicorn web server on 0.0.0.0:${PORT:-5000}..."
exec gunicorn main:app \
    --bind "0.0.0.0:${PORT:-5000}" \
    --workers 1 \
    --threads 4 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile - \
    --log-level info
