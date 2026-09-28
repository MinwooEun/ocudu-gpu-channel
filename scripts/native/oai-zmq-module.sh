# shellcheck shell=bash
# Which OAI nrUE ZMQ radio module a gate loads. Sourced by the OAI gates and by
# build-oai-zmq-module.sh.
#
# Default: the reply-poll patched module (S9). The stock module in the pinned
# OAI build sleeps up to 10 ms in zmq_poll while a reply is owed, which paces
# the whole lock-step chain at ~0.28x real time.
#
#   OCUDU_NATIVE_OAI_ZMQ_MODULE=patched|stock   (default patched)
#     patched -> builds/oai-zmq-s9, verified against its MODULE-MANIFEST.txt
#     stock   -> builds/oai-zmq-release (the module the pinned build produced)
#   OCUDU_NATIVE_OAI_SHLIBPATH=<dir>            explicit directory; wins over the above
#
# resolve_oai_zmq_module <native_root> sets and exports
#   OAI_ZMQ_MODULE_VARIANT  patched | stock | custom
#   OCUDU_NATIVE_OAI_SHLIBPATH  the directory to pass as shlibpath
#   OAI_ZMQ_MODULE_SHA256   sha256 of liboai_zmqdevif.so in that directory

OAI_ZMQ_PIN="2b69bde6aeafe892cda1531a0f0cbba2e37792cd"
OAI_ZMQ_PATCH="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/patches/oai-zmq-tx-reply-poll.patch"
OAI_ZMQ_PATCH_SHA256="b2f1e51bfe38385fefcabbd7e9675278f45c5ab165af33429cb19772b5dbb9e3"

resolve_oai_zmq_module()
{
  local native_root="$1"
  local dir variant
  if [[ -n "${OCUDU_NATIVE_OAI_SHLIBPATH:-}" ]]; then
    dir="${OCUDU_NATIVE_OAI_SHLIBPATH}"
    variant=custom
  else
    variant="${OCUDU_NATIVE_OAI_ZMQ_MODULE:-patched}"
    case "${variant}" in
      patched)
        dir="${native_root}/builds/oai-zmq-s9"
        local manifest="${dir}/MODULE-MANIFEST.txt"
        if [[ ! -f "${manifest}" ]]; then
          printf 'error: %s is missing; run scripts/native/build-oai-zmq-module.sh patched\n' "${manifest}" >&2
          return 1
        fi
        if ! grep -qx "patch_sha256=${OAI_ZMQ_PATCH_SHA256}" "${manifest}" || \
           ! grep -qx "oai_pin=${OAI_ZMQ_PIN}" "${manifest}" || \
           ! grep -qx "module_sha256=$(sha256sum "${dir}/liboai_zmqdevif.so" | cut -d' ' -f1)" "${manifest}"; then
          printf 'error: %s does not match the recorded patch/pin/module; rebuild it\n' "${dir}" >&2
          return 1
        fi
        ;;
      stock) dir="${native_root}/builds/oai-zmq-release" ;;
      *)
        printf 'error: OCUDU_NATIVE_OAI_ZMQ_MODULE must be patched or stock, not %s\n' "${variant}" >&2
        return 1
        ;;
    esac
  fi
  if [[ ! -f "${dir}/liboai_zmqdevif.so" ]]; then
    printf 'error: no liboai_zmqdevif.so in %s\n' "${dir}" >&2
    return 1
  fi
  OAI_ZMQ_MODULE_VARIANT="${variant}"
  OAI_ZMQ_MODULE_SHA256="$(sha256sum "${dir}/liboai_zmqdevif.so" | cut -d' ' -f1)"
  export OAI_ZMQ_MODULE_VARIANT OAI_ZMQ_MODULE_SHA256
  export OCUDU_NATIVE_OAI_SHLIBPATH="${dir}"
}
