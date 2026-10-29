#!/usr/bin/env bash
# Run the existing 1x1 attach gate with the CUDA gNB.
#
# The gate itself learns exactly one thing from this file -- which binary to
# run, and which revision that binary must report. Everything else that is
# specific to CUDA (source/patch audit, build checks, acceleration staging,
# provenance) lives here and in the files this calls, so the gate stays the
# regression net it was.
#
#   OCUDU_NATIVE_GNB_ACCELERATION=disabled|low-phy-rx|low-phy-tx|pusch|pdsch|prach|all
#     Default is 'disabled': the CUDA binary running its host PHY. That is the
#     parity control -- it separates "the build swap broke something" from
#     "the acceleration broke something".
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"
native_dir="${repo_root}/scripts/native"
source "${native_dir}/env.sh"

acceleration="${OCUDU_NATIVE_GNB_ACCELERATION:-disabled}"
case "${acceleration}" in
  disabled|low-phy-rx|low-phy-tx|pusch|pdsch|prach|all) ;;
  *) echo "invalid OCUDU_NATIVE_GNB_ACCELERATION: ${acceleration}" >&2; exit 2 ;;
esac

# Audits the pinned source, the exact reviewed patch, the CUDA build settings,
# the binary revision and its CUDA help output. Fails loudly rather than
# silently falling back to the CPU build.
selection="$(/usr/bin/python3 "${script_dir}/resolve-cuda-gnb.py" \
  --root "${OCUDU_NATIVE_ROOT}" --fields)"
IFS=$'\t' read -r gnb_binary gnb_source gnb_build gnb_commit <<<"${selection}"

export OCUDU_NATIVE_GNB_BINARY="${gnb_binary}"
export OCUDU_NATIVE_GNB_COMMIT="${gnb_commit:0:7}"
export OCUDU_NATIVE_GNB_ACCELERATION="${acceleration}"
# CUDA PHY device initialisation runs before the gNB prints its banner and
# does not fit the gate's default 15 s. Bounded, and overridable.
export OCUDU_NATIVE_GNB_START_TIMEOUT_SECONDS="${OCUDU_NATIVE_GNB_START_TIMEOUT_SECONDS:-120}"
# The broker's --duration clock starts with the broker process, so the gNB's
# device initialisation is spent out of the measured window. Measured at
# ~19.7 s to the ZMQ bind with every mode enabled; 30 s leaves the live window
# comfortably longer than the 15 s the gate asks for, without making the gate
# run appreciably longer than it must.
export OCUDU_NATIVE_BROKER_STARTUP_ALLOWANCE_SECONDS="${OCUDU_NATIVE_BROKER_STARTUP_ALLOWANCE_SECONDS:-30}"
export OCUDU_NATIVE_CONFIG_RENDERER="${script_dir}/render-cuda-1x1-configs.py"

printf 'event=native_cuda_1x1_launch gnb=%s commit=%s acceleration=%s\n' \
  "${gnb_binary}" "${OCUDU_NATIVE_GNB_COMMIT}" "${acceleration}"

exec "${native_dir}/run-ocudu-legacy-1x1.sh" "$@"
