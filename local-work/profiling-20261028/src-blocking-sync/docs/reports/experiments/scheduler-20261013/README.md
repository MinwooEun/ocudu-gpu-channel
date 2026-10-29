# Scheduler comparison on RTX 5090 — 13 October 2026

Two native OCUDU cells ran round-robin and QoS-aware proportional-fair scheduling with identical offered traffic and shared Sionna channel updates. The second run exchanged the policies between cells. Both runs completed 120 seconds with all four UEs connected to their intended cells and all 120 measurement intervals valid.

Page 14 now uses the [corrected sequential comparison](../scheduler-broker-paced-20261013/README.md). These concurrent-cell measurements remain as diagnostic evidence.

## Result from the concurrent-cell runs

| Scheduler | Run 1, ms | Run 2, ms | Mean over both runs, ms |
|---|---:|---:|---:|
| Round-robin | 23.676753 | 44.895089 | **34.285921** |
| QoS-aware | 36.318758 | 19.411829 | **27.865293** |

The metric is the arithmetic mean of the **per-second p99 one-way downlink UDP delay for the bulk-download UE**. Each scheduler contributes 240 valid seconds, equally divided between cell assignments. It is not the p99 of all packets pooled across the experiment. Delay includes the software radio stack and host scheduling, not just the MAC scheduler or GPU computation. Slide labels round these values to 34.3 and 27.9 ms.

Values were independently recomputed from `segments[*].cells[cell].ues[ue].flows.dl_bulk.delay_ms.p99` and matched `comparison.ue0_dl_delay_p99_ms.mean_x/mean_y`. The comparison field reports cell A as x and cell B as y; scheduler identities must be read from `lanes` before combining runs.

Run 1 placed RR in cell A and QoS in cell B; run 2 reversed them. RR had lower bulk delay in run 1, while QoS had lower bulk delay in run 2. Cell B had higher bulk delay in both runs. One seed and one swapped pair do not establish a general policy ranking or a statistically supported gain; no confidence interval is invented for the combined bars. The interactive-UE metric, retained in the reports, averages 10.730734 ms for RR and 10.013349 ms for QoS, using each second's largest p99 among that UE's DL flows.

## Setup

- Intel Core Ultra 9 285K, 24 physical cores; NVIDIA RTX 5090; driver 580.173.02; CUDA 12.8.
- Two native OCUDU gNBs, four single-port srsUEs, Open5GS and two CUDA channel brokers. Each gNB serves two UEs through its own broker; no RF edge connects the two cells.
- 20 MHz, 15 kHz subcarrier spacing, 23.04 MS/s. Each run measures 120 seconds, with a configured six-second drain.
- Both gNBs share cores 0–7; all four UEs share 8–19; brokers use 20 and 21; auxiliary processes use 22–23. These are process allocations across 24 cores, not 24 CPU channel workers.
- Per cell, the bulk UE uses 5QI 9 with 40 Mb/s downlink and 2 Mb/s uplink. The interactive UE uses 5QI 7 with 12 Mb/s on/off downlink video (mean on/off durations 2/1 seconds), plus 200-byte control packets every 10 ms in each direction. These are offered loads; sustained saturation is not assumed on this hardware.
- Seed 1 fixes the robot-ring route, solver seed and traffic schedules. One Sionna bridge supplies both cells at 10 Hz. AWGN SNR is configured at 40 dB. The gNB RX gain is −55 dB in both runs, following the launcher's documented correction for srsUE uplink clipping at the default gain.
- Schedulers are the pinned OCUDU time-domain RR and QoS-aware proportional-fair policies. QoS uses the benchmark's defaults: `gbr_prioritized`, fairness coefficient 2.0, priority/PDB/GBR terms enabled. No GBR service is established by these non-GBR flows.

## Connectivity and timing limits

