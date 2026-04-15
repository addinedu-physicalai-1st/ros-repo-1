"""
event_publisher.py

/robot/event 토픽 퍼블리셔 래퍼 클래스.

ROBOT → HQ 이벤트를 publish_event() 한 번 호출로 전송한다.

지원 이벤트명:
    ArrivedAtRequester    - 요청자 위치 도착
    ArrivedAtKitchen      - 주방 도착
    ArrivedAtMenuLocation - 배송 목적지 도착
    ArrivedAtDishwashing  - 설거지장 도착
    ArrivedAtTarget       - 안내 목적지 도착
    ArrivedAtStandby      - 대기장소 도착
    NearTableOr1Min       - 테이블 근처 1분 경과 (동행)
    TimeoutWaiting        - 타임아웃 대기 알림
"""

from typing import Optional

from geometry_msgs.msg import PoseStamped

from rost_state_machine.msg import RobotEvent


class EventPublisher:
    """/robot/event 토픽 퍼블리셔 래퍼"""

    def __init__(self, node):
        """
        :param node: rclpy.node.Node 인스턴스
        """
        self._node = node
        self._pub = node.create_publisher(RobotEvent, '/robot/event', 10)

    def publish_event(
        self,
        event: str,
        session_id: str = '',
        pose: Optional[PoseStamped] = None,
    ) -> None:
        """
        RobotEvent 메시지를 /robot/event에 퍼블리시한다.

        :param event: 이벤트 이름 (ArrivedAtRequester 등)
        :param session_id: 현재 세션 ID
        :param pose: 현재 로봇 위치 (선택)
        """
        msg = RobotEvent()
        msg.event = event
        msg.session_id = session_id
        if pose is not None:
            msg.current_pose = pose

        self._pub.publish(msg)
        self._node.get_logger().info(
            f'[EVENT → HQ] {event}  (세션: {session_id})'
        )
