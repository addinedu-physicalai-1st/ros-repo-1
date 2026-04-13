#!/bin/bash
# start.sh — Launch control server, web server, and admin dashboard together.
#
# Usage:
#   cd /path/to/ros-repo-1/server
#   ADMIN_API_KEY=<key> ./start.sh
#
# Ports (override with env vars):
#   Control server : MRTA_PORT   (default 8000)   TCP 9000  UDP 9001
#   Web server     : WEB_PORT    (default 3000)
#
# Set ADMIN_API_KEY to the api_key of an ADMIN user (printed by the control
# server on first startup, or stored in MRTA_ADMIN_KEY_OUT file).
# CONTROL_SERVICE_KEY is used by the web server WS relay; set it to the same key.
#
# Dashboard (PyQt5) auto-launch:
#   Requires a graphical session (DISPLAY must be set).
#   Disable with: NO_DASHBOARD=1 ./start.sh
#   The dashboard uses DASHBOARD_PYTHON if set, otherwise the first of
#   /usr/bin/python3, /bin/python3 that can `import PyQt5`, else `python3`.
#   (server/.venv often has no PyQt5 — do not rely on venv for the GUI.)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Pick a Python interpreter that has PyQt5 (avoid server venv without GUI deps).
_dashboard_python() {
  if [ -n "${DASHBOARD_PYTHON:-}" ] && [ -x "${DASHBOARD_PYTHON}" ]; then
    printf '%s' "${DASHBOARD_PYTHON}"
    return 0
  fi
  for _py in /usr/bin/python3 /bin/python3; do
    [ -x "${_py}" ] || continue
    if "${_py}" -c "from PyQt5.QtWidgets import QApplication; import requests" 2>/dev/null; then
      printf '%s' "${_py}"
      return 0
    fi
  done
  command -v python3
}

# Auto-activate venv if found (server/.venv, server/control/.venv, or system python)
_activate_venv() {
  for candidate in \
      "${SCRIPT_DIR}/.venv/bin/activate" \
      "${SCRIPT_DIR}/control/.venv/bin/activate"; do
    if [ -f "${candidate}" ]; then
      # shellcheck source=/dev/null
      source "${candidate}"
      echo "[start.sh] Using venv: ${candidate}"
      return 0
    fi
  done
  echo "[start.sh] No .venv found, using system Python."
}
_activate_venv

MRTA_PORT="${MRTA_PORT:-8000}"
WEB_PORT="${WEB_PORT:-3000}"

export CONTROL_BASE_URL="${CONTROL_BASE_URL:-http://localhost:${MRTA_PORT}}"
export CONTROL_WS_URL="${CONTROL_WS_URL:-ws://localhost:${MRTA_PORT}/ws/stream}"
# If CONTROL_SERVICE_KEY not set separately, share ADMIN_API_KEY
export CONTROL_SERVICE_KEY="${CONTROL_SERVICE_KEY:-${ADMIN_API_KEY:-}}"

echo "[start.sh] Starting control server on port ${MRTA_PORT}..."
(
  cd "${SCRIPT_DIR}/control"
  exec python3 -m uvicorn main:app \
    --host 0.0.0.0 \
    --port "${MRTA_PORT}" \
    --log-level info \
    --no-access-log
) &
CTRL_PID=$!

# Brief pause to let control server bind its ports before web server connects
sleep 1

echo "[start.sh] Starting web server on port ${WEB_PORT}..."
(
  cd "${SCRIPT_DIR}/web"
  exec python3 -m uvicorn main:app \
    --host 0.0.0.0 \
    --port "${WEB_PORT}" \
    --log-level info \
    --no-access-log
) &
WEB_PID=$!

# ── Admin dashboard (PyQt5) ─────────────────────────────────────────────────
PYQT_PID=""
DASHBOARD_DIR="${REPO_ROOT}/ui/desktop/admin_ui"

if [ "${NO_DASHBOARD:-0}" = "1" ]; then
  echo "[start.sh] Dashboard launch skipped (NO_DASHBOARD=1)."
elif [ -z "${DISPLAY:-}" ] && [ -z "${WAYLAND_DISPLAY:-}" ]; then
  echo "[start.sh] WARNING: No display found (DISPLAY/WAYLAND_DISPLAY not set)."
  echo "[start.sh] Dashboard will not be launched. Set DISPLAY=:0 to enable."
elif [ ! -f "${DASHBOARD_DIR}/main.py" ]; then
  echo "[start.sh] WARNING: Dashboard not found at ${DASHBOARD_DIR}/main.py — skipping."
else
  echo "[start.sh] Waiting for control server to become healthy..."
  _tries=0
  until curl -sf "http://localhost:${MRTA_PORT}/health" >/dev/null 2>&1; do
    _tries=$(( _tries + 1 ))
    if [ "${_tries}" -ge 15 ]; then
      echo "[start.sh] Control server did not respond in time — skipping dashboard."
      break
    fi
    sleep 1
  done

  if curl -sf "http://localhost:${MRTA_PORT}/health" >/dev/null 2>&1; then
    DASH_PY="$(_dashboard_python)"
    if ! "${DASH_PY}" -c "from PyQt5.QtWidgets import QApplication" 2>/dev/null; then
      echo "[start.sh] ERROR: PyQt5 not available for '${DASH_PY}'."
      echo "[start.sh] Install: sudo apt install python3-pyqt5   or   pip install PyQt5 requests"
      echo "[start.sh] Or set DASHBOARD_PYTHON=/path/to/python3 that has PyQt5."
    elif ! "${DASH_PY}" -c "import requests" 2>/dev/null; then
      echo "[start.sh] ERROR: requests not available for '${DASH_PY}' (dashboard needs it)."
      echo "[start.sh] Install: pip install requests   (for that same Python)"
    else
      echo "[start.sh] Launching admin dashboard with: ${DASH_PY}"
      (
        cd "${DASHBOARD_DIR}"
        DISPLAY="${DISPLAY:-:0}" \
        CONTROL_BASE_URL="${CONTROL_BASE_URL}" \
        ADMIN_API_KEY="${ADMIN_API_KEY:-}" \
          exec "${DASH_PY}" main.py
      ) &
      PYQT_PID=$!
      echo "[start.sh] Dashboard PID: ${PYQT_PID}"
    fi
  fi
fi
# ────────────────────────────────────────────────────────────────────────────

echo "[start.sh] All processes running."
echo "[start.sh]   control  PID=${CTRL_PID}  → http://localhost:${MRTA_PORT}"
echo "[start.sh]   web      PID=${WEB_PID}   → http://localhost:${WEB_PORT}"
[ -n "${PYQT_PID}" ] && echo "[start.sh]   dashboard PID=${PYQT_PID}"
echo "[start.sh] Press Ctrl-C to stop all."

cleanup() {
  echo ""
  echo "[start.sh] Stopping all processes..."
  kill "${CTRL_PID}" "${WEB_PID}" ${PYQT_PID} 2>/dev/null || true
  wait "${CTRL_PID}" "${WEB_PID}" ${PYQT_PID} 2>/dev/null || true
  echo "[start.sh] Done."
}
trap cleanup INT TERM

wait
