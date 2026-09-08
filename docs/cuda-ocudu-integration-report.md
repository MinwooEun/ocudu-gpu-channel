# OCUDU CUDA Integration Report

Date: 8 September 2026

The CUDA-enabled OCUDU gNB now completes UE attachment, PDU session establishment,
and gateway ping through the CUDA channel broker in the local 1×1 environment.
C0, C1, and C2 are complete. The final C3 configuration with all acceleration
options enabled and NVIDIA Multi-Process Service (MPS) passes the selected
functional, radio KPI, backend, and broker latency checks. Full C3 certification
remains incomplete because the six-stage campaign and the complete PHY test suite
have not both been repeated on the final revision.

This report records the integration work and existing measurements. It does not
claim a throughput improvement, strict realtime operation, or validation of
multi-antenna operation with the newly integrated gNB acceleration.

## Environment and measurement scope

| Item | Configuration |
| --- | --- |
| GPU | NVIDIA GeForce RTX 5090, compute capability 12.0, device 0 |
| Software | CUDA 12.8.93; driver 595.71.05; GCC 13.3.0; CMake 3.28.3 |
| CUDA OCUDU | WG branch `nvcuda_accel_02`, commit `5830c9cb7813393b5d518dd5ee2b6641071be4ad`, with the repository patch |
| CPU reference OCUDU | Commit `a1916edcdbcd70ba6e0af47ee87be061dad5a4e4` |
| UE and core | srsUE, srsRAN 4G commit `eea87b1d893ae58e0b08bc381730c502024ae71f`; Open5GS commit `d9d3abdd480be96fac3bc8a997e83446648763ca` |
| Topology | One gNB and one single-port UE, rank-1 1×1, ZMQ IQ transport |
| Sample rate | 23.04 MS/s |
| Channel | CUDA broker; one zero-delay TDL tap at −3 dB, followed by 0.125 rad phase rotation and 125 Hz carrier-frequency offset; no added AWGN |
| Run duration | 15 seconds of broker operation for the regression gate; 90 seconds for the separate KPI gate; initialization and cleanup add wall time |
| KPI window | 60 consecutive scheduler reports, approximately 64.38 seconds of wall time in the final comparison |

The CPU reference label describes the gNB profile. The channel broker remains
CUDA-backed in both reference and accelerated runs. These are comparisons of the
two pinned builds, rather than a same-source compiler-only experiment.

The final reviewed patch is
[`ocudu-cuda-host-grid-compat.patch`](../scripts/native/patches/ocudu-cuda-host-grid-compat.patch).
Its SHA256 is `8188ae4c9eae9ba822607f74ea8c72bc1af7d57161140841c6571e0835c84d68`.
The tested CUDA gNB binary SHA256 is
`68f49ea7035fbcda2445baf78af4f9268628cef28843dd0a7aacfab3248c3aa4`.
Measurements were taken from the working tree based on channel repository commit
`f2e02f96c6c9c73e5ad8c347effcfd19c1b9a8ea`; archived provenance also records
the source manifest, tracked diff, binary, and configuration hashes.

## Milestones

| Stage | Purpose | Status |
| --- | --- | --- |
| C0 | Build the pinned CUDA gNB separately and validate its CUDA PHY components | Completed on the initial compatibility patch; 12/12 tests passed |
| C1 | Integrate CPU/CUDA profile selection and provenance into the native runner | Completed; CPU regression, configuration parity, and CUDA preflight passed |
| C2 | Compare the CPU reference against the CUDA build with gNB acceleration disabled | Completed; all three interleaved pairs passed functional and ±5% p99 checks |
| C3 | Enable PHY acceleration cumulatively and compare functionality, KPIs, and latency | Final `all` configuration passed with MPS; complete post-fix certification remains pending |
| C4 | Proposed concurrent Sionna workload validation | Not executed; requires an explicit change to the current mission's Sionna exclusion |

### C0 and C1: build and runtime integration

The CUDA source and build directories are separate from the existing CPU build.
The build helper verifies the pinned source, exact reviewed patch, CUDA target,
test registration, and the gNB acceleration help output. A strict PHY log verifier
also checks printed verdicts because some upstream test programs return zero
even when their output reports failure.

