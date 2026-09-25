#!/usr/bin/env bash
# S3 prerequisite -- the non-CUDA half of the live stack on the DGX Spark:
# CPU OCUDU gNB (baseline), srsRAN_4G srsUE, Open5GS 5GC, MongoDB.
#
# Same commits and build options as the workstation's native workspace
# (scripts/native/native-workspace.lock.json: git_sources + build_profiles).
# Differences, each forced by the platform:
#   - CPU OCUDU gets -DMCPU=neoverse-v2 (GCC 13.3 does not know Cortex-X925/A725;
#     see SPARK_MILESTONES.md S1) and -DMARCH=armv9-a: this older tree's crypto
#     probe retries with -march=${MARCH}+crypto, and the default MARCH=native gives
#     the invalid -march=native+crypto (the vendor branch later switched the retry
#     to -mcpu, 66ee7ce702). armv9-a matches neoverse-v2 and compiles warning-free.
#   - MongoDB is the aarch64 build of the same version (6.0.29, ubuntu2204 --
#     MongoDB 6.0 publishes no ubuntu2404 build; the workstation uses the
#     ubuntu2204 x86_64 build on noble the same way).
#   - Dependencies come from the container image (system apt), not a user-space sysroot.
#
# Run inside ocudu-minwoo on the Spark:  bash s3-build-stack.sh
# On the Jetson (J3):  PLATFORM_ROOT=/workspace/ocudu-jetson STACK_MCPU=cortex-a78ae \
#                      STACK_MARCH=armv8.2-a S3_BUILD_JOBS=6 bash s3-build-stack.sh
set -euo pipefail

root="${PLATFORM_ROOT:-/workspace/ocudu-spark}"
jobs="${S3_BUILD_JOBS:-16}"
mcpu="${STACK_MCPU:-neoverse-v2}"; march="${STACK_MARCH:-armv9-a}"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
out="${root}/results/s3-stack-${stamp}"
mkdir -p "$out" "$root"/{src,builds,install,tools}
exec > >(tee -a "$out/s3-stack.log") 2>&1

fetch() { # dir url commit
  if [[ ! -d "$1/.git" ]]; then git clone -q "$2" "$1"; fi
  git -C "$1" fetch -q origin "$3" 2>/dev/null || true
  git -C "$1" checkout -q "$3"
  echo "src $(basename "$1") $(git -C "$1" rev-parse HEAD)"
}

echo "=== sources $(date -u +%T) ==="
fetch "$root/src/ocudu"     https://gitlab.com/ocudu/ocudu.git          a1916edcdbcd70ba6e0af47ee87be061dad5a4e4
fetch "$root/src/srsRAN_4G" https://github.com/srsran/srsRAN_4G.git     eea87b1d893ae58e0b08bc381730c502024ae71f
fetch "$root/src/open5gs"   https://github.com/open5gs/open5gs.git      d9d3abdd480be96fac3bc8a997e83446648763ca
# Open5GS is built with --wrap-mode=nodownload, so its meson subprojects are
# checked out at the locked commits instead of fetched by meson.
sp="$root/src/open5gs/subprojects"
fetch "$sp/prometheus-client-c" https://github.com/open5gs/prometheus-client-c.git a58ba25bf87a9b1b7c6be4e6f4c62047d620f402
fetch "$sp/freeDiameter"        https://github.com/open5gs/freeDiameter.git        14725af3ba0edbf9ff61c4e3239ed42464423b2e
fetch "$sp/libtins"             https://github.com/open5gs/libtins.git             bf22438172d269e6db70e27246dffd8e1f0b96e3
fetch "$sp/usrsctp"             https://github.com/sctplab/usrsctp.git             07f871bda23943c43c9e74cc54f25130459de830

echo "=== mongodb $(date -u +%T) ==="
m=mongodb-linux-aarch64-ubuntu2204-6.0.29.tgz
cd "$root/tools"
[[ -f $m ]] || curl -fsSLO "https://fastdl.mongodb.org/linux/$m"
curl -fsSLO "https://fastdl.mongodb.org/linux/$m.sha256"
sha256sum -c "$m.sha256"
tar xzf "$m" -C "$root/install"
ln -sfn "${m%.tgz}" "$root/install/mongodb"
# The runner looks for install/mongodb-<version>; scripts/native/env.sh checks
# that the workstation's x86 sysroot/gnutls/bison folders exist. Dependencies
# here come from system apt, so those are empty placeholders.
ln -sfn "${m%.tgz}" "$root/install/mongodb-6.0.29"
for d in sysroot gnutls-3.7.3 bison-3.8.2; do
  mkdir -p "$root/install/$d"
  echo "Placeholder: scripts/native/env.sh checks this path; dependencies come from system apt." > "$root/install/$d/README"
