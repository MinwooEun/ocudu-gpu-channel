#!/usr/bin/env bash
set -eu
printf '%s\n' "$$" > "${OCG_UE_NSYS_OUTPUT}/ue.pid"
exec /workspace/gpuch/s4/build-s1/srsue/src/srsue "$@"
