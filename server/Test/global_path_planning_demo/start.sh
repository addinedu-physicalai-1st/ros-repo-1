#!/usr/bin/env bash
# Launch the full ROS-integrated waypoint-planner demo stack:
#   1) Gazebo sim (pinky_gz_sim)
#   2) Nav2 bringup (pinky_navigation) with map4.yaml
#   3) monitor.py (live visualization)
#
# nav2_bridge.py is per-goal and must be invoked manually, e.g.:
#   python3 nav2_bridge.py --goal Kitchen
#
# Logs: ./.run/*.log
# PIDs: ./.run/*.pid
# Stop: ./kill.sh

DEMO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${DEMO_DIR}/../../.." && pwd)"
RUN_DIR="${DEMO_DIR}/.run"
MAP_YAML="${REPO_ROOT}/install/pinky_navigation/share/pinky_navigation/map/map4.yaml"

mkdir -p "${RUN_DIR}"

# ROS setup.bash scripts reference unbound vars; source before enabling `set -u`.
# shellcheck disable=SC1091
source /opt/ros/jazzy/setup.bash
# shellcheck disable=SC1091
source "${REPO_ROOT}/install/setup.bash"

set -u

start_bg() {
    local name="$1"; shift
    local log="${RUN_DIR}/${name}.log"
    local pidf="${RUN_DIR}/${name}.pid"

    if [[ -f "${pidf}" ]] && kill -0 "$(cat "${pidf}")" 2>/dev/null; then
        echo "[start] ${name} already running (pid $(cat "${pidf}"))"
        return 0
    fi

    echo "[start] launching ${name} -> ${log}"
    setsid "$@" >"${log}" 2>&1 &
    echo $! >"${pidf}"
}

wait_for() {
    local label="$1"; local timeout="$2"; shift 2
    echo -n "[start] waiting for ${label} (max ${timeout}s) "
    for _ in $(seq 1 "${timeout}"); do
        if "$@" >/dev/null 2>&1; then echo "- ok"; return 0; fi
        echo -n "."
        sleep 1
    done
    echo " - TIMEOUT"
    return 1
}

# 1) Gazebo
start_bg gazebo ros2 launch pinky_gz_sim launch_sim.launch.xml

wait_for "/scan topic" 30 bash -c 'ros2 topic list 2>/dev/null | grep -q "^/scan$"'

# 2) Nav2
start_bg nav2 ros2 launch pinky_navigation gz_bringup_launch.xml "map:=${MAP_YAML}"

wait_for "/follow_path action" 60 bash -c 'ros2 action list 2>/dev/null | grep -q "/follow_path"'

# 3) Monitor
start_bg monitor python3 "${DEMO_DIR}/monitor.py"

echo
echo "[start] stack up. Logs: ${RUN_DIR}"
echo "[start] send a goal with:"
echo "        cd ${DEMO_DIR} && python3 nav2_bridge.py --goal Kitchen"
