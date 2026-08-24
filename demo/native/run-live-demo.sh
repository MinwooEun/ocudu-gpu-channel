#!/usr/bin/env bash
set -euo pipefail

# LIVE-RADIO demo tier (plan S5): real Open5GS + OCUDU gNB + srsUE attached
# through the CUDA broker, with the web page on :8082.
#
#   ./run-live-demo.sh [duration-seconds] [--mode 2x1|4x1]   (default 7200, 2x1)
#
#   2x1 -- 2T2R gNB, DL 2x1 MISO / UL 1x2 SIMO (rank-1 R2 stack)
#   4x1 -- 4T4R gNB, DL 4x1 MISO / UL 1x4 SIMO (rank-1 R3 stack)
#
# Reuses the rank-1 2x1 gate's builds and config renderer, then applies the
# demo deltas: the topology gains a path_loss step per model + ipc control/
# telemetry endpoints, srsUE writes metrics CSV, and a host-side tailer +
# bridge serve the page. Runs alongside the synthetic demos (:8080/:8081).
# Intended for tmux; Ctrl-C tears the whole tree down (unshare --kill-child).

duration="${1:-7200}"
mode="2x1"
[[ "${2:-}" == "--mode" && -n "${3:-}" ]] && mode="$3"
[[ "${mode}" == "2x1" || "${mode}" == "4x1" ]] || { echo "error: --mode must be 2x1 or 4x1" >&2; exit 2; }
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"
demo="${repo_root}/demo"
# Sysroot library paths (libtalloc & friends for Open5GS) travel to the inner
# stack via the environment, which unshare preserves.
# shellcheck source=../../scripts/native/env.sh
source "${repo_root}/scripts/native/env.sh"
native_root="${OCUDU_NATIVE_ROOT:-/home/ubuntu/ocudu-native-workspace}"
physical_gpu="${OCUDU_NATIVE_GPU_DEVICE:-0}"
renderer="${repo_root}/scripts/native/render-rank1-${mode}-configs.py"
demo_topology="${script_dir}/topology.live-rank1-${mode}.cuda.yaml"
if [[ "${mode}" == "4x1" ]]; then
  dl_link="gnb0>ue0:dl_miso_4x1"; ul_link="ue0>gnb0:ul_simo_1x4"
else
  dl_link="gnb0>ue0:dl_miso_2x1"; ul_link="ue0>gnb0:ul_simo_1x2"
fi
inner="${script_dir}/run-live-demo-inner.sh"
py="${PYTHON:-python3}"

fail() { printf 'error: %s\n' "$1" >&2; exit 2; }

"$py" -c 'import zmq' 2>/dev/null || fail "${py} needs pyzmq"
# Whichever interpreter can import pymongo drives the subscriber insert.
python_mongo=""
for candidate in /usr/bin/python3 "$(command -v python3)"; do
  "${candidate}" -c 'import bson, pymongo' 2>/dev/null \
    && { python_mongo="${candidate}"; break; }
done
[[ -n "${python_mongo}" ]] || fail "no python3 with pymongo found (pip install pymongo)"
for command_name in unshare nsenter ip flock ss setsid stdbuf; do
  command -v "${command_name}" >/dev/null 2>&1 || fail "missing command: ${command_name}"
done
for path in "${renderer}" "${inner}" \
  "${native_root}/builds/ocudu-zmq-release/apps/gnb/gnb" \
  "${native_root}/builds/srsran4g-zmq-release/srsue/src/srsue" \
  "${native_root}/builds/open5gs-v2.7.6/tests/app/5gc" \
  "${native_root}/install/mongodb-6.0.29/bin/mongod" \
  "${native_root}/builds/ocudu-gpu-channel-rank1-cuda-release/ocudu-gpu-channel" \
  "${demo_topology}"; do
  [[ -e "${path}" ]] || fail "missing required path: ${path}"
done
[[ -c /dev/net/tun ]] || fail "/dev/net/tun is absent"
for p in 8082 5566; do
  ss -ltn 2>/dev/null | grep -q ":${p}\b" && fail "host port ${p} already in use"
done

# One live tier at a time (the RAN ports inside the netns never clash, but
# two brokers on one GPU device with real-time deadlines is asking for it).
lock_path="${demo}/run-logs/.live-demo.lock"
mkdir -p "$(dirname "${lock_path}")"
exec 9>"${lock_path}"
flock -n 9 || fail "another live demo is already running"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
run_dir="${demo}/run-logs/live-${timestamp}"
config_dir="${run_dir}/configs"
log_dir="${run_dir}/logs"
mkdir -p "${config_dir}" "${log_dir}"

