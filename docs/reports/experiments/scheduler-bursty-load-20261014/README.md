# Scheduler comparison with brief video bursts — 14 October 2026

The previous test saturated both UE queues and produced roughly one-second interactive delays. This experiment instead creates brief congestion that can clear between bursts. The design was saved before execution: 30 Mb/s download, 40 Mb/s video while ON, mean ON/OFF durations 0.2/0.8 seconds. Expected average DL demand including control is 38.16 Mb/s, below the approximately 57 Mb/s cell capacity measured in the previous stress test. Peak demand is 70.16 Mb/s.

No scheduler settings, queue limits or drop policies change. All four RR/QoS/QoS/RR runs are retained.

## Results

| Metric | Round-robin | QoS-aware |
|---|---:|---:|
| Control delay, ms | 63.048 | 48.121 |
| Video delay, ms | 84.776 | 64.384 |
| Download delay, ms | 30.502 | 45.138 |
| Control packets received/sent | 24000/24000 | 24000/24000 |
| Video packets received/sent | 180294/180294 | 180294/180294 |
| Download packets received/sent | 750000/750000 | 750000/750000 |

Control delay changed by 23.68% and video delay by 24.05% in favor of QoS. All packets, including both uplink streams, arrived after the six-second drain. No full-RLC-queue events appear in any run.

Delay is the mean of per-second p99 delivered-packet one-way UDP delay, equally averaged over two runs. Empty video seconds are excluded. This is not pooled packet p99 or maximum latency.

| UTC run | Policy | Control ms | Video ms | IQ progress / nominal | Channel starvations |
|---|---|---:|---:|---:|---:|
| 20261013T165805Z | RR | 62.594 | 84.441 | 99.8969% | 4 |
| 20261013T170050Z | QOS | 48.185 | 64.398 | 99.9082% | 4 |
| 20261013T170335Z | QOS | 48.056 | 64.370 | 99.8776% | 7 |
| 20261013T170622Z | RR | 63.501 | 85.111 | 99.8104% | 4 |

| Largest per-second p99 | Round-robin | QoS-aware |
|---|---:|---:|
| Control, ms | 288.306 | 295.871 |
| Video, ms | 288.451 | 297.602 |
| Download, ms | 146.615 | 135.445 |

The worst per-second p99 was not improved by QoS; the reported 24% benefit applies to the mean of the per-second values. Download delay is included to expose the service tradeoff. The scheduler can reduce waiting for the interactive UE by making the download UE wait longer, even when all packets arrive.

## Setup and checks

- RTX 5090 and Core Ultra 9 285K. One gNB and two UEs at a time, two separate 120-second measurements per policy, six seconds drain. Unchanged binaries and scheduler defaults from the [previous experiment](../scheduler-priority-load-20261014/README.md).
- gNB cores 0–7, UEs share 8–19, broker 20, auxiliary processes 22–23. Existing unrelated containers were preserved.
- 20 MHz, 15 kHz SCS, 23.04 MS/s, CUDA channel, maximum 23040-sample batches. Seed-1 moving robot-ring Sionna scenario at 10 Hz, configured 40 dB AWGN SNR. Broker pacing stays enabled, redundant UE receive sleep disabled.
- Download UE 5QI 9: 30 Mb/s DL and 2 Mb/s UL, 1200-byte packets. Interactive UE 5QI 7: 40 Mb/s video, exponentially distributed mean ON/OFF periods 0.2/0.8 seconds, plus 200-byte control packets every 10 ms in both directions.
- Launcher overrides: `OCUDU_NATIVE_SB_SINGLE_CELL=1`, `OCUDU_NATIVE_SB_UE_RX_SLEEP=false`, `OCUDU_NATIVE_SB_TRAFFIC_OVERRIDES=ue0.dl_bulk.rate_mbps=30,ue1.dl_video.rate_mbps=40,ue1.dl_video.on_mean_s=0.2,ue1.dl_video.off_mean_s=0.8`.

The configuration comparison verifies identical traffic and CPU allocations across policies, with only scheduler policy differing in gNB configuration. All 120 measurement seconds and 1200 channel grid positions are validated per run. Channel positions, tap counts and delays match; small ray-solver gain/phase differences are retained in `matched_checks`. Observed active processes and CPU affinities confirm sequential single-cell execution.

IQ progress is cumulative acquired samples over monotonic elapsed time, using interior heartbeats. All channel queue-overflow, sample-gap and ZMQ-error counters are zero. Input-starvation events remain; this does not establish strict zero-miss real-time qualification. Two repeats at one seed do not establish statistical significance or a general scheduler ranking.

## Evidence

[Predeclared design](design.json), [summary](summary.json), [resource checks](resource-check.json), [queue checks](queue-log-examples.json), [sequence](sequence-status.log), [analysis](collect.py), [source hashes](source-hashes.json), [raw hashes](raw-hashes.json). Each run folder contains the benchmark report, run settings, gate verdict, policy check and configuration hashes. Earlier overload measurements remain unchanged in their original report.
