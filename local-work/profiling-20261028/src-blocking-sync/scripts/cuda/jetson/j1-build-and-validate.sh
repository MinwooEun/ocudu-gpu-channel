#!/usr/bin/env bash
# J1 -- the vendor's own validation on Jetson AGX Orin, NO patch applied.
#
# The Jetson counterpart of scripts/cuda/c0-build-and-validate.sh: same pinned
# source, same CMake options, same test regexes transcribed from the WG doc,
# same printed-verdict grading. What differs is only the platform: sm_87, CUDA
# 12.6, aarch64 system packages instead of the workstation's user-space sysroot.
# Nothing is fixed here; failures are recorded and traced in JETSON_MILESTONES.md.
#
# Run inside the Jetson container:
#   NVP_MODE="<host nvpmodel -q output>" bash j1-build-and-validate.sh          # Jetson
#   CUDA_ARCH=121 PLATFORM_ROOT=/workspace/ocudu-spark STAGE=s1 J1_BUILD_JOBS=16 \
#     EXTRA_CMAKE_ARGS=-DMCPU=neoverse-v2 bash j1-build-and-validate.sh         # DGX Spark
# MCPU=neoverse-v2 is the WG doc's own DGX Spark setting: GCC 13.3 does not know
# Cortex-X925/A725, -mcpu=native then lacks +crypto, and OCUDU's crypto probe
# reuses a cached result so its armv8-a+crypto fallback never runs.
set -euo pipefail

WG_COMMIT="${EXPECT_COMMIT:-5830c9cb7813393b5d518dd5ee2b6641071be4ad}"   # override only to test another vendor commit
CUDA_ARCH="${CUDA_ARCH:-87}"    # Orin 8.7 (not in the WG doc's list); DGX Spark GB10 runs this with CUDA_ARCH=121

# WG doc, "Validation Run" -- identical to c0-build-and-validate.sh.
WG_PHY_TESTS='^(ofdm_demodulator_cuda_test|ofdm_prach_demodulator_cuda_test|pdxch_baseband_modulator_cuda_test|ldpc_encoder_gpu_cpu_test|ldpc_decoder_gpu_cpu_test|prach_detector_cuda_test|pusch_gpu_cpu_comparison_test|pdsch_gpu_e2e_test|pusch_e2e_pipeline_test|pusch_resident_dematch_scramble_test|srs_estimator_gpu_latency_baseline_4x4_n4|srs_estimator_gpu_sensitivity_baseline_4x4_n4)$'
WG_OFH_TESTS='^ofh_iq_compression_cuda/'

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="${PLATFORM_ROOT:-${JETSON_ROOT:-/workspace/ocudu-jetson}}"
src="${SRC_DIR:-${root}/src/ocudu-cuda}"
stage="${STAGE:-j1}"
build="${root}/builds/${stage}-cuda-vendor-sm${CUDA_ARCH}"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
out="${root}/results/${stage}-${stamp}"
# nvcc for sm_87 needs several GB per process; user-a's SETUP.md saw OOM risk
# at -j12 on this board. 30W mode has 8 cores online anyway.
jobs="${J1_BUILD_JOBS:-6}"
export PATH="/usr/local/cuda/bin:${PATH}"
export CUDACXX="${CUDACXX:-/usr/local/cuda/bin/nvcc}"
mkdir -p "$out"
exec > >(tee -a "$out/j1.log") 2>&1

[[ "$(git -C "$src" rev-parse HEAD)" == "$WG_COMMIT" ]] || { echo "FATAL: source is not $WG_COMMIT" >&2; exit 1; }
[[ -z "$(git -C "$src" status --porcelain)" ]] || { echo "FATAL: source is not clean; J1 requires the unpatched vendor tree" >&2; exit 1; }
echo "${stage}_source=${WG_COMMIT} unpatched=yes arch=${CUDA_ARCH} jobs=${jobs}"

bash "${script_dir}/probe-platform.sh" "$out" >/dev/null
"$CUDACXX" --version | tail -2 | tee "$out/nvcc.txt"
free -g | tee "$out/mem.txt"

