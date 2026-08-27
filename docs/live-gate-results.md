# Live gate results

Measured results for every gate in `scripts/remote/`, recorded so a reader can
see what has actually been demonstrated rather than inferring it from the fact
that a script exists.

**Host**: Intel Core Ultra 9 285K, one RTX 5090 (32 GB), driver 580.173.02,
CUDA 12.8.93, Ubuntu 24.04.
**Date**: 2026-08-19, with the multi-UE rows re-measured through `d00e84e`.
**Branch**: `minwooeun-rank1-miso-simo-review-fixes`.
**Stack**: OCUDU gNB + Open5GS 5GC + srsRAN_4G srsUE, all containerised, driven
through the CUDA broker. Every gate was run from a clean `git clone` of the
branch with only `.config` added.
**srsUE base**: single-UE gates run `release_23_11`. Multi-UE gates run the
latest `zhouyou-gu/srsRAN_4G` master (`SRSRAN_4G_REPO` / `SRSRAN_4G_REF`), which
is what `release_23_11` needed to be replaced by — see the root cause below.

Every srsUE keeps `nof_antennas = 1`. All claims are rank-1 MISO/SIMO.

## Single-UE gates

| Gate | Result | Live y=Hx |
|---|---|---|
| `ocudu-attach-smoke.sh` (1×1) | **pass** | n/a |
| `ocudu-rank1-2x1-smoke.sh` (2T2R) | **pass** | UL rows 4.59e-05 / 2.06e-05 · DL row 4.86e-08 |
| `ocudu-rank1-4x1-smoke.sh` (4T4R) | **pass** | UL rows 4.54 / 2.16 / 1.68 / 2.76 e-05 · DL row 4.86e-08 |

All with RRC connected, PDU session established, user-plane ping landing, and
`tx_queue_overflows = tx_sequence_gaps = zmq_errors = 0`.

The uplink rows reproduce the figures originally reported from the native
harness (4.6 / 2.2 / 1.7 / 2.8 e-05) row by row, on different hardware, a
different 5GC deployment and a different container stack.

## Multi-UE gates

Two or more srsUEs on one multi-antenna cell. Every gNB receive row is then the
sum of all the UEs' uplink columns, and the matrix checker reconstructs each row
from all incoming links, then removes them one at a time and requires the match
to break.

| Gate | UEs | Result |
|---|---|---|
| `ocudu-multi-ue-smoke.sh` (1T1R) | 2 | **pass** |
| `ocudu-rank1-2x1-multi-ue-smoke.sh` (2T2R) | 2 | **pass** — rows 4.54e-05 / 4.53e-05; removing either UE breaks the match by 91.3 to 236.9 |
| `ocudu-rank1-4x1-multi-ue-smoke.sh` (4T4R) | 2 | **pass** — rows 6.76 / 5.33 / 2.91 / 3.99 e-05 |
| `ocudu-rank1-2x1-triple-ue-smoke.sh` (2T2R) | 3 | **unrecorded** — the blocker below is fixed, but this gate has not been re-run since |
| `ocudu-rank1-2x1-quad-ue-smoke.sh` (2T2R) | 4 | **unrecorded** — fixture reset in `6a6e136`, not re-run since |
| `ocudu-rank1-4x1-quad-ue-smoke.sh` (4T4R) | 4 | **pass** — 4/4 attach on the first RA attempt; rows 7.9 / 6.7 / 5.1 / 5.4 e-05, every leave-one-out breaks by ~1e+02 |

Control experiments used for the diagnosis below, not gates:
`examples/topology.ocudu-docker.multi-ue-quad.cuda.yaml` (stock single-antenna
cell, four UEs) and `examples/ocudu/gnb_zmq_b210_fdd_1t1r_mimo_settings_bisect.yaml`
(single antenna carrying the MIMO cell settings).

The 2×1 three- and four-UE gates are committed as reproducible investigations.
Their blocker is fixed (below), but neither has been re-run since, so they carry
no recorded result. Do not cite them as demonstrated capability until they do.

## Why three and four UEs did not attach

**Root cause: srsUE `release_23_11` transmits preamble index 0 no matter what,
and does not enforce contention resolution.** Every UE therefore derived the
same RA-RNTI, decoded the same random access response, and the UEs that lost
contention reported a successful attach and stopped retrying. Three processes
logged `RRC Connected` on one identity while only one held a PDU session.

**Fix** (`6a6e136`): build srsUE from the latest `zhouyou-gu/srsRAN_4G` master,
which corrects the false-attach behaviour and adds a `SRSUE_PRACH_PREAMBLE_INDEX`
override, and give each UE its own contention-based preamble.
`SRSRAN_4G_REPO` / `SRSRAN_4G_REF` make the base overridable. Every UE then
attaches on its **first** attempt with its own C-RNTI, PDU session and IP, on
the stock fixtures with no raised `preamble_trans_max`.

