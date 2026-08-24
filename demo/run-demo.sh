#!/usr/bin/env bash
# MIMO live demo -- one-command bring-up of the whole synthetic stack on the
# 5090 box. Intended to be run inside tmux; Ctrl-C tears everything down.
#
#   ./run-demo.sh [duration-seconds] [--classic]     (default 7200)
#
# Default TX mode is pilot alternation (pilot_source.py) so the |H| heatmap
# is measured (plan L2). --classic switches back to the C++ always-on tone
# sources (ocudu-zmq-source); the page then falls back to the declared-R view.
#
# Stack (plan section 2): 4x ocudu-zmq-source -> broker (CUDA, control :5559,
# telemetry :5560) -> power meter (C1) -> bridge+page on :8080 (C2/C3).
# Only 8080 needs to be reachable from the demo laptop.
set -euo pipefail

duration="${1:-7200}"
mode="pilot"
[[ "${2:-}" == "--classic" ]] && mode="classic"
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
bin="${repo}/build-cuda"
demo="${repo}/demo"
logs="${demo}/run-logs"
py="${PYTHON:-python3}"

"$py" -c 'import zmq, numpy' 2>/dev/null \
  || { echo "ERROR: ${py} needs pyzmq and numpy (pip install pyzmq numpy)"; exit 1; }
[[ -x "${bin}/ocudu-gpu-channel" ]] \
  || { echo "ERROR: ${bin}/ocudu-gpu-channel missing -- build build-cuda first"; exit 1; }

for p in 5559 5560 5561 8080 16200 16201 16202 16203 16204 16205 16206 16207; do
  if ss -ltn 2>/dev/null | grep -q ":${p}\b"; then
    echo "ERROR: port ${p} already in use"; exit 1
  fi
done

mkdir -p "${logs}"
pids=()
cleanup() { echo; echo "stopping demo stack"; kill "${pids[@]}" 2>/dev/null || true; wait 2>/dev/null || true; }
trap cleanup EXIT INT TERM

if [[ "${mode}" == "pilot" ]]; then
  echo "== pilot source (TX alternation: both/tx0/tx1/silence = 250/250/250/150 ms) =="
  "$py" "${demo}/pilot_source.py" \
    --port 0=tcp://*:16200 --port 1=tcp://*:16202 \
    --port 0=tcp://*:16204 --port 1=tcp://*:16206 \
    --duration "${duration}" >"${logs}/src_pilot.log" 2>&1 &
  pids+=($!)
else
  echo "== sources (4x always-on unit-power tone) =="
  for p in 16200 16202 16204 16206; do
    "${bin}/ocudu-zmq-source" --endpoint "tcp://*:${p}" --batch-samples 23040 \
      --duration "${duration}s" >"${logs}/src_${p}.log" 2>&1 &
    pids+=($!)
  done
fi

echo "== broker (CUDA, control :5559, telemetry :5560 @10 Hz) =="
"${bin}/ocudu-gpu-channel" --config "${demo}/topology.demo-mimo-2x2.cuda.yaml" \
  --duration "${duration}s" \
  --control-endpoint "tcp://*:5559" \
  --telemetry-endpoint "tcp://*:5560" --telemetry-rate-hz 10 \
  >"${logs}/broker.log" 2>&1 &
broker_pid=$!
pids+=("${broker_pid}")
sleep 1
grep -q "event=start" "${logs}/broker.log" \
  || { cat "${logs}/broker.log"; echo "ERROR: broker did not start"; exit 1; }

echo "== power meter (C1 -> :5561, mode=${mode}) =="
meter_args=()
[[ "${mode}" == "pilot" ]] && meter_args=(--pilot 250,250,250,150)
"$py" "${demo}/power_meter.py" \
  --port gnb_rx0=tcp://127.0.0.1:16201 --port gnb_rx1=tcp://127.0.0.1:16203 \
  --port ue_rx0=tcp://127.0.0.1:16205 --port ue_rx1=tcp://127.0.0.1:16207 \
  --push tcp://127.0.0.1:5561 "${meter_args[@]}" >"${logs}/meter.log" 2>&1 &
pids+=($!)

echo "== bridge + page (C2/C3) on :8080 =="
"$py" "${demo}/bridge.py" --http-port 8080 >"${logs}/bridge.log" 2>&1 &
pids+=($!)
sleep 1

ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo
echo "demo up: open  http://${ip:-<this-box>}:8080  on the laptop"
echo "logs: ${logs}/   scripted sweep: ${py} ${demo}/driver.py sweep"
echo "Ctrl-C stops everything."
# Follow the broker: when its duration expires (or it dies), tear down the
# meter/bridge too instead of leaving them holding 5561/8080.
wait "${broker_pid}"
