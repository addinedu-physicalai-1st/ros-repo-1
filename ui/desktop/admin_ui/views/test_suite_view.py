from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QTableWidget, QTableWidgetItem, QHeaderView, QTabWidget, QAbstractItemView)
from PyQt5.QtGui import QFont
from PyQt5.QtCore import Qt, QTimer

TEST_CATEGORIES = {
    "A. 로봇 ↔ 관제": [
        ("TCP 연결 생성", "TCP", "[로봇→서버] 소켓 connect 시도", "정상 연결 (ESTABLISHED)"),
        ("TCP 재연결", "TCP", "서버 강제 종료 후 재연결", "자동 reconnect"),
        ("UDP 송신 가능", "UDP", "telemetry packet 전송", "패킷 수신됨"),
        ("다중 로봇 연결", "TCP/UDP", "3~10대 동시 연결", "모두 정상 유지"),
        ("연결 상태 모니터", "TCP", "heartbeat 체크", "offline 감지 가능")
    ],
    "B. 로봇 → 관제 UDP": [
        ("위치 데이터 송신", "10Hz", "초당 10회 송신 확인", "지연 없이 수신"),
        ("배터리 데이터 송신", "1Hz", "초당 1회 송신", "정상 반영"),
        ("패킷 유실 테스트", "10Hz", "일부 패킷 drop", "시스템 정상 동작"),
        ("순서 역행 테스트", "-", "seq 역전 데이터 전송", "무시됨"),
        ("timestamp 검증", "-", "과거 데이터 전송", "무시 또는 덮어쓰기"),
        ("Magic Number 검증", "-", "잘못된 magic 전송", "discard"),
        ("protobuf 파싱", "-", "malformed packet", "에러 없이 drop")
    ],
    "C. 관제 → 로봇 TCP": [
        ("MOVE_TO 명령", "위치 이동", "특정 좌표 이동", "정상 주행"),
        ("EMERGENCY_STOP", "즉시 정지", "주행 중 호출", "즉시 정지"),
        ("CANCEL", "작업 취소", "작업 중 취소", "작업 중단"),
        ("RETURN_DOCK", "충전 복귀", "충전 위치 이동", "정상 복귀"),
        ("중복 명령 처리", "명령 2회", "두 번 전송", "1회만 처리"),
        ("명령 ACK 확인", "cmd_id", "응답 수신", "ACK 정상"),
        ("연결 끊김 중 명령", "TCP 끊김", "명령 전송", "실패 처리")
    ],
    "D. TCP 상태/보고": [
        ("task_status 송신", "FSM 상태", "상태 변경 시 전송", "DB 반영"),
        ("heartbeat", "alive", "일정 주기 송신", "연결 유지"),
        ("protobuf 검증", "상태 메시지", "malformed", "drop")
    ],
    "E. REST API": [
        ("태스크 조회", "GET /tasks", "상태별 조회", "정상 JSON"),
        ("telemetry 조회", "GET /telemetry", "최신값 조회", "캐시값 반환"),
        ("명령 전송", "POST /commands", "로봇 제어", "cmd_id 반환"),
        ("인증 테스트", "Bearer", "잘못된 토큰", "401"),
        ("동시 요청", "동시 접근", "10~100 요청", "정상 처리")
    ],
    "F. 성능/실시간성": [
        ("UDP 지연", "<100ms", "latency 측정", "실시간 유지"),
        ("TCP 명령 지연", "<200ms", "명령→동작 시간", "즉시 반응"),
        ("서버 처리량", "로봇 수", "10대 이상", "안정 동작")
    ],
    "G. 장애/예외(⚠️)": [
        ("UDP 패킷 유실", "불안정", "30% drop", "시스템 정상"),
        ("TCP 연결 끊김", "WiFi OFF", "연결 종료", "재연결"),
        ("서버 다운", "Kill", "서버 강제 종료", "복구 후 정상")
    ]
}

class TestSuitePage(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        
        lbl = QLabel("🧪 네트워크 및 시스템 통합 테스트 보드")
        lbl.setFont(QFont("Malgun Gothic", 18, QFont.Bold))
        layout.addWidget(lbl)
        
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabBar::tab { padding: 10px 20px; font-weight: bold; background: #F0F2F5; border: 1px solid #DCDFE6; }
            QTabBar::tab:selected { background: white; color: #409EFF; border-bottom: none; }
            QTabWidget::pane { border: 1px solid #DCDFE6; }
        """)
        
        for cat_name, tests in TEST_CATEGORIES.items():
            tab_widget = QWidget()
            tab_widget.setStyleSheet("background: white;")
            t_layout = QVBoxLayout(tab_widget)
            t_layout.setContentsMargins(20, 20, 20, 20)
            
            table = QTableWidget(len(tests), 5)
            table.setHorizontalHeaderLabels(["테스트 항목", "대상/프로토콜", "테스트 내용", "기대 결과", "상태 / 실행"])
            table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
            table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
            table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
            table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
            table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
            table.setStyleSheet("QTableWidget { gridline-color: #E4E7ED; border: 1px solid #E4E7ED; }")
            table.setSelectionBehavior(QAbstractItemView.SelectRows)

            for row, item_tup in enumerate(tests):
                if len(item_tup) == 4:
                    t_item, t_target, t_content, t_expected = item_tup
                else:
                    t_item, t_content, t_expected = item_tup
                    t_target = "-"
                
                table.setItem(row, 0, QTableWidgetItem(t_item))
                table.setItem(row, 1, QTableWidgetItem(t_target))
                table.setItem(row, 2, QTableWidgetItem(t_content))
                table.setItem(row, 3, QTableWidgetItem(t_expected))
                
                action_frame = QWidget()
                a_layout = QHBoxLayout(action_frame)
                a_layout.setContentsMargins(5, 5, 5, 5)
                
                btn = QPushButton("▶ 실행")
                btn.setStyleSheet("background-color: #409EFF; color: white; border-radius: 4px; padding: 4px 10px; font-weight: bold;")
                
                status_lbl = QLabel("대기 중")
                status_lbl.setStyleSheet("color: #909399; font-weight: bold;")
                
                def make_run_func(b, s):
                    def run_click():
                        b.setText("진행 중")
                        b.setStyleSheet("background-color: #E6A23C; color: white; border-radius: 4px; padding: 4px 10px; font-weight: bold;")
                        QTimer.singleShot(1000, lambda: [
                            b.setText("완료✅"),
                            b.setEnabled(False),
                            b.setStyleSheet("background-color: #DCDFE6; color: #909399; border-radius: 4px; padding: 4px 10px; font-weight: bold;"),
                            s.setText("PASS"),
                            s.setStyleSheet("color: #67C23A; font-weight: bold;")
                        ])
                    return run_click
                
                btn.clicked.connect(make_run_func(btn, status_lbl))
                
                a_layout.addWidget(btn)
                a_layout.addWidget(status_lbl)
                
                table.setCellWidget(row, 4, action_frame)
                
            t_layout.addWidget(table)
            
            run_all_btn = QPushButton("▶ 현재 탭 전체 시나리오 실행")
            run_all_btn.setStyleSheet("background-color: #67C23A; color: white; padding: 10px; border-radius: 4px; font-weight: bold;")
            t_layout.addWidget(run_all_btn, 0, Qt.AlignRight)
            
            self.tabs.addTab(tab_widget, cat_name)
            
        layout.addWidget(self.tabs)
