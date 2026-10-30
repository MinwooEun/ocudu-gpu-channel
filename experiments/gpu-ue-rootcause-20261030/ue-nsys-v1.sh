#!/usr/bin/env bash
set -eu
ue_binary=/workspace/gpuch/s4/build-s1/srsue/src/srsue
if [[ ${SRSUE_PRACH_PREAMBLE_INDEX:-unset} != 0 ]]; then
  exec "$ue_binary" "$@"
fi
ue_mask=$(sed -n 's/^Cpus_allowed_list:[[:space:]]*//p' /proc/self/status)
mkdir -p "${OCG_UE_NSYS_OUTPUT}/trace"
export SRSUE_SLOT_TRACE_DIR="${OCG_UE_NSYS_OUTPUT}/trace"
setsid taskset -c 0-4 /usr/local/cuda/bin/nsys profile \
  --trace=cuda,osrt --sample=none --cpuctxsw=none --osrt-threshold=1000 \
  --delay=40 --duration=6 --kill=none --wait=primary \
  -o "${OCG_UE_NSYS_OUTPUT}/timeline" \
  taskset -c "$ue_mask" "$ue_binary" "$@" &
profile_pid=$!
printf '%s\n' "$profile_pid" > "${OCG_UE_NSYS_OUTPUT}/profiler.pid"
stop_profile() {
  trap '' TERM INT
  kill -INT -- "-$profile_pid" 2>/dev/null || true
  wait "$profile_pid" || true
  exit 0
}
trap stop_profile TERM INT
wait "$profile_pid"
