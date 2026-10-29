#!/usr/bin/env bash
# Inner half of the native TDD multi-UE gate with OAI nrUEs (X3/X4). Runs
# INSIDE the user + network + mount namespace created by
# run-ocudu-oai-multi-ue.sh; never invoke it directly.
#
# Structure: run-ocudu-multi-ue-inner.sh (srsUE) with the UE side of
# run-ocudu-oai-1x1-inner.sh (OAI nrUE) once per UE:
#   - one nested netns per UE (ue1, ue2) and one veth pair per UE into it
#     (10.201.0.1/.2 for ue0, 10.201.1.1/.2 for ue1), because the OAI nrUE has
#     no netns option: the whole process runs in its namespace and its ZMQ
#     path crosses the veth to the broker in this namespace;
#   - OAI verdict tokens (see attach_evidence below for what is counted).
set -uo pipefail

repo_root="" native_root="" config_dir="" log_dir="" report_dir="" netns_dir="" timestamp=""
physical_gpu="0" channel_build="" gnb_binary="" parent_netns="" parent_mntns="" outer_uid=""
control_endpoint="" telemetry_endpoint="" sionna_python="" sionna_bridge=""
sionna_scenario_config="" sionna_status_jsonl="" sionna_update_hz="10" sionna_ready_seconds="180"
run_duration_seconds="240" strict_realtime="0" ue_exec="" root_exec=""
wire_capture_samples="0" wire_capture_skip_seconds="60" stagger_seconds="0"

usage_error()
{
  printf 'error: %s\n' "$1" >&2
  exit 2
}

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --repo-root) repo_root="${2:-}"; shift 2 ;;
    --native-root) native_root="${2:-}"; shift 2 ;;
    --config-dir) config_dir="${2:-}"; shift 2 ;;
    --log-dir) log_dir="${2:-}"; shift 2 ;;
    --report-dir) report_dir="${2:-}"; shift 2 ;;
    --netns-dir) netns_dir="${2:-}"; shift 2 ;;
    --timestamp) timestamp="${2:-}"; shift 2 ;;
    --physical-gpu) physical_gpu="${2:-}"; shift 2 ;;
    --channel-build) channel_build="${2:-}"; shift 2 ;;
    --gnb-binary) gnb_binary="${2:-}"; shift 2 ;;
    --parent-netns) parent_netns="${2:-}"; shift 2 ;;
    --parent-mntns) parent_mntns="${2:-}"; shift 2 ;;
    --outer-uid) outer_uid="${2:-}"; shift 2 ;;
    --control-endpoint) control_endpoint="${2:-}"; shift 2 ;;
    --telemetry-endpoint) telemetry_endpoint="${2:-}"; shift 2 ;;
    --sionna-python) sionna_python="${2:-}"; shift 2 ;;
    --sionna-bridge) sionna_bridge="${2:-}"; shift 2 ;;
    --sionna-scenario-config) sionna_scenario_config="${2:-}"; shift 2 ;;
    --sionna-status-jsonl) sionna_status_jsonl="${2:-}"; shift 2 ;;
    --sionna-update-hz) sionna_update_hz="${2:-}"; shift 2 ;;
    --run-duration-seconds) run_duration_seconds="${2:-}"; shift 2 ;;
    --strict-realtime) strict_realtime="${2:-}"; shift 2 ;;
    --ue-exec) ue_exec="${2:-}"; shift 2 ;;
    --root-exec) root_exec="${2:-}"; shift 2 ;;
    --wire-capture-samples) wire_capture_samples="${2:-}"; shift 2 ;;
    --wire-capture-skip-seconds) wire_capture_skip_seconds="${2:-}"; shift 2 ;;
    --stagger-seconds) stagger_seconds="${2:-}"; shift 2 ;;
    *) usage_error "unknown argument: $1" ;;
  esac
done

