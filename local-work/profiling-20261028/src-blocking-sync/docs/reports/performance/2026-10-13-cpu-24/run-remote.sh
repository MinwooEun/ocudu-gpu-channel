#!/usr/bin/env bash
set -euo pipefail
source scripts/remote/common.sh
remote_sh bash -s -- "$REMOTE_WORKSPACE" "$REMOTE_BUILDS_ROOT" <<'REMOTE'
set -euo pipefail
expand(){ case "$1" in '~/'*)printf '%s/%s\n' "$HOME" "${1#\~/}";; *)printf '%s\n' "$1";;esac; }
work=$(expand "$1");root=$(expand "$2");task="$root/cpu-24-20261013";out="$task/results"
mkdir -p "$out"
source "$work/tools/env.sh"
export PATH="$work/tools/cuda-12.8.1/bin:$PATH"
export OCG_BENCH_PACE=0 OCG_BENCH_REFRESH=0 OCG_BENCH_THREADS=0
cfg="$task/source/use_cases/configs/topologies/perf/topology.perf-tdl-a-fanin-8.cuda.yaml"
cp "$cfg" "$out/tdl-a_E16.cuda.yaml"
sed 's/backend: cuda/backend: cpu/' "$cfg" > "$out/tdl-a_E16.cpu1.yaml"
{
 date -u '+utc_started=%Y-%m-%dT%H:%M:%SZ'
 printf 'source_base_commit=f95dabd0d13db3b24e9a4b04c919ad3620468f11; plus cpu-24 source patch\nmode=Release; CUDA sm_120\nworkload=3 runs x 30 seconds per variant; 5 second separate warmup per backend\n'
 lscpu | sed -n '/Model name:/p;/CPU(s):/p;/Thread(s) per core:/p;/Core(s) per socket:/p'
 nvidia-smi --query-gpu=name,driver_version,pcie.link.gen.max,pcie.link.width.max,power.limit --format=csv
 "$work/tools/cuda-12.8.1/bin/nvcc" --version
 c++ --version | head -1
 sha256sum "$task/build/ocudu-gpu-channel-bench" "$out/tdl-a_E16.cuda.yaml" "$out/tdl-a_E16.cpu1.yaml"
} > "$out/environment.txt"
sed '/backend: cpu/a\  cpu_threads: 24' "$out/tdl-a_E16.cpu1.yaml" > "$out/tdl-a_E16.cpu24.yaml"
for backend in cpu1 cpu24 cuda;do
 "$task/build/ocudu-gpu-channel-bench" --config "$out/tdl-a_E16.$backend.yaml" --duration 5s --per-node > "$out/warmup.$backend.csv" 2> "$out/warmup.$backend.stderr"
done
for spec in '1 cpu1' '1 cpu24' '1 cuda' '2 cuda' '2 cpu24' '2 cpu1' '3 cpu1' '3 cuda' '3 cpu24';do
 read -r repeat backend <<< "$spec"
 printf 'Running %s, repetition %s of 3 (30 seconds)\n' "$backend" "$repeat"
 nvidia-smi --query-gpu=timestamp,utilization.gpu,temperature.gpu,clocks.current.graphics,pcie.link.gen.current,pcie.link.width.current,power.draw --format=csv -l 1 > "$out/$backend.$repeat.gpu.csv" &
 monitor=$!
 /usr/bin/time -o "$out/$backend.$repeat.cpu-time.txt" -f 'wall_seconds=%e\nuser_seconds=%U\nsystem_seconds=%S\ncpu_percent=%P' "$task/build/ocudu-gpu-channel-bench" --config "$out/tdl-a_E16.$backend.yaml" --duration 30s --per-node > "$out/$backend.$repeat.csv" 2> "$out/$backend.$repeat.stderr" &
 timer=$!
 if [[ "$backend" == cpu24 ]]; then
   sleep 2
   bench_pid=$(pgrep -P "$timer" | head -1)
   if [[ -n "$bench_pid" ]]; then
     ps -L -p "$bench_pid" -o pid,tid,psr,pcpu,time,comm > "$out/$backend.$repeat.threads-start.txt"
     sleep 20
     ps -L -p "$bench_pid" -o pid,tid,psr,pcpu,time,comm > "$out/$backend.$repeat.threads-end.txt" || true
   fi
 fi
 wait "$timer"
 kill "$monitor";wait "$monitor" 2>/dev/null || true
 awk -F, '$1=="model_mix_latency" {printf "  calls=%s, p99=%s us, max=%s us\n",$2,$5,$7}' "$out/$backend.$repeat.csv"
done
date -u '+utc_completed=%Y-%m-%dT%H:%M:%SZ' >> "$out/environment.txt"
REMOTE
case "$REMOTE_BUILDS_ROOT" in '~/'*) fetch_root="${REMOTE_BUILDS_ROOT#\~/}";;*)fetch_root="$REMOTE_BUILDS_ROOT";;esac
mkdir -p "$repo_root/tmp/cpu-24/results"
rsync -az -e "ssh -i $REMOTE_SSH_KEY -o BatchMode=yes -o ConnectTimeout=8" "$REMOTE_USER@$REMOTE_HOST:$fetch_root/cpu-24-20261013/results/" "$repo_root/tmp/cpu-24/results/"
