#!/usr/bin/env bash
# NC-D6 -- negative control for the J2 Orin layer (defect D6).
#
# Builds the J2 base commit (pin + C1, no J2 diff) in its own checkout and runs
# the J2 test set minus pusch_gpu_cpu_comparison_test (~1 h on Orin, untouched by
# D6). Expected: the tests J2 fixed fail again -- lower-PHY, PDSCH and OFH
# retries with cudaErrorInvalidDevice (101) or SIGSEGV -- so the J2 diff, not
# the C1 patch, is what makes them pass. Judge from the per-test lines.
set -uo pipefail
WG_COMMIT=5830c9cb7813393b5d518dd5ee2b6641071be4ad
repo="$(cd "$(dirname "$0")/../../.." && pwd)"
root="${PLATFORM_ROOT:-/workspace/ocudu-jetson}"
base_src="$root/src/ocudu-cuda-j2"
src="$root/src/ocudu-cuda-nc6"
build="$root/builds/nc6-cuda-c1-sm87"
jobs="${J2_BUILD_JOBS:-6}"
out="$root/results/nc-d6-$(date -u +%Y%m%dT%H%M%SZ)"
export PATH="/usr/local/cuda/bin:$PATH"
mkdir -p "$out"; exec > >(tee -a "$out/nc-d6.log") 2>&1
die() { echo "FATAL: $*"; exit 1; }
TESTS='^(ofdm_demodulator_cuda_test|ofdm_prach_demodulator_cuda_test|pdxch_baseband_modulator_cuda_test|ldpc_encoder_gpu_cpu_test|ldpc_decoder_gpu_cpu_test|prach_detector_cuda_test|pusch_gpu_cpu_cfo_interpolation_test|pusch_gpu_cpu_sync_sinr_test|pdsch_gpu_e2e_test|pusch_e2e_pipeline_test|pusch_resident_dematch_scramble_test|srs_estimator_gpu_latency_baseline_4x4_n4|srs_estimator_gpu_sensitivity_baseline_4x4_n4)$'

base="$(git -C "$base_src" rev-parse HEAD)" || die "no J2 checkout"
[[ "$(git -C "$base_src" rev-parse HEAD~1)" == "$WG_COMMIT" ]] || die "J2 base is not pin+C1"
if [[ ! -d "$src/.git" ]]; then git clone -q "$base_src" "$src" || die clone; fi
git -C "$src" checkout -q "$base" && git -C "$src" checkout -q -- . || die checkout
[[ -z "$(git -C "$src" status --porcelain)" ]] || die "control tree is not clean"
echo "source=pin+C1 (no J2) commit=$base"

echo "=== configure/build $(date -u +%T) ==="
cmake -S "$src" -B "$build" -G Ninja -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=ON \
  -DENABLE_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=87 -DCMAKE_POSITION_INDEPENDENT_CODE=ON \
  -DENABLE_UHD=OFF -DENABLE_SIDEKIQ=OFF -DENABLE_MKL=OFF -DENABLE_FFTZ=OFF -DENABLE_ARMPL=OFF \
  -DENABLE_DPDK=OFF -DENABLE_LIBNUMA=OFF -DENABLE_PLUGINS=OFF -DENABLE_BACKWARD=OFF \
  -DENABLE_ZEROMQ=ON -DENABLE_FFTW=ON -DENABLE_EXPORT=ON > "$out/configure.log" 2>&1 || die configure
cmake --build "$build" --target ofdm_demodulator_cuda_test ofdm_prach_demodulator_cuda_test \
  pdxch_baseband_modulator_cuda_test ldpc_encoder_gpu_cpu_test ldpc_decoder_gpu_cpu_test prach_detector_cuda_test \
  pusch_gpu_cpu_comparison_test pdsch_gpu_e2e_test pusch_e2e_pipeline_test pusch_resident_dematch_scramble_test \
  srs_estimator_gpu_latency_benchmark srs_estimator_gpu_sensitivity_sweep ofh_iq_compression_cuda_test \
  -j"$jobs" > "$out/build.log" 2>&1 || die build
echo "=== build done $(date -u +%T) ==="

ctest --test-dir "$build" --output-on-failure --no-tests=error --timeout 1800 -j1 -R "$TESTS" > "$out/phy-validation.log" 2>&1
echo "phy_ctest_exit=$?"
grep -E '^ *[0-9]+/[0-9]+ Test|tests passed' "$out/phy-validation.log"
ctest --test-dir "$build" --output-on-failure --timeout 600 -j1 -R '^ofh_iq_compression_cuda/' > "$out/ofh-validation.log" 2>&1
echo "ofh_ctest_exit=$?"; grep -E 'tests passed|Failed|SEGFAULT' "$out/ofh-validation.log"
echo "error_101_lines=$(grep -c -E 'invalid device ordinal|cudaErrorInvalidDevice|\(101\)' "$out"/*-validation.log | paste -sd,)"
echo "nc_d6_evidence=$out"; echo NC_D6_DONE
