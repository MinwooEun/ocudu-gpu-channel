#!/usr/bin/env bash
set -euo pipefail

# Inner runner for the LIVE-RADIO demo tier (plan S5): real Open5GS core,
# real OCUDU 2T2R gNB, real srsUE, attached through the CUDA broker -- the
# rank-1 2x1 gate stack (run-ocudu-rank1-2x1-inner.sh) turned into a
# long-running demo:
#   - broker runs for the demo duration with --control-endpoint and
#     --telemetry-endpoint on ipc:// sockets (ipc crosses the network
#     namespace because the filesystem is shared, so the host-side bridge
#     can drive path_loss and read telemetry without holes in the netns);
#   - srsUE writes metrics CSV for the host-side tailer;
#   - after attach, a continuous ping runs in the UE netns and its output
#     is tailed by the host for the page's RTT sparkline.
# No audit pins, no validators, no wire capture: this is a demo, the gates
# stay untouched.

mode="run"
parent_netns=""
parent_mntns=""
outer_uid=""
netns_dir=""
physical_gpu=""
native_root=""
repo_root=""
config_dir=""
log_dir=""
duration_seconds=""
# add_users.py needs pymongo; the system python3 no longer carries it on this
# box, so the outer script passes whichever interpreter does.
python_mongo="/usr/bin/python3"

usage_error()
{
  printf 'error: %s\n' "$1" >&2
  exit 2
}

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --parent-netns) parent_netns="${2:-}"; shift 2 ;;
    --parent-mntns) parent_mntns="${2:-}"; shift 2 ;;
    --outer-uid) outer_uid="${2:-}"; shift 2 ;;
    --netns-dir) netns_dir="${2:-}"; shift 2 ;;
    --physical-gpu) physical_gpu="${2:-}"; shift 2 ;;
    --native-root) native_root="${2:-}"; shift 2 ;;
    --repo-root) repo_root="${2:-}"; shift 2 ;;
    --config-dir) config_dir="${2:-}"; shift 2 ;;
    --log-dir) log_dir="${2:-}"; shift 2 ;;
    --duration) duration_seconds="${2:-}"; shift 2 ;;
    --python-mongo) python_mongo="${2:-}"; shift 2 ;;
    *) usage_error "unknown argument: $1" ;;
  esac
done

