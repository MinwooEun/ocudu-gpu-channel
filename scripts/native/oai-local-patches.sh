# shellcheck shell=bash
# The local OAI patches this repository carries on top of the pinned OAI, with
# their recorded sha256. Sourced by the build scripts, the gates and
# check-oai-local-patches.sh. Upstream reports come later; until then these
# patches are applied at build time and the pinned tree stays untouched.

OAI_LOCAL_PIN="2b69bde6aeafe892cda1531a0f0cbba2e37792cd"

# ZMQ radio module (liboai_zmqdevif.so, build-oai-zmq-module.sh).
OAI_LOCAL_ZMQ_PATCHES=(
  "oai-zmq-tx-reply-poll.patch:b2f1e51bfe38385fefcabbd7e9675278f45c5ab165af33429cb19772b5dbb9e3"
)

# nrUE PHY (nr-uesoftmodem, build-oai-ue-local.sh).
OAI_LOCAL_UE_PATCHES=(
  "oai-nr-dlsch-mmse-scale.patch:1856ac0f0aa11c13bfd5e718a656b616492b39dfdbc194bfc5ecedf44881d691"
)

# resolve_oai_ue_build <native_root> picks the nr-uesoftmodem build for the OAI
# 2x2 gate and exports OAI2X2_NRUE_DIR, OAI_UE_VARIANT and OAI_UE_SHA256.
#   OCUDU_NATIVE_OAI_UE=local (default: builds/oai-zmq-local, the UE PHY
#   patches above, checked against its BUILD-MANIFEST.txt) | stock
#   (builds/oai-zmq-release, the pinned build). An explicit OAI2X2_NRUE_DIR
#   wins over both.
resolve_oai_ue_build()
{
  local native_root="$1" dir variant
  if [[ -n "${OAI2X2_NRUE_DIR:-}" ]]; then
    dir="${OAI2X2_NRUE_DIR}"
    variant=custom
  else
    variant="${OCUDU_NATIVE_OAI_UE:-local}"
    case "${variant}" in
      local)
        dir="${native_root}/builds/oai-zmq-local"
        local manifest="${dir}/BUILD-MANIFEST.txt" entry
        if [[ ! -f "${manifest}" ]]; then
          printf 'error: %s is missing; run scripts/native/build-oai-ue-local.sh\n' "${manifest}" >&2
          return 1
        fi
        local ok=1
        grep -qx "oai_pin=${OAI_LOCAL_PIN}" "${manifest}" || ok=0
        for entry in "${OAI_LOCAL_UE_PATCHES[@]}"; do
          grep -qx "patch=${entry%%:*} sha256=${entry##*:}" "${manifest}" || ok=0
        done
        grep -qx "nr_uesoftmodem_sha256=$(sha256sum "${dir}/nr-uesoftmodem" | cut -d' ' -f1)" "${manifest}" || ok=0
        if [[ "${ok}" != 1 ]]; then
          printf 'error: %s does not match the recorded pin/patches/binary; rebuild it\n' "${dir}" >&2
          return 1
        fi
        ;;
      stock) dir="${native_root}/builds/oai-zmq-release" ;;
      *)
        printf 'error: OCUDU_NATIVE_OAI_UE must be local or stock, not %s\n' "${variant}" >&2
        return 1
        ;;
    esac
  fi
  if [[ ! -x "${dir}/nr-uesoftmodem" ]]; then
    printf 'error: no nr-uesoftmodem in %s\n' "${dir}" >&2
    return 1
  fi
  OAI_UE_VARIANT="${variant}"
  OAI_UE_SHA256="$(sha256sum "${dir}/nr-uesoftmodem" | cut -d' ' -f1)"
  export OAI_UE_VARIANT OAI_UE_SHA256
  export OAI2X2_NRUE_DIR="${dir}"
}
