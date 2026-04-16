#!/usr/bin/env bash
# Launch multi-robot control from the central server.
#
# Prerequisites:
#   - Each pinky robot must already be running driver + Nav2
#     (start_pinky.sh on each robot).
#   - All machines on the same Wi-Fi network with multicast allowed.
#
# Usage:
#   # 2 robots on different domain IDs (default)
#   ./start_multi.sh --goals Kitchen Return
#
#   # Explicit domain IDs
#   ./start_multi.sh --goals Kitchen Return --domain-ids 41 42
#
#   # Simulation (2 robots sharing the same domain)
#   ./start_multi.sh --sim --goals Kitchen Return
#
# Stop: Ctrl+C

DEMO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${DEMO_DIR}/../../.." && pwd)"

# ROS setup.bash scripts reference unbound vars; source before enabling `set -u`.
# shellcheck disable=SC1091
source /opt/ros/jazzy/setup.bash
# shellcheck disable=SC1091
source "${REPO_ROOT}/install/setup.bash"

set -u

MODE="real"
GOALS=()
DOMAIN_IDS=()
EXTRA_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --sim)
            MODE="sim"; shift ;;
        --real)
            MODE="real"; shift ;;
        --goals)
            shift
            while [[ $# -gt 0 && ! "$1" =~ ^-- ]]; do
                GOALS+=("$1"); shift
            done
            ;;
        --domain-ids)
            shift
            while [[ $# -gt 0 && ! "$1" =~ ^-- ]]; do
                DOMAIN_IDS+=("$1"); shift
            done
            ;;
        -h|--help)
            cat <<EOF
usage: $(basename "$0") [--sim | --real] --goals GOAL1 GOAL2 [--domain-ids ID1 ID2]

  --sim         Use sim time (Gazebo)
  --real        Real robot mode (default)
  --goals       Waypoint labels, one per robot
  --domain-ids  ROS_DOMAIN_ID per robot (default: 41 42 43 ...)
EOF
            exit 0 ;;
        *)
            EXTRA_ARGS+=("$1"); shift ;;
    esac
done

if [[ ${#GOALS[@]} -eq 0 ]]; then
    echo "[multi] ERROR: --goals required (e.g. --goals Kitchen Return)" >&2
    exit 1
fi

N_ROBOTS=${#GOALS[@]}

# Default domain IDs: 41, 42, 43, ...
if [[ ${#DOMAIN_IDS[@]} -eq 0 ]]; then
    for ((i=0; i<N_ROBOTS; i++)); do
        DOMAIN_IDS+=($((41 + i)))
    done
fi

if [[ "${MODE}" == "sim" ]]; then
    export DEMO_USE_SIM_TIME=true
else
    export DEMO_USE_SIM_TIME=false
fi

echo "[multi] mode=${MODE} (DEMO_USE_SIM_TIME=${DEMO_USE_SIM_TIME})"
echo "[multi] robots=${N_ROBOTS}"
for ((i=0; i<N_ROBOTS; i++)); do
    echo "  Robot-${i}: goal=${GOALS[$i]}, domain_id=${DOMAIN_IDS[$i]}"
done
echo

# Build the command
CMD=(python3 "${DEMO_DIR}/multi_robot_controller.py")
CMD+=(--goals "${GOALS[@]}")
CMD+=(--domain-ids "${DOMAIN_IDS[@]}")
if [[ ${#EXTRA_ARGS[@]} -gt 0 ]]; then
    CMD+=("${EXTRA_ARGS[@]}")
fi

echo "[multi] ${CMD[*]}"
echo
exec "${CMD[@]}"
