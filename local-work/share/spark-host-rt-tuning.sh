#!/bin/bash
# Spark (GB10) host-side real-time knobs for the OCUDU channel-emulator tests.
# Needs root ON THE HOST (not inside a container). Everything here is reversible and
# nothing is persisted across reboot.
#
#   sudo bash spark-host-rt-tuning.sh status     # show current state
#   sudo bash spark-host-rt-tuning.sh on         # apply for a test window
#   sudo bash spark-host-rt-tuning.sh off        # restore defaults
#
# What it changes and why:
#  1. kernel.sched_schedstats=1   per-thread run-queue wait accounting in /proc/<pid>/task/*/schedstat
#                                 (lets us see whether a gNB/UE thread waited for a CPU or slept). Harmless.
#  2. cpuidle: disable LPI-2 (231 us exit) and LPI-3 (433 us exit) on the big cores 5-9,15-19.
#                                 A core that idles between IQ blocks then wakes in ~40 us instead of ~400 us.
#                                 Cost: a few watts of idle power on those 10 cores while enabled.
#  3. kernel.perf_event_paranoid=-1  lets us run `perf sched record` from the container to attribute
#                                 the remaining tails to threads. Host-wide; revert after the window.
set -e
[[ $(id -u) -eq 0 ]] || { echo "run with sudo on the Spark host"; exit 1; }
BIG="5 6 7 8 9 15 16 17 18 19"
case "${1:-status}" in
  status)
    echo "sched_schedstats=$(cat /proc/sys/kernel/sched_schedstats) perf_event_paranoid=$(cat /proc/sys/kernel/perf_event_paranoid)"
    for c in 5 15 0; do echo -n "cpu$c idle:"; for s in /sys/devices/system/cpu/cpu$c/cpuidle/state*; do echo -n " $(cat $s/name)=$([ "$(cat $s/disable)" = 1 ] && echo off || echo on)"; done; echo; done ;;
  on)
    sysctl -q -w kernel.sched_schedstats=1
    sysctl -q -w kernel.perf_event_paranoid=-1
    for c in $BIG; do for s in 2 3; do echo 1 > /sys/devices/system/cpu/cpu$c/cpuidle/state$s/disable; done; done
    echo applied; "$0" status ;;
  off)
    sysctl -q -w kernel.sched_schedstats=0
    sysctl -q -w kernel.perf_event_paranoid=4
    for c in $BIG; do for s in 2 3; do echo 0 > /sys/devices/system/cpu/cpu$c/cpuidle/state$s/disable; done; done
    echo restored; "$0" status ;;
  *) echo "usage: $0 status|on|off"; exit 2 ;;
esac
