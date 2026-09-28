#!/usr/bin/env bash
set -uo pipefail

# Recurring check for the local OAI patches (oai-local-patches.sh).
#
# Static part (seconds, no GPU):
#   - each patch file matches its recorded sha256
#   - each patch still applies to the pinned OAI tree (patch --dry-run)
#   - the built artifacts carry manifests for this pin and these patches
#     (builds/oai-zmq-s9/MODULE-MANIFEST.txt, builds/oai-zmq-local/BUILD-MANIFEST.txt)
#
# --probe (about 6 minutes, uses the GPU; run it alone on the device):
#   one short OAI 2x2 run per side, and each patch must show its defect without
#   it and the fix with it:
#     ZMQ reply-poll  stock module -> real-time factor < 0.5; patched -> > 0.9
#     MMSE scale      stock UE at 20 dB back-off -> rank-2 NACK > 20%;
#                     patched UE -> NACK < 5%
#
# Usage (as container root, like the gates):
#   OCUDU_NATIVE_ROOT=... bash scripts/native/check-oai-local-patches.sh [--probe]
# Exit status 0 only if every check passes.

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"
# shellcheck source=oai-local-patches.sh
source "${script_dir}/oai-local-patches.sh"

native_root="${OCUDU_NATIVE_ROOT:?set OCUDU_NATIVE_ROOT}"
pinned="${native_root}/src/oai"
probe=0
[[ "${1:-}" == "--probe" ]] && probe=1
failures=0

report()
{
  local status="$1" what="$2" detail="$3"
  printf '%-4s %-44s %s\n' "${status}" "${what}" "${detail}"
  [[ "${status}" == PASS ]] || failures=$((failures + 1))
}

check_patch()
{
  local entry="$1" name want got file
  name="${entry%%:*}"
  want="${entry##*:}"
  file="${script_dir}/patches/${name}"
  got="$(sha256sum "${file}" 2>/dev/null | cut -d' ' -f1)"
  if [[ "${got}" == "${want}" ]]; then
    report PASS "${name} sha256" "${got:0:12}"
  else
    report FAIL "${name} sha256" "have ${got:-missing}, recorded ${want:0:12}"
  fi
  if patch -d "${pinned}" -p1 --dry-run -s <"${file}" >/dev/null 2>&1; then
    report PASS "${name} applies to pin" "${OAI_LOCAL_PIN:0:8}"
  else
    report FAIL "${name} applies to pin" "patch --dry-run failed against ${pinned}"
  fi
}

pin_now="$(git -C "${pinned}" rev-parse HEAD 2>/dev/null)"
if [[ "${pin_now}" == "${OAI_LOCAL_PIN}" ]] && git -C "${pinned}" diff --quiet; then
  report PASS "pinned tree" "${OAI_LOCAL_PIN:0:8}, clean"
else
  report FAIL "pinned tree" "HEAD ${pin_now:-?}, expected ${OAI_LOCAL_PIN:0:8} and no local changes"
fi
for entry in "${OAI_LOCAL_ZMQ_PATCHES[@]}" "${OAI_LOCAL_UE_PATCHES[@]}"; do
  check_patch "${entry}"
done

zmq_manifest="${native_root}/builds/oai-zmq-s9/MODULE-MANIFEST.txt"
zmq_sha="${OAI_LOCAL_ZMQ_PATCHES[0]##*:}"
if grep -qx "oai_pin=${OAI_LOCAL_PIN}" "${zmq_manifest}" 2>/dev/null && \
   grep -qx "patch_sha256=${zmq_sha}" "${zmq_manifest}" && \
   grep -qx "module_sha256=$(sha256sum "${native_root}/builds/oai-zmq-s9/liboai_zmqdevif.so" | cut -d' ' -f1)" "${zmq_manifest}"; then
  report PASS "builds/oai-zmq-s9 manifest" "pin, patch and module hashes match"
else
  report FAIL "builds/oai-zmq-s9 manifest" "missing or stale; run build-oai-zmq-module.sh patched"
fi
ue_manifest="${native_root}/builds/oai-zmq-local/BUILD-MANIFEST.txt"
ue_ok=1
grep -qx "oai_pin=${OAI_LOCAL_PIN}" "${ue_manifest}" 2>/dev/null || ue_ok=0
for entry in "${OAI_LOCAL_UE_PATCHES[@]}"; do
  grep -qx "patch=${entry%%:*} sha256=${entry##*:}" "${ue_manifest}" 2>/dev/null || ue_ok=0
