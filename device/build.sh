#!/bin/bash
# build.sh — conda ros 환경에서 rostaurant 워크스페이스를 빌드합니다.
#
# 사용법:
#   ./build.sh                          # 전체 빌드
#   ./build.sh rostaurant_state_machine # 특정 패키지만 빌드
#
# 반드시 conda ros 환경 (Python 3.12) 에서 실행해야 합니다.
# rostaurant_state_machine 은 ament_cmake 패키지이므로
# Python3_EXECUTABLE 을 명시하지 않으면 base conda (3.13) 로 컴파일되어
# 런타임에 libpython3.13.so not found 오류가 발생합니다.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# conda ros 환경 확인
PYTHON_BIN="$(command -v python3)"
PYTHON_VERSION="$("${PYTHON_BIN}" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"

if [ "${PYTHON_VERSION}" != "3.12" ]; then
    echo "[build.sh] ERROR: Python ${PYTHON_VERSION} 감지됨."
    echo "[build.sh]        conda ros (Python 3.12) 환경을 먼저 활성화하세요:"
    echo "[build.sh]          conda activate ros"
    exit 1
fi

echo "[build.sh] Python ${PYTHON_VERSION} (${PYTHON_BIN}) 사용 — OK"

cd "${SCRIPT_DIR}"

if [ $# -eq 0 ]; then
    echo "[build.sh] 전체 빌드 시작..."
    colcon build --symlink-install \
        --cmake-args -DPython3_EXECUTABLE="${PYTHON_BIN}"
else
    echo "[build.sh] 패키지 빌드: $*"
    colcon build --symlink-install \
        --packages-select "$@" \
        --cmake-args -DPython3_EXECUTABLE="${PYTHON_BIN}"
fi

echo "[build.sh] 빌드 완료. source install/setup.bash 를 실행하세요."
