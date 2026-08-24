# MIMO live demo — implementation plan

> **Status 2026-08-24 (second pass):** everything through S4 is implemented
> and gate-verified in `demo/` — S0, C1+S1, S2/S3 (bridge + page, buttons
> live), **L2 pilot alternation (measured |h_rc|² heatmap)**, C4 sweep, and
> the **1×4 SIMO steering demo** (`run-simo-demo.sh`, :8081) with A/B swap
> buttons — delivered via a ~0.3 s broker restart because `fixed_mimo` has no
> runtime swap message; the proper control-plane message is drafted in
> `docs/plans/fixed-mimo-swap.md` (needs Charles's review). The restart path
> also covers S6's broker-restart drill: the meter reconnects on its own.
>
> **Third pass (same day): S5 live-radio tier is running** —
> `demo/native/run-live-demo.sh` (:8082) brings up the rank-1 2×1 stack
> (Open5GS + OCUDU 2T2R gNB + srsUE through the CUDA broker, rootless
> namespaces, ~40 s to attach) as a long-running demo with a path-loss
> slider that measurably moves the real UE's RSRP/RTT. Control/telemetry
> cross the netns over ipc://; srsUE metrics CSV feeds the page.
> Remaining: S6 full rehearsal, Hyunsoo's final page design. The telemetry
> `live{}` contract (§8, Appendix B) is pinned by
> `demo/contract/telemetry-sample.json`.

Target location in repo: `docs/plans/mimo-live-demo.md`
Owners: Minwoo Eun (MIMO / broker side) · Hyunsoo Lee (web / bridge side)
Reviewers: Zhouyou (Charles) Gu · Prof. Park

## 0. Context and goal

Visitors (mixed industry + academia) arrive within the next weeks. Request from
Charles: prepare **live visualizations** + a **short intro talk**, on **one
top-down web page** that shows the **MIMO component clearly**, presented jointly
with turn-taking. Page is served from the RTX 5090 workstation; TVs connect via
a laptop browser to an open IP:port on that box. Names to appear somewhere
appropriate: Minwoo Eun, Hyunsoo Lee, Zhouyou (Charles) Gu, Prof. Park.

**Hard constraint:** the demo must run standalone on `ocudu-gpu-channel` alone —
no Sionna runtime dependency. (Sionna only supplied the published TDL tap
numbers; the example YAMLs already carry them baked in.) Hyunsoo's Sionna work
plugs in later as one additional panel, not as a prerequisite.

## 1. What already exists (reuse, do not rebuild)

- **Broker + CUDA channel**: TDL-A..E profiles, Jakes fading, Rician LOS,
  per-edge lanes, slot-cadence real time (~97 µs kernel at `tdl-a_E16`,
  58,430 µs → 319 µs vs CPU, ≈183×).
- **Control plane** — ZMQ REP `tcp://*:5559` (`--control-endpoint`):
  `scalar`, `profile_swap`, `batch_*` messages, applied at slot boundaries.
  `profile_swap` returns `warmup_until_slot` (delay-line zero-fill contract).
- **Telemetry** — ZMQ PUB `tcp://*:5560` (`--telemetry-endpoint`,
  `--telemetry-rate-hz`, default 20 Hz): one JSON frame per edge
  (`link_id, slot, seqno, live{...}, profile_active, warmup_until_slot`),
  topic prefix = `link_id`. **Caveat: never exercised against a live
  subscriber — validating this is step S0.**
- **2×2 correlated MIMO gates** (`gpu-test-sequence.sh` steps 8–9): synthetic
  relay through a running broker; measured RX power vs analytic expectation
  (correlated 9.542 vs 9.71; iid control 6.964 vs 6.94); live correlation-matrix
  swap over the control plane moves power off the iid value. **This is the demo
  backend in script form** — the demo turns this pass/fail gate into a
  continuously running loop that exports numbers.
- **rank-1 MISO/SIMO declaration** (Minwoo) — enables the 1×4 steering demo.
- **Live-radio tier (stretch)**: `run-ocudu-mimo-2port-no-core.sh` (real
  2-antenna OCUDU gNB, 4 ZMQ endpoints, no Docker/core) and
  `verify-mimo-matrix-capture.py` (y vs H·x per-sample check).

## 2. Architecture

```
[TX relay driver]──ZMQ IQ──▶ broker (CUDA, 5090 box) ──ZMQ IQ──▶ [sink + power meter (C1)]
                                   │ PUB :5560 (channel state, 10 Hz)          │ per-port avg_power
                                   ▼                                           ▼
                            [bridge / web server (C2)] ◀────── meter frames ───┘
                                   │  WebSocket push + static page :8080
                                   ▼
                            [one-page UI (C3)]  ── buttons ──▶ bridge ── REQ :5559 ──▶ broker
```

Everything runs on the 5090 workstation. Only port **8080** (bridge + static
page combined) needs to be reachable from the demo laptop; 5559/5560 stay
local. TVs mirror the laptop browser.

## 3. Components to build

- **C1 — power meter** (Minwoo, ~20 lines): extend the gate's relay sink to
  emit per-port `avg_power` over sliding windows (0.5 s) instead of a single
  end-of-run number. Transport to bridge: local ZMQ PUSH or UDP JSON
  (`{"port": "rx0", "t": ..., "avg_power": ...}`).
- **C2 — bridge/server** (Hyunsoo, single Python file): asyncio app that
  (a) SUBs `:5560` for channel state, (b) receives meter frames, (c) exposes
  REQ `:5559` actions as HTTP/WS endpoints for the UI buttons, (d) serves the
  static page and pushes merged state over WebSocket at 10 Hz. Browsers cannot
  speak ZMQ — this bridge is mandatory.
- **C3 — one-page UI** (Hyunsoo, layout agreed via wireframe): top-down order =
  presentation order. Header (title + 4 names + URL chip) → metric cards
  (kernel µs, slot-budget %, 183×, telemetry Hz) → **MIMO panel** (2×2 |H|
  heatmap, per-lane power bars vs analytic line, buttons: correlation swap /
  iid toggle) → fading sparkline (f_d = 10 Hz) → massive-MIMO scaling panel
  (lanes vs kernel-µs bars against the 500 µs budget line; labelled as
  projection anchored at measured E16 = 97 µs).
- **C4 — demo driver** (Minwoo): scenario scripts behind the buttons
  (correlation swap, iid toggle, path_loss slider, SIMO steering swap), plus an
  optional closed-loop "agentic" script that sweeps parameters automatically
  while the page reacts — this is the visible form of the agentic/closed-loop
  control story.

## 4. Demo fidelity levels for |H|

- **L1 (must, days 1–2)** — *declared* H from topology/telemetry beside
  *measured* per-port power with the analytic expectation line (exact gate
  math, rendered live). Sufficient for the visit.
- **L2 (should)** — TX pilot alternation (one TX column at a time) →
  per-column measured |h_rc| fills the 2×2 heatmap with real measurements.
- **L3 (stretch)** — two simultaneous tones, FFT-bin separation at the sink →
  both columns measured live at once.
- **Minwoo solo headline** — 1×4 rank-1 SIMO: port power bars reproduce the
  |a_r|² steering pattern; a live steering swap visibly reorders the bars.
  Opens Minwoo's talk segment; independent of everything Hyunsoo owns.

## 5. Locked settings

- Fading `f_d,max`: **10 Hz** for demo topologies (default 100 Hz looks like
  noise at UI refresh rates; 10 Hz makes the envelope visibly breathe over
  seconds).
- `--telemetry-rate-hz`: **10**.
- SCS **30 kHz** → 500 µs budget shown on the gauge (bench default).
- Ports: 5559/5560 local-only; **8080** exposed. Firewall change on the 5090
  box: 8080 only.
- UI must respect the warmup contract: while `slot < warmup_until_slot` after a
  `profile_swap`, grey the affected lane / show a "warming up" badge instead of
  plotting artefact samples.
- Names: page header carries all four; add Hyunsoo to the repo contributors
  line alongside the existing rank-1 MISO/SIMO credit.

## 6. Build steps and gates (repo style: no step ships without its gate)

- **S0 — telemetry smoke** (Minwoo, day 0):
  run broker with `--telemetry-endpoint tcp://*:5560`, then

  ```python
  import zmq
  s = zmq.Context().socket(zmq.SUB)
  s.connect("tcp://localhost:5560")
  s.setsockopt_string(zmq.SUBSCRIBE, "")
  while True: print(s.recv_multipart())
  ```

  Gate: frames arrive; record the exact `live{...}` keys → they define the
  bridge data contract (Appendix B). This also closes the documented
  "telemetry never exercised live" caveat.
- **S1 — power meter**: run the step-8 correlated topology relay with C1.
  Gate: windowed powers reproduce the gate's analytic expectations
  (≈9.71 correlated / ≈6.94 iid) within the gate tolerance.
- **S2 — bridge + page skeleton**: Gate: browser on a second machine shows
  live numbers updating at 10 Hz through :8080 only.
- **S3 — control buttons**: Gate: pressing "correlation swap" on the page moves
  the measured power off the iid value on screen — the on-screen mirror of gate
  step 9. Verify exact REQ JSON against the gate script before wiring.
- **S4 — MIMO panel + SIMO steering**: Gate: L1 visuals complete; 1×4 rank-1
  bars reorder on a live steering swap.
- **S5 (optional)** — L2 pilot alternation; live 2-port OCUDU tier via
  `run-ocudu-mimo-2port-no-core.sh`.
- **S6 — rehearsal**: full 3-minute run-through with role hand-offs; page
  reloaded cold; one failure drill (broker restart mid-demo).

Suggested timeline: week 1 = S0–S2, week 2 = S3–S4 + S6; S5 only if time
remains.

## 7. Talk outline (≈3 min, turn-taking; order = page top-down)

1. Hyunsoo (30 s): what this is — a real-time GPU channel emulator sitting
   inside live srsRAN/OCUDU stacks; introduce the page.
2. Minwoo (60 s): MIMO live — |H| heatmap; press correlation swap; watch
   off-diagonals and measured power move.
3. Hyunsoo (30 s): fading + telemetry — 10 Hz envelope breathing; closed-loop
   control (the agentic script driving :5559 while the page reacts).
4. Minwoo (30 s): scaling roadmap — lane explosion vs 500 µs budget; low-rank
   decomposition as the research direction (L spatial components instead of
   Nt·Nr lanes).
5. Close (10 s): names, thanks.

Audience one-liners — industry: "commercial-emulator-class capability on one
GPU, dropped into a live stack" (cost, productization, CUDA optimization beat:
58,430 µs → 319 µs). Academia: "channel modelling under a hard 500 µs real-time
budget is open research — low-rank/correlation-exploiting emulation at massive
MIMO scale" (the scaling panel is the pitch).