echo "== render configs (rank-1 renderer + demo patches) =="
/usr/bin/python3 "${renderer}" --repo-root "${repo_root}" --native-root "${native_root}" \
  --output-dir "${config_dir}" --log-dir "${log_dir}" >"${log_dir}/render.log" 2>&1 \
  || { cat "${log_dir}/render.log"; fail "config render failed"; }
# Demo deltas: topology with path_loss steps; srsUE metrics CSV for the tailer.
cp "${demo_topology}" "${config_dir}/topology.yaml"
cat >>"${config_dir}/srsue.conf" <<EOF

[general]
metrics_csv_enable = true
metrics_period_secs = 0.5
metrics_csv_filename = ${log_dir}/ue_metrics.csv
# default is -1 (flush only at shutdown), which would starve the live tailer
metrics_csv_flush_period_sec = 1
EOF

pids=()
stack_pid=""
cleanup() {
  echo; echo "stopping live demo"
  # TERM the inner script (child of unshare), NOT the unshare wrapper: killing
  # unshare SIGKILLs the inner (--kill-child) before its trap can stop the
  # setsid'd process groups, which would orphan gNB/srsUE/core.
  if [[ -n "${stack_pid}" ]]; then
    local inner_pid
    inner_pid="$(pgrep -P "${stack_pid}" | head -1 || true)"
    [[ -n "${inner_pid}" ]] && kill -TERM "${inner_pid}" 2>/dev/null || true
    for _ in $(seq 1 100); do
      kill -0 "${stack_pid}" 2>/dev/null || break
      sleep 0.1
    done
  fi
  kill "${pids[@]}" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "== RAN stack in rootless namespaces (core + gNB + srsUE + broker) =="
netns_dir="${run_dir}/netns"
mkdir -p "${netns_dir}"
parent_netns="$(readlink /proc/self/ns/net)"
parent_mntns="$(readlink /proc/self/ns/mnt)"
unshare --user --map-root-user --net --mount --fork --kill-child --propagation private \
  "${inner}" --parent-netns "${parent_netns}" --parent-mntns "${parent_mntns}" \
  --outer-uid "$(id -u)" --netns-dir "${netns_dir}" --physical-gpu "${physical_gpu}" \
  --native-root "${native_root}" --repo-root "${repo_root}" \
  --config-dir "${config_dir}" --log-dir "${log_dir}" --duration "${duration}" \
  --python-mongo "${python_mongo}" \
  >"${log_dir}/inner-console.log" 2>&1 &
stack_pid=$!
pids+=("${stack_pid}")

echo "waiting for UE attach (this takes ~30-60 s: core, broker, gNB, srsUE)..."
for _ in $(seq 1 240); do
  kill -0 "${stack_pid}" 2>/dev/null || {
    tail -20 "${log_dir}/inner-console.log"
    fail "RAN stack exited during bring-up (logs: ${log_dir})"
  }
  grep -q 'event=live_demo_up' "${log_dir}/inner-console.log" 2>/dev/null && break
  sleep 0.5
done
grep -q 'event=live_demo_up' "${log_dir}/inner-console.log" || {
  tail -20 "${log_dir}/inner-console.log"
  fail "UE did not attach within the bring-up window (logs: ${log_dir})"
}
echo "UE attached: RRC connected, PDU session up, ping running"

echo "== metrics tailer -> :5566 =="
"$py" "${demo}/native/live_tailer.py" \
  --metrics-csv "${log_dir}/ue_metrics.csv" --ping-log "${log_dir}/ue-ping.log" \
  --srsue-log "${log_dir}/srsue.log" --status-json "${log_dir}/live-status.json" \
  --push tcp://127.0.0.1:5566 >"${log_dir}/tailer.log" 2>&1 &
pids+=($!)

echo "== bridge + page on :8082 =="
"$py" "${demo}/bridge.py" --http-port 8082 --page live.html \
  --telemetry "ipc://${config_dir}/telemetry.ipc" \
  --meter-bind tcp://127.0.0.1:5566 \
  --control "ipc://${config_dir}/control.ipc" \
  --links "${dl_link}" "${ul_link}" \
  >"${log_dir}/bridge.log" 2>&1 &
pids+=($!)
sleep 1

ip="$(ip -4 -o addr show scope global 2>/dev/null | awk '!/docker/{print $4}' | cut -d/ -f1 | head -1)"
echo
echo "live demo up: open  http://${ip:-<this-box>}:8082"
echo "logs: ${log_dir}/"
echo "Ctrl-C stops everything."
wait "${stack_pid}"
