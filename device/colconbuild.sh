#!/bin/bash
set -e

colcon build --symlink-install \
  --cmake-args \
  -DPython3_EXECUTABLE=$(which python)
