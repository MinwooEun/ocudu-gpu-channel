# Sequential single-cell scheduler comparison — 13 October 2026

This is the baseline with the UE receive sleep enabled. The [corrected pacing follow-up](../scheduler-broker-paced-20261013/README.md) supplies the current page 14 values.

RR and QoS ran separately on the RTX 5090, using the same cell, CPU allocation and offered traffic. Both completed 120 valid measurement seconds. **Neither reached real time.**

| Policy | Mean per-second bulk-DL p99 delay | Actual gNB IQ progress | Fraction of nominal IQ rate | Scheduler progress | Full-run broker input waits |
|---|---:|---:|---:|---:|---:|
| Round-robin | **10.761212 ms** | 21.350181 MS/s | 92.67% | 926.527 slots/s | 9 |
| QoS-aware | **13.546253 ms** | 21.126034 MS/s | 91.69% | 920.066 slots/s | 16 |

Nominal operation is 23.04 MS/s and 1000 slots/s. Delays round to **10.8 / 13.5 ms**. Each value averages 120 separate one-second p99 values for received bulk-download packets. It is not a pooled packet p99 or MAC computation time. One run per policy, one fixed seed and slightly different achieved rates do not establish a general scheduler ranking.

## Matched setup

- Intel Core Ultra 9 285K, 24 physical cores; RTX 5090, driver 580.173.02, CUDA 12.8.
- One OCUDU gNB, one CUDA channel broker, two single-port srsUEs, Open5GS. Both policies use cell A and PCI 1. No second-cell radio, UE or broker processes were started.
- gNB cores 0–7; both UEs 8–19; broker 20; auxiliary processes 22–23. Core 21 was not reassigned. These CPU sets match the earlier concurrent experiment's cell A allocation.
- 20 MHz, 15 kHz SCS, 23.04 MS/s. Same native binaries, −55 dB gNB RX gain, pacing and OS scheduling configuration. Two sequential 120-second measurements, six-second configured drain.
- Bulk UE: 5QI 9, 40 Mb/s DL, 2 Mb/s UL. Interactive UE: 5QI 7, 12 Mb/s on/off DL video (2/1 second mean on/off periods), plus 200-byte control packets every 10 ms in each direction.
- Seed-1 moving robot-ring Sionna scenario, 10 Hz channel updates and 40 dB configured AWGN SNR. All 1200 measurement grid points occurred in each run without skips.

[Channel and traffic checks](channel-and-traffic-check.json) confirm identical traffic configurations, positions, tap counts and tap delays. 1090/1200 profile hashes match exactly; remaining tap differences are at most 0.011130259 dB gain and 0.000366787 rad phase. The solved profiles are not claimed bit-identical.

## Timing and delivery

The [IQ audit](radio-speed-audit.json) uses differences in actual acquired complex-sample counters between monotonic heartbeat seconds 60 and 130. All six radio-port checks agree within their run. Integer heartbeat times imply a conservative 69–71 second interval; even its highest possible rate remains below nominal. The independent slot reconstruction divides unwrapped SFN/slot progress by wall time, not the count of log messages, and matches the original analyzer to within 0.01 slots/s. The IQ and scheduler checks use different window endpoints.

Both connectivity/data-integrity gates passed. Neither UE crashed, lost sync or released RRC; there were no queue overflows, sequence gaps or ZMQ errors. Every scheduled packet arrived after drain in both runs: bulk DL 500000, bulk UL 25000, video DL 103153, and DL/UL control 12000 each.

Strict zero-starvation real-time qualification failed. Full-run broker input-wait totals were 9 and 16; the interior IQ window contains 3 and 9 per-port wait events. These represent waits exceeding five batch durations (5 ms), not a direct count of MAC deadline misses. Requested gNB real-time priorities failed, and live snapshots show ordinary TS scheduling. No scheduling privileges or pacing parameters were changed.

The earlier concurrent cells ran around 90–91% of real time; isolated cells still fall short. Removing the second cell did not eliminate the slowdown. This test does not identify the remaining bottleneck or establish that GPU computation causes it.

## Runs and reproduction

- [RR run 20261013T101825Z](20261013T101825Z/benchmark-report.json), [gate](20261013T101825Z/gate-summary.json), [parameters](20261013T101825Z/run-parameters.json).
- [QoS run 20261013T102138Z](20261013T102138Z/benchmark-report.json), [gate](20261013T102138Z/gate-summary.json), [parameters](20261013T102138Z/run-parameters.json).
- [Plot values](plot-data.json), [audit script](audit.py), [source hashes](source-hashes.json), [artifact hashes](SHA256SUMS.json). Each run includes active configurations, policy verification, gNB console, channel digests and host-load samples.

Set `OCUDU_NATIVE_SB_SINGLE_CELL=1`, `OCUDU_NATIVE_SB_WEB_UI=0`, and the CPU sets above. Invoke the shipping scheduler launcher separately with `OCUDU_NATIVE_SB_SCHED_A=rr` and then `qos`, retaining seed 1, mixed traffic and 120-second duration. The second-cell scheduler setting is unused. The launcher filters traffic and analysis to cell A; the default remains two cells. RTX regression checks ran 28 tests with one skip and no failures, including known-delay single-cell logs with second-cell files absent. Both live runs exercised the shipping launcher.

Native pins and provisioning match the [earlier experiment](../scheduler-20261013/README.md): OCUDU `a1916edcdbcd70ba6e0af47ee87be061dad5a4e4`, srsRAN user fork `eea87b1d893ae58e0b08bc381730c502024ae71f`, Open5GS `d9d3abdd480be96fac3bc8a997e83446648763ca`. Scheduler algorithms and channel kernels were unchanged. Raw logs remain in the dedicated RTX validation workspace; no new system packages or unrelated services were changed.
