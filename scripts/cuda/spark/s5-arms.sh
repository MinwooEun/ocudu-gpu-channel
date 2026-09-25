#!/usr/bin/env bash
# S5 on the Spark: CPU OCUDU gNB vs CUDA gNB (acceleration disabled, all), live
# direct ZMQ, interleaved so slow drift hits every arm alike, then the matched-
# allocation comparison (s5-compare-arms.py) against the CPU gNB.
#
#   bash s5-arms.sh [repeats=3] [traffic_seconds=60]
#   S5_ARMS="cpu all"   subset of arms (default "cpu disabled all"); cpu is always the reference
#   SPARK_LOCK=... PLATFORM_ROOT=...   CUDA build and work root (see live-direct-zmq.sh)
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
reps="${1:-3}"; traffic="${2:-60}"
arms=(${S5_ARMS:-cpu disabled all})
out=${PLATFORM_ROOT:-/workspace/ocudu-spark}/results/s5-arms-$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$out"
echo "arms=${arms[*]} lock=${SPARK_LOCK:-default}" | tee "$out/runs.txt"
declare -A dirs=()
for i in $(seq 1 "$reps"); do
  for arm in "${arms[@]}"; do
    others=$(nvidia-smi --query-compute-apps=pid --format=csv,noheader | wc -l)
    c=$(bash "$here/live-direct-zmq.sh" "$arm" "$traffic"); rc=$?
    d=$(sed -n 's/.*out=\(\S*direct-zmq-\S*\).*/\1/p' "$c" | head -1)
    echo "rep=$i arm=$arm rc=$rc gpu_others_at_start=$others $(grep -m1 '^result=' "$c" | cut -d' ' -f1-8) run=$d" | tee -a "$out/runs.txt"
    [[ $rc -eq 0 && -n "$d" ]] && dirs[$arm]+="${dirs[$arm]:+,}$d"
  done
done
args=(); for arm in "${arms[@]}"; do args+=("$arm=${dirs[$arm]:-}"); done
python3 "$here/s5-compare-arms.py" --ref cpu --json "$out/compare.json" "${args[@]}" | tee "$out/compare.txt"
echo "S5_COMPARE_EXIT=${PIPESTATUS[0]}" | tee -a "$out/compare.txt"
echo "s5_evidence=$out"