Two further defects were removed on the way, both in the harness:

- **Malformed IMEI from the second UE onward** (`23244a0`). The N-UE
  generalisation built each IMEI as `printf '35349006987331%d'` with `(9 + i)`,
  giving 16 digits from `ue1` on. Zero-padded back to 15. Measured, this was
  *not* the blocker — with correct IMEIs the result was unchanged at one UE of
  four — but a malformed IMEI presents exactly like a contention failure, so it
  is worth not having in the picture.
- **A per-UE wait for a PDU session in the launch loop** (`6a6e136`). A
  destination cannot advance until every incoming edge has data, so the cell
  produces nothing until the LAST UE's radio is running; the earlier UEs cannot
  attach yet by construction and each wait burned its full timeout. At four UEs
  with a 40 s wait the last UE launched at ~156 s against the gate's own 150 s
  duration: the broker stopped with `tx_pulls=9`, having relayed nothing, and no
  UE ever transmitted a preamble.

**What this does not fix.** The lifecycle defects the investigation uncovered
are real and still unfixed — the cell cannot run until every declared peer's
radio is live, and a late-joining lane replays its peer's backlog. The preamble
fix means multi-UE gates no longer *depend* on them, not that they are solved.
They are documented from "Why the cell waits at all" onward, and tracked as V3
in [`../RANK1_REVIEW_MILESTONES.md`](../RANK1_REVIEW_MILESTONES.md).

### The investigation, and what it cost to get here

The narrative below is kept because four of its conclusions were wrong and each
was disproved by a specific measurement. Read it as history plus a description
of the two open lifecycle defects, not as current status. The delay-based
explanation in particular has been **reverted** — see
"Corrections to earlier explanations".

### The three defects, separated

Running the delay fix together with a cold-source broker change (a node advances
while a peer has never connected, treating it as silence) isolates the remaining
work cleanly:

```
ue0  c-rnti=0x4601  RA=1    rrc=1  pdu=1  ip=10.45.1.2   <- clean attach
ue1  c-rnti=0x4601  RA=1    rrc=1  pdu=0                 <- decoded ue0's RAR
ue2  c-rnti=0x4601  RA=1    rrc=1  pdu=0                 <- same
ue3  RA=200, no c-rnti                                   <- never detected
PRACH: 1   detected_preambles=[{idx=0 ta=0.00us detection_metric=86.9}]
```

Detection is strong again (86.9, not the 3.6 seen without the broker change) and
the first UE attaches properly. So three independent defects, not one:

| # | Defect | Status |
|---|---|---|
| 1 | Identical propagation delay collapses all preambles into one peak | **fixed**, this commit |
| 2 | A cell cannot run until every UE's link is live | fix works but trips `tx_queue_overflows` |
| 3 | A late-joining lane replays its peer's backlog and jams | **unsolved** |

Defect 3 is why defect 2's benefit stops at the first UE. A lane that goes live
after the node has started keeps its cursor at 0, so the node replays that
peer's stream from its first sample. Under the real-time throttle the backlog
never shrinks: the ring pins at capacity (measured 2396160/2457600 with over a
million puller room stalls), the puller stalls, and that UE's srsUE blocks in
`tx()` before its preamble reaches a slot the gNB reads.

Three cursor policies were tried for it and none is right:

| Policy | Result |
|---|---|
| Replay from sequence 0 | ring jams at 97%, UE freezes |
| Snap to the live frontier | discards the startup head start; relay stalls at `tx_pulls=6` |
| Snap only once the node has produced | `tx_queue_overflows` 317, still one PRACH |

The head start matters because it is the lock-step radios' only timing slack --
the epoch co-init comment in `broker.cpp` warns of exactly this. The likely
correct answer is re-establishing a *common* epoch across all lanes when a
participant joins, rather than patching one lane's cursor, which is a design
decision about what a running cell does when a new radio appears and is left
open deliberately.

### Defect 3, and the symmetric wall behind it

Combining the delay fix with cold-source admission and a late-joiner cursor snap
does clear the ring jam -- the late UEs' rings drop from 2396160/2457600 with
over a million room stalls to 46096/2457600 with **zero**. But the pressure only
moves to the other side of the same loop:

```
gnb0_p0 ring=2442540/2457600  room_stall=2120691  state=wait_room
```

A UE node whose radio has not launched still processes downlink into a receive
ring nobody drains. It fills, that node stalls on `output_room`, stops consuming
the gNB's transmit ring, and back-pressures the gNB itself.

