#!/usr/bin/env bash
set -euo pipefail

mode=""
parent_netns=""
parent_mntns=""
outer_uid=""
netns_dir=""
physical_gpu=""
hardware_probe=""
probe_broker=""
runtime_broker=""
probe_config=""
native_root=""
repo_root=""
config_dir=""
log_dir=""
report_dir=""
timestamp=""
channel_mode="legacy"
run_duration_seconds="15"
run_family=""
broker_ready_device="ue0"
control_endpoint=""
telemetry_endpoint=""
# Empty unless the outer script enabled metrics. The gNB binds its
# remote-control WebSocket on this namespace's loopback, which the
# dashboard cannot reach, so a relay re-exports it as this socket file.
gnb_metrics_socket=""
# Must match the port the renderer wrote into gnb.yaml.
gnb_metrics_port="${OCUDU_NATIVE_GNB_METRICS_PORT:-8001}"
sionna_python=""
sionna_bridge=""
sionna_scenario_config=""
sionna_status_jsonl=""
sionna_update_hz="10"
sionna_ready_seconds="120"
live_ready_path=""
live_ready_event="native_sionna_1x1_live_ready"
# Keepalive traffic for the unbounded live demo only; 0 leaves the run exactly
# as it was. It exists because a UE that has nothing to send stops appearing in
# any KPI the scheduler derives per report period, and eventually trips the
# gNB's inactivity release. The interval is fractional on purpose: the KPIs are
# per-report-period sums, so an interval at or above the scheduler's report
# period (metrics.periodicity.du_report_period, 1000 ms as rendered) leaves the
# periods in between with a truthful but useless row of zeros. Keep it well
# under that period -- 0.2 s puts five packets in every report.
ue_keepalive_seconds="0"

# Optional gNB binary override. Unset, every use below resolves to exactly the
# path this script hardcoded before, so an unset run is the pre-change run.
gnb_binary=""

# gNB startup wait. Unset it stays 15 s, the value this script hardcoded before.
# A CUDA PHY build needs longer: its device-side initialisation runs before the
# gNB prints its started banner, and 15 s kills it mid-initialisation.
gnb_start_timeout_seconds="15"

# Extra seconds granted to the broker's own --duration clock, which starts
# when the broker process starts, not when the gNB's radio appears. Unset it
# is 0 and the broker is launched with exactly the duration it was launched
# with before. A CUDA PHY gNB needs it: its device-side initialisation runs
# for ~20 s before the ZMQ radio binds, so a broker holding only the measured
# duration self-exits before the gNB ever requests a sample, and the run ends
# with zero slots processed rather than with a verdict about acceleration.
broker_startup_allowance_seconds="0"

usage_error()
{
  printf 'error: %s\n' "$1" >&2
  exit 2
}

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --mode) mode="${2:-}"; shift 2 ;;
    --gnb-binary) gnb_binary="${2:-}"; shift 2 ;;
    --gnb-start-timeout-seconds) gnb_start_timeout_seconds="${2:-}"; shift 2 ;;
    --broker-startup-allowance-seconds) broker_startup_allowance_seconds="${2:-}"; shift 2 ;;
    --parent-netns) parent_netns="${2:-}"; shift 2 ;;
    --parent-mntns) parent_mntns="${2:-}"; shift 2 ;;
    --outer-uid) outer_uid="${2:-}"; shift 2 ;;
    --netns-dir) netns_dir="${2:-}"; shift 2 ;;
    --physical-gpu) physical_gpu="${2:-}"; shift 2 ;;
    --hardware-probe) hardware_probe="${2:-}"; shift 2 ;;
    --probe-broker) probe_broker="${2:-}"; shift 2 ;;
    --broker) runtime_broker="${2:-}"; shift 2 ;;
    --probe-config) probe_config="${2:-}"; shift 2 ;;
    --native-root) native_root="${2:-}"; shift 2 ;;
    --repo-root) repo_root="${2:-}"; shift 2 ;;
    --config-dir) config_dir="${2:-}"; shift 2 ;;
    --log-dir) log_dir="${2:-}"; shift 2 ;;
    --report-dir) report_dir="${2:-}"; shift 2 ;;
    --timestamp) timestamp="${2:-}"; shift 2 ;;
    --channel-mode) channel_mode="${2:-}"; shift 2 ;;
    --run-duration-seconds) run_duration_seconds="${2:-}"; shift 2 ;;
    --run-family) run_family="${2:-}"; shift 2 ;;
    --broker-ready-device) broker_ready_device="${2:-}"; shift 2 ;;
    --control-endpoint) control_endpoint="${2:-}"; shift 2 ;;
    --telemetry-endpoint) telemetry_endpoint="${2:-}"; shift 2 ;;
    --gnb-metrics-socket) gnb_metrics_socket="${2:-}"; shift 2 ;;
    --sionna-python) sionna_python="${2:-}"; shift 2 ;;
    --sionna-bridge) sionna_bridge="${2:-}"; shift 2 ;;
    --sionna-scenario-config) sionna_scenario_config="${2:-}"; shift 2 ;;
    --sionna-status-jsonl) sionna_status_jsonl="${2:-}"; shift 2 ;;
    --sionna-update-hz) sionna_update_hz="${2:-}"; shift 2 ;;
    --sionna-ready-seconds) sionna_ready_seconds="${2:-}"; shift 2 ;;
    --live-ready-path) live_ready_path="${2:-}"; shift 2 ;;
    --live-ready-event) live_ready_event="${2:-}"; shift 2 ;;
    --ue-keepalive-seconds) ue_keepalive_seconds="${2:-}"; shift 2 ;;
    *) usage_error "unknown argument: $1" ;;
  esac
