"""HTTP client for the control server REST API (synchronous / PyQt-safe).

All network calls run inside ApiWorker (QThread) so the Qt event loop is
never blocked.  Connect ApiWorker.result / ApiWorker.error signals to
update the UI.
"""

from __future__ import annotations

import requests
from PyQt5.QtCore import QThread, pyqtSignal


# ── enum label maps (mirrors robotcafe.proto) ────────────────────────────────

ROBOT_STATUS_LABELS: dict[int, str] = {
    0: "알 수 없음",
    1: "대기",
    2: "이동 중",
    3: "도착",
    4: "충전 중",
    5: "에러",
    6: "오프라인",
}

TASK_STATUS_LABELS: dict[int, str] = {
    0: "알 수 없음",
    1: "대기 중",
    2: "진행 중",
    3: "완료",
    4: "실패",
    5: "취소됨",
}

TASK_TYPE_LABELS: dict[int, str] = {
    0: "알 수 없음",
    1: "키오스크→테이블",
    2: "테이블→화장실",
    3: "테이블→디스플레이",
    4: "식기 수거",
    5: "로봇 교체",
    6: "안내 서비스",
    7: "도킹 복귀",
}

# CommandType enum values
CMD_UNSPECIFIED   = 0
CMD_MOVE_TO       = 1
CMD_CANCEL        = 2
CMD_RESET         = 3
CMD_RETURN_DOCK   = 4
CMD_EMERGENCY_STOP = 5


class ApiClient:
    """Thin synchronous wrapper around the control server REST API.

    Initialised from utils.config at import time so that env-var overrides
    applied before QApplication starts are respected.
    """

    def __init__(self) -> None:
        # Import here to avoid circular imports at module level
        from utils.config import CONTROL_BASE_URL, ADMIN_API_KEY  # noqa: PLC0415
        self.base = CONTROL_BASE_URL.rstrip("/")
        self.headers = {"Authorization": f"Bearer {ADMIN_API_KEY}"}
        self.timeout = 5

    # ── private helpers ───────────────────────────────────────────────────────

    def _get(self, path: str, **params) -> dict:
        r = requests.get(
            f"{self.base}{path}",
            headers=self.headers,
            params={k: v for k, v in params.items() if v is not None},
            timeout=self.timeout,
        )
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, data: dict) -> dict:
        r = requests.post(
            f"{self.base}{path}", json=data, headers=self.headers, timeout=self.timeout
        )
        r.raise_for_status()
        return r.json()

    def _patch(self, path: str, data: dict) -> dict:
        r = requests.patch(
            f"{self.base}{path}", json=data, headers=self.headers, timeout=self.timeout
        )
        r.raise_for_status()
        return r.json()

    def _put(self, path: str, data) -> dict:
        r = requests.put(
            f"{self.base}{path}", json=data, headers=self.headers, timeout=self.timeout
        )
        r.raise_for_status()
        return r.json()

    # ── public API methods ────────────────────────────────────────────────────

    def health_check(self) -> dict:
        return self._get("/health")

    def get_robots(self) -> dict:
        """GET /robots → {"robots": [...]}"""
        return self._get("/robots")

    def get_telemetry_pose(self, robot_id: str) -> dict:
        """GET /telemetry/pose/{robot_id} → {"latest_pose": {...}}"""
        return self._get(f"/telemetry/pose/{robot_id}")

    def get_telemetry_battery(self, robot_id: str) -> dict:
        """GET /telemetry/battery/{robot_id} → {"robot_id": str, "battery_percent": int}"""
        return self._get(f"/telemetry/battery/{robot_id}")

    def get_tasks(self, limit: int = 100, offset: int = 0) -> dict:
        """GET /tasks → {"tasks": [...], "total": int}"""
        return self._get("/tasks", limit=limit, offset=offset)

    def get_task(self, task_id: str) -> dict:
        """GET /tasks/{task_id} → {"task": {...}}"""
        return self._get(f"/tasks/{task_id}")

    def create_task(
        self,
        task_type: int,
        dest_id: str,
        requester_id: str = "",
        priority: int = 2,
    ) -> dict:
        """POST /tasks"""
        return self._post("/tasks", {
            "task_type": task_type,
            "dest_id": dest_id,
            "requester_id": requester_id,
            "priority": priority,
        })

    def send_command(
        self,
        robot_id: str,
        task_id: str,
        command: int,
        target_id: str = "",
    ) -> dict:
        """POST /commands/send"""
        return self._post("/commands/send", {
            "robot_id": robot_id,
            "task_id": task_id,
            "command": command,
            "target_id": target_id,
        })

    def get_places(self, active_only: bool = True) -> dict:
        """GET /places → {"places": [...]}"""
        return self._get("/places", active_only=1 if active_only else 0)

    def get_place_waypoints(self, place_id: str) -> dict:
        """GET /places/{place_id}/waypoints"""
        return self._get(f"/places/{place_id}/waypoints")

    def patch_place(self, place_id: str, data: dict) -> dict:
        """PATCH /places/{place_id}"""
        return self._patch(f"/places/{place_id}", data)

    def put_waypoints(self, place_id: str, waypoints: list) -> dict:
        """PUT /places/{place_id}/waypoints"""
        return self._put(f"/places/{place_id}/waypoints", waypoints)


class ApiWorker(QThread):
    """Run a single API call in a background thread.

    Usage::

        w = ApiWorker(client.get_robots)
        w.result.connect(my_slot)
        w.error.connect(lambda msg: print("API error:", msg))
        w.start()

    Keep a reference to the worker until it finishes (connect to
    ``w.finished`` to clean up).
    """

    result: pyqtSignal = pyqtSignal(object)
    error:  pyqtSignal = pyqtSignal(str)

    def __init__(self, fn, *args, **kwargs) -> None:
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs

    def run(self) -> None:
        try:
            data = self._fn(*self._args, **self._kwargs)
            self.result.emit(data)
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))
