#!/usr/bin/env bash
# C5: paired CPU/CUDA runs inside one measurement envelope.
#
# The envelope is the deliverable, not a speedup. C5's exit gate asks for
# paired runs with MPS and P-core pinning applied identically to the baseline,
# the accelerated arm AND the shared services, with the affinity that actually
# took effect recorded, and with failed measurements kept. It explicitly does
# not ask whether CUDA is faster -- at this fixture's 20 MHz single layer the
# vendor's own numbers put the GPU below 1.0x, so a speedup is not expected and
# its absence is not a finding.
#
# Both arms are pinned and run under the same isolated MPS server. The baseline
# is pinned too even though its gNB uses no CUDA: the broker does, the P/E core
# mix on this CPU moves the baseline by 6-7% on its own, and a comparison
# between two different envelopes measures the envelopes.
#
# Arms alternate (A B A B ...) so that slow drift -- thermal, background load --
# lands on both rather than on whichever ran second.
#
#   OCUDU_CUDA_C5_REPEATS     pairs to run, default 2
#   OCUDU_CUDA_C5_PCORES      cpu list for taskset, default 0-7 (this 285K's P cores)
#   OCUDU_CUDA_C5_STAGE       accelerated arm's stage, default all
set -uo pipefail
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"
source "${repo_root}/scripts/native/env.sh"
repeats="${OCUDU_CUDA_C5_REPEATS:-2}"
pcores="${OCUDU_CUDA_C5_PCORES:-0-7}"
stage="${OCUDU_CUDA_C5_STAGE:-all}"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
out="${OCUDU_NATIVE_ROOT}/results/cuda-rebuild/c5-paired-${stamp}"
runs="${OCUDU_NATIVE_ROOT}/results/logs/ocudu-interop"
mkdir -p "$out"

# Record the envelope itself, so a later reader does not have to trust that the
# run was pinned to the cores this comment claims are the fast ones.
{
  echo "pcores=${pcores}"
  echo "stage=${stage}"
  echo "repeats=${repeats}"
  for cpu in $(seq 0 23); do
    [[ -r "/sys/devices/system/cpu/cpu${cpu}/cpu_capacity" ]] || continue
    echo "cpu${cpu}_capacity=$(cat "/sys/devices/system/cpu/cpu${cpu}/cpu_capacity")"
  done
  nvidia-smi --query-gpu=name,driver_version,clocks.max.sm --format=csv,noheader
} >"${out}/envelope.txt" 2>&1

run_arm() { # label  env-assignments...
  local label="$1"; shift
  local gate_log="${out}/${label}.gate.log"
  echo "########## ${label}"

  python3 "${script_dir}/sample-run-telemetry.py" --out "$out" --label "$label" \
    --interval 1 --deadline-seconds 400 --settle-seconds 90 >"${out}/${label}.affinity.log" 2>&1 &
  local sampler="$!"

  # taskset wraps everything the gate starts -- gNB, broker, srsUE, 5GC, mongod
  # all inherit the mask, which is what "applied to the shared services" means.
  taskset -c "${pcores}" python3 "${script_dir}/with-cuda-mps.py" -- \
    env "$@" "${gate_cmd[@]}" >"$gate_log" 2>&1
  local status="$?"
  wait "$sampler" 2>/dev/null

  local summary run_dir=""
  summary="$(sed -n 's/.*summary="\([^"]*\)".*/\1/p;s/^summary=\(.*\)$/\1/p' "$gate_log" | tail -1)"
  [[ -n "$summary" && -f "$summary" ]] && run_dir="$(basename "$(dirname "$summary")")"

  # A failed measurement is kept and named, not re-run until it looks good.
  local verdict='no-run'
  if [[ -n "$run_dir" ]]; then
    verdict="$(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('status','?'))" "$summary" 2>/dev/null || echo '?')"
    python3 "${script_dir}/summarize-broker-metrics.py" --json "${runs}/${run_dir}/broker.log" \
      >"${out}/${label}.broker.json" 2>/dev/null
    python3 "${script_dir}/summarize-phy-kpis.py" --json "${runs}/${run_dir}/gnb-internal.log" \
      >"${out}/${label}.phy.json" 2>/dev/null
  fi
  printf '%-16s exit=%-3s verdict=%-10s run=%s\n' "$label" "$status" "$verdict" "${run_dir:-none}" \
    | tee -a "${out}/summary.txt"
  python3 - "$out" "$label" "$status" "$verdict" "$run_dir" <<'PY'
import json, pathlib, sys
out, label, status, verdict, run_dir = sys.argv[1:]
path = pathlib.Path(out) / 'runs.json'
data = json.loads(path.read_text()) if path.exists() else {}
def load(name):
    f = pathlib.Path(out) / f'{label}.{name}.json'
    return json.loads(f.read_text()) if f.exists() else None
data[label] = {'exit': int(status), 'verdict': verdict, 'run_dir': run_dir,
               'broker': load('broker'), 'phy': load('phy'), 'affinity': load('affinity')}
path.write_text(json.dumps(data, indent=2))
PY
}

for ((i = 1; i <= repeats; i++)); do
  gate_cmd=("${repo_root}/scripts/native/run-ocudu-legacy-1x1.sh")
  run_arm "cpu-${i}" -u OCUDU_NATIVE_GNB_ACCELERATION
  gate_cmd=("${script_dir}/run-ocudu-cuda-1x1.sh")
  run_arm "cuda-${i}" OCUDU_NATIVE_GNB_ACCELERATION="${stage}"
done

echo
python3 "${script_dir}/report-c5-envelope.py" "${out}/runs.json" "${out}/envelope.txt" | tee -a "${out}/summary.txt"
echo "c5_evidence=${out}"
