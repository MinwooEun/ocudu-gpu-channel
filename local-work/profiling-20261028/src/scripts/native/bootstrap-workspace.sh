#!/usr/bin/env bash
# Provision or validate the locked rootless native workspace.
#
# Reproducibility boundary: this lock describes the audited Ubuntu 24.04 host
# contract plus a user-space Debian overlay.  It is not a hermetic or arbitrary
# clean-host build: 48 Debian dependency clauses and the base compiler/runtime
# are supplied by the host.  Archive hashes authenticate bytes against this
# repository's lock; only MongoDB also has a cached upstream checksum sidecar.

set -euo pipefail
export LC_ALL=C

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"
lock_file="${script_dir}/native-workspace.lock.json"
verifier="${script_dir}/verify-workspace-lock.py"
checker="${script_dir}/check-workspace.sh"

native_root="/home/ubuntu/ocudu-native-workspace"
verify_only=false
offline=false
default_jobs="$(getconf _NPROCESSORS_ONLN 2>/dev/null || printf '1')"
jobs="${default_jobs}"

usage()
{
  cat <<'EOF'
Usage: scripts/native/bootstrap-workspace.sh [OPTIONS]

Options:
  --verify-only       Verify the locked, already-provisioned workspace only.
  --offline           Forbid network provisioning (accepted fail-closed).
  --root PATH         Dedicated workspace root (default:
                      /home/ubuntu/ocudu-native-workspace).
  --jobs N            Positive build parallelism (default: online CPU count).
  -h, --help          Show this help.

This script never invokes sudo or Docker and never resets, deletes, or cleans
an existing source tree. Without --verify-only it downloads the exact locked
inputs, creates the user-space dependency overlay, and builds the native stack.
EOF
}

die()
{
  printf 'bootstrap-workspace: %s\n' "$*" >&2
  exit 1
}

usage_error()
{
  printf 'bootstrap-workspace: %s\n' "$*" >&2
  usage >&2
  exit 2
}

