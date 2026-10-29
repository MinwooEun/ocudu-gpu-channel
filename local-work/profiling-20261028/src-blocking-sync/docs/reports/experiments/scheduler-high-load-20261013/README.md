# Higher-load sequential scheduler comparison — 13–14 October 2026 (SGT)

Four single-cell runs completed in the order RR, QoS, QoS, RR. Raising bulk downlink traffic from 40 to 70 Mb/s causes OCUDU packet-queue overflow in both policies. QoS has a modest interactive-delay advantage in these repeats; bulk delay and delivery remain similar. This is one traffic mix and channel seed, not a general scheduler ranking.

## Results

Each delay is the mean of each valid second’s p99 delivered-packet one-way UDP delay. Policy means average the two run means equally. Empty video seconds are excluded. These are neither pooled packet p99 values nor scheduler execution times.

| Metric | Round-robin | QoS-aware |
|---|---:|---:|
| Interactive control delay, ms | 8.883 | 8.042 |
| Interactive video delay, ms | 9.713 | 8.579 |
| Bulk download delay, ms | 995.244 | 986.915 |
| Bulk packets delivered | 71.12% | 71.55% |
| Mean downlink PRB utilization | 85.99% | 86.13% |

Measured QoS control delay is 9.46% lower than RR. The two RR run means are 8.339, 9.427 ms; the QoS means are 7.893, 8.192 ms.
Measured QoS video delay is 11.68% lower than RR. The two RR run means are 9.214, 10.213 ms; the QoS means are 8.317, 8.840 ms.

Every interactive control/video packet and every bulk uplink packet arrived after drain. Bulk downlink loss is shown explicitly: delay includes only delivered packets. OCUDU logs contain `Dropping SDU. Cause: RLC SDU queue is full` in both policies. This identifies a real packet-queue bottleneck under the higher offered load; channel IQ queue overflow and sequence-gap counters remain zero. [Log excerpts](queue-log-examples.json).

| Run (UTC ID) | Policy | Control, ms | Video, ms | Bulk, ms | Bulk missing / sent | Channel starvations |
|---|---|---:|---:|---:|---:|---:|
| 20261013T154902Z | RR | 8.339 | 9.214 | 995.104 | 252757 / 875000 | 12 |
| 20261013T155148Z | QOS | 7.893 | 8.317 | 986.446 | 248726 / 875000 | 6 |
| 20261013T155436Z | QOS | 8.192 | 8.840 | 987.383 | 249136 / 875000 | 9 |
| 20261013T155722Z | RR | 9.427 | 10.213 | 995.384 | 252582 / 875000 | 13 |

## Setup and controls

- RTX 5090, Core Ultra 9 285K, CUDA channel backend, one OCUDU gNB and two srsUEs. Each policy ran alone for two separate 120-second measurements, with six seconds of traffic drain after each. All 120 seconds were valid in all four runs.
- Fixed affinity: gNB cores 0–7, both UEs sharing 8–19, broker core 20, auxiliary processes 22–23. Core 21 was not reassigned. These are allocations, not CPU utilization measurements. Normal OS scheduling and broker pacing remained unchanged; the redundant srsUE receive sleep stayed disabled.
- 20 MHz, 15 kHz SCS, 23.04 MS/s, 23040-sample maximum channel batches. The seed-1 moving robot-ring Sionna scenario updates at 10 Hz with configured 40 dB AWGN SNR.
- Bulk UE: 5QI 9, 70 Mb/s DL and 2 Mb/s UL, 1200-byte packets. Interactive UE: 5QI 7, 12 Mb/s on/off DL video with 2/1-second mean on/off periods, plus 200-byte control packets every 10 ms in both directions. The only offered-traffic change from the earlier comparison is bulk DL 40→70 Mb/s.
- Run settings, actual gNB configuration dumps and sampled process affinities were checked. At most one gNB, one broker and two UEs were present at once. No diagnostic interposer was enabled; only the launcher’s existing line-buffering preload remained. [Resource checks](resource-check.json), [sequence](sequence-status.log).

Generated UE, channel and scenario configurations match after normalizing run-specific paths. The gNB configuration differs only in the scheduler policy. Live scenario positions, tap counts and delays match at all 1200 grid points. Ray-solver tap gain and phase have small numerical differences, recorded in `matched_checks` in [summary.json](summary.json); the realized channels are not claimed bit-identical. CPU/time scheduling and HARQ are also nondeterministic.

## Previous-result verification

