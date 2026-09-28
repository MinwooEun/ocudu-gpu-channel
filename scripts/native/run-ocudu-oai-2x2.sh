#!/usr/bin/env bash
set -euo pipefail

# M6.3 -- the native OAI nrUE 2x2 SU-MIMO run.
#
# OCUDU gNB (2T2R) <-> CUDA broker with a fixed 2x2 matrix <-> OAI nrUE
# (2 RX / 2 TX), single UE. Same Open5GS / subscriber / cell identity as the
# OAI 1x1 gate; see render-oai-2x2-configs.py for exactly what differs.
#
# Knobs (environment):
#   OAI2X2_PATH           broker (default) | direct (no emulator, identity H)
#   OAI2X2_MAX_RANK       2 (default) | 1
#   OAI2X2_MAX_UE_MCS     optional PDSCH MCS cap
#   OAI2X2_CSI_RS         on (default) | off
#   OAI2X2_TX_BACKOFF_DB  gNB amplitude_control.tx_gain_backoff (OCUDU default 12)
#   OAI2X2_TOPOLOGY       topology fixture (default the 2x2 fixture)
#   OAI2X2_BROKER_SECONDS run window (default 90)
#   OAI2X2_IPERF_SECONDS  DL UDP iperf length, 0 disables (default 15)
#   OAI2X2_IPERF_RATE     DL UDP offered rate (default 80M)
#   OAI2X2_BROKER_EXTRA   extra broker arguments (e.g. wire capture)
#   OAI2X2_UE_EXTRA       extra nr-uesoftmodem arguments
#   OAI2X2_NRUE_DIR       OAI build directory (default builds/oai-zmq-release)
#   OCUDU_NATIVE_OAI_ZMQ_MODULE  patched (default: builds/oai-zmq-s9, the S9
#                         reply-poll driver) or stock (builds/oai-zmq-release)
#   OCUDU_NATIVE_OAI_SHLIBPATH  explicit ZMQ radio module directory; overrides
#                         OCUDU_NATIVE_OAI_ZMQ_MODULE
#   OAI2X2_LABEL          free-text label stored with the run
#
# Output: results/{logs,reports}/oai-2x2/<timestamp>/, then
# summarize-oai-2x2-run.py prints rank / HARQ / throughput from the logs.

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"
# shellcheck source=env.sh
source "${script_dir}/env.sh"

native_root="${OCUDU_NATIVE_ROOT}"
# shellcheck source=oai-zmq-module.sh
source "${script_dir}/oai-zmq-module.sh"
physical_gpu="${OCUDU_NATIVE_GPU_DEVICE:-0}"
cuda_compiler="${CUDACXX:-/usr/local/cuda/bin/nvcc}"
inner="${script_dir}/run-ocudu-oai-2x2-inner.sh"
renderer="${script_dir}/render-oai-2x2-configs.py"
summarizer="${script_dir}/summarize-oai-2x2-run.py"
audited_ocudu="a1916edcdbcd70ba6e0af47ee87be061dad5a4e4"
audited_oai="2b69bde6aeafe892cda1531a0f0cbba2e37792cd"

export OAI2X2_PATH="${OAI2X2_PATH:-broker}"
max_rank="${OAI2X2_MAX_RANK:-2}"
csi_rs="${OAI2X2_CSI_RS:-on}"
topology="${OAI2X2_TOPOLOGY:-${repo_root}/examples/native/topology.ocudu.oai-2x2.cuda.yaml}"

usage_error()
{
  printf 'error: %s\n' "$1" >&2
  exit 2
}

