# GPU Channel Emulation on DGX Spark — Scaling Results and Proposal

Date: 2026-10-22 · Author: Minwoo Eun · Status: draft for internal review before sending to NVIDIA

## 1. Summary

On one DGX Spark (GB10) the GPU channel emulator keeps a live 5G cell (OCUDU gNB + attached UEs + Sionna RT channel) at real time for a single UE up to 100 MHz, and the GPU stays below 6 % of each 1 ms slot at every scale we tried. What limits scaling today is the CPU side of the lock-step radio loop, not the GPU: with 4 srsUEs in one 20 MHz cell the radio runs at 0.57x real time, with 16 UEs at 0.31x, while the GPU still spends only 60 µs per slot.

All numbers below were measured on 2026-10-22 on the Spark with the gNB and UE(s) attached, PDU session established, ping passing and UDP traffic flowing. Nothing is a benchmark of the emulator alone.

| Axis | Result |
| --- | --- |
| Bandwidth, OAI nrUE 1x1, CPU gNB and CUDA gNB | Real time at 20, 50 and 100 MHz with either gNB: 1,002 / 1,003 / 2,005 (CPU) and 1,002 / 1,003 / 2,004 (CUDA, 2026-10-27) slots per second against 1,000 / 1,000 / 2,000 nominal |
| UE count, srsUE, one 20 MHz cell, pedestrian Sionna channel | 1 UE 0.90x · 2 UEs 0.80x · 4 UEs 0.57x · 8 UEs 0.40x · 16 UEs 0.31x. All 16 UEs attach and are served; GPU time per slot rises only from 40 to 60 µs |
| Same, after the local SIMDe LDPC fix in srsUE (2026-10-23/24, sections 3 and 7.4) | 1 UE 0.98x · 2 UEs 0.98x · 4 UEs 0.90x · 8 UEs 0.58x · 16 UEs 0.35x (UEs on little cores drop out) |
| Same, after the native NEON LDPC decoder, gNB DL run-ahead, quiet logs and the broker wait policy (2026-10-24/26, section 7.5) | 1 UE **0.996x** · 2 UEs **0.997x** · 4 UEs **0.998x** (real time) · 8 UEs **0.93–0.94x** · 16 UEs 0.46x; what is left is two UEs on little cores (8 UEs) and the gNB's own per-slot CPU time (16 UEs) |
| Same cell with the **CUDA-accelerated OCUDU gNB** (D10 lock build, all stages on the GPU except PRACH is included too; broker and gNB in one MPS server; 2026-10-26) | 1 UE 0.998 · 2 UEs 0.997 · 4 UEs 0.995 · 8 UEs 0.91–0.93 · 16 UEs 0.44–0.45: the same curve as the CPU gNB. Without MPS (two GPU contexts) 8 UEs 0.71, 16 UEs 0.33–0.35. Two cells with CUDA gNBs: 532 / 526 slots/s under MPS (0.53), 376 / 394 without, against 877 / 884 with CPU gNBs |
| Cells per GPU | Two cells (two gNBs, two CUDA brokers, one live Sionna bridge fanned out to both) run at 674 slots/s each (0.67x); 783 / 787 slots/s (0.78x) after the UE-side LDPC fix; **877 / 884 slots/s (0.88x)** with the full recipe of section 7.5 (2026-10-26) |
| Antenna count live (4x1, 4x2, 2x4, 4x4), one OAI nrUE, idle cell, CPU / CUDA gNB (2026-10-27) | 20 MHz all 1.00; 50 MHz 0.71/0.82 · 0.65/0.72 · 0.60/0.63 · 0.49/0.51; 100 MHz 0.17/0.45 · 0.16/0.46 · 0.42/0.44 · 0.33/0.34 (last two fail the PUSCH health bound). Broker call 36–142 µs per node throughout; the wait is on the radios' IQ. With four gNB antennas at 100 MHz the CUDA gNB is 2.7x the CPU gNB, the only axis where PHY offload shows |
| Bandwidth × UE count, OAI nrUE 1x1, idle cell, CPU and CUDA gNB (2026-10-27) | 2 UEs: 20 MHz 0.99 · 50 MHz 0.99 · 100 MHz 0.84–0.85; 4 UEs: 0.95–0.98 · 0.79–0.82 · 0.50. CUDA gNB within ±0.03 of CPU at every point; the fall is UE CPU (two of four UEs on little cores) |
| 2x2 rank-2, OAI nrUE, 200 Mb/s offered | 20 MHz 0.88x · 50 MHz 0.37x · 100 MHz 0.28x (idle: 1.00 / 0.98 / 0.66x). A CUDA-accelerated gNB sharing the GPU changes none of these (full grid 2026-10-27: idle 1.00 / 0.99 / 0.69x, loaded 0.84 / 0.38 / 0.29x); with five big cores for the UE instead of two (2026-10-26): 50 MHz 0.59x, 100 MHz 0.35x, 0.42x with the gNB run-ahead. A `perf` profile shows no single hot spot in the OAI UE (LDPC, already NEON through SIMDe, is 25 % of its CPU) |
| GPU work per slot | 40–60 µs per receiver call (kernel ~24–40 µs) from 1 to 16 UEs live; 70–140 µs per receiver at every point of the emulator-boundary sweep (section 6b) |
| The emulator's boundary vs antenna count (section 6b, 2026-10-27, synthetic radios) | 2x2: real time to 8 UEs at 20 MHz, 2 at 50 MHz, 1 at 100 MHz (0.87); 4x4: 2 UEs at 20 MHz, 1 at 50 MHz, not real time at 100 MHz (0.3–0.5). Up to 2x2 at 20 MHz the limit is still the IQ transport (port count); from 2x2 at 50 MHz and at every 4x4 point the per-node GPU channel call grows with lanes × bandwidth (kernel 41 → 492 µs) and becomes the limit. Radio CPU ≤ 190 % of 500 % everywhere |
| The emulator's own boundary (section 6b, 2026-10-26, synthetic radios, no gNB or UE) | Broker as shipped: real time to **16 UEs at 20 MHz, 4 at 50 MHz, 2 at 100 MHz**; 24 / 8 / 4 UEs at 0.62–0.93. The limit is the broker's ZMQ transport (I/O threads, per-port request/reply), not the GPU: `OCG_ZMQ_IO_THREADS=4` lifts 24 UEs at 20 MHz from 0.70 to 0.87 with no code change. Channel updates at the live rate cost nothing. Separate brokers per cell pay cross-context time slicing on the GPU from three brokers up |

Section 7 pins down where the time goes, with per-slot instrumentation inside srsUE and the broker (measured 2026-10-23). Two causes account for the loss: (1) srsUE's PDSCH decode on aarch64 runs on srsRAN 4G's generic scalar LDPC/PHY path (no NEON equivalent of its AVX2 code), so a full-band 20 MHz slot costs 1.6–2.9 ms of UE CPU, and (2) the lock-step loop has no slack: OCUDU's ZMQ radio answers with DL block j only after UL block j is in, so every slot is a serial chain of gNB turnaround + broker + UE turnaround that already sums to 1.0 ms with no traffic. Core placement, idle states and thread priorities were measured and ruled out as primary causes.

We then verified cause (1) by fixing it locally (section 7.4): building srsRAN 4G's AVX2 LDPC encoder/decoder on aarch64 through the SIMDe header library (NEON emulation of the AVX2 intrinsics, no algorithmic change) makes the decoder 3.5x faster and moves the same live benchmark from 0.87 to 0.98x (1 UE), from 0.76 to 0.98x (2 UEs), from 0.57 to 0.90x (4 UEs) and from 0.40 to 0.58x (8 UEs); 16 UEs stay at 0.35x because five UEs per little core cannot keep up. What remains is cause (2) plus the generic rest of the UE PHY, which a native NEON port or a GPU decode would address further.

The proposal (section 8) asks NVIDIA for help on exactly the parts that bound these curves: a NEON or GPU LDPC/PHY path for the UE side on GB10, GPU context scheduling between tenants, and a path to a GPU-resident RAN PHY so that the radio loop stops being CPU-bound.

## 2. System under test

| Part | What ran on the Spark |
| --- | --- |
| Host | DGX Spark GB10: 10 Cortex-X925 + 10 Cortex-A725 cores (big cores are CPUs 5–9 and 15–19), 128 GB unified memory, Blackwell GPU sm_121, CUDA 13.0, Ubuntu 24.04 in Docker |
| gNB | OCUDU (srsRAN-derived) commit a1916edc, ZMQ radio, CPU PHY; optionally the CUDA-accelerated gNB (PDSCH / PUSCH / PRACH / lower PHY on the GPU, under MPS) |
| UEs | srsUE (srsRAN 4G 23.04 fork, 15 kHz FDD, 20 MHz) for the multi-UE runs; OAI nrUE for 50 / 100 MHz, 30 kHz TDD and 2x2 rank-2 |
| Channel emulator | `ocudu-gpu-channel` CUDA broker: per-link TDL plus per-receiver AWGN on the GPU every slot, zero-copy host memory, sample-indexed channel updates |
| Channel source | Sionna RT 2.0.1 ray tracing (SUTD campus scene, pedestrian UEs), 10 updates per second, solved on the same GPU. Frozen trace for the UE sweep; live bridge for the two-cell runs |
| Core and traffic | Open5GS 2.7.6, one network namespace per UE, ping plus UDP traffic per UE (bulk 5QI 9 and interactive 5QI 7 flows) |

**Real-time ratio** is radio samples delivered per wall-clock second divided by the nominal sample rate (23.04 MS/s at 20 MHz). 1.0 means the emulated air interface advances at real time. Below 1.0 the whole cell runs in slow motion: every slot still happens, but wall-clock latency and throughput scale by the ratio. It is read from the gNB-side receive link in the broker and cross-checked against gNB slot counts.

**Lock-step loop.** With ZMQ radios the gNB, the broker and each UE exchange one 1 ms IQ block at a time: the gNB sends DL, the broker applies the channel and forwards it, every UE answers with UL, the broker returns UL to the gNB, and only then the gNB produces the next DL. One round trip has to fit in 1 ms per slot, and a cell waits for its slowest UE every slot.

