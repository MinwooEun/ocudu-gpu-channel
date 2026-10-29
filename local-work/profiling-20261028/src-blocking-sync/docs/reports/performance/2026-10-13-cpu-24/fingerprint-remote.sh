#!/usr/bin/env bash
set -euo pipefail
source scripts/remote/common.sh
case "$REMOTE_BUILDS_ROOT" in '~/'*) fetch_root="${REMOTE_BUILDS_ROOT#\~/}";;*)fetch_root="$REMOTE_BUILDS_ROOT";;esac
rsync -az -e "ssh -i $REMOTE_SSH_KEY -o BatchMode=yes -o ConnectTimeout=8" tmp/cpu-24/baseline_probe.cpp "$REMOTE_USER@$REMOTE_HOST:$fetch_root/cpu-24-20261013/"
remote_sh bash -s -- "$REMOTE_WORKSPACE" "$REMOTE_BUILDS_ROOT" <<'REMOTE'
set -euo pipefail
expand(){ case "$1" in '~/'*)printf '%s/%s\n' "$HOME" "${1#\~/}";;*)printf '%s\n' "$1";;esac; }
work=$(expand "$1");root=$(expand "$2");task="$root/cpu-24-20261013";old="$root/slides-page10-20261013"
source "$work/tools/env.sh"
cat "$task/build/CMakeFiles/test_cpu_parallel.dir/link.txt"
c++ -std=c++20 -O3 -DNDEBUG -I "$old/source/include" "$task/baseline_probe.cpp" "$old/build/libocudu_gpu_channel_lib.a" -L "$work/tools/cuda-12.8.1/lib64" -lcudart -L "$work/tools/zeromq-4.3.5/lib" -Wl,-rpath,"$work/tools/zeromq-4.3.5/lib" -lzmq -pthread -o "$task/baseline_probe"
"$task/baseline_probe" > "$task/baseline-fingerprint.txt"
"$task/build/test_cpu_parallel" > "$task/current-fingerprint.txt"
diff "$task/baseline-fingerprint.txt" "$task/current-fingerprint.txt"
cat "$task/current-fingerprint.txt"
REMOTE
