#!/usr/bin/env bash
# C4's BLER clause: a traffic-bearing paired run, because the attach gate cannot
# express one percentage point.
#
# The plain gate carries the attach exchange and one acceptance ping -- 27 to 31
# PUSCH transmissions, where a single CRC failure moves BLER by 3.7 pp. This
# opts the bounded run into the keepalive ping (0.2 s, ping's unprivileged
# floor) and lengthens the broker's window, so the run accumulates enough
# transmissions for the resolution to fall under 1 pp.
#
# Read the result with its limits in view. `legacy` channel mode relays IQ close
# to cleanly, so 0 % on both arms is the expected outcome and the comparison has
# no power to discriminate: it shows the accelerated path does not *introduce*
# errors, not that the two paths behave alike under stress. That needs a channel
# that produces errors, which is a C5/C6 fixture, not a longer run.
#
#   OCUDU_CUDA_BLER_ALLOWANCE  broker startup allowance, default 60
#   OCUDU_CUDA_BLER_INTERVAL   keepalive ping interval, default 0.2
#   OCUDU_CUDA_BLER_STAGE      accelerated arm's stage, default all
set -uo pipefail
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"
source "${repo_root}/scripts/native/env.sh"
allowance="${OCUDU_CUDA_BLER_ALLOWANCE:-60}"
interval="${OCUDU_CUDA_BLER_INTERVAL:-0.2}"
stage="${OCUDU_CUDA_BLER_STAGE:-all}"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
out="${OCUDU_NATIVE_ROOT}/results/cuda-rebuild/c4-bler-${stamp}"
runs="${OCUDU_NATIVE_ROOT}/results/logs/ocudu-interop"
mkdir -p "$out"

run_arm() { # label  env-assignments...
  local label="$1"; shift
  local gate_log="${out}/${label}.gate.log"
  echo "########## ${label}"
  env OCUDU_NATIVE_UE_KEEPALIVE_SECONDS="${interval}" \
      OCUDU_NATIVE_BROKER_STARTUP_ALLOWANCE_SECONDS="${allowance}" \
      "$@" >"$gate_log" 2>&1
  local status="$?"
  local summary run_dir="" verdict='no-run'
  summary="$(sed -n 's/.*summary="\([^"]*\)".*/\1/p;s/^summary=\(.*\)$/\1/p' "$gate_log" | tail -1)"
  if [[ -n "$summary" && -f "$summary" ]]; then
    run_dir="$(basename "$(dirname "$summary")")"
    verdict="$(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('status','?'))" "$summary" 2>/dev/null || echo '?')"
    python3 "${script_dir}/summarize-phy-kpis.py" --json "${runs}/${run_dir}/gnb-internal.log" \
      >"${out}/${label}.kpis.json" 2>/dev/null
    # The keepalive must actually have run; a silent no-op would leave the
    # sample size unchanged and the verdict would look the same as before.
    local pings=0
    [[ -f "${runs}/${run_dir}/ue-keepalive.log" ]] && \
      pings="$(grep -c 'icmp_seq' "${runs}/${run_dir}/ue-keepalive.log" 2>/dev/null || echo 0)"
    printf '%-12s exit=%-3s verdict=%-10s keepalive_replies=%-5s run=%s\n' \
      "$label" "$status" "$verdict" "$pings" "$run_dir" | tee -a "${out}/summary.txt"
  else
    printf '%-12s exit=%-3s verdict=%s\n' "$label" "$status" "$verdict" | tee -a "${out}/summary.txt"
  fi
  python3 - "$out" "$label" "$status" "$verdict" "$run_dir" <<'PY'
import json, pathlib, sys
out, label, status, verdict, run_dir = sys.argv[1:]
path = pathlib.Path(out) / 'stages.json'
data = json.loads(path.read_text()) if path.exists() else {}
kpis = pathlib.Path(out) / f'{label}.kpis.json'
data[label] = {'exit': int(status), 'verdict': verdict, 'run_dir': run_dir,
               'backends': None,
               'kpis': json.loads(kpis.read_text()) if kpis.exists() else None}
path.write_text(json.dumps(data, indent=2))
PY
}

run_arm cpu-baseline env -u OCUDU_NATIVE_GNB_ACCELERATION \
  bash "${repo_root}/scripts/native/run-ocudu-legacy-1x1.sh"
run_arm "$stage" env OCUDU_NATIVE_GNB_ACCELERATION="$stage" \
  bash "${script_dir}/run-ocudu-cuda-1x1.sh"

echo
python3 "${script_dir}/compare-c4-stages.py" "${out}/stages.json" | tee -a "${out}/summary.txt"
echo "c4_bler_evidence=${out}"
