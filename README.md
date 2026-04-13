# Smart Restaurant Robot System - Admin Dashboard

## 📖 프로젝트 소개 (Introduction)
본 프로젝트는 스마트 레스토랑 로봇 시스템을 위한 모듈형 **PyQt5 기반의 통합 관제 대시보드 (Admin Dashboard)** 입니다. 로봇의 실시간 관제, 개별 네트워크 설정, 맵 및 테이블 관리, 태스크 할당, 블랙박스 녹화 기록 관리 및 시스템 네트워크 모의 테스트 기능을 단일 어플리케이션 안에서 모두 제공합니다.

## ✨ 주요 기능 (Key Features)
1. **🗺️ 관제 메인 페이지 (Map Dashboard)**
   - 로봇의 위치와 이동 경로를 시각적으로 모니터링할 수 있는 반응형 맵 뷰 제공.
2. **🤖 로봇 개별 환경 설정 (Robot Setting)**
   - 각 로봇의 TCP/UDP 네트워크 파라미터 등 상세 연결 환경을 구성하고 제어.
3. **🪑 맵(테이블/경로) 설정 (Map Setting)**
   - 매장 내 테이블 추가/삭제 및 로봇의 주행 경로 등을 직관적으로 설정.
4. **📝 태스크(작업) 통합 관리 (Task Management)**
   - 로봇에게 할당되는 각종 서빙 및 이동 태스크를 종합적으로 관리.
5. **📹 비전 및 녹화 관리 (Vision & Record Management)**
   - 로봇의 비전 시스템 및 블랙박스 역할을 하는 녹화 기록 조회 기능.
6. **🧪 관제 시스템 및 네트워크 테스트 (System & Network Tests)**
   - TCP 상태, REST API, 실시간 응답 성능, 장애 및 예외 상황 등에 대한 통합 네트워크 모의 테스트 및 히스토리 트래킹 기능 지원.

## 📂 디렉토리 구조 (Directory Structure)
UI 관련 코드는 `ui/desktop/admin_ui/` 하위에 완전하게 모듈화되어 있습니다.

```text
ros-repo-1/
└── ui/
    └── desktop/
        └── admin_ui/
            ├── main.py              # 메인 실행 파일 및 통합 GUI (QMainWindow)
            ├── components/          # 재사용 가능한 UI 컴포넌트(위젯)
            ├── utils/               # 유틸리티 (예: test_manager.py)
            └── views/               # 기능별 개별 페이지 화면 구성
                ├── map_view.py              # 맵 관제 대시보드
                ├── robot_setting_view.py    # 로봇 환경 설정
                ├── map_setting_view.py      # 맵 & 테이블 설정
                ├── task_view.py             # 태스크 관리
                └── record_view.py           # 비전 및 녹화 관리
```

## ⚙️ 요구 환경 (Requirements)
* **Python 3.x**
* **PyQt5**

필요한 패키지를 설치하려면 아래 명령어를 사용하세요:
```bash
pip install PyQt5
```

## 🚀 실행 가이드 (How to Run)
터미널에서 `admin_ui` 디렉토리로 이동한 후 `main.py`를 실행합니다.

```bash
# 디렉토리 이동
cd ui/desktop/admin_ui

# 어플리케이션 실행
python main.py
```