for required in "${repo_root}" "${native_root}" "${config_dir}" "${log_dir}" "${report_dir}" "${netns_dir}"; do
  [[ "${required}" == /* && -d "${required}" && ! -L "${required}" ]] || usage_error "invalid run directory: ${required}"
done
[[ "${timestamp}" =~ ^[0-9]{8}T[0-9]{6}Z$ ]] || usage_error "invalid --timestamp"
[[ "${outer_uid}" =~ ^(0|[1-9][0-9]*)$ ]] || usage_error "invalid --outer-uid"
[[ "${physical_gpu}" =~ ^(0|[1-9][0-9]*)$ ]] || usage_error "invalid --physical-gpu"
[[ "${control_endpoint}" == ipc://* && "${telemetry_endpoint}" == ipc://* ]] || usage_error "control and telemetry endpoints must be ipc://"
[[ -x "${sionna_python}" ]] || usage_error "missing Sionna Python: ${sionna_python}"
[[ -f "${sionna_bridge}" ]] || usage_error "missing Sionna bridge: ${sionna_bridge}"
[[ -f "${sionna_scenario_config}" ]] || usage_error "missing Sionna scenario: ${sionna_scenario_config}"
[[ "${sionna_update_hz}" =~ ^[0-9]+(\.[0-9]+)?$ ]] || usage_error "invalid Sionna update rate"
[[ "${run_duration_seconds}" =~ ^[1-9][0-9]*$ && "${run_duration_seconds}" -ge 160 ]] || usage_error "invalid run duration"
[[ "${strict_realtime}" =~ ^[01]$ ]] || usage_error "invalid strict-realtime flag"
[[ "${wire_capture_samples}" =~ ^(0|[1-9][0-9]*)$ && "${wire_capture_skip_seconds}" =~ ^(0|[1-9][0-9]*)$ ]] || usage_error "invalid wire capture request"
[[ "${stagger_seconds}" =~ ^(0|[1-9][0-9]*)$ ]] || usage_error "invalid stagger"
[[ "$(readlink /proc/self/ns/net)" != "${parent_netns}" ]] || usage_error "network namespace was not isolated"
[[ "$(readlink /proc/self/ns/mnt)" != "${parent_mntns}" ]] || usage_error "mount namespace was not isolated"
awk -v uid="${outer_uid}" '$1 == 0 && $2 == uid && $3 == 1 { found = 1 } END { exit !found }' /proc/self/uid_map || \
  usage_error "user namespace does not contain the exact root mapping"
for command_name in ip mount umount nsenter ps setpriv taskset; do
  command -v "${command_name}" >/dev/null 2>&1 || usage_error "missing command: ${command_name}"
done
[[ -x /usr/bin/python3 ]] || usage_error "missing /usr/bin/python3"

# Must agree with render-multi-ue-configs.py UES (ports, IPs) and with
# render-oai-multi-ue-configs.py VETH (veth addresses). Two UEs.
ue_ids=(ue0 ue1)
ue_netns=(ue1 ue2)
ue_ipv4=(10.45.1.2 10.45.1.3)
ue_tx_port=(2101 2103)
ue_rx_port=(2100 2102)
ue_veth_host=(10.201.0.1 10.201.1.1)
ue_veth_ue=(10.201.0.2 10.201.1.2)
ue_gateway="10.45.1.1"
# Per-UE CPU lists from the outer gate ("cpus0;cpus1"), empty = unpinned.
IFS=';' read -r -a ue_cpus <<<"${OCUDU_NATIVE_OAI_MUE_UE_CPUS:-}"
attach_strict="${OCUDU_NATIVE_ATTACH_STRICT:-1}"

mount_active=0
root_tun=""
declare -a created_netns=() created_veths=()
declare -a process_names=() process_pids=() process_pgids=()
started_pid=""

process_running()
{
  local state
  state="$(ps -o stat= -p "$1" 2>/dev/null | awk '{print $1}')"
  [[ -n "${state}" && "${state:0:1}" != "Z" ]]
}

start_group()
{
  local name="$1" output="$2"; shift 2
  local gate_lock_fd="${OCUDU_NATIVE_GATE_LOCK_FD:-}"
  if [[ "${gate_lock_fd}" =~ ^[0-9]+$ && "${gate_lock_fd}" -gt 2 ]]; then
    setsid stdbuf -oL -eL "$@" >"${output}" 2>&1 {gate_lock_fd}>&- &
  else
    setsid stdbuf -oL -eL "$@" >"${output}" 2>&1 &
  fi
  started_pid="$!"
  process_names+=("${name}")
  process_pids+=("${started_pid}")
  process_pgids+=("${started_pid}")
}

group_alive()
{
  ps -eo pgid=,sid=,stat= | awk -v g="$1" '($1 == g || $2 == g) && $3 !~ /^Z/ { found = 1 } END { exit !found }'
}

signal_group()
{
  local signal="$1" pgid="$2" member
  kill -s "${signal}" -- "-${pgid}" >/dev/null 2>&1 || true
  for member in $(ps -eo pid=,sid= | awk -v g="${pgid}" '$2 == g { print $1 }'); do
    kill -s "${signal}" "${member}" >/dev/null 2>&1 || true
  done
}

stop_group()
{
  local index="$1"
  local pid="${process_pids[index]}" pgid="${process_pgids[index]}"
  local signal deadline
  [[ "${pid}" =~ ^[1-9][0-9]*$ && "${pgid}" =~ ^[1-9][0-9]*$ && "${pgid}" -gt 1 ]] || return 0
  if group_alive "${pgid}"; then
    for signal in INT TERM KILL; do
      signal_group "${signal}" "${pgid}"
      deadline=$((SECONDS + 4))
      while group_alive "${pgid}" && [[ "${SECONDS}" -lt "${deadline}" ]]; do sleep 0.1; done
      group_alive "${pgid}" || break
    done
    if group_alive "${pgid}"; then
      printf 'error: %s group %s remains alive after bounded KILL\n' "${process_names[index]}" "${pgid}" >&2
      return 124
    fi
  fi
  wait "${pid}" >/dev/null 2>&1 || true
  return 0
}

cleanup()
{
  local original_status="$?"
  set +e
  trap - EXIT INT TERM HUP
  local index wanted cleanup_failed=0
  for wanted in ue-exec root-exec broker nrue sionna gnb open5gs mongod; do
    for ((index=0; index<${#process_pids[@]}; index++)); do
      if [[ "${process_names[index]}" == "${wanted}"* ]]; then
        if stop_group "${index}"; then process_pids[index]="0"; else cleanup_failed=1; fi
      fi
    done
  done
  for ((index=${#process_pids[@]}-1; index>=0; index--)); do
    stop_group "${index}" || cleanup_failed=1
  done
  for name in "${created_netns[@]}"; do ip netns del "${name}" >/dev/null 2>&1 || true; done
  for name in "${created_veths[@]}"; do ip link del "${name}" >/dev/null 2>&1 || true; done
  [[ -n "${root_tun}" ]] && { ip link del "${root_tun}" >/dev/null 2>&1 || true; }
  [[ "${mount_active}" -eq 1 ]] && { umount /run/netns >/dev/null 2>&1 || true; }
  if [[ "${cleanup_failed}" -ne 0 && "${original_status}" -eq 0 ]]; then original_status=124; fi
  exit "${original_status}"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

wait_log()
{
  local file="$1" pattern="$2" pid="$3" timeout="$4"
  local deadline=$((SECONDS + timeout))
  while [[ "${SECONDS}" -lt "${deadline}" ]]; do
    grep -q -- "${pattern}" "${file}" 2>/dev/null && return 0
    process_running "${pid}" || return 1
    sleep 0.2
  done
  return 1
}

gnb="${gnb_binary:-${native_root}/builds/ocudu-zmq-release/apps/gnb/gnb}"
# nr-uesoftmodem: the pinned build (as the OAI 1x1 gate) unless
# OCUDU_NATIVE_OAI_UE=local asks for builds/oai-zmq-local (the 2x2 gate's UE
# PHY patches, checked by resolve_oai_ue_build). The ZMQ radio module is the
# outer gate's choice (OCUDU_NATIVE_OAI_SHLIBPATH, patched by default).
nrue_dir="${native_root}/builds/oai-zmq-release"
nrue_variant="${OCUDU_NATIVE_OAI_UE:-stock}"
if [[ "${nrue_variant}" == "local" ]]; then
  # shellcheck source=oai-local-patches.sh
  source "${repo_root}/scripts/native/oai-local-patches.sh"
  resolve_oai_ue_build "${native_root}" || usage_error "local OAI UE build selection failed"
  nrue_dir="${OAI2X2_NRUE_DIR}"
elif [[ "${nrue_variant}" != "stock" ]]; then
  usage_error "OCUDU_NATIVE_OAI_UE must be stock or local"
fi
nrue="${nrue_dir}/nr-uesoftmodem"
oai_build="${OCUDU_NATIVE_OAI_SHLIBPATH:-${native_root}/builds/oai-zmq-release}"
fivegc="${native_root}/builds/open5gs-v2.7.6/tests/app/5gc"
mongod="${native_root}/install/mongodb-6.0.29/bin/mongod"
broker="${channel_build}/ocudu-gpu-channel"
add_users="${native_root}/src/ocudu/docker/open5gs/add_users.py"
subscriber_verify="${repo_root}/scripts/native/verify-open5gs-subscribers-multi.py"
data_dir="${native_root}/data/ocudu-oai-multi-ue-native/${timestamp}"
uecap_file="${OCUDU_NATIVE_OAI_UECAP_FILE:-${config_dir}/uecap.xml}"
for binary in "${gnb}" "${nrue}" "${fivegc}" "${mongod}" "${broker}"; do
  [[ -x "${binary}" ]] || usage_error "missing executable: ${binary}"
done
[[ -f "${oai_build}/liboai_zmqdevif.so" ]] || usage_error "missing OAI ZMQ radio module in ${oai_build}"
[[ -f "${uecap_file}" ]] || usage_error "missing OAI UE capability file: ${uecap_file}"
[[ -f "${config_dir}/nrue-radio.args" ]] || usage_error "renderer did not write nrue-radio.args"
[[ -d "${data_dir}" ]] || usage_error "missing data dir: ${data_dir}"
# The bridge traces at the cell's carrier (TDD: one frequency for every
# direction, including the UE<->UE edges), read from the renderer's metadata.
carrier_hz="$(/usr/bin/python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["cell"]["carrier_hz"])' \
  "${config_dir}/oai-multi-ue-shape.json")" || usage_error "cannot read the carrier from oai-multi-ue-shape.json"
[[ "${carrier_hz}" =~ ^[1-9][0-9]*$ ]] || usage_error "invalid carrier_hz: ${carrier_hz}"
printf 'event=oai_multi_ue_inner nrue=%s zmq_module=%s uecap=%s carrier_hz=%s ue_cpus="%s"\n' \
  "${nrue}" "${oai_build}" "${uecap_file}" "${carrier_hz}" "${OCUDU_NATIVE_OAI_MUE_UE_CPUS:-}"

# --- namespace layout -------------------------------------------------------
mount --make-rprivate /
mount --bind "${netns_dir}" /run/netns
mount_active=1
ip link set lo up
root_tun="ogstun"
ip tuntap add dev "${root_tun}" mode tun
ip addr add 10.45.0.1/24 dev "${root_tun}"
ip addr add 10.45.1.1/24 dev "${root_tun}"
ip link set "${root_tun}" up
for index in "${!ue_ids[@]}"; do
  name="${ue_netns[index]}"
  ip netns add "${name}"
  created_netns+=("${name}")
  nsenter --net="/run/netns/${name}" -- ip link set lo up
  # The nrUE's ZMQ path to the broker: veth host side in this namespace, peer
  # inside the UE's namespace. Names are short (IFNAMSIZ) and per UE.
  veth="vethoai${index}"
  ip link add "${veth}" type veth peer name "${veth}p"
  created_veths+=("${veth}")
  ip link set "${veth}p" netns "${name}"
  ip addr add "${ue_veth_host[index]}/30" dev "${veth}"
  ip link set "${veth}" up
  nsenter --net="/run/netns/${name}" -- ip addr add "${ue_veth_ue[index]}/30" dev "${veth}p"
  nsenter --net="/run/netns/${name}" -- ip link set "${veth}p" up
  nsenter --net="/run/netns/${name}" -- ping -c 1 -W 2 "${ue_veth_host[index]}" >/dev/null || \
    usage_error "veth path to ${name} is not routable"
done

run_dir="${netns_dir%/netns}"
expand_exec_template()
{
  local text="$1"
  text="${text//\{log_dir\}/${log_dir}}"
  text="${text//\{run_dir\}/${run_dir}}"
  text="${text//\{config_dir\}/${config_dir}}"
  text="${text//\{ue_ids\}/${ue_ids[*]}}"
  text="${text//\{ue_ips\}/${ue_ipv4[*]}}"
  text="${text//\{ue_gateway\}/${ue_gateway}}"
  printf '%s' "${text}"
}
if [[ -n "${root_exec}" ]]; then
  root_exec_command="$(expand_exec_template "${root_exec}")"
  printf 'event=root_exec_start command=%q\n' "${root_exec_command}"
  start_group root-exec "${log_dir}/root-exec.log" bash -c "${root_exec_command}"
fi

# --- core -------------------------------------------------------------------
start_group mongod "${log_dir}/mongod-console.log" "${mongod}" \
  --dbpath "${data_dir}" --bind_ip 127.0.0.1 --port 27017 --logpath "${log_dir}/mongod.log"
/usr/bin/python3 - <<'PY' || usage_error "mongod did not accept connections"
import socket, time
deadline = time.monotonic() + 20
while time.monotonic() < deadline:
    try:
        with socket.create_connection(("127.0.0.1", 27017), timeout=.25):
            raise SystemExit(0)
    except OSError:
        time.sleep(.25)
raise SystemExit(2)
PY
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="${native_root}/src/open5gs:${PYTHONPATH:-}" /usr/bin/python3 "${add_users}" \
  --mongodb 127.0.0.1 --mongodb_port 27017 --subscriber_data "${config_dir}/subscriber.csv" \
  >"${log_dir}/subscriber-insert.log" 2>&1 || usage_error "subscriber insert failed"
/usr/bin/python3 "${subscriber_verify}" --subscriber-csv "${config_dir}/subscriber.csv" \
  >"${log_dir}/subscriber-verify.log" 2>&1 || usage_error "subscriber verification failed"
start_group open5gs "${log_dir}/open5gs.log" "${fivegc}" -c "${config_dir}/open5gs.yaml"
fivegc_pid="${started_pid}"
/usr/bin/python3 - <<'PY' || usage_error "Open5GS AMF did not come up"
import socket, time
deadline = time.monotonic() + 30
while time.monotonic() < deadline:
    try:
        with socket.create_connection(("127.0.0.20", 7777), timeout=.25):
            raise SystemExit(0)
    except OSError:
        time.sleep(.25)
raise SystemExit(2)
PY

# --- broker, Sionna, gNB, UEs ----------------------------------------------
broker_pin=() gnb_pin=()
[[ -n "${OCUDU_NATIVE_BROKER_CPUS:-}" ]] && broker_pin=(taskset -c "${OCUDU_NATIVE_BROKER_CPUS}")
[[ -n "${OCUDU_NATIVE_GNB_CPUS:-}" ]] && gnb_pin=(taskset -c "${OCUDU_NATIVE_GNB_CPUS}")
declare -a broker_args=(
  "${broker}" --config "${config_dir}/topology.yaml" --duration "${run_duration_seconds}s"
  --control-endpoint "${control_endpoint}" --telemetry-endpoint "${telemetry_endpoint}" --telemetry-rate-hz 500
)
[[ "${strict_realtime}" == "1" ]] && broker_args+=(--strict-realtime)
if [[ "${wire_capture_samples}" -gt 0 ]]; then
  mkdir -p "${log_dir}/wire-capture"
  broker_args+=(--wire-capture-dir "${log_dir}/wire-capture" --wire-capture-samples "${wire_capture_samples}"
                --wire-capture-skip "$((wire_capture_skip_seconds * 23040000))")
fi
# shellcheck disable=SC2086  # OCUDU_NATIVE_BROKER_ENV is a KEY=VALUE list
start_group broker "${log_dir}/broker.log" \
  env CUDA_VISIBLE_DEVICES="${physical_gpu}" ${OCUDU_NATIVE_BROKER_ENV:-} "${broker_pin[@]}" "${broker_args[@]}"
broker_pid="${started_pid}"
broker_index=$((${#process_pids[@]} - 1))
broker_exit_deadline=$((SECONDS + run_duration_seconds + 10))
for id in "${ue_ids[@]}"; do
  wait_log "${log_dir}/broker.log" "event=socket_ready device=${id}" "${broker_pid}" 15 \
    || { grep -m1 "event=fatal" "${log_dir}/broker.log" >&2 || true; usage_error "broker did not bind ${id}"; }
done
wait_log "${log_dir}/broker.log" 'event=control_start ' "${broker_pid}" 15 || usage_error "broker control server did not become ready"
# Every link starts as a -100 dB TDL; Sionna must have swapped them in before
# the gNB is admitted. One carrier for all directions (TDD).
start_group sionna "${log_dir}/sionna-bridge.log" \
  env CUDA_VISIBLE_DEVICES="${physical_gpu}" "${sionna_python}" "${sionna_bridge}" \
  --scenario-config "${sionna_scenario_config}" --control-endpoint "${control_endpoint}" --duration 0 \
  --update-hz "${sionna_update_hz}" --status-jsonl "${sionna_status_jsonl}" \
  --carrier-frequency-hz "${carrier_hz}"
sionna_pid="${started_pid}"
wait_log "${log_dir}/sionna-bridge.log" '"event":"sionna_rt_update"' "${sionna_pid}" "${sionna_ready_seconds}" || \
  usage_error "Sionna RT did not publish its first matrix profile update"

start_group gnb "${log_dir}/gnb-console.log" "${gnb_pin[@]}" "${gnb}" -c "${config_dir}/gnb.yaml"
gnb_pid="${started_pid}"
wait_log "${log_dir}/gnb-console.log" '==== gNB started ===' "${gnb_pid}" "${OCUDU_NATIVE_GNB_START_TIMEOUT_SECONDS:-20}" || usage_error "gNB did not start"
sleep 3

# nrUE launch, per UE. Radio arguments from the renderer (TDD n78 20 MHz:
# `-E -r 51 --numerology 1 --band 78 -C 3489420000 --ssb 0`); the OAI 1x1
# gate's fixes: setpriv drops CAP_SYS_NICE (SCHED_FIFO would EPERM-abort in
# the rootless userns), absolute --uecap_file, the gate's rx_gain and
# --cont-fo-comp (oai-gate-defaults.sh). Each UE runs from its own working
# directory because the nrUE writes nrL1_UE_stats-0.log etc. into cwd.
read -r -a oai_radio <"${config_dir}/nrue-radio.args"
[[ -n "${OCUDU_NATIVE_OAI_UE_RADIO_ARGS:-}" ]] && read -r -a oai_radio <<<"${OCUDU_NATIVE_OAI_UE_RADIO_ARGS}"
ue_rx_gain=()
[[ -n "${OAI_GATE_UE_RX_GAIN_DB:-}" ]] && ue_rx_gain=(--zmq.'[0]'.rx_gain_db "${OAI_GATE_UE_RX_GAIN_DB}")
ue_fo=()
[[ -n "${OAI_GATE_UE_CONT_FO_COMP:-}" ]] && ue_fo=(--cont-fo-comp "${OAI_GATE_UE_CONT_FO_COMP}")
printf 'event=nrue_radio_args %s uecap=%s rx_gain_db=%s cont_fo_comp=%s\n' "${oai_radio[*]}" "${uecap_file}" \
  "${OAI_GATE_UE_RX_GAIN_DB:-none}" "${OAI_GATE_UE_CONT_FO_COMP:-off}" | tee "${log_dir}/nrue-radio.log"
declare -a nrue_pids=()
for index in "${!ue_ids[@]}"; do
  id="${ue_ids[index]}"
  if [[ "${index}" -gt 0 && "${stagger_seconds}" -gt 0 ]]; then sleep "${stagger_seconds}"; fi
  ue_pin=()
  [[ -n "${ue_cpus[index]:-}" ]] && ue_pin=(taskset -c "${ue_cpus[index]}")
  mkdir -p "${log_dir}/nrue-${id}"
  date -u +%s%3N >"${log_dir}/nrue-${id}.start_unix_ms"
  pushd "${log_dir}/nrue-${id}" >/dev/null
  start_group "nrue-${id}" "${log_dir}/nrue-${id}.log" nsenter --net="/run/netns/${ue_netns[index]}" -- \
    setpriv --bounding-set -sys_nice "${ue_pin[@]}" ${OCUDU_NATIVE_NRUE_WRAPPER:-} \
    "${nrue}" -O "${config_dir}/nrue-${id}.conf" "${oai_radio[@]}" \
    --ue-fo-compensation --uecap_file "${uecap_file}" \
    --device.name oai_zmqdevif --loader.oai_zmqdevif.shlibpath "${oai_build}" \
    --zmq.'[0]'.tx_channels "tcp://${ue_veth_ue[index]}:${ue_tx_port[index]}" \
    --zmq.'[0]'.rx_channels "tcp://${ue_veth_host[index]}:${ue_rx_port[index]}" \
    "${ue_rx_gain[@]}" "${ue_fo[@]}"
  popd >/dev/null
  nrue_pids+=("${started_pid}")
done

# --- attach verdict ---------------------------------------------------------
declare -a rrc=() pdu=() ping_ok=()
for _ in "${ue_ids[@]}"; do rrc+=(0); pdu+=(0); ping_ok+=(0); done
deadline=$((SECONDS + 150))
while [[ "${SECONDS}" -lt "${deadline}" ]]; do
  all_done=1
  for index in "${!ue_ids[@]}"; do
    id="${ue_ids[index]}"
    log="${log_dir}/nrue-${id}.log"
    grep -q 'State = NR_RRC_CONNECTED' "${log}" 2>/dev/null && rrc[index]=1
    grep -q 'Received PDU Session Establishment Accept' "${log}" 2>/dev/null && pdu[index]=1
    if [[ "${rrc[index]}" -eq 1 && "${pdu[index]}" -eq 1 && "${ping_ok[index]}" -eq 0 ]]; then
      # The PDU accept precedes the TUN configuration (oaitun_ue1 in every UE
      # namespace -- OAI names it by its ue_id 0, and the namespaces keep them apart).
      if nsenter --net="/run/netns/${ue_netns[index]}" -- ip -4 addr show dev oaitun_ue1 2>/dev/null | grep -q "${ue_ipv4[index]//./\\.}" && \
         nsenter --net="/run/netns/${ue_netns[index]}" -- ping -I oaitun_ue1 -c 3 -W 2 "${ue_gateway}" \
           >"${log_dir}/ue-ping-${id}.log" 2>&1; then
        ping_ok[index]=1
        if [[ -n "${ue_exec}" ]]; then
          ue_exec_command="$(expand_exec_template "${ue_exec}")"
          ue_exec_command="${ue_exec_command//\{ue_id\}/${id}}"
          ue_exec_command="${ue_exec_command//\{ue_ip\}/${ue_ipv4[index]}}"
          ue_exec_command="${ue_exec_command//\{ue_index\}/${index}}"
          ue_exec_command="${ue_exec_command//\{ue_netns\}/${ue_netns[index]}}"
          printf 'event=ue_exec_start ue=%s command=%q\n' "${id}" "${ue_exec_command}"
          start_group "ue-exec-${id}" "${log_dir}/ue-exec-${id}.log" \
            nsenter --net="/run/netns/${ue_netns[index]}" -- bash -c "${ue_exec_command}"
        fi
      fi
    fi
    [[ "${ping_ok[index]}" -eq 1 ]] || all_done=0
  done
  [[ "${all_done}" -eq 1 ]] && break
  sleep 0.5
done
# A second ping round late in the run: "stayed attached" evidence for the
# strict verdict (the first round happens seconds after attach).
late_ping_at=$((broker_exit_deadline - 40))
while [[ "${SECONDS}" -lt "${late_ping_at}" ]] && process_running "${broker_pid}"; do sleep 1; done
for index in "${!ue_ids[@]}"; do
  if [[ "${ping_ok[index]}" -eq 1 ]] && process_running "${broker_pid}"; then
    nsenter --net="/run/netns/${ue_netns[index]}" -- ping -I oaitun_ue1 -c 5 -W 2 "${ue_gateway}" \
      >"${log_dir}/ue-ping-late-${ue_ids[index]}.log" 2>&1 || true
  fi
done

# --- bounded broker drain ---------------------------------------------------
while process_running "${broker_pid}" && [[ "${SECONDS}" -lt "${broker_exit_deadline}" ]]; do sleep 0.1; done
if process_running "${broker_pid}"; then
  printf 'error: broker exceeded its bounded natural-exit window\n' >&2
  stop_group "${broker_index}" || true
  broker_status=124
else
  set +e
  wait "${broker_pid}"
  broker_status="$?"
  set -o pipefail
fi
gnb_alive=0; process_running "${gnb_pid}" && gnb_alive=1
fivegc_alive=0; process_running "${fivegc_pid}" && fivegc_alive=1
nrue_alive=1
for pid in "${nrue_pids[@]}"; do process_running "${pid}" || nrue_alive=0; done

/usr/bin/python3 - "${log_dir}" "${report_dir}/attach-summary.json" "${config_dir}/oai-multi-ue-shape.json" \
  "${timestamp}" "${broker_status}" "${gnb_alive}" "${fivegc_alive}" "${nrue_alive}" \
  "${rrc[*]}" "${pdu[*]}" "${ping_ok[*]}" "${ue_ids[*]}" "${attach_strict}" <<'PY'
import json, pathlib, re, sys

(log_dir, out_path, shape_path, timestamp, broker_status, gnb_alive, fivegc_alive, nrue_alive,
 rrc, pdu, ping_ok, ue_ids, attach_strict) = sys.argv[1:]
log_dir = pathlib.Path(log_dir)
broker_lines = (log_dir / "broker.log").read_text(encoding="utf-8", errors="replace").splitlines()
stop = next((l for l in reversed(broker_lines) if l.startswith("event=stop ")), "")
counters = {k: int(v) for k, v in re.findall(r"(\w+)=(\d+)", stop)}
ids = ue_ids.split()
per_ue = {ue: {"rrc_connected": int(r), "pdu_session_established": int(p), "ping_ok": int(q)}
          for ue, r, p, q in zip(ids, rrc.split(), pdu.split(), ping_ok.split())}


def pings(path):
    if not path.exists():
        return 0, 0
    m = re.search(r"(\d+) packets transmitted, (\d+) (?:packets )?received", path.read_text(encoding="utf-8", errors="replace"))
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def attach_evidence(ue):
    """Strict evidence from the OAI nrUE console log (X0, OAI tokens).

    Counted after the first "State = NR_RRC_CONNECTED":
      sr_failures        "SR not served! SR counter N reached sr_MaxTransmissions"
                         (nr_ue_procedures.c; the UE then starts a new RA)
      reattach_attempts  "Triggering new RA procedure for UE with RNTI"
                         (connected-mode RA, nr_ra_procedures.c) plus any further
                         "Initialization of 4-Step CBRA procedure"
      rlf_count          "Timer T310 expired" (rrc_timers_and_constants.c) and
                         any "Radio Link Failure"/"RLF" line
      integrity_failures "Integrity check failure" anywhere (two UEs merged
                         onto one C-RNTI decode each other's NAS)
    Recorded, not gated: resyncs ("Resynchronizing RX by"), RA successes,
    the UE's initial-sync count. The late ping round (ue-ping-late-*.log)
    must also be fully answered when it ran.
    """
    path = log_dir / f"nrue-{ue}.log"
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines() if path.exists() else []
    first = next((i for i, l in enumerate(lines) if "State = NR_RRC_CONNECTED" in l), None)
    after = lines[first + 1:] if first is not None else []
    sent, received = pings(log_dir / f"ue-ping-{ue}.log")
    late_sent, late_received = pings(log_dir / f"ue-ping-late-{ue}.log")
    return {
        "sr_failures": sum(1 for l in after if "SR not served!" in l),
        "reattach_attempts": sum(1 for l in after if "Triggering new RA procedure" in l
                                 or "Initialization of 4-Step CBRA procedure" in l),
        "rlf_count": sum(1 for l in after if "Timer T310 expired" in l or re.search(r"Radio Link Failure|\bRLF\b", l)),
        "integrity_failures": sum(1 for l in lines if "Integrity check failure" in l),
        "resyncs": sum(1 for l in lines if "Resynchronizing RX by" in l),
        "ra_successes": sum(1 for l in lines if "RA procedure succeeded" in l),
        "initial_syncs": sum(1 for l in lines if "UE synchronized!" in l),
        "ping_sent": sent, "ping_received": received,
        "late_ping_sent": late_sent, "late_ping_received": late_received,
    }


for ue, v in per_ue.items():
    v.update(attach_evidence(ue))
    v["attach_clean"] = int(bool(
        v["rrc_connected"] and v["pdu_session_established"]
        and v["ping_sent"] > 0 and v["ping_received"] == v["ping_sent"]
        and v["late_ping_received"] == v["late_ping_sent"]
        and v["sr_failures"] == 0 and v["reattach_attempts"] == 0
        and v["rlf_count"] == 0 and v["integrity_failures"] == 0))
    print(f"event=ue_attach_evidence ue={ue} rrc={v['rrc_connected']} pdu={v['pdu_session_established']} "
          f"ping={v['ping_received']}/{v['ping_sent']} late_ping={v['late_ping_received']}/{v['late_ping_sent']} "
          f"sr_failures={v['sr_failures']} reattach_attempts={v['reattach_attempts']} rlf={v['rlf_count']} "
          f"integrity_failures={v['integrity_failures']} resyncs={v['resyncs']} clean={v['attach_clean']}", flush=True)
all_attached = all(v["rrc_connected"] and v["pdu_session_established"] and v["ping_ok"] for v in per_ue.values())
if int(attach_strict):
    all_attached = all_attached and all(v["attach_clean"] for v in per_ue.values())
strict_clean = all(counters.get(k, 1) == 0 for k in ("tx_queue_overflows", "tx_sequence_gaps", "zmq_errors"))
summary = {
    "timestamp": timestamp, "gate": "ocudu-oai-multi-ue", "ue": "oai-nrue", "docker_used": False,
    "runtime_mode": "rootless_user_net_mount_namespace", "ue_count": len(ids), "attach_strict": int(attach_strict),
    "per_ue": per_ue, "broker_status": int(broker_status),
    "gnb_alive_at_broker_stop": int(gnb_alive), "open5gs_alive_at_broker_stop": int(fivegc_alive),
    "nrue_alive_at_broker_stop": int(nrue_alive), "log_dir": str(log_dir),
    "status": "passed" if (all_attached and strict_clean and int(broker_status) == 0 and int(gnb_alive) == 1
                           and int(fivegc_alive) == 1 and int(nrue_alive) == 1) else "failed",
}
summary.update({k: counters.get(k, -1) for k in ("tx_pulls", "rx_requests", "rx_starvations",
                                                   "tx_queue_overflows", "tx_sequence_gaps", "zmq_errors")})
summary["control"] = {k: counters.get(k) for k in ("control_msgs_received", "control_updates_applied",
                      "control_updates_rejected", "control_batches_committed", "control_batches_aborted",
                      "telemetry_frames", "telemetry_drops") if k in counters}
heartbeats = {}
for line in broker_lines:
    if line.startswith("event=heartbeat ") and "puller[" in line:
        dev = re.search(r" dev=([A-Za-z0-9_-]+) ring=", line)
        if dev:
            heartbeats[dev.group(1)] = {
                "t": int((re.search(r" t=(\d+)", line) or [0, 0])[1]),
                "puller_idle": int((re.search(r"puller\[[^\]]*idle=(\d+)", line) or [0, -1])[1]),
                "producer_stall": int((re.search(r"producer\[[^\]]*stall=(\d+)", line) or [0, -1])[1]),
            }
summary["last_heartbeat"] = heartbeats
status_jsonl = log_dir / "sionna-status.jsonl"
if status_jsonl.exists():
    updates = 0
    last = None
    for line in status_jsonl.read_text(encoding="utf-8", errors="replace").splitlines():
        if '"sionna_rt_update"' in line:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("event") == "sionna_rt_update":
                updates += 1
                last = record
    summary["sionna"] = {"updates": updates, "frequencies_hz": (last or {}).get("frequencies_hz"),
                         "last_channel_generation_ms": ((last or {}).get("timing_ms") or {}).get("channel_generation")}
try:
    shape = json.loads(pathlib.Path(shape_path).read_text(encoding="utf-8"))
    summary["cell"] = shape.get("cell")
    summary["ue_tx_scale_db"] = shape.get("ue_tx_scale_db")
    summary["ue_tx_power_source"] = shape.get("ue_tx_power_source")
    summary["rx_noise"] = shape.get("rx_noise")
    summary["links"] = shape.get("links")
except (OSError, json.JSONDecodeError):
    pass
parameters = pathlib.Path(out_path).parent / "run-parameters.json"
if parameters.exists():
    try:
        summary["run_parameters"] = json.loads(parameters.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
capture = log_dir / "wire-capture" / "wire-capture.json"
if capture.exists():
    summary["wire_capture"] = str(capture)
out = pathlib.Path(out_path)
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"summary={out}")
raise SystemExit(0 if summary["status"] == "passed" else 1)
PY
