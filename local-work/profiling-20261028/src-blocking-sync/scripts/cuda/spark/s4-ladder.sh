#!/usr/bin/env bash
# S4 staged ladder on the Spark: each stage once, 60 s traffic, backend verdict per stage.
# Also the J4 ladder on the Jetson: PLATFORM_ROOT, SPARK_LOCK, ATTACH_SECONDS pass
# through to live-direct-zmq.sh; OCUDU_NATIVE_CUDA_GRID_MODE=auto|pinned|managed
# overrides the grid policy in the render (recorded in the output header).
L=/workspace/ocudu-cuda-rebuild/scripts/cuda/spark/live-direct-zmq.sh
root="${PLATFORM_ROOT:-/workspace/ocudu-spark}"
out=$root/results/s4-ladder-$(date -u +%Y%m%dT%H%M%SZ).txt
echo "gpu_others_at_start=$(nvidia-smi --query-compute-apps=pid --format=csv,noheader | wc -l) grid_mode=${OCUDU_NATIVE_CUDA_GRID_MODE:-policy} lock=${SPARK_LOCK:-default}" > "$out"
for st in low-phy-rx low-phy-tx pusch pdsch prach; do
  c=$(bash $L $st 60)
  d=$(ls -td $root/results/cuda-rebuild/direct-zmq-* | head -1)
  python3 - "$st" "$c" "$d" >> "$out" <<'PY'
import json,re,sys
st,c,d=sys.argv[1:]
res=open(c).read(); r=re.search(r"^result=(\w+).*keepalive_replies=(\d+).*gnb_start_s=(\d+)",res,re.M)
b=json.load(open(d+"/backends.json")) if __import__("os").path.exists(d+"/backends.json") else {}
k=re.search(r'"bler_pct": ([0-9.]+)',res); n=re.search(r'"transmissions": (\d+)',res); sn=re.search(r'"p50_db": ([-0-9.]+)',res)
tx=set()
for l in open(d+"/logs/gnb-internal.log",errors="ignore"):
    if "Lower-PHY TX GPU path selected" in l: tx.add("direct" if "direct" in l else "staging")
print(f"{st:11s} result={r.group(1) if r else '?'} keepalive={r.group(2) if r else '?'} start_s={r.group(3) if r else '?'} pusch={n.group(1) if n else '?'} bler={k.group(1) if k else '?'}% sinr_p50={sn.group(1) if sn else '?'} selected={b.get('selected')} degraded={b.get('degraded')} host_fallback={b.get('host_fallback')} verdict={b.get('verdict')} lowphy_tx={sorted(tx)} run={d.split('/')[-1]}")
PY
  tail -1 "$out"
done
echo S4_DONE >> "$out"