## 3. Scaling axis 1 — UEs per cell

One OCUDU gNB, one CUDA broker, N srsUEs, 20 MHz, pedestrian UEs on the SUTD campus scene (seed 20261016), mixed traffic (even UEs bulk download, odd UEs on/off video plus 100 Hz control), round-robin scheduler with HARQ-driven link adaptation. Each row is the mean of two cold runs of 30 s after 10 s warm-up. CPU placement: gNB on CPUs 5–12, broker on 15–16 (spinning), UEs on big cores 17–19 first, then little cores as N grows.

| UEs | Real-time ratio | Broker starvations per run | GPU time per slot p50 / p99 (µs) | GPU kernel p50 (µs) | Cell DL (Mb/s, radio time) | gNB CPU | per-UE CPU |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 0.88 | 360 | 40 / 115 | 24 | 19 | 138 % | 150 % |
| 2 | 0.76 | 1,400 | 45 / 130 | 25 | 21 | 137 % | 86 % |
| 4 | 0.57 | 2,800 | 50 / 135 | 24 | 24 | 165 % | 51 % |
| 8 | 0.40 | 17,100 | 50 / 160 | 25 | 25 | 162 % | 37 % |
| 16 | 0.31 | 34,000 | 60 / 185 | 25 | 25 | 157 % | 17 % |

What the table says:

- The GPU is flat. From 1 to 16 UEs (2 to 32 emulated links) the per-slot channel call grows from 40 to 60 µs, the kernel stays at about 24 µs. Section 6b takes the RAN out of the loop and finds the emulator's own limit elsewhere: the broker's ZMQ transport stops it at 16–24 UEs per 20 MHz cell, with the GPU call still at 70–140 µs per receiver.
- The radio loop slows with N because every slot waits for the slowest UE. Starvations (the broker waiting more than 5 ms for a peer's IQ) grow from a few hundred to 34,000 per 40 radio seconds.
- Cell throughput in radio time is constant (the 20 MHz cell is full), so wall-clock throughput falls with the ratio.
- The 1- and 2-UE rows ran with the gNB on CPUs 5–9; the 4-, 8- and 16-UE rows with CPUs 5–12 (see section 7 for why).
- For reference, the branch's stock placement (broker on a little core) gives 0.41x at 4 UEs; moving the broker and UEs to big cores alone brings it to 0.57x.

**The same sweep after the UE-side LDPC fix (2026-10-23/24).** Section 7 traces the curve above to srsUE's scalar LDPC decoder on aarch64; section 7.4 describes the local fix (srsRAN 4G's AVX2 LDPC built through SIMDe). Re-running the sweep with the fixed srsUE, same scene, seed, traffic, placement and durations:

| UEs | Real-time ratio, before → after | Broker starvations per run | GPU time per slot p50 / p99 (µs) | Cell DL (Mb/s, radio time) | gNB CPU | per-UE CPU | Audit |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 1 | 0.88 → **0.98** | 360 → 48 | 40 / 135 | 19 → 21 | 180 % | 88 % | pass |
| 2 | 0.76 → **0.98** | 1,400 → 123 | 45 / 138 | 21 → 23 | 180 % | 60 % | pass |
| 4 | 0.57 → **0.90** (0.88–0.94 over four runs) | 2,800 → 420 | 45 / 140 | 24 → 23–32 | 181 % | 48 % | pass (one of two sessions: 1 of 400 channel updates applied a block late) |
| 8 | 0.40 → **0.58** | 17,100 → 2,600 | 50 / 160 | 25 → 24 | 175 % | 39 % | pass |
| 16 | 0.31 → **0.35–0.36** | 34,000 → 5,300 | 60 / 188 | 25 → 25–37 | 166 % | 17 % | fails: 7–12 RRC releases per UE in one run, only 4 of 30 radio seconds valid in the other |

- Up to 2 UEs the cell is now at real time within the serial-chain ceiling of section 7.1 (0.97–0.98x); at 4 UEs it reaches 0.90x and the remaining loss is shared between the gNB turnaround and the UEs.
- 8 and 16 UEs stay CPU-bound on the UE side for a different reason: three big cores (plus two or five little cores) host 8 or 16 UEs, so decodes queue behind each other. At 16 UEs the UEs on the little cores (A725, half the decode speed) fall out of sync and are released, which the audit rejects. Those rows now measure core count, not the decoder.
- gNB CPU rises from 160 to 180 % because the gNB is no longer waiting: the faster UEs let it run its own slot work back to back.
- The GPU column is unchanged: 40–60 µs per slot at every N.
- The fix and the placement are both needed. With the fixed srsUE but the branch's stock placement (broker on little core 13, UEs on cores 14–19 including a little core, `rx_sleep` on) 4 UEs run at 0.45x (two runs 0.448 / 0.456) and 1 UE at 0.83–0.93x; the broker's per-slot time on the little core has a p99 of 495 µs against 135 µs on a big core. Placement alone gave 0.57x, the decoder alone 0.45x, both together 0.90x at 4 UEs.

**The same sweep with the CUDA-accelerated OCUDU gNB (2026-10-26).** The gNB was replaced by the D10 lock build of the CUDA-accelerated OCUDU (`d10-cuda-patched-sm121`, OCUDU `nvcuda_accel_02` at 5830c9cb with the C1+D8+D9+D10 patches; lower-PHY RX/TX, PUSCH, PDSCH, PRACH and SRS on the GPU, UL/DL grids managed), everything else as in the recipe above except that this build has no run-ahead knob. Broker and gNB share one MPS server unless stated (the single-cell runner otherwise keeps the broker in its own context). Each row is one session of two tests, all four audit gates passing unless stated.

| UEs | CPU gNB, recipe | CPU gNB, recipe without run-ahead | CUDA gNB, MPS (broker + gNB) | CUDA gNB, no MPS (two contexts) |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 0.996 / 0.997 | — | **0.998 / 0.998** | — |
| 2 | 0.997 / 0.997 | — | **0.997 / 0.997** | — |
| 4 | 0.998 / 0.998 | — | **0.995 / 0.995** | — |
| 8 | 0.93–0.94 | 0.921 / 0.934 | **0.913 / 0.928** | 0.713 / 0.713 |
| 16 | 0.460 / 0.460 | 0.445 / 0.453 | 0.453 / 0.442 (test 2 misses 239 channel updates) | 0.333 / 0.350 |

