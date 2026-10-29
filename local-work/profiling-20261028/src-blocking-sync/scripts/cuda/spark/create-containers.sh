#!/usr/bin/env bash
# Build the Spark images and create the three dev containers.
# Run on the DGX Spark HOST by an account that can use docker.
#
#   bash create-containers.sh            # dry run: prints what would happen
#   APPLY=1 bash create-containers.sh    # builds images, creates missing containers
#
# Existing containers are never touched: a name that already exists is skipped.
#
# | container       | image              | ssh  | broker ctrl/telemetry | extra capabilities                |
# |-----------------|--------------------|------|-----------------------|-----------------------------------|
# | ocudu-user-a   | ocudu-spark-base:1 | 2201 | 5559 / 5560           | none                              |
# | ocudu-minwoo    | ocudu-spark-ocudu:1| 2202 | 5561 / 5562           | netns, TUN, rtprio, no AppArmor   |
# | ocudu-user-b  | ocudu-spark-base:1 | 2203 | 5563 / 5564           | none                              |
#
# Port numbers follow the Jetson layout (user-a 2201/5559-5560, minwoo 2202/5561-5562).
# All three: GPU through the NVIDIA CDI spec, the host CUDA 13.0 toolkit mounted
# read-only, per-user named volumes for /home/dev and /workspace, bridge network.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
DOCKER="${DOCKER:-docker}"
CUDA_HOST="${CUDA_HOST:-/usr/local/cuda-13.0}"
BASE_IMAGE=ocudu-spark-base:1
OCUDU_IMAGE=ocudu-spark-ocudu:1

[[ -x "${CUDA_HOST}/bin/nvcc" ]] || { echo "no nvcc under ${CUDA_HOST}" >&2; exit 1; }
[[ -f /var/run/cdi/nvidia.yaml || -f /etc/cdi/nvidia.yaml ]] || { echo "no NVIDIA CDI spec; run: sudo nvidia-ctk cdi generate --output=/var/run/cdi/nvidia.yaml" >&2; exit 1; }

common=( --device nvidia.com/gpu=all
         -v "${CUDA_HOST}:${CUDA_HOST}:ro"
         --restart unless-stopped --shm-size 2g )
ocudu_caps=( --cap-add NET_ADMIN --cap-add SYS_ADMIN --cap-add SYS_NICE
             --device /dev/net/tun
             --ulimit rtprio=99 --ulimit memlock=-1
             --sysctl net.ipv4.ip_forward=1
             --security-opt apparmor=unconfined )
# apparmor=unconfined: Docker's default AppArmor profile on this Ubuntu 24.04 host
# denies `mount --make-shared /run/netns`, so `ip netns add` fails even with
# SYS_ADMIN (checked 2026-09-24 with a throwaway container: default -> denied,
# unconfined -> OK). Only minwoo's container gets it; the other two keep the profile.

# user ssh ctrl telemetry image [extra...]
plan() {
  local user=$1 ssh=$2 ctrl=$3 tele=$4 image=$5; shift 5
  local name="ocudu-${user}"
  local cmd=( "$DOCKER" run -d --name "$name" --hostname "$name"
              "${common[@]}"
              -v "${user}-home:/home/dev" -v "${user}-workspace:/workspace"
              -p "${ssh}:22" -p "${ctrl}:5559" -p "${tele}:5560"
              "$@" "$image" )
  if "$DOCKER" inspect "$name" >/dev/null 2>&1; then
    echo "skip   $name (already exists)"
    return
  fi
  echo "create $name: ${cmd[*]}"
  if [[ "${APPLY:-0}" == 1 ]]; then
    "${cmd[@]}"
  fi
}

echo "build  $BASE_IMAGE  from $HERE/base"
echo "build  $OCUDU_IMAGE from $HERE/ocudu"
if [[ "${APPLY:-0}" == 1 ]]; then
  "$DOCKER" build -t "$BASE_IMAGE" "$HERE/base"
  "$DOCKER" build --build-arg "BASE_IMAGE=$BASE_IMAGE" -t "$OCUDU_IMAGE" "$HERE/ocudu"
fi

plan user-a  2201 5559 5560 "$BASE_IMAGE"
plan minwoo   2202 5561 5562 "$OCUDU_IMAGE" "${ocudu_caps[@]}"
plan user-b 2203 5563 5564 "$BASE_IMAGE"

if [[ "${APPLY:-0}" != 1 ]]; then
  echo; echo "dry run only; APPLY=1 to execute"
  exit 0
fi
echo
echo "set each login password on the host:"
for u in user-a minwoo user-b; do echo "  $DOCKER exec -it ocudu-$u passwd dev"; done