| Run | Cell A slots/s | Cell B slots/s | Broker receive starvations A / B |
|---|---:|---:|---:|
| RR / QoS | 914.178 | 905.766 | 22 / 27 |
| QoS / RR | 911.786 | 900.505 | 29 / 17 |

Real time is 1000 slots/s. The measured range is 90.05–91.42% of real-time speed, so absolute delay includes this slowdown. Both connectivity/data-integrity gates passed, with no UE crashes, out-of-sync events, RRC releases, TX queue overflows, sequence gaps or ZMQ errors. **Strict zero-miss real-time qualification did not pass** because receive-starvation events occurred. The gate's `passed` status does not imply that stricter timing result.

Delay statistics describe received packets. In run 1, bulk DL delivery after drain was 499971/500000 for RR and 499972/500000 for QoS; each interactive UE received 103144/103153 video packets and 11999/12000 control packets. Run 2 received every scheduled DL packet. Both runs received all scheduled UL packets. Raw counts and sender/receiver checks remain in each report.

All 1200 measurement grid points were solved in each run with no skipped points, and both brokers acknowledged every fan-out update. Positions, tap counts and tap delays match across runs. 1081/1200 profile hashes match exactly; the other profiles differ by at most 0.011131 dB in tap gain and 0.000436 rad in phase. The two cells receive the same solved profiles within each run; the two runs are not claimed to be bit-identical.

## Sources and reproducibility

The [radio-speed and concurrency audit](radio-speed-audit.md) independently confirms the slowdown from actual IQ sample counters and explains the shared CPU allocation and failed real-time priority requests.

| Component | Revision |
|---|---|
| OCUDU | `a1916edcdbcd70ba6e0af47ee87be061dad5a4e4` |
| srsRAN user fork | `eea87b1d893ae58e0b08bc381730c502024ae71f` |
| Open5GS | `d9d3abdd480be96fac3bc8a997e83446648763ca` |

The UE uses the existing `integrations/srsran/patches/srsue-ra-contention.patch`, SHA-256 `0f4b9316af3f415b38b4459df1a1035a56f89442a73647895123f6a0869bbfd0`. Scheduler algorithms were unchanged. The benchmark renderer was repaired to supply explicit PRACH root 1 to the shared gNB renderer for each independent RF cell; it previously failed with `KeyError: prach_root` before starting radios.

Provisioning used an isolated `ocudu-gpu-channel:full-validation-netns` container. The private workspace lock matches the image's glibc package `2.39-0ubuntu8.4` rather than `2.39-0ubuntu8.8`, and fetches the same UE pin from the user fork. Host curl/git, LLVM 18, matching NVIDIA OptiX libraries, libpcap dependencies, click and ping were copied into the isolated workspace; provenance hashes remain with the remote run. The existing Sionna environment was mounted read-only. No system package installation or unrelated service change was required.

The 94 locked Debian archives, three source archives and eight Git pins passed workspace verification. RTX CPU/CUDA CTest passed 13/13; scheduler tests ran 27 cases with one skipped and no failures. Both gNB policies were independently checked from their configuration dumps, and each UE's serving PCI was verified. Initial provisioning/configuration failures were retained outside the measurement runs rather than folded into the result.

Evidence:

- [Run 1 report](20261013T094409Z/benchmark-report.json), [gate](20261013T094409Z/gate-summary.json), [parameters](20261013T094409Z/run-parameters.json).
- [Run 2 report](20261013T094837Z/benchmark-report.json), [gate](20261013T094837Z/gate-summary.json), [parameters](20261013T094837Z/run-parameters.json).
- [Plot data](plot-data.json), [channel reproduction check](channel-reproduction.json), [setup and source hashes](experiment-setup.json), [artifact hashes](SHA256SUMS.json).

Raw logs and complete runtime dependencies remain in the dedicated remote validation workspace `validation/scheduler-20261013`. The configs saved alongside each report specify the full scenario, policies and traffic. This is a fresh RTX measurement, not a reconstruction of the earlier GB10 same-policy difference.