The earlier page-14 values were not duplicated or taken from the same scheduler run. Recomputing the saved 120 one-second measurements reproduces the numbers below. The previous RR and QoS configurations have identical offered traffic and CPU sets; UE, channel and scenario files match, and only the gNB scheduler policy differs. Both previous runs delivered all scheduled packets.

| Earlier 40 Mb/s bulk traffic | Round-robin | QoS-aware |
|---|---:|---:|
| Bulk delay, ms | 8.937 | 8.734 |
| Interactive control delay, ms | 9.008 | 8.069 |
| Interactive video delay, ms | 9.801 | 8.576 |

The previous slide emphasized bulk traffic, where the difference was small. Higher bulk load alone still does not produce a large scheduler separation: interactive traffic receives service under both policies, while bulk queueing becomes severe. Page 14 now shows control and video delays separately, alongside bulk delivery. The earlier comparison remains archived in the [original report](../scheduler-broker-paced-20261013/README.md).

## Radio timing and limitations

| Run | gNB acquired-IQ progress / nominal | Logged scheduler slots/s |
|---|---:|---:|
| 20261013T154902Z | 99.8965% | 998.845 |
| 20261013T155148Z | 99.8951% | 998.960 |
| 20261013T155436Z | 99.8785% | 998.920 |
| 20261013T155722Z | 99.8584% | 998.740 |

IQ speed uses differences of cumulative acquired-sample counters divided by monotonic observation time, with interior heartbeat endpoints between 60 and 130 seconds. A read-only observer polls the line-buffered broker log every 2 ms on auxiliary cores. This carries observation/scheduling error and is corroborated by the separate scheduler-slot measurement. The saved summary includes all three radio ports and exact endpoints.

All runs have zero channel TX queue overflows, sample-sequence gaps and ZMQ errors. Input-starvation events remain, so strict zero-miss real-time qualification still fails. A successful launcher gate establishes the checks it implements; it does not require perfect packet delivery under overload or zero starvation.

Two repetitions at one seed and one higher load characterize these observed runs only. They do not establish statistical significance, a complete load curve, or a general scheduler advantage. The same twelve-core allocation is shared by the two UEs within each run. Unrelated workstation containers were preserved; their background activity was not controlled.

## Evidence and reproduction

- 20261013T154902Z: [benchmark](20261013T154902Z/benchmark-report.json), [settings](20261013T154902Z/run-parameters.json), [gate](20261013T154902Z/gate-summary.json), [policy verification](20261013T154902Z/policy-check.json), [configuration hashes](20261013T154902Z/config-hashes.json).
- 20261013T155148Z: [benchmark](20261013T155148Z/benchmark-report.json), [settings](20261013T155148Z/run-parameters.json), [gate](20261013T155148Z/gate-summary.json), [policy verification](20261013T155148Z/policy-check.json), [configuration hashes](20261013T155148Z/config-hashes.json).
- 20261013T155436Z: [benchmark](20261013T155436Z/benchmark-report.json), [settings](20261013T155436Z/run-parameters.json), [gate](20261013T155436Z/gate-summary.json), [policy verification](20261013T155436Z/policy-check.json), [configuration hashes](20261013T155436Z/config-hashes.json).
- 20261013T155722Z: [benchmark](20261013T155722Z/benchmark-report.json), [settings](20261013T155722Z/run-parameters.json), [gate](20261013T155722Z/gate-summary.json), [policy verification](20261013T155722Z/policy-check.json), [configuration hashes](20261013T155722Z/config-hashes.json).
- [Summary and per-second delay series](summary.json), [source hashes](source-hashes.json), [raw evidence hashes](raw-hashes.json), [analysis program](collect.py), [IQ observer](observe.py), [resource observer](resources.py).

Use the matched native launcher with `OCUDU_NATIVE_SB_SINGLE_CELL=1`, `OCUDU_NATIVE_SB_UE_RX_SLEEP=false`, `OCUDU_NATIVE_SB_TRAFFIC_OVERRIDES=ue0.dl_bulk.rate_mbps=70` and the recorded CPU sets. Run policies sequentially RR, QoS, QoS, RR. Keep 120 measurement seconds, seed 1 and the same channel/traffic settings. Native pins and dependencies are unchanged from the preceding corrected comparison.

Raw native logs and configuration files remain under RTX `validation/scheduler-20261013/ocudu-native-workspace/`; additional observations are in `validation/scheduler-20261013/high-load/`. No runtime source change was needed. The dedicated experiment container was stopped after collection, preserving all thirteen unrelated running containers.
