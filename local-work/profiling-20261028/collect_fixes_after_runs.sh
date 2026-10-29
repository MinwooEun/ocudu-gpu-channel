#!/usr/bin/env bash
set -euo pipefail
lab=/workspace/gpuch/profile-20261028
while pgrep -f '^python3 /tmp/ocg-check-live-fixes.py baseline-repeat ue5big-spin-repeat$' >/dev/null; do
  sleep 3
done
ctest --test-dir "$lab/build-blocking-sync" \
  -R '^(processing|runtime_update_parity|matrix_profile_history|broker)$' \
  --output-on-failure > "$lab/blocking-sync-default-validation.log" 2>&1
python3 /tmp/ocg-summarize-live-fixes.py > "$lab/fixes-final-summary.log"
nvidia-smi --query-compute-apps=pid,process_name --format=csv > "$lab/fixes-gpu-final.csv"
cp /tmp/ocg-blocking-config.log /tmp/ocg-blocking-build2.log "$lab/"
taskset -c 0-4 tar -I 'gzip -1' -C "$lab" -cf - \
  fixes live-fixes-summary.json blocking-sync-default-validation.log \
  fixes-final-summary.log fixes-gpu-final.csv \
  ocg-blocking-config.log ocg-blocking-build2.log
