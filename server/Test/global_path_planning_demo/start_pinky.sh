#!/usr/bin/env bash
# Pinky-side launch for the split-architecture demo.
# Run THIS script on the robot (ssh into pinky, then execute).
# It brings up:
#   1) pinky_bringup (motors + LiDAR + TF + odom)
#   2) pinky_navigation Nav2 (use_sim_time=false)
#
# The laptop-side ``start.sh --real`` must share ROS_DOMAIN_ID with
# this script (default 41).
#
# Map file: this demo uses map4.yaml. scp it to pinky first, e.g.:
#   scp install/pinky_navigation/share/pinky_navigation/map/map4.{yaml,pgm} \
#       pinky@<IP>:~/
# Then export MAP_YAML=$HOME/map4.yaml (or pass --map).
#
# Logs: ~/.pinky_demo/*.log
# PIDs: ~/.pinky_demo/*.pid
# Stop: kill_pinky.sh

RUN_DIR="${HOME}/.pinky_demo"
mkdir -p "${RUN_DIR}"

# shellcheck disable=SC1091
source /opt/ros/jazzy/setup.bash
# Source the first workspace overlay that exists. Override via
# PINKY_OVERLAY=/path/to/install/setup.bash if your setup differs.
OVERLAY_CANDIDATES=(
    "${PINKY_OVERLAY:-}"
    "${HOME}/pinky_pro/install/setup.bash"
    "${HOME}/ros-repo-1/install/setup.bash"
)
for ov in "${OVERLAY_CANDIDATES[@]}"; do
    if [[ -n "${ov}" && -f "${ov}" ]]; then
        # shellcheck disable=SC1091
        source "${ov}"
        echo "[start_pinky] overlay: ${ov}"
        break
    fi
done

set -u

MAP_YAML_DEFAULT="${HOME}/map4.yaml"
MAP_YAML="${MAP_YAML:-${MAP_YAML_DEFAULT}}"
PARAMS_YAML_DEFAULT="${HOME}/nav2_params.yaml"
PARAMS_YAML="${PARAMS_YAML:-${PARAMS_YAML_DEFAULT}}"
SKIP_DRIVER="false"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --map) MAP_YAML="$2"; shift 2 ;;
        --params) PARAMS_YAML="$2"; shift 2 ;;
        --no-driver) SKIP_DRIVER="true"; shift ;;
        -h|--help)
            cat <<EOF
usage: $(basename "$0") [--map PATH] [--params PATH] [--no-driver]

  --map PATH     Map YAML for Nav2 (default: ${MAP_YAML_DEFAULT}).
  --params PATH  Nav2 params YAML (default: ${PARAMS_YAML_DEFAULT};
                 if missing, falls back to the one inside pinky_navigation
                 install).
  --no-driver    Skip pinky_bringup (use when the driver is already up,
                 e.g. during iterative Nav2 restarts).

Env:
  ROS_DOMAIN_ID  Peer discovery domain. Default 41 — must match laptop.
EOF
            exit 0 ;;
        *) echo "unknown flag: $1" >&2; exit 2 ;;
    esac
done

export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-41}"

if [[ ! -f "${MAP_YAML}" ]]; then
    echo "[start_pinky] ERROR: map not found at ${MAP_YAML}" >&2
    echo "  scp the map file from the laptop or pass --map PATH." >&2
    exit 1
fi

start_bg() {
    local name="$1"; shift
    local log="${RUN_DIR}/${name}.log"
    local pidf="${RUN_DIR}/${name}.pid"

    if [[ -f "${pidf}" ]] && kill -0 "$(cat "${pidf}")" 2>/dev/null; then
        echo "[start_pinky] ${name} already running (pid $(cat "${pidf}"))"
        return 0
    fi

    echo "[start_pinky] launching ${name} -> ${log}"
    setsid "$@" >"${log}" 2>&1 &
    echo $! >"${pidf}"
}

wait_for() {
    local label="$1"; local timeout="$2"; shift 2
    echo -n "[start_pinky] waiting for ${label} (max ${timeout}s) "
    for _ in $(seq 1 "${timeout}"); do
        if "$@" >/dev/null 2>&1; then echo "- ok"; return 0; fi
        echo -n "."
        sleep 1
    done
    echo " - TIMEOUT"
    return 1
}

echo "[start_pinky] ROS_DOMAIN_ID=${ROS_DOMAIN_ID}, map=${MAP_YAML}"

# 1) Driver (motors + LiDAR + odom + TF)
if [[ "${SKIP_DRIVER}" == "false" ]]; then
    start_bg driver ros2 launch pinky_bringup bringup_robot.launch.xml
    if ! wait_for "/scan topic" 30 \
            bash -c 'ros2 topic list 2>/dev/null | grep -q "^/scan$"'; then
        echo "[start_pinky] ERROR: /scan never appeared. Check LiDAR + driver." >&2
        exit 1
    fi
else
    echo "[start_pinky] skipping driver (--no-driver)"
fi

# 2) Nav2 (real bringup, wall time). Use the caller-supplied params
# file if available, otherwise fall back to the package default.
NAV2_ARGS=("map:=${MAP_YAML}" "use_sim_time:=false")
if [[ -f "${PARAMS_YAML}" ]]; then
    echo "[start_pinky] nav2 params: ${PARAMS_YAML}"
    NAV2_ARGS+=("params_file:=${PARAMS_YAML}")
else
    echo "[start_pinky] nav2 params: (package default — ${PARAMS_YAML} not found)"
fi
start_bg nav2 ros2 launch pinky_navigation bringup_launch.xml "${NAV2_ARGS[@]}"

if ! wait_for "/follow_path action" 60 \
        bash -c 'ros2 action list 2>/dev/null | grep -q "/follow_path"'; then
    echo "[start_pinky] ERROR: Nav2 /follow_path didn't come up. See nav2.log." >&2
    exit 1
fi

echo
echo "[start_pinky] ready. Laptop can now run: bash start.sh --real"
echo "[start_pinky] stop with: bash kill_pinky.sh"
