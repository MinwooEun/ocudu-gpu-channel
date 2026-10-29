#!/bin/bash
# channel boundary sweep with ocudu-gpu-channel-bench (live cadence: pace + fresh inputs + one thread per RX node)
# usage: sweep.sh <outfile.csv> <phase> ; phase lines come from stdin: "label ues srate scs taps gnbp uep cells"
B=/workspace/ocudu-spark-ranb/builds/ocudu-gpu-channel-single-cell/ocudu-gpu-channel-bench
W=/workspace/gpuch/bound; out=$1; phase=$2; dur=${DUR:-10s}
[ -f $out ] || echo "phase,label,ues,srate_hz,scs_khz,taps,gnb_ports,ue_ports,cells,links,metric,count,p50_us,p95_us,p99_us,p999_us,max_us,slot_us,gate,backend,zero_copy" > $out
while read -r label ues srate scs taps gnbp uep cells; do
  [ -z "$label" ] && continue; case $label in \#*) continue;; esac
  y=$W/topo-$label.yaml
  python3 $W/gen.py --ues $ues --srate-hz $srate --scs-khz $scs --taps $taps --gnb-ports $gnbp --ue-ports $uep --cells $cells --out $y > $W/gen-$label.log || { echo "GEN_FAIL $label"; continue; }
  links=$((2*ues*cells))
  echo "== $label start=$(date -u +%T) ues=$ues srate=$srate scs=$scs taps=$taps ports=$gnbp/$uep cells=$cells"
  OCG_BENCH_PACE=1 OCG_BENCH_REFRESH=1 OCG_BENCH_THREADS=1 timeout 120 $B --config $y --duration $dur --scs-khz $scs > $W/bench-$label.out 2> $W/bench-$label.err
  rc=$?; echo "   rc=$rc $(grep -m1 model_mix_latency $W/bench-$label.out) $(grep -m1 kernel_us $W/bench-$label.out)"
  be=$(grep -m1 '^backend,' $W/bench-$label.out | cut -d, -f2); zc=$(grep -m1 '^cuda_zero_copy,' $W/bench-$label.out | cut -d, -f2)
  grep -E '^(model_mix_latency|h2d_us|kernel_us|d2h_us|gpu_process_us|call_us|host_prep_us|host_out_us),' $W/bench-$label.out | while IFS= read -r row; do
    echo "$phase,$label,$ues,$srate,$scs,$taps,$gnbp,$uep,$cells,$links,$row,$be,$zc" >> $out; done
  [ $rc -ne 0 ] && { echo "   rc=$rc $(tail -2 $W/bench-$label.err | tr '\n' ' ')"; echo "$phase,$label,$ues,$srate,$scs,$taps,$gnbp,$uep,$cells,$links,ERROR,$rc,,,,,,,,," >> $out; }
done
