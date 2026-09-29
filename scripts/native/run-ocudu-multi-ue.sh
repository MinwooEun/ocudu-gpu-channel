#!/usr/bin/env bash
# Native multi-UE attach gate: one OCUDU gNB, two srsUEs, Open5GS, and this
# tree's broker on examples/topology.ocudu-docker.multi-ue.cuda.yaml, with no
# container runtime anywhere.
#
# This is the Docker-free counterpart of scripts/remote/ocudu-multi-ue-smoke.sh.
# It exists because nested LXC blocks runc from writing
# net.ipv4.ip_unprivileged_port_start into a fresh network namespace, so no
# bridged container can start here, while `unshare --user --net` can.
#
# Like the 1x1 gate it builds the broker from THIS repository, so the binary
# under test is the working tree's, not a prebuilt artifact.
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/.." && cd .. && pwd)"
# shellcheck source=env.sh
source "${script_dir}/env.sh"

native_root="${OCUDU_NATIVE_ROOT}"
physical_gpu="${OCUDU_NATIVE_GPU_DEVICE:-0}"
cuda_compiler="${CUDACXX:-/opt/conda/envs/cuda128/bin/nvcc}"
inner="${script_dir}/run-ocudu-multi-ue-inner.sh"
# Sionna mode swaps the renderer for the scenario-driven one and adds the
# bridge, the broker control plane and the read-only web UI. Unset, this gate
# runs exactly as it always has, on the checked-in fixed-TDL topology.
channel_mode="${OCUDU_NATIVE_CHANNEL_MODE:-legacy}"
sionna_scenario="${OCUDU_NATIVE_SIONNA_SCENARIO:-}"
sionna_python="${OCUDU_NATIVE_SIONNA_PYTHON:-}"
sionna_update_hz="${OCUDU_NATIVE_SIONNA_UPDATE_HZ:-10}"
web_port="${OCUDU_NATIVE_WEB_PORT:-8080}"
if [[ "${channel_mode}" == "sionna" ]]; then
  renderer="${script_dir}/render-sionna-multi-ue-configs.py"
else
  renderer="${script_dir}/render-multi-ue-configs.py"
fi
audited_ocudu="a1916edcdbcd70ba6e0af47ee87be061dad5a4e4"
audited_srsran="eea87b1d893ae58e0b08bc381730c502024ae71f"
audited_open5gs="d9d3abdd480be96fac3bc8a997e83446648763ca"

usage_error()
{
  printf 'error: %s\n' "$1" >&2
  exit 2
}

[[ "$#" -eq 0 ]] || usage_error "usage: $0"
[[ "${channel_mode}" == "legacy" || "${channel_mode}" == "sionna" ]] || \
  usage_error "unsupported OCUDU_NATIVE_CHANNEL_MODE: ${channel_mode}"