The symmetric fix -- a sink with no listener discards instead of blocking -- was
implemented and **fails on a contract the existing tests defend**. `test_broker`
rejects it immediately:

```
multi-ue lockstep: tx_pulls=6 rx_requests=0 gnb_received=0
FAIL: broker served no RX requests (multi-device relay dead-locked)
```

The reason is that the sink side has no equivalent of the source side's
`next_sequence() == 0`. "Has not requested yet" and "will never request" look
identical, and a radio that starts slowly would silently lose its first samples
-- which is exactly what the test is there to prevent. On the source side the
distinction is decidable; on the sink side it is not, without something outside
the ring telling the broker whether a peer is expected at all.

That is the shape of the remaining work: the topology already declares which
peers exist, so the broker could be told which endpoints to expect and treat an
unconnected-but-declared sink differently from a slow one. That is a schema and
lifecycle change, not a patch to the room calculation, and it is left open
rather than guessed at again.

(Implementation note for whoever picks this up: `rx_headroom()` takes
`rx_mutex`, so any headroom check made while already holding that lock must be
computed inline or it self-deadlocks. That cost a hung `test_broker` run.)

### Why the cell waits at all, and what would remove the wait

Two waits chain together, and neither is fundamental.

**The emulator waits** because a node sizes its slot as
`common = min(avail)` over every incoming lane: to compute `y = SUM H*x` it
needs a sample from every source at the same instant. That is correct for
coherence, but `avail == 0` cannot distinguish a peer that is momentarily caught
up from one that has never existed.

**The gNB waits** because the broker holds a receive request until the node has
produced. So the emulator's internal coherence rule propagates outward and stops
the radio's transmit path, since a lock-step radio blocks in receive until
answered.

Everything else in this section follows from those two. The evidence that they
are not fundamental is that the topology already names every peer: the broker
could be told which endpoints to expect and treat "declared but not yet
connected" as a first-class state, distinct from "connected and briefly idle".
That is the change that would remove the wait. It is a lifecycle and schema
change, not a patch to the window calculation.

### What was measured while trying to remove it

Four broker variants were built and reverted. Each is recorded with the
measurement that killed it, because each looked correct in isolation:

| Variant | Result |
|---|---|
| Cold source contributes silence | cell runs from the first UE, ue0 attaches with a PDU session; later UEs jam |
| + late-joiner cursor snapped to frontier | ring jam cleared (2396160 -> 46096, room stalls 1.3M -> 0), `tx_queue_overflows` 0; still one PRACH |
| + cold sink discards when nothing listens | `test_broker` fails outright: "broker served no RX requests" |
| + cold sink trims to one batch of air | ctest passes, `tx_queue_overflows` returns (395); still one PRACH |

The last two exist because of a distinct defect worth recording on its own: a
port whose radio has not connected accumulates downlink history, and when that
radio finally starts it is served minutes-old air. A late UE decoded an EARLIER
UE's random access response out of that backlog and logged

```
Random Access Complete.  c-rnti=0x4601, ta=0
```

with the same C-RNTI as the first UE and `ta=0`, despite its own link carrying a
16-sample delay that would have produced `ta≈32`. It never transmitted a
detectable preamble, and it stopped retrying because it believed it had
attached. Any fix for multi-UE has to bound that staleness as well as the
stall.

### What was confirmed to work at the time

Both items below were measured, and both were **superseded** by the preamble
fix. They are kept because they bound what the delay experiment did and did not
show.

- **Equal transmit power matters once delays separate the UEs.** An earlier
  near/far spread of 16 dB pushed the far UEs to `power_dB -3.61` and
  `detection_metric 3.9`, against 15.14 and 86.8 for the near UE. The spread was
  removed in `aedf56d` and has not been reinstated.
- **Simultaneous launch with distinct delays attached a UE that was not the
  first**: ue3 reached `c-rnti=0x4603`, a PDU session and IP 10.45.1.5, which no
  earlier configuration achieved. It still did not attach all four.

### Corrections to earlier explanations

Four explanations were published in this branch before this one and are all
wrong. They are recorded because each was disproved by a specific measurement:

- *"Identical propagation delay is why the gNB saw one preamble, and distinct
  delays are what separates UEs."* Published in `7c97b33`. The premise was that
  srsUE always sends preamble index 0, so timing advance is the only thing that
  separates UEs at the receiver. `6a6e136` removed that premise: with a
  per-UE preamble index every UE attaches on its first attempt at identical
  delay. The distinct delays were then **reverted to identity in the quad
  fixture**, because they actively broke the matrix gate — a delayed carrier is
  not an identity carrier, so three of four users could not be reconstructed and
  their signal appeared as residual (`max |y - Hx| = 4.4e+02` against a 1e-04
  tolerance). Distinct delays did change the gNB's view (PRACH detections
  1 -> 204), which is why the explanation survived as long as it did; it was a
  real effect on the wrong variable.

