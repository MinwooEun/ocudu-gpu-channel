#!/bin/bash
set -eu
mkdir -p "${OCG_CAPTURE_TARGET}"
exec /workspace/gpuch/profile-20261028/build/ocudu-gpu-channel "$@" --wire-capture-dir "${OCG_CAPTURE_TARGET}" --wire-capture-skip 650000000 --wire-capture-samples 250000000
