# Scheduler comparison with heavier interactive traffic — 14 October 2026

The earlier 70 Mb/s download plus 12 Mb/s video experiment congested the download queue but delivered every interactive packet. This experiment raises only the video ON rate to 40 Mb/s, so both UEs compete for service. The four runs use RR, QoS, QoS, RR in sequence, with unchanged scheduler settings and equal resources. All four runs are retained.

## Results

| Metric | Round-robin | QoS-aware |
|---|---:|---:|
| Control delay, ms | 998.933 | 878.095 |
| Video delay, ms | 1029.858 | 909.587 |
| Download delay, ms | 1780.381 | 1774.988 |
| Control packet loss, % | 3.950 | 1.279 |
| Video packet loss, % | 8.305 | 4.624 |
| Download packet loss, % | 54.039 | 55.076 |

QoS lost 67.6% fewer control packets and 44.3% fewer video packets. Download delivery was 45.96% with RR and 44.92% with QoS, so the interactive improvement comes with a download-service tradeoff.

Delay is the mean of each valid second’s p99 delivered-packet one-way UDP delay, averaged equally over two runs. It excludes missing packets and empty video seconds. Packet loss is reported separately after a six-second drain. These metrics describe application traffic, not scheduler execution time.

| UTC run ID | Policy | Control ms | Video ms | Control missing | Video missing | IQ progress / nominal | Channel starvations |
|---|---|---:|---:|---:|---:|---:|---:|
| 20261013T163211Z | RR | 971.5 | 1005.1 | 446 | 25524 | 99.8913% | 13 |
| 20261013T163458Z | QOS | 878.3 | 909.3 | 167 | 15879 | 99.8810% | 8 |
| 20261013T163745Z | QOS | 877.9 | 909.9 | 140 | 15919 | 99.8988% | 2 |
| 20261013T164031Z | RR | 1026.4 | 1054.6 | 502 | 31585 | 99.8029% | 16 |

## Reproducible setup

- RTX 5090 and Core Ultra 9 285K. Each policy runs alone twice for 120 measurement seconds. Native gNB/UE revisions and binaries match the [earlier higher-load experiment](../scheduler-high-load-20261013/README.md).
- gNB cores 0–7, both UEs share 8–19, broker 20, auxiliary processes 22–23. Only one gNB, one broker and two UEs run at once. Other existing containers remain untouched.
- 20 MHz, 15 kHz SCS, 23.04 MS/s, CUDA, maximum 23040-sample batches. Seed-1 moving robot-ring Sionna scenario, 10 Hz updates, configured 40 dB AWGN SNR.
- Download UE: 5QI 9, 70 Mb/s DL, 2 Mb/s UL, 1200-byte packets. Interactive UE: 5QI 7, 40 Mb/s video during seeded on/off periods (mean ON/OFF 2/1 seconds), plus 200-byte control packets every 10 ms in both directions.
- Launcher overrides: `OCUDU_NATIVE_SB_SINGLE_CELL=1`, `OCUDU_NATIVE_SB_UE_RX_SLEEP=false`, `OCUDU_NATIVE_SB_TRAFFIC_OVERRIDES=ue0.dl_bulk.rate_mbps=70,ue1.dl_video.rate_mbps=40`. Existing broker pacing remains enabled.

## Checks and interpretation

Generated traffic and CPU settings match across all runs; gNB configuration differs only by scheduler policy. All 120 measurement seconds and all 1200 Sionna grid positions are checked for each run. Tap delays and counts agree; small ray-solver gain/phase differences are recorded rather than treated as bit-identical channels. Active process affinities and single-cell execution are checked in `resource-check.json`.

IQ progress uses cumulative acquired samples divided by monotonic elapsed time, measured over interior heartbeat observations. All runs have zero channel TX queue overflows, sample sequence gaps and ZMQ errors, but nonzero starvation events remain. This experiment does not establish strict zero-miss real-time operation. OCUDU logs show full RLC queues under the higher offered traffic. Two repeats at one channel/traffic seed do not establish statistical significance or a general scheduler ranking. Unrelated host background activity was not controlled.

## Evidence

[Summary](summary.json), [resource checks](resource-check.json), [sequence](sequence-status.log), [analysis](collect.py), [queue log examples](queue-log-examples.json), [source hashes](source-hashes.json), [raw hashes](raw-hashes.json). Each run directory contains benchmark results, settings, gate verdict, policy verification and configuration hashes. The previous 12 Mb/s result remains unchanged in its original report.