- *"The gNB merges the preambles onto one C-RNTI."* It issues a fresh C-RNTI per
  detected preamble; `rnti_manager::allocate()` increments until it finds a free
  one, so it cannot reuse a registered RNTI. Only one preamble was ever
  detected.
- *"`ss2_type: ue_dedicated`, which multi-antenna downlink forces, is the
  blocker."* Reverting it appeared to fix four UEs, but the C-RNTIs show three
  of those four were the same UE and the PDU count stayed at 1. `ss2_type`
  changes only how the losers fail, not how many attach.
- *"The multi-source stall freezes virtual time, so UEs cannot be separated."*
  The stall is real, but UEs sharing an occasion is survivable when they are
  physically distinguishable; separation in time was never the binding
  requirement.

`RRC Connected` is not proof of attach: srsUE reports it even when it lost
contention resolution. Judge multi-UE results on distinct C-RNTIs and completed
PDU sessions.

## Synthetic control

Before any of the live multi-UE work, the superposition arithmetic was checked
in isolation: a 2-port gNB against two single-port synthetic peers, no RAN stack
involved.

```
gnb0 rx row0: max|y-(h_ue0*x0 + h_ue1*x1)| = 2.044e-07   [only ue0: 4.472e-01 | only ue1: 7.566e-01]
gnb0 rx row1: max|y-(h_ue0*x0 + h_ue1*x1)| = 1.077e-07   [only ue0: 6.265e-01 | only ue1: 2.915e-01]
```

The single-user hypotheses are wrong by 0.29 to 0.76, so the engine sums both
links per row rather than dropping one. The engine's multi-user support is
therefore not in question -- the blockage above is in the attach procedure, not
the channel.

## Other verification on this host

| Check | Result |
|---|---|
| `gpu-test-sequence.sh` | 9/9 pass |
| `ctest`, CUDA and CPU trees | 8/8 each |
| `ctest` under ASan + UBSan + LeakSanitizer | 8/8 clean |
| ThreadSanitizer, `ctest` plus a live relay | no race in project code; all reports inside uninstrumented libzmq |
| Synthetic y=Hx: 2×2, 2×1/1×2, 4×1/1×4, both backends | pass, all rows <= 1.44e-07 |
| CPU vs CUDA parity | identical row RMS on the same topology |

## Whole-run latency

Node process latency, every slot recorded (`event=process_latency_summary`),
from the live gates:

| Config | Node | n (slots) | p50 | p95 | p99 | p99.9 |
|---|---|---|---|---|---|---|
| 2×1 | gnb0 | 57,753 | 80 µs | 135 µs | 205 µs | 340 µs |
| 2×1 | ue0 | 54,794 | 75 µs | 150 µs | 230 µs | 380 µs |
| 4×1 | gnb0 | 54,439 | 115 µs | 200 µs | 285 µs | 675 µs |
| 4×1 | ue0 | 54,284 | 120 µs | 210 µs | 310 µs | 650 µs |

GPU kernel p50: 10.6 µs (2×1), 12.9 µs (4×1). Everything through p99.9 fits the
1 ms slot budget.

**The maximum is not measured, and the earlier reading of it was an artefact.**
An earlier edition of this section said the observed maximum in both
configurations landed in the 5 ms overflow bucket. It did not. `max_us` was
computed as `process_percentile_us(diag, 1.0)`, which asks the prefix sum for
`cumulative > total` — a condition no prefix sum can satisfy — so the search ran
off the end of the histogram and returned its fallback: the constant 5005 µs, on
every run, whether or not a single slot had ever overflowed. Reproduced directly
on this host: `test_broker` printed `max_us=5005 overflow_n=0`, a 5 ms maximum on
a run with an empty overflow bucket.

The percentiles are unaffected — p50/p95/p99/p99.9 were computed from a
satisfiable rank and stand as published. Only the maximum was wrong, and it was
wrong in the direction of alarm.

Fixed: the rank is clamped to `total-1`, the overflow bucket reports its lower
edge as documented, `overflow_n` is now printed alongside so the maximum can be
read as "at least" when it is non-zero, and `event=process_overflow` names the
slot index and full stage breakdown for the first 32 overflow slots. A
regression test in `test_broker` rejects a summary line whose percentiles are
not monotone, or which claims a 5 ms maximum with an empty overflow bucket.

The gates have **not** been re-run since. Until they are, this table's maxima
are unknown and no statement should be made about the tail beyond p99.9.
Tracked as V1 in [`../RANK1_REVIEW_MILESTONES.md`](../RANK1_REVIEW_MILESTONES.md).