Initial compatibility fixes restored SRS staging from ordinary host/pinned grids
and repaired PDSCH single-symbol compression when CPU access had migrated a
managed resource grid. The original 12-test suite passed in 866.94 seconds.
The PUSCH comparison covered 48 PRB/RX/SINR conditions with ten repetitions each:
maximum SINR difference was 0.1 dB, BLER difference was zero percentage points,
and decode agreement was 100%. The pipeline test reported zero payload mismatches
over 100 measured iterations.

`OCUDU_NATIVE_GNB_PROFILE=cpu|cuda` now selects the build through workspace checks,
the native runner, and artifact provenance. CPU remains the default. Validation
checks the selected source, patch, build settings, executable, and recorded hashes.
The C1 CPU gate passed attachment, session establishment, and all three pings;
rendered configuration parity and CUDA dependency preflight also passed.

### Accelerated startup and PUSCH correctness

CUDA PHY initialization could exceed the entire 15-second broker run. The runner
now waits for CUDA PHY initialization before starting the broker measurement
clock, with a bounded 120-second initialization wait.

The first accelerated uplink failure was traced to a GPU estimator that ignored
the configured time-interpolation strategy and always averaged. The patch carries
the strategy through the factory and constructor. A 400 Hz CFO regression checks
CRC and payload parity over ten transmissions: restoring the old averaging
behavior makes all ten GPU transmissions fail while the CPU reference passes.
The corrected revision passed the expanded 13-test suite in 883.18 seconds and
two accelerated live gates. That full-suite result predates the final C3 fixes.

### C2: reference comparison

Campaign `c2-20260908T125913Z` ran three interleaved CPU/CUDA-disabled pairs under
the environment and 15-second fixture described above.

| Pair | CPU p99, gNB/UE node (µs) | CUDA-disabled p99, gNB/UE node (µs) | Result |
| --- | --- | --- | --- |
| 1 | 81 / 81 | 80 / 84 | Pass |
| 2 | 82 / 81 | 81 / 81 | Pass |
| 3 | 83 / 83 | 81 / 82 | Pass |

All six runs passed attachment, PDU session, ping, and data-integrity checks.
The p99 differences were −2.41% to +3.70%, within the fixed ±5% limit.
An earlier campaign failed one comparison at −5.88%. Its original evidence was
preserved. The broker histogram was refined from 5 µs to 1 µs buckets because
5 µs resolution is too coarse for a ±5% comparison near 80 µs. The acceptance
limit was unchanged, and the entire three-pair campaign was repeated.

### C3: cumulative acceleration and final comparison

The stage renderer cumulatively enables lower-PHY RX, lower-PHY TX, PUSCH,
PDSCH, PRACH including lower-PHY PRACH demodulation, and finally SRS (`all`).
Forced lower-PHY acceleration selects managed grids to supply the required
device mapping. Two additional defects were repaired:

- The ZMQ sequential execution configuration has no codeblock executor. Explicitly
  enabled flexible CUDA PDSCH now receives an inline executor with concurrency one.
  The new factory regression passes; restoring the old condition aborts.
- The synchronous/UCI PUSCH path reported an EVM-derived estimate as SINR instead
  of the noise-variance SINR used by the reference path. The fix preserves EVM
  independently and reports the corresponding SINR. A negative control showed
  a 12.3 dB error despite correct payloads; the corrected regression reports
  CPU/GPU agreement to 0.0 dB at its printed precision.

The initial seven-run campaign, `c3-20260908T130332Z`, completed attachment and
60-report capture for the reference and all six stages. It failed SINR checks
from PUSCH onward and failed the broker latency comparison: accelerated p99 was
113–124 / 127–139 µs versus the CPU reference's 82 / 82 µs. These failed results
remain archived.

An isolated MPS experiment subsequently passed three 15-second CPU/all-enabled
comparisons. The reusable MPS wrapper records the server and clients, uses a
private control socket, and shuts down its own daemon after the command. Evidence
confirms that the gNB and broker shared that MPS server during accelerated runs.
The earlier direct-mode and later MPS campaigns also differ in the SINR fix, so
they do not isolate MPS as the sole cause of the latency change.

The final representative comparison, `c3-20260908T133003Z`, used the corrected
binary and MPS. Both runs lasted 90 seconds and yielded 60 consecutive reports.

