"""task_executor_node: /robot_command → NavigationDriver → /task_status

아키텍처:
  NavigationDriver (ABC)          ← 나중에 주행 패키지로 교체할 인터페이스
      └── Nav2Driver              ← 현재 구현체 (Nav2 NavigateToPose)

  TaskExecutorNode
      ├── subscribe  /robot_command  (RobotCommand)
      ├── publish    /task_status    (RobotTaskStatus)
      └── delegate   NavigationDriver.navigate_to() / cancel()

주행 패키지 교체 방법:
    1. NavigationDriver 를 상속한 새 클래스 작성
    2. navigate_to() 와 cancel() 구현
    3. main() 에서 Nav2Driver() 대신 새 드라이버로 교체
    → TaskExecutorNode 코드는 수정 없음
"""

from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod
from typing import Optional

import rclpy
from geometry_msgs.msg import PoseStamped
from nav2_msgs.action import NavigateToPose
from rclpy.action import ActionClient
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy

from pinky_interfaces.msg import RobotCommand, RobotTaskStatus

# ─────────────────────────────────────────────────────────────────────────────
# CommandType 숫자값 (proto enum과 동일)
# ─────────────────────────────────────────────────────────────────────────────
CMD_MOVE_TO        = 1
CMD_CANCEL         = 2
CMD_RESET          = 3
CMD_RETURN_DOCK    = 4
CMD_EMERGENCY_STOP = 5
CMD_FOLLOW         = 6
CMD_COLLECT        = 7
CMD_DELIVERY       = 8
CMD_GUIDE          = 9

# FollowAction 숫자값
FOLLOW_MOVE_TO_REQUESTER = 1
FOLLOW_START             = 2
FOLLOW_END               = 3
FOLLOW_GO_TO_TABLE       = 4
FOLLOW_RESTART           = 5
FOLLOW_RETRY             = 6

# CollectionAction 숫자값
COLLECT_MOVE_TO_REQUESTER   = 1
COLLECT_START               = 2
COLLECT_DONE                = 3
COLLECT_MOVE_TO_DISHWASHING = 4
COLLECT_END                 = 5
COLLECT_RETRY               = 6

# DeliveryAction 숫자값
DELIVERY_MOVE_TO_KITCHEN = 1
DELIVERY_START           = 2
DELIVERY_NEXT            = 3
DELIVERY_RETRY           = 4
DELIVERY_END             = 5

# GuidanceAction 숫자값
GUIDANCE_MOVE_TO_REQUESTER = 1
GUIDANCE_START             = 2
GUIDANCE_RETRY             = 3
GUIDANCE_END               = 4

# TaskEventType 숫자값 (RobotTaskStatus.event_type 에 실어 발행)
EVENT_NONE                 = 0
EVENT_ARRIVED_AT_REQUESTER = 1
EVENT_ARRIVED_AT_TABLE     = 2
EVENT_ARRIVED_AT_KITCHEN   = 3
EVENT_ARRIVED_AT_DISHWASHING = 4
EVENT_ARRIVED_AT_MENU      = 5
EVENT_ARRIVED_AT_DEST      = 6
EVENT_NEAR_TABLE_1MIN      = 7

# 이동이 필요한 태스크별 액션 집합
_NAV_ACTIONS: dict[int, dict[int, int]] = {
    # cmd_type → {task_action → arrival_event}
    CMD_FOLLOW: {
        FOLLOW_MOVE_TO_REQUESTER: EVENT_ARRIVED_AT_REQUESTER,
        FOLLOW_GO_TO_TABLE:       EVENT_ARRIVED_AT_TABLE,
        FOLLOW_RETRY:             EVENT_ARRIVED_AT_REQUESTER,
    },
    CMD_COLLECT: {
        COLLECT_MOVE_TO_REQUESTER:   EVENT_ARRIVED_AT_REQUESTER,
        COLLECT_MOVE_TO_DISHWASHING: EVENT_ARRIVED_AT_DISHWASHING,
        COLLECT_RETRY:               EVENT_ARRIVED_AT_REQUESTER,
    },
    CMD_DELIVERY: {
        DELIVERY_MOVE_TO_KITCHEN: EVENT_ARRIVED_AT_KITCHEN,
        DELIVERY_START:           EVENT_ARRIVED_AT_MENU,
        DELIVERY_NEXT:            EVENT_ARRIVED_AT_MENU,
        DELIVERY_RETRY:           EVENT_ARRIVED_AT_MENU,
    },
    CMD_GUIDE: {
        GUIDANCE_MOVE_TO_REQUESTER: EVENT_ARRIVED_AT_REQUESTER,
        GUIDANCE_START:             EVENT_ARRIVED_AT_DEST,
        GUIDANCE_RETRY:             EVENT_ARRIVED_AT_DEST,
    },
}

