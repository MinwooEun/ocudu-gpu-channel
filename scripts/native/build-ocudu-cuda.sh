#!/usr/bin/env bash
# Build the pinned WG CUDA gNB and run its documented CUDA PHY subset.
# Run inside the native-workspace environment (source ~/ocudu-env.sh first).
set -euo pipefail
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${script_dir}/env.sh"
[[ $# -eq 0 ]] || { echo "usage: $0 (configure with OCUDU_NATIVE_* environment variables)" >&2; exit 2; }
selection="$(python3 "${script_dir}/native_gnb_profile.py" --root "${OCUDU_NATIVE_ROOT}" --profile cuda --prepare-source --fields)"
IFS=$'\t' read -r gnb_binary source_dir build_dir expected_commit <<<"${selection}"
jobs="${OCUDU_NATIVE_BUILD_JOBS:-8}"
arch="${OCUDU_NATIVE_CUDA_ARCH:-120}"
[[ "$jobs" =~ ^[1-9][0-9]*$ && "$arch" == 120 ]] || { echo "invalid jobs or architecture (locked to 120)" >&2; exit 2; }
export CUDACXX="${CUDACXX:-/usr/local/cuda/bin/nvcc}"
cmake -S "$source_dir" -B "$build_dir" \
  -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=ON \
  -DENABLE_CUDA=ON "-DCMAKE_CUDA_ARCHITECTURES=$arch" \
  -DCMAKE_POSITION_INDEPENDENT_CODE=ON \
  "-DCMAKE_INSTALL_PREFIX=${OCUDU_NATIVE_ROOT}/install/ocudu-cuda" \
  "-DCMAKE_PREFIX_PATH=${OCUDU_NATIVE_GNUTLS};${OCUDU_NATIVE_SYSROOT}/usr" \
  "-DCMAKE_INCLUDE_PATH=${OCUDU_NATIVE_GNUTLS}/include;${OCUDU_NATIVE_SYSROOT}/usr/include;${OCUDU_NATIVE_SYSROOT}/usr/include/x86_64-linux-gnu" \
  "-DCMAKE_LIBRARY_PATH=${OCUDU_NATIVE_GNUTLS}/lib;${OCUDU_NATIVE_SYSROOT}/usr/lib/x86_64-linux-gnu" \
  -DENABLE_UHD=OFF -DENABLE_SIDEKIQ=OFF -DENABLE_MKL=OFF -DENABLE_FFTZ=OFF \
  -DENABLE_ARMPL=OFF -DENABLE_DPDK=OFF -DENABLE_LIBNUMA=OFF \
  -DENABLE_PLUGINS=OFF -DENABLE_BACKWARD=OFF -DENABLE_ZEROMQ=ON \
  -DENABLE_FFTW=ON -DENABLE_EXPORT=ON
# ENABLE_CUDA can silently fall back when no compiler exists. Require the
# actual accelerated library before interpreting a successful build as CUDA.
cmake --build "$build_dir" --target ocudu_phy_cuda gnb -j"$jobs"
targets=(
  ofdm_demodulator_cuda_test ofdm_prach_demodulator_cuda_test
  pdxch_baseband_modulator_cuda_test ldpc_encoder_gpu_cpu_test
  ldpc_decoder_gpu_cpu_test prach_detector_cuda_test
  pusch_gpu_cpu_comparison_test pdsch_gpu_e2e_test pusch_e2e_pipeline_test
  pusch_resident_dematch_scramble_test srs_estimator_gpu_latency_benchmark
  srs_estimator_gpu_sensitivity_sweep
)
cmake --build "$build_dir" --target "${targets[@]}" -j"$jobs"
pattern='^(ofdm_demodulator_cuda_test|ofdm_prach_demodulator_cuda_test|pdxch_baseband_modulator_cuda_test|ldpc_encoder_gpu_cpu_test|ldpc_decoder_gpu_cpu_test|prach_detector_cuda_test|pusch_gpu_cpu_comparison_test|pusch_gpu_cpu_cfo_interpolation_test|pusch_gpu_cpu_sync_sinr_test|pdsch_gpu_e2e_test|pusch_e2e_pipeline_test|pusch_resident_dematch_scramble_test|srs_estimator_gpu_latency_baseline_4x4_n4|srs_estimator_gpu_sensitivity_baseline_4x4_n4)$'
ctest --test-dir "$build_dir" --show-only=json-v1 -R "$pattern" > "$build_dir/cuda-phy-test-list.json"
python3 - "$build_dir/cuda-phy-test-list.json" <<'CHECK'
import json, sys
with open(sys.argv[1]) as stream:
    tests = json.load(stream)["tests"]
if len(tests) != 14:
    raise SystemExit(f"expected 14 CUDA PHY tests, found {len(tests)}")
CHECK
ctest --test-dir "$build_dir" --verbose --output-on-failure --no-tests=error --timeout 3600 -j1 -R "$pattern"
grep -q 'CFO interpolation regression: PASS (CPU/GPU CRC and payload parity)' "$build_dir/Testing/Temporary/LastTest.log"
grep -q 'Synchronous SINR regression: PASS' "$build_dir/Testing/Temporary/LastTest.log"
python3 "${script_dir}/verify-cuda-phy-log.py" "$build_dir/Testing/Temporary/LastTest.log"
"$build_dir/apps/gnb/gnb" --version
"$build_dir/apps/gnb/gnb" --help > "$build_dir/gnb-help.txt"
# --version identifies the commit but does not advertise CUDA support.
grep -q '^GPU acceleration:' "$build_dir/gnb-help.txt"