- **The CUDA gNB does not move the curve.** From 1 to 16 UEs it reproduces the CPU gNB within noise, and the CPU gNB without run-ahead does too (8 UEs 0.92–0.93), so neither the gNB's PHY arithmetic nor the run-ahead is what bounds 8 and 16 UEs today. The broker's own stage timings over the last 40 s of the 16-UE sessions are the same with either gNB (room 1.0–1.2 ms, data 0.5–0.7 ms per slot, channel call 48 µs): the radios drain and feed the broker at the same pace. The 16-UE limit is the CPU budget of the whole loop on 20 cores (sixteen srsUEs on three big and two little cores, gNB MAC and upper layers on eight), not the gNB's PHY. The hop traces of two further 16-UE sessions say the same: the gNB's turnaround (its reply to one UL block to its next DL block, measured at the broker) is 1.10 ms median with the CUDA gNB and 1.05 ms with the CPU gNB, and the UEs' is 1.13 and 1.10 ms (1.4 ms for the UEs on little cores), so at 16 UEs both ends of the loop exceed the 1 ms slot by the same margin whichever gNB runs (sessions `tagged-hop-cd10-16ue-*` 0.443 / 0.444, `tagged-hop-cpu-16ue-*` 0.468 / 0.469, `OCG_HOP_TRACE_DIR` traces under `/workspace/gpuch/hop-hop-*`).
- **MPS is not optional with a CUDA gNB.** With the broker in its own context and the gNB in another, 8 UEs drop from 0.92 to 0.71 (the broker's channel call grows from 52 to 118 µs and its waits with it), 16 UEs from 0.45 to 0.34, and even 1 UE is 0.93–0.96 instead of 0.998 (session g116, broker outside the server). This is the cross-context time slicing of section 6 on the live stack.
- **GPU memory.** The CUDA gNB holds about 9.5 GB of the unified memory on the GB10 (the broker 0.2 GB).
- **What did not run.** The lead-track CUDA build (`cuda-lphy-sm121`, the same OCUDU commit plus the lower-PHY run-ahead patch of section 7.5) attaches srsUEs but its lower-PHY TX then emits about 126 slots in 50 s and the UEs never reach a PDU session; the run-ahead patch and the CUDA lower PHY do not combine. A first series of CUDA runs failed at PRACH or lower-PHY demodulation for an environmental reason: the runtime-compiled FFT kernels need `libnvrtc-builtins.so.13.0`, which login shells find through `LD_LIBRARY_PATH=/usr/local/cuda/lib64` (`/etc/profile.d/cuda.sh`) and the benchmark's non-login shell did not; exporting it fixed every one of those failures. A cold CUDA gNB also compiles its kernels on the first slot, which once delayed the broker's control reply past the replay bridge's 5 s timeout (the first test of two sessions); later sessions reuse the kernel cache.

## 4. Scaling axis 2 — cells per GPU

Two OCUDU gNBs (PCI 1 and 2), two CUDA brokers, two srsUEs per cell, one live Sionna RT bridge solving the robot-ring scene at 10 Hz and fanning every update out to both brokers, so both cells see the same channel at the same instant. 30 s measured, seed 1, round robin in both cells.

| CPU placement (gNB a / gNB b / brokers / UEs) | Slots per second, cell a / cell b | Real-time ratio | Cell DL a / b (Mb/s) |
| --- | ---: | ---: | ---: |
| 5–12 shared / 5–12 shared / 13, 14 (little) / 15–19 (big) | 674 / 675 | 0.67 | 38.8 / 38.8 |
| 5–9 (big) / 10–14 (little) / 15, 16 (big, spinning) / 17–19 (big) | 383 / 401 | 0.38–0.40 | 12.9 / 22.1 |
| 5–9 (big) / 15–19 (big) / 10, 11 (little) / 12–14 (little) | 243 / 242 | 0.24 | 13.5 / 13.4 |

Same three placements after the UE-side LDPC fix (section 7.4), 2026-10-24, all three passing the branch's A/A gate:

| CPU placement (gNB a / gNB b / brokers / UEs) | Slots per second, cell a / cell b, before → after | Real-time ratio after | Cell DL a / b (Mb/s) after |
| --- | ---: | ---: | ---: |
| 5–12 shared / 5–12 shared / 13, 14 (little) / 15–19 (big) | 674 / 675 → **783 / 787** | 0.78 | 45.1 / 45.1 |
| 5–9 (big) / 10–14 (little) / 15, 16 (big, spinning) / 17–19 (big) | 383 / 401 → **607 / 567** | 0.57–0.61 | 22.6 / 32.4 |
| 5–9 (big) / 15–19 (big) / 10, 11 (little) / 12–14 (little) | 243 / 242 → **318 / 323** | 0.32 | 17.4 / 18.0 |

- Two cells with two UEs each now run at 0.78x on one GPU, up from 0.67x, and the cells still track each other within 1 %. The gain is smaller than in the single-cell sweep because here the two gNBs share eight big cores (five workers each) and the two brokers sit on little cores; with the UE decode fixed, the gNB side of the lock step (section 7.1) is what bounds this row.
- The ordering of the placements does not change: the gNB needs big cores more than anything else, and a broker or UE on a little core costs more than a shared gNB core.

Same three placements with the full recipe of section 7.5 (NEON LDPC, gNB run-ahead 3 ms, `OCG_BROKER_SPIN=2`, two ZMQ I/O threads), 2026-10-26, all passing the A/A gate:

| CPU placement (gNB a / gNB b / brokers / UEs) | Slots per second, cell a / cell b (stock → SIMDe → full recipe) | Real-time ratio | Cell DL a / b (Mb/s) |
| --- | ---: | ---: | ---: |
| 5–12 shared / 5–12 shared / 13, 14 (little) / 15–19 (big) | 674 / 675 → 783 / 787 → **877 / 884** | 0.88 | 47.6 / 47.7 |
| 5–9 (big) / 10–14 (little) / 15, 16 (big) / 17–19 (big) | 383 / 401 → 607 / 567 → **920 / 760** | 0.76–0.92 | 47.8 / 43.0 |
| 5–9 (big) / 15–19 (big) / 10, 11 (little) / 12–14 (little) | 243 / 242 → 318 / 323 → **422 / 425** | 0.42 | 24.2 / 24.4 |

- Two cells with two UEs each reach 0.88x with the brokers still on little cores; the cell whose gNB has five big cores to itself reaches 0.92x. A fourth placement (four big cores per gNB, one big core per broker) is rejected by the runner, which requires five CPUs per gNB because OCUDU's main pool deadlocks with one worker.
- With two CUDA-accelerated gNBs (D10 build, all stages) in the default placement: **532 / 526 slots/s (0.53)** with gNBs and brokers in one MPS server, **376 / 394** without MPS, against 877 / 884 with CPU gNBs. Four GPU clients (two gNBs, two brokers) share the GB10: the brokers' channel call grows from 70 to 190 µs per receiver and their input and output waits with it, so on one GPU two CUDA gNBs cost more than they save.

- Two cells on one GPU cost nothing on the GPU side: the broker per-slot time is the same as with one cell, and both cells stay within 1 % of each other.
- Where the UEs run decides the speed. Four srsUEs on five big cores give 0.67x; on three big cores 0.4x; on three little cores 0.24x. The 10 big cores of the GB10 are the scarce resource, not the GPU.
- Two cells with two UEs each (0.67x) run faster than one cell with four UEs (0.57x): the lock-step fan-in per cell is smaller.

## 5. Scaling axis 3 — bandwidth

**1x1, OAI nrUE, zero-copy broker, 25 s attach gate with ping.** Gate defaults: patched OAI ZMQ module, spark-gb10 core placement (gNB 5–9, broker 15–17 spinning, UE 18–19). CPU gNB measured 2026-10-22; the CUDA-accelerated gNB (D10 lock build, all stages, gNB and broker in one MPS server) 2026-10-27, read from the broker's per-second heartbeat on the gNB link.

| Bandwidth | Numerology | Nominal slots/s | CPU gNB, slots/s | CUDA gNB, slots/s |
| ---: | --- | ---: | ---: | ---: |
| 20 MHz | 15 kHz FDD | 1,000 | 1,002 | 1,002 |
| 50 MHz | 15 kHz FDD | 1,000 | 1,003 | 1,003 |
| 100 MHz | 30 kHz TDD n78 | 2,000 | 2,005 | 2,004 |

**2x2 rank-2, OAI nrUE, unitary 2x2 channel, 90 s run with a 15 s DL UDP iperf.** The 2x2 cell doubles the per-slot work of gNB and UE (two ports, two layers). CPU gNB rows 2026-10-22; the CUDA gNB grid (same D10 build, all stages, MPS) 2026-10-27, one run per cell.

| Bandwidth | Idle, CPU gNB | Idle, CUDA gNB | 200 Mb/s offered, CPU gNB | 200 Mb/s offered, CUDA gNB | DL delivered over the air, CPU / CUDA (Mb/s) |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 20 MHz | 1.00 | 1.00 | 0.88 | 0.84 (0.90 on 10-22) | 148 / 148 |
| 50 MHz | 0.98 | 0.99 | 0.37 | 0.38 | 386 / 386 |
| 100 MHz | 0.66 | 0.69 | 0.28 | 0.29 | 415 / 424 |

- At 20 MHz the GPU emulator is invisible: real time idle, 0.88x under full load with the CPU gNB.
- Above 20 MHz the 2x2 loop is bounded by the OAI UE's per-slot turnaround (1.2–1.8 ms per slot under load, measured in earlier work) and the gNB's sequential lower PHY, not by the channel. The broker's own share of the round is about 120 µs.
- Running the CUDA-accelerated gNB on the same GPU as the emulator (both under MPS) gives the same ratio as the CPU gNB at every bandwidth, idle and loaded, 1x1 and 2x2 (full grid 2026-10-27). Sharing the GPU is free here, and PHY offload does not move the bandwidth axis either: the loaded 50/100 MHz 2x2 rows are the UE's serial DL chain, as the next paragraph shows.

**Bandwidth × UE count with OAI nrUEs (2026-10-27).** The srsUE used for the UE sweep is a 20 MHz 15 kHz UE (srsRAN 4G's NR UE reuses its LTE PRACH library, capped at a 2048-point FFT), so the UE-count axis above 20 MHz was measured with several OAI nrUE processes instead: the branch's TDD n78 two-UE gate (`scripts/native/run-ocudu-oai-multi-ue.sh`, Sionna channel on the SUTD scene, idle cell with pings, 160 s) with three local knobs — the cell at 20 / 50 / 100 MHz at 30 kHz (51 / 133 / 273 PRB, 23.04 / 61.44 / 122.88 MS/s, the SSB ARFCN the gNB derives for each), two or four UEs, and the CUDA gNB stanza. Placement: gNB 5–9, broker 15–17, two UEs on one big + one little core each (18+4, 19+3), the third and fourth UE on little cores 13 and 14. Real-time ratio from the broker's per-second heartbeat on the gNB port (median over the window).

| Cell (TDD n78, 30 kHz) | 1 UE 1x1 (OAI gate) | 2 UEs, CPU gNB | 2 UEs, CUDA gNB | 4 UEs, CPU gNB | 4 UEs, CUDA gNB |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 20 MHz | 1.00 | 0.994 | 0.994 | 0.95 | 0.975 |
| 50 MHz | 1.00 | 0.986* | 0.988 | 0.79 | 0.82 |
| 100 MHz | 1.00 | 0.84 | 0.85 | 0.50 | 0.50 |

\* The first CPU-gNB run at 50 MHz lost one UE after 50 s to an OAI assertion on a falsely decoded DCI (`nr_dlsch_extract_rbs`, `n_dmrs_cdm_groups`); the ratio is the median of the 50 s both UEs were up; the repeat run passed the gate at the same 0.986 (one transient dip to 0.43 and 233 broker starvations in 160 s). Every other run passed the gate (all UEs RRC-connected, PDU session, ping).

- The CUDA gNB again changes nothing (±0.03 at every point): the fall from 1 UE to 2 and 4 UEs at 50 / 100 MHz is the UEs' CPU, two of the four UEs sitting on A725 cores and every UE sharing one X925 core with the rest of the stack. The emulator's own edge at these bandwidths (section 6b: 4 UEs at 50 MHz and 2 at 100 MHz at real time with synthetic radios, 8 / 4 at 0.9) is not what these rows hit — at 100 MHz with 4 UEs the broker's channel call is unchanged and every node waits on input IQ.
- Read with the srsUE column at 20 MHz (16 UEs at 0.45) and the 1x1 OAI column, the live limit on one GB10 scales roughly with aggregate sample rate × UE count: about 4 UEs × 20 MHz, 2 × 50 MHz, 1–2 × 100 MHz at or near real time, and it is set by UE CPU, not by the channel or the gNB PHY.

**Antenna count live: 4x1, 4x2, 2x4, 4x4 with one OAI nrUE (2026-10-27).** The 2x2 gate was given antenna-count knobs (gNB 2 or 4 ports, UE 1, 2 or 4 ports; DFT-based fixed MIMO matrices with orthogonal rows/columns, DL rank capped at 2 by the OAI UE), idle cell (1 Mb/s), CPU and CUDA gNB (both under MPS where CUDA). One run per point; the gate's own real-time factor over its measurement window.

| gNB × UE antennas | 20 MHz, CPU / CUDA | 50 MHz, CPU / CUDA | 100 MHz, CPU / CUDA |
| ---: | ---: | ---: | ---: |
| 1x1 | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 |
| 2x2 | 1.00 / 1.00 | 0.98 / 0.99 | 0.66 / 0.69 |
| 4x1 | 1.00 / 1.00 | 0.71 / 0.82 | 0.17 / 0.45 |
| 4x2 | 1.00 / 1.00 | 0.65 / 0.72 | 0.16 / 0.46 |
| 2x4 | 1.00 / 1.00 | 0.60 / 0.63 | 0.42\* / 0.44\* |
| 4x4 | 1.00 / 1.00 | 0.49 / 0.51 | 0.33\* / 0.34\* |

\* Attach, PDU session and ping pass but the gate's health bound fails: PUSCH error ratio 0.12–0.15 against the 0.10 limit (the UE transmits on four antennas at 100 MHz).

- At 20 MHz every antenna layout is real time with either gNB. From 50 MHz up the ratio falls with the port count on either side, and the broker is not where the time goes: its channel call per node stays at 36–142 µs (kernel 24–117 µs) at every point, while the stage that grows is the wait for input IQ from the radios (700–1,600 µs per slot at 50 MHz, up to 2.7 ms at 100 MHz 4x1 with the CPU gNB). The radios, i.e. the gNB's and the UE's PHY, deliver late.
- This is the one place where the CUDA gNB is clearly ahead: with four gNB antennas at 100 MHz the CPU gNB runs at 0.16–0.17 and the CUDA gNB at 0.45–0.46 (4x1, 4x2). There the gNB's CPU PHY is the wall; once it is on the GPU the OAI UE sets the pace. With four UE antennas (2x4, 4x4) both gNBs give the same 0.33–0.44, i.e. the UE is the wall.
- Against the channel-only antenna grid of section 6b (4x4 at 50 MHz 0.7–1.0 and at 100 MHz 0.3–0.5 with synthetic radios), the live 4x4 points sit at or below the channel's own edge, so at 4x4 and 100 MHz the RAN and the channel reach their limits together; everywhere else the RAN stops first.

**Where the loaded 2x2 loop spends its time (2026-10-26).** Two things were checked so that the 2x2 rows are read correctly. First, the gNB run-ahead of section 7.5 had already been tried on this axis in the lead-track runs of 2026-10-02 (`OCUDU_LPHY_RX_TO_TX_MAX_MS=2`, with and without the threaded lower-PHY profile): at 100 MHz idle it lifts 0.66 to 0.80–0.85, but under 200 Mb/s it moves 100 MHz only from 0.25–0.29 to 0.32–0.34, 50 MHz from 0.40 to 0.39 and 20 MHz from 0.89 to 0.95–0.98, so the loaded 50/100 MHz rows are not a lock-step slack problem. Second, a `perf` profile of the OAI UE and the gNB during the 100 MHz 200 Mb/s window (999 Hz, 12 s; this run: 0.24x, 471 Mb/s delivered in air time, health pass) shows no single hot spot of the kind srsUE had (section 7.2):

- The UE is pinned to two big cores by the gate defaults and keeps about 1.55 of them busy. Its single DL actor thread holds 36 % of the samples (channel estimation 5.7 %, channel compensation 9.4 %, `nr_rx_pdsch` 3.8 %, frequency-offset compensation 3.7 %, DFTs about 8 %); the LDPC decoder, which OAI already runs through SIMDe on aarch64 (AVX2 code mapped to NEON by `sse_intrin.h`), takes 24.5 % spread over twelve pool threads (decoder core 17.7 %, rate matching 3.5 %, de-interleaving 2.6 %); the radio thread takes 13.8 %, half of it `lrintf` in the ZMQ module's float-to-int16 conversion.
- The gNB's radio thread spends 45 % of its samples polling in `radio_zmq_rx_channel::receive` and `radio_zmq_tx_channel::send_response`, i.e. waiting on the lock step, the PHY worker 32 %, ZMQ I/O 20 %.

So a native NEON LDPC for OAI (the analogue of the srsUE fix) would recover at most 15–20 % of the UE's CPU, not the 3–20x the srsUE decoder gave; the shape of the 2x2 limit is a serial per-slot DL chain in a 0.5 ms slot on a two-core UE budget. Giving the UE five big cores instead of two (gNB 5–9, broker on little cores 10–12, UE 15–19) confirms it: 100 MHz 200 Mb/s goes from 0.24–0.26 to **0.35**, and with the gNB run-ahead (2 ms) on top to **0.42**; 50 MHz 200 Mb/s from 0.40 to **0.59** (all runs pass the health bound, 456–501 Mb/s delivered in air time at 100 MHz). The 2x2 rows above therefore measure the UE's share of ten big cores as much as the UE's code, and the remaining gap at 100 MHz is the serial DL chain in a 0.5 ms slot (item 1 of section 8), not one decoder.

## 6. Scaling axis 4 — GPU sharing and GB10 versus RTX 5090

These two results are from the same project earlier (2026-09-26 and 2026-09-30, same Spark) and are the GPU-side part of the picture.

**Tenants on one GPU (robot-ring two-cell demo, 2026-09-30).** The broker's per-slot emulator call is 0.1–0.4 ms when every other tenant (Sionna RT, a CUDA gNB, a synthetic hog) runs as an MPS client in the broker's context and the broker uses a high-priority stream. When a tenant runs in its own CUDA context and keeps the GPU busy, every other context waits one time-slice quantum per slot: the broker call rises to 2.2–2.3 ms regardless of what the broker does. Moving Sionna RT into MPS took the broker p99 from 1,493 µs to 211 µs. Stream priority, SM limits and MPS alone cannot beat cross-context time slicing from inside; the only lever left is the driver's compute time-slice policy, which is GPU-global.

**GB10 versus RTX 5090 (same emulator build, 2026-09-26, 11 channel configurations).** The per-slot emulator time is the same on both, about 44–47 µs. GB10 copies host-to-device faster (8.5 versus 14 µs) and its kernel is about twice as slow (13 versus 6.6 µs); zero-copy unified memory removes the copy stage on GB10 entirely (broker p50 40–45 µs flat from 20 to 100 MHz).

## 6b. Scaling axis 5 — the channel emulator's own boundary (2026-10-26)

Every ratio above is bounded by the RAN stack before the emulator is. To find where the emulator itself stops, the gNB and the UEs were replaced by synthetic ZMQ radios so that the broker sees exactly what it sees live (the same sample rate, slot size and lock-step request/reply per port, the broker's own pacing) but nothing on the far side is slow: one `ocudu-zmq-source` per port pushing as fast as the broker accepts, one `ocudu-zmq-sink` per port requesting once per slot, 20 s per point, real-time ratio = samples the sinks received / (sample rate × 20 s). Topologies are generated with the live benchmark's shape (one gNB, N UEs, one AWGN per receiver, an 8-tap TDL per link; live Sionna links carry 2–8 taps). The broker's own per-second stage timings (`event=cpu_stage_timings`: room = waiting for space in the RX ring the radio drains, data = waiting for input IQ, process = the channel call on the GPU, throttle = pacing) say which stage grows at the edge. Unless stated, the broker runs on cores 5–14 with blocking waits (`OCG_BROKER_SPIN=0`) and the radios on the big cores 15–19.

**Where the broker as shipped stops** (two ZMQ I/O threads, the recipe's value):

| Cell | UEs (RX nodes) | Ratio | Broker stages per slot, mean (room / data / process µs) |
| --- | ---: | ---: | --- |
| 20 MHz, 1 ms slot | 8 (9) | 1.000 | 46 / 0.4 / 56 |
| 20 MHz | 16 (17) | **1.000** | 147 / 1 / 71 |
| 20 MHz | 20 (21) | 0.86 | — |
| 20 MHz | 24 (25) | 0.62–0.75 | 1,353 / 128 / 89 |
| 20 MHz | 32 (33) | 0.46 | 1,485 / 416 / 125 |
| 50 MHz, 1 ms slot | 4 (5) | **1.000** | 695 / 1 / 82 |
| 50 MHz | 8 (9) | 0.88–0.93 | 569 / 243 / 118 |
| 50 MHz | 12 (13) | 0.56–0.63 | 938 / 494 / 135 |
| 100 MHz, 0.5 ms slot | 2 (3) | **1.000** | 178 / 10 / 72 |
| 100 MHz | 4 (5) | 0.75–0.81 | 464 / 83 / 92 |
| 100 MHz | 6 (7) | 0.58–0.63 | 624 / 152 / 103 |

- The GPU is not what stops it. The channel call (process) stays at 70–140 µs per receiver per slot at every point, and at 24 UEs it is the same with `SPIN=0` at 450 % broker CPU as with `SPIN=2` at 970 % or with all 20 cores: the ratio is 0.62 either way. What grows is **room**, the producer waiting for the radio to drain the previous slot's rows over ZMQ, and at 50/100 MHz also **data**, waiting for input IQ to arrive over ZMQ. Both are the broker's ZMQ transport: per slot it moves 184 KB (20 MHz) or 491 KB (50/100 MHz) per port in each direction, 9 MB per millisecond at 24 UEs, and all of it goes through the broker's ZMQ I/O threads (one by default, two in the recipe).
- Channel updates at the live rate (one `matrix_profile_swap` per link at 10 Hz through the control endpoint, 320–480 batches per second) cost nothing measurable at any of these points (16 UEs 0.994 → 1.000, 20 UEs 0.86 → 0.87, 24 UEs 0.75 → 0.72, 50 MHz 8 UEs 0.88 → 0.87, 100 MHz 4 UEs 0.75 → 0.81), nor do the hop trace and the control endpoint themselves (16 UEs: 1.000 with and without).
- Taps per link do not change the count: 1–32 taps per link give the same calls; 32 is the device-side ceiling (`kDeviceMaxTaps`) and a 64-tap profile is rejected at start.

**What moves the edge: ZMQ I/O threads, not CPU cores or spinning.** At 24 UEs / 20 MHz with everything else fixed, `OCG_ZMQ_IO_THREADS` 1 / 2 / 4 / 8 gives **0.47 / 0.70 / 0.87 / 0.88**; at 100 MHz / 4 UEs 0.81 / 0.91 / 0.89; at 50 MHz / 12 UEs 0.70 / 0.60 / 0.66 (no gain, within noise). `ipc://` instead of TCP loopback gives 0.80 (two I/O threads) and 0.82 (four) at 24 UEs, 0.90 at 100 MHz / 4 UEs: about the same as four I/O threads over TCP. With four I/O threads the residual at the edge is still the room stage (860 µs at 24 UEs), i.e. the per-port request/reply round trip of the radio itself; with four I/O threads and the radios on their own big cores the edge sits at 20 UEs (0.99), 24 UEs (0.87, reproduced twice), 28 UEs (0.70) and 32 UEs (0.60) at 20 MHz, at 8 / 12 UEs (0.89 / 0.59) at 50 MHz and at 4 / 6 UEs (0.91 / 0.58) at 100 MHz. Giving the broker fifteen cores including the ten little ones makes it worse (0.78), and spinning (`SPIN=2`) at this port count is worse still (0.65 at 974 % CPU), so the residual is latency in the per-port request/reply chain, not a shortage of cores. The synthetic radios themselves need big cores: sources on the five A725 cores cannot feed 25 ports (0.60 with the data stage at 1.1 ms), which is also why the live recipe keeps every radio off the little cores.

**Antenna count (2026-10-27, same synthetic-radio method, broker as shipped: two I/O threads, blocking waits, radios on big cores 15–19, broker on 5–14, 20 s runs).** Each UE and the gNB get P ports (1x1, 2x2, 4x4), so a cell with N UEs has (N+1)·P ports and every receiving node sums P transmit lanes per tap. The radios' own CPU was sampled mid-run every time: all sources together never exceeded 190 % and all sinks 150 % of the five big cores (500 %) at any point below, so the radio side is not what bounds any row.

| Cell | 1x1 | 2x2 | 4x4 |
| ---: | --- | --- | --- |
| 20 MHz | 16 UEs 1.000 · 24 UEs 0.73 | 4 UEs 1.000 · 8 UEs 0.98 · 12 UEs 0.67 · 16 UEs 0.45 | 2 UEs 1.000 · 4 UEs 0.89 · 6 UEs 0.60 · 8 UEs 0.45 |
| 50 MHz | 4 UEs 1.000 · 8 UEs 0.87 | 2 UEs 1.000 (×2; one earlier run 0.89) · 4 UEs 0.67 · 6 UEs 0.52 · 8 UEs 0.40 | 1 UE 0.69–0.97 (two runs) · 2 UEs 0.45 · 3 UEs 0.36 · 4 UEs 0.22 |
| 100 MHz | 2 UEs 0.99 · 4 UEs 0.80 | 1 UE 0.87 (×2) · 2 UEs 0.64 · 3 UEs 0.51 · 4 UEs 0.41 | 1 UE 0.34–0.50 (two runs) · 2 UEs 0.31 · 3 UEs 0.22 |

- Two regimes. At 1x1, and at 2x2 up to 20 MHz, the edge follows the **port count** exactly as before (2x2 with 18 ports 0.98 against 1x1 with 17 ports 1.000; 26 ports 0.67 against 25 ports 0.73; 34 against 33 both 0.45) and the growing stage is still the ZMQ transport (room/data), with the GPU kernel at about 40 µs per node call. From 2x2 at 50 MHz and at every 4x4 point the **GPU call itself becomes the limit**: the broker makes one channel call per receiving node per slot, and that call's kernel grows with lanes × bandwidth — 41 µs (1x1, 20 MHz) → 141 µs (2x2, 50 MHz, 4 UEs) → 235 µs (4x4, 100 MHz, 1 UE) → 492 µs (4x4, 50 MHz, 4 UEs); the whole call (p50 per node) 65–120 → 240–335 → 350 → 775–1,210 µs against slots of 1,000 µs (15 kHz) and 500 µs (30 kHz). With 4x4 at 50 MHz and 4 UEs the call alone is longer than the slot.
- Boundary with antennas, broker as shipped: **2x2 real time to 8 UEs at 20 MHz, 2 UEs at 50 MHz, 1 UE at 100 MHz with margin to spare (0.87); 4x4 real time to 2 UEs at 20 MHz and 1 UE at 50 MHz (0.7–1.0 across runs), and 100 MHz 4x4 is not real time even with one UE (0.3–0.5).** The 4x4 single-UE points vary by ±0.15 between runs at the same settings; the trend with UE count is monotonic in every series.
- What this adds to item 5 of section 8: the IQ transport is the first wall (1x1 and 2x2 at 20 MHz), the per-node channel kernel the second (2x2 above 20 MHz, 4x4 everywhere). Neither is the CPU of the radios, and neither was reached by any live run of sections 3–5.

**Brokers per GPU (cells as separate processes, i.e. separate CUDA contexts).** 4-UE cells at 20 MHz, one broker each: 2 brokers 0.995, 3 brokers 0.93, 4 brokers 0.89, 5 brokers 0.68; two 8-UE brokers 0.93 (one 16-UE broker: 1.000). The channel call grows with the number of contexts: 70 µs with one broker, 154 / 236 / 451 / 544 µs per call with 2 / 3 / 4 / 5 brokers, which is the cross-context time slicing of section 6 (the GPU alternates between contexts rather than running their kernels together). At 50 MHz two 4-UE brokers run at 1.000 / 0.81 and at 100 MHz two 2-UE brokers at 0.67 against 1.000 for one. Two cells on one GB10 therefore cost little at 20 MHz, and the live two-cell row (0.88) is not bounded here; from three brokers up the context switching is a real part of the budget, and MPS (section 6) is the known remedy.

**Boundary of the channel on one GB10, broker as shipped (two I/O threads):** 16 UEs at 20 MHz, 4 UEs at 50 MHz, 2 UEs at 100 MHz at real time with margin; 20–24 / 8 / 4 UEs at 0.75–0.9. Four ZMQ I/O threads (an environment knob, no code change) move the 20 MHz edge to about 24 UEs at 0.87. The GPU call budget is 70–140 µs per receiver and is not the limit at any of these points.

**Does the knob carry over to the live stack?** Only where the broker has cores to spare. In the live recipe the broker sits on two big cores (the gNB needs five and the UEs three), and there `OCG_ZMQ_IO_THREADS=4` is a regression: 8 UEs drop from 0.93–0.94 to 0.65 / 0.68 (session g107; every broker stage slows, the channel call 49 → 128 µs, room 328 → 794 µs, data 120 → 310 µs, because four I/O threads plus 27 spinning broker threads now share two cores), 16 UEs stay at 0.45 / 0.46 (g108; the data stage, waiting for the gNB's IQ, is 10–12 ms per slot with either setting, so the broker is not what bounds 16 UEs live) and two cells stay at 863 / 878 slots/s (brokers on one little core each). The recipe therefore keeps two I/O threads on this box; four is the right value when a broker can have four or more cores of its own, for example with the UEs on another machine. No change to the broker's code or behaviour is planned from these results (decision of 2026-10-26); items 1–3 of the recipe (I/O threads matched to the broker's cores, broker and radios on big cores, blocking waits above about 20 ports and spinning below) are the complete first-tier answer.

The full dataset, the drivers and the Sionna-side solve times (26 / 32 / 45 / 88 ms per 10 Hz step at 1 / 4 / 8 / 16 UEs, the solver not running during the boundary runs) are in the upstream report `docs/reports/performance/2026-10-26-gb10-broker-boundary/` (PR zhouyou-gu/ocudu-gpu-channel#9).

One measurement artefact to note: the branch's `ocudu-gpu-channel-bench` tool, which drives the channel call alone, saturates at about 24,500 calls per second at 20 MHz and 10,900 at 50/100 MHz whatever the thread count. That is the tool's own per-call accounting (a per-sample power sum under one global mutex), not the GPU, and its numbers were not used above.

## 7. Where real time is lost

We first split one slot of the lock-step loop into hops inside the broker (ZMQ pull / channel / reply timestamps, 4 UEs, 20 MHz, mixed traffic, big-core placement), then instrumented srsUE itself slot by slot (sync thread, PHY workers, PDSCH decode stages, ZMQ send/receive; patch `srsue-slot-trace.patch`, same CLOCK_MONOTONIC as the broker trace). All numbers are from live sessions with the gNB, 5GC, UEs, ping and UDP traffic up.

### 7.1 The loop is a serial chain with no slack on the gNB side

| Quantity (broker trace, median / p90 / p99) | 4 UEs, 2 % traffic (0.97x) | 4 UEs, mixed traffic (0.57x) |
| --- | ---: | ---: |
| Slot cycle | 996 / 1,316 / 1,899 µs | 1,001 / 3,000 / 6,941 µs |
| gNB: UL block delivered → next DL block handed back | 587 / 810 / 941 µs | 579 / 1,049 / 1,603 µs |
| UE: DL block delivered → next UL block handed back | 337 / 612 / 2,088 µs | 303–337 / 1,384–1,651 / 3,351–4,384 µs |
| Broker channel processing (GPU) | 40 / 60 / 130 µs | 45 / 60 / 135 µs |
| TX lead over RX, gNB (blocks the node is ahead) | 0 (range −1…+1) | 0 |
| TX lead over RX, each srsUE | 2 (range 1…3) | 2 (range −1…3) |

OCUDU's ZMQ radio produces DL block j only after it has received UL block j (lead 0), so each slot is gNB turnaround (0.58 ms) + two broker hops + UE turnaround (0.3 ms) in series: 1.0 ms with no traffic at all. That is why the best case is 0.97x, not 1.2x, and why every tail on either side lands directly on the slot cycle. srsUE keeps a two-block lead (its UL timestamps are 4 ms ahead but the ZMQ driver only releases one block per worker), which absorbs a UE slot of up to ~2 ms and nothing beyond.

In the slow slots (>2 ms) of the mixed run, 75–85 % of the excess time belongs to the UEs (spread evenly over the four, no periodicity) and 15–25 % to the gNB.

### 7.2 What the UE does with its 2 ms: PDSCH decode

Per-slot timing inside srsUE (Cortex-X925 cores, 30 s window, mixed traffic):

| UE-side quantity | 1 UE (0.87x) | 4 UEs (0.57x), per UE |
| --- | ---: | ---: |
| Slots with a PDSCH grant | 89 % | 12–19 % |
| PDSCH decode, full-band allocation (80–106 PRB), median | 1.9–2.0 ms | 1.0–2.9 ms (MCS 9 → 18) |
| PDSCH decode, 27–52 PRB, median | — | 0.4–1.2 ms |
| PDSCH decode, 1–26 PRB, median | — | 0.16–0.48 ms |
| PUSCH encode, 17–18 kbit, median | 0.69 ms | 0.70–0.71 ms |
| Everything else in the worker per slot (CSI, FFT, PDCCH) | 125 µs | 125 µs |
| Time the UE spends blocked waiting for the broker's pull (ZMQ send) | 0 µs median | 1 µs median |
| Worker CPU per UE | 0.85 cores | 0.2–0.3 cores |

Inside the decode, stage timers show where the time is (1 UE, 26,768 PDSCH decodes, 2.98 LDPC code blocks each):

| PDSCH decode stage (median per slot) | Time | Share of decode |
| --- | ---: | ---: |
| DMRS channel estimation | 26 µs | 1.3 % |
| Resource-element extraction + equalization | 39 µs | 1.9 % |
| Soft demodulation | 7 µs | 0.3 % |
| LDPC rate dematching (per code block) | 31 µs | 4.4 % |
| **LDPC decode + CRC (per code block, at an average of 1.0 iteration)** | **571 µs** | **91 %** |
| Whole PDSCH decode | 1,897 µs | 100 % |

The decoder terminates after a single iteration on almost every block (`avg_iter` = 1.0) and still costs 0.57 ms per 8,448-bit code block, i.e. about 15 Mb/s of coded throughput per iteration on a Cortex-X925 at 3.9 GHz. Decode time therefore scales with the allocation size (number of code blocks), not with the transport block size: a 15 kbit block at MCS 9 over 96 PRB costs the same 2 ms as a 31 kbit block at MCS 18. Capping LDPC iterations at 4 (instead of 10) leaves the median unchanged (the median block already stops after one) and only trims the tail of blocks that fail and run to the cap; the real-time ratio moves from 0.57 to 0.64 (4 UEs) and 0.87 to 0.92 (1 UE), which confirms the mechanism without being a fix. The cause is the implementation: srsRAN 4G selects its AVX512/AVX2 LDPC decoders only on x86 and otherwise falls back to generic scalar C (`SRSRAN_LDPC_DECODER_C`); there is no NEON path. Its own micro-test on this machine gives 2.9 Mb/s coded throughput on an X925 core and 1.35 Mb/s on an A725 core for BG1 at rate 1/3 (ten iterations), and the encoder 34 Mb/s. The same srsUE on an x86 host with AVX2 ran the same benchmark at 99.9 % real time; that gap is this decoder.

With 4 UEs in round robin each UE decodes a full-band block roughly every fourth to sixth slot; the 2 ms decode plus the following slot's work exceeds its two-block lead, the UE's UL block arrives late, and the gNB (lead 0) waits for it. With 1 UE the UE decodes in 89 % of slots at ~2 ms each; three PHY workers keep the throughput, but the latency is exposed on 15 % of cycles.

### 7.3 Ruled out by measurement

| Hypothesis | Test | Result |
| --- | --- | --- |
| Deep CPU idle (LPI-2/3, up to 433 µs exit) | Disabled on the ten slot-path cores (host root) | 0.571 → 0.580 (noise) |
| srsUE `rx_sleep` (1 ms sleep per receive; fixed 92 → 99.9 % on x86) | `rx_sleep=false` | No change on GB10 |
| Priority inversion in srsUE (ZMQ/IQ threads SCHED_OTHER vs FIFO-96 decoders, 3.3 cores of run-queue wait) | IQ threads to SCHED_FIFO 97 | Run-queue wait vanished, real time unchanged (0.54–0.56): the wait moved to the decode workers |
| Too few UE cores | 4 big cores for 4 UEs instead of 3 | 0.593 / 0.556 (noise) |
| Broker / GPU | Per-slot processing time | 40–60 µs, p99 < 0.5 ms at every UE count |
| Core placement | Stock (broker on a little core, UEs partly on little cores) vs all slot-path threads on X925 cores | 0.41 → 0.57: real, but secondary |

Two platform facts still matter for anyone running real-time RAN on GB10:

- **OCUDU sizes its main worker pool as min(5, pinned CPUs − 3).** A 5-core gNB pin leaves 2 workers; with 4 UEs attaching together the RRC procedures stall and the PDU session never completes. An 8-CPU mask restores 5 workers and 16 UEs attach cleanly.
- **Little cores are not usable on the slot path.** A broker, gNB thread or UE on an A725 core adds hundreds of microseconds per hop. Ten big cores have to hold the gNB (5), the brokers (2–3) and all UEs.

### 7.4 Verifying the cause by fixing it: AVX2 LDPC on aarch64 through SIMDe

srsRAN 4G's AVX2 LDPC encoder and decoder compile on aarch64 unchanged when the `immintrin.h` include is redirected to SIMDe (`simde/x86/avx2.h` with native aliases; `libsimde-dev` 0.7.2 as packaged by Ubuntu). The patch (`srsran4g-ldpc-simde.patch`, 178 lines) adds a CMake option, builds the six AVX2 LDPC sources with `-DLV_HAVE_AVX2` and the shim include path, and lets `sch_nr.c` select the AVX2 encoder/decoder when the option is on. srsRAN's own `ldpc_dec_avx2_test` / `ldpc_enc_avx2_test` pass for BG1/BG2 at lifting sizes 2–384. This is emulation, not a NEON design: each 256-bit AVX2 vector becomes two 128-bit NEON operations, and the horizontal/shuffle idioms cost more than their x86 originals.

| LDPC micro-test, BG1, lifting 384, rate 1/3 | Generic C (stock on aarch64) | AVX2 via SIMDe | Ratio |
| --- | ---: | ---: | ---: |
| Decoder, coded throughput, Cortex-X925 | 3.0 Mb/s | 10.5 Mb/s | 3.5x |
| Decoder, coded throughput, Cortex-A725 | 1.35 Mb/s | 5.0 Mb/s | 3.7x |
| Encoder, Cortex-X925 | 34 Mb/s | 1,260 Mb/s | 37x |

Live benchmark, same configuration as the UE sweep (one 20 MHz cell, pedestrian Sionna channel, mixed traffic, RR + HARQ-OLLA, 30 s, two runs per session):

| Live metric | 1 UE, before → after | 4 UEs, before → after | 8 UEs, before → after |
| --- | ---: | ---: | ---: |
| Real-time ratio | 0.86 / 0.87 → **0.99 / 0.98** | 0.57 → **0.94 / 0.90** (second session 0.88 / 0.90) | 0.40 → **0.58 / 0.58** |
| Full-band PDSCH decode, median per UE | 1.90 ms → 0.63 ms | 1.0–2.9 ms → 0.67–0.69 ms | — → 0.68–1.1 ms (p90 1.4–5 ms on shared cores) |
| LDPC decode + CRC per code block, median | 571 µs → 148–157 µs | — → 148–152 µs | — |
| PUSCH encode (18 kbit), median | 0.69 ms → 0.19 ms | 0.70 ms → 0.19 ms | — |
| UE worker CPU per UE | 0.85 cores → 0.4 cores | 0.2–0.3 → 0.13 cores | — |
| Slot cycle (broker trace), median / p90 / p99 | — | 1,001 / 3,000 / 6,941 → 950 / 1,717 / 2,957 µs | — |
| Excess time in slow slots (>2 ms), gNB share | 15–25 % | 15–25 % → **~40 %** | — |

Two things follow. First, the decoder was the cause, together with placement: with the branch's stock placement the fixed decoder only lifts 4 UEs from 0.41 to 0.45x, because the broker on a little core (p99 495 µs per slot) and the UEs sharing little cores then bound the loop; with the big-core placement with 4 UEs the real-time ratio moves from 0.57 to 0.90–0.94 and the UE-side share of the slow slots falls until the gNB's own turnaround (0.42 ms median, 1.3 ms p99) is as large a contributor as any single UE. Second, the loop is now bounded by cause (2): the mean cycle of 1.09 ms against a 1.0 ms slot is the serial chain gNB + broker + UE with lead 0 on the gNB side, so the remaining 6–10 % cannot come from the UE alone. The 4-UE session is marked UNQUALIFIED by the branch's own audit for a single channel update (1 of 400) applied one block late, a direct consequence of not yet being at real time. 8 UEs stay at 0.58 because five srsUEs share three X925 cores and two A725 cores; the per-slot decode is now fast, but the tails (p90 1.4–5 ms) come from UEs queued behind each other on the same core.

A native NEON port of the decoder (srsRAN Project ships one for its gNB) should give another 2–3x over SIMDe, and a GPU LDPC shared by all emulated UEs would remove the per-core limit that caps the 8-UE case. Neither changes the gNB-side lock-step bound, which is OCUDU's radio and the broker (item 1 of section 8).

### 7.5 Second round (2026-10-24): native NEON LDPC, gNB run-ahead, and where 8 UEs stop

Three more local changes were made and measured, each on top of the previous one:

1. **A native NEON LDPC decoder for srsUE** (`ldpc_dec_c_neon.c`, a port of srsRAN 4G's AVX2 layered min-sum decoder to 128-bit NEON sub-nodes; same algorithm and LLR saturation rules; selected by default on aarch64, with `SRSRAN_LDPC_DECODER=c|simde|neon` for A/B runs). srsRAN's decoder test passes for BG1 and BG2 at every lifting size tried (2–384). Coded throughput, BG1 lifting 384: 68 Mb/s on a Cortex-X925 (6.6x the SIMDe build, 22x the generic decoder) and 24 Mb/s on a Cortex-A725. A newer SIMDe (0.8.4) gave nothing over 0.7.2. Live: full-band PDSCH decode median 0.30 ms (was 1.9 ms stock, 0.63 ms with SIMDe), LDPC per code block 28 µs, UE worker load 0.09 cores per UE at 8 UEs.
2. **gNB-side DL run-ahead.** The lead-0 behaviour of section 7.1 is OCUDU's lower PHY: `dl_process` waits until the DL timestamp is within `rx_to_tx_max_delay` (1 ms stock) of the last received UL sample. The branch's lead-track OCUDU build exposes it as `OCUDU_LPHY_RX_TO_TX_MAX_MS`; at 3 ms the gNB keeps a TX lead of 2 blocks, its turnaround median drops from 0.42 to 0.22 ms and UE tails of up to 3 ms no longer stall the slot. The threaded lower-PHY profiles of that build (`single`, `dual`, with or without the radio-worker real-time priority) stall the gNB for hundreds of milliseconds and break attach; they were not used.
3. **Logging and placement.** At info level the gNB writes 274 MB per 40 s run (RLC, PDCP, GTPU and PHY per-PDU lines, 2.1 M lines) and each srsUE 350 MB (2.3 M PHY_LIB candidate lines), all from data-path threads. Setting those layers to warning (the scheduler lines the analysis needs stay at info) and switching the MAC pcap off is worth about 0.02 at 8 UEs. The broker must stay on big cores (broker on two little cores: 0.45 at 8 UEs, GPU-call p99 195 µs); srsUEs tolerate two per big core.

The broker paces every producer at the nominal sample rate (`runtime.pacing`), so 1.00 is the ceiling by construction and any cycle longer than 1 ms is lost for good.

| Configuration (live, 20 MHz, mixed traffic, RR + HARQ-OLLA) | 1 UE | 2 UEs | 4 UEs | 8 UEs | 16 UEs |
| --- | ---: | ---: | ---: | ---: | ---: |
| Stock branch on GB10 (2026-10-22) | 0.88 | 0.76 | 0.57 | 0.40 | 0.31 |
| + big-core placement + SIMDe LDPC (section 7.4) | 0.98 | 0.98 | 0.90 | 0.58 | 0.35 |
| + NEON LDPC | — | — | 0.993 / 0.995 | 0.78 (re-pinned: two UEs per big core) | 0.36–0.37 |
| + gNB run-ahead 3 ms | — | — | **0.998 / 0.997** | 0.78–0.81 | — |
| + quiet logs, pcap off | — | — | **0.998 / 0.998** | 0.81–0.82 | 0.38–0.40 (passes the audit) |
| + broker wait policy `OCG_BROKER_SPIN=2` (+ 2 ZMQ I/O threads) | **0.996 / 0.997** | **0.997 / 0.997** | **0.998 / 0.998** | **0.93–0.94** (five sessions: 0.928–0.942) | 0.46 |

Four UEs are at real time. Eight UEs first stopped at 0.81, and the hop trace said why: the UEs were no longer on the critical path (each keeps its two-block lead and spends 9 % of a core), the gNB held its two-block lead as well, yet the slot cycle still took 1.1–1.2 ms in the median, growing linearly with the UE count (4 UEs 1.0 ms, 8 UEs 1.2 ms, 16 UEs 2.3 ms). That is the broker: per slot it moves 184 KB per port in and out over ZMQ (3 MB at 8 UEs, 6 MB at 16) with a puller and a REP thread per port plus a producer per node (27 threads at 8 UEs) on two cores, and the benchmark runs it with `OCG_BROKER_SPIN=1`, so all 27 threads spin for those two cores. Turning the spin off gives 0.87–0.89; `OCG_BROKER_SPIN=2` (spin only on in-process hand-offs, block on sockets) gives **0.93–0.94**, reproduced over five sessions, with the median cycle back at the 1 ms pacing floor. A second ZMQ I/O thread (`OCG_ZMQ_IO_THREADS=2`; the default is one for every transfer) adds nothing measurable, nor do four.

The last 6 % at 8 UEs is tails (cycle p90 1.6–1.7 ms, p99 2.4 ms), and half of the slow cycles belong to the two UEs on little cores (A725: UE turnaround median 0.65 ms against 0.5 ms on an X925). There is no big core left to move them to: the gNB needs five, the broker two, and three big cores host the other six UEs two each. Every rearrangement tried costs more than it gains: broker on one core (0.54), three UEs per big core (0.71), four UEs per big core (0.50), broker on little cores (0.45). At 16 UEs the gNB itself exceeds the slot (turnaround median 0.76–1.0 ms, cycle 2.0–2.2 ms), so 16 UEs on one GB10 is bounded by the gNB's CPU PHY and MAC, which is item 1 of section 8.

What this round rules out: ZMQ single-copy on the gNB radio worker (0.81 → 0.81), real-time priority for that worker (no change), an idle sleep in its polling loop (same ratio, gNB CPU 170 % → 90 %), two instead of three PHY workers per UE, the per-slot trace instrumentation itself (0.776 with and without it), srsUE's `rx_sleep` (worse: 0.85–0.88), and a gNB on five big cores with a forced five-thread main pool (attach of the first test fails).

## 8. What we propose to NVIDIA

The emulator is not the bottleneck on GB10 for anything the live stack can reach today; the host side of the radio loop is. The emulator's own edge, measured without the RAN (section 6b), is its ZMQ IQ transport at 16–24 UEs per 20 MHz cell and 4 UEs at 100 MHz, with the GPU call still small. We would like NVIDIA's help on the five items below, in this order of impact.

1. **A GPU-resident RAN PHY on GB10.** Today the gNB's CPU PHY (and the UE's) bound the loop. Access to or guidance on Aerial cuPHY / cuBB on GB10, or a review of our CUDA-accelerated OCUDU PHY, would let the DL/UL turnaround move onto the GPU where the emulator already lives. Target: one 20 MHz cell with 16 UEs at real time on one Spark. Measured on 2026-10-26: the current CUDA-accelerated OCUDU gNB (D10) gives the same 1–16 UE curve as the CPU gNB under MPS, so the next gain has to come from the rest of the loop (UE CPU, gNB MAC and upper layers, broker transport), not from PHY offload alone.
2. **A NEON or GPU LDPC/PHY path for the UE side on GB10.** The UE decoder was the single largest loss (section 7.2); our SIMDe build (section 7.4) recovers most of it at 1 and 4 UEs and proves the mechanism, but it is emulation of x86 code and caps at about 10 Mb/s coded per core. Options we see: a NEON port of srsRAN 4G's AVX2 LDPC decoder (srsRAN Project already ships one for its gNB), a cuPHY/cuBB-based or CUDA LDPC decode shared by all emulated UEs, or NVIDIA's guidance on the Arm vector path for GB10. Target: full-band PDSCH decode under 0.3 ms per slot per UE.
3. **GPU scheduling between tenants.** Our live system runs three kinds of tenant on one GPU: the channel brokers (hard 1 ms deadline), Sionna RT ray tracing (bursty, 25–50 ms solves) and the CUDA gNB. We need a sanctioned way to keep the broker's deadline when another context is busy: compute time-slice policy per process rather than per GPU, or priority between contexts. We have a reproducible two-cell scheduling demo for this.
4. **A second GB10 or an NVLink pair.** The next scaling axis is cells across nodes: two brokers on two Sparks sharing one Sionna scene. We have the fan-out bridge already; we lack the second box.
5. **The IQ transport between emulated radios and the emulator on GB10.** Section 6b shows the channel stopping not in the GPU (70–140 µs per receiver per slot) but in moving 9 MB per millisecond of IQ through ZMQ over TCP loopback per 20 MHz cell of 24 UEs, and 4x that per port at 100 MHz. The per-receiver call structure stays as it is (one call per receiver the moment its inputs exist). What we would like from NVIDIA is guidance on a shared-memory IQ path on GB10's unified memory between the radios and the emulator (zero-copy rings the GPU can read directly, in place of ZMQ messages), which would remove the transport stage from the slot budget. Target: 64 UEs at 20 MHz, 16 at 100 MHz, per GB10.

What NVIDIA gets: a complete, open, reproducible real-time RAN-plus-channel benchmark on Spark (gNB, UE, core, ray-traced channel, all live) with the scaling curves above as the baseline, and co-authorship on the write-up.

## 9. Methods and reproducibility

- Code: `ehs0/ocudu-gpu-channel`, branch `RAN_benchmark` at commit c5eb514 (single-cell and two-cell scheduler benchmarks, Sionna traces), with three local knobs added to `use_cases/ran_benchmark/run-single-cell-policy.sh` for this study (CPU placement, srsUE `rx_sleep`, log level). Patch: `~/ocudu-work/share/ranb-local-knobs-2026-10-22.patch`. Bandwidth runs use the `br15` tree's OAI 1x1 / 2x2 gates with the S11 defaults.
- Instrumentation: broker hop trace (`OCG_HOP_TRACE_DIR`, in the branch) and the srsUE per-slot trace patch `srsue-slot-trace.patch` (header `lib/include/srsran/phy/utils/slot_trace.h`, probes in `sync_sa.cc`, `nr/sf_worker.cc`, `nr/cc_worker.cc`, `ue_dl_nr.c`, `pdsch_nr.c`, `sch_nr.c`, `rf_zmq_imp*.c`; env `SRSUE_SLOT_TRACE_DIR`), plus the diagnostic knob `SRSRAN_LDPC_MAX_ITER`. Fixes: `srsran4g-ldpc-simde.patch` (copy `~/ocudu-work/share/srsran4g-ldpc-simde-2026-10-23.patch`; build `builds/srsran4g-zmq-local` with `-DSRSRAN_LDPC_SIMDE=ON`) and the native NEON decoder on top of it, `~/ocudu-work/share/srsran4g-ldpc-neon-simde-2026-10-24.patch` (12 files; `ldpc_dec_c_neon.c`, test `ldpc_dec_neon_test`, A/B env `SRSRAN_LDPC_DECODER`). Benchmark knobs used in section 7.5 (per-UE CPU pin, quiet logs, PHY workers, gNB main-pool/RU affinities): `~/ocudu-work/share/ranb-local-knobs-2026-10-24.patch`. gNB run-ahead: the branch's lead-track OCUDU build with `OCUDU_LPHY_RX_TO_TX_MAX_MS=3`; broker: `OCG_BROKER_SPIN=2`. Sessions `tagged-trace*-*`, `tagged-iter4-*`, `tagged-iso-*`, `tagged-simde-{1ue,4ue-e,8ue}-*` (2026-10-23), `tagged-simde-{2ue,16ue,4ue-f}-*` and two-cell reports `20261024T11{1303,1436,1608}Z` (2026-10-24); srsUE traces `/workspace/gpuch/slottrace-*`; LDPC micro-test output `/workspace/gpuch/ldpc-bench.txt`.
- Raw data on the Spark (container `ocudu-minwoo`): single-cell sessions under `/workspace/ocudu-spark-ranb/results/single-cell-scheduler-benchmark/tagged-*` (g1–g16); two-cell reports under `/workspace/ocudu-spark-ranb/results/reports/ocudu-scheduler-benchmark/20261022T11{0848,1038,1223}Z`; 2x2 bandwidth runs under `/workspace/gpuch/lead/runs/bw*`; 1x1 bandwidth runs `oai-1x1/20261022T1135{34}Z, …3614Z, …3653Z`; hop traces `/workspace/gpuch/hop-1ue`.
- Every single-cell session passed the branch's own fairness audit (trace hash, sample-aligned channel updates, traffic set, all UEs attached) except where noted as failed; failed runs are excluded from the tables and explained in section 7. Three 4-UE sessions on 2026-10-23 were killed 46 s into measurement by the previous, timed-out session's cleanup: the controller identifies a session's processes by the shared `active` directory path, so a late cleanup of one session kills the next (reported to the branch owner together with the Sionna channel-trace build occasionally hanging at start-up with no progress, which is what triggered the timeouts).
- Emulator boundary (section 6b): topology generator `gen.py` (N UEs, sample rate, taps, ports, cells; same YAML shape as `render_single_cell.py`), sweep driver `sweep.sh` around `ocudu-gpu-channel-bench` (`OCG_BENCH_PACE=1 OCG_BENCH_REFRESH=1 OCG_BENCH_THREADS=1`, 10 s per point) and broker driver `phase2.sh` around `ocudu-gpu-channel` + `ocudu-zmq-source` / `ocudu-zmq-sink` (20 s per point, sinks paced at one request per slot, radios pinned apart from the broker), all in `~/ocudu-work/share/channel-boundary-2026-10-26/`; raw CSVs and logs on the Spark under `/workspace/gpuch/bound/` (`phase1*.csv` bench, `phase2*.csv` broker, `p2-*/` per-run source, sink and broker logs). Build: `/workspace/ocudu-spark-ranb/builds/ocudu-gpu-channel-single-cell` (the branch at c5eb514). Two-cell final-recipe reports: `/workspace/ocudu-spark-ranb/results/reports/ocudu-scheduler-benchmark/20261026T07{4139,4313,4445}Z`; 1- and 2-UE final-recipe sessions `tagged-final-{1ue,2ue}-*` (g105, g106).
- Emulator boundary, drivers and data: `phase2.sh` / `phase4.sh` (one broker; `phase4.sh` adds I/O-thread, transport, trace and control knobs and a start retry), `phase3.sh` (K brokers, Sionna-rate updates through `updater.py`, hop trace), `stagestat.py` (per-stage breakdown from the broker's `cpu_stage_timings` lines), `hopstat.py`; CSVs `phase2*.csv`, `phase3.csv` (invalid: a foreign GPU tenant during the run, repeated as `phase5.csv`), `phase4.csv`, `phase6.csv`, all in `~/ocudu-work/share/channel-boundary-2026-10-26/` and on the Spark under `/workspace/gpuch/bound/` with per-run broker, source, sink and update logs (`p2-*`, `p3-*`, `p4-*`). One operational trap met on the way: after a day of runs the container held 96 GB of file cache and the NVIDIA driver intermittently failed to create a GPU context (`cudaSetDevice failed: out of memory`, kernel log `kgrctxAllocCtxBuffers: NV_ERR_NO_MEMORY`) with 9 GB free; a temporary 48 GB anonymous allocation inside the container reclaimed the cache and the failures stopped (8/8 starts).
- CUDA gNB sessions (2026-10-26): `tagged-cd10-{1ue,2ue,4ue,8ue,16ue,8ue-nomps,16ue-nomps}-*` (g117–g123), smoke `tagged-cuda-4ue-d10all-fix-*` (g115), broker-outside-MPS `tagged-cd10-all-1ue-*` (g116), CPU controls `tagged-cpu-noahead-{8ue,16ue}-*` (g124, g125), two-cell reports `20261026T13{1042,1405}Z`; failed first series `tagged-cuda-4ue{,-noprach,-pdsch,-d10all,-lphy-noahead,-lphyall-fix}-*` (g109–g114, NVRTC library path / lead build). Runner knobs added locally for these runs (`~/ocudu-work/share/ranb-cuda-gnb-knobs-2026-10-26.patch`): `SINGLE_CELL_GNB_ACCELERATION=<stage>` (+ `SINGLE_CELL_CUDA_LOWER`, `SINGLE_CELL_CUDA_LOWER_PRACH`, `SINGLE_CELL_CUDA_GRID_MODE` overrides), `SINGLE_CELL_GNB_START_TIMEOUT`, `SINGLE_CELL_MPS=on` (runs the benchmark under `scripts/cuda/with-cuda-mps.py`), `SINGLE_CELL_BROKER_IN_MPS=1`; the two-cell equivalents `OCUDU_NATIVE_SB_GNB_ACCELERATION`, `OCUDU_NATIVE_SB_BROKER_IN_MPS`.
- Live antenna sweep (2026-10-27): 2x2 gate with local knobs `OAI2X2_GNB_ANT` (2|4) and `OAI2X2_UE_ANT` (1|2|4) in `scripts/native/render-oai-2x2-configs.py`, `run-ocudu-oai-2x2.sh`, `run-ocudu-oai-2x2-inner.sh` (gNB `nof_antennas_dl/ul`, N-port device_args, UE `--ue-nb-ant-rx/tx`, M ZMQ channel pairs 2100–2107, `uecap_ports{M}.xml`); topologies from `/workspace/gpuch/bound/gen-nxm-topology.py` (DFT-based fixed MIMO); patch `~/ocudu-work/share/oai-gate-nxm-antennas-2026-10-27.patch`; runs `/workspace/gpuch/lead/runs/n{4x1,4x2,2x4,4x4}-{20,50,100}i-{cpu,cuda}-*`, list `~/ocudu-work/share/channel-boundary-2026-10-26/live-nxm-runs.tsv`.
- Antenna grid (2026-10-27): `/workspace/gpuch/bound/phase7.sh` + `run-phase7.sh` (gen.py `--gnb-ports/--ue-ports`, radios' CPU sampled mid-run), results `phase7.csv`, repeats `phase7r.csv` (copies in `~/ocudu-work/share/channel-boundary-2026-10-26/phase7*.csv`), GPU split from the broker's `event=gpu_timings` (h2d/kernel/d2h) and `process_latency_summary` per node. Two runs before the spin setting was unified are in `phase7.attempt1.csv` / `phase7.spin2-partial.csv`.
- OAI multi-UE grid (2026-10-27): gate `scripts/native/run-ocudu-oai-multi-ue.sh` of the branch with local knobs `OAIMUE_BW_MHZ` (20/50/100: 51/133/273 PRB at 30 kHz, gNB-derived SSB ARFCN 632256/631296/634464, UE `--ssb` computed from point A, 50 MHz 30 kHz entries added to the OAI UE capability), `OAIMUE_UE_COUNT` (2/4: veth, netns, ports 2100–2107, quad subscriber list) and `OCUDU_NATIVE_GNB_ACCELERATION` (CUDA stanza as `render-cuda-1x1-configs.py`), plus `OCUDU_NATIVE_MUE_SKIP_CTEST` (the tree's `cpu_parallel` ctest fails on this box and is unrelated); CUDA runs wrapped in `scripts/cuda/with-cuda-mps.py`; patched OAI ZMQ module via `OCUDU_NATIVE_OAI_SHLIBPATH=builds/oai-zmq-patched`. Patch `~/ocudu-work/share/ranb-oai-multi-ue-bw-knobs-2026-10-27.patch`; runs `/workspace/gpuch/bound/oaimue/` (campaign.sh, runs.tsv, summ.py), reports `results/reports/ocudu-oai-multi-ue/20261027T06{4204,4505,4626,4927,5229,5531,5832}Z, …07{0134,0429,0725,1021,1325}Z`. The srsUE 50 MHz attempt (runner knob `SINGLE_CELL_BW_MHZ`, patch `ranb-cuda-gnb-and-bw-knobs-2026-10-27.patch`) stops in srsUE itself: its LTE PRACH library is capped at a 2048-point FFT, and lifting the cap (`srsue-prb270-attempt-2026-10-27.patch`, reverted) moves the crash into the 270-PRB OFDM reconfiguration, so srsUE stays a 20 MHz UE here.
- Caveats: one seed and one scene per axis; 30 s measurements; the emulator-boundary points use a synthetic 8-tap TDL and synthetic radios (no HARQ, no traffic), so they bound the channel alone, and their 20 s single runs vary by about ±0.05 at the edge (24 UEs: 0.62–0.75 across days and placements, 0.87 twice with four I/O threads); srsUE reports a constant CQI, so DL link adaptation is HARQ-driven only; the 2x2 rows use a unitary channel; the GPU-sharing and 5090 numbers are from September runs of the same code base, not repeated today.
