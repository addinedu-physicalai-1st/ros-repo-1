#!/usr/bin/env bash
# Launch the waypoint-planner demo stack in either sim or real mode.
#
#   sim  (default): Gazebo + gz_bringup_launch (use_sim_time=true) + monitor
#                   — everything on this machine.
#   --real        : monitor only. The pinky robot must be running
#                   driver + Nav2 already (see start_pinky.sh), and
#                   both machines must share ROS_DOMAIN_ID (default 41).
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

  --sim   (default) Launch Gazebo + Nav2 + monitor on this machine
                    (use_sim_time=true).
  --real            Launch monitor only. Pinky must already be running
                    driver + Nav2 (see start_pinky.sh) and both
                    machines must share ROS_DOMAIN_ID (default 41).
EOF
            exit 0 ;;
        *) echo "unknown flag: $1" >&2; exit 2 ;;
    esac
done

# ROS 2 peer discovery — both machines must agree.
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-41}"

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

echo "[start] mode=${MODE} (DEMO_USE_SIM_TIME=${DEMO_USE_SIM_TIME}, ROS_DOMAIN_ID=${ROS_DOMAIN_ID})"

if [[ "${MODE}" == "sim" ]]; then
    # 1) Gazebo
    start_bg gazebo ros2 launch pinky_gz_sim launch_sim.launch.xml
    wait_for "/scan topic" 30 bash -c 'ros2 topic list 2>/dev/null | grep -q "^/scan$"'

    # 2) Nav2 (sim bringup, use_sim_time=true)
    start_bg nav2 ros2 launch pinky_navigation gz_bringup_launch.xml \
        "map:=${MAP_YAML}" "use_sim_time:=true"

    wait_for "/follow_path action" 60 bash -c 'ros2 action list 2>/dev/null | grep -q "/follow_path"'
else
    # Real mode: Pinky is expected to be running driver + Nav2 already.
    # Verify discovery by waiting for /follow_path over the network.
    echo "[start] waiting for remote Nav2 on pinky..."
    if ! wait_for "/follow_path action (via pinky)" 60 bash -c 'ros2 action list 2>/dev/null | grep -q "/follow_path"'; then
        cat >&2 <<EOF
[start] ERROR: /follow_path not found on ROS_DOMAIN_ID=${ROS_DOMAIN_ID}.
  Is start_pinky.sh running on the pinky?
  Is ROS_DOMAIN_ID matching on both sides?
  Are both machines on the same network (multicast allowed)?
EOF
        rm -f "${MODE_FILE}"
        exit 1
    fi
fi

# Monitor (picks up DEMO_USE_SIM_TIME + ROS_DOMAIN_ID from the exported env).
start_bg monitor python3 "${DEMO_DIR}/monitor.py"

echo
echo "[start] stack up (mode=${MODE}). Logs: ${RUN_DIR}"
echo "[start] send a goal with:"
echo "        cd ${DEMO_DIR} && \\"
echo "          ROS_DOMAIN_ID=${ROS_DOMAIN_ID} DEMO_USE_SIM_TIME=${DEMO_USE_SIM_TIME} \\"
echo "          python3 nav2_bridge.py --goal Kitchen"
