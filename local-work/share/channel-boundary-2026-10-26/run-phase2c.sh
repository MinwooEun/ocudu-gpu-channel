#!/bin/bash
# phase 2c: the synthetic radios on big cores (the A725 cores could not drive 61440-sample batches at 0.5 ms),
# broker on the other five big cores. 50 and 100 MHz boundary of the real broker.
until [ -f /workspace/gpuch/bound/oai-prof/done ]; do sleep 20; done; sleep 10
cd /workspace/gpuch/bound
v() { label=$1; n=$2; srate=$3; scs=$4; echo "P2c-$label-n$n $n $srate $scs 8 1 1 1" | env BIG=5-9 LITTLE=15-19 OCG_BROKER_SPIN=2 OCG_ZMQ_IO_THREADS=2 bash phase2.sh phase2c.csv "2c-$label"; }
for n in 1 2 4 6 8; do v 100 $n 122880000 30; done
for n in 4 8 12 16; do v 50 $n 61440000 15; done
v 20 16 23040000 15
v 20 8 23040000 15
echo DONE >> phase2c.log; touch phase2c.done
