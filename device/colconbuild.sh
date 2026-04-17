#!/bin/bash
set -e

colcon build \
  --cmake-args \
  -DPython3_EXECUTABLE=$(which python)
