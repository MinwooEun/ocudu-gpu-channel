#!/usr/bin/env bash
set -euo pipefail
source scripts/remote/common.sh
bench_task=cpu-24-20261013
archive_file="$repo_root/tmp/cpu-24/source.tar"
COPYFILE_DISABLE=1 tar --no-xattrs -cf "$archive_file" CMakeLists.txt apps benchmarks include src tests scripts/native use_cases/configs
remote_sh bash -s -- "$REMOTE_BUILDS_ROOT" "$bench_task" <<'REMOTE'
set -euo pipefail
root="$1";case "$root" in '~/'*)root="$HOME/${root#\~/}";;esac
mkdir -p "$root/$2/source"
REMOTE
cat "$archive_file" | "${ssh_base[@]}" 'bash -c '\''root="$1"; case "$root" in \~/\*) root="$HOME/${root#\~/}";; esac; tar -xf - -C "$root/$2/source"'\'' bash' "$REMOTE_BUILDS_ROOT" "$bench_task"
remote_sh bash -s -- "$REMOTE_WORKSPACE" "$REMOTE_BUILDS_ROOT" "$bench_task" <<'REMOTE'
set -euo pipefail
expand(){ case "$1" in '~/'*) printf '%s/%s\n' "$HOME" "${1#\~/}";; *)printf '%s\n' "$1";;esac; }
work=$(expand "$1");root=$(expand "$2");task="$root/$3"
source "$work/tools/env.sh"
export PATH="$work/tools/cuda-12.8.1/bin:$PATH"
cmake -S "$task/source" -B "$task/build" -DCMAKE_BUILD_TYPE=Release -DOCUDU_GPU_CHANNEL_ENABLE_CUDA=ON -DOCUDU_GPU_CHANNEL_BUILD_TESTS=ON -DCMAKE_CUDA_COMPILER="$work/tools/cuda-12.8.1/bin/nvcc" -DOCUDU_GPU_CHANNEL_CUDA_ARCHITECTURES=120 > "$task/configure.log" 2>&1
cmake --build "$task/build" -j8 > "$task/build.log" 2>&1 || { tail -90 "$task/build.log"; exit 1; }
ctest --test-dir "$task/build" --output-on-failure -j4 > "$task/ctest.log" 2>&1 || { tail -100 "$task/ctest.log"; exit 1; }
tail -5 "$task/ctest.log"
printf 'Isolated benchmark build complete.\n'
REMOTE
