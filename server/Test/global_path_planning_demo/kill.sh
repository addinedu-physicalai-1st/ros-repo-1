#!/usr/bin/env bash
# Stop the demo stack started by start.sh.
# Kills process groups recorded in .run/*.pid plus any leftover
# ros2/gz processes spawned under them.

set -u

DEMO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_DIR="${DEMO_DIR}/.run"

stop_group() {
    local name="$1"
    local pidf="${RUN_DIR}/${name}.pid"
    [[ -f "${pidf}" ]] || { echo "[kill] ${name}: no pidfile"; return 0; }

    local pid
    pid="$(cat "${pidf}")"
    if ! kill -0 "${pid}" 2>/dev/null; then
        echo "[kill] ${name}: pid ${pid} not running"
        rm -f "${pidf}"
        return 0
    fi

    echo "[kill] ${name}: sending SIGINT to pgid ${pid}"
    kill -INT "-${pid}" 2>/dev/null || kill -INT "${pid}" 2>/dev/null || true

    for _ in $(seq 1 10); do
        kill -0 "${pid}" 2>/dev/null || break
        sleep 0.5
    done

    if kill -0 "${pid}" 2>/dev/null; then
        echo "[kill] ${name}: escalating to SIGTERM"
        kill -TERM "-${pid}" 2>/dev/null || kill -TERM "${pid}" 2>/dev/null || true
        sleep 2
    fi
    if kill -0 "${pid}" 2>/dev/null; then
        echo "[kill] ${name}: escalating to SIGKILL"
        kill -KILL "-${pid}" 2>/dev/null || kill -KILL "${pid}" 2>/dev/null || true
    fi

    rm -f "${pidf}"
}

MODE_FILE="${RUN_DIR}/mode"
MODE="$(cat "${MODE_FILE}" 2>/dev/null || echo unknown)"
echo "[kill] mode=${MODE}"

stop_group monitor
if [[ "${MODE}" != "real" ]]; then
    # In real mode Nav2 runs on the pinky, not on this machine.
    stop_group nav2
    stop_group gazebo
fi

# Sweep stragglers that ros2 launch likes to leave behind.
# In real mode we only clean up laptop-local processes.
SWEEP_PATTERNS=(
    "monitor.py"
    "nav2_bridge.py"
    "multi_robot_controller.py"
)
if [[ "${MODE}" != "real" ]]; then
    SWEEP_PATTERNS+=(
        "ros2 launch pinky_navigation"
        "nav2_"
        "ros2 launch pinky_gz_sim"
        "gz sim"
        "gz-sim-server"
        "ruby.*gz"
    )
fi

for pat in "${SWEEP_PATTERNS[@]}"; do
    pgrep -f "${pat}" >/dev/null 2>&1 && {
        echo "[kill] sweeping ${pat}"
        pkill -INT -f "${pat}" 2>/dev/null || true
    }
done

sleep 1
for pat in "${SWEEP_PATTERNS[@]}"; do
    pgrep -f "${pat}" >/dev/null 2>&1 && pkill -KILL -f "${pat}" 2>/dev/null || true
done

rm -f "${MODE_FILE}"
echo "[kill] done"
