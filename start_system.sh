#!/usr/bin/env bash
# ============================================================================
# start_system.sh — Launch the full RosTaurant system
#
# Starts everything in order:
#   1) Pinky robots (driver + Nav2) via SSH
#   2) Control server (FastAPI + scheduler + path planning)
#   3) Web server (UI proxy)
#   4) Admin dashboard (PyQt5, optional)
#   5) Monitor (multi-robot visualization, optional)
#
# Usage:
#   ./start_system.sh                    # servers only (no robots, no monitor)
#   ./start_system.sh --robots           # servers + 2 robots
#   ./start_system.sh --robots --monitor # servers + 2 robots + monitor
#   ./start_system.sh --all              # everything
#
# Stop:
#   ./kill_system.sh
#   (or Ctrl+C if running in foreground)
#
# Environment variables:
#   ADMIN_API_KEY     — Admin API key (required for dashboard/web)
#   MRTA_PORT         — Control server port (default: 8000)
#   WEB_PORT          — Web server port (default: 3000)
#   MRTA_MAP_PATH     — Path planning map YAML (auto-detected if omitted)
#   PINKY1_IP         — Pinky 1 IP (required, set in .env)
#   PINKY2_IP         — Pinky 2 IP (required, set in .env)
#   PINKY1_DOMAIN_ID  — ROS domain for pinky 1 (default: 41)
#   PINKY2_DOMAIN_ID  — ROS domain for pinky 2 (default: 42)
# ============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER_DIR="${SCRIPT_DIR}/server"
DEMO_DIR="${SERVER_DIR}/Test/global_path_planning_demo"
RUN_DIR="${SCRIPT_DIR}/.run"
mkdir -p "${RUN_DIR}"

# Load .env if present (does not override already-set vars)
if [[ -f "${SCRIPT_DIR}/.env" ]]; then
    set -a; source "${SCRIPT_DIR}/.env"; set +a
fi

# Defaults
MRTA_PORT="${MRTA_PORT:-8000}"
WEB_PORT="${WEB_PORT:-3000}"
PINKY1_IP="${PINKY1_IP:?PINKY1_IP is not set. Define it in .env or export it.}"
PINKY2_IP="${PINKY2_IP:?PINKY2_IP is not set. Define it in .env or export it.}"
PINKY1_DOMAIN_ID="${PINKY1_DOMAIN_ID:-41}"
PINKY2_DOMAIN_ID="${PINKY2_DOMAIN_ID:-42}"

# Initial pose per robot: "x y z yaw" (set in .env or defaults)
PINKY1_INIT_POSE="${PINKY1_INIT_POSE:-0.0 0.0 0.0 0.0}"
PINKY2_INIT_POSE="${PINKY2_INIT_POSE:-0.05 -0.766 0.0 0.0}"

# Auto-detect map path
if [[ -z "${MRTA_MAP_PATH:-}" ]]; then
    for candidate in \
        "${DEMO_DIR}/maps/buffet_sim.yaml" \
        "${SCRIPT_DIR}/install/pinky_navigation/share/pinky_navigation/map/map4.yaml"; do
        if [[ -f "${candidate}" ]]; then
            export MRTA_MAP_PATH="${candidate}"
            break
        fi
    done
fi

# Flags
START_ROBOTS=false
START_MONITOR=false
NO_DASHBOARD="${NO_DASHBOARD:-0}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --robots)  START_ROBOTS=true; shift ;;
        --monitor) START_MONITOR=true; shift ;;
        --all)     START_ROBOTS=true; START_MONITOR=true; shift ;;
        --no-dashboard) NO_DASHBOARD=1; shift ;;
        -h|--help)
            cat <<EOF
usage: $(basename "$0") [--robots] [--monitor] [--all] [--no-dashboard]

  --robots        Start pinky robots via SSH (driver + Nav2)
  --monitor       Start multi-robot monitor (matplotlib visualization)
  --all           Start everything (robots + monitor + servers)
  --no-dashboard  Skip PyQt5 admin dashboard
EOF
            exit 0 ;;
        *) echo "unknown flag: $1" >&2; exit 2 ;;
    esac
done

echo "============================================================"
echo "  RosTaurant System Startup"
echo "============================================================"
echo "  Control server : http://localhost:${MRTA_PORT}"
echo "  Web server     : http://localhost:${WEB_PORT}"
echo "  Map path       : ${MRTA_MAP_PATH:-<none>}"
echo "  Robots         : ${START_ROBOTS}"
echo "  Monitor        : ${START_MONITOR}"
echo "============================================================"
echo

