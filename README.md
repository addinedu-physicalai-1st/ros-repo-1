# Smart Buffet Robot Control System

ROS 기반 뷔페 서빙 및 안내 로봇을 위한 웹 제어 시스템 (Web Control System) 및 UI 저장소입니다.

## 📌 주요 기능 (Features)
- **테이블 고객용 UI (`ui/web/table_ui`):** 
  - 화장실 로봇 안내 및 지도 확인
  - 메뉴 안내 (로봇 동행)
  - 다 먹은 식기 수거 요청 / 로봇 교대 요청
  - 직원 호출
- **관리자용 대시보드 UI (`ui/web/buffet_admin_ui`):**
  - 메뉴 및 위치(장소) 관리
  - 로봇 상태 모니터링 및 제어 (ROS 연동)
- **Backend 서버 (`server/web/index.js`):**
  - Node.js (Express) 및 SQLite 채택
  - 클라이언트 간 통신, 데이터베이스 연동 지원, JWT 기반 관리자 인증

## 📂 프로젝트 구조 (Directory Structure)
```
ros-repo-1/
├── server/
│   └── web/              # 백엔드 서버
│       ├── data/         # SQLite DB 저장 공간 (실행 시 생성됨)
│       ├── index.js      # Express 메인 라우터 및 로직
│       └── package.json  # 의존성 패키지 관리
├── ui/
│   └── web/              # 프론트엔드 UI
│       ├── buffet_admin_ui/  # 관리자용 통합 대시보드
│       ├── table_ui/         # 각 테이블용 태블릿 UI
│       └── kiosk_ui/         # 키오스크 관련 UI 
├── device/               # 로봇 디바이스 및 하드웨어 연동 관련 스크립트
└── README.md             # 프로젝트 소개
```

## 🚀 실행 방법 (Getting Started)

### 사전 요구사항 (Prerequisites)
- [Node.js](https://nodejs.org/ko/) v18 이상

### 서버 및 UI 실행
1. 레포지토리 클론 및 폴더 이동
```bash
git clone <repository-url>
cd ros-repo-1/server/web
```
2. 패키지 설치
```bash
npm install
```
3. 서버 실행
```bash
npm start
```
4. 접속 확인 (기본 포트: `5050`)
- **관리자 UI:** [http://localhost:5050/ui/buffet_admin_ui/buffet_admin.html](http://localhost:5050/ui/buffet_admin_ui/buffet_admin.html)
- **테이블 UI:** [http://localhost:5050/ui/table_ui/table_service.html?table=3](http://localhost:5050/ui/table_ui/table_service.html?table=3)

## 🛠️ 기술 스택 (Tech Stack)
- **Frontend:** HTML5, CSS3, Vanilla JavaScript 
- **Backend:** Node.js, Express.js
- **Database:** SQLite (better-sqlite3)
- **Auth:** JWT (jsonwebtoken), bcrypt
- **Robotics:** ROS (차후 시스템 통합)
