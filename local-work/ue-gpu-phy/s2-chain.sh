#!/bin/bash
# Local S2 live chain: slot trace for CPU vs GPU-LDPC vs GPU full DL chain (fft+pdsch) in the same live stack.
L=/workspace/gpuch; T=$L/s4/trace; rm -f $L/s4/s2-chain.done
export LD_LIBRARY_PATH=/usr/local/cuda/lib64
until grep -q "exit=0" $L/s4/s2-build.done 2>/dev/null; do sleep 20; done
waitgpu() { until ! pgrep -f boundary.py >/dev/null && [ -z "$(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null)" ]; do sleep 20; done; }
req() { echo "{\"ue_count\":$1,\"gnb_antennas\":1,\"mobility\":\"pedestrian\",\"placement\":\"uniform\",\"traffic_profile\":\"mixed\",\"tests\":[{\"scheduler\":\"rr\",\"link_adaptation\":\"harq_olla\"},{\"scheduler\":\"rr\",\"link_adaptation\":\"harq_olla\"}],\"seed\":20261016,\"measure_seconds\":$2,\"warmup_seconds\":10,\"repeat_count\":1,\"comparison_order\":\"abba\"}"; }
COMMON="SB_ALLOW_UNVALIDATED=1 SINGLE_CELL_CPUS_AUX=0-4 SINGLE_CELL_UE_RX_SLEEP=false SINGLE_CELL_QUIET_LOGS=1 SINGLE_CELL_PCAP=off SINGLE_CELL_CPUS_GNB=5-12 SINGLE_CELL_CPUS_BROKER=15-16 SINGLE_CELL_CPUS_UES=17-19 OCG_BROKER_SPIN=2 OCG_ZMQ_IO_THREADS=2 SINGLE_CELL_UE_BINARY=/workspace/gpuch/s4/build-s1/srsue/src/srsue SRSRAN_SCH_TIMING=1 SRSRAN_LDPC_CUDA_VERBOSE=1"
MPS="SINGLE_CELL_MPS=on SINGLE_CELL_BROKER_IN_MPS=1"
GPU="SRSRAN_LDPC_DECODER=cuda SRSRAN_UE_DL_CUDA=all SRSRAN_LDPC_CUDA_SYNC=block $MPS"
run() { tag=$1; shift; waitgpu; mkdir -p -m 777 $T/$tag; timeout 1500 bash $L/ranb-run.sh $tag $COMMON "SRSUE_SLOT_TRACE_DIR=$T/$tag" "$@" > $L/ranb-run-$tag.log 2>&1; echo "EXIT=$?" >> $L/ranb-run-$tag.log; }
run s2-b50-cpu-1c   "RANB_REQ=$(req 1 20)" SINGLE_CELL_BW_MHZ=50 SINGLE_CELL_CPUS_UE0=17
run s2-b50-gpu-1c   "RANB_REQ=$(req 1 20)" SINGLE_CELL_BW_MHZ=50 SINGLE_CELL_CPUS_UE0=17 $GPU
run s2-b50-gpuspin-1c "RANB_REQ=$(req 1 20)" SINGLE_CELL_BW_MHZ=50 SINGLE_CELL_CPUS_UE0=17 SRSRAN_LDPC_DECODER=cuda SRSRAN_UE_DL_CUDA=all SRSRAN_LDPC_CUDA_SYNC=spin $MPS
run s2-b50-cpu-3c   "RANB_REQ=$(req 1 20)" SINGLE_CELL_BW_MHZ=50 SINGLE_CELL_CPUS_UE0=17-19
run s2-b50-gpu-3c   "RANB_REQ=$(req 1 20)" SINGLE_CELL_BW_MHZ=50 SINGLE_CELL_CPUS_UE0=17-19 $GPU
run s2-b20-cpu-4ue  "RANB_REQ=$(req 4 20)" SINGLE_CELL_BW_MHZ=20
run s2-b20-gpu-4ue  "RANB_REQ=$(req 4 20)" SINGLE_CELL_BW_MHZ=20 $GPU
echo CHAIN_DONE > $L/s4/s2-chain.done
