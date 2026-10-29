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
  export OCUDU_NATIVE_PLATFORM_PROFILE OCUDU_NATIVE_GNB_CPUS OCUDU_NATIVE_BROKER_CPUS OCUDU_NATIVE_NRUE_CPUS \
    OCUDU_NATIVE_BROKER_ENV
}

# oai_gate_ue_rx_gain
#   The OAI ZMQ radio has no AGC, and the nrUE's fixed-point receive chain is
#   sized for ~TARGET_RX_POWER (50 dB). An OCUDU gNB at its default 12 dB
#   back-off reaches the UE near 55 dB, where 64QAM PDSCH NACKs 69-89% at rank
#   1 and rank 2 (SPARK_MILESTONES.md S12). With the patched module
#   (oai-zmq-rx-gain.patch) the gate sets zmq.[0].rx_gain_db, the role an RF
#   receive gain plays on a radio: default -12 dB, i.e. the level of a 24 dB
#   gNB back-off, measured clean at rank 1 and 2.
#   OCUDU_NATIVE_OAI_UE_RX_GAIN_DB=<dB> overrides it (0 disables). The stock
#   module has no such parameter, so nothing is passed there.
#   Exports OAI_GATE_UE_RX_GAIN_DB (empty when not applied).
oai_gate_ue_rx_gain()
{
  OAI_GATE_UE_RX_GAIN_DB=""
  local value="${OCUDU_NATIVE_OAI_UE_RX_GAIN_DB:--12}"
  if [[ ! "${value}" =~ ^-?[0-9]+(\.[0-9]+)?$ ]]; then
    printf 'error: OCUDU_NATIVE_OAI_UE_RX_GAIN_DB must be a number of dB\n' >&2
    return 1
  fi
  if [[ "${OAI_ZMQ_MODULE_VARIANT:-}" == "patched" ]]; then
    OAI_GATE_UE_RX_GAIN_DB="${value}"
  elif [[ -n "${OCUDU_NATIVE_OAI_UE_RX_GAIN_DB:-}" && "${OAI_ZMQ_MODULE_VARIANT:-}" == "stock" ]]; then
    printf 'error: OCUDU_NATIVE_OAI_UE_RX_GAIN_DB needs the patched ZMQ module\n' >&2
    return 1
  elif [[ -n "${OCUDU_NATIVE_OAI_UE_RX_GAIN_DB:-}" ]]; then
    OAI_GATE_UE_RX_GAIN_DB="${value}"  # custom module: the caller asked for it
  fi
  export OAI_GATE_UE_RX_GAIN_DB
}

# oai_gate_ue_fo_comp
#   The OAI nrUE corrects its carrier offset by retuning the radio
#   (nrue_ru_set_freq), and the ZMQ radio's set_freq is a no-op, so without
#   continuous FO compensation a channel CFO is never removed from the DL
#   samples. The legacy 1x1 channel carries 125 Hz: the phase drifts ~0.06 rad
#   per symbol away from the DMRS, QPSK survives and 64QAM PDSCH NACKs ~60%
#   (M6 §8.11). --cont-fo-comp 1 rotates every DL symbol in software
#   (slot_fep_nr.c) by the PBCH-tracked offset and pre-compensates the UL.
#   OCUDU_NATIVE_OAI_UE_CONT_FO_COMP=0|1|2|3 overrides it (0 disables).
#   Exports OAI_GATE_UE_CONT_FO_COMP (empty when disabled).
oai_gate_ue_fo_comp()
{
  local value="${OCUDU_NATIVE_OAI_UE_CONT_FO_COMP:-1}"
  if [[ ! "${value}" =~ ^[0-3]$ ]]; then
    printf 'error: OCUDU_NATIVE_OAI_UE_CONT_FO_COMP must be 0, 1, 2 or 3\n' >&2
    return 1
  fi
  OAI_GATE_UE_CONT_FO_COMP=""
  [[ "${value}" != 0 ]] && OAI_GATE_UE_CONT_FO_COMP="${value}"
  export OAI_GATE_UE_CONT_FO_COMP
}

# oai_gate_defaults_line: one log line naming every default this run applied.
oai_gate_defaults_line()
{
  printf 'event=oai_gate_defaults oai_zmq_module=%s ue_rx_gain_db=%s ue_cont_fo_comp=%s oai_ue=%s platform=%s gnb_cpus=%s broker_cpus=%s nrue_cpus=%s broker_env=%s mps=%s\n' \
    "${OAI_ZMQ_MODULE_VARIANT:-?}" "${OAI_GATE_UE_RX_GAIN_DB:-none}" "${OAI_GATE_UE_CONT_FO_COMP:-off}" "${OAI_UE_VARIANT:-n/a}" "${OCUDU_NATIVE_PLATFORM_PROFILE:-none}" \
    "${OCUDU_NATIVE_GNB_CPUS:-any}" "${OCUDU_NATIVE_BROKER_CPUS:-any}" "${OCUDU_NATIVE_NRUE_CPUS:-any}" \
    "${OCUDU_NATIVE_BROKER_ENV:-none}" "$([[ -n "${CUDA_MPS_PIPE_DIRECTORY:-}" ]] && echo on || echo off)"
}