done

[[ "${mode}" == "probe" || "${mode}" == "run" ]] || usage_error "--mode must be probe or run"
[[ "${channel_mode}" == "legacy" || "${channel_mode}" == "sionna" || \
   "${channel_mode}" == "external" ]] || \
  usage_error "--channel-mode must be legacy, sionna or external"
[[ "${run_duration_seconds}" =~ ^(0|[1-9][0-9]*)$ ]] || usage_error "invalid run duration"
[[ "${broker_startup_allowance_seconds}" =~ ^(0|[1-9][0-9]*)$ ]] || \
  usage_error "invalid broker startup allowance"
[[ "${ue_keepalive_seconds}" =~ ^(0|0?\.[0-9]+|[1-9][0-9]*(\.[0-9]+)?)$ ]] || \
  usage_error "invalid keepalive interval"
if [[ "${ue_keepalive_seconds}" != "0" ]]; then
  # ping refuses intervals under 0.2 s without real privilege, and a
  # namespace-scoped capability would not help here.
  awk -v value="${ue_keepalive_seconds}" 'BEGIN { exit !(value >= 0.2 && value <= 60) }' || \
    usage_error "keepalive interval must be 0 or within [0.2, 60] seconds"
fi
if [[ "${mode}" == "run" ]]; then
  [[ "${run_family}" =~ ^[a-z0-9][a-z0-9-]*$ ]] || usage_error "invalid --run-family"