# ── 1) Pinky robots ────────────────────────────────────────────────
if [[ "${START_ROBOTS}" == "true" ]]; then
    echo "[system] Starting pinky robots..."

    for info in "${PINKY1_IP}:${PINKY1_DOMAIN_ID}:pinky1" \
                "${PINKY2_IP}:${PINKY2_DOMAIN_ID}:pinky2"; do
        IFS=: read -r ip domain_id name <<< "${info}"

        if ! ssh -o ConnectTimeout=3 -o BatchMode=yes "pinky@${ip}" "true" 2>/dev/null; then
            echo "[system] WARNING: ${name} (${ip}) not reachable — skipping"
            continue
        fi

        echo "[system] Starting ${name} (${ip}, domain=${domain_id})..."
        ssh "pinky@${ip}" "ROS_DOMAIN_ID=${domain_id} bash ~/start_pinky.sh" \
            >"${RUN_DIR}/${name}.log" 2>&1 &
        echo $! >"${RUN_DIR}/${name}_ssh.pid"
    done

    # Wait for SSH commands to complete
    wait
    echo "[system] Robots started."

    # Set initial poses via /initialpose topic
    echo "[system] Setting initial poses..."
    if [[ -f /opt/ros/jazzy/setup.bash ]]; then
        source /opt/ros/jazzy/setup.bash
        [[ -f "${SCRIPT_DIR}/install/setup.bash" ]] && source "${SCRIPT_DIR}/install/setup.bash"
    fi

    _publish_initial_pose() {
        local ip="$1" domain_id="$2" pose_str="$3" name="$4"
        # Skip silently if the robot is unreachable — saves the whole
        # startup from hanging when only one robot is powered on.
        if ! ssh -o ConnectTimeout=3 -o BatchMode=yes "pinky@${ip}" "true" 2>/dev/null; then
            echo "[system] skip initial pose for ${name} (${ip} unreachable)"
            return
        fi
        read px py pz pyaw <<< "${pose_str}"
        local qz qw
        qz=$(python3 -c "import math; print(math.sin(${pyaw}/2))")
        qw=$(python3 -c "import math; print(math.cos(${pyaw}/2))")
        timeout 10 ssh -o ConnectTimeout=3 "pinky@${ip}" \
            "source /opt/ros/jazzy/setup.bash && \
            ROS_DOMAIN_ID=${domain_id} ros2 topic pub /initialpose \
            geometry_msgs/msg/PoseWithCovarianceStamped \
            \"{header: {frame_id: 'map'}, pose: {pose: {position: {x: ${px}, y: ${py}, z: ${pz}}, orientation: {z: ${qz}, w: ${qw}}}}}\" \
            --once" >/dev/null 2>&1 &
    }

    _publish_initial_pose "${PINKY1_IP}" "${PINKY1_DOMAIN_ID}" "${PINKY1_INIT_POSE}" "pinky1"
    _publish_initial_pose "${PINKY2_IP}" "${PINKY2_DOMAIN_ID}" "${PINKY2_INIT_POSE}" "pinky2"
    wait
    echo "[system] Initial poses set."
    echo
fi

# ── 2) Control + Web servers ───────────────────────────────────────
echo "[system] Starting servers..."
# Dashboard is managed by this script, not server/start.sh.
export NO_DASHBOARD=1
(
    cd "${SERVER_DIR}"
    exec bash start.sh
) &
SERVERS_PID=$!
echo "${SERVERS_PID}" >"${RUN_DIR}/servers.pid"

# Wait for control server to be healthy
echo -n "[system] Waiting for control server "
for _ in $(seq 1 30); do
    if curl -sf "http://localhost:${MRTA_PORT}/health" >/dev/null 2>&1; then
        echo " ready"
        break
    fi
    echo -n "."
    sleep 1
done
echo