# RobotStatus 숫자값
STATUS_IDLE    = 1
STATUS_MOVING  = 2
STATUS_ARRIVED = 3
STATUS_ERROR   = 5

# FsmState 숫자값
FSM_IDLE          = 1
FSM_MOVING_TO_WP  = 3
FSM_ARRIVED       = 5
FSM_RETURNING     = 6
FSM_NAV_FAILED    = 7

# 동행: FOLLOW_START 후 1분 타이머 (초)
FOLLOW_NEAR_TABLE_SECONDS = 60.0


# ─────────────────────────────────────────────────────────────────────────────
# 주행 드라이버 인터페이스 (교체 지점)
# ─────────────────────────────────────────────────────────────────────────────

class NavigationDriver(ABC):
    """주행 백엔드 추상 인터페이스.

    나중에 커스텀 주행 패키지로 교체할 때:
      1. 이 클래스를 상속
      2. navigate_to() 와 cancel() 구현
      3. main() 에서 Nav2Driver() → 새 드라이버로만 교체
    """

    @abstractmethod
    def navigate_to(
        self,
        x: float,
        y: float,
        theta: float,
        on_result: "Callable[[bool], None]",
    ) -> None:
        """목적지로 이동 시작. 완료/실패 시 on_result(success) 콜백 호출."""

    @abstractmethod
    def cancel(self) -> None:
        """현재 진행 중인 주행을 취소."""


# ─────────────────────────────────────────────────────────────────────────────
# Nav2 구현체
# ─────────────────────────────────────────────────────────────────────────────

class Nav2Driver(NavigationDriver):
    """Nav2 NavigateToPose 액션 클라이언트 기반 드라이버."""

    def __init__(self, node: Node) -> None:
        self._node = node
        self._client = ActionClient(node, NavigateToPose, "navigate_to_pose")
        self._goal_handle: Optional[object] = None
        self._lock = threading.Lock()

    def wait_for_server(self, timeout_sec: float = 10.0) -> bool:
        self._node.get_logger().info("Nav2Driver: waiting for navigate_to_pose action server...")
        ready = self._client.wait_for_server(timeout_sec=timeout_sec)
        if ready:
            self._node.get_logger().info("Nav2Driver: action server ready")
        else:
            self._node.get_logger().warn("Nav2Driver: action server not available (timeout)")
        return ready

    def navigate_to(self, x: float, y: float, theta: float, on_result) -> None:
        import math
        goal = NavigateToPose.Goal()
        goal.pose = PoseStamped()
        goal.pose.header.frame_id = "map"
        goal.pose.header.stamp = self._node.get_clock().now().to_msg()
        goal.pose.pose.position.x = x
        goal.pose.pose.position.y = y
        # theta → quaternion (yaw only)
        goal.pose.pose.orientation.z = math.sin(theta / 2.0)
        goal.pose.pose.orientation.w = math.cos(theta / 2.0)

        self._node.get_logger().info(f"Nav2Driver: navigate_to x={x:.3f} y={y:.3f} θ={theta:.3f}")

        send_future = self._client.send_goal_async(goal)

        def _on_goal_accepted(future):
            handle = future.result()
            if not handle.accepted:
                self._node.get_logger().warn("Nav2Driver: goal rejected")
                on_result(False)
                return
            with self._lock:
                self._goal_handle = handle
            result_future = handle.get_result_async()
            result_future.add_done_callback(lambda f: _on_result(f, on_result))

        def _on_result(future, cb):
            with self._lock:
                self._goal_handle = None
            result = future.result()
            # NavigateToPose result: status 4 = SUCCEEDED
            success = (result.status == 4)
            self._node.get_logger().info(f"Nav2Driver: result status={result.status} success={success}")
            cb(success)

        send_future.add_done_callback(_on_goal_accepted)

    def cancel(self) -> None:
        with self._lock:
            handle = self._goal_handle
        if handle is not None:
            self._node.get_logger().info("Nav2Driver: cancelling goal")
            handle.cancel_goal_async()


# ─────────────────────────────────────────────────────────────────────────────
# 태스크 실행 노드
# ─────────────────────────────────────────────────────────────────────────────

