# Channel and radio-runtime load audit — 13 October 2026

**There is no evidence of sustained channel compute overload, but zero-starvation and zero-delay qualification fails.** Both single-cell runs contain short IQ delivery pauses. The channel has typical compute headroom, yet records input starvation and rare processing calls above 1 ms. OCUDU also pauses before supplying TX IQ; srsUE TX waits largely overlap outstanding downlink requests. These observations do not establish the ultimate PHY/OS cause.

## Matched setup

RR (`20261013T112417Z`) and QoS (`20261013T112921Z`) ran sequentially on RTX 5090 / Core Ultra 9 285K (24 physical cores), one cell and two UEs each. Each measurement lasts 120 seconds, followed by six seconds of traffic drain. Radio settings are 20 MHz, 15 kHz SCS, 23.04 MS/s and 23040-sample maximum channel batches (1 ms). Both use seed-1 moving robot-ring Sionna channels, 10 Hz updates and 40 dB AWGN.

CPU affinity is gNB 0–7, both UEs sharing 8–19, channel broker 20, auxiliary processes 22–23. Core 21 is unused by the single-cell radio setup. The broker remains paced; the additional srsUE receive sleep is disabled. Normal OS scheduling is unchanged. Bulk traffic is DL 40 Mb/s and UL 2 Mb/s; the second UE carries 12 Mb/s on/off video and 200-byte control packets at 100 Hz in each direction. See the preserved run settings for both runs.

These instrumented runs diagnose timing. They do not replace page 14's scheduler comparison or constitute a new policy-performance ranking.

## Channel findings

| Measurement | RR | QoS |
|---|---:|---:|
| Broker CPU use, equivalent cores / one assigned | 0.593 | 0.592 |
| gNB processed-IQ progress / wall time | 99.8595% | 99.8680% |
| Radio-time lag accumulated over approximately 120 s | 168.573 ms | 158.395 ms |
| Pacing debt discarded | 168.230 ms | 157.698 ms |
| gNB receive-channel processing p99 | 0.332 ms | 0.317 ms |
| gNB receive-channel processing maximum | 3.021 ms | 2.280 ms |
| gNB channel calls longer than 1 ms | 2 | 8 |
| Full-run input starvation events | 15 | 9 |
| Full-run TX queue overflow / sequence gap / ZMQ error | 0 / 0 / 0 | 0 / 0 / 0 |

A starvation is counted once per wait episode when a previously active producer has no incoming samples for more than five maximum-batch durations: **5 ms here**. The broker waits for real IQ; this counter does not mean it discarded samples or substituted zeros. Stop counters cover the full live process lifetime, including outside the traffic measurement window.

Processing includes host preparation, CUDA submission/waiting and output handling. The UE receive-channel processing p99 is also below 0.337 ms, with rare maxima of 1.722–2.766 ms. There is substantial typical headroom, but these tails prevent a claim that the channel always finishes within 1 ms. Partial batches are possible; the attached channel analysis also estimates costs per nominal 23040-sample interval.

Most pacing adjustments occur in iterations dominated by waiting for input IQ or output space. Discarding pacing debt reduces permitted catch-up; it does not discard IQ. The analyzer checks the exact integer-nanosecond relationship between elapsed time, charged sample duration, pacing debt and endpoint phase. Consequently, the approximately 0.14% shortfall is measured radio-time lag, not an inferred CPU-utilization percentage.

## OCUDU and srsUE findings

| Measurement | RR | QoS |
|---|---:|---:|
| OCUDU CPU use, equivalent cores / eight assigned | 1.403 | 1.422 |
| OCUDU radio-thread CPU use | 97.3% of one core | 97.6% of one core |
| UE0 / UE1 CPU use, equivalent cores | 0.819 / 0.436 | 0.830 / 0.463 |
| OCUDU scheduler maximum reported decision latency | 0.624 ms | 0.251 ms |
| OCUDU MAC DL maximum reported latency | 3.693 ms | 2.205 ms |
| OCUDU accepted TX request → IQ send, maximum | 9.712 ms | 7.315 ms |
| Broker IQ send completion → OCUDU receive completion, maximum | 9.232 ms | 3.664 ms |
| Broker request → srsUE TX request acceptance, maximum across UEs | 10.328 ms | 6.224 ms |
| srsUE accepted TX request → IQ send, maximum across UEs | 1.201 ms | 0.059 ms |

CPU use is actual per-thread execution time sampled from `/proc/.../schedstat`, summed per process. OCUDU's radio thread continuously polls ZMQ, so its nearly full core does not by itself establish useful-work overload. Aggregate headroom also cannot rule out a serial-thread bottleneck or brief scheduling delays. Both UEs share twelve cores; their combined mean use is approximately 1.26–1.29 cores.

Socket timestamps locate pauses at IQ boundaries. An interval from send completion to receive completion includes ZMQ internal delivery and process scheduling; it is not exclusively receiver computation. OCUDU's TX request-to-send interval includes waiting for outgoing IQ from its internal buffer.

The QoS trace adds polling-gap observations. During **all eight OCUDU TX waits above 5 ms**, its radio thread successfully handled receive-side calls. During the longest 7.315 ms TX wait, it handled eight RX calls and had no RX polling gap above 1 ms. This supports delayed outgoing-IQ availability while the radio thread remained active. It does not identify which PHY worker or upstream dependency delayed that IQ. TX-port polling gaps alone are not scheduler stalls: OCUDU intentionally stops receiving new TX requests while waiting to answer the accepted request. [Correlation evidence](qos/gnb-poll-correlation.json).