| Metric | CPU reference | CUDA `all` | Comparison |
| --- | --- | --- | --- |
| Attachment / PDU session / ping | Pass | Pass | Pass |
| Mean report UL / DL BLER | 0% / 0% | 0% / 0% | Difference 0 percentage points |
| Mean reported PUSCH SINR | 1.310 dB | 1.645 dB | +0.336 dB; within ±0.5 dB |
| Mean UL / DL MCS | 5.783 / 26 | 6.533 / 26 | +0.750 / 0 |
| Broker p99, gNB / UE node | 82 / 82 µs | 83 / 82 µs | +1.22% / 0%; within ±5% |
| Broker processing observations, gNB / UE node | 79,611 / 78,460 | 79,241 / 78,933 | Nonempty whole-run histograms |
| Queue overflows / sequence gaps / ZMQ errors | 0 / 0 / 0 | 0 / 0 / 0 | Pass |
| RX starvations | 5 | 10 | Strict realtime not established |

BLER values are means of per-report values. Broker p99 measures broker processing
latency, not end-to-end radio latency or isolated gNB PHY execution time.
Runtime evidence confirms CUDA backend selection and exercised lower-PHY paths;
lower-PHY TX still logs host resource-grid staging. SRS factory selection is
confirmed, but scheduled SRS traffic is not established by this fixture.

The final machine-readable verdict is deliberately limited:

```json
{
  "functional_pass": true,
  "kpi_pass": true,
  "selected_stages_qualified": true,
  "full_c3_kpi_qualified": false
}
```

The final affected PUSCH CFO, synchronous SINR, and PDSCH tests passed 3/3 in
35.18 seconds. The build helper registers 14 PHY tests, but the complete 14-test
suite has not been rerun on this final patch.

## Reproduction

On the existing workstation, enter the prepared container from the host:

```bash
docker exec -it ocudu-minwoo bash
source /home/minwoo/ocudu-env.sh
cd /home/minwoo/ocudu-work/ocudu-gpu-channel
```

Run the verified all-enabled CUDA configuration with isolated MPS:

```bash
OCUDU_NATIVE_GNB_PROFILE=cuda OCUDU_NATIVE_GNB_ACCELERATION=all \
  python3 scripts/native/with-cuda-mps.py -- \
  bash scripts/native/run-ocudu-legacy-1x1.sh
```

Allow approximately one minute including initialization and cleanup. Success is
reported as `event=native_legacy_1x1_attach_gate result=pass`.

Repeat the representative CPU/all-enabled KPI comparison, allowing approximately
four to five minutes:

```bash
python3 scripts/native/with-cuda-mps.py -- \
  python3 scripts/native/qualify-cuda-stages.py \
  --stage c3 --metrics --acceleration all
```

These commands depend on the prepared native workspace and GPU environment.
The repository contains the patch and build/run tooling; native dependencies,
binaries, and raw measurement archives are stored separately. See the
[native runbook](../scripts/native/README.md) for setup and further commands.

## Evidence and remaining work

Evidence paths below are relative to `OCUDU_NATIVE_ROOT`, which is
`/home/hyunsoo/ocudu-native-workspace` inside the prepared container. The host
mount is `/home/minwoo/ocudu-work/ocudu-native-workspace`. These are local archives,
not files included in the Git repository.

| Evidence | Location |
| --- | --- |
| Initial build and C1 validation | `builds/ocudu-cuda-zmq-release/{c0-result.json,c1-result.json}` |
| Interpolation fix and full 13-test result | `builds/ocudu-cuda-zmq-release/accelerated-fix-result.json` |
| Final targeted fixes | `builds/ocudu-cuda-zmq-release/{c3-pdsch-fix-result.json,c3-sync-sinr-fix-result.json}` |
| C2 successful comparison | `results/cuda-qualification/c2-20260908T125913Z/` |
| Initial C3 failed comparison | `results/cuda-qualification/c3-20260908T130332Z/` |
| Final selected C3 comparison | `results/cuda-qualification/c3-20260908T133003Z/` |
| Final MPS server/client and cleanup records | `results/cuda-qualification/mps-20260908T133003.211558Z/` |
| Final CPU and CUDA raw KPI reports | `results/reports/ocudu-cuda-kpi/{20260908T133004Z,20260908T133148Z}/` |

Remaining certification work is to repeat all six C3 stages under MPS on the final
patch (approximately 12 minutes) and rerun the complete 14-test PHY gate
(approximately 15 minutes, potentially longer if rebuilding is required).
Higher traffic loads, sustained operation, multi-port gNB acceleration, and
scheduled SRS require additional experiments. C4's proposed Sionna concurrency
test requires an explicit mission scope amendment before execution.