[[ "$#" -eq 0 ]] || usage_error "usage: $0 (configure with OAI2X2_* variables)"
[[ "${OAI2X2_PATH}" == broker || "${OAI2X2_PATH}" == direct ]] || usage_error "OAI2X2_PATH must be broker or direct"
[[ "${native_root}" == /* && "${native_root}" != "/" ]] || usage_error "invalid native root"
[[ -x "${cuda_compiler}" ]] || usage_error "missing CUDA compiler: ${cuda_compiler}"
for command_name in unshare nsenter ip mount umount flock cmake ss setsid stdbuf iperf3; do
  command -v "${command_name}" >/dev/null 2>&1 || usage_error "missing command: ${command_name}"
done
[[ "$(git -C "${native_root}/src/ocudu" rev-parse HEAD)" == "${audited_ocudu}" ]] || usage_error "OCUDU revision mismatch"
[[ "$(git -C "${native_root}/src/oai" rev-parse HEAD)" == "${audited_oai}" ]] || usage_error "OAI revision mismatch"
# Exports OCUDU_NATIVE_OAI_SHLIBPATH for the inner script (patched by default).
resolve_oai_zmq_module "${native_root}" || usage_error "OAI ZMQ module selection failed"
printf 'oai zmq module: %s %s\n' "${OAI_ZMQ_MODULE_VARIANT}" "${OCUDU_NATIVE_OAI_SHLIBPATH}"

exec {lock_fd}<"${script_dir}/run-ocudu-oai-1x1.sh"
flock -n "${lock_fd}" || usage_error "another native OAI gate is running"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
results_root="${native_root}/results"
log_dir="${results_root}/logs/oai-2x2/${timestamp}"
report_dir="${results_root}/reports/oai-2x2/${timestamp}"
config_dir="${native_root}/configs/ocudu-oai-2x2-native/${timestamp}"
netns_dir="${native_root}/run/ocudu-oai-2x2-native/${timestamp}/netns"
data_dir="${native_root}/data/ocudu-oai-2x2-native/${timestamp}"
mkdir -p "${log_dir}" "${report_dir}" "${config_dir}" "${netns_dir}" "${data_dir}"

render_args=(--repo-root "${repo_root}" --native-root "${native_root}" --output-dir "${config_dir}"
  --log-dir "${log_dir}" --path "${OAI2X2_PATH}" --max-rank "${max_rank}" --csi-rs "${csi_rs}"
  --topology "${topology}")
[[ -n "${OAI2X2_MAX_UE_MCS:-}" ]] && render_args+=(--max-ue-mcs "${OAI2X2_MAX_UE_MCS}")
[[ -n "${OAI2X2_TX_BACKOFF_DB:-}" ]] && render_args+=(--tx-backoff-db "${OAI2X2_TX_BACKOFF_DB}")
/usr/bin/python3 "${renderer}" "${render_args[@]}" >"${log_dir}/render.log" 2>&1 || {
  cat "${log_dir}/render.log" >&2; usage_error "render failed"; }
"${native_root}/builds/ocudu-zmq-release/apps/gnb/gnb" -c "${config_dir}/gnb.yaml" --dryrun \
  >"${log_dir}/gnb-dryrun.log" 2>&1 || { tail -20 "${log_dir}/gnb-dryrun.log" >&2; usage_error "gNB dry run failed"; }

channel_build="${native_root}/builds/ocudu-gpu-channel-oai2x2-cuda-release"
cmake -S "${repo_root}" -B "${channel_build}" -DCMAKE_BUILD_TYPE=Release \
  -DOCUDU_GPU_CHANNEL_ENABLE_CUDA=ON -DCMAKE_CUDA_COMPILER="${cuda_compiler}" \
  -DOCUDU_GPU_CHANNEL_CUDA_ARCHITECTURES=120 >"${log_dir}/cmake-configure.log" 2>&1
cmake --build "${channel_build}" -j"$(nproc)" >"${log_dir}/cmake-build.log" 2>&1
export OAI2X2_BROKER_BIN="${channel_build}/ocudu-gpu-channel"

cp "${config_dir}"/* "${report_dir}/"
{
  printf 'timestamp=%s\npath=%s\nmax_rank=%s\ncsi_rs=%s\nmax_ue_mcs=%s\ntx_backoff_db=%s\n' \
    "${timestamp}" "${OAI2X2_PATH}" "${max_rank}" "${csi_rs}" "${OAI2X2_MAX_UE_MCS:-}" "${OAI2X2_TX_BACKOFF_DB:-}"
  printf 'topology=%s\nlabel=%s\nue_extra=%s\nbroker_extra=%s\nnrue_dir=%s\n' \
    "${topology}" "${OAI2X2_LABEL:-}" "${OAI2X2_UE_EXTRA:-}" "${OAI2X2_BROKER_EXTRA:-}" "${OAI2X2_NRUE_DIR:-}"
  printf 'oai_zmq_module=%s\noai_shlibpath=%s\noai_zmq_module_sha256=%s\n' \
    "${OAI_ZMQ_MODULE_VARIANT}" "${OCUDU_NATIVE_OAI_SHLIBPATH}" "${OAI_ZMQ_MODULE_SHA256}"
  printf 'channel_head=%s\nchannel_dirty=%s\n' "$(git -C "${repo_root}" rev-parse HEAD)" \
    "$(git -C "${repo_root}" status --porcelain | wc -l)"
} >"${report_dir}/run-params.txt"

parent_netns="$(readlink /proc/self/ns/net)"
parent_mntns="$(readlink /proc/self/ns/mnt)"
set +e
unshare --user --map-root-user --net --mount --fork --kill-child --propagation private \
  "${inner}" --mode run --parent-netns "${parent_netns}" --parent-mntns "${parent_mntns}" \
  --outer-uid "$(id -u)" --netns-dir "${netns_dir}" --physical-gpu "${physical_gpu}" \
  --native-root "${native_root}" --repo-root "${repo_root}" --config-dir "${config_dir}" \
  --log-dir "${log_dir}" --report-dir "${report_dir}" --timestamp "${timestamp}"
run_status="$?"
set -e
/usr/bin/python3 "${summarizer}" --log-dir "${log_dir}" --report-dir "${report_dir}" || true
printf 'event=native_oai_2x2_run status=%s timestamp=%s path=%s max_rank=%s report=%s\n' \
  "${run_status}" "${timestamp}" "${OAI2X2_PATH}" "${max_rank}" "${report_dir}"
exit "${run_status}"