For every srsUE TX request-acceptance delay above 5 ms, 99.1–99.8% of the interval overlaps a pending downlink IQ reply. This supports propagation through the radio pipeline rather than independent sustained UE CPU overload. It is not proof that srsUE contributes no delay.

Across 119 in-window OCUDU metric reports per run, error indications and late DL/UL HARQ counters are zero. Timestamped internal logs contain no runtime RF-failure, overflow, underflow or task-enqueue-failure messages in the measurement windows. However, failed UL PDCCH allocation attempts total **118 RR / 162 QoS**. Source inspection confirms these are per-report radio-control resource allocation attempts, reset each report; they are not CPU deadline counters.

The srsUE gateway's narrow `Stack latency` metric has maxima 2.420 ms RR / 3.684 ms QoS for UE0. This is not full PHY or end-to-end processing latency. Its RF overrun/underrun/late CSV counters are all zero, but the ZMQ backend's `rf_zmq_register_error_handler` is a no-op, so these zeros cannot certify RF timing. OCUDU's ZMQ RX `receive()` also waits on an empty buffer without issuing an underflow notification. Boundary traces are necessary to expose such waits.

## Delivery and qualification

RR delivered all 652153 scheduled packets. QoS delivered 652152: one of 12000 downlink control packets was absent after drain; other flows completed, with no duplicates or unknown sequence numbers. Its loss location is unresolved. Both UEs stayed attached and both launcher gates passed, but those gates do not require zero starvation or perfect packet delivery. **They are not strict real-time passes.**

No detected channel queue overflow or sample-sequence gap is good evidence against those particular failure modes. It does not justify a blanket statement that the channel and radio stacks have no underflow, overload or delay. Low utilization itself is normal; the relevant failure is inability to supply IQ when required.

## Instrumentation and limits

Temporary producer/GPU traces use the [preceding pacing diagnostic](../scheduler-pacing-trace-20261013/README.md). The additional LD_PRELOAD observer timestamps ZMQ send/receive boundaries without changing payloads or return values. It uses preallocated mapped storage; all completed REQ/REP transactions match in order and byte count, with at most one unfinished shutdown transaction per port, and zero dropped trace records. Payload content was not independently captured. RR uses [v1](wire_trace-v1.c); QoS uses [v2](wire_trace.c), adding polling gaps and slow failed nonblocking calls. The v1 request/reply smoke check passed 100 exchanges with unchanged payloads; v2 compiled with `-Wall -Wextra -Werror`, and all live transaction checks passed.

A 50 ms observer sampled native threads on auxiliary cores. Kernel scheduler-wait accounting is disabled (`sched_schedstats=0`): execution-time counters remain usable, but zero runqueue-wait fields cannot prove absence of OS scheduling delay. Logging calls occasionally take approximately 3 ms; none of the recorded `fwrite` calls exceeded 5 ms. This does not establish logging as the cause.

Instrumentation adds overhead, including extra timestamp reads on the busy-polling thread. Some RR postprocessing also ran on the host while QoS was active, so this is not a strictly isolated performance comparison. No causal scheduler-policy comparison is claimed. Native source pins remain OCUDU `a1916edcdbcd70ba6e0af47ee87be061dad5a4e4` and srsUE fork `eea87b1d893ae58e0b08bc381730c502024ae71f`, with existing locked local patches.

## Evidence and cleanup

- RR: [channel analysis](rr/analysis.json), [socket and CPU analysis](rr/wire-analysis.json), [stack counters](rr/stack-counters.json), [run settings](rr/run-parameters.json), [gate](rr/gate-summary.json), [benchmark](rr/benchmark-report.json), [raw hashes](rr/raw-hashes.json).
- QoS: [channel analysis](qos/analysis.json), [socket and CPU analysis](qos/wire-analysis.json), [stack counters](qos/stack-counters.json), [run settings](qos/run-parameters.json), [gate](qos/gate-summary.json), [benchmark](qos/benchmark-report.json), [raw hashes](qos/raw-hashes.json).
- Programs: [socket analyzer](analyze_wire.py), [channel analyzer](analyze_channel.py), [stack-counter extraction](stack_counters.py), [CPU observer](observe.py), [smoke check](smoke.c).

Raw traces and native logs remain on RTX under `validation/scheduler-20261013/runtime-audit/{rr,qos}` and the corresponding native run IDs. Published polling events retain all gNB RX-port gaps and gaps above 5 ms; full event lists remain remotely. Reproduction uses the same native launcher, `OCUDU_NATIVE_SB_SINGLE_CELL=1`, `OCUDU_NATIVE_SB_UE_RX_SLEEP=false`, `OCG_DIAG_TRACE_DIR`, `OCG_WIRE_TRACE_DIR` and `LD_PRELOAD` pointing to the compiled observer.

Temporary channel instrumentation was removed and the validation mirror restored to the canonical source hashes. The restored build passed all 13 RTX CTest cases. The dedicated experiment container was stopped; thirteen unrelated containers were preserved. No native-stack source or slide artifacts were changed by this audit. The next diagnostic target is OCUDU's PHY-to-TX-buffer availability during the identified pauses; source-level worker traces would be needed to establish the initiating cause.
