# Remaining radio-progress deficit — RTX 5090, 13 October 2026

Channel computation has ample typical headroom. The remaining slowdown occurs primarily around IQ handoff: the broker waits for input samples or for output space, and its bounded catch-up policy converts sufficiently long pauses into lasting radio-time lag.

These are instrumented diagnosis runs, not replacements for the scheduler-delay values on page 14. Hardware, CPU allocation, traffic, channel scenario and the disabled srsUE receive sleep match the [corrected scheduler comparison](../scheduler-broker-paced-20261013/README.md).

## Results

| Policy | gNB processed-IQ progress | Lost radio progress | Pacing debt discarded | Adjustment in wait-dominated iterations |
|---|---:|---:|---:|---:|
| RR | 99.8898% | 132.243 ms | 131.488 ms | 98.3% |
| QoS | 99.8971% | 123.506 ms | 123.619 ms | 97.0% |

The final column groups each pacing adjustment by the largest stage in that interval: waiting for input samples or for output space. It is not a causal allocation of individual microseconds. Endpoint phase accounts for the difference between lost progress and discarded pacing debt. The independent gNB scheduler logs agree, at 998.908 and 998.971 slots/s.

Measured channel-call durations include CPU preparation, CUDA submission/waiting, GPU work and output handling:

| Policy | Receiving node | Calls in measurement | Median, ms | p99, ms | Maximum, ms | Calls above 1 ms |
|---|---|---:|---:|---:|---:|---:|
| RR | gnb0 | 138138 | 0.090 | 0.320 | 0.945 | 0 |
| RR | ue0 | 119868 | 0.074 | 0.324 | 0.921 | 0 |
| RR | ue1 | 119868 | 0.074 | 0.330 | 0.842 | 0 |
| QOS | gnb0 | 137140 | 0.092 | 0.309 | 2.172 | 4 |
| QOS | ue0 | 119877 | 0.074 | 0.322 | 1.623 | 1 |
| QOS | ue1 | 119876 | 0.074 | 0.323 | 2.110 | 5 |

Most calls have substantial headroom, but **the channel program does occasionally pause beyond 1 ms**. In QoS, the ten calls above 1 ms across all three receivers include both off-CPU time and time spent inside host CUDA submission/waiting. The trace does not pinpoint the driver or OS event behind these tails. CUDA event intervals spanning the kernel stage have medians around 13 µs and p99 around 43–51 µs; these intervals can include gaps between submissions and are not exclusive GPU busy time.

The broker can process partial batches. After grouping processing costs into consecutive 23040-sample intervals, gNB p99 is 0.370 ms RR / 0.366 ms QoS; the estimated cost exceeds 1 ms once in RR and five times in QoS. The two UE receivers have zero such cases in RR and one/five in QoS. These rare processing tails do not explain most of the accumulated radio-time deficit.

A corroborating [RR gNB log excerpt](rr-gnb-pause.log) shows a 7.114 ms gap between consecutive scheduler slots. The matching broker iteration spent 5.233 ms waiting for output space and 0.097 ms processing the channel. This locates a pause at the IQ exchange boundary, without identifying the thread that initiated it.

Both runs delivered every scheduled traffic packet after drain, with no queue overflow, sequence gap or ZMQ error. Full-run input-starvation counts were 8 RR / 13 QoS, so strict zero-starvation qualification remains failed. No IQ-discard mechanism was added or observed.

## Measurement

Per-node traces record every producer iteration: sample count, monotonic timestamps at stage boundaries, actual pacing deadline, and CPU time spent in the channel call. Records are buffered in memory and written after processing stops; no per-call file writes occur. Instrumentation adds measurement overhead and does not alter pacing, sample values, CPU placement or radio settings.

The inspected 120-second intervals start at the traffic measurement anchor. For each receiving node, sample progress and elapsed time are compared at the same producer charge timestamps. The analysis independently reconstructs the deadline recurrence and verifies, exactly in integer nanoseconds:

`elapsed time − charged sample duration = discarded pacing debt + endpoint phase difference`

