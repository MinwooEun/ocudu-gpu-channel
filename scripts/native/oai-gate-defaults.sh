# shellcheck shell=bash
# Gate defaults that keep an OAI run at real time (SPARK_MILESTONES.md S9-S11),
# shared by the OAI 1x1 and 2x2 gates. Each has an opt-out, and each gate
# records what it applied in its run parameters.
#
# Call order in a gate, after its own argument/path checks:
#   oai_gate_mps_reexec <gnb_binary> <gate script> || usage_error ...
#   resolve_oai_zmq_module <native_root> (oai-local-patches.sh) || ...
#   oai_gate_platform || usage_error ...
# MPS comes first because it re-executes the gate; the module and placement
# are then resolved once, in the re-executed process, from a clean slate.

OAI_GATE_DEFAULTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# oai_gate_mps_reexec <gnb_binary> <script> [args...]
#   A CUDA gNB shares the GPU with the broker; without MPS the two contexts
#   time-slice and the broker's kernel start waits ~150 us at p99 (S9). If MPS
#   applies and is not active yet, exec the gate again under one MPS server
#   (with-cuda-mps.py always shuts it down). Otherwise return with
#   OAI_GATE_GNB_USES_CUDA set.
#   OCUDU_NATIVE_MPS=auto (default: only for a CUDA gNB) | on | off.
oai_gate_mps_reexec()
{
  local gnb_binary="$1"
  shift
  local choice="${OCUDU_NATIVE_MPS:-auto}"
  if [[ ! "${choice}" =~ ^(auto|on|off)$ ]]; then
    printf 'error: OCUDU_NATIVE_MPS must be auto, on or off\n' >&2
    return 1
  fi
  OAI_GATE_GNB_USES_CUDA=0
  ldd "${gnb_binary}" 2>/dev/null | grep -Eq 'libcudart|libcuda\.so' && OAI_GATE_GNB_USES_CUDA=1
  export OAI_GATE_GNB_USES_CUDA
  if [[ -z "${CUDA_MPS_PIPE_DIRECTORY:-}" ]] && \
     [[ "${choice}" == "on" || ( "${choice}" == "auto" && "${OAI_GATE_GNB_USES_CUDA}" -eq 1 ) ]]; then
    export OCUDU_NATIVE_MPS_REASON="${choice}:gnb_uses_cuda=${OAI_GATE_GNB_USES_CUDA}"
    exec /usr/bin/python3 "${OAI_GATE_DEFAULTS_DIR}/../cuda/with-cuda-mps.py" -- bash "$@"
  fi
}

# oai_gate_platform
#   CPU placement from platform-profiles.json (a no-op on an unknown host;
#   OCUDU_NATIVE_PLATFORM=none turns it off, per-role *_CPUS override it).
#   Exports OCUDU_NATIVE_PLATFORM_PROFILE and OCUDU_NATIVE_{GNB,BROKER,NRUE}_CPUS,
#   which the inner scripts turn into `taskset -c`.
oai_gate_platform()
{
  local shell_assignments
  shell_assignments="$(/usr/bin/python3 "${OAI_GATE_DEFAULTS_DIR}/platform-profile.py" --shell)" || {
    printf 'error: platform profile resolution failed\n' >&2
    return 1
  }
  eval "${shell_assignments}"
  export OCUDU_NATIVE_PLATFORM_PROFILE OCUDU_NATIVE_GNB_CPUS OCUDU_NATIVE_BROKER_CPUS OCUDU_NATIVE_NRUE_CPUS
}

# oai_gate_defaults_line: one log line naming every default this run applied.
oai_gate_defaults_line()
{
  printf 'event=oai_gate_defaults oai_zmq_module=%s oai_ue=%s platform=%s gnb_cpus=%s broker_cpus=%s nrue_cpus=%s mps=%s\n' \
    "${OAI_ZMQ_MODULE_VARIANT:-?}" "${OAI_UE_VARIANT:-n/a}" "${OCUDU_NATIVE_PLATFORM_PROFILE:-none}" \
    "${OCUDU_NATIVE_GNB_CPUS:-any}" "${OCUDU_NATIVE_BROKER_CPUS:-any}" "${OCUDU_NATIVE_NRUE_CPUS:-any}" \
    "$([[ -n "${CUDA_MPS_PIPE_DIRECTORY:-}" ]] && echo on || echo off)"
}
