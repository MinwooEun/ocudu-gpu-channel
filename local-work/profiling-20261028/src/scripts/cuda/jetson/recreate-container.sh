#!/usr/bin/env bash
# Recreate minwoo's Jetson container with the capabilities the J track needs.
# Run on the Jetson HOST (not inside a container) by an account that can use docker.
#
#   OLD=<current container name> bash recreate-container.sh          # dry run: prints the plan
#   OLD=<current container name> APPLY=1 bash recreate-container.sh  # does it
#
# Keeps the old container's named volumes, published ports, hostname and nvidia
# runtime. Adds only: NET_ADMIN + SYS_ADMIN (ip netns add = unshare + bind mount),
# SYS_NICE + rtprio (gNB realtime threads), /dev/net/tun (Open5GS UPF),
# ip_forward. The network stays the default bridge, NOT --network host: host
# networking would let netns/iptables/routes touch the shared Jetson's own stack.
# The old container is stopped and renamed to <OLD>-pre-j0, never deleted here.
set -euo pipefail

OLD="${OLD:?set OLD to the current container name}"
NEW="${NEW:-$OLD}"
IMAGE="${IMAGE:-ocudu-jetson-minwoo:j0}"
HERE="$(cd "$(dirname "$0")" && pwd)"
DOCKER="${DOCKER:-docker}"

"$DOCKER" inspect "$OLD" >/dev/null
[[ "$("$DOCKER" inspect -f '{{.HostConfig.Runtime}}' "$OLD")" == nvidia ]] \
  || { echo "refusing: $OLD does not use the nvidia runtime" >&2; exit 1; }

hostname="$("$DOCKER" inspect -f '{{.Config.Hostname}}' "$OLD")"
restart="$("$DOCKER" inspect -f '{{.HostConfig.RestartPolicy.Name}}' "$OLD")"
shm="$("$DOCKER" inspect -f '{{.HostConfig.ShmSize}}' "$OLD")"
mapfile -t mounts < <("$DOCKER" inspect -f \
  '{{range .Mounts}}{{if eq .Type "volume"}}-v={{.Name}}:{{.Destination}}{{else}}-v={{.Source}}:{{.Destination}}{{end}}{{"\n"}}{{end}}' "$OLD" | sed '/^$/d')
mapfile -t ports < <("$DOCKER" inspect -f \
  '{{range $p, $b := .HostConfig.PortBindings}}{{range $b}}-p={{.HostPort}}:{{$p}}{{"\n"}}{{end}}{{end}}' "$OLD" \
  | sed -e 's#/tcp$##' -e '/^$/d')

run=( "$DOCKER" run -d --name "$NEW" --hostname "$hostname" --runtime nvidia
      ${restart:+--restart "$restart"} --shm-size "$shm"
      "${mounts[@]}" "${ports[@]}"
      --cap-add NET_ADMIN --cap-add SYS_ADMIN --cap-add SYS_NICE
      --device /dev/net/tun
      --ulimit rtprio=99 --ulimit memlock=-1
      --sysctl net.ipv4.ip_forward=1
      "$IMAGE" )

echo "old container : $OLD  (hostname $hostname, restart ${restart:-none}, shm $shm)"
printf 'mounts        : %s\n' "${mounts[@]}"
printf 'ports         : %s\n' "${ports[@]}"
echo "build         : $DOCKER build -t $IMAGE $HERE"
echo "rename        : $DOCKER stop $OLD && $DOCKER rename $OLD ${OLD}-pre-j0"
echo "run           : ${run[*]}"

[[ "${APPLY:-0}" == 1 ]] || { echo; echo "dry run only; APPLY=1 to execute"; exit 0; }

"$DOCKER" build -t "$IMAGE" "$HERE"
"$DOCKER" stop "$OLD"
"$DOCKER" rename "$OLD" "${OLD}-pre-j0"
"${run[@]}"
echo "created $NEW; old container kept as ${OLD}-pre-j0"
echo "the dev password lives in the old container's /etc/shadow, not a volume: set it again with"
echo "  $DOCKER exec -it $NEW passwd dev"