done
"$root/install/mongodb/bin/mongod" --version | head -1

echo "=== ocudu (CPU) $(date -u +%T) ==="
cmake -S "$root/src/ocudu" -B "$root/builds/ocudu-zmq-release" -G Ninja \
  -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF -DENABLE_UHD=OFF -DENABLE_SIDEKIQ=OFF \
  -DENABLE_MKL=OFF -DENABLE_FFTZ=OFF -DENABLE_ARMPL=OFF -DENABLE_DPDK=OFF -DENABLE_LIBNUMA=OFF \
  -DENABLE_PLUGINS=OFF -DENABLE_BACKWARD=OFF -DENABLE_ZEROMQ=ON -DENABLE_FFTW=ON -DENABLE_EXPORT=ON \
  "-DMCPU=${mcpu}" "-DMARCH=${march}" "-DCMAKE_INSTALL_PREFIX=$root/install/ocudu" > "$out/ocudu-configure.log" 2>&1
cmake --build "$root/builds/ocudu-zmq-release" --target gnb -j"$jobs" > "$out/ocudu-build.log" 2>&1
"$root/builds/ocudu-zmq-release/apps/gnb/gnb" --version | head -2

echo "=== srsRAN_4G srsUE $(date -u +%T) ==="
cmake -S "$root/src/srsRAN_4G" -B "$root/builds/srsran4g-zmq-release" -G Ninja \
  -DCMAKE_BUILD_TYPE=Release -DENABLE_SRSUE=ON -DENABLE_SRSENB=OFF -DENABLE_SRSEPC=OFF \
  -DENABLE_UHD=OFF -DENABLE_ZEROMQ=ON -DENABLE_WERROR=OFF -DENABLE_EXPORT=ON \
  "-DCMAKE_INSTALL_PREFIX=$root/install/srsran4g" > "$out/srsran4g-configure.log" 2>&1
# Build everything, not just the srsue target: the ZMQ radio is a separate
# plugin (libsrsran_rf_zmq.so) that srsue loads at run time.
cmake --build "$root/builds/srsran4g-zmq-release" -j"$jobs" > "$out/srsran4g-build.log" 2>&1
ls -l "$root/builds/srsran4g-zmq-release/srsue/src/srsue"
find "$root/builds/srsran4g-zmq-release" -name "libsrsran_rf_zmq.so*" | head -1

echo "=== open5gs $(date -u +%T) ==="
# Open5GS pulls prometheus-client-c in through meson's CMake module. With CMake
# 4.x first on PATH (the Jetson container has 4.4.3 in /usr/local/bin) the
# translated subproject carries link_args ['-shared'] into every metrics user:
# AMF/SMF/UPF/PCF link as entry-0 shared objects and die with SIGILL before
# main. Pin the CMake meson uses to a 3.x (STACK_MESON_CMAKE, default the
# system /usr/bin/cmake) through a native file.
meson="${MESON:-meson}"
meson_cmake="${STACK_MESON_CMAKE:-/usr/bin/cmake}"
[[ "$("$meson_cmake" --version | head -1)" =~ version\ 3\. ]] || { echo "FATAL: meson's CMake must be 3.x: $meson_cmake"; exit 1; }
printf "[binaries]\ncmake = '%s'\n" "$meson_cmake" > "$out/meson-native.ini"
[[ -d "$root/builds/open5gs-v2.7.6" ]] || \
  "$meson" setup "$root/builds/open5gs-v2.7.6" "$root/src/open5gs" --native-file "$out/meson-native.ini" --buildtype=release --wrap-mode=nodownload \
    "--prefix=$root/install/open5gs-v2.7.6" > "$out/open5gs-setup.log" 2>&1
ninja -C "$root/builds/open5gs-v2.7.6" -j"$jobs" > "$out/open5gs-build.log" 2>&1
ninja -C "$root/builds/open5gs-v2.7.6" install >> "$out/open5gs-build.log" 2>&1
ls "$root/install/open5gs-v2.7.6/bin" | tr '\n' ' '; echo

df -h /workspace | tail -1
echo "s3_stack_evidence=${out}"
echo S3_STACK_DONE
