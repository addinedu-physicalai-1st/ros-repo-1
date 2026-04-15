#!/usr/bin/env bash
# Launch the waypoint-planner demo stack in either sim or real mode.
#
#   sim  (default): Gazebo + gz_bringup_launch (use_sim_time=true) + monitor
#   --real        : real-robot bringup_launch (use_sim_time=false) + monitor.
#                   Assumes the robot is already powered on and publishing
#                   /scan, odom, and tf for base_link/base_footprint.
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

MODE="sim"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --real) MODE="real"; shift ;;
        --sim)  MODE="sim";  shift ;;
        -h|--help)
            cat <<EOF
usage: $(basename "$0") [--sim | --real]

  --sim   (default) Launch Gazebo + Nav2 with use_sim_time=true
  --real            Launch Nav2 only with use_sim_time=false.
                    /scan, /odom and base TF must already be published
                    by the real robot.
EOF
            exit 0 ;;
        *) echo "unknown flag: $1" >&2; exit 2 ;;
    esac
done

# Record the mode so kill.sh and the Python processes know which
# clock domain they are in.
MODE_FILE="${RUN_DIR}/mode"
echo "${MODE}" >"${MODE_FILE}"
if [[ "${MODE}" == "sim" ]]; then
    export DEMO_USE_SIM_TIME=true
else
    export DEMO_USE_SIM_TIME=false
fi

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

echo "[start] mode=${MODE} (DEMO_USE_SIM_TIME=${DEMO_USE_SIM_TIME})"

if [[ "${MODE}" == "sim" ]]; then
    # 1) Gazebo
    start_bg gazebo ros2 launch pinky_gz_sim launch_sim.launch.xml
    wait_for "/scan topic" 30 bash -c 'ros2 topic list 2>/dev/null | grep -q "^/scan$"'

    # 2) Nav2 (sim bringup, use_sim_time=true by default in launch)
    start_bg nav2 ros2 launch pinky_navigation gz_bringup_launch.xml \
        "map:=${MAP_YAML}" "use_sim_time:=true"
else
    # Real robot: the robot stack (driver, LiDAR, odom publisher, TF)
    # must already be running — we only bring up Nav2 and the monitor.
    if ! ros2 topic list 2>/dev/null | grep -q "^/scan$"; then
        echo "[start] ERROR: /scan not found. Start the robot driver first." >&2
        rm -f "${MODE_FILE}"
        exit 1
    fi
    start_bg nav2 ros2 launch pinky_navigation bringup_launch.xml \
        "map:=${MAP_YAML}" "use_sim_time:=false"
fi

wait_for "/follow_path action" 60 bash -c 'ros2 action list 2>/dev/null | grep -q "/follow_path"'

# 3) Monitor (picks up DEMO_USE_SIM_TIME from the exported env).
start_bg monitor python3 "${DEMO_DIR}/monitor.py"

echo
echo "[start] stack up (mode=${MODE}). Logs: ${RUN_DIR}"
echo "[start] send a goal with:"
echo "        cd ${DEMO_DIR} && DEMO_USE_SIM_TIME=${DEMO_USE_SIM_TIME} python3 nav2_bridge.py --goal Kitchen"
