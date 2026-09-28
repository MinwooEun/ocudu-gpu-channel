#!/usr/bin/env bash
set -euo pipefail

# Builds the OAI nrUE ZMQ radio module (liboai_zmqdevif.so) on its own, next to
# the pinned OAI build, so the gates can load it with
# --loader.oai_zmqdevif.shlibpath. The pinned source tree and the pinned build
# are never modified: the one source file is copied out, patched there, and
# compiled and linked with the exact flags.make / link.txt CMake generated for
# builds/oai-zmq-release.
#
#   build-oai-zmq-module.sh patched   -> builds/oai-zmq-s9        (reply-poll patch, S9)
#   build-oai-zmq-module.sh stock     -> builds/oai-zmq-s9-stock  (same procedure, no patch;
#                                        the A/B control for the procedure itself)
#
# Each output directory gets MODULE-MANIFEST.txt (OAI pin, patch sha256,
# source and module sha256). oai-zmq-module.sh checks it before a gate uses the
# module.

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# The same toolchain environment build-oai-ue.sh uses (sysroot CPATH: simde,
# libconfig, ...).
# shellcheck source=env.sh
source "${script_dir}/env.sh"
# shellcheck source=oai-zmq-module.sh
source "${script_dir}/oai-zmq-module.sh"

die() { printf 'error: %s\n' "$1" >&2; exit 1; }

variant="${1:-}"
[[ "${variant}" == patched || "${variant}" == stock ]] || die "usage: $0 patched|stock"
native_root="${OCUDU_NATIVE_ROOT:?set OCUDU_NATIVE_ROOT}"
src="${native_root}/src/oai"
release="${native_root}/builds/oai-zmq-release"
target_dir="${release}/radio/zmq/CMakeFiles/oai_zmqdevif.dir"
out="${native_root}/builds/$([[ "${variant}" == patched ]] && echo oai-zmq-s9 || echo oai-zmq-s9-stock)"

[[ "$(git -C "${src}" rev-parse HEAD)" == "${OAI_ZMQ_PIN}" ]] || die "OAI checkout is not the pin ${OAI_ZMQ_PIN}"
git -C "${src}" diff --quiet -- radio/zmq/zmq_radio.cpp || die "pinned zmq_radio.cpp has local changes"
for file in "${target_dir}/flags.make" "${target_dir}/link.txt"; do
  [[ -f "${file}" ]] || die "missing ${file} (build OAI first: build-oai-ue.sh)"
done

rm -rf "${out}"
mkdir -p "${out}/src"
cp "${src}/radio/zmq/zmq_radio.cpp" "${out}/src/zmq_radio.cpp"
patch_sha=none
if [[ "${variant}" == patched ]]; then
  patch_sha="$(sha256sum "${OAI_ZMQ_PATCH}" | cut -d' ' -f1)"
  [[ "${patch_sha}" == "${OAI_ZMQ_PATCH_SHA256}" ]] || die "patch sha256 ${patch_sha} is not the recorded ${OAI_ZMQ_PATCH_SHA256}"
  # The patch is written against radio/zmq/zmq_radio.cpp; apply it to the copy.
  patch --no-backup-if-mismatch -s "${out}/src/zmq_radio.cpp" <"${OAI_ZMQ_PATCH}"
fi

# Compile: the same CXX_DEFINES / CXX_INCLUDES / CXX_FLAGS CMake uses.
cat >"${out}/Makefile" <<EOF
include ${target_dir}/flags.make
all:
	/usr/bin/c++ \$(CXX_DEFINES) \$(CXX_INCLUDES) \$(CXX_FLAGS) -c src/zmq_radio.cpp -o src/zmq_radio.cpp.o
EOF
make -s -C "${out}" all

# Link: CMake's own link line, run where it expects to run, with only the
# object and the output path swapped.
link_line="$(cat "${target_dir}/link.txt")"
[[ "${link_line}" == *"-o ../../liboai_zmqdevif.so CMakeFiles/oai_zmqdevif.dir/zmq_radio.cpp.o"* ]] || \
  die "unexpected link.txt layout"
link_line="${link_line/-o ..\/..\/liboai_zmqdevif.so CMakeFiles\/oai_zmqdevif.dir\/zmq_radio.cpp.o/-o ${out}/liboai_zmqdevif.so ${out}/src/zmq_radio.cpp.o}"
(cd "${release}/radio/zmq" && eval "${link_line}")

{
  printf 'variant=%s\noai_pin=%s\npatch=%s\npatch_sha256=%s\n' \
    "${variant}" "${OAI_ZMQ_PIN}" "$([[ "${variant}" == patched ]] && basename "${OAI_ZMQ_PATCH}" || echo none)" "${patch_sha}"
  printf 'source_sha256=%s\nmodule_sha256=%s\n' \
    "$(sha256sum "${out}/src/zmq_radio.cpp" | cut -d' ' -f1)" \
    "$(sha256sum "${out}/liboai_zmqdevif.so" | cut -d' ' -f1)"
} >"${out}/MODULE-MANIFEST.txt"
cat "${out}/MODULE-MANIFEST.txt"
