#!/usr/bin/env bash
# Inner half of the native two-cell TDD gate with OAI nrUEs (X5). Runs INSIDE
# the user + network + mount namespace created by run-ocudu-oai-two-cell-tdd.sh;
# never invoke it directly.
#
# Structure: run-ocudu-oai-multi-ue-inner.sh (X3/X4: netns + veth per nrUE,
# OAI verdict tokens, wire capture) with run-ocudu-multi-gnb-inner.sh's second
# cell (two gNB processes started together, four-node broker, each UE's camped
# PCI checked against its own cell). New here: per-gNB DL/UL HARQ and CQI
# evidence (stdout metrics table + PHY log), the nrUE's reported SINR/CQI
# series, and -- when a wire capture was taken -- a per-TDD-slot analysis with
# numpy (from the Sionna interpreter) that classifies every 0.5 ms slot by
# which of gnb0 / gnb1 / ue0 / ue1 transmitted and reports the victim UE's
# receive level in its own DL slots with and without the other UE's uplink.
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

# Must agree with render-oai-two-cell-tdd-configs.py CELLS / UES / VETH.
gnb_ids=(gnb0 gnb1)
gnb_pcis=(1 2)
ue_ids=(ue0 ue1)
ue_netns=(ue1 ue2)
ue_ipv4=(10.45.1.2 10.45.1.3)
ue_tx_port=(2101 2103)
ue_rx_port=(2100 2102)
ue_veth_host=(10.201.0.1 10.201.1.1)
ue_veth_ue=(10.201.0.2 10.201.1.2)
ue_gateway="10.45.1.1"
IFS=';' read -r -a ue_cpus <<<"${OCUDU_NATIVE_OAI_MUE_UE_CPUS:-}"
IFS=';' read -r -a gnb_cpus <<<"${OCUDU_NATIVE_TDD_GNB_CPUS:-}"
attach_strict="${OCUDU_NATIVE_ATTACH_STRICT:-1}"
gnb_start_timeout="${OCUDU_NATIVE_GNB_START_TIMEOUT_SECONDS:-20}"

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
data_dir="${native_root}/data/ocudu-oai-two-cell-tdd-native/${timestamp}"
uecap_file="${OCUDU_NATIVE_OAI_UECAP_FILE:-${config_dir}/uecap.xml}"
shape_json="${config_dir}/two-cell-tdd-shape.json"
for binary in "${gnb}" "${nrue}" "${fivegc}" "${mongod}" "${broker}"; do
  [[ -x "${binary}" ]] || usage_error "missing executable: ${binary}"
done
[[ -f "${oai_build}/liboai_zmqdevif.so" ]] || usage_error "missing OAI ZMQ radio module in ${oai_build}"
[[ -f "${uecap_file}" ]] || usage_error "missing OAI UE capability file: ${uecap_file}"
[[ -f "${config_dir}/nrue-radio.args" ]] || usage_error "renderer did not write nrue-radio.args"
[[ -f "${shape_json}" ]] || usage_error "renderer did not write two-cell-tdd-shape.json"
[[ -d "${data_dir}" ]] || usage_error "missing data dir: ${data_dir}"
carrier_hz="$(/usr/bin/python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["cell"]["carrier_hz"])' "${shape_json}")" \
  || usage_error "cannot read the carrier from two-cell-tdd-shape.json"
[[ "${carrier_hz}" =~ ^[1-9][0-9]*$ ]] || usage_error "invalid carrier_hz: ${carrier_hz}"
printf 'event=oai_two_cell_tdd_inner nrue=%s zmq_module=%s uecap=%s carrier_hz=%s gnb_cpus="%s" ue_cpus="%s"\n' \
  "${nrue}" "${oai_build}" "${uecap_file}" "${carrier_hz}" "${OCUDU_NATIVE_TDD_GNB_CPUS:-}" "${OCUDU_NATIVE_OAI_MUE_UE_CPUS:-}"

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
# The two gNBs bind N2/N3 on 127.0.0.11/.12 (loopback /8 answers for them).
for index in "${!ue_ids[@]}"; do
  name="${ue_netns[index]}"
  ip netns add "${name}"
  created_netns+=("${name}")
  nsenter --net="/run/netns/${name}" -- ip link set lo up
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