# ── Sync admin API key if DB's hash diverges from .env ─────────────
if [[ -n "${ADMIN_API_KEY:-}" ]]; then
    AUTH_CODE=$(curl -sS -o /dev/null -w "%{http_code}" -m 3 \
        -H "Authorization: Bearer ${ADMIN_API_KEY}" \
        "http://localhost:${MRTA_PORT}/robots" 2>/dev/null || echo "000")
    if [[ "${AUTH_CODE}" != "200" ]]; then
        echo "[system] Admin API key mismatch (HTTP ${AUTH_CODE}) — syncing DB..."
        (
            cd "${SERVER_DIR}"
            [[ -f .venv/bin/activate ]] && source .venv/bin/activate
            ADMIN_API_KEY="${ADMIN_API_KEY}" python3 - <<'PY'
import os, sys, sqlite3
sys.path.insert(0, 'control')
from auth import hash_api_key
conn = sqlite3.connect('control/rostaurant.db')
n = conn.execute(
    "UPDATE users SET api_key_hash = ? WHERE name = 'admin'",
    (hash_api_key(os.environ["ADMIN_API_KEY"]),),
).rowcount
conn.commit()
print(f"[system] Synced {n} admin user(s) to .env API key")
PY
        ) || echo "[system] WARNING: admin key sync failed"
    fi
fi

# ── Sync place coordinates from map YAML if NULL ───────────────────
if [[ -n "${MRTA_MAP_PATH:-}" && -f "${MRTA_MAP_PATH}" ]]; then
    MRTA_MAP_PATH="${MRTA_MAP_PATH}" /usr/bin/python3 - "${SERVER_DIR}" <<'PY' || echo "[system] WARNING: place coord sync failed"
import os, sys, sqlite3
server_dir = sys.argv[1]
sys.path.insert(0, os.path.join(server_dir, "lib"))
from path_planning import load_buffet_map

LABEL_TO_PLACE = {
    "Kitchen": "KITCHEN", "Waiting": "WAIT_A", "Kiosk": "KIOSK_1",
    "Table-N": "TBL_01", "Table-S": "TBL_02",
    "Toilet": "TOILET", "Food1": "DISP_01", "Food2": "DISP_02",
    "Food3": "DISP_03", "Collect": "DISP_04",
}
bm = load_buffet_map(os.environ["MRTA_MAP_PATH"])
conn = sqlite3.connect(os.path.join(server_dir, "control/rostaurant.db"))
changed = 0
for wp in bm.graph.waypoints.values():
    pid = LABEL_TO_PLACE.get(wp.label or "")
    if not pid:
        continue
    row = conn.execute("SELECT x, y FROM places WHERE place_id = ?", (pid,)).fetchone()
    if not row:
        continue
    if row[0] is None or row[1] is None or abs(row[0] - wp.x) > 1e-6 or abs(row[1] - wp.y) > 1e-6:
        conn.execute(
            "UPDATE places SET x = ?, y = ?, theta = ? WHERE place_id = ?",
            (float(wp.x), float(wp.y), float(getattr(wp, "yaw", 0.0) or 0.0), pid),
        )
        changed += 1
conn.commit()
if changed:
    print(f"[system] Synced {changed} place coord(s) from map YAML")
PY
fi

# ── 3) Monitor (standalone, only if --monitor without dashboard) ──
# The admin dashboard now includes the map visualization, so the
# standalone monitor is only needed for headless/debug scenarios.
if [[ "${START_MONITOR}" == "true" && "${START_ROBOTS}" == "true" ]]; then
    # Check if dashboard will run — if so, skip standalone monitor.
    DASHBOARD_DIR="${SCRIPT_DIR}/ui/desktop/admin_ui"
    if [[ -f "${DASHBOARD_DIR}/main.py" ]] && [[ -n "${DISPLAY:-}" || -n "${WAYLAND_DISPLAY:-}" ]]; then
        echo "[system] Monitor skipped (dashboard includes map visualization)"
    else
        echo "[system] Starting standalone multi-robot monitor..."
        if [[ -f /opt/ros/jazzy/setup.bash ]]; then
            source /opt/ros/jazzy/setup.bash
            [[ -f "${SCRIPT_DIR}/install/setup.bash" ]] && source "${SCRIPT_DIR}/install/setup.bash"
        fi
        export DEMO_USE_SIM_TIME=false
        (
            cd "${DEMO_DIR}"
            exec python3 monitor.py --domain-ids "${PINKY1_DOMAIN_ID}" "${PINKY2_DOMAIN_ID}"
        ) >"${RUN_DIR}/monitor.log" 2>&1 &
        MONITOR_PID=$!
        echo "${MONITOR_PID}" >"${RUN_DIR}/monitor.pid"
        echo "[system] Monitor PID: ${MONITOR_PID}"
    fi
    echo
fi