## 8. Open questions

- Which "10 Hz" Charles meant (telemetry rate vs Doppler) — both are set; confirm.
- Exact telemetry `live{}` field names — fixed after S0 capture.
- Meter transport (ZMQ PUSH vs UDP) — Hyunsoo's preference at S2.
- Final web port number and firewall approval on the 5090 box.

## Appendix A — control-plane message shapes (verify against gate script at S3)

```jsonc
// scalar
{ "type": "scalar", "link_id": "<edge>", "param": "path_loss_db",
  "value": 12.0, "take_effect_at_slot": null }
// profile_swap (correlation/steering scenarios; returns warmup_until_slot)
{ "type": "profile_swap", "link_id": "<edge>",
  "taps": [ { "delay_samples": 0.0, "gain_db": -3.0, "phase_rad": 0.0 } ],
  "fading": { "f_d_max_hz": 10.0 } }
```

## Appendix B — bridge → UI data contract (fill at S0/S1)

```jsonc
{ "t": 0.0,
  "channel": { "<link_id>": { "live": { /* from S0 capture */ },
                               "profile_active": "", "warmup_until_slot": 0 } },
  "power":   { "rx0": 9.5, "rx1": 4.1 },
  "expected": { "correlated": 9.71, "iid": 6.94 },
  "gpu": { "kernel_us": 97 } }
```
