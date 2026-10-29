#!/usr/bin/env bash
# S15: one line per run dir: tag, gate summary (rt_factor, NACK, DL Mb/s, health),
# broker p50/p99 per node, and the critical-path split from the hop trace
# (broker share per direction p50, device turnaround p50, cycle mean).
# usage: s15-summary.sh <runs-dir-glob...>   (hop traces under ../hop/<tag>)
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
for d in "$@"; do
  tag=$(basename "$d" | sed 's/-[0-9]\{6\}$//')
  g=$(grep -o "rt_factor=[0-9.]* \|nack_ratio=[0-9.]*\|dl_rx_mbps=[0-9.]*\|health=[a-z]*" "$d/gate.log" | tr '\n' ' ')
  run=$(grep -o "oai-2x2/[0-9TZ]*" "$d/meta.txt" | head -1)
  L=/workspace/ocudu-spark/results/logs/$run/broker.log
  p=$(grep -o "event=process_latency_summary node=[a-z0-9]* n=[0-9]* p50_us=[0-9]* p95_us=[0-9]* p99_us=[0-9]*" "$L" 2>/dev/null | awk '{print $2"/"$4"/"$6}' | tr '\n' ' ')
  h="$(dirname "$d")/../hop/$tag/hop-trace.csv"
  cp=""
  if [[ -f "$h" ]]; then
    cp=$(python3 "$here/s15-critical-path.py" "$h" 10 | awk '
      /^== DL/ {dir="DL"} /^== UL/ {dir="UL"} /^== gnb0/ {dir="gnb0"} /^== ue0/ {dir="ue0"}
      $1=="broker" {for(i=1;i<=NF;i++) if($i ~ /^p50=/) printf "%s.broker_p50=%s ", dir, substr($i,5)}
      $1=="turnaround" {for(i=1;i<=NF;i++) if($i ~ /^p50=/) printf "%s.turn_p50=%s ", dir, substr($i,5)}
      $1=="cycle" {for(i=1;i<=NF;i++) if($i ~ /^mean=/) printf "%s.cycle_mean=%s ", dir, substr($i,6)}')
  fi
  echo "$tag $g $p $cp"
done