# ── 4) ROS2-to-Control bridge (relays TF → TCP/UDP telemetry) ─────
if [[ "${START_ROBOTS}" == "true" ]]; then
    BRIDGE_SCRIPT="${SERVER_DIR}/control/ros2_bridge.py"
    if [[ -f "${BRIDGE_SCRIPT}" ]]; then
        echo "[system] Starting ROS2 bridge..."
        if [[ -f /opt/ros/jazzy/setup.bash ]]; then
            source /opt/ros/jazzy/setup.bash
            [[ -f "${SCRIPT_DIR}/install/setup.bash" ]] && source "${SCRIPT_DIR}/install/setup.bash"
        fi
        export DEMO_USE_SIM_TIME=false
        /usr/bin/python3 "${BRIDGE_SCRIPT}" \
            --robot-ids pinky1 pinky2 \
            --domain-ids "${PINKY1_DOMAIN_ID}" "${PINKY2_DOMAIN_ID}" \
            >"${RUN_DIR}/bridge.log" 2>&1 &
        BRIDGE_PID=$!
        echo "${BRIDGE_PID}" >"${RUN_DIR}/bridge.pid"
        echo "[system] Bridge PID: ${BRIDGE_PID}"
    fi
fi

# ── 5) Dashboard (PyQt5 admin GUI) ─────────────────────────────────
DASHBOARD_DIR="${SCRIPT_DIR}/ui/desktop/admin_ui"
if [[ -f "${DASHBOARD_DIR}/main.py" ]] && [[ -n "${DISPLAY:-}" || -n "${WAYLAND_DISPLAY:-}" ]]; then
    echo "[system] Starting admin dashboard..."
    (
        cd "${DASHBOARD_DIR}"
        CONTROL_BASE_URL="http://localhost:${MRTA_PORT}" \
        ADMIN_API_KEY="${ADMIN_API_KEY:-}" \
        MRTA_MAP_PATH="${MRTA_MAP_PATH:-}" \
        exec /usr/bin/python3 main.py
    ) >"${RUN_DIR}/dashboard.log" 2>&1 &
    DASHBOARD_PID=$!
    echo "${DASHBOARD_PID}" >"${RUN_DIR}/dashboard.pid"
    echo "[system] Dashboard PID: ${DASHBOARD_PID}"
else
    echo "[system] Dashboard skipped (no display or main.py not found)"
fi

# ── 5) Open kiosk in browser ──────────────────────────────────────
KIOSK_URL="http://localhost:${WEB_PORT}/static/kiosk/kiosk.html"
if command -v xdg-open >/dev/null 2>&1 && [[ -n "${DISPLAY:-}" ]]; then
    echo "[system] Opening kiosk: ${KIOSK_URL}"
    xdg-open "${KIOSK_URL}" >/dev/null 2>&1 &
fi

# ── Summary ────────────────────────────────────────────────────────
echo "============================================================"
echo "  System running"
echo "============================================================"
echo "  Servers PID    : ${SERVERS_PID}"
[[ -f "${RUN_DIR}/bridge.pid" ]] && echo "  Bridge PID     : $(cat "${RUN_DIR}/bridge.pid")"
[[ -f "${RUN_DIR}/dashboard.pid" ]] && echo "  Dashboard PID  : $(cat "${RUN_DIR}/dashboard.pid")"
[[ -f "${RUN_DIR}/monitor.pid" ]] && echo "  Monitor PID    : $(cat "${RUN_DIR}/monitor.pid")"
if [[ "${START_ROBOTS}" == "true" ]]; then
    echo "  Pinky1         : ${PINKY1_IP} (domain ${PINKY1_DOMAIN_ID})"
    echo "  Pinky2         : ${PINKY2_IP} (domain ${PINKY2_DOMAIN_ID})"
fi
echo
echo "  Stop: ./kill_system.sh"
echo "============================================================"

# Keep running until Ctrl+C
cleanup() {
    echo ""
    echo "[system] Shutting down... use kill_system.sh for full cleanup."
    [[ -f "${RUN_DIR}/dashboard.pid" ]] && kill "$(cat "${RUN_DIR}/dashboard.pid")" 2>/dev/null || true
    [[ -f "${RUN_DIR}/bridge.pid" ]] && kill "$(cat "${RUN_DIR}/bridge.pid")" 2>/dev/null || true
    [[ -f "${RUN_DIR}/monitor.pid" ]] && kill "$(cat "${RUN_DIR}/monitor.pid")" 2>/dev/null || true
    kill "${SERVERS_PID}" 2>/dev/null || true
    wait 2>/dev/null || true
}
trap cleanup INT TERM

wait
