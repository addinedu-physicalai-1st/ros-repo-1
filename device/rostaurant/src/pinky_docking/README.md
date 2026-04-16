# pinky_docking

Pinky 로봇이 **ArUco 마커를 탐지 → Nav2 자율주행 → 정밀 도킹**으로 자동 주차하는 ROS 2 패키지.

---

## 홈 디렉토리 구조

```
~/
├── pinkylib/           ← 원본 라이브러리 (참조용)
├── pinky_pro/          ← 공식 pinky ROS2 패키지
└── pinky_docking/      ← 이 패키지
```

## 패키지 구조

```
pinky_docking/
├── pinky_docking/
│   ├── parking_node.py       # Nav2 자율주차 (메인)
│   ├── docking_node.py       # 구 직접 트래킹 (하위호환)
│   └── pinkylib/
│       ├── camera.py
│       └── motor.py
├── launch/
│   ├── pinky_parking.launch.py   # 자율주차
│   └── pinky_docking.launch.py   # 구 트래킹
└── ...
```

---

## 동작 흐름

```
[IDLE]
  │ start
  ▼
[SCANNING] ── 카메라로 ArUco 탐지
  │            카메라 좌표 → map TF 변환
  │            Nav2 목표점 계산 (마커 앞 nav_goal_dist_m)
  ▼
[NAVIGATING] ── Nav2 BasicNavigator.goToPose()
  │              자율주행
  ▼
[DOCKING] ── 정밀 도킹 (ρ/θ 제어)
  │           ① |θ| > theta_thresh → 제자리 회전 (kp_theta × θ)
  │           ② |θ| ≤ theta_thresh → 직진 (kp_rho × ρ)
  ▼
[PARKED] ── ρ ≤ parking_dist_cm 달성
```

## ρ/θ 제어 (경로 휨 없음)

```
x_cm, z_cm = 카메라 pose (x=좌우, z=전방)

ρ = √(x² + z²)      ← 실제 직선 거리
θ = atan2(x, z)     ← 마커 방향각

① θ 정렬 단계 (|θ| > threshold):
   left  =  kp_theta × θ
   right = -kp_theta × θ   (제자리 회전)

② ρ 전진 단계 (|θ| ≤ threshold):
   left = right = kp_rho × (ρ - parking_dist_cm)
```

---

## 빌드

```bash
cd ~/pinky_docking       # 또는 워크스페이스 src에 복사 후
# 워크스페이스에서:
colcon build --packages-select pinky_docking --symlink-install
source install/setup.bash
```

---

## 실행 순서

```bash
# 1. 로봇 bringup (이미 실행 중이면 스킵)
ros2 launch pinky_bringup bringup_robot.launch.xml

# 2. Nav2 + 맵 (이미 실행 중이면 스킵)
ros2 launch pinky_navigation bringup_launch.xml map:=<맵이름>

# 3. 주차 노드 실행
ros2 launch pinky_docking pinky_parking.launch.py \
    calib_path:=/home/pinky/camera_calibration.npz \
    target_id:=0
```

---

## 제어

```bash
# 주차 시작
ros2 service call /docking/start std_srvs/SetBool "{data: true}"
ros2 topic pub /docking/cmd std_msgs/String "data: 'start'" --once

# 주차 정지
ros2 service call /docking/start std_srvs/SetBool "{data: false}"

# 상태 확인 (IDLE/SCANNING/NAVIGATING/DOCKING/PARKED/ERROR)
ros2 topic echo /docking/status

# 디버그 이미지
ros2 run rqt_image_view rqt_image_view /docking/image
```

---

## 파라미터

| 파라미터 | 기본값 | 설명 |
|---|---|---|
| `target_id` | `0` | ArUco 마커 ID |
| `parking_dist_cm` | `30.0` | 최종 정차 거리 (cm) |
| `nav_goal_dist_m` | `0.5` | Nav2 목표점: 마커 앞 거리 (m) |
| `max_speed` | `35.0` | 정밀 도킹 최대 속도 |
| `kp_rho` | `1.2` | 전진 P 게인 |
| `kp_theta` | `50.0` | 회전 P 게인 |
| `theta_thresh_deg` | `5.0` | 전진 시작 각도 임계값 (deg) |
| `marker_size_m` | `0.05` | ArUco 마커 크기 (m) |
| `calib_path` | `""` | 캘리브레이션 파일 경로 |
| `camera_frame` | `camera_link` | 카메라 TF 프레임 |
| `robot_base_frame` | `base_link` | 로봇 베이스 TF 프레임 |
| `nav2_timeout_sec` | `30.0` | Nav2 타임아웃 (초) |

---

## 주의사항

- `camera_link` TF가 URDF/SLAM에 정의되어 있어야 합니다
- Nav2와 SLAM Toolbox가 먼저 실행되어 있어야 합니다
- 캘리브레이션 파일 없이는 pose 정확도가 낮습니다
