#!/bin/bash
# broker-side boundary: separate CPU (ZMQ threads, wait policy, cores) from the GPU cap at 16/24/32 UEs, 20 MHz
cd /workspace/gpuch/bound
v() { label=$1; n=$2; shift 2; echo "P2b-$label-n$n $n 23040000 15 8 1 1 1" | env "$@" bash phase2.sh phase2b.csv "2b-$label"; }
for n in 16 24 32; do
  v spin2-10big $n OCG_BROKER_SPIN=2 OCG_ZMQ_IO_THREADS=2
  v spin0-10big $n OCG_BROKER_SPIN=0 OCG_ZMQ_IO_THREADS=2
  v spin1-10big $n OCG_BROKER_SPIN=1 OCG_ZMQ_IO_THREADS=2
  v spin2-20all $n OCG_BROKER_SPIN=2 OCG_ZMQ_IO_THREADS=2 BIG=0-19 LITTLE=0-19
  v spin0-20all $n OCG_BROKER_SPIN=0 OCG_ZMQ_IO_THREADS=2 BIG=0-19 LITTLE=0-19
done
# is the synthetic sink's own 500 us cadence the limiter at 100 MHz? let the sink request back to back (broker pacing sets the rate)
v2() { label=$1; n=$2; srate=$3; scs=$4; shift 4; echo "P2b-$label-n$n $n $srate $scs 8 1 1 1" | env "$@" bash phase2.sh phase2b.csv "2b-$label"; }
for n in 1 4 8; do v2 req0-100 $n 122880000 30 REQ_US=0 OCG_BROKER_SPIN=2 OCG_ZMQ_IO_THREADS=2; done
for n in 16 32; do v2 req0-20 $n 23040000 15 REQ_US=0 OCG_BROKER_SPIN=2 OCG_ZMQ_IO_THREADS=2; done
v2 req0-100-bigsinks 1 122880000 30 REQ_US=0 LITTLE=15-19 BIG=5-9 OCG_BROKER_SPIN=2 OCG_ZMQ_IO_THREADS=2
v2 req500-100-bigsinks 1 122880000 30 LITTLE=15-19 BIG=5-9 OCG_BROKER_SPIN=2 OCG_ZMQ_IO_THREADS=2
