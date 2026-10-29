#!/bin/bash
# phase 6 (continued): edge residual with 4 I/O threads; radios on the five big cores 15-19 (little cores cannot feed 25 ports)
cd /workspace/gpuch/bound
idle() { [ -z "$(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null)" ]; }
r() { label=$1; ues=$2; srate=$3; scs=$4; io=$5; spin=$6; shift 6; until idle; do echo "gpu busy: $(nvidia-smi --query-compute-apps=pid,process_name --format=csv,noheader | tr "\n" ";")"; sleep 20; done; echo "$label $ues $srate $scs $io tcp 0 0 $spin" | env "$@" bash phase4.sh phase6.csv phase6; }
{
r R-24-io4-broker15        24 23040000 15 4 0 BIG=0-14 LITTLE=15-19
r R-24-io4-spin2           24 23040000 15 4 2 BIG=5-14 LITTLE=15-19
r R-24-io4-base2           24 23040000 15 4 0 BIG=5-14 LITTLE=15-19
r R-20-io4                 20 23040000 15 4 0 BIG=5-14 LITTLE=15-19
r R-28-io4                 28 23040000 15 4 0 BIG=5-14 LITTLE=15-19
r R-32-io4                 32 23040000 15 4 0 BIG=5-14 LITTLE=15-19
r R-50-8-io4               8 61440000 15 4 0 BIG=5-14 LITTLE=15-19
r R-50-12-io4-b            12 61440000 15 4 0 BIG=5-14 LITTLE=15-19
r R-100-4-io4-b            4 122880000 30 4 0 BIG=5-14 LITTLE=15-19
r R-100-6-io4              6 122880000 30 4 0 BIG=5-14 LITTLE=15-19
} >> phase6.log 2>&1
echo DONE >> phase6.log; touch phase6.done