class TaskExecutorNode(Node):
    """/robot_command 를 받아 주행 드라이버에 전달하고 /task_status 를 발행."""

    def __init__(self, driver: NavigationDriver) -> None:
        super().__init__("pinky_task_executor")
        self._driver = driver

        self.declare_parameter("robot_command_topic", "/robot_command")
        self.declare_parameter("task_status_topic",   "/task_status")
        self.declare_parameter("robot_id",            "")

        cmd_topic    = self.get_parameter("robot_command_topic").value
        status_topic = self.get_parameter("task_status_topic").value
        self._robot_id: str = self.get_parameter("robot_id").value

        qos = QoSProfile(
            depth=10,
            reliability=ReliabilityPolicy.RELIABLE,
            history=HistoryPolicy.KEEP_LAST,
        )

        self._cmd_sub = self.create_subscription(
            RobotCommand, cmd_topic, self._on_command, qos
        )
        self._status_pub = self.create_publisher(RobotTaskStatus, status_topic, qos)

        # 현재 실행 중인 커맨드 정보
        self._current_cmd_id:    str = ""
        self._current_task_id:   str = ""
        self._current_cmd_type:  int = 0
        self._current_task_action: int = 0
        self._fsm_state:         int = FSM_IDLE
        self._robot_status:      int = STATUS_IDLE
        self._lock = threading.Lock()

        # 동행 near-table 타이머
        self._near_table_timer: Optional[threading.Timer] = None

        self.get_logger().info(
            f"TaskExecutorNode ready — cmd={cmd_topic} status={status_topic}"
        )

    # ── 커맨드 수신 진입점 ──────────────────────────────────────────────

    def _on_command(self, msg: RobotCommand) -> None:
        cmd = int(msg.command)
        action = int(msg.task_action)
        self.get_logger().info(
            f"[CMD] cmd_id={msg.cmd_id} type={cmd} action={action} "
            f"step={msg.step_index} target=({msg.target_x:.2f},{msg.target_y:.2f})"
        )

        if cmd == CMD_MOVE_TO:
            self._handle_navigate(msg, arrival_event=EVENT_NONE)

        elif cmd == CMD_RETURN_DOCK:
            self._handle_navigate(msg, arrival_event=EVENT_NONE, is_return=True)

        elif cmd in (CMD_CANCEL, CMD_RESET):
            self._handle_cancel()

        elif cmd == CMD_EMERGENCY_STOP:
            self._handle_emergency_stop()

        elif cmd in (CMD_FOLLOW, CMD_COLLECT, CMD_DELIVERY, CMD_GUIDE):
            self._handle_task_command(msg)

        else:
            self.get_logger().warn(f"Unknown command type: {cmd}")

    # ── 태스크별 커맨드 분기 ────────────────────────────────────────────

    def _handle_task_command(self, msg: RobotCommand) -> None:
        """FOLLOW_CMD / COLLECT_CMD / DELIVERY_CMD / GUIDE_CMD 처리."""
        cmd    = int(msg.command)
        action = int(msg.task_action)

        # 이동이 필요한 액션 → navigate_to() 실행
        nav_map = _NAV_ACTIONS.get(cmd, {})
        if action in nav_map:
            arrival_event = nav_map[action]
            self._handle_navigate(msg, arrival_event=arrival_event)
            return

        # 이동 없이 상태 전환만 하는 액션 처리
        if cmd == CMD_FOLLOW:
            self._handle_follow_action(msg, action)
        elif cmd == CMD_COLLECT:
            self._handle_collect_action(msg, action)
        elif cmd == CMD_DELIVERY:
            self._handle_delivery_action(msg, action)
        elif cmd == CMD_GUIDE:
            self._handle_guidance_action(msg, action)

    # ── 동행 비이동 액션 ─────────────────────────────────────────────────

    def _handle_follow_action(self, msg: RobotCommand, action: int) -> None:
        if action == FOLLOW_START:
            # 동행 시작: 1분 타이머 시작 → 완료 시 NEAR_TABLE_1MIN 이벤트 발행
            self._cancel_near_table_timer()
            self.get_logger().info(
                f"[FOLLOW_START] task={msg.task_id} — near-table timer {FOLLOW_NEAR_TABLE_SECONDS}s"
            )
            with self._lock:
                self._current_task_id  = msg.task_id
                self._current_cmd_type = CMD_FOLLOW
                self._robot_status     = STATUS_MOVING  # 동행 중 = MOVING 상태

            self._publish_status(FSM_MOVING_TO_WP, STATUS_MOVING, msg.task_id)

            # 1분 후 NEAR_TABLE_1MIN 이벤트 발행
            task_id = msg.task_id
            timer = threading.Timer(
                FOLLOW_NEAR_TABLE_SECONDS,
                lambda: self._on_near_table_timeout(task_id),
            )
            timer.daemon = True
            timer.start()
            with self._lock:
                self._near_table_timer = timer

        elif action in (FOLLOW_END, FOLLOW_RESTART):
            # 동행 종료 / 재시작 — 타이머 취소 후 IDLE 복귀
            self._cancel_near_table_timer()
            label = "FOLLOW_END" if action == FOLLOW_END else "FOLLOW_RESTART"
            self.get_logger().info(f"[{label}] task={msg.task_id}")
            with self._lock:
                task_id = self._current_task_id
                self._current_task_id = ""
                self._current_cmd_id  = ""
                self._fsm_state       = FSM_IDLE
                self._robot_status    = STATUS_IDLE
            self._publish_status(FSM_IDLE, STATUS_IDLE, task_id)

        else:
            self.get_logger().warn(f"[FOLLOW] unhandled action={action}")

    # ── 수거 비이동 액션 ─────────────────────────────────────────────────

    def _handle_collect_action(self, msg: RobotCommand, action: int) -> None:
        if action == COLLECT_START:
            # 수거 동작 시작 신호 — 실제 수거 메커니즘은 하드웨어 토픽으로 제어
            self.get_logger().info(f"[COLLECT_START] task={msg.task_id}")
            self._publish_status(FSM_MOVING_TO_WP, STATUS_MOVING, msg.task_id)

        elif action == COLLECT_DONE:
            # 수거 완료 처리 — IDLE 로 전환 (다음 커맨드 대기)
            self.get_logger().info(f"[COLLECT_DONE] task={msg.task_id}")
            self._publish_status(FSM_ARRIVED, STATUS_ARRIVED, msg.task_id)

        elif action == COLLECT_END:
            # 수거 종료
            self.get_logger().info(f"[COLLECT_END] task={msg.task_id}")
            with self._lock:
                task_id = self._current_task_id
                self._current_task_id = ""
                self._current_cmd_id  = ""
                self._fsm_state       = FSM_IDLE
                self._robot_status    = STATUS_IDLE
            self._publish_status(FSM_IDLE, STATUS_IDLE, task_id)

        else:
            self.get_logger().warn(f"[COLLECT] unhandled action={action}")

    # ── 운반 비이동 액션 ─────────────────────────────────────────────────

    def _handle_delivery_action(self, msg: RobotCommand, action: int) -> None:
        if action == DELIVERY_END:
            # 운반 종료
            self.get_logger().info(f"[DELIVERY_END] task={msg.task_id}")
            with self._lock:
                task_id = self._current_task_id
                self._current_task_id = ""
                self._current_cmd_id  = ""
                self._fsm_state       = FSM_IDLE
                self._robot_status    = STATUS_IDLE
            self._publish_status(FSM_IDLE, STATUS_IDLE, task_id)

        else:
            self.get_logger().warn(f"[DELIVERY] unhandled action={action}")

    # ── 안내 비이동 액션 ─────────────────────────────────────────────────

    def _handle_guidance_action(self, msg: RobotCommand, action: int) -> None:
        if action == GUIDANCE_END:
            # 안내 종료
            self.get_logger().info(f"[GUIDANCE_END] task={msg.task_id}")
            with self._lock:
                task_id = self._current_task_id
                self._current_task_id = ""
                self._current_cmd_id  = ""
                self._fsm_state       = FSM_IDLE
                self._robot_status    = STATUS_IDLE
            self._publish_status(FSM_IDLE, STATUS_IDLE, task_id)

        else:
            self.get_logger().warn(f"[GUIDANCE] unhandled action={action}")

    # ── 이동 공통 핸들러 ────────────────────────────────────────────────

    def _handle_navigate(
        self,
        msg: RobotCommand,
        arrival_event: int,
        is_return: bool = False,
    ) -> None:
        """navigate_to() 를 실행하고 완료 시 arrival_event 를 포함해 상태를 발행."""
        self._cancel_near_table_timer()

        with self._lock:
            if self._robot_status == STATUS_MOVING:
                self._driver.cancel()
            self._current_cmd_id    = msg.cmd_id
            self._current_task_id   = msg.task_id
            self._current_cmd_type  = int(msg.command)
            self._current_task_action = int(msg.task_action)
            self._fsm_state         = FSM_MOVING_TO_WP
            self._robot_status      = STATUS_MOVING

        fsm_moving = FSM_RETURNING if is_return else FSM_MOVING_TO_WP
        self._publish_status(fsm_moving, STATUS_MOVING, msg.task_id)

        def on_result(success: bool) -> None:
            with self._lock:
                if self._current_cmd_id != msg.cmd_id:
                    return  # 이미 다른 커맨드로 교체됨
                if success:
                    self._fsm_state    = FSM_ARRIVED
                    self._robot_status = STATUS_ARRIVED
                else:
                    self._fsm_state    = FSM_NAV_FAILED
                    self._robot_status = STATUS_ERROR

            if success:
                self.get_logger().info(
                    f"[ARRIVED] task={msg.task_id} dest={msg.target_id} event={arrival_event}"
                )
                # arrival_event 를 event_type 에 실어 발행 → ros_bridge_node 가 TaskEvent 로 전달
                self._publish_status(
                    FSM_ARRIVED, STATUS_ARRIVED, msg.task_id,
                    event_type=arrival_event,
                )
            else:
                self.get_logger().warn(f"[NAV_FAILED] task={msg.task_id}")
                self._publish_status(FSM_NAV_FAILED, STATUS_ERROR, msg.task_id)

        self._driver.navigate_to(msg.target_x, msg.target_y, msg.target_theta, on_result)

    def _handle_cancel(self) -> None:
        self._cancel_near_table_timer()
        self._driver.cancel()
        with self._lock:
            self._fsm_state    = FSM_IDLE
            self._robot_status = STATUS_IDLE
            task_id = self._current_task_id
            self._current_cmd_id    = ""
            self._current_task_id   = ""
            self._current_cmd_type  = 0
            self._current_task_action = 0
        self._publish_status(FSM_IDLE, STATUS_IDLE, task_id)
        self.get_logger().info("[CANCEL] navigation cancelled, back to IDLE")

    def _handle_emergency_stop(self) -> None:
        self._cancel_near_table_timer()
        self._driver.cancel()
        with self._lock:
            self._fsm_state    = FSM_IDLE
            self._robot_status = STATUS_ERROR
            task_id = self._current_task_id
            self._current_cmd_id    = ""
            self._current_task_id   = ""
            self._current_cmd_type  = 0
            self._current_task_action = 0
        self._publish_status(FSM_IDLE, STATUS_ERROR, task_id)
        self.get_logger().warn("[E-STOP] emergency stop executed")

    # ── 동행 near-table 타이머 ────────────────────────────────────────

    def _on_near_table_timeout(self, task_id: str) -> None:
        """1분 타이머 완료 → NEAR_TABLE_1MIN 이벤트 발행."""
        with self._lock:
            if self._current_task_id != task_id:
                return  # 이미 다른 태스크로 전환됨
        self.get_logger().info(f"[NEAR_TABLE_1MIN] task={task_id}")
        self._publish_status(
            FSM_ARRIVED, STATUS_ARRIVED, task_id,
            event_type=EVENT_NEAR_TABLE_1MIN,
        )

    def _cancel_near_table_timer(self) -> None:
        with self._lock:
            timer = self._near_table_timer
            self._near_table_timer = None
        if timer is not None:
            timer.cancel()

    # ── 상태 발행 ─────────────────────────────────────────────────────

    def _publish_status(
        self,
        fsm: int,
        robot_status: int,
        task_id: str,
        event_type: int = EVENT_NONE,
    ) -> None:
        msg = RobotTaskStatus()
        msg.robot_id     = self._robot_id
        msg.robot_status = robot_status
        msg.fsm_state    = fsm
        msg.current_task = task_id
        msg.battery      = 0   # battery는 pinky_bringup의 battery_publisher가 담당
        msg.last_error   = 0
        msg.event_type   = event_type
        self._status_pub.publish(msg)


# ─────────────────────────────────────────────────────────────────────────────
# 진입점
# ─────────────────────────────────────────────────────────────────────────────

def main(args=None):
    rclpy.init(args=args)

    # ── 주행 드라이버 교체 지점 ──────────────────────────────────
    # 나중에 커스텀 주행 패키지로 바꿀 때 여기만 수정:
    #   driver = MyCustomDriver(node)
    # ─────────────────────────────────────────────────────────────

    # 임시 노드로 ActionClient 초기화
    tmp_node = rclpy.create_node("_task_executor_init")
    driver = Nav2Driver(tmp_node)
    tmp_node.destroy_node()

    node = TaskExecutorNode(driver)

    # Nav2Driver 의 ActionClient 를 TaskExecutorNode 컨텍스트에서 재생성
    driver._node = node
    driver._client = ActionClient(node, NavigateToPose, "navigate_to_pose")
    driver.wait_for_server(timeout_sec=10.0)

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
