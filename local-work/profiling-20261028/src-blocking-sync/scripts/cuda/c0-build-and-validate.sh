#!/usr/bin/env bash
# C0 -- establish the hardware gap with NO patch applied.
#
# Builds the pinned WG CUDA source exactly as its own documentation prescribes
# and runs the validation that documentation specifies, on this workstation.
# Nothing is fixed here: the output of this stage is a per-test verdict and the
# mechanism behind each failure. Any source modification belongs to C1.
set -euo pipefail

WG_COMMIT="5830c9cb7813393b5d518dd5ee2b6641071be4ad"
CUDA_ARCH="120"   # WG doc: "RTX 50xx / Blackwell client GPUs: 120"

# WG doc, "Validation Run" -- transcribed verbatim.
WG_PHY_TESTS='^(ofdm_demodulator_cuda_test|ofdm_prach_demodulator_cuda_test|pdxch_baseband_modulator_cuda_test|ldpc_encoder_gpu_cpu_test|ldpc_decoder_gpu_cpu_test|prach_detector_cuda_test|pusch_gpu_cpu_comparison_test|pdsch_gpu_e2e_test|pusch_e2e_pipeline_test|pusch_resident_dematch_scramble_test|srs_estimator_gpu_latency_baseline_4x4_n4|srs_estimator_gpu_sensitivity_baseline_4x4_n4)$'
WG_OFH_TESTS='^ofh_iq_compression_cuda/'

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"
source "${repo_root}/scripts/native/env.sh"

src="${OCUDU_NATIVE_ROOT}/src/ocudu-cuda"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
build="${OCUDU_NATIVE_ROOT}/builds/c0-cuda-unpatched"
out="${OCUDU_NATIVE_ROOT}/results/cuda-rebuild/c0-${stamp}"
mkdir -p "$out"

# --- C0 precondition: the source must be the pinned commit with NO local change.
# A patched tree would make this stage measure C1's work instead of the vendor's.
[[ "$(git -C "$src" rev-parse HEAD)" == "$WG_COMMIT" ]] || { echo "FATAL: source is not $WG_COMMIT" >&2; exit 1; }
[[ -z "$(git -C "$src" status --porcelain)" ]] || { echo "FATAL: source is not clean; C0 requires the unpatched vendor tree" >&2; exit 1; }
echo "c0_source=${WG_COMMIT} unpatched=yes"

nvidia-smi --query-gpu=gpu_name,compute_cap,driver_version --format=csv | tee "$out/gpu.txt"
"${CUDACXX:-/usr/local/cuda/bin/nvcc}" --version | tail -2 | tee "$out/nvcc.txt"

echo "=== configure (arch ${CUDA_ARCH}) ==="
cmake -S "$src" -B "$build" \
  -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=ON \
  -DENABLE_CUDA=ON "-DCMAKE_CUDA_ARCHITECTURES=${CUDA_ARCH}" \
  -DCMAKE_POSITION_INDEPENDENT_CODE=ON \
  "-DCMAKE_INSTALL_PREFIX=${OCUDU_NATIVE_ROOT}/install/c0-cuda-unpatched" \
  "-DCMAKE_PREFIX_PATH=${OCUDU_NATIVE_GNUTLS};${OCUDU_NATIVE_SYSROOT}/usr" \
  "-DCMAKE_INCLUDE_PATH=${OCUDU_NATIVE_GNUTLS}/include;${OCUDU_NATIVE_SYSROOT}/usr/include;${OCUDU_NATIVE_SYSROOT}/usr/include/x86_64-linux-gnu" \
  "-DCMAKE_LIBRARY_PATH=${OCUDU_NATIVE_GNUTLS}/lib;${OCUDU_NATIVE_SYSROOT}/usr/lib/x86_64-linux-gnu" \
  -DENABLE_UHD=OFF -DENABLE_SIDEKIQ=OFF -DENABLE_MKL=OFF -DENABLE_FFTZ=OFF \
  -DENABLE_ARMPL=OFF -DENABLE_DPDK=OFF -DENABLE_LIBNUMA=OFF \
  -DENABLE_PLUGINS=OFF -DENABLE_BACKWARD=OFF -DENABLE_ZEROMQ=ON \
  -DENABLE_FFTW=ON -DENABLE_EXPORT=ON > "$out/configure.log" 2>&1