[[ "${outer_uid}" =~ ^(0|[1-9][0-9]*)$ ]] || usage_error "invalid --outer-uid"
[[ "${physical_gpu}" =~ ^(0|[1-9][0-9]*)$ ]] || usage_error "invalid --physical-gpu"
[[ "${duration_seconds}" =~ ^[1-9][0-9]*$ ]] || usage_error "invalid --duration"
[[ "${netns_dir}" == /* && -d "${netns_dir}" && ! -L "${netns_dir}" ]] || usage_error "invalid --netns-dir"
[[ "$(readlink /proc/self/ns/net)" != "${parent_netns}" ]] || usage_error "network namespace was not isolated"
[[ "$(readlink /proc/self/ns/mnt)" != "${parent_mntns}" ]] || usage_error "mount namespace was not isolated"
awk -v uid="${outer_uid}" '$1 == 0 && $2 == uid && $3 == 1 { found = 1 } END { exit !found }' /proc/self/uid_map || \
  usage_error "user namespace does not contain the exact root mapping"
[[ -c /dev/net/tun ]] || usage_error "/dev/net/tun is absent"
for command_name in ip mount umount nsenter timeout; do
  command -v "${command_name}" >/dev/null 2>&1 || usage_error "missing command: ${command_name}"
done

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

stop_group()
{
  local index="$1"
  local pid="${process_pids[index]}"
  local pgid="${process_pgids[index]}"
  local signal deadline
  [[ "${pid}" =~ ^[1-9][0-9]*$ && "${pgid}" =~ ^[1-9][0-9]*$ && "${pgid}" -gt 1 ]] || return 0
  process_running "${pid}" || return 0
  for signal in INT TERM KILL; do
    kill -s "${signal}" -- "-${pgid}" >/dev/null 2>&1 || true
    deadline=$((SECONDS + 4))
    while process_running "${pid}" && [[ "${SECONDS}" -lt "${deadline}" ]]; do
      sleep 0.1
    done
    process_running "${pid}" || break
  done
  wait "${pid}" >/dev/null 2>&1 || true
  return 0
}

cleanup()
{
  local original_status="$?"
  set +e
  trap - EXIT INT TERM HUP
  local index wanted
  # Broker admission stops first while both radio requesters are alive, then
  # the radios, then core and database -- same order as the gate.
  for wanted in ping broker srsue gnb open5gs mongod; do
    for ((index=0; index<${#process_pids[@]}; index++)); do
      if [[ "${process_names[index]}" == "${wanted}" ]]; then
        stop_group "${index}"
        process_pids[index]="0"
      fi
    done
  done
  for ((index=${#process_pids[@]}-1; index>=0; index--)); do
    stop_group "${index}"
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
  exit "${original_status}"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

start_group()
{
  local name="$1"
  local output="$2"
  shift 2
  setsid stdbuf -oL -eL "$@" >"${output}" 2>&1 &
  local pid="$!"
  local pgid
  pgid="$(ps -o pgid= -p "${pid}" | tr -d '[:space:]')"
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

status_file="${log_dir}/live-status.json"
write_status()
{
  # Atomically publish the stack state for the host-side tailer.
  printf '{"phase": "%s", "t": %s}\n' "$1" "$(date +%s)" >"${status_file}.tmp"
  mv -f "${status_file}.tmp" "${status_file}"
}

gnb="${native_root}/builds/ocudu-zmq-release/apps/gnb/gnb"
srsue="${native_root}/builds/srsran4g-zmq-release/srsue/src/srsue"
fivegc="${native_root}/builds/open5gs-v2.7.6/tests/app/5gc"
mongod="${native_root}/install/mongodb-6.0.29/bin/mongod"
broker="${native_root}/builds/ocudu-gpu-channel-rank1-cuda-release/ocudu-gpu-channel"
add_users="${native_root}/src/ocudu/docker/open5gs/add_users.py"
for binary in "${gnb}" "${srsue}" "${fivegc}" "${mongod}" "${broker}"; do
  [[ -x "${binary}" ]] || usage_error "missing executable: ${binary}"
done

write_status "starting"
mount --make-rprivate /
mount --bind "${netns_dir}" /run/netns
mount_active=1
ip link set lo up
root_tun="ogstun"
ip tuntap add dev "${root_tun}" mode tun
ip addr add 10.45.0.1/24 dev "${root_tun}"
ip addr add 10.45.1.1/24 dev "${root_tun}"
ip link set "${root_tun}" up
nested_name="ue1"
ip netns add "${nested_name}"
nsenter --net="/run/netns/${nested_name}" -- ip link set lo up

data_dir="${log_dir}/mongo-data"
mkdir -p "${data_dir}"
start_group mongod "${log_dir}/mongod-console.log" "${mongod}" \
  --dbpath "${data_dir}" --bind_ip 127.0.0.1 --port 27017 --logpath "${log_dir}/mongod.log"
/usr/bin/python3 - <<'PY'
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
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH="${native_root}/src/open5gs:${PYTHONPATH:-}" "${python_mongo}" "${add_users}" \
  --mongodb 127.0.0.1 --mongodb_port 27017 --subscriber_data "${config_dir}/subscriber.csv" \
  >"${log_dir}/subscriber-insert.log" 2>&1

write_status "core"
start_group open5gs "${log_dir}/open5gs.log" "${fivegc}" -c "${config_dir}/open5gs.yaml"
/usr/bin/python3 - <<'PY'
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

write_status "broker"
start_group broker "${log_dir}/broker.log" env CUDA_VISIBLE_DEVICES="${physical_gpu}" \
  "${broker}" --config "${config_dir}/topology.yaml" --duration "${duration_seconds}s" \
  --control-endpoint "ipc://${config_dir}/control.ipc" \
  --telemetry-endpoint "ipc://${config_dir}/telemetry.ipc" --telemetry-rate-hz 10
broker_pid="${started_pid}"
broker_index=$((${#process_pids[@]} - 1))
wait_log "${log_dir}/broker.log" 'event=radio_node_resolved id=ue0' "${broker_pid}" 15 || \
  usage_error "broker did not become ready"

write_status "gnb"
start_group gnb "${log_dir}/gnb-console.log" "${gnb}" -c "${config_dir}/gnb.yaml"
gnb_pid="${started_pid}"
wait_log "${log_dir}/gnb-console.log" '==== gNB started ===' "${gnb_pid}" 15 || \
  usage_error "gNB did not start"
sleep 3

write_status "srsue"
start_group srsue "${log_dir}/srsue.log" "${srsue}" "${config_dir}/srsue.conf"
srsue_pid="${started_pid}"

deadline=$((SECONDS + 60))
rrc=0; pdu=0
while [[ "${SECONDS}" -lt "${deadline}" ]] && process_running "${srsue_pid}"; do
  grep -q 'RRC Connected' "${log_dir}/srsue.log" 2>/dev/null && rrc=1
  grep -q 'PDU Session Establishment successful' "${log_dir}/srsue.log" 2>/dev/null && pdu=1
  [[ "${rrc}" -eq 1 && "${pdu}" -eq 1 ]] && break
  sleep 0.5
done
if [[ "${rrc}" -ne 1 || "${pdu}" -ne 1 ]]; then
  write_status "attach_failed"
  usage_error "srsUE did not attach (rrc=${rrc} pdu=${pdu}); see ${log_dir}/srsue.log"
fi
write_status "attached"

# Continuous RTT probe for the page: one ping per 0.5 s until teardown, output
# line-buffered so the host tailer sees each reply as it happens.
start_group ping "${log_dir}/ue-ping.log" \
  nsenter --net=/run/netns/ue1 -- ping -I tun_srsue -i 0.5 -W 2 10.45.1.1

echo "event=live_demo_up rrc=1 pdu=1 duration=${duration_seconds}s"
while process_running "${broker_pid}"; do
  sleep 1
done
process_pids[broker_index]="0"
write_status "stopped"
echo "event=live_demo_stop"
