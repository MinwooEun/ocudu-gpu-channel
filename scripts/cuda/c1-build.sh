#!/usr/bin/env bash
# C1 build helper. Same configuration as C0, separate build directory so the
# unpatched C0 evidence build is never overwritten. Incremental by design:
# re-run after each fix and only the changed translation units rebuild.
set -euo pipefail
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"
source "${repo_root}/scripts/native/env.sh"
src="${OCUDU_NATIVE_ROOT}/src/ocudu-cuda"
build="${OCUDU_NATIVE_ROOT}/builds/c1-cuda-patched"
export CUDACXX="${CUDACXX:-/usr/local/cuda/bin/nvcc}"

if [[ ! -f "$build/CMakeCache.txt" ]]; then
  cmake -S "$src" -B "$build" \
    -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=ON \
    -DENABLE_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=120 \
    -DCMAKE_POSITION_INDEPENDENT_CODE=ON \
    "-DCMAKE_INSTALL_PREFIX=${OCUDU_NATIVE_ROOT}/install/c1-cuda-patched" \
    "-DCMAKE_PREFIX_PATH=${OCUDU_NATIVE_GNUTLS};${OCUDU_NATIVE_SYSROOT}/usr" \
    "-DCMAKE_INCLUDE_PATH=${OCUDU_NATIVE_GNUTLS}/include;${OCUDU_NATIVE_SYSROOT}/usr/include;${OCUDU_NATIVE_SYSROOT}/usr/include/x86_64-linux-gnu" \
    "-DCMAKE_LIBRARY_PATH=${OCUDU_NATIVE_GNUTLS}/lib;${OCUDU_NATIVE_SYSROOT}/usr/lib/x86_64-linux-gnu" \
    -DENABLE_UHD=OFF -DENABLE_SIDEKIQ=OFF -DENABLE_MKL=OFF -DENABLE_FFTZ=OFF \
    -DENABLE_ARMPL=OFF -DENABLE_DPDK=OFF -DENABLE_LIBNUMA=OFF \
    -DENABLE_PLUGINS=OFF -DENABLE_BACKWARD=OFF -DENABLE_ZEROMQ=ON \
    -DENABLE_FFTW=ON -DENABLE_EXPORT=ON >/dev/null
fi
targets=(ocudu_phy_cuda gnb
  ofdm_demodulator_cuda_test ofdm_prach_demodulator_cuda_test
  pdxch_baseband_modulator_cuda_test ldpc_encoder_gpu_cpu_test
  ldpc_decoder_gpu_cpu_test prach_detector_cuda_test
  pusch_gpu_cpu_comparison_test pdsch_gpu_e2e_test pusch_e2e_pipeline_test
  pusch_resident_dematch_scramble_test srs_estimator_gpu_latency_benchmark
  srs_estimator_gpu_sensitivity_sweep ofh_iq_compression_cuda_test)
cmake --build "$build" --target "${targets[@]}" -j"${OCUDU_NATIVE_BUILD_JOBS:-12}"
echo "c1_build=${build}"
sha256sum "$build/apps/gnb/gnb"