# --- broker, Sionna, gNBs, UEs ---------------------------------------------
broker_pin=()
[[ -n "${OCUDU_NATIVE_BROKER_CPUS:-}" ]] && broker_pin=(taskset -c "${OCUDU_NATIVE_BROKER_CPUS}")
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
for id in "${gnb_ids[@]}" "${ue_ids[@]}"; do
  wait_log "${log_dir}/broker.log" "event=socket_ready device=${id}" "${broker_pid}" 15 \
    || { grep -m1 "event=fatal" "${log_dir}/broker.log" >&2 || true; usage_error "broker did not bind ${id}"; }
done
wait_log "${log_dir}/broker.log" 'event=control_start ' "${broker_pid}" 15 || usage_error "broker control server did not become ready"
start_group sionna "${log_dir}/sionna-bridge.log" \
  env CUDA_VISIBLE_DEVICES="${physical_gpu}" "${sionna_python}" "${sionna_bridge}" \
  --scenario-config "${sionna_scenario_config}" --control-endpoint "${control_endpoint}" --duration 0 \
  --update-hz "${sionna_update_hz}" --status-jsonl "${sionna_status_jsonl}" \
  --carrier-frequency-hz "${carrier_hz}"
sionna_pid="${started_pid}"
wait_log "${log_dir}/sionna-bridge.log" '"event":"sionna_rt_update"' "${sionna_pid}" "${sionna_ready_seconds}" || \
  usage_error "Sionna RT did not publish its first matrix profile update"

# Both cells start together (run-ocudu-multi-gnb-inner.sh): the broker's
# producer needs every incoming lane streaming, so a late second gNB would
# only starve the first. Each gNB gets its own taskset list.
declare -a gnb_pids=()
for index in "${!gnb_ids[@]}"; do
  id="${gnb_ids[index]}"
  gnb_pin=()
  [[ -n "${gnb_cpus[index]:-}" ]] && gnb_pin=(taskset -c "${gnb_cpus[index]}")
  start_group "gnb-${id}" "${log_dir}/${id}-console.log" "${gnb_pin[@]}" "${gnb}" -c "${config_dir}/${id}.yaml"
  gnb_pids+=("${started_pid}")
done
for index in "${!gnb_ids[@]}"; do
  wait_log "${log_dir}/${gnb_ids[index]}-console.log" '==== gNB started ===' "${gnb_pids[index]}" "${gnb_start_timeout}" \
    || usage_error "${gnb_ids[index]} did not start"
