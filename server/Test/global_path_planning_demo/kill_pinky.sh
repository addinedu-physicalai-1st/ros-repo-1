#!/usr/bin/env bash
# Stop driver + Nav2 on the pinky (mirrors start_pinky.sh).
# Run on the robot via ssh.

RUN_DIR="${HOME}/.pinky_demo"

stop_group() {
    local name="$1"
    local pidf="${RUN_DIR}/${name}.pid"
    [[ -f "${pidf}" ]] || { echo "[kill_pinky] ${name}: no pidfile"; return 0; }

    local pid
    pid="$(cat "${pidf}")"
    if ! kill -0 "${pid}" 2>/dev/null; then
        echo "[kill_pinky] ${name}: pid ${pid} not running"
        rm -f "${pidf}"
        return 0
    fi

    echo "[kill_pinky] ${name}: sending SIGINT to pgid ${pid}"
    kill -INT "-${pid}" 2>/dev/null || kill -INT "${pid}" 2>/dev/null || true

    for _ in $(seq 1 10); do
        kill -0 "${pid}" 2>/dev/null || break
        sleep 0.5
    done

    if kill -0 "${pid}" 2>/dev/null; then
        echo "[kill_pinky] ${name}: escalating to SIGTERM"
        kill -TERM "-${pid}" 2>/dev/null || kill -TERM "${pid}" 2>/dev/null || true
        sleep 2
    fi
    if kill -0 "${pid}" 2>/dev/null; then
        echo "[kill_pinky] ${name}: escalating to SIGKILL"
        kill -KILL "-${pid}" 2>/dev/null || kill -KILL "${pid}" 2>/dev/null || true
    fi

    rm -f "${pidf}"
}

stop_group nav2
stop_group driver

# Sweep stragglers.
for pat in \
    "ros2 launch pinky_navigation" \
    "ros2 launch pinky_bringup" \
    "nav2_" \
    "sllidar" \
    "pinky_bringup"; do
    pgrep -f "${pat}" >/dev/null 2>&1 && {
        echo "[kill_pinky] sweeping ${pat}"
        pkill -INT -f "${pat}" 2>/dev/null || true
    }
done

sleep 1
for pat in \
    "ros2 launch pinky_navigation" \
    "ros2 launch pinky_bringup" \
    "nav2_" \
    "sllidar"; do
    pgrep -f "${pat}" >/dev/null 2>&1 && pkill -KILL -f "${pat}" 2>/dev/null || true
done

echo "[kill_pinky] done"