done
grep -qx "nr_uesoftmodem_sha256=$(sha256sum "${native_root}/builds/oai-zmq-local/nr-uesoftmodem" 2>/dev/null | cut -d' ' -f1)" \
  "${ue_manifest}" 2>/dev/null || ue_ok=0
if [[ "${ue_ok}" == 1 ]]; then
  report PASS "builds/oai-zmq-local manifest" "pin, patches and binary hash match"
else
  report FAIL "builds/oai-zmq-local manifest" "missing or stale; run build-oai-ue-local.sh"
fi

if [[ "${probe}" == 1 ]]; then
  run_probe()
  {
    # $1 label, then env assignments; prints the report directory.
    local label="$1"
    shift
    local log
    log="$(mktemp /tmp/oai-local-probe.XXXXXX)"
    env HOME=/root OCUDU_NATIVE_ROOT="${native_root}" "$@" \
      OAI2X2_PATH=broker OAI2X2_MAX_RANK=2 OAI2X2_BROKER_SECONDS=55 OAI2X2_IPERF_SECONDS=8 \
      OAI2X2_IPERF_RATE=200M OAI2X2_LABEL="patch-check ${label}" \
      OAI2X2_TOPOLOGY="${repo_root}/examples/native/topology.ocudu.oai-2x2-unitary.cuda.yaml" \
      bash "${script_dir}/run-ocudu-oai-2x2.sh" >"${log}" 2>&1
    grep -o 'report=[^ ]*' "${log}" | tail -1 | cut -d= -f2
    rm -f "${log}"
  }
  field()
  {
    /usr/bin/python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])' "$1/rank-summary.json" "$2" 2>/dev/null
  }
  others="$(nvidia-smi --query-compute-apps=pid,process_name --format=csv,noheader 2>/dev/null | wc -l)"
  [[ "${others}" == 0 ]] || printf 'note: %s other GPU process(es) running during the probe\n' "${others}"

  # ZMQ reply-poll: same UE, the module is the only difference (24 dB, clean link).
  for side in stock patched; do
    dir="$(run_probe "zmq-${side}" OCUDU_NATIVE_OAI_ZMQ_MODULE="${side}" OCUDU_NATIVE_OAI_UE=local OAI2X2_TX_BACKOFF_DB=24)"
    rt="$(field "${dir}" realtime_factor)"
    if [[ "${side}" == stock ]]; then
      awk -v v="${rt:-9}" 'BEGIN{exit !(v < 0.5)}' && report PASS "zmq reply-poll: stock shows defect" "realtime_factor=${rt}" \
        || report FAIL "zmq reply-poll: stock shows defect" "realtime_factor=${rt:-none} (expected < 0.5) ${dir}"
    else
      awk -v v="${rt:-0}" 'BEGIN{exit !(v > 0.9)}' && report PASS "zmq reply-poll: patched fixes it" "realtime_factor=${rt}" \
        || report FAIL "zmq reply-poll: patched fixes it" "realtime_factor=${rt:-none} (expected > 0.9) ${dir}"
    fi
  done
  # MMSE scale: patched module both sides, the UE build is the only difference (20 dB).
  for side in stock local; do
    dir="$(run_probe "mmse-${side}" OCUDU_NATIVE_OAI_ZMQ_MODULE=patched OCUDU_NATIVE_OAI_UE="${side}" OAI2X2_TX_BACKOFF_DB=20)"
    nack="$(field "${dir}" nack_ratio)"
    if [[ "${side}" == stock ]]; then
      awk -v v="${nack:-0}" 'BEGIN{exit !(v > 0.20)}' && report PASS "mmse scale: stock UE shows defect" "rank-2 NACK=${nack}" \
        || report FAIL "mmse scale: stock UE shows defect" "rank-2 NACK=${nack:-none} (expected > 0.20) ${dir}"
    else
      awk -v v="${nack:-1}" 'BEGIN{exit !(v < 0.05)}' && report PASS "mmse scale: patched UE fixes it" "rank-2 NACK=${nack}" \
        || report FAIL "mmse scale: patched UE fixes it" "rank-2 NACK=${nack:-none} (expected < 0.05) ${dir}"
    fi
  done
fi

printf 'result=%s failures=%d\n' "$([[ "${failures}" == 0 ]] && echo pass || echo fail)" "${failures}"
[[ "${failures}" == 0 ]]