if [[ "${channel_mode}" == "sionna" ]]; then
  [[ "${sionna_scenario}" == /* && -f "${sionna_scenario}" && ! -L "${sionna_scenario}" ]] || \
    usage_error "OCUDU_NATIVE_SIONNA_SCENARIO must be an absolute regular file"
  [[ -x "${sionna_python}" ]] || \
    usage_error "OCUDU_NATIVE_SIONNA_PYTHON must point at the Sionna interpreter"
  [[ "${web_port}" =~ ^[1-9][0-9]*$ && "${web_port}" -le 65535 ]] || \
    usage_error "invalid OCUDU_NATIVE_WEB_PORT: ${web_port}"
fi
[[ "${physical_gpu}" =~ ^(0|[1-9][0-9]*)$ && "${physical_gpu}" -le 255 ]] || usage_error "invalid GPU device"
[[ -x "${cuda_compiler}" ]] || usage_error "missing CUDA compiler: ${cuda_compiler}"
for command_name in unshare nsenter ip mount umount flock cmake ctest ss setsid stdbuf; do
  command -v "${command_name}" >/dev/null 2>&1 || usage_error "missing command: ${command_name}"
done
for path in "${inner}" "${renderer}" \
  "${native_root}/builds/ocudu-zmq-release/apps/gnb/gnb" \
  "${native_root}/builds/srsran4g-zmq-release/srsue/src/srsue" \
  "${native_root}/builds/open5gs-v2.7.6/tests/app/5gc" \
  "${native_root}/install/mongodb-6.0.29/bin/mongod" \
  "${repo_root}/examples/topology.ocudu-docker.multi-ue.cuda.yaml"; do
  [[ -e "${path}" ]] || usage_error "missing required path: ${path}"
done
[[ -c /dev/net/tun ]] || usage_error "/dev/net/tun is absent"
[[ "$(git -C "${native_root}/src/ocudu" rev-parse HEAD)" == "${audited_ocudu}" ]] || usage_error "OCUDU revision mismatch"
[[ "$(git -C "${native_root}/src/srsRAN_4G" rev-parse HEAD)" == "${audited_srsran}" ]] || usage_error "srsRAN revision mismatch"
[[ "$(git -C "${native_root}/src/open5gs" rev-parse HEAD)" == "${audited_open5gs}" ]] || usage_error "Open5GS revision mismatch"
if [[ "${OCUDU_NATIVE_SKIP_WORKSPACE_LOCK:-0}" == "1" ]]; then
  # The lock pins an x86_64 host; an aarch64 host (DGX Spark, Jetson) cannot
  # satisfy it. The source pins above are still checked.
  echo "event=skip x86_native_workspace_lock"
else
  "/usr/bin/python3" "${script_dir}/verify-workspace-lock.py" \
    --root "${native_root}" --repo-root "${repo_root}" \
    --lock "${script_dir}/native-workspace.lock.json"
fi
grep -qx 'ENABLE_ZEROMQ:BOOL=ON' "${native_root}/builds/ocudu-zmq-release/CMakeCache.txt" || usage_error "gNB lacks ZMQ"
# Ports for the gNB pair and BOTH UE pairs, plus mongo and the core.
for port in 2000 2001 2100 2101 2102 2103 27017 38412 7777; do
  ss -H -ltn "sport = :${port}" | grep -q . && usage_error "TCP port ${port} is already listening"
done

exec {lock_fd}<"${BASH_SOURCE[0]}"
flock -n "${lock_fd}" || usage_error "another native multi-UE gate is running"
export OCUDU_NATIVE_GATE_LOCK_FD="${lock_fd}"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
log_dir="${native_root}/results/logs/ocudu-multi-ue/${timestamp}"
report_dir="${native_root}/results/reports/ocudu-multi-ue/${timestamp}"
config_dir="${native_root}/configs/ocudu-multi-ue-native/${timestamp}"
data_dir="${native_root}/data/ocudu-multi-ue-native/${timestamp}"
netns_dir="${native_root}/run/ocudu-multi-ue-native/${timestamp}/netns"
for path in "${log_dir}" "${report_dir}" "${config_dir}" "${data_dir}" "${netns_dir}"; do
  [[ ! -e "${path}" && ! -L "${path}" ]] || usage_error "run path already exists: ${path}"
done
mkdir -p "${log_dir}" "${report_dir}" "${config_dir}" "${data_dir}" "${netns_dir}"

declare -a renderer_args=(
  --repo-root "${repo_root}" --native-root "${native_root}"
  --output-dir "${config_dir}" --log-dir "${log_dir}"
)
[[ "${channel_mode}" == "sionna" ]] && renderer_args+=(--scenario-config "${sionna_scenario}")
# UE count: 2 (default) or 4 (topology.ocudu-docker.multi-ue-quad). The fixed-TDL
# renderer supports both; the Sionna renderer is two-UE only.
ue_count="${OCUDU_NATIVE_MUE_UE_COUNT:-2}"
[[ "${ue_count}" =~ ^(2|4)$ ]] || usage_error "OCUDU_NATIVE_MUE_UE_COUNT must be 2 or 4"
if [[ "${ue_count}" != 2 ]]; then
  [[ "${channel_mode}" != "sionna" ]] || usage_error "OCUDU_NATIVE_MUE_UE_COUNT=${ue_count} needs the fixed-TDL channel mode"
  renderer_args+=(--ue-count "${ue_count}")
fi
export OCUDU_NATIVE_MUE_UE_COUNT="${ue_count}"
"/usr/bin/python3" "${renderer}" "${renderer_args[@]}" >"${log_dir}/render.log" 2>&1 || {
  cat "${log_dir}/render.log" >&2; usage_error "config rendering failed"
}
"${native_root}/builds/ocudu-zmq-release/apps/gnb/gnb" -c "${config_dir}/gnb.yaml" --dryrun \
  >"${log_dir}/gnb-dryrun.log" 2>&1 || { tail -20 "${log_dir}/gnb-dryrun.log" >&2; usage_error "gNB dry run failed"; }

# Build the broker from THIS tree, so the gate tests the working copy.
#
# OCUDU_NATIVE_CHANNEL_BUILD exists so the same gate can be pointed at a second
# build directory and run against another revision -- e.g. checking out the
# pre-MIMO baseline in a worktree and re-running to establish whether a live
# failure predates the change under test. CMake refuses to reuse a cache built
# from a different source dir, so each revision needs its own.
channel_build="${OCUDU_NATIVE_CHANNEL_BUILD:-${native_root}/builds/ocudu-gpu-channel-cuda-release}"
cmake -S "${repo_root}" -B "${channel_build}" -DCMAKE_BUILD_TYPE=Release \
  -DOCUDU_GPU_CHANNEL_ENABLE_CUDA=ON -DCMAKE_CUDA_COMPILER="${cuda_compiler}" \
  -DOCUDU_GPU_CHANNEL_CUDA_ARCHITECTURES=120 >"${log_dir}/cmake-configure.log" 2>&1 \
  || { tail -20 "${log_dir}/cmake-configure.log" >&2; usage_error "cmake configure"; }
cmake --build "${channel_build}" -j"$(nproc)" >"${log_dir}/cmake-build.log" 2>&1 \
  || { tail -20 "${log_dir}/cmake-build.log" >&2; usage_error "cmake build"; }
CUDA_VISIBLE_DEVICES="${physical_gpu}" \
  ctest --test-dir "${channel_build}" --output-on-failure >"${log_dir}/ctest.log" 2>&1 \
  || { tail -20 "${log_dir}/ctest.log" >&2; usage_error "ctest"; }

parent_netns="$(readlink /proc/self/ns/net)"
parent_mntns="$(readlink /proc/self/ns/mnt)"

declare -a inner_args=(
  --repo-root "${repo_root}" --native-root "${native_root}"
  --config-dir "${config_dir}" --log-dir "${log_dir}" --netns-dir "${netns_dir}"
  --timestamp "${timestamp}" --physical-gpu "${physical_gpu}"
  --channel-build "${channel_build}"
  --parent-netns "${parent_netns}" --parent-mntns "${parent_mntns}"
  --outer-uid "$(id -u)"
)
web_pid=""
if [[ "${channel_mode}" == "sionna" ]]; then
  # ipc:// under the run directory, so the control and telemetry sockets live
  # in the namespace the inner script owns and are not reachable from the host.
  run_dir="${native_root}/run/ocudu-multi-ue-native/${timestamp}"
  mkdir -p "${run_dir}"
  control_endpoint="ipc://${run_dir}/control.sock"
  telemetry_endpoint="ipc://${run_dir}/telemetry.sock"
  sionna_status_jsonl="${log_dir}/sionna-status.jsonl"
  inner_args+=(
    --channel-mode sionna
    --control-endpoint "${control_endpoint}"
    --telemetry-endpoint "${telemetry_endpoint}"
    --sionna-python "${sionna_python}"
    --sionna-bridge "${repo_root}/scripts/sionna_rt/run_bridge.py"
    --sionna-scenario-config "${sionna_scenario}"
    --sionna-status-jsonl "${sionna_status_jsonl}"
    --sionna-update-hz "${sionna_update_hz}"
  )
  # Read-only observer. It tails the status JSONL the bridge writes and
  # subscribes to broker telemetry; it never touches the control socket.
  "${sionna_python}" "${repo_root}/scripts/web_ui/server.py" \
    --port "${web_port}" --telemetry-endpoint "${telemetry_endpoint}" \
    --status-jsonl "${sionna_status_jsonl}" \
    --index "${repo_root}/scripts/web_ui/index.html" \
    >"${log_dir}/web-ui.log" 2>&1 &
  web_pid="$!"
  printf 'Web UI: http://127.0.0.1:%s\n' "${web_port}"
fi

set +e
unshare --user --map-root-user --net --mount --fork --kill-child --propagation private \
  "${inner}" "${inner_args[@]}"
inner_status="$?"
set -e
[[ -n "${web_pid}" ]] && kill "${web_pid}" >/dev/null 2>&1
[[ -n "${web_pid}" ]] && wait "${web_pid}" >/dev/null 2>&1

summary="${report_dir}/attach-summary.json"
if [[ "${inner_status}" -eq 0 && -f "${summary}" ]]; then
  printf 'event=native_multi_ue_attach_gate result=pass summary="%s"\n' "${summary}"
else
  [[ -f "${summary}" ]] && cat "${summary}" >&2
  printf 'event=native_multi_ue_attach_gate result=fail status=%s logs="%s"\n' \
    "${inner_status}" "${log_dir}" >&2
fi
exit "${inner_status}"
