# cuda: zero-copy host memory for integrated GPUs (GB10, Jetson Orin)

Branch `gb10-zero-copy` (7 commits on top of `cuda-gb10-orin` / PR #2 head `a07b8a9`). Not pushed.

## What

- New knob `runtime.cuda_host_memory: auto | copy | zero_copy`, default `auto`.
  `auto` uses zero-copy only when the device reports `cudaDevAttrIntegrated`;
  a discrete GPU stays on the existing copy path.
- Zero-copy maps the per-slot IQ input/output buffers (`cudaHostAllocMapped`).
  Where the device has pageable memory access (GB10), kernels also read the
  caller's input spans through a source table and write the caller's output
  row directly, removing the host packing and output copies.
  Orin has no pageable access and uses the mapped input/output buffers only.
- `IqRing` push/read copy in at most two blocks instead of per-sample modulo
  (applies to the CPU backend too).
- Native multi-gNB attach gate (`scripts/native/run-ocudu-multi-gnb.sh`).

## Evidence

Output is bit-identical to the copy path (new parity tests, including a
3-source fan-in case; negative controls fail as expected).

| Platform | emulator call p50, mvp 2-edge | live broker p50 (legacy 1x1) |
|---|---|---|
| GB10 | 46.6 -> 25.9 us | 60-65 -> 40 us |
| GB10, gNB with 64 UEs | 934 -> 177 us | - |
| Jetson Orin (30 W) | 251 -> 183 us | 415-455 -> 345-360 us |
| RTX 5090 (`auto`) | unchanged (copy) | unchanged |

Details: `ZERO_COPY_MILESTONES.md` (Z0-Z8), `SPARK_MILESTONES.md` (S7).

## Fix included: prepare-time uploads raced the first slot

`prepare()` uploaded the initial node state (`device_row_begin`, correlation
groups, link states) with `cudaMemcpy` from pageable memory on the legacy
stream, while slots run on a `cudaStreamNonBlocking` stream. Under GPU
contention the first slot could read the state before it landed, and that edge
then ignored gain/phase/profile updates. The uploads now go on the node stream,
followed by a stream sync. The bug predates this branch (`a07b8a9`); with a
busy kernel in another process ctest went 0/30 -> 30/30.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
