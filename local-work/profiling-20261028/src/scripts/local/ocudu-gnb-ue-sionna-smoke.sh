#!/usr/bin/env bash
# One-command local integration test:
# Open5GS + 2 OCUDU gNBs + 2 srsUEs + CUDA broker + Sionna RT.
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"

export OCUDU_MGNB_EXECUTION=local
export OCUDU_MGNB_CHANNEL_MODE="${OCUDU_MGNB_CHANNEL_MODE:-sionna}"
export OCUDU_MGNB_DURATION_SECONDS="${OCUDU_MGNB_DURATION_SECONDS:-90}"
export OCUDU_MGNB_SIONNA_READY_SECONDS="${OCUDU_MGNB_SIONNA_READY_SECONDS:-120}"

exec "${repo_root}/scripts/remote/ocudu-multi-gnb-smoke.sh" "$@"