fi
[[ "${outer_uid}" =~ ^(0|[1-9][0-9]*)$ ]] || usage_error "invalid --outer-uid"
[[ "${physical_gpu}" =~ ^(0|[1-9][0-9]*)$ ]] || usage_error "invalid --physical-gpu"
[[ "${broker_ready_device}" =~ ^[A-Za-z0-9_-]+$ ]] || usage_error "invalid --broker-ready-device"
[[ "${netns_dir}" == /* && -d "${netns_dir}" && ! -L "${netns_dir}" ]] || usage_error "invalid --netns-dir"
[[ "$(readlink /proc/self/ns/net)" != "${parent_netns}" ]] || usage_error "network namespace was not isolated"
[[ "$(readlink /proc/self/ns/mnt)" != "${parent_mntns}" ]] || usage_error "mount namespace was not isolated"
awk -v uid="${outer_uid}" '$1 == 0 && $2 == uid && $3 == 1 { found = 1 } END { exit !found }' /proc/self/uid_map || \
  usage_error "user namespace does not contain the exact root mapping"
cap_eff="$(awk '/^CapEff:/ {print $2}' /proc/self/status)"
cap_eff_value=$((16#${cap_eff}))
(( (cap_eff_value & (1 << 12)) != 0 )) || usage_error "CAP_NET_ADMIN is absent inside userns"
(( (cap_eff_value & (1 << 21)) != 0 )) || usage_error "CAP_SYS_ADMIN is absent inside userns"
[[ -c /dev/net/tun ]] || usage_error "/dev/net/tun is absent"
for command_name in ip mount umount nsenter timeout; do
  command -v "${command_name}" >/dev/null 2>&1 || usage_error "missing command: ${command_name}"
done
[[ -x /usr/bin/python3 ]] || usage_error "missing /usr/bin/python3"
if [[ "${mode}" == "run" && "${channel_mode}" != "legacy" ]]; then
  [[ "${live_ready_path}" == /* ]] || usage_error "live-ready path must be absolute"
  [[ "${control_endpoint}" == ipc://* && "${telemetry_endpoint}" == ipc://* ]] || \
    usage_error "rootless control and telemetry must use ipc:// endpoints"
fi
if [[ "${mode}" == "run" && "${channel_mode}" == "sionna" ]]; then
  [[ -x "${sionna_python}" ]] || usage_error "Sionna Python is missing"
  [[ -f "${sionna_bridge}" && ! -L "${sionna_bridge}" ]] || usage_error "Sionna bridge is missing"
  [[ -f "${sionna_scenario_config}" && ! -L "${sionna_scenario_config}" ]] || \
    usage_error "Sionna scenario config is missing"
  [[ "${sionna_status_jsonl}" == /* ]] || \
    usage_error "Sionna artifact paths must be absolute"
  [[ "${sionna_update_hz}" =~ ^[0-9]+([.][0-9]+)?$ ]] || usage_error "invalid Sionna update rate"
  [[ "${sionna_ready_seconds}" =~ ^[1-9][0-9]*$ ]] || usage_error "invalid Sionna ready timeout"
  [[ "${live_ready_event}" =~ ^[a-z0-9_]+$ ]] || usage_error "invalid live-ready event"
fi

mount_active=0
root_tun=""
nested_name=""
declare -a process_names=()
declare -a process_pids=()
declare -a process_pgids=()
started_pid=""

process_running()
{
  local pid="$1"
  local state
  state="$(ps -o stat= -p "${pid}" 2>/dev/null | awk '{print $1}')"
  [[ -n "${state}" && "${state:0:1}" != "Z" ]]
}

# Session members of a group started by start_group (setsid makes pid = pgid
# = sid). Children the leader forked stay in its session even if they change
# group, and they can outlive the leader.
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
  local pid="${process_pids[index]}"
  local pgid="${process_pgids[index]}"
  local signal deadline
  [[ "${pid}" =~ ^[1-9][0-9]*$ && "${pgid}" =~ ^[1-9][0-9]*$ && "${pgid}" -gt 1 ]] || return 0
  # Wait on the whole group, not the leader: a leader that exits or aborts
  # during teardown (open5gs 5gc) used to leave its forked daemons running.
  if group_alive "${pgid}"; then
    for signal in INT TERM KILL; do
      signal_group "${signal}" "${pgid}"
      deadline=$((SECONDS + 4))
      while group_alive "${pgid}" && [[ "${SECONDS}" -lt "${deadline}" ]]; do
        sleep 0.1
      done
      group_alive "${pgid}" || break
    done
    if group_alive "${pgid}"; then
      printf 'error: %s group %s remains alive after bounded KILL\n' \
        "${process_names[index]}" "${pgid}" >&2
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
  # Stop the keepalive first: no reason to keep injecting user-plane traffic
  # into a stack that is being torn down. Then Broker admission, while both
  # radio requesters are still alive, then the radio peers, and finally their
  # core/database dependencies.
  for wanted in ue-keepalive sionna broker srsue gnb open5gs mongod; do
    for ((index=0; index<${#process_pids[@]}; index++)); do
      if [[ "${process_names[index]}" == "${wanted}" ]]; then
        if stop_group "${index}"; then
          process_pids[index]="0"
        else
          cleanup_failed=1
        fi
      fi
    done
  done
  for ((index=${#process_pids[@]}-1; index>=0; index--)); do
    stop_group "${index}" || cleanup_failed=1
  done
  if [[ -n "${nested_name}" ]]; then
    ip netns del "${nested_name}" >/dev/null 2>&1 || true
  fi
  if [[ -n "${root_tun}" ]]; then
    ip link del "${root_tun}" >/dev/null 2>&1 || true
  fi
  if [[ "${mount_active}" -eq 1 ]]; then
    umount /run/netns >/dev/null 2>&1 || true
  fi
  if [[ "${cleanup_failed}" -ne 0 && "${original_status}" -eq 0 ]]; then
    original_status=124
  fi
  exit "${original_status}"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

prepare_namespace()
{
  mount --make-rprivate /
  mount --bind "${netns_dir}" /run/netns
  mount_active=1
  ip link set lo up
}

run_probe()
{
  [[ -x "${hardware_probe}" ]] || usage_error "hardware probe is missing"
  [[ -x "${probe_broker}" ]] || usage_error "probe Broker is missing"
  [[ "${probe_config}" == /* && -f "${probe_config}" && ! -L "${probe_config}" ]] || \
    usage_error "probe topology is missing or unsafe"
  prepare_namespace
  /usr/bin/python3 -c 'import socket; s=socket.socket(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_SCTP); s.bind(("127.0.0.1", 0)); s.close()'
  root_tun="ogstun_probe"
  ip tuntap add dev "${root_tun}" mode tun
  ip addr add 10.254.0.1/30 dev "${root_tun}"
  ip link set "${root_tun}" up
  nested_name="ue1probe"
  ip netns add "${nested_name}"
  nsenter --net="/run/netns/${nested_name}" -- ip link set lo up
  nsenter --net="/run/netns/${nested_name}" -- ip tuntap add dev tun_srsue_probe mode tun
  nsenter --net="/run/netns/${nested_name}" -- ip link set tun_srsue_probe up
  nsenter --net="/run/netns/${nested_name}" -- ip link del tun_srsue_probe
  probe_output="$(CUDA_VISIBLE_DEVICES="${physical_gpu}" "${hardware_probe}" 2>&1)" || {
    printf '%s\n' "${probe_output}" >&2
    usage_error "CUDA hardware probe failed inside isolated userns"
  }
  printf '%s\n' "${probe_output}"
  grep -qx 'test_hardware_probe OK' <<<"${probe_output}" || \
    usage_error "CUDA hardware test did not emit its exact success token"
  broker_probe_output="$(CUDA_VISIBLE_DEVICES="${physical_gpu}" timeout -s TERM -k 2s 15s \
    "${probe_broker}" --config "${probe_config}" --duration 1ms --hardware-strict 2>&1)" || {
    printf '%s\n' "${broker_probe_output}" >&2
    usage_error "selected CUDA device Broker probe failed inside isolated userns"
  }
  printf '%s\n' "${broker_probe_output}" | grep -E \
    '^(event=start backend=cuda |event=hardware_probe ok=true device=0 |event=hardware_footprint |event=stop )'
  grep -q '^event=start backend=cuda ' <<<"${broker_probe_output}" || \
    usage_error "Broker probe did not start the CUDA backend"
  grep -q '^event=hardware_probe ok=true device=0 ' <<<"${broker_probe_output}" || \
    usage_error "Broker probe did not validate logical CUDA device 0"
  [[ "${broker_probe_output}" != *cuda_device_channel_fallback* ]] || \
    usage_error "Broker probe used a CUDA channel fallback"
  echo "event=native_userns_primitive_probe result=pass"
}

start_group()
{
  local name="$1"
  local output="$2"
  shift 2
  # The outer gate holds its flock on OCUDU_NATIVE_GATE_LOCK_FD. Close it in
  # the child: a process that outlives teardown must not keep the lock (a
  # stray open5gs-scpd once refused seven later runs, S15).
  local gate_lock_fd="${OCUDU_NATIVE_GATE_LOCK_FD:-}"
  if [[ "${gate_lock_fd}" =~ ^[0-9]+$ && "${gate_lock_fd}" -gt 2 ]]; then
    setsid stdbuf -oL -eL "$@" >"${output}" 2>&1 {gate_lock_fd}>&- &
  else
    setsid stdbuf -oL -eL "$@" >"${output}" 2>&1 &
  fi
  local pid="$!"
  local pgid
  # setsid runs in the background child; poll until it has made the group.
  for _ in $(seq 1 50); do
    pgid="$(ps -o pgid= -p "${pid}" | tr -d '[:space:]')"
    [[ "${pgid}" == "${pid}" ]] && break
    sleep 0.02
  done
  [[ "${pid}" =~ ^[1-9][0-9]*$ && "${pgid}" == "${pid}" ]] || usage_error "invalid process group for ${name}"
  process_names+=("${name}")
  process_pids+=("${pid}")
  process_pgids+=("${pgid}")
  started_pid="${pid}"
}

wait_log()
{
  local path="$1"
  local token="$2"
  local pid="$3"
  local seconds="$4"
  local deadline=$((SECONDS + seconds))
  while [[ "${SECONDS}" -lt "${deadline}" ]]; do
    grep -q -- "${token}" "${path}" 2>/dev/null && return 0
    process_running "${pid}" || return 1
    sleep 0.25
  done
  return 1
}

write_summary()
{
  local status="$1"
  local broker_status="$2"
  local rrc="$3"
  local pdu="$4"
  local ping_ok="$5"
  local rx_starvations="$6"
  local tx_queue_overflows="$7"
  local tx_sequence_gaps="$8"
  local zmq_errors="$9"
  local gnb_alive="${10}"
  local fivegc_alive="${11}"
  local srsue_alive="${12}"
  local sionna_updates="${13:-0}"
  local telemetry_frames="${14:-0}"
  local control_batches_committed="${15:-0}"
  /usr/bin/python3 - "${report_dir}/attach-summary.json" "${timestamp}" "${status}" \
    "${broker_status}" "${rrc}" "${pdu}" "${ping_ok}" "${rx_starvations}" \
    "${tx_queue_overflows}" "${tx_sequence_gaps}" "${zmq_errors}" \
    "${gnb_alive}" "${fivegc_alive}" "${srsue_alive}" \
    "${channel_mode}" "${run_duration_seconds}" "${sionna_updates}" \
    "${telemetry_frames}" "${control_batches_committed}" \
    "${log_dir}" "${report_dir}" <<'PY'
import json
import sys

(path, timestamp, status, broker_status, rrc, pdu, ping_ok, rx_starvations,
 tx_queue_overflows, tx_sequence_gaps, zmq_errors, gnb_alive, fivegc_alive,
 srsue_alive, channel_mode, duration_seconds, sionna_updates,
 telemetry_frames, control_batches_committed, log_dir, report_dir) = sys.argv[1:]
data = {
    "timestamp": timestamp,
    "status": status,
    "duration_seconds": int(duration_seconds),
    "channel_mode": channel_mode,
    "srsran_ref": "release_23_11",
    "runtime_mode": "rootless_user_net_mount_namespace",
    "docker_used": False,
    "primitive_probe_passed": True,
    "broker_status": int(broker_status),
    "rrc_connected": int(rrc),
    "pdu_session_established": int(pdu),
    "ping_ok": int(ping_ok),
    "gnb_alive_at_broker_stop": int(gnb_alive),
    "open5gs_alive_at_broker_stop": int(fivegc_alive),
    "srsue_alive_at_broker_stop": int(srsue_alive),
    "rx_starvations": int(rx_starvations),
    "tx_queue_overflows": int(tx_queue_overflows),
    "tx_sequence_gaps": int(tx_sequence_gaps),
    "zmq_errors": int(zmq_errors),
    "sionna_updates": int(sionna_updates),
    "telemetry_frames": int(telemetry_frames),
    "control_batches_committed": int(control_batches_committed),
    "log_dir": log_dir,
    "report_dir": report_dir,
}
with open(path, "x", encoding="utf-8") as output:
    json.dump(data, output, indent=2, sort_keys=True)
    output.write("\n")
PY
}

extract_counter()
{
  local key="$1"
  local line="$2"
  local value
  value="$(sed -n "s/.*${key}=\([0-9][0-9]*\).*/\1/p" <<<"${line}")"
  printf '%s\n' "${value:-0}"
}

write_live_ready()
{
  local rrc="$1"
  local pdu="$2"
  local ping_ok="$3"
  [[ "${channel_mode}" != "legacy" ]] || return 0
  /usr/bin/python3 - "${live_ready_path}" "${timestamp}" "${rrc}" "${pdu}" \
    "${ping_ok}" "${sionna_status_jsonl}" "${control_endpoint}" \
    "${telemetry_endpoint}" "${live_ready_event}" <<'PY'
import json
import sys

(path, timestamp, rrc, pdu, ping_ok, status_jsonl, control_endpoint,
 telemetry_endpoint, live_ready_event) = sys.argv[1:]
with open(path, "x", encoding="utf-8") as output:
    json.dump(
        {
            "event": live_ready_event,
            "timestamp": timestamp,
            "rrc_connected": int(rrc),
            "pdu_session_established": int(pdu),
            "ping_ok": int(ping_ok),
            "sionna_status_jsonl": status_jsonl,
            "control_endpoint": control_endpoint,
            "telemetry_endpoint": telemetry_endpoint,
        },
        output,
        indent=2,
        sort_keys=True,
    )
    output.write("\n")
PY
}

run_stack()
{
  for required in "${native_root}" "${repo_root}" "${config_dir}" "${log_dir}" "${report_dir}"; do
    [[ "${required}" == /* && -d "${required}" && ! -L "${required}" ]] || usage_error "invalid run directory: ${required}"
  done
  local gnb="${gnb_binary:-${native_root}/builds/ocudu-zmq-release/apps/gnb/gnb}"
  local srsue="${native_root}/builds/srsran4g-zmq-release/srsue/src/srsue"
  local fivegc="${native_root}/builds/open5gs-v2.7.6/tests/app/5gc"
  local mongod="${native_root}/install/mongodb-6.0.29/bin/mongod"
  local broker="${runtime_broker}"
  local add_users="${native_root}/src/ocudu/docker/open5gs/add_users.py"
  local subscriber_verify="${repo_root}/scripts/native/verify-open5gs-subscriber.py"
  for binary in "${gnb}" "${srsue}" "${fivegc}" "${mongod}" "${broker}"; do
    [[ -x "${binary}" ]] || usage_error "missing executable: ${binary}"
  done

  prepare_namespace
  root_tun="ogstun"
  ip tuntap add dev "${root_tun}" mode tun
  # Open5GS advertises 10.45.0.1 for the dynamic pool, while the immutable
  # legacy subscriber is pinned to 10.45.1.2 and uses 10.45.1.1 as gateway.
  ip addr add 10.45.0.1/24 dev "${root_tun}"
  ip addr add 10.45.1.1/24 dev "${root_tun}"
  ip link set "${root_tun}" up
  nested_name="ue1"
  ip netns add "${nested_name}"
  nsenter --net="/run/netns/${nested_name}" -- ip link set lo up

  local data_dir="${native_root}/data/${run_family}/${timestamp}"
  local mongod_pid fivegc_pid broker_pid gnb_pid srsue_pid sionna_pid=""
  local broker_index broker_exit_deadline sionna_index=-1 sionna_failed=0
  start_group mongod "${log_dir}/mongod-console.log" "${mongod}" --dbpath "${data_dir}" --bind_ip 127.0.0.1 --port 27017 --logpath "${log_dir}/mongod.log"
  mongod_pid="${started_pid}"
  /usr/bin/python3 - "${mongod_pid}" <<'PY'
import socket
import sys
import time
pid = int(sys.argv[1])
deadline = time.monotonic() + 20
while time.monotonic() < deadline:
    try:
        with socket.create_connection(("127.0.0.1", 27017), timeout=.25):
            raise SystemExit(0)
    except OSError:
        time.sleep(.25)
raise SystemExit(2)
PY
  # PYTHONDONTWRITEBYTECODE: add_users imports Open5GS.py straight out of the
  # pinned open5gs checkout, and the __pycache__ CPython would drop there makes
  # that checkout dirty -- which fails the workspace lock on the NEXT run, so
  # the gate could only ever be run once. Suppressing bytecode keeps the
  # audited source tree byte-identical across runs.
  PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH="${native_root}/src/open5gs:${PYTHONPATH:-}" /usr/bin/python3 "${add_users}" \
    --mongodb 127.0.0.1 --mongodb_port 27017 --subscriber_data "${config_dir}/subscriber.csv" \
    >"${log_dir}/subscriber-insert.log" 2>&1
  /usr/bin/python3 "${subscriber_verify}" --subscriber-csv "${config_dir}/subscriber.csv" \
    >"${log_dir}/subscriber-verify.log" 2>&1

  start_group open5gs "${log_dir}/open5gs.log" "${fivegc}" -c "${config_dir}/open5gs.yaml"
  fivegc_pid="${started_pid}"
  /usr/bin/python3 - <<'PY'
import socket
import time
deadline = time.monotonic() + 30
while time.monotonic() < deadline:
    try:
        with socket.create_connection(("127.0.0.20", 7777), timeout=.25):
            raise SystemExit(0)
    except OSError:
        time.sleep(.25)
raise SystemExit(2)
PY
  local broker_duration_seconds="${run_duration_seconds}"
  if [[ "${run_duration_seconds}" -gt 0 ]]; then
    broker_duration_seconds=$((run_duration_seconds + broker_startup_allowance_seconds))
  fi
  local broker_args=(
    "${broker}" --config "${config_dir}/topology.yaml"
    --duration "${broker_duration_seconds}s"
  )
  if [[ "${channel_mode}" != "legacy" ]]; then
    broker_args+=(
      --control-endpoint "${control_endpoint}"
      --telemetry-endpoint "${telemetry_endpoint}"
      --telemetry-rate-hz 500
    )
  fi
  start_group broker "${log_dir}/broker.log" env CUDA_VISIBLE_DEVICES="${physical_gpu}" \
    "${broker_args[@]}"
  broker_pid="${started_pid}"
  broker_index=$((${#process_pids[@]} - 1))
  # Bound a finite run while allowing duration=0 to remain live until SIGINT.
  if [[ "${run_duration_seconds}" -gt 0 ]]; then
    broker_exit_deadline=$((SECONDS + broker_duration_seconds + 10))
  else
    broker_exit_deadline=0
  fi
  wait_log "${log_dir}/broker.log" "event=socket_ready device=${broker_ready_device} " \
    "${broker_pid}" 15 || usage_error "broker did not become ready"
  if [[ "${channel_mode}" != "legacy" ]]; then
    wait_log "${log_dir}/broker.log" 'event=control_start ' "${broker_pid}" 15 || \
      usage_error "broker control server did not become ready"
  fi
  if [[ "${channel_mode}" == "sionna" ]]; then
    start_group sionna "${log_dir}/sionna-bridge.log" \
      env CUDA_VISIBLE_DEVICES="${physical_gpu}" "${sionna_python}" "${sionna_bridge}" \
      --scenario-config "${sionna_scenario_config}" \
      --control-endpoint "${control_endpoint}" --duration 0 \
      --update-hz "${sionna_update_hz}" --status-jsonl "${sionna_status_jsonl}"
    sionna_pid="${started_pid}"
    sionna_index=$((${#process_pids[@]} - 1))
    wait_log "${log_dir}/sionna-bridge.log" '"event":"sionna_rt_update"' \
      "${sionna_pid}" "${sionna_ready_seconds}" || \
      usage_error "Sionna RT did not publish its first matrix profile update"
  fi
  start_group gnb "${log_dir}/gnb-console.log" "${gnb}" -c "${config_dir}/gnb.yaml"
  gnb_pid="${started_pid}"
  wait_log "${log_dir}/gnb-console.log" '==== gNB started ===' "${gnb_pid}" "${gnb_start_timeout_seconds}" || usage_error "gNB did not start"
  if [[ -n "${gnb_metrics_socket}" ]]; then
    # Runs inside this namespace so it can reach the gNB's loopback, and
    # writes its listening socket into the shared run directory. Started
    # after the gNB so the first dashboard connection finds a live port.
    start_group gnb-metrics-relay "${log_dir}/gnb-metrics-relay.log" \
      /usr/bin/python3 "${repo_root}/scripts/native/gnb-metrics-relay.py" \
      --socket "${gnb_metrics_socket}" --port "${gnb_metrics_port}"
  fi
  sleep 3
  start_group srsue "${log_dir}/srsue.log" "${srsue}" "${config_dir}/srsue.conf"
  srsue_pid="${started_pid}"

  local attach_wait_seconds=20
  [[ "${channel_mode}" != "legacy" ]] && attach_wait_seconds=40
  local deadline=$((SECONDS + attach_wait_seconds))
  local rrc=0 pdu=0 ping_ok=0
  while [[ "${SECONDS}" -lt "${deadline}" ]] && process_running "${srsue_pid}"; do
    grep -q 'RRC Connected' "${log_dir}/srsue.log" 2>/dev/null && rrc=1
    grep -q 'PDU Session Establishment successful' "${log_dir}/srsue.log" 2>/dev/null && pdu=1
    [[ "${rrc}" -eq 1 && "${pdu}" -eq 1 ]] && break
    sleep 0.5
  done
  if [[ "${rrc}" -eq 1 && "${pdu}" -eq 1 ]]; then
    if nsenter --net=/run/netns/ue1 -- ping -I tun_srsue -c 3 -W 2 10.45.1.1 >"${log_dir}/ue-ping.log" 2>&1; then
      ping_ok=1
    fi
  fi
  if [[ "${rrc}" -eq 1 && "${pdu}" -eq 1 && "${ping_ok}" -eq 1 ]]; then
    write_live_ready "${rrc}" "${pdu}" "${ping_ok}"
    # Started only after the verdict is written. ue-ping.log -- which the
    # acceptance check reads -- stays the acceptance ping alone; the keepalive
    # writes to its own log, so the verdict path is unchanged either way.
    #
    # Bounded runs were excluded here so that the gate kept the exact traffic
    # profile it was proven with. That still holds by default: the interval is
    # 0 unless a caller sets it, so an unset run carries the same traffic it
    # always did. A bounded run may now opt in, because measuring uplink BLER
    # needs more than the attach exchange and one acceptance ping -- under
    # thirty PUSCH transmissions cannot express a one-percentage-point
    # difference, whatever threshold is written down.
    if [[ "${ue_keepalive_seconds}" != "0" ]]; then
      start_group ue-keepalive "${log_dir}/ue-keepalive.log" \
        nsenter --net=/run/netns/ue1 -- \
        ping -I tun_srsue -i "${ue_keepalive_seconds}" 10.45.1.1
    fi
  elif [[ "${run_duration_seconds}" -eq 0 ]] && process_running "${broker_pid}"; then
    # An unbounded live demo must still return a useful failure if attach did
    # not complete; otherwise the outer launcher would wait forever.
    stop_group "${broker_index}" || true
  fi

  while process_running "${broker_pid}" && \
        { [[ "${broker_exit_deadline}" -eq 0 ]] || [[ "${SECONDS}" -lt "${broker_exit_deadline}" ]]; }; do
    if [[ "${channel_mode}" == "sionna" ]] && ! process_running "${sionna_pid}"; then
      sionna_failed=1
      break
    fi
    sleep 0.1
  done
  local broker_status
  if [[ "${sionna_failed}" -ne 0 ]] && process_running "${broker_pid}"; then
    stop_group "${broker_index}" || true
  fi
  if process_running "${broker_pid}"; then
    printf 'error: broker exceeded its bounded natural-exit window\n' >&2
    stop_group "${broker_index}" || true
    broker_status=124
  else
    set +e
    wait "${broker_pid}"
    broker_status="$?"
    set -e
  fi
  process_pids[broker_index]="0"
  if [[ "${sionna_index}" -ge 0 ]]; then
    stop_group "${sionna_index}" || true
    process_pids[sionna_index]="0"
  fi
  local gnb_alive=0 fivegc_alive=0 srsue_alive=0
  process_running "${gnb_pid}" && gnb_alive=1
  process_running "${fivegc_pid}" && fivegc_alive=1
  process_running "${srsue_pid}" && srsue_alive=1
  local stop_line rx_starvations tx_queue_overflows tx_sequence_gaps zmq_errors status
  local sionna_updates=0 telemetry_frames=0 control_batches_committed=0
  stop_line="$(grep '^event=stop ' "${log_dir}/broker.log" | tail -n 1 || true)"
  rx_starvations="$(extract_counter rx_starvations "${stop_line}")"
  tx_queue_overflows="$(extract_counter tx_queue_overflows "${stop_line}")"
  tx_sequence_gaps="$(extract_counter tx_sequence_gaps "${stop_line}")"
  zmq_errors="$(extract_counter zmq_errors "${stop_line}")"
  telemetry_frames="$(extract_counter telemetry_frames "${stop_line}")"
  control_batches_committed="$(extract_counter control_batches_committed "${stop_line}")"
  if [[ "${channel_mode}" == "sionna" ]]; then
    sionna_updates="$(grep -c '"event":"sionna_rt_update"' "${log_dir}/sionna-bridge.log" 2>/dev/null)" || \
      sionna_updates=0
  fi
  status="passed"
  if [[ "${broker_status}" -ne 0 || "${tx_queue_overflows}" -ne 0 || "${tx_sequence_gaps}" -ne 0 || "${zmq_errors}" -ne 0 ]]; then
    status="broker_failed"
  elif [[ "${gnb_alive}" -ne 1 || "${fivegc_alive}" -ne 1 || "${srsue_alive}" -ne 1 ]]; then
    status="stack_process_exited_before_broker_stop"
  elif [[ "${rrc}" -ne 1 || "${pdu}" -ne 1 ]]; then
    status="ue_stack_blocker_no_attach"
  elif [[ "${ping_ok}" -ne 1 ]]; then
    status="ue_stack_blocker_ping_failed"
  elif [[ "${channel_mode}" == "sionna" && \
          ( "${sionna_failed}" -ne 0 || "${sionna_updates}" -lt 1 || \
            "${telemetry_frames}" -lt 1 || "${control_batches_committed}" -lt 1 ) ]]; then
    status="sionna_observability_failed"
  fi
  write_summary "${status}" "${broker_status}" "${rrc}" "${pdu}" "${ping_ok}" \
    "${rx_starvations}" "${tx_queue_overflows}" "${tx_sequence_gaps}" "${zmq_errors}" \
    "${gnb_alive}" "${fivegc_alive}" "${srsue_alive}" \
    "${sionna_updates}" "${telemetry_frames}" "${control_batches_committed}"
  [[ "${status}" == "passed" ]]
}

if [[ "${mode}" == "probe" ]]; then
  run_probe
else
  run_stack
fi