echo "=== configure (arch ${CUDA_ARCH}) $(date -u +%T) ==="
cmake -S "$src" -B "$build" -G Ninja \
  -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=ON \
  -DENABLE_CUDA=ON "-DCMAKE_CUDA_ARCHITECTURES=${CUDA_ARCH}" \
  -DCMAKE_POSITION_INDEPENDENT_CODE=ON \
  "-DCMAKE_INSTALL_PREFIX=${root}/install/${stage}-cuda-vendor-sm${CUDA_ARCH}" \
  -DENABLE_UHD=OFF -DENABLE_SIDEKIQ=OFF -DENABLE_MKL=OFF -DENABLE_FFTZ=OFF \
  -DENABLE_ARMPL=OFF -DENABLE_DPDK=OFF -DENABLE_LIBNUMA=OFF \
  -DENABLE_PLUGINS=OFF -DENABLE_BACKWARD=OFF -DENABLE_ZEROMQ=ON \
  -DENABLE_FFTW=ON -DENABLE_EXPORT=ON ${EXTRA_CMAKE_ARGS:-} > "$out/configure.log" 2>&1
grep -E '^(CMAKE_CUDA_ARCHITECTURES|ENABLE_CUDA|CMAKE_BUILD_TYPE|MCPU|CMAKE_CXX_COMPILER:|CMAKE_CUDA_COMPILER:)' "$build/CMakeCache.txt" | tee "$out/cache.txt"

echo "=== build: ocudu_phy_cuda + gnb $(date -u +%T) ==="
cmake --build "$build" --target ocudu_phy_cuda gnb -j"$jobs" > "$out/build-gnb.log" 2>&1
echo "=== build: WG validation test targets $(date -u +%T) ==="
cmake --build "$build" --target \
  ofdm_demodulator_cuda_test ofdm_prach_demodulator_cuda_test \
  pdxch_baseband_modulator_cuda_test ldpc_encoder_gpu_cpu_test \
  ldpc_decoder_gpu_cpu_test prach_detector_cuda_test \
  pusch_gpu_cpu_comparison_test pdsch_gpu_e2e_test pusch_e2e_pipeline_test \
  pusch_resident_dematch_scramble_test srs_estimator_gpu_latency_benchmark \
  srs_estimator_gpu_sensitivity_sweep -j"$jobs" > "$out/build-tests.log" 2>&1
# Without building this target the OFH suite stays a _NOT_BUILT placeholder and
# the WG regex matches it instead of the real cases (C0 finding).
cmake --build "$build" --target ofh_iq_compression_cuda_test -j"$jobs" >> "$out/build-tests.log" 2>&1
echo "=== build done $(date -u +%T) ==="

"$build/apps/gnb/gnb" --version | tee "$out/gnb-version.txt"
"$build/apps/gnb/gnb" --help > "$out/gnb-help.txt" 2>&1 || true
grep -q '^GPU acceleration:' "$out/gnb-help.txt" && echo "gnb_cuda_help=present" || echo "gnb_cuda_help=ABSENT"
sha256sum "$build/apps/gnb/gnb" | tee "$out/gnb-sha256.txt"

echo "=== WG PHY validation (12 tests per WG doc) $(date -u +%T) ==="
ctest --test-dir "$build" -N -R "$WG_PHY_TESTS" > "$out/phy-test-list.txt" 2>&1 || true
grep -c "Test *#" "$out/phy-test-list.txt" | sed 's/^/phy_tests_registered=/'
set +e
ctest --test-dir "$build" --output-on-failure --no-tests=error --timeout 7200 -j1 \
  -R "$WG_PHY_TESTS" > "$out/phy-validation.log" 2>&1
echo "phy_ctest_exit=$?"
cp "$build/Testing/Temporary/LastTest.log" "$out/phy-LastTest.log"

echo "=== WG OFH validation $(date -u +%T) ==="
ctest --test-dir "$build" -N -R "$WG_OFH_TESTS" > "$out/ofh-test-list.txt" 2>&1
grep -c "Test *#" "$out/ofh-test-list.txt" | sed 's/^/ofh_tests_registered=/'
ctest --test-dir "$build" --output-on-failure --timeout 600 -j1 \
  -R "$WG_OFH_TESTS" > "$out/ofh-validation.log" 2>&1
echo "ofh_ctest_exit=$?"
set -e

echo "=== printed-verdict grading (exit status is not sufficient) ==="
python3 "${script_dir}/../verify-phy-log.py" "$out/phy-LastTest.log" | tee "$out/phy-log-verdict.txt" || true
grep -E 'Test +#|tests passed|Total Test time' "$out/phy-validation.log" | tee "$out/phy-summary.txt"
echo "${stage}_evidence=${out}"
echo J1_DONE
