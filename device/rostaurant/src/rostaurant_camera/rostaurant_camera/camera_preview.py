#!/usr/bin/env python3

# Copyright 2026 PinkLab
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
OpenCV로 V4L2 카메라 실시간 미리보기 (ROS 없이 단독 실행).

camera_node 와 동일한 기본 해상도(640×480)를 사용합니다.
camera_node 가 실행 중이면 동일 /dev/videoX 를 동시에 열 수 없을 수 있습니다.
"""

from __future__ import annotations

import argparse
import sys

import cv2

DEFAULT_CAMERA_INDEX = 2
FRAME_W = 640
FRAME_H = 360


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description='OpenCV 실시간 카메라 미리보기 (q 또는 Esc 로 종료)',
    )
    parser.add_argument(
        '--camera-index',
        type=int,
        default=DEFAULT_CAMERA_INDEX,
        help=f'VideoCapture 인덱스 (기본: {DEFAULT_CAMERA_INDEX})',
    )
    parser.add_argument(
        '--width',
        type=int,
        default=FRAME_W,
        help=f'요청 가로 픽셀 (기본: {FRAME_W})',
    )
    parser.add_argument(
        '--height',
        type=int,
        default=FRAME_H,
        help=f'요청 세로 픽셀 (기본: {FRAME_H})',
    )
    args = parser.parse_args(argv)

    cap = cv2.VideoCapture(args.camera_index)
    if not cap.isOpened():
        print(
            f'오류: 카메라 인덱스 {args.camera_index} 를 열 수 없습니다.',
            file=sys.stderr,
        )
        return 1

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, float(args.width))
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, float(args.height))
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    window = 'camera_preview'
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)

    try:
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                print('프레임 읽기 실패.', file=sys.stderr)
                break

            if frame.shape[1] != args.width or frame.shape[0] != args.height:
                frame = cv2.resize(frame, (args.width, args.height))

            cv2.imshow(window, frame)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord('q'), ord('Q'), 27):
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
