# MIMO live demo stack

Implements the Minwoo-side components of `docs/plans/mimo-live-demo.md`, plus
working prototypes of the Hyunsoo-side bridge and page so the whole loop can
be exercised today. Everything runs standalone on `ocudu-gpu-channel` — no
Sionna, no Docker, no core network.

Machine prerequisites (GPU/CUDA, Python deps, native-workspace builds,
ports): see [`ENVIRONMENT.md`](ENVIRONMENT.md).

## What is reproducible from this repository

The 2026-08 review's first finding was that results had been reported from a
harness nobody receiving the branch could run. That finding applies to one of
the three tiers here, and it is stated per tier rather than left for a reader
to discover:

| Tier | Needs | Reproducible from this repo alone |
|---|---|---|
| `:8080` 2×2 correlation (`run-demo.sh`) | `build-cuda/ocudu-gpu-channel`, Python with pyzmq + numpy | **Yes** |
| `:8081` 1×4 SIMO steering (`run-simo-demo.sh`) | the same | **Yes** |
| `:8082` live radio (`native/run-live-demo.sh`) | the whole `~/ocudu-native-workspace` — OCUDU gNB, srsUE, Open5GS and mongod builds, provisioned outside this repo | **No** |

The live tier runs on the native harness, which the review classified as a
record of the original run rather than a supported path:
`scripts/native/bootstrap-workspace.sh` deliberately disables provisioning and
`/home/ubuntu` and `/opt/conda` are hardcoded. Anyone without that workspace
already built cannot start `:8082`, and no error message will explain why
beyond a missing-binary line.

Porting the live tier onto the containerised harness in `scripts/remote/` —
which provisions its own network and 5GC — is tracked as V5 in
[`../RANK1_REVIEW_MILESTONES.md`](../RANK1_REVIEW_MILESTONES.md). Until that is
done, quote `:8082` results with the same caveat the native gates carry.

## Quick start (on the 5090 box, inside tmux)

```bash
cd demo
./run-demo.sh                 # 2x2 correlation demo on :8080 (2 h default)
./run-simo-demo.sh            # 1x4 rank-1 steering demo on :8081 (own ports,
                              # runs ALONGSIDE the 2x2 stack: open both tabs)
./native/run-live-demo.sh     # LIVE tier on :8082 — real Open5GS + OCUDU gNB
                              # + srsUE attached through the CUDA broker
                              # (--mode 2x1 default; --mode 4x1 = 4T4R gNB,
                              #  DL 4x1 MISO / UL 1x4 SIMO)
# laptop: http://<box-ip>:8080 / :8081 / :8082 (only these ports need opening)
```

**2×2 page (:8080)** — **Correlation ON** / **IID** buttons (live
`correlation_swap`; measured RX power moves between the analytic 6.94 and
9.71 lines), a **path loss** slider, a MEASURED 2×2 |h_rc|² heatmap fed by TX
pilot alternation (plan L2), and a fading sparkline with analytic reference
lines plus a marker at every control action. `./run-demo.sh 7200 --classic`
switches to always-on C++ tone sources (heatmap falls back to declared R).

**SIMO page (:8081)** — four RX-port bars sitting exactly on the declared
|a_r|² steering pattern (deterministic single-tap channel), with **Steering
A/B** buttons that re-render the 1×4 `fixed_mimo` topology and restart the
broker (~0.3 s; the meter rides through it). This is the plan's S4 headline —
delivered via restart because no `fixed_mimo` runtime swap message exists yet;
`docs/plans/fixed-mimo-swap.md` is the proposal for the real one.

**Live page (:8082)** — the plan's S5 tier, real radio: the rank-1 2×1 gate
stack (mongod → Open5GS 5GC → CUDA broker → OCUDU 2T2R gNB → srsUE, rootless
namespaces) turned into a long-running demo. Bring-up takes ~40 s to UE
attach; the page then shows srsUE-reported RSRP / DL SNR / bitrates, a live
ping RTT from inside the UE netns, and broker telemetry — and a **path-loss
slider** drives the real link: 12 dB visibly drops RSRP (~25 → ~6) and
raises RTT, and it recovers on release. Control/telemetry cross the netns
boundary over `ipc://` sockets (shared filesystem); UE metrics and ping
reach the page through `native/live_tailer.py`.

Scripted closed-loop scenario (2×2):

```bash
python3 driver.py sweep              # alternates correlated<->iid, ramps path loss
python3 driver.py correlate|iid      # one-shot actions
python3 driver.py path-loss 12
```

## Files

