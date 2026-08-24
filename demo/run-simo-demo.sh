#!/usr/bin/env bash
# Rank-1 SIMO steering demo -- 1x4 fixed_mimo with a live re-steer button.
#
#   ./run-simo-demo.sh [duration-seconds]     (default 7200)
#
# Runs on its own ports (broker 163xx, control 5562, telemetry 5563, meter
# 5564, supervisor 5565, web 8081) so it can run ALONGSIDE the 2x2 demo
# (run-demo.sh, web 8080): open both tabs on the laptop. Ctrl-C tears down.
set -euo pipefail

duration="${1:-7200}"
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
bin="${repo}/build-cuda"
demo="${repo}/demo"
logs="${demo}/run-logs"
py="${PYTHON:-python3}"

"$py" -c 'import zmq, numpy' 2>/dev/null \
  || { echo "ERROR: ${py} needs pyzmq and numpy"; exit 1; }
[[ -x "${bin}/ocudu-gpu-channel" ]] \
  || { echo "ERROR: ${bin}/ocudu-gpu-channel missing"; exit 1; }

for p in 5562 5563 5564 5565 8081 16300 16301 16302 16303 16304 16305 16306 16307 16308 16309; do
  if ss -ltn 2>/dev/null | grep -q ":${p}\b"; then
    echo "ERROR: port ${p} already in use"; exit 1
  fi
done

mkdir -p "${logs}"
pids=()
cleanup() { echo; echo "stopping SIMO demo stack"; kill "${pids[@]}" 2>/dev/null || true; wait 2>/dev/null || true; }
trap cleanup EXIT INT TERM

echo "== sources (5x unit tone: 1 UE TX + 4 unused gNB TX) =="
for p in 16300 16302 16304 16306 16308; do
  "${bin}/ocudu-zmq-source" --endpoint "tcp://*:${p}" --batch-samples 23040 \
    --duration "${duration}s" >"${logs}/simo_src_${p}.log" 2>&1 &
  pids+=($!)
done

echo "== steering supervisor (owns the broker; REP :5565) =="
"$py" "${demo}/simo_supervisor.py" --broker "${bin}/ocudu-gpu-channel" \
  --rep tcp://127.0.0.1:5565 --control "tcp://*:5562" --telemetry "tcp://*:5563" \
  --duration "${duration}" >"${logs}/simo_supervisor.log" 2>&1 &
supervisor_pid=$!
pids+=("${supervisor_pid}")
sleep 2

echo "== power meter (gnb_rx0..3 -> :5564) =="
"$py" "${demo}/power_meter.py" \
  --port gnb_rx0=tcp://127.0.0.1:16303 --port gnb_rx1=tcp://127.0.0.1:16305 \
  --port gnb_rx2=tcp://127.0.0.1:16307 --port gnb_rx3=tcp://127.0.0.1:16309 \
  --push tcp://127.0.0.1:5564 >"${logs}/simo_meter.log" 2>&1 &
pids+=($!)

echo "== bridge + page on :8081 =="
"$py" "${demo}/bridge.py" --http-port 8081 --page simo.html \
  --telemetry tcp://127.0.0.1:5563 --meter-bind tcp://127.0.0.1:5564 \
  --control tcp://127.0.0.1:5562 --steering-rep tcp://127.0.0.1:5565 \
  >"${logs}/simo_bridge.log" 2>&1 &
pids+=($!)
sleep 1

ip="$(ip -4 -o addr show scope global 2>/dev/null | awk '!/docker/{print $4}' | cut -d/ -f1 | head -1)"
echo
echo "SIMO demo up: open  http://${ip:-<this-box>}:8081"
echo "logs: ${logs}/simo_*.log"
echo "Ctrl-C stops everything."
wait "${supervisor_pid}"
