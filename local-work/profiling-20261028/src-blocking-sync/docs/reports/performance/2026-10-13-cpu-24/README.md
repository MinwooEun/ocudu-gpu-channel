# CPU TDL processing with 24 workers — 13 October 2026

The CPU backend now accepts `runtime.cpu_threads: 24`. Previously each receiving-node call evaluated its samples serially; the benchmark could only run receiving nodes concurrently. This adds a persistent sample-worker pool shared by all receiving nodes. The default remains one calling thread with no pool.

## Results

| Variant | Median run p99 (ms) | Run p99 range (ms) | Slowest call (ms) |
|---|---:|---:|---:|
| CPU, one thread | 56.847507 | 56.798826–57.047801 | 59.959969 |
| CPU, 24 workers | 9.794650 | 9.634258–9.869149 | 21.322051 |
| CUDA | 0.230855 | 0.229187–0.231314 | 0.558084 |

The 24-worker CPU improves p99 by **5.80×** over the matched one-thread CPU run. CUDA p99 is **42.43×** lower than the 24-worker CPU p99. Each summary uses three runs of the same binary and model configuration; only backend and CPU worker count differ.

All 24 sample-worker threads accumulated CPU time. Average process CPU use across the three CPU24 runs was 8.47, 8.65, 8.56 core equivalents. Worker activity snapshots and process user/system/wall times are saved separately. Waiting and serial stages prevent continuous saturation of all cores.

The 24-worker CPU p99 still exceeds the 1 ms represented by each IQ batch. CUDA’s largest observed call in these runs was 0.558084 ms; this limited synthetic measurement does not establish a live-radio guarantee.

| Variant | Run | Measured calls | p99 (ms) |
|---|---:|---:|---:|
| cpu1 | 1 | 2,367 | 57.047801 |
| cpu1 | 2 | 2,376 | 56.798826 |
| cpu1 | 3 | 2,376 | 56.847507 |
| cpu24 | 1 | 17,019 | 9.869149 |
| cpu24 | 2 | 17,334 | 9.634258 |
| cpu24 | 3 | 17,190 | 9.794650 |
| cuda | 1 | 186,012 | 0.230855 |
| cuda | 2 | 186,687 | 0.229187 |
| cuda | 3 | 186,372 | 0.231314 |

## Scope and correctness

Each worker calculates a disjoint range of output samples for one TDL edge. All taps contributing to an output sample retain their original accumulation order. Fading-grid generation, other model steps, edge accumulation and state updates remain on the calling thread. Workers finish before delay history advances. LOS phase recurrence is replayed to each range boundary to preserve the serial realization exactly; this introduces additional work for LOS profiles.

The CPU's 24 physical cores comprise 8 performance cores and 16 efficiency cores, with one hardware thread per core ([Intel specification](https://www.intel.com/content/www/us/en/products/sku/241060/intel-core-ultra-9-processor-285k-36m-cache-up-to-5-70-ghz/specifications.html)). The pool has 24 workers plus the coordinating caller. Workers are scheduled by Linux without explicit core pinning. This is a 24-worker measurement on a 24-core CPU, not a claim that every core stays busy throughout each call.

Validation on the RTX workstation:

- All 13 CTest cases pass, including CPU/CUDA processing and runtime-update parity tests.
- A barrier test proves that 24 distinct sample workers execute concurrently; it also checks exception propagation, pool reuse, zero/uneven work sizes and invalid worker counts.
- Serial and 24-worker IQ match bit for bit over changing batch sizes, delay history, concurrent receiving nodes, gain/phase changes and profile replacement, with static, Rayleigh and Rician channels.
- Fingerprints match a probe linked against the previous revision, `f95dabd0d13db3b24e9a4b04c919ad3620468f11`. The previous-revision probe omits the new pool-specific checks and uses the original serial backend. Saved fingerprint logs record the comparison.
- The broker loopback test also runs with 24 workers through synthetic ZMQ peers and checks nonzero traffic, sequence gaps, queue overflows and socket errors. This does not qualify live radio timing.

## Matched benchmark setup

Intel Core Ultra 9 285K, NVIDIA RTX 5090, CUDA 12.8.1, NVIDIA driver 580.173.02, GCC 13.3.0, Release build for sm_120. GPU monitor files record the active PCIe link. Source is the recorded base revision plus `source.patch`; `environment.txt` identifies the measured executable, and `sha256.json` identifies the evidence.

- One gNB and eight UEs, one port per node, 16 directed edges: eight downlink and eight uplink.
- TDL-A on every edge: 23 taps, 100 ns RMS delay spread, Jakes fading with 100 Hz maximum Doppler.
- 23.04 million complex IQ samples/s; each receiving-node call processes 23,040 samples per output port (1 ms of signal). This does not specify occupied NR carrier bandwidth.
- Three 30-second runs per variant, with a separate 5-second warmup per variant. Alternating order: CPU1/CPU24/CUDA, CUDA/CPU24/CPU1, CPU1/CUDA/CPU24. Each measured run retains all calls, including initial calls.
- One coordinating thread calls the nine receiving nodes sequentially in every variant. CPU24 uses its internal 24-worker pool. The `OCG_BENCH_THREADS` option stays disabled; it would change the receiving-node scheduling.
- Synthetic deterministic IQ is reused. No pacing, input refresh, sockets or radio programs. CUDA uses the discrete-GPU copy path. All nine nodes produce nonzero output in every run.

## Timing definition

`model_mix_latency` surrounds input/output-span preparation and the synchronous `process_superposition()` call. CUDA time includes CPU preparation, transfers, GPU work, synchronization and output handling. Initialization, socket/radio work and subsequent output-power accounting are excluded.

The population combines gNB calls (eight incoming edges) and UE calls (one incoming edge each). It does not measure all 16 edges in one call. p99 is the nearest-rank 99th percentile per run; the slide plots the median of three run-level p99 values. Ratios are latency ratios for this workload, not general throughput or live-radio speedups. The benchmark's default `slot_us=500` field is separate from the configured 1 ms IQ batch duration.

## Reproduction

Apply `source.patch` to the recorded base revision. Build with `CMAKE_BUILD_TYPE=Release`, `OCUDU_GPU_CHANNEL_ENABLE_CUDA=ON`, `OCUDU_GPU_CHANNEL_BUILD_TESTS=ON`, `OCUDU_GPU_CHANNEL_CUDA_ARCHITECTURES=120` and CUDA 12.8.1. Run CTest, then use the saved YAML configurations:

```sh
OCG_BENCH_PACE=0 OCG_BENCH_REFRESH=0 OCG_BENCH_THREADS=0 \
  ocudu-gpu-channel-bench --config tdl-a_E16.cpu24.yaml --duration 30s --per-node
```

Repeat with `cpu1` and `cuda`, using the duration and ordering above. Run a separate 5-second warmup per variant first. `--per-node` supplies additional CUDA diagnostics; the comparison uses the common aggregate timing row. The report retains the earlier single-thread results in `../2026-10-13-tdl-a/`; presentation page 10 now uses this matched 24-worker comparison.
