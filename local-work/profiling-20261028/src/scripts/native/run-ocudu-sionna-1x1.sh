#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export OCUDU_NATIVE_CHANNEL_MODE=sionna
exec "${script_dir}/run-ocudu-legacy-1x1.sh" "$@"