while (($#)); do
  case "$1" in
    --verify-only)
      verify_only=true
      shift
      ;;
    --offline)
      offline=true
      shift
      ;;
    --root)
      (($# >= 2)) || usage_error "--root requires a path"
      native_root="$2"
      shift 2
      ;;
    --jobs)
      (($# >= 2)) || usage_error "--jobs requires a positive integer"
      jobs="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      (($# == 0)) || usage_error "unexpected positional arguments: $*"
      ;;
    *)
      usage_error "unknown argument: $1"
      ;;
  esac
done

[[ "${jobs}" =~ ^[1-9][0-9]*$ ]] || usage_error "--jobs must be a positive integer"
[[ "${native_root}" == /* ]] || usage_error "--root must be an absolute path"
[[ ! -L "${native_root}" ]] || die "workspace root must not be a symlink: ${native_root}"

command -v readlink >/dev/null 2>&1 || die "required host tool is missing: readlink"
native_root="$(readlink -m -- "${native_root}")"

case "${native_root}" in
  /|/home|/home/ubuntu|/tmp|/var|/var/tmp)
    die "refusing broad or shared workspace root: ${native_root}"
    ;;
esac

root_base="$(basename -- "${native_root}")"
[[ "${root_base}" =~ ^ocudu-native-workspace([._-].+)?$ ]] || \
  die "workspace root basename must be ocudu-native-workspace or a suffixed variant"

case "${native_root}/" in
  "${repo_root}/"*) die "workspace root must not be inside the audit repository" ;;
esac
case "${repo_root}/" in
  "${native_root}/"*) die "workspace root must not contain the audit repository" ;;
esac

for required_file in "${lock_file}" "${verifier}" "${checker}"; do
  [[ -f "${required_file}" ]] || die "required repository file is missing: ${required_file}"
done
[[ -x /usr/bin/python3 ]] || die "required host tool is missing: /usr/bin/python3"

json_value()
{
  /usr/bin/python3 - "${lock_file}" "$1" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    value = json.load(stream)
for component in sys.argv[2].split("."):
    value = value[component]
if not isinstance(value, (str, int)):
    raise SystemExit(f"lock value is not scalar: {sys.argv[2]}")
print(value)
PY
}

require_executable()
{
  local path="$1"
  [[ -x "${path}" ]] || die "locked host executable is missing: ${path}"
}

require_version()
{
  local name="$1"
  local actual="$2"
  local expected="$3"
  [[ "${actual}" == "${expected}" ]] || \
    die "${name} version mismatch: ${actual} != ${expected}"
  printf 'host_%s=%s\n' "${name}" "${actual}"
}

check_host_contract()
{
  local path expected actual output architecture

  path="$(json_value host_contract.python.path)"
  expected="$(json_value host_contract.python.version)"
  require_executable "${path}"
  actual="$(${path} --version 2>&1)"
  require_version python "${actual#Python }" "${expected}"

  path="$(json_value host_contract.gcc.path)"
  expected="$(json_value host_contract.gcc.version)"
  require_executable "${path}"
  require_version gcc "$(${path} -dumpfullversion -dumpversion)" "${expected}"

  path="$(json_value host_contract.gxx.path)"
  expected="$(json_value host_contract.gxx.version)"
  require_executable "${path}"
  require_version gxx "$(${path} -dumpfullversion -dumpversion)" "${expected}"

  path="$(json_value host_contract.cmake.path)"
  expected="$(json_value host_contract.cmake.version)"
  require_executable "${path}"
  output="$(${path} --version)"
  actual="${output%%$'\n'*}"
  require_version cmake "${actual##* }" "${expected}"

  path="$(json_value host_contract.binutils.linker)"
  expected="$(json_value host_contract.binutils.version)"
  require_executable "${path}"
  output="$(${path} --version)"
  actual="${output%%$'\n'*}"
  require_version binutils "${actual##* }" "${expected}"

  path="$(json_value host_contract.make.path)"
  expected="$(json_value host_contract.make.version)"
  require_executable "${path}"
  output="$(${path} --version)"
  actual="${output%%$'\n'*}"
  require_version make "${actual##* }" "${expected}"

  path="$(json_value host_contract.pkg_config.path)"
  expected="$(json_value host_contract.pkg_config.version)"
  require_executable "${path}"
  require_version pkg_config "$(${path} --version)" "${expected}"

  command -v dpkg >/dev/null 2>&1 || die "required host tool is missing: dpkg"
  command -v dpkg-query >/dev/null 2>&1 || die "required host tool is missing: dpkg-query"
  architecture="$(dpkg --print-architecture)"
  expected="$(json_value host_contract.glibc_package_version)"
  actual="$(dpkg-query -W -f='${Version}' "libc6:${architecture}")"
  require_version glibc_package "${actual}" "${expected}"

  # CUDA is part of the lock but is only needed by the channel CUDA build.
  # If present, reject drift; absence does not invalidate this stack-only check.
  path="$(json_value host_contract.cuda.nvcc)"
  expected="$(json_value host_contract.cuda.version)"
  if [[ -x "${path}" ]]; then
    output="$(${path} --version)"
    actual="$(sed -n 's/.*V\([0-9][0-9.]*\).*/\1/p' <<<"${output}")"
    require_version cuda_nvcc "${actual}" "${expected}"
  else
    printf 'host_cuda_nvcc=absent_optional_for_stack_only\n'
  fi
}

verify_file()
{
  local path="$1"
  local expected_bytes="$2"
  local expected_sha256="$3"
  [[ -f "${path}" && ! -L "${path}" ]] || return 1
  [[ "$(stat -c '%s' "${path}")" == "${expected_bytes}" ]] || return 1
  [[ "$(sha256sum "${path}" | awk '{print $1}')" == "${expected_sha256}" ]]
}

download_file()
{
  local url="$1"
  local output="$2"
  local expected_bytes="$3"
  local expected_sha256="$4"
  local fallback_url="${5:-}"
  local temporary
  if verify_file "${output}" "${expected_bytes}" "${expected_sha256}"; then
    printf 'cached=%s\n' "${output}"
    return 0
  fi
  [[ ! -e "${output}" && ! -L "${output}" ]] || \
    die "cached input exists but does not match its lock: ${output}"
  [[ "${offline}" != true ]] || die "offline mode is missing cached input: ${output}"
  mkdir -p "$(dirname "${output}")"
  temporary="${output}.part.$$"
  [[ ! -e "${temporary}" && ! -L "${temporary}" ]] || \
    die "temporary download path already exists: ${temporary}"
  if ! curl --fail --location --connect-timeout 20 \
    --output "${temporary}" "${url}"; then
    if [[ -z "${fallback_url}" ]] || ! curl --fail --location --retry 4 \
      --retry-all-errors --connect-timeout 20 --output "${temporary}" "${fallback_url}"; then
      rm -f "${temporary}"
      die "download failed: ${url}${fallback_url:+ (fallback: ${fallback_url})}"
    fi
  fi
  if ! verify_file "${temporary}" "${expected_bytes}" "${expected_sha256}"; then
    rm -f "${temporary}"
    die "download does not match the committed lock: ${url}"
  fi
  mv "${temporary}" "${output}"
  printf 'downloaded=%s\n' "${output}"
}

download_locked_inputs()
{
  local package version architecture bytes digest repository_path cache_path
  local kind name url relative sidecar_bytes sidecar_digest
  while IFS=$'\t' read -r package version architecture bytes digest repository_path cache_path; do
    [[ "${package}" != \#* ]] || continue
    [[ -n "${package}" ]] || continue
    download_file "https://launchpad.net/ubuntu/+archive/primary/+files/${repository_path##*/}" \
      "${native_root}/${cache_path}" "${bytes}" "${digest}" \
      "https://archive.ubuntu.com/ubuntu/${repository_path}"
  done <"${repo_root}/$(json_value debian_overlay.manifest)"

  while IFS=$'\t' read -r kind name url relative bytes digest; do
    download_file "${url}" "${native_root}/${relative}" "${bytes}" "${digest}"
  done < <(/usr/bin/python3 - "${lock_file}" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    lock = json.load(stream)
for archive in lock["archives"]:
    print("archive", archive["name"], archive["url"], archive["cache_path"],
          archive["bytes"], archive["sha256"], sep="\t")
    sidecar = archive.get("sha256_sidecar")
    if sidecar:
        print("sidecar", archive["name"], archive["url"] + ".sha256",
              sidecar["cache_path"], sidecar["bytes"], sidecar["sha256"], sep="\t")
PY
)
}

extract_debian_overlay()
{
  local manifest_sha256 stamp package version architecture bytes digest repository_path cache_path
  manifest_sha256="$(json_value debian_overlay.sha256)"
  stamp="${native_root}/.bootstrap/debian-overlay.sha256"
  if [[ -f "${stamp}" && "$(<"${stamp}")" == "${manifest_sha256}" ]]; then
    echo "debian_overlay=already_extracted"
    return 0
  fi
  mkdir -p "${native_root}/install/sysroot" "${native_root}/.bootstrap"
  while IFS=$'\t' read -r package version architecture bytes digest repository_path cache_path; do
    [[ "${package}" != \#* ]] || continue
    [[ -n "${package}" ]] || continue
    dpkg-deb --extract "${native_root}/${cache_path}" "${native_root}/install/sysroot"
  done <"${repo_root}/$(json_value debian_overlay.manifest)"
  printf '%s\n' "${manifest_sha256}" >"${stamp}"
  echo "debian_overlay=extracted"
}

relocate_autotools_overlay()
{
  local sysroot="${native_root}/install/sysroot"
  local aclocal_script="${sysroot}/usr/bin/aclocal-1.16"
  local autom4te_config="${sysroot}/usr/share/autoconf/autom4te.cfg"
  local libtoolize_script="${sysroot}/usr/bin/libtoolize"

  for path in "${aclocal_script}" "${autom4te_config}" "${libtoolize_script}"; do
    [[ -f "${path}" && ! -L "${path}" ]] || \
      die "autotools relocation input is missing or unsafe: ${path}"
  done

  # Debian's scripts embed /usr/share paths which do not follow PATH or the
  # environment overrides in env.sh. Rewrite only those known installation
  # variables, leaving interpreter paths such as /usr/bin/perl untouched.
  if ! grep -Fq "${sysroot}/usr/share/automake-1.16" "${aclocal_script}"; then
    sed -i \
      -e "s|/usr/share/automake-1.16|${sysroot}/usr/share/automake-1.16|g" \
      -e "s|/usr/share/aclocal|${sysroot}/usr/share/aclocal|g" \
      "${aclocal_script}"
  fi
  if ! grep -Fq "${sysroot}/usr/share/autoconf" "${autom4te_config}"; then
    sed -i \
      -e "s|/usr/share/autoconf|${sysroot}/usr/share/autoconf|g" \
      "${autom4te_config}"
  fi
  sed -i -E \
    -e "s|^prefix=.*$|prefix='${sysroot}/usr'|" \
    -e "s|^datadir=.*$|datadir='${sysroot}/usr/share'|" \
    -e "s|^pkgauxdir=.*$|pkgauxdir='${sysroot}/usr/share/libtool/build-aux'|" \
    -e "s|^pkgltdldir=.*$|pkgltdldir='${sysroot}/usr/share/libtool'|" \
    -e "s|^aclocaldir=.*$|aclocaldir='${sysroot}/usr/share/aclocal'|" \
    "${libtoolize_script}"

  for link_name in automake aclocal; do
    local target="${link_name}-1.16"
    local link_path="${sysroot}/usr/bin/${link_name}"
    [[ ! -e "${link_path}" || -L "${link_path}" ]] || \
      die "refusing to replace non-symlink autotools entry: ${link_path}"
    ln -sfn "${target}" "${link_path}"
  done
  echo "autotools_overlay=relocated"
}

ensure_git_checkout()
{
  local name="$1"
  local url relative commit destination actual
  IFS=$'\t' read -r url relative commit < <(/usr/bin/python3 - "${lock_file}" "${name}" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    lock = json.load(stream)
for source in lock["git_sources"]:
    if source["name"] == sys.argv[2]:
        print(source["url"], source["path"], source["commit"], sep="\t")
        raise SystemExit(0)
raise SystemExit(f"unknown locked Git source: {sys.argv[2]}")
PY
)
  destination="${native_root}/${relative}"
  if [[ ! -e "${destination}" && ! -L "${destination}" ]]; then
    [[ "${offline}" != true ]] || die "offline mode is missing Git source: ${name}"
    mkdir -p "$(dirname "${destination}")"
    git init "${destination}"
    git -C "${destination}" remote add origin "${url}"
  fi
  [[ -d "${destination}/.git" && ! -L "${destination}" ]] || \
    die "Git source path is not a safe checkout: ${destination}"
  if ! git -C "${destination}" rev-parse --verify HEAD >/dev/null 2>&1; then
    [[ "${offline}" != true ]] || die "offline checkout lacks commit: ${name}"
    git -C "${destination}" fetch --depth 1 origin "${commit}"
    git -C "${destination}" checkout --detach FETCH_HEAD
  fi
  actual="$(git -C "${destination}" rev-parse HEAD)"
  [[ "${actual}" == "${commit}" ]] || \
    die "existing ${name} checkout has unexpected revision: ${actual}"
  [[ -z "$(git -C "${destination}" status --porcelain)" ]] || \
    die "existing ${name} checkout is dirty: ${destination}"
  printf '%s_revision=%s\n' "${name}" "${actual}"
}

prepare_git_sources()
{
  ensure_git_checkout ocudu
  ensure_git_checkout srsRAN_4G
  ensure_git_checkout open5gs
  ensure_git_checkout prometheus-client-c
  ensure_git_checkout freeDiameter
  ensure_git_checkout libtins
  ensure_git_checkout usrsctp
  ensure_git_checkout oai
}

export_overlay_environment()
{
  local sysroot="${native_root}/install/sysroot"
  local gnutls="${native_root}/install/gnutls-3.7.3"
  local bison="${native_root}/install/bison-3.8.2"
  export PATH="${bison}/bin:${sysroot}/usr/bin:${PATH}"
  export PYTHONPATH="${sysroot}/usr/lib/python3/dist-packages${PYTHONPATH:+:${PYTHONPATH}}"
  export CPATH="${gnutls}/include:${sysroot}/usr/include/libmongoc-1.0:${sysroot}/usr/include/libbson-1.0:${sysroot}/usr/include:${sysroot}/usr/include/x86_64-linux-gnu${CPATH:+:${CPATH}}"
  export LIBRARY_PATH="${gnutls}/lib:${sysroot}/usr/lib/x86_64-linux-gnu${LIBRARY_PATH:+:${LIBRARY_PATH}}"
  export LD_LIBRARY_PATH="${gnutls}/lib:${sysroot}/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
  export PKG_CONFIG_PATH="${gnutls}/lib/pkgconfig:${sysroot}/usr/lib/x86_64-linux-gnu/pkgconfig:${sysroot}/usr/share/pkgconfig${PKG_CONFIG_PATH:+:${PKG_CONFIG_PATH}}"
  unset PKG_CONFIG_SYSROOT_DIR
}

extract_source_archive()
{
  local archive="$1"
  local destination="$2"
  [[ -d "${destination}" && ! -L "${destination}" ]] && return 0
  [[ ! -e "${destination}" && ! -L "${destination}" ]] || \
    die "source extraction path is unsafe: ${destination}"
  mkdir -p "$(dirname "${destination}")"
  tar --extract --file "${archive}" --directory "$(dirname "${destination}")"
  [[ -d "${destination}" && ! -L "${destination}" ]] || \
    die "archive did not create expected source directory: ${destination}"
}

build_user_dependencies()
{
  local bison_source="${native_root}/src/build-deps/bison-3.8.2"
  local bison_build="${native_root}/builds/bison-3.8.2"
  local bison_prefix="${native_root}/install/bison-3.8.2"
  local gnutls_source="${native_root}/src/build-deps/gnutls-3.7.3"
  local gnutls_build="${native_root}/builds/gnutls-3.7.3"
  local gnutls_prefix="${native_root}/install/gnutls-3.7.3"
  local sysroot="${native_root}/install/sysroot"

  extract_source_archive "${native_root}/tools/bison-3.8.2.tar.xz" "${bison_source}"
  mkdir -p "${bison_build}"
  if [[ ! -f "${bison_build}/Makefile" ]]; then
    (cd "${bison_build}" && M4="${sysroot}/usr/bin/m4" \
      "${bison_source}/configure" --prefix="${bison_prefix}")
  fi
  make -C "${bison_build}" -j"${jobs}"
  make -C "${bison_build}" install
  [[ -x "${bison_prefix}/bin/bison" ]] || die "Bison installation failed"

  export_overlay_environment
  extract_source_archive "${native_root}/tools/gnutls-3.7.3.tar.xz" "${gnutls_source}"
  mkdir -p "${gnutls_build}"
  if [[ ! -f "${gnutls_build}/Makefile" ]]; then
    (cd "${gnutls_build}" && "${gnutls_source}/configure" \
      --prefix="${gnutls_prefix}" --disable-doc --disable-guile --disable-tests \
      --without-p11-kit --without-tpm --without-idn --without-libintl-prefix \
      --disable-tools --with-included-unistring)
  fi
  make -C "${gnutls_build}" -j"${jobs}"
  make -C "${gnutls_build}" install
  [[ -f "${gnutls_prefix}/lib/libgnutls.so" || -f "${gnutls_prefix}/lib/libgnutls.a" ]] || \
    die "GnuTLS installation failed"
}

install_mongodb()
{
  local destination="${native_root}/install/mongodb-6.0.29"
  if [[ -x "${destination}/bin/mongod" ]]; then
    echo "mongodb=already_installed"
    return 0
  fi
  [[ ! -e "${destination}" && ! -L "${destination}" ]] || \
    die "incomplete MongoDB destination already exists: ${destination}"
  mkdir -p "${destination}"
  tar --extract --gzip \
    --file "${native_root}/tools/mongodb-linux-x86_64-ubuntu2204-6.0.29.tgz" \
    --directory "${destination}" --strip-components 1
  [[ -x "${destination}/bin/mongod" ]] || die "MongoDB extraction failed"
  echo "mongodb=installed"
}

build_native_stack()
{
  local sysroot="${native_root}/install/sysroot"
  local gnutls="${native_root}/install/gnutls-3.7.3"
  local cmake_common=(
    "-DCMAKE_PREFIX_PATH=${gnutls};${sysroot}/usr"
    "-DCMAKE_INCLUDE_PATH=${gnutls}/include;${sysroot}/usr/include;${sysroot}/usr/include/x86_64-linux-gnu"
    "-DCMAKE_LIBRARY_PATH=${gnutls}/lib;${sysroot}/usr/lib/x86_64-linux-gnu"
  )
  local ocudu_build="${native_root}/builds/ocudu-zmq-release"
  local srsran_build="${native_root}/builds/srsran4g-zmq-release"
  local open5gs_build="${native_root}/builds/open5gs-v2.7.6"
  export_overlay_environment

  cmake -S "${native_root}/src/ocudu" -B "${ocudu_build}" \
    "${cmake_common[@]}" -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF \
    -DCMAKE_INSTALL_PREFIX="${native_root}/install/ocudu" \
    -DENABLE_UHD=OFF -DENABLE_SIDEKIQ=OFF -DENABLE_MKL=OFF -DENABLE_FFTZ=OFF \
    -DENABLE_ARMPL=OFF -DENABLE_DPDK=OFF -DENABLE_LIBNUMA=OFF \
    -DENABLE_PLUGINS=OFF -DENABLE_BACKWARD=OFF -DENABLE_ZEROMQ=ON \
    -DENABLE_FFTW=ON -DENABLE_EXPORT=ON
  cmake --build "${ocudu_build}" --target gnb -j"${jobs}"

  cmake -S "${native_root}/src/srsRAN_4G" -B "${srsran_build}" \
    "${cmake_common[@]}" -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX="${native_root}/install/srsran4g" \
    -DENABLE_SRSUE=ON -DENABLE_SRSENB=OFF -DENABLE_SRSEPC=OFF \
    -DENABLE_UHD=OFF -DENABLE_ZEROMQ=ON -DENABLE_WERROR=OFF -DENABLE_EXPORT=ON
  cmake --build "${srsran_build}" --target srsue -j"${jobs}"

  if [[ ! -f "${open5gs_build}/build.ninja" ]]; then
    "${sysroot}/usr/bin/meson" setup "${open5gs_build}" "${native_root}/src/open5gs" \
      --prefix="${native_root}/install/open5gs-v2.7.6" \
      --buildtype=release --wrap-mode=nodownload
  fi
  "${sysroot}/usr/bin/ninja" -C "${open5gs_build}" \
    tests/app/5gc \
    src/nrf/open5gs-nrfd \
    src/scp/open5gs-scpd \
    src/upf/open5gs-upfd \
    src/smf/open5gs-smfd \
    src/amf/open5gs-amfd \
    src/ausf/open5gs-ausfd \
    src/udm/open5gs-udmd \
    src/pcf/open5gs-pcfd \
    src/nssf/open5gs-nssfd \
    src/bsf/open5gs-bsfd \
    src/udr/open5gs-udrd \
    subprojects/freeDiameter/extensions/dbg_msg_dumps.fdx \
    subprojects/freeDiameter/extensions/dict_rfc5777.fdx \
    subprojects/freeDiameter/extensions/dict_mip6i.fdx \
    subprojects/freeDiameter/extensions/dict_nasreq.fdx \
    subprojects/freeDiameter/extensions/dict_nas_mipv6.fdx \
    subprojects/freeDiameter/extensions/dict_dcca.fdx \
    subprojects/freeDiameter/extensions/dict_dcca_3gpp/dict_dcca_3gpp.fdx

  [[ -x "${ocudu_build}/apps/gnb/gnb" ]] || die "OCUDU gNB build failed"
  [[ -x "${srsran_build}/srsue/src/srsue" ]] || die "srsUE build failed"
  [[ -x "${open5gs_build}/tests/app/5gc" ]] || die "Open5GS 5GC build failed"
  [[ -f "${open5gs_build}/subprojects/freeDiameter/extensions/dbg_msg_dumps.fdx" ]] || \
    die "Open5GS freeDiameter extension build failed"
}

printf '%s\n' \
  'claim_boundary=locked Ubuntu-24.04 host contract plus user-space overlay; not hermetic' \
  "workspace_root=${native_root}" \
  "offline=${offline}" \
  "jobs=${jobs}"

check_host_contract

if [[ "${verify_only}" != true ]]; then
  command -v curl >/dev/null 2>&1 || die "required host tool is missing: curl"
  command -v git >/dev/null 2>&1 || die "required host tool is missing: git"
  command -v dpkg-deb >/dev/null 2>&1 || die "required host tool is missing: dpkg-deb"
  command -v tar >/dev/null 2>&1 || die "required host tool is missing: tar"
  [[ ! -e "${native_root}" && ! -L "${native_root}" ]] && mkdir -p "${native_root}"
  [[ -d "${native_root}" && ! -L "${native_root}" ]] || \
    die "workspace root is missing or unsafe: ${native_root}"
  mkdir -p "${native_root}/builds" "${native_root}/install" \
    "${native_root}/src" "${native_root}/tools"
  download_locked_inputs
  extract_debian_overlay
  relocate_autotools_overlay
  build_user_dependencies
  install_mongodb
  prepare_git_sources
  /usr/bin/python3 "${verifier}" \
    --root "${native_root}" --repo-root "${repo_root}" --lock "${lock_file}"
  build_native_stack
  echo "bootstrap_provision=ok"
fi

[[ -d "${native_root}" ]] || die "workspace root is missing: ${native_root}"

/usr/bin/python3 "${verifier}" \
  --root "${native_root}" \
  --repo-root "${repo_root}" \
  --lock "${lock_file}"

OCUDU_NATIVE_ROOT="${native_root}" "${checker}"
printf 'bootstrap_verify_only=ok\n'
