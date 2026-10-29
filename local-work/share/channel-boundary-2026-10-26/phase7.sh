#!/bin/bash
# phase 7: channel-only boundary vs antenna count (gNB ports x UE ports), real broker + synthetic radios, recipe knobs
# (I/O threads 2, spin 2 up to 20 ports else blocking, radios on big cores 15-19, broker on 5-14). Also samples the
# radios' CPU mid-run so the radio side can be ruled in or out.
# stdin: "label ues srate scs gnbp uep"; usage: phase7.sh <out.csv> <phase>
BD=/workspace/ocudu-spark-ranb/builds/ocudu-gpu-channel-single-cell; W=/workspace/gpuch/bound; out=$1; phase=$2
DUR=${DUR:-20}; BIG=${BIG:-5-14}; LITTLE=${LITTLE:-15-19}; IO=${IO:-2}
[ -f $out ] || echo "phase,label,ues,srate_hz,scs_khz,gnb_ports,ue_ports,ports,rx_rows,spin,sink_ratio_min,sink_ratio_mean,sink_ratio_max,rx_starvations,broker_rc,broker_cpu_pct,src_cpu_pct_sum,sink_cpu_pct_sum,room_us,data_us,process_us,throttle_us" > $out
while read -r label ues srate scs gnbp uep; do
  [ -z "$label" ] && continue; case $label in \#*) continue;; esac
  d=$W/p7-$label; rm -rf $d; mkdir -p $d; y=$d/topo.yaml; slot_us=$(python3 -c "print(int(1000*15/$scs))")
  python3 $W/gen.py --ues $ues --srate-hz $srate --scs-khz $scs --taps 8 --gnb-ports $gnbp --ue-ports $uep --base-port 20000 --out $y > $d/gen.log || { echo GEN_FAIL $label; continue; }
  nports=$(awk '/ports/{print $3}' $d/gen.log); batch=$(awk '{print $7}' $d/gen.log); rows=$nports
  spin=${SPIN:-0}
  echo "== $label start=$(date -u +%T) ues=$ues srate=$srate ports=$gnbp/$uep nports=$nports spin=$spin"
  pids=(); spids=(); for i in $(seq 0 $((nports-1))); do taskset -c $LITTLE $BD/ocudu-zmq-source --endpoint tcp://*:$((20000+2*i)) --batch-samples $batch --duration $((DUR+6))s > $d/src-$i.log 2>&1 & pids+=($!); spids+=($!); done
  sleep 1
  for try in 1 2 3; do
    OCG_BROKER_SPIN=$spin OCG_ZMQ_IO_THREADS=$IO taskset -c $BIG $BD/ocudu-gpu-channel --config $y --duration $((DUR+4))s > $d/broker.log 2>&1 & bpid=$!
    sleep 2; grep -q "event=fatal" $d/broker.log || break
    echo "   broker start failed (try $try): $(grep -m1 -o 'error=.*' $d/broker.log | cut -c1-120)"; wait $bpid; sleep 5
  done
  kpids=(); for i in $(seq 0 $((nports-1))); do taskset -c $LITTLE $BD/ocudu-zmq-sink --endpoint tcp://127.0.0.1:$((20001+2*i)) --duration ${DUR}s --request-interval-us $slot_us > $d/sink-$i.log 2>&1 & pids+=($!); kpids+=($!); done
  sleep $((DUR/2)); bcpu=$(ps -o %cpu= -p $bpid | tr -d ' ')
  scpu=$(ps -o %cpu= -p $(IFS=,; echo "${spids[*]}") 2>/dev/null | awk '{s+=$1} END{printf "%.0f", s}'); kcpu=$(ps -o %cpu= -p $(IFS=,; echo "${kpids[*]}") 2>/dev/null | awk '{s+=$1} END{printf "%.0f", s}')
  wait $bpid; brc=$?; for q in "${pids[@]}"; do wait $q 2>/dev/null; done
  read -r rmin rmean rmax < <(python3 - "$d" "$srate" "$DUR" <<'PY'
import sys,glob,re
d,srate,dur=sys.argv[1],float(sys.argv[2]),float(sys.argv[3]); r=[]
for f in sorted(glob.glob(d+"/sink-*.log")):
    m=re.search(r"samples_received=(\d+)",open(f).read()); r.append(int(m.group(1))/(srate*dur) if m else 0.0)
print(f"{min(r):.4f} {sum(r)/len(r):.4f} {max(r):.4f}" if r else "0 0 0")
PY
)
  starv=$(grep -m1 "event=stop" $d/broker.log | grep -o "rx_starvations=[0-9]*" | cut -d= -f2)
  st=$(python3 $W/stagestat.py $d/broker.log | tail -1 | awk '{print $3","$5","$7","$8}')
  echo "   sink min/mean/max=$rmin/$rmean/$rmax starv=$starv brc=$brc broker_cpu=$bcpu% src_cpu=$scpu% sink_cpu=$kcpu% stages[room,data,process,throttle]=$st $(grep -m1 -o 'error=.*' $d/broker.log | cut -c1-100)"
  echo "$phase,$label,$ues,$srate,$scs,$gnbp,$uep,$nports,$rows,$spin,$rmin,$rmean,$rmax,$starv,$brc,$bcpu,$scpu,$kcpu,$st" >> $out
  pkill -f "ocudu-zmq-source --endpoint" 2>/dev/null; pkill -f "ocudu-zmq-sink --endpoint" 2>/dev/null; sleep 2
done