done
sleep 3

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
gnb_alive=1
for pid in "${gnb_pids[@]}"; do process_running "${pid}" || gnb_alive=0; done
fivegc_alive=0; process_running "${fivegc_pid}" && fivegc_alive=1
nrue_alive=1
for pid in "${nrue_pids[@]}"; do process_running "${pid}" || nrue_alive=0; done
# Stop the ue-exec pingers now so their logs carry final statistics.
for ((index=0; index<${#process_pids[@]}; index++)); do
  [[ "${process_names[index]}" == ue-exec* ]] && { stop_group "${index}" || true; process_pids[index]="0"; }
done

# --- per-TDD-slot analysis of the wire capture (numpy from the Sionna venv) --
slot_analysis="${report_dir}/tdd-slot-analysis.json"
if [[ -f "${log_dir}/wire-capture/wire-capture.json" ]]; then
  "${sionna_python}" - "${log_dir}/wire-capture" "${shape_json}" "${slot_analysis}" <<'PY' 2>&1 | tee "${log_dir}/tdd-slot-analysis.log" || true
import json, pathlib, sys
import numpy as np

capture_dir, shape_path, out_path = map(pathlib.Path, sys.argv[1:4])
shape = json.loads(shape_path.read_text())
manifest = json.loads((capture_dir / "wire-capture.json").read_text())
slot = shape["cell"]["slot_samples"]          # 11520 = 0.5 ms at 23.04 MS/s
period = 10
patterns = {c["device_id"]: c for c in shape["cells"]}
serving = shape["serving"]                     # ue -> gnb
GNB_TX_DB, UE_TX_DB = -40.0, -70.0             # slot-mean thresholds on each node's own tx_in wire


def slot_power_db(path):
    data = np.memmap(path, dtype=np.complex64, mode="r")
    n = (len(data) // slot) * slot
    p = (np.abs(data[:n]) ** 2).reshape(-1, slot).mean(axis=1)
    return 10.0 * np.log10(np.maximum(p, 1e-30))


series = {}
for port in manifest["ports"]:
    node = port["node"]
    for direction in ("tx_in", "rx_out"):
        path = capture_dir / f"{port['id']}.{direction}.cf32"
        if path.exists():
            series[(node, direction)] = slot_power_db(path)
nodes = sorted({n for n, _ in series})
n_slots = min(len(v) for v in series.values())
tx_active = {}
for node in nodes:
    threshold = GNB_TX_DB if node.startswith("gnb") else UE_TX_DB
    tx_active[node] = series[(node, "tx_in")][:n_slots] > threshold
for node in ("gnb0", "gnb1", "ue0", "ue1"):      # a port absent from the capture never transmits
    tx_active.setdefault(node, np.zeros(n_slots, dtype=bool))


def find_phase(active, dl_slots):
    """Phase p such that slots with (i - p) % period < dl_slots hold the gNB's TX."""
    best, best_score = 0, -1.0
    idx = np.arange(len(active))
    for p in range(period):
        kind = (idx - p) % period
        dl, ul = active[kind < dl_slots], active[kind > dl_slots]
        if len(dl) and len(ul):
            score = dl.mean() - ul.mean()
            if score > best_score:
                best, best_score = p, score
    return best, best_score


phases = {}
for gnb in ("gnb0", "gnb1"):
    if gnb in nodes and gnb in patterns:
        phases[gnb] = find_phase(tx_active[gnb], patterns[gnb]["tdd_ul_dl_cfg"]["nof_dl_slots"])
phase_offset = ((phases["gnb1"][0] - phases["gnb0"][0]) % period) if len(phases) == 2 else None

report = {"capture_dir": str(capture_dir), "slot_samples": slot, "slots": int(n_slots), "period": period,
          "thresholds_db": {"gnb_tx": GNB_TX_DB, "ue_tx": UE_TX_DB},
          "tx_active_slots": {n: int(a.sum()) for n, a in tx_active.items()},
          "tdd_phase": {g: {"first_dl_slot": int(p), "separation": float(s)} for g, (p, s) in phases.items()},
          "tdd_phase_offset_gnb1_minus_gnb0_slots": phase_offset,
          "patterns": {g: patterns[g]["tdd_pattern"] for g in patterns},
          "classes": {}, "victim": {}}


def med(values):
    return float(np.median(values)) if len(values) else None


# Every slot classified by the four TX activities; median RX of every node per class.
keys = np.zeros(n_slots, dtype=np.int64)
for bit, node in enumerate(("gnb0", "gnb1", "ue0", "ue1")):
    if node in tx_active:
        keys |= tx_active[node].astype(np.int64) << bit
for key in sorted(set(keys.tolist())):
    mask = keys == key
    label = "+".join(n for bit, n in enumerate(("gnb0", "gnb1", "ue0", "ue1")) if key >> bit & 1) or "silent"
    report["classes"][label] = {"slots": int(mask.sum()),
                                **{f"{n}_rx_median_db": med(series[(n, 'rx_out')][:n_slots][mask]) for n in nodes}}

lines = [f"slots={n_slots} ({n_slots * slot / 23040000:.2f} s) phases={ {g: p for g, (p, _) in phases.items()} } "
         f"offset_gnb1-gnb0={phase_offset} patterns={report['patterns']}",
         f"{'TX class':24s} {'slots':>6s} " + " ".join(f"{n + ' rx':>10s}" for n in nodes)]
for label, row in report["classes"].items():
    lines.append(f"{label:24s} {row['slots']:6d} " + " ".join(
        f"{(row[f'{n}_rx_median_db'] if row[f'{n}_rx_median_db'] is not None else float('nan')):10.1f}" for n in nodes))

# The headline: the victim's RX in its OWN cell's DL slots (its serving gNB transmits, it does not),
# split by whether the other UE transmits in that slot.
for victim, other in (("ue0", "ue1"), ("ue1", "ue0")):
    if victim not in nodes or other not in nodes or serving[victim] not in nodes:
        continue
    own = serving[victim]
    rx = series[(victim, "rx_out")][:n_slots]
    dl = tx_active[own] & ~tx_active[victim]
    with_other, without_other = dl & tx_active[other], dl & ~tx_active[other]
    other_only = tx_active[other] & ~tx_active[own] & ~tx_active[victim]
    silent = ~tx_active["gnb0"] & ~tx_active["gnb1"] & ~tx_active["ue0"] & ~tx_active["ue1"]
    entry = {
        "serving_gnb": own,
        "dl_slots": int(dl.sum()),
        "dl_slots_with_other_ue_tx": int(with_other.sum()),
        "dl_slots_without_other_ue_tx": int(without_other.sum()),
        "rx_median_db_dl_with_other_ue_tx": med(rx[with_other]),
        "rx_median_db_dl_without_other_ue_tx": med(rx[without_other]),
        "rx_median_db_other_ue_tx_only": med(rx[other_only]),
        "rx_median_db_silent": med(rx[silent]),
        "rx_p90_db_dl_with_other_ue_tx": float(np.percentile(rx[with_other], 90)) if with_other.any() else None,
        "rx_p90_db_dl_without_other_ue_tx": float(np.percentile(rx[without_other], 90)) if without_other.any() else None,
        "own_dl_and_other_ue_tx_overlap_slots": int((tx_active[own] & tx_active[other]).sum()),
    }
    report["victim"][victim] = entry
    lines.append(f"victim {victim} (cell {own}): DL slots {entry['dl_slots']}, of which {entry['dl_slots_with_other_ue_tx']} "
                 f"with {other} TX; RX median DL+{other}TX={entry['rx_median_db_dl_with_other_ue_tx']} dB, "
                 f"DL only={entry['rx_median_db_dl_without_other_ue_tx']} dB, {other} TX only={entry['rx_median_db_other_ue_tx_only']} dB, "
                 f"silent={entry['rx_median_db_silent']} dB")
# gNB-side: each gNB's RX in its own UL slots (it is silent) with the other cell's gNB transmitting or not.
for gnb, other in (("gnb0", "gnb1"), ("gnb1", "gnb0")):
    if gnb in nodes and other in nodes:
        rx = series[(gnb, "rx_out")][:n_slots]
        ul = ~tx_active[gnb]
        report["victim"][gnb] = {"ul_slots": int(ul.sum()),
                                 "rx_median_db_ul_with_other_gnb_tx": med(rx[ul & tx_active[other]]),
                                 "rx_median_db_ul_without_other_gnb_tx": med(rx[ul & ~tx_active[other]])}
out_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
print("\n".join(lines))
print(f"event=tdd_slot_analysis json={out_path}")
PY
fi

/usr/bin/python3 - "${log_dir}" "${report_dir}/attach-summary.json" "${shape_json}" "${slot_analysis}" \
  "${timestamp}" "${broker_status}" "${gnb_alive}" "${fivegc_alive}" "${nrue_alive}" \
  "${rrc[*]}" "${pdu[*]}" "${ping_ok[*]}" "${ue_ids[*]}" "${gnb_pcis[*]}" "${attach_strict}" <<'PY'
import json, pathlib, re, statistics, sys

(log_dir, out_path, shape_path, slot_analysis, timestamp, broker_status, gnb_alive, fivegc_alive, nrue_alive,
 rrc, pdu, ping_ok, ue_ids, gnb_pcis, attach_strict) = sys.argv[1:]
log_dir = pathlib.Path(log_dir)
broker_lines = (log_dir / "broker.log").read_text(encoding="utf-8", errors="replace").splitlines()
stop = next((l for l in reversed(broker_lines) if l.startswith("event=stop ")), "")
counters = {k: int(v) for k, v in re.findall(r"(\w+)=(\d+)", stop)}
ids = ue_ids.split()
expected_pci = [int(p) for p in gnb_pcis.split()]
shape = json.loads(pathlib.Path(shape_path).read_text(encoding="utf-8"))
per_ue = {ue: {"rrc_connected": int(r), "pdu_session_established": int(p), "ping_ok": int(q), "expected_pci": expected_pci[i]}
          for i, (ue, r, p, q) in enumerate(zip(ids, rrc.split(), pdu.split(), ping_ok.split()))}


def read(path):
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def pings(path):
    text = read(path)
    m = re.search(r"(\d+) packets transmitted, (\d+) (?:packets )?received", text)
    rtt = re.search(r"rtt min/avg/max/mdev = ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+) ms", text)
    return ((int(m.group(1)), int(m.group(2))) if m else (0, 0)), ([float(x) for x in rtt.groups()] if rtt else None)


def attach_evidence(ue):
    """X3's strict OAI evidence plus the camped PCI and the UE-reported DL SINR/CQI."""
    text = read(log_dir / f"nrue-{ue}.log")
    lines = text.splitlines()
    first = next((i for i, l in enumerate(lines) if "State = NR_RRC_CONNECTED" in l), None)
    after = lines[first + 1:] if first is not None else []
    (sent, received), _ = pings(log_dir / f"ue-ping-{ue}.log")
    (late_sent, late_received), _ = pings(log_dir / f"ue-ping-late-{ue}.log")
    (exec_sent, exec_received), exec_rtt = pings(log_dir / f"ue-exec-{ue}.log")
    pcis = [int(p) for p in re.findall(r"Initial sync successful, PCI: (\d+)", text)]
    # "DL Chan: SSB 0 SINR 42.6 dB RSRP -28 dBm, RI 0 CQI 15 ..." once a second from the nrUE.
    csi = [(float(s), int(r), int(c)) for s, r, c in
           re.findall(r"DL Chan: SSB \d+ SINR ([-\d.]+) dB RSRP (-?\d+) dBm, RI \d+ CQI (\d+)", text)]
    sinr = [c[0] for c in csi]
    cqi = [c[2] for c in csi]
    return {
        "camped_pci": pcis[-1] if pcis else -1, "initial_sync_pcis": pcis,
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
        "exec_ping": {"sent": exec_sent, "received": exec_received, "rtt_min_avg_max_mdev_ms": exec_rtt} if exec_sent else None,
        "ue_reported": {"samples": len(csi), "sinr_db_median": statistics.median(sinr) if sinr else None,
                        "sinr_db_min": min(sinr) if sinr else None, "sinr_db_p10": (sorted(sinr)[len(sinr) // 10] if sinr else None),
                        "cqi_median": statistics.median(cqi) if cqi else None, "cqi_min": min(cqi) if cqi else None,
                        "cqi_histogram": {str(k): cqi.count(k) for k in sorted(set(cqi))}},
    }


def gnb_evidence(gnb):
    """DL/UL HARQ from the gNB: the stdout metrics table (per-UE ok/nok/CQI/SNR rows,
    accumulated over the run) and the PHY log's PUCCH `ack=` digits / PUSCH crc."""
    console = read(log_dir / f"{gnb}-console.log")
    header = None
    totals = {}
    for line in console.splitlines():
        if "pci" in line and "rnti" in line and "|" in line:
            header = [seg.split() for seg in line.split("|")]
            continue
        if header is None or "|" not in line:
            continue
        segs = [seg.split() for seg in line.split("|")]
        if len(segs) != len(header) or len(segs[0]) < 2 or not re.fullmatch(r"[0-9a-fA-F]{4}", segs[0][1]):
            continue
        rnti = segs[0][1]
        row = totals.setdefault(rnti, {"rows": 0, "dl_ok": 0, "dl_nok": 0, "ul_ok": 0, "ul_nok": 0, "cqi": [], "pusch_snr": [], "dl_mcs": [], "ul_mcs": []})
        row["rows"] += 1
        try:
            dl = dict(zip(header[1], segs[1]))
            ul = dict(zip(header[2], segs[2])) if len(segs) > 2 else {}
            row["dl_ok"] += int(dl.get("ok", 0)); row["dl_nok"] += int(dl.get("nok", 0))
            row["ul_ok"] += int(ul.get("ok", 0)); row["ul_nok"] += int(ul.get("nok", 0))
            if dl.get("cqi", "n/a") not in ("n/a", "-"): row["cqi"].append(int(dl["cqi"]))
            if dl.get("mcs", "n/a") not in ("n/a", "-"): row["dl_mcs"].append(int(dl["mcs"]))
            if ul.get("mcs", "n/a") not in ("n/a", "-"): row["ul_mcs"].append(int(ul["mcs"]))
            snr = ul.get("pusch") or ul.get("snr")
            if snr not in (None, "n/a", "-"): row["pusch_snr"].append(float(snr))
        except (ValueError, IndexError):
            continue
    metrics = {}
    for rnti, row in totals.items():
        total_dl = row["dl_ok"] + row["dl_nok"]
        total_ul = row["ul_ok"] + row["ul_nok"]
        metrics[rnti] = {
            "rows": row["rows"], "dl_ok": row["dl_ok"], "dl_nok": row["dl_nok"],
            "dl_nack_ratio": (row["dl_nok"] / total_dl) if total_dl else None,
            "ul_ok": row["ul_ok"], "ul_nok": row["ul_nok"], "ul_nack_ratio": (row["ul_nok"] / total_ul) if total_ul else None,
            "cqi_median": statistics.median(row["cqi"]) if row["cqi"] else None, "cqi_min": min(row["cqi"]) if row["cqi"] else None,
            "dl_mcs_median": statistics.median(row["dl_mcs"]) if row["dl_mcs"] else None,
            "pusch_snr_db_median": statistics.median(row["pusch_snr"]) if row["pusch_snr"] else None,
            "pusch_snr_db_min": min(row["pusch_snr"]) if row["pusch_snr"] else None,
        }
    phy = read(log_dir / f"{gnb}-internal.log")
    acks = "".join(re.findall(r"PUCCH: .*? ack=([012]+)", phy))
    pusch_sinr = [float(s) for s in re.findall(r"PUSCH: .*? sinr=([-\d.]+)dB", phy)]
    return {
        "stdout_metrics_per_rnti": metrics,
        "phy_log": {"pdsch": len(re.findall(r"PDSCH: rnti=0x", phy)),
                    "pusch_crc_ok": phy.count("crc=OK"), "pusch_crc_ko": phy.count("crc=KO"),
                    "pucch_ack_bits": {"ack": acks.count("1"), "nack": acks.count("0"), "dtx": acks.count("2")},
                    "pusch_sinr_db_median": statistics.median(pusch_sinr) if pusch_sinr else None},
        "console_lines": console.count("\n"),
    }


for ue, v in per_ue.items():
    v.update(attach_evidence(ue))
    v["on_expected_cell"] = int(v["camped_pci"] == v["expected_pci"])
    v["attach_clean"] = int(bool(
        v["rrc_connected"] and v["pdu_session_established"]
        and v["ping_sent"] > 0 and v["ping_received"] == v["ping_sent"]
        and v["late_ping_received"] == v["late_ping_sent"]
        and v["sr_failures"] == 0 and v["reattach_attempts"] == 0
        and v["rlf_count"] == 0 and v["integrity_failures"] == 0))
    r = v["ue_reported"]
    print(f"event=ue_attach_evidence ue={ue} pci={v['camped_pci']}/{v['expected_pci']} rrc={v['rrc_connected']} "
          f"pdu={v['pdu_session_established']} ping={v['ping_received']}/{v['ping_sent']} "
          f"late_ping={v['late_ping_received']}/{v['late_ping_sent']} sr_failures={v['sr_failures']} "
          f"reattach_attempts={v['reattach_attempts']} rlf={v['rlf_count']} integrity_failures={v['integrity_failures']} "
          f"resyncs={v['resyncs']} sinr_med={r['sinr_db_median']} sinr_min={r['sinr_db_min']} cqi_med={r['cqi_median']} "
          f"cqi_min={r['cqi_min']} exec_ping={v['exec_ping']} clean={v['attach_clean']}", flush=True)
per_gnb = {}
for gnb in ("gnb0", "gnb1"):
    per_gnb[gnb] = gnb_evidence(gnb)
    print(f"event=gnb_evidence gnb={gnb} metrics={json.dumps(per_gnb[gnb]['stdout_metrics_per_rnti'])} "
          f"phy={json.dumps(per_gnb[gnb]['phy_log'])}", flush=True)
all_attached = all(v["rrc_connected"] and v["pdu_session_established"] and v["ping_ok"] for v in per_ue.values())
if int(attach_strict):
    all_attached = all_attached and all(v["attach_clean"] for v in per_ue.values())
own_cells = all(v["on_expected_cell"] for v in per_ue.values())
strict_clean = all(counters.get(k, 1) == 0 for k in ("tx_queue_overflows", "tx_sequence_gaps", "zmq_errors"))
summary = {
    "timestamp": timestamp, "gate": "ocudu-oai-two-cell-tdd", "ue": "oai-nrue", "docker_used": False,
    "runtime_mode": "rootless_user_net_mount_namespace", "ue_count": len(ids), "cell_count": 2,
    "attach_strict": int(attach_strict), "each_ue_on_its_own_cell": int(own_cells),
    "per_ue": per_ue, "per_gnb": per_gnb, "broker_status": int(broker_status),
    "gnb_alive_at_broker_stop": int(gnb_alive), "open5gs_alive_at_broker_stop": int(fivegc_alive),
    "nrue_alive_at_broker_stop": int(nrue_alive), "log_dir": str(log_dir),
    "status": "passed" if (all_attached and own_cells and strict_clean and int(broker_status) == 0 and int(gnb_alive) == 1
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
summary["node_stalls"] = sum(1 for l in broker_lines if l.startswith("event=node_stall "))
status_jsonl = log_dir / "sionna-status.jsonl"
if status_jsonl.exists():
    updates, last = 0, None
    for line in status_jsonl.read_text(encoding="utf-8", errors="replace").splitlines():
        if '"sionna_rt_update"' in line:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("event") == "sionna_rt_update":
                updates += 1
                last = record
    taps = {}
    for channel in (last or {}).get("channels", []):
        taps[channel["link_id"].split(":")[0]] = {"strongest_tap_gain_db": channel.get("strongest_tap_gain_db"),
                                                  "total_path_power_db": channel.get("total_path_power_db"),
                                                  "ray_count": channel.get("ray_count")}
    summary["sionna"] = {"updates": updates, "frequencies_hz": (last or {}).get("frequencies_hz"),
                         "last_channel_generation_ms": ((last or {}).get("timing_ms") or {}).get("channel_generation"),
                         "last_taps": taps}
for key in ("cell", "cells", "tdd_mode", "cli_slots_ue1_into_ue0", "cli_slots_ue0_into_ue1", "ue_tx_scale_db",
            "ue_tx_power_source", "rx_noise", "links", "ue_ue_links", "serving"):
    summary[key] = shape.get(key)
parameters = pathlib.Path(out_path).parent / "run-parameters.json"
if parameters.exists():
    try:
        summary["run_parameters"] = json.loads(parameters.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
capture = log_dir / "wire-capture" / "wire-capture.json"
if capture.exists():
    summary["wire_capture"] = str(capture)
analysis = pathlib.Path(slot_analysis)
if analysis.exists():
    try:
        summary["tdd_slot_analysis"] = json.loads(analysis.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        summary["tdd_slot_analysis"] = str(analysis)
out = pathlib.Path(out_path)
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"summary={out}")
raise SystemExit(0 if summary["status"] == "passed" else 1)
PY
