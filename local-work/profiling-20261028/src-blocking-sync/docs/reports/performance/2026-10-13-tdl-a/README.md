# TDL-A CPU and CUDA benchmark, 13 October 2026

Current-code comparison for presentation page 10. Source revision: `f95dabd0d13db3b24e9a4b04c919ad3620468f11`. The plotted statistic is the median of three run-level p99 processing-call times.

| Backend | Run | Calls | p99 (ms) | Maximum (ms) |
|---|---:|---:|---:|---:|
| cpu | 1 | 2,331 | 57.924784 | 59.881898 |
| cpu | 2 | 2,340 | 57.853351 | 59.420087 |
| cpu | 3 | 2,340 | 57.783040 | 58.364488 |
| cuda | 1 | 186,588 | 0.229360 | 3.526937 |
| cuda | 2 | 186,381 | 0.230352 | 0.420592 |
| cuda | 3 | 185,733 | 0.231591 | 1.244905 |

Plotted CPU p99: **57.853351 ms**. Plotted CUDA p99: **0.230352 ms**. Their ratio is **251.152×**. These are call-latency percentiles, not an end-to-end throughput ratio.

## Setup

- Intel Core Ultra 9 285K and NVIDIA GeForce RTX 5090. CUDA 12.8.1, driver 580.173.02, GCC 13.3.0, Release build targeting sm_120. The GPU used PCIe Gen 5 ×8 during work (the May reference used ×4). See `environment.txt` and GPU monitor CSVs.
- Synthetic topology: one gNB and eight UEs, one port per node, eight downlink and eight uplink edges. No radio programs or ZMQ sockets are involved in this benchmark.
- 23.04 million complex IQ samples/s. Every receiving-node call processes 23,040 samples per output port, representing 1 ms of signal.
- Every edge uses TDL-A with 23 taps, 100 ns delay spread and Jakes fading with 100 Hz maximum Doppler. CPU and CUDA YAML files differ only in backend.
- Three 30-second runs per backend in alternating order, with a separate 5-second warmup run per backend. Individual measured runs retain all timed calls, including their initial calls.
- One CPU calling thread processes the nine receiving nodes in sequence. No pacing, input refresh or concurrent per-node CPU workers. The input IQ buffers are reused. CUDA uses its standard copy path on this discrete GPU.

## Meaning of the numbers

- `model_mix_latency` measures host-clock time around input-span/output-span preparation and the synchronous `process_superposition()` call. On CUDA it includes CPU preparation, transfers, GPU processing, synchronization and output handling. It excludes initialization, socket transport, radio software and subsequent output-power accounting.
- Each run combines calls from all nine receiving nodes: the gNB has eight incoming edges, while each UE has one. The result is a percentile across that mixed call workload, not the time to process all 16 edges in one call.
- p99 is the nearest-rank 99th percentile: at least 99% of measured calls in that run completed within that time. The chart then takes the median p99 across the three runs.
- Maximum latency is recorded separately. GPU calls exceeded 1 ms in the observations, so a p99 below 1 ms does not establish an every-call timing guarantee or live-radio qualification.
- The benchmark CSV `slot_us=500` field comes from its default 30 kHz numerology. It is separate from this configured 1 ms IQ batch duration. The slide does not interpret either as a passed real-time gate.

## Provenance and replacement of the earlier claim

The former 58.430 ms to 0.319 ms / 183× comparison came from the May 25, 2026 `tdl-a_E16` records in `../2026-05-sweeps/sweep-2026-05-25-post-d2b.json` and `../2026-05-sweeps/sweep-2026-05-25-post-d3.json`. Both records used the CUDA backend. The slower implementation generated fading on the CPU; it was not a fresh comparison with the current CPU reference backend. The old slide label was inaccurate. This report replaces the values with matched current CPU-reference and CUDA runs.

## Reproduction

Build `ocudu-gpu-channel-bench` from the recorded revision with `CMAKE_BUILD_TYPE=Release`, `OCUDU_GPU_CHANNEL_ENABLE_CUDA=ON`, `OCUDU_GPU_CHANNEL_CUDA_ARCHITECTURES=120`, and CUDA 12.8.1. Use the saved backend-specific YAML files and run each three times:

```sh
OCG_BENCH_PACE=0 OCG_BENCH_REFRESH=0 OCG_BENCH_THREADS=0 \
  ocudu-gpu-channel-bench --config tdl-a_E16.cuda.yaml --duration 30s --per-node
```

Replace `cuda` with `cpu` for the CPU runs. Run the same command for 5 seconds as a separate warmup before measured runs. `--per-node` emits additional CUDA diagnostics; the plotted metric is the common aggregate `model_mix_latency` row.

Implementation: `apps/ocudu_gpu_channel_bench.cpp` and `src/latency.cpp` at the recorded revision. Raw CSVs, configurations, metadata and checksums accompany this report.