grep -E '^(CMAKE_CUDA_ARCHITECTURES|ENABLE_CUDA|CMAKE_BUILD_TYPE)' "$build/CMakeCache.txt" | tee "$out/cache.txt"

# ENABLE_CUDA can silently fall back; require the accelerated library itself.
echo "=== build: ocudu_phy_cuda + gnb ==="
cmake --build "$build" --target ocudu_phy_cuda gnb -j"${OCUDU_NATIVE_BUILD_JOBS:-12}" > "$out/build-gnb.log" 2>&1
echo "=== build: WG validation test targets ==="
cmake --build "$build" --target \
  ofdm_demodulator_cuda_test ofdm_prach_demodulator_cuda_test \
  pdxch_baseband_modulator_cuda_test ldpc_encoder_gpu_cpu_test \
  ldpc_decoder_gpu_cpu_test prach_detector_cuda_test \
  pusch_gpu_cpu_comparison_test pdsch_gpu_e2e_test pusch_e2e_pipeline_test \
  pusch_resident_dematch_scramble_test srs_estimator_gpu_latency_benchmark \
  srs_estimator_gpu_sensitivity_sweep -j"${OCUDU_NATIVE_BUILD_JOBS:-12}" > "$out/build-tests.log" 2>&1
# gtest_discover_tests populates its test list POST_BUILD. Without building this
# target the OFH suite stays registered as ofh_iq_compression_cuda_test_NOT_BUILT
# and the WG OFH regex matches a placeholder instead of the eight real cases.
cmake --build "$build" --target ofh_iq_compression_cuda_test \
  -j"${OCUDU_NATIVE_BUILD_JOBS:-12}" >> "$out/build-tests.log" 2>&1

"$build/apps/gnb/gnb" --version | tee "$out/gnb-version.txt"
"$build/apps/gnb/gnb" --help > "$out/gnb-help.txt" 2>&1 || true
grep -q '^GPU acceleration:' "$out/gnb-help.txt" && echo "gnb_cuda_help=present" || echo "gnb_cuda_help=ABSENT"
sha256sum "$build/apps/gnb/gnb" | tee "$out/gnb-sha256.txt"

# --- WG's own documented validation, run unmodified on this hardware.
echo "=== WG PHY validation (12 tests per WG doc) ==="
ctest --test-dir "$build" -N -R "$WG_PHY_TESTS" > "$out/phy-test-list.txt" 2>&1 || true
grep -c "Test *#" "$out/phy-test-list.txt" | sed 's/^/phy_tests_registered=/'
set +e
ctest --test-dir "$build" --output-on-failure --no-tests=error --timeout 3600 -j1 \
  -R "$WG_PHY_TESTS" > "$out/phy-validation.log" 2>&1
echo "phy_ctest_exit=$?"
# ctest rewrites Testing/Temporary/LastTest.log on every invocation. Snapshot the
# PHY run here, before the OFH run replaces it, or the verdict grader below reads
# the wrong suite and reports "no comparison found" for a suite that ran one.
cp "$build/Testing/Temporary/LastTest.log" "$out/phy-LastTest.log"

echo "=== WG OFH validation (8 tests per WG doc) ==="
ctest --test-dir "$build" -N -R "$WG_OFH_TESTS" > "$out/ofh-test-list.txt" 2>&1
ctest --test-dir "$build" --output-on-failure --timeout 600 -j1 \
  -R "$WG_OFH_TESTS" > "$out/ofh-validation.log" 2>&1
echo "ofh_ctest_exit=$?"
set -e

echo "=== printed-verdict grading (exit status is not sufficient) ==="
python3 "${script_dir}/verify-phy-log.py" "$out/phy-LastTest.log" \
  | tee "$out/phy-log-verdict.txt" || true
echo "c0_evidence=${out}"