Discarded pacing debt means time that is no longer eligible for catch-up. It does not mean discarded IQ samples. All receiver nodes are measured independently; their deficits must not be added together.

The stage attribution identifies the largest measured stage in each interval that ends with a pacing adjustment. It is a description of where the broker was waiting, not a causal assignment to a particular gNB/UE thread or operating-system event. Waiting for input includes broker puller scheduling and transport delays; waiting for output space includes output delivery and peer consumption.

Nominal-slot processing costs are estimated by splitting fragment-call time in proportion to the number of samples in each consecutive 23040-sample interval. This avoids treating a tiny fragment as a full 1 ms slot. The estimate is not a physical timing measurement of each individual sample.

## Reporting correction

The old `event=process_latency_summary max_us` was invalid: its percentile helper selected rank `count`, then required the cumulative count to exceed that rank. This can never happen, so the helper always returned the 5005 µs fallback. Previous 5.005 ms maxima are not evidence of a slow call.

The summary now uses the exact maximum already recorded by `ReceiverTimingAccumulator`. A regression compares the printed value with the existing receiver telemetry after real loopback processing. The regression rejected the original source with the expected maximum mismatch. After the fix, all 13 RTX CTest cases passed; [mutation evidence](mutation-test.log), [test results](fixed-tests.log), and [fix](reporting-fix.patch).

## Limits

Typical channel-call duration does not prove that every deadline is met. The strict zero-starvation gate remains separate from successful attachment and complete packet delivery. The traces do not identify the particular radio-stack or OS mechanism initiating each IQ-handoff pause. No real-time priority or pacing-policy changes were made.

## Evidence and reproducibility

- RR: `20261013T110621Z`, [analysis](rr/analysis.json), [run settings](rr/run-parameters.json), [gate](rr/gate-summary.json), [raw trace/log hashes](rr/raw-hashes.json).
- QoS: `20261013T111356Z`, [analysis](qos/analysis.json), [run settings](qos/run-parameters.json), [gate](qos/gate-summary.json), [raw trace/log hashes](qos/raw-hashes.json).
- [Analysis program](analyze.py), [source hashes before instrumentation](source-hashes.json), [diagnostic header](diagnostic_trace.h), [RR instrumentation](instrumentation-v1.patch), [QoS instrumentation](instrumentation.patch), [summary](summary.json).

Each run used one cell, one CUDA broker, two UEs, RTX 5090, Core Ultra 9 285K, 20 MHz, 15 kHz SCS, 23.04 MS/s, 23040-sample maximum batches, seed-1 moving robot-ring channels, 10 Hz updates and the matched mixed traffic described in the preceding report. The gNB uses cores 0–7, both UEs 8–19, broker 20 and auxiliary processes 22–23. CPU sets, normal OS scheduling and broker pacing were unchanged.

Apply the diagnostic patch to the matching source and place `diagnostic_trace.h` in `src/`. QoS instrumentation was generated after applying `reporting-fix.patch`. Run the existing single-cell launcher with `OCUDU_NATIVE_SB_UE_RX_SLEEP=false` and `OCG_DIAG_TRACE_DIR` pointing to a directory writable from the launcher's user namespace. Verify write access from that namespace before starting. Every trace must remain below its 500000-record capacity; the analyzer checks capacity, count matching and the deadline recurrence.

RR has complete producer traces for all nodes but GPU substage data only for UE0; missing GPU data are explicitly marked and excluded. An intervening QoS run, `20261013T111018Z`, completed traffic but could not create trace files under the isolated namespace; it is excluded from this analysis. The repeated QoS run has matching producer/GPU records for every node. Directory permissions were corrected before that run; radio settings were unchanged.

The monotonic-to-wall-clock mapping changed by only 3 ns between checks. Source and raw trace hashes are preserved; the large binary traces remain in the dedicated RTX validation workspace. Temporary instrumentation was removed from the source mirror, which now matches the local source with only the validated maximum-reporting correction. The dedicated container was stopped after validation; unrelated containers were left running.
