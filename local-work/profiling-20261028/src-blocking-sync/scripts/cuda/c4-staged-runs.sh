#!/usr/bin/env bash
# C4: raise the acceleration ladder one rung at a time and record each rung.
#
# The exit gate for C4 is not "the top of the ladder works". It asks that every
# rung pass the gate, that the runtime log show the backend actually selected at
# that rung rather than a quiet fall back to host, and that BLER and SINR track
# the CPU build. Running only `disabled` and `all` proves neither the rungs in
# between nor which rung a regression came from.
#
# The CPU baseline runs first, with no acceleration environment at all, and is
# what every rung is compared against.
#
#   OCUDU_CUDA_C4_STAGES  space-separated subset, default: the whole ladder
set -uo pipefail
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"
source "${repo_root}/scripts/native/env.sh"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
out="${OCUDU_NATIVE_ROOT}/results/cuda-rebuild/c4-staged-${stamp}"
mkdir -p "$out"
stages="${OCUDU_CUDA_C4_STAGES:-disabled low-phy-rx low-phy-tx pusch pdsch prach all}"

run_one() { # label  gate-command...
  local label="$1"; shift
  local log="${out}/${label}.gate.log"
  echo "########## ${label}"
  ( "$@" ) >"$log" 2>&1
  local status="$?"
  local summary run_dir verdict="unknown" backend="n/a" counters=""
  summary="$(sed -n 's/.*summary="\([^"]*\)".*/\1/p;s/^summary=\(.*\)$/\1/p' "$log" | tail -1)"
  if [[ -n "$summary" && -f "$summary" ]]; then
    run_dir="$(dirname "$summary")"
    verdict="$(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('status','?'))" "$summary" 2>/dev/null || echo '?')"
    counters="$(grep -o 'tx_pulls=[0-9]* rx_requests=[0-9]* rx_starvations=[0-9]* tx_queue_overflows=[0-9]* tx_sequence_gaps=[0-9]* zmq_errors=[0-9]*' "$log" | tail -1)"
    local gnb_log="${OCUDU_NATIVE_ROOT}/results/logs/ocudu-interop/$(basename "$run_dir")/gnb-internal.log"
    if [[ -f "$gnb_log" ]]; then
      python3 "${script_dir}/summarize-phy-kpis.py" --json "$gnb_log" >"${out}/${label}.kpis.json" 2>/dev/null
      # Scored against what the runtime log says was selected, not against
      # survival: a quiet host fallback attaches and pings just as happily.
      if [[ "$label" != "cpu-baseline" ]]; then
        python3 "${script_dir}/verify-stage-backends.py" --json "$label" "$gnb_log" \
          >"${out}/${label}.backends.json" 2>/dev/null
        backend="$(python3 "${script_dir}/verify-stage-backends.py" "$label" "$gnb_log" 2>/dev/null)"
      else
        backend='n/a (CPU baseline)'
      fi
    fi
  fi
  printf '%-12s exit=%-3s verdict=%-16s backend=%s\n' "$label" "$status" "$verdict" "$backend" | tee -a "${out}/summary.txt"
  [[ -n "$counters" ]] && printf '%-12s %s\n' '' "$counters" | tee -a "${out}/summary.txt"
  python3 - "$out" "$label" "$status" "$verdict" "$backend" "$summary" <<'PY'
import json, pathlib, sys
out, label, status, verdict, backend, summary = sys.argv[1:]
path = pathlib.Path(out) / 'stages.json'
data = json.loads(path.read_text()) if path.exists() else {}
def load(name):
    f = pathlib.Path(out) / f'{label}.{name}.json'
    return json.loads(f.read_text()) if f.exists() else None
data[label] = {'exit': int(status), 'verdict': verdict, 'backend': backend,
               'attach_summary': summary,
               'backends': load('backends'), 'kpis': load('kpis')}
path.write_text(json.dumps(data, indent=2))
PY
}

# Baseline: the pre-existing CPU gate, nothing set.
run_one cpu-baseline env -u OCUDU_NATIVE_GNB_ACCELERATION \
  bash "${repo_root}/scripts/native/run-ocudu-legacy-1x1.sh"

for stage in $stages; do
  run_one "$stage" env OCUDU_NATIVE_GNB_ACCELERATION="$stage" \
    bash "${script_dir}/run-ocudu-cuda-1x1.sh"
done

echo
echo "=== CPU 대비 비교 ==="
python3 "${script_dir}/compare-c4-stages.py" "${out}/stages.json" | tee -a "${out}/summary.txt"
echo "c4_staged_evidence=${out}"
