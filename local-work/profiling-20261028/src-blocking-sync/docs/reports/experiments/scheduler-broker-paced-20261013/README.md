# Scheduler comparison with corrected UE pacing — 13 October 2026

The main slowdown came from srsUE's full-block relative receive sleep. Disabling that additional sleep while retaining broker pacing raises radio progress from roughly 92% to **99.9% of nominal** on the same CPU allocation and traffic. The corrected single-cell runs provide the values used on page 14.

| Policy | Mean per-second bulk-DL p99 delay | Observed gNB IQ progress | Nominal-rate fraction | Scheduler progress | Full-run broker input waits |
|---|---:|---:|---:|---:|---:|
| Round-robin | **8.936967 ms** | 23.010425 MS/s | 99.872% | 998.778 slots/s | 4 |
| QoS-aware | **8.733633 ms** | 23.021316 MS/s | 99.919% | 999.059 slots/s | 6 |

Nominal operation is 23.04 MS/s and 1000 slots/s. Slide values are **8.9 ms RR** and **8.7 ms QoS**. Both runs completed 120/120 valid measurement seconds. Delays are similar in this setup; one run per policy does not establish a general scheduler ranking or a significant gain.

## Pacing defect and controlled change

The pinned srsUE ZMQ receive function calls `usleep(sample_count / sample_rate)` on every receive. It sleeps for the whole block duration and then performs the remaining receive/processing work. Sleep overshoot and other work accumulate beyond the nominal block duration. The broker already uses bounded absolute-deadline pacing and cannot force a slow peer to advance faster.

In the [single-cell baseline](../scheduler-single-cell-20261013/README.md), RR reached 926.527 slots/s and QoS 920.066, despite no second cell. [Heartbeat stage snapshots](baseline-stage-snapshots.json) showed median channel calls around 73–88 microseconds, input waits around 0.7–0.8 ms and generally negligible broker throttle time. These are sampled last-call timings, not full-call distributions.

The [minimal UE patch](srsue-zmq-rx-sleep.patch) extracts only the existing CMX integration's `rx_sleep` switch. The default remains true. The corrected runs set `OCUDU_NATIVE_SB_UE_RX_SLEEP=false`, which adds `rx_sleep=false` to both UE ZMQ configurations; broker pacing remains enabled. No CPU sets, traffic, channel-kernel algorithms or real-time privileges were changed. This controlled change removes most of the observed deficit. It does not explain every remaining sub-millisecond scheduling delay.

## Matched setup and metric

- Intel Core Ultra 9 285K, 24 physical cores; RTX 5090, driver 580.173.02, CUDA 12.8. One OCUDU gNB, one CUDA broker, two single-port srsUEs and Open5GS. Only cell A / PCI 1 runs.
- Same allocations for both policies and the baseline: gNB cores 0–7, both UEs 8–19, broker 20, auxiliary processes 22–23. Core 21 is not reassigned. OS real-time priority requests still fail; the correction does not depend on granting those privileges.
- 20 MHz, 15 kHz SCS, 23.04 MS/s, −55 dB gNB RX gain. Each policy runs separately for 120 measurement seconds, with six-second configured drain.
- Bulk UE: 5QI 9, DL 40 Mb/s and UL 2 Mb/s. Interactive UE: 5QI 7, DL video 12 Mb/s on/off with 2/1-second mean periods, plus 200-byte control packets every 10 ms each direction.
- Seed-1 moving robot-ring Sionna scenario, 10 Hz updates, configured AWGN SNR 40 dB. All 1200 grid points occurred without skips. Positions, tap counts and delays match; 1086/1200 hashes match. Remaining differences are at most 0.000937477 dB gain and 0.000135425 rad phase. Profiles are not claimed bit-identical.

The plotted metric averages each valid second's p99 one-way bulk-download UDP packet delay, giving 120 values per scheduler. It is not a pooled packet p99 or pure MAC computation time. Host scheduling, radio processing, queues and retransmissions contribute to the delay. [Traffic and channel checks](channel-and-traffic-check.json) verify the matched inputs; offered load does not imply continuous saturation.

## Real-time check and limits

The [IQ audit](radio-speed-audit.json) uses actual broker acquired-sample counters from all three radio ports. A read-only observer timestamps heartbeat lines with a monotonic nanosecond clock, polling every 2 ms on the auxiliary CPU set. The table uses sample differences divided by observed elapsed time inside heartbeat seconds 60–130. Observation times include polling and scheduling delay; they are not hardware timestamps. The original integer-second heartbeat calculation is retained as a separate cross-check.

Independent gNB SFN/slot reconstruction over each full 120-second measurement also gives approximately 999 slots/s and agrees with the original analyzer within 0.01 slots/s. The IQ and scheduler checks use different endpoints. The measured remaining deficit is small but real: **near-nominal average progress is not a strict zero-miss real-time pass**.

Both connectivity/data-integrity gates passed, with no crashes, out-of-sync events, RRC releases, queue overflows, sequence gaps or ZMQ errors. Both runs received every scheduled packet after drain: 500000 bulk DL, 25000 bulk UL, 103153 video DL, and 12000 control packets in each direction.

Full-run broker input-wait totals were 4 RR / 6 QoS; the interior audit window contains 2 / 0 per-port wait events. These are waits beyond five batch durations (5 ms), not a direct count of MAC deadline misses. Strict zero-starvation qualification remains failed. The hardware was not shown incapable of nominal radio throughput by the earlier incorrectly paced experiment.


The [per-call timing follow-up](../scheduler-pacing-trace-20261013/README.md) locates most remaining lag in IQ input/output waits and records occasional processing tails. It also corrects the broker log’s invalid 5.005 ms maximum; the scheduler delay values above are unchanged.

## Evidence and reproduction

- [RR 20261013T103050Z](20261013T103050Z/benchmark-report.json), [gate](20261013T103050Z/gate-summary.json), [parameters](20261013T103050Z/run-parameters.json).
- [QoS 20261013T103414Z](20261013T103414Z/benchmark-report.json), [gate](20261013T103414Z/gate-summary.json), [parameters](20261013T103414Z/run-parameters.json).
- [Plot values](plot-data.json), [UE build manifest](UE-BUILD-MANIFEST.txt), [patch lock](srsue-local-patches.lock.json), [source hashes](source-hashes.json), [artifact hashes](SHA256SUMS.json), [test log](validation.log).

Build the locked UE with `scripts/native/build-srsue-local.sh` in the provisioned native environment. Set `OCUDU_NATIVE_SB_SINGLE_CELL=1`, `OCUDU_NATIVE_SB_UE_RX_SLEEP=false`, `OCUDU_NATIVE_SB_WEB_UI=0`, the CPU sets above, seed 1, mixed traffic, 120-second duration and −55 dB gNB RX gain. Invoke the shipping scheduler launcher separately with `OCUDU_NATIVE_SB_SCHED_A=rr`, then `qos`.

RTX checks passed: 28 scheduler tests with one skip, two integration-asset tests and both corrected live runs. The upstream source trees remain pinned and unmodified. OCUDU pin `a1916edcdbcd70ba6e0af47ee87be061dad5a4e4`, srsRAN fork `eea87b1d893ae58e0b08bc381730c502024ae71f`, Open5GS `d9d3abdd480be96fac3bc8a997e83446648763ca`; UE patches and binary SHA-256 are in the manifest. Raw logs stay in the dedicated RTX validation workspace.
