#!/usr/bin/env bash
# C1 exit gate: WG's own documented validation PLUS the blind-spot regressions
# this stage adds. Graded by printed verdicts as well as ctest status.
set -uo pipefail
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"
source "${repo_root}/scripts/native/env.sh"
build="${OCUDU_NATIVE_ROOT}/builds/c1-cuda-patched"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
out="${OCUDU_NATIVE_ROOT}/results/cuda-rebuild/c1-${stamp}"
mkdir -p "$out"

# WG's 12, verbatim, plus the two regressions C1 adds for the blind spots.
TESTS='^(ofdm_demodulator_cuda_test|ofdm_prach_demodulator_cuda_test|pdxch_baseband_modulator_cuda_test|ldpc_encoder_gpu_cpu_test|ldpc_decoder_gpu_cpu_test|prach_detector_cuda_test|pusch_gpu_cpu_comparison_test|pusch_gpu_cpu_cfo_interpolation_test|pusch_gpu_cpu_sync_sinr_test|pdsch_gpu_e2e_test|pusch_e2e_pipeline_test|pusch_resident_dematch_scramble_test|srs_estimator_gpu_latency_baseline_4x4_n4|srs_estimator_gpu_sensitivity_baseline_4x4_n4)$'
OFH='^ofh_iq_compression_cuda/'

sha256sum "$build/apps/gnb/gnb" | tee "$out/gnb-sha256.txt"
ctest --test-dir "$build" -N -R "$TESTS" | grep -c "Test *#" | sed 's/^/phy_tests_registered=/'
ctest --test-dir "$build" --output-on-failure --no-tests=error --timeout 3600 -j1 \
  -R "$TESTS" > "$out/phy-validation.log" 2>&1
echo "phy_ctest_exit=$?"
# Snapshot before the OFH run replaces LastTest.log.
cp "$build/Testing/Temporary/LastTest.log" "$out/phy-LastTest.log"

ctest --test-dir "$build" --output-on-failure --timeout 600 -j1 -R "$OFH" > "$out/ofh-validation.log" 2>&1
echo "ofh_ctest_exit=$?"

python3 "${script_dir}/verify-phy-log.py" "$out/phy-LastTest.log" | tee "$out/phy-log-verdict.txt"
# The two blind-spot regressions print their own PASS markers; require both.
for marker in 'CFO interpolation regression: PASS' 'Synchronous SINR regression: PASS'; do
  grep -q "$marker" "$out/phy-LastTest.log" && echo "marker_ok=\"$marker\"" || echo "marker_MISSING=\"$marker\""
done
echo "c1_evidence=${out}"
