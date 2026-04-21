#!/usr/bin/env bash
# ============================================================================
# kill_system.sh — Stop the full RosTaurant system
#
# Stops in reverse order:
#   1) Dashboard (PyQt5 admin GUI)
#   2) Monitor (matplotlib visualization)
#   3) Control + Web servers
#   4) Pinky robots (driver + Nav2) — optional
#
# Usage:
#   ./kill_system.sh              # stop local processes (robots keep running)
#   ./kill_system.sh --robots     # stop everything including robots
#   ./kill_system.sh --all        # same as --robots
# ============================================================================

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER_DIR="${SCRIPT_DIR}/server"
DEMO_DIR="${SERVER_DIR}/Test/global_path_planning_demo"
RUN_DIR="${SCRIPT_DIR}/.run"

# Load .env if present
if [[ -f "${SCRIPT_DIR}/.env" ]]; then
    set -a; source "${SCRIPT_DIR}/.env"; set +a
fi

PINKY1_IP="${PINKY1_IP:?PINKY1_IP is not set. Define it in .env or export it.}"
PINKY2_IP="${PINKY2_IP:?PINKY2_IP is not set. Define it in .env or export it.}"

KILL_ROBOTS=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --robots|--all) KILL_ROBOTS=true; shift ;;
        -h|--help)
            cat <<EOF
usage: $(basename "$0") [--robots | --all]

  --robots/--all  Also stop pinky robots via SSH
  (default)       Stop only local processes (servers + monitor + dashboard)
EOF
            exit 0 ;;
        *) echo "unknown flag: $1" >&2; exit 2 ;;
    esac
done

echo "[kill] Stopping RosTaurant system..."

# ── 1) Dashboard (PyQt5 admin GUI) ────────────────────────────────
# PyQt's exec_() ignores SIGINT, so go SIGTERM → SIGKILL quickly.
DASHBOARD_PID_FILE="${RUN_DIR}/dashboard.pid"
if [[ -f "${DASHBOARD_PID_FILE}" ]]; then
    pid="$(cat "${DASHBOARD_PID_FILE}")"
    if kill -0 "${pid}" 2>/dev/null; then
        echo "[kill] Stopping dashboard (PID ${pid})..."
        kill -TERM "${pid}" 2>/dev/null || true
        for _ in 1 2 3; do
            kill -0 "${pid}" 2>/dev/null || break
            sleep 0.5
        done
        kill -0 "${pid}" 2>/dev/null && kill -KILL "${pid}" 2>/dev/null || true
    fi
    rm -f "${DASHBOARD_PID_FILE}"
fi
# Sweep any leftover dashboard processes — match by cwd or script path,
# since cmdline is just "python3 main.py" once the shell cd's into admin_ui.
for p in $(pgrep -f "python3 main.py" 2>/dev/null); do
    cwd=$(readlink "/proc/$p/cwd" 2>/dev/null || true)
    case "$cwd" in
        */ui/desktop/admin_ui*) kill -KILL "$p" 2>/dev/null || true ;;
    esac
done

# ── 2) ROS2 Bridge ─────────────────────────────────────────────────
BRIDGE_PID_FILE="${RUN_DIR}/bridge.pid"
if [[ -f "${BRIDGE_PID_FILE}" ]]; then
    pid="$(cat "${BRIDGE_PID_FILE}")"
    if kill -0 "${pid}" 2>/dev/null; then
        echo "[kill] Stopping ROS2 bridge (PID ${pid})..."
        kill -INT "${pid}" 2>/dev/null || true
        sleep 1
        kill -0 "${pid}" 2>/dev/null && kill -TERM "${pid}" 2>/dev/null || true
    fi
    rm -f "${BRIDGE_PID_FILE}"
fi
pkill -f "ros2_bridge.py" 2>/dev/null || true

# ── 3) Monitor ─────────────────────────────────────────────────────
MONITOR_PID_FILE="${RUN_DIR}/monitor.pid"
if [[ -f "${MONITOR_PID_FILE}" ]]; then
    pid="$(cat "${MONITOR_PID_FILE}")"
    if kill -0 "${pid}" 2>/dev/null; then
        echo "[kill] Stopping monitor (PID ${pid})..."
        kill -INT "${pid}" 2>/dev/null || true
        sleep 1
        kill -0 "${pid}" 2>/dev/null && kill -TERM "${pid}" 2>/dev/null || true
    fi
    rm -f "${MONITOR_PID_FILE}"
fi
pkill -f "python3.*monitor.py.*--domain-ids" 2>/dev/null || true

# ── 4) Demo stack (if running via demo start.sh) ──────────────────
if [[ -f "${DEMO_DIR}/kill.sh" ]]; then
    (cd "${DEMO_DIR}" && bash kill.sh 2>/dev/null) || true
fi

# ── 5) Control + Web servers ──────────────────────────────────────
SERVERS_PID_FILE="${RUN_DIR}/servers.pid"
if [[ -f "${SERVERS_PID_FILE}" ]]; then
    pid="$(cat "${SERVERS_PID_FILE}")"
    if kill -0 "${pid}" 2>/dev/null; then
        echo "[kill] Stopping servers (PID ${pid})..."
        kill -INT "${pid}" 2>/dev/null || true
        sleep 2
        kill -0 "${pid}" 2>/dev/null && kill -TERM "${pid}" 2>/dev/null || true
    fi
    rm -f "${SERVERS_PID_FILE}"
fi

# Sweep server processes
for pat in "uvicorn main:app" "python3 -m uvicorn"; do
    pkill -f "${pat}" 2>/dev/null || true
done

# ── 6) Pinky robots (optional) ────────────────────────────────────
if [[ "${KILL_ROBOTS}" == "true" ]]; then
    echo "[kill] Stopping pinky robots..."
    for ip in "${PINKY1_IP}" "${PINKY2_IP}"; do
        if ssh -o ConnectTimeout=3 -o BatchMode=yes "pinky@${ip}" "true" 2>/dev/null; then
            echo "[kill] Stopping robot at ${ip}..."
            ssh "pinky@${ip}" "bash ~/kill_pinky.sh" 2>/dev/null || true
        else
            echo "[kill] ${ip} not reachable — skipping"
        fi
    done
fi

# Clean up pid files
rm -f "${RUN_DIR}"/pinky*_ssh.pid

echo "[kill] Done."
