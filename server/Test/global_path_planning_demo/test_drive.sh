#!/usr/bin/env bash
# Drive the robot through a sequence of waypoint labels via
# nav2_bridge.py, reporting pass/fail per trial.
#
# Usage:
#   ./test_drive.sh                       # default cycle
#   ./test_drive.sh Kitchen Charging      # custom sequence
#   ./test_drive.sh --loops 3 Kitchen Charging Return Entrance
#
# Prereqs:
#   - start.sh has been run and the stack is up (Gazebo + Nav2 + monitor).
#   - AMCL is localized (monitor shows the robot on the map).
#
# Logs: ./.run/test_drive_<timestamp>.log

DEMO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_DIR="${DEMO_DIR}/.run"
mkdir -p "${RUN_DIR}"

# ROS setup.bash scripts reference unbound vars; source before enabling `set -u`.
# shellcheck disable=SC1091
source /opt/ros/jazzy/setup.bash
REPO_ROOT="$(cd "${DEMO_DIR}/../../.." && pwd)"
# shellcheck disable=SC1091
source "${REPO_ROOT}/install/setup.bash"

set -u

LOOPS=1
PER_GOAL_TIMEOUT=120
DEFAULT_SEQ=(Kitchen Charging Return Entrance Table-N Table-S)

usage() {
    cat <<EOF
usage: $(basename "$0") [--loops N] [--timeout SEC] [GOAL ...]

  --loops N       Repeat the whole sequence N times (default 1).
  --timeout SEC   Per-goal wall-clock timeout (default ${PER_GOAL_TIMEOUT}s).
  GOAL ...        Waypoint labels. Defaults to:
                  ${DEFAULT_SEQ[*]}
EOF
}

GOALS=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --loops) LOOPS="$2"; shift 2 ;;
        --timeout) PER_GOAL_TIMEOUT="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        --) shift; GOALS+=("$@"); break ;;
        -*) echo "unknown flag: $1" >&2; usage; exit 2 ;;
        *) GOALS+=("$1"); shift ;;
    esac
done
if [[ ${#GOALS[@]} -eq 0 ]]; then
    GOALS=("${DEFAULT_SEQ[@]}")
fi

# Sanity: the FollowPath action must be alive; otherwise the user
# forgot to run start.sh and every trial will just stall.
if ! ros2 action list 2>/dev/null | grep -q "/follow_path"; then
    echo "[test_drive] /follow_path action not found — is start.sh running?" >&2
    exit 1
fi

STAMP="$(date +%Y%m%d_%H%M%S)"
LOG="${RUN_DIR}/test_drive_${STAMP}.log"
: >"${LOG}"

total=0
pass=0
fail=0
declare -a FAILURES

echo "[test_drive] sequence: ${GOALS[*]} (x${LOOPS} loops, ${PER_GOAL_TIMEOUT}s/goal)"
echo "[test_drive] log: ${LOG}"
echo

start_t=$SECONDS
for ((loop=1; loop<=LOOPS; loop++)); do
    for goal in "${GOALS[@]}"; do
        total=$((total + 1))
        tag="loop${loop}/${goal}"
        echo "=== [${tag}] dispatching ==="
        echo "=== [${tag}] dispatching ===" >>"${LOG}"
        t0=$SECONDS
        if timeout "${PER_GOAL_TIMEOUT}" python3 "${DEMO_DIR}/nav2_bridge.py" \
                --goal "${goal}" >>"${LOG}" 2>&1; then
            dt=$((SECONDS - t0))
            # Bridge exits 0 both on success and on planning failure
            # — check the log for the actual arrival / preempt marker.
            if tail -30 "${LOG}" | grep -qE "Arrived at ${goal}|proximity preempt"; then
                pass=$((pass + 1))
                echo "    PASS (${dt}s)"
            else
                fail=$((fail + 1))
                FAILURES+=("${tag} (no arrival marker)")
                echo "    FAIL no arrival marker (${dt}s)"
            fi
        else
            rc=$?
            dt=$((SECONDS - t0))
            fail=$((fail + 1))
            FAILURES+=("${tag} (rc=${rc}, ${dt}s)")
            echo "    FAIL rc=${rc} (${dt}s)"
        fi
    done
done
elapsed=$((SECONDS - start_t))

echo
echo "=== summary ==="
echo "  total  : ${total}"
echo "  pass   : ${pass}"
echo "  fail   : ${fail}"
echo "  time   : ${elapsed}s"
if [[ ${fail} -gt 0 ]]; then
    echo "  failures:"
    for f in "${FAILURES[@]}"; do echo "    - ${f}"; done
    exit 1
fi
