# Incoming-stream scaling benchmark, 13 October 2026

Presentation page 12 uses fresh CUDA measurements from source revision `f95dabd0d13db3b24e9a4b04c919ad3620468f11`. Each curve uses the median of three run-level p99 values for the gNB's receiving port.

| Incoming TX ports | Total call p99 (ms) | CPU to GPU copy p99 (ms) | GPU calculation p99 (ms) | Total call p99 range (ms) | Maximum total call (ms) |
|---:|---:|---:|---:|---:|---:|
| 1 | 0.058490 | 0.016192 | 0.014240 | 0.058249–0.058507 | 0.673631 |
| 2 | 0.077087 | 0.027200 | 0.013151 | 0.076631–0.078245 | 1.242288 |
| 4 | 0.116084 | 0.040608 | 0.015007 | 0.115716–0.117445 | 1.140832 |
| 8 | 0.182652 | 0.068223 | 0.017055 | 0.180749–0.184902 | 1.497952 |
| 16 | 0.331641 | 0.119744 | 0.025183 | 0.328482–0.338508 | 3.872045 |
| 32 | 0.642709 | 0.231999 | 0.038943 | 0.637892–0.647466 | 1.126843 |
| 64 | 1.338493 | 0.450432 | 0.071967 | 1.334155–1.347793 | 1.942166 |

## Setup

- NVIDIA GeForce RTX 5090 and Intel Core Ultra 9 285K. PCIe Gen 5 ×8 observed during GPU work. Driver 580.173.02, CUDA 12.8.1, GCC 13.3.0, Release sm_120 build.
- The benchmark binary is the same isolated build used by page 10, verified before execution with SHA256 `2e27cf99f7716418017cfa19f955ae3e7aba016d00b696287deb6a112a571673`.
- One gNB and N UEs, one port per node, with N uplink and N downlink edges. N takes the values 1, 2, 4, 8, 16, 32 and 64. No UE-to-UE edges. The gNB receives N IQ streams, and each UE receives one.
- Each edge applies one tap with zero delay, -3 dB gain and zero tap phase, then a fixed 0.125 rad phase rotation and 250 Hz carrier frequency offset. This is a single-tap scaling experiment, distinct from page 10's 23-tap TDL-A fading experiment.
- 23,040 complex IQ samples per call at 23.04 MS/s, representing 1 ms of signal. Input buffers contain deterministic test IQ and are reused. No radio programs or sockets run.
- Three 10-second runs per configuration, after a separate 2-second warmup per configuration. Sweep order: ascending, descending, ascending. Measured runs retain all calls, including initial calls. One CPU thread calls each RX node sequentially. Pacing, input refresh and concurrent per-node workers are disabled. CUDA uses explicit copies (`cuda_zero_copy=0`).
- Every measured run has nonzero output and nonzero sample counts at every configured RX port. Timing alone does not prove numerical parity or live-radio qualification.

## Meaning of the chart

`node:gnb0:call_us` measures host elapsed time inside the CUDA backend from `call_start` through timing collection. It includes host preparation, CPU/GPU transfers, GPU calculation, synchronization and output handling. It excludes benchmark span preparation outside the backend, initialization, socket/radio work and output-power accounting. Selecting the gNB's records avoids mixing its N-edge workload with the single-edge UE calls.

`node:gnb0:h2d_us` and `node:gnb0:kernel_us` use CUDA event intervals for input copying and GPU calculation. The displayed phase p99 values do not add to total-call p99. Return copies and host overhead contribute to total-call time but are not separate curves.

P99 is the nearest-rank 99th percentile within each run. The chart shows the median of three p99 values. The table also gives the run-to-run p99 range and maximum observed call. The 1 ms horizontal reference is the signal duration of one configured batch, not a passed deadline test. The CSV's default `slot_us=500` comes from the 30 kHz SCS option and does not change the configured batch. The chart's equally spaced x-axis positions are successive doublings of the port count.

## Reproduction and provenance

Build the recorded revision with CUDA enabled, Release mode and architecture 120. Generate the saved configurations with `scripts/tools/gen_topology.py one-to-n N N<N>.yaml`. Run each configuration three times, after a separate 2-second warmup:

```sh
OCG_BENCH_PACE=0 OCG_BENCH_REFRESH=0 OCG_BENCH_THREADS=0 \
  ocudu-gpu-channel-bench --config N64.yaml --duration 10s --per-node
```

The measurements replace the May values in section 20.3 of `../measured-boundaries.md`. Those used PCIe Gen 5 ×4 and aggregate call percentiles. This experiment measures the gNB specifically on the current code and hardware connection, so it is not a controlled attribution of the improvement to any single change.

Implementation: `apps/ocudu_gpu_channel_bench.cpp`, `src/cuda_backend.cu`, `src/latency.cpp` and `scripts/tools/gen_topology.py` at the recorded revision. Raw CSVs, YAML configurations, GPU monitors, metadata, summary and checksums accompany this report.
