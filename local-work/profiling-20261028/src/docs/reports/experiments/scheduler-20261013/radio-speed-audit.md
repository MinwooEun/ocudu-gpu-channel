# Radio speed and concurrency audit

Saved IQ counters confirm sample progress below real time. This is not an artifact of counting scheduler log lines.

| Run | Cell / policy | gNB IQ progress, MS/s | Nominal-rate fraction | Independently reconstructed slots/s |
|---|---|---:|---:|---:|
| 1 | A / RR | 21.0388 | 91.31% | 914.179 |
| 1 | B / QoS | 20.7854 | 90.21% | 905.768 |
| 2 | A / QoS | 20.9253 | 90.82% | 911.784 |
| 2 | B / RR | 20.7653 | 90.13% | 900.498 |

Nominal operation is 23.04 MS/s and 1000 slots/s. The broker's `acquired` counter counts complex IQ samples successfully copied from each radio TX reply into its input ring (`src/broker.cpp`). Differences between heartbeat elapsed seconds 60 and 130 give the rates above. All twelve per-port checks agree closely within their cell. Run 1 cell A, for example, advances 1,472,716,800 samples in nominally 70 wall-clock seconds.

Heartbeat time uses monotonic elapsed seconds truncated to integers. Even allowing a conservative 69–71 second interval, every rate remains below nominal. The independent scheduler check unwraps SFN/slot numbers and divides slot progress by wall-clock elapsed time inside the 120-second measurement; it does not count printed lines. The IQ check uses an interior window, so rates need not match exactly. See [counter excerpts, endpoints and priority warnings](radio-speed-audit.json) and the [audit script](audit-radio-speed.py), executed on RTX against saved native logs.

## Concurrency and interpretation

The two policy-swapped runs were sequential. Within each run both cells operated simultaneously: two gNBs shared cores 0–7, four UEs shared cores 8–19, brokers used 20 and 21, and auxiliary processes used 22–23. They also shared the GPU and host memory system. Separate RF topologies do not provide compute isolation.

Resource contention is plausible, but these logs do not establish the bottleneck or prove concurrency caused the slowdown. Cell B had higher bulk delay in both policy assignments, further limiting attribution to scheduler choice. A controlled one-cell-at-a-time comparison with identical CPU allocation, replayed channel settings and traffic, followed by a matched concurrent run, is needed to test this hypothesis. The current results do not establish standalone stack performance or a general scheduler ranking.

## Real-time operation

The broker was configured to pace samples at the nominal rate. Its pacer limits early delivery; it cannot guarantee timely production by every participant. ZMQ software radios advance through sample exchange without an independent hardware sample clock. Connectivity can therefore continue while sample progress falls behind wall time.

Every saved gNB console reports failed scheduling-priority requests for the worker pool and I/O thread. The experiment wrapper drops `CAP_SYS_NICE`; pinned OCUDU requests `SCHED_FIFO` for real-time priorities. No live per-thread policy snapshot was retained, so this audit does not claim to inspect every thread's effective policy. Enabling priority alone would not prove real-time performance or resolve the bottleneck.

The stack was intended to run at real-time pace, but achieved approximately 90–91% in this shared-resource experiment. Broker input waits also failed the strict zero-starvation criterion. These events are waits exceeding five batch durations, not a direct count of MAC deadline misses. No new experiment was run for this audit.