| file | plan item | role |
|---|---|---|
| `topology.demo-mimo-2x2.cuda.yaml` | §5 | 2×2 TDL-A, `kind: iid` declared (opt-in for runtime correlation swaps), f_d = 10 Hz, trailing `path_loss` step so the slider is not inert, ports 162xx |
| `s0_telemetry_smoke.py` | S0 | captures telemetry frames, prints/dumps the `live{}` contract |
| `power_meter.py` | C1/S1 | drains RX REP endpoints sink-style; 0.5 s windowed + cumulative per-port power as JSON over ZMQ PUSH; `--pilot` adds phase-resolved h0/h1 lane measurements; rides through broker restarts (REQ recreate after 1 s) |
| `pilot_source.py` | L2 | replaces the C++ tone sources with a TX-alternation schedule (both/tx0/tx1/silence = 250/250/250/150 ms); the silence gap is the meter's phase-sync marker, delivered through the channel itself |
| `bridge.py` | C2 | stdlib+pyzmq single file: SUB telemetry, PULL meter, REQ control, serves the page and pushes merged state over **SSE** (`/events`) at 10 Hz; `--steering-rep` enables the SIMO steering action |
| `static/index.html` | C3 | 2×2 UI: header/names, metric cards, measured \|h_rc\|² heatmap (declared-R fallback), power bars vs analytic lines, warmup badge, sparkline with reference lines + action markers, scaling panel |
| `static/simo.html` | S4 | 1×4 UI: per-port bars vs \|a_r\|² ticks, Steering A/B buttons, re-steering badge |
| `driver.py` | C4 | scenario CLI + the closed-loop sweep (goes through the bridge so the page's declared-state view stays in sync) |
| `simo_supervisor.py` | S4 | renders the 1×4 `fixed_mimo` topology from a named steering vector, owns/restarts the broker, ZMQ REP :5565 for swaps |
| `run-demo.sh` | §2 | 2×2 bring-up: pilot source (or `--classic` C++ sources) → broker (control :5559, telemetry :5560 @10 Hz) → meter → bridge :8080 |
| `run-simo-demo.sh` | S4 | SIMO bring-up on disjoint ports (control :5562, telemetry :5563, meter :5564, supervisor :5565, web :8081) so both demos run at once |
| `native/run-live-demo.sh` | S5 | live tier bring-up: renders the rank-1 gate configs (+ demo patches), launches the namespaced RAN stack, then tailer + bridge on :8082/:5566 |
| `native/run-live-demo-inner.sh` | S5 | inside the rootless namespaces: mongod → Open5GS → broker (`ipc://` control/telemetry, long duration) → gNB → srsUE → attach check → continuous ping |
| `native/topology.live-rank1-2x1.cuda.yaml` | S5 | rank-1 2×1 gate topology + a `path_loss` step per model (demo copy; audited fixtures untouched) |
| `native/live_tailer.py` | S5 | tails srsUE metrics CSV / ping log / status file on the shared fs, pushes frames to the bridge |
| `static/live.html` | S5 | live page: attach badges, RSRP/SNR/bitrate/RTT cards + sparklines, path-loss slider |
| `contract/telemetry-sample.json` | S0 gate | captured live frames defining the Appendix-B contract |

## Gate results (measured 2026-08-24, RTX 5090, CUDA build)

- **S0** — telemetry live-subscriber caveat closed: 19.8 Hz received
  (10 Hz × 2 links), v3.0 layout is **one part** per frame,
  `"<link_id> {json}"` with the topic as a plain byte prefix.
  `live{}` keys: `path_loss_db, awgn_snr_db, cfo_hz, tap0_delay_samples,
  tap0_gain_db, tap0_phase_rad, los_k_db`.
- **S1** — meter reproduces the gate analytics on the step-8 topologies
  (cumulative mean over 4 ports): correlated **9.53** vs ~9.71,
  iid **7.01** vs ~6.94, both inside the ±1.5 gate tolerance.
- **S3-equivalent** — live `correlation_swap` moved the windowed 4-port mean
  from ~6.9 (iid) to ~9.7–10.2 (correlated) on screen; `kind: iid` swaps it
  back. Path loss 20 dB drops measured power ×0.01 exactly.
- **L2 pilot alternation** — with `pilot_source.py` + `--pilot` the meter
  phase-locks off the silence gap (mode `sync`→`pilot`) and the per-lane
  h0/h1 powers sit around the Rayleigh mean 3.47 while the both-phase mean
  still tracks 6.94→9.71 across a swap. Python sources hold the broker's
  real-time cadence (counters clean, same tx_pulls rate as the C++ sources).
- **S4 steering (restart-based)** — pattern A bars measure
  [0.810, 0.302, 0.122, 0.040] against analytic [0.81, 0.3025, 0.1225, 0.04];
  swap to B reorders them exactly reversed; broker restart 0.26 s and the
  meter reconnects on its own. Also doubles as the S6 broker-restart drill.
- **S5 live tier** — real srsUE attached through the CUDA broker (RRC +
  PDU session + ping, ~40 s bring-up); 12 dB path loss on the DL link
  dropped srsUE-reported RSRP 25 → 5.9 and raised ping RTT 19 → 30 ms,
  recovering on release; broker telemetry mirrored the applied value; SSE
  stream stays strict-JSON even while srsUE reports `nan` (tailer drops
  non-finite fields). Ctrl-C teardown leaves no processes or ports behind.
- **S5 4x1 mode** — `--mode 4x1` runs the 4T4R gNB with DL 4×1 MISO /
  UL 1×4 SIMO (rank-1 R3 fixtures): attach + ping pass identically, and
  12 dB on `gnb0>ue0:dl_miso_4x1` dropped RSRP 25 → 3.7. The page derives
  link ids from telemetry, so the same live.html serves both modes.

## Findings worth knowing

- Telemetry does **not** carry per-lane |H| — only scalar link params. The
  measured heatmap therefore comes from pilot alternation (L2, default mode);
  in `--classic` mode the panel falls back to declared state (L1).
- A `scalar path_loss_db` update is silently inert unless the model chain
  declares a `path_loss` step; and a correlated model must lead with the
  fading tdl, so the step goes *after* the tdl. The demo topology does this.
- **No runtime steering swap exists for `fixed_mimo` links**: both `scalar`
  and `profile_swap` are rejected on them by design. The SIMO demo therefore
  swaps steering by broker restart (fast enough at ~0.3 s to read as live);
  the proper control-plane message is drafted in
  `docs/plans/fixed-mimo-swap.md` and needs review before implementation.
- Browsers push through **SSE**, not WebSocket, so the bridge stays on the
  Python stdlib. If Hyunsoo prefers WebSocket, swap the `/events` handler
  for an aiohttp app; the data contract is unchanged.
