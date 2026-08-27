# MIMO live demo — implementation summary

Date: 2026-08-24 · Branch: `rank1-miso-simo` · Owner: Minwoo Eun
Plan: `docs/plans/mimo-live-demo.md` · Runbook: `demo/README.md`

## What was delivered

Three web demos, all runnable today on the RTX 5090 box, all standalone on
`ocudu-gpu-channel` (no Sionna, no Docker). They form the talk's story arc:

| # | Page | Story | Stack |
|---|------|-------|-------|
| 1 | `:8080` — 2×2 correlation | *the emulator is provably correct* | synthetic tone sources → CUDA broker → power meter |
| 2 | `:8081` — 1×4 SIMO steering | *beam geometry made visible* | deterministic `fixed_mimo`, supervisor-driven re-steer |
| 3 | `:8082` — live radio | *a real 5G stack lives on this channel* | Open5GS + OCUDU gNB + srsUE through the broker |

Bring-up: `demo/run-demo.sh`, `demo/run-simo-demo.sh`,
`demo/native/run-live-demo.sh [duration] [--mode 2x1|4x1]`. All three run
concurrently (disjoint ports); each tears down cleanly on Ctrl-C.

## Plan items → status

- **S0 telemetry smoke** — DONE. Closed the "never exercised live" caveat:
  19.8 Hz received (10 Hz × 2 links); v3.0 frame layout is a single part,
  `"<link_id> {json}"`; `live{}` carries 7 scalar keys. Contract pinned in
  `demo/contract/telemetry-sample.json`.
- **C1 power meter + S1 gate** — DONE. Sink-style REQ drain, 0.5 s sliding
  windows; reproduces the step-8 analytics: correlated **9.53** (~9.71),
  iid **7.01** (~6.94), inside the ±1.5 gate tolerance. Rides through broker
  restarts (REQ socket recreate after 1 s).

  Label for those two figures: each is a **single observation of one 0.5 s
  window** (`window_s` and `batches` in every emitted sample carry the window
  and the sample count it averaged), not a percentile and not an average over
  runs. They are judged the way a stochastic quantity has to be — against the
  analytic value that draw predicts, with a tolerance sized to the spread —
  which is why the comparison is to 9.71 / 6.94 rather than to a previous run.
- **C2 bridge / S2** — DONE (prototype for Hyunsoo). Single stdlib+pyzmq
  file: telemetry SUB + meter PULL + control REQ, page served with 10 Hz
  Server-Sent Events push. Second-machine access verified via one port.
- **S3 control buttons** — DONE. Correlation ON/IID moves the measured
  4-port mean between the analytic lines live; path-loss slider attenuates
  exactly (20 dB → ×0.01 measured).
- **L2 pilot alternation** — DONE (beyond the L1 "must"). `pilot_source.py`
  alternates TX phases (both/tx0/tx1/silence, 250/250/250/150 ms); the
  silence gap travels through the channel and phase-locks the meter, so the
  2×2 heatmap shows MEASURED per-lane |h_rc|² (Rayleigh mean ≈ 3.47),
  breathing under 10 Hz Jakes fading. `--classic` reverts to declared-R (L1).
- **S4 SIMO steering** — DONE via broker restart. 1×4 bars measure
  [0.810, 0.302, 0.122, 0.040] against declared |a_r|² exactly; Steering A↔B
  reorders them; restart is ~0.26 s. The proper runtime message does not
  exist yet (`fixed_mimo` links reject both `scalar` tap params and
  `profile_swap` by design) — a `fixed_mimo_swap` control message is drafted
  in `docs/plans/fixed-mimo-swap.md`, awaiting review.
- **S5 live tier** — DONE, both editions. The rank-1 gate stack (mongod →
  Open5GS 5GC → CUDA broker → OCUDU gNB → srsUE, rootless user/net/mount
  namespaces) as a long-running demo. `--mode 2x1` = 2T2R, DL 2×1 / UL 1×2;
  `--mode 4x1` = 4T4R, DL 4×1 MISO / UL 1×4 SIMO. Attach (RRC + PDU + ping)
  in ~40 s. Measured: 12 dB DL path loss drops srsUE-reported RSRP 25 → 5.9
  (2x1) / 25 → 3.7 (4x1) and raises ping RTT 19 → 30 ms; recovers on
  release; broker telemetry mirrors the commanded value.
- **S6** — restart drill covered (SIMO swap + meter self-recovery); the full
  3-minute rehearsal with role hand-offs remains.
- Every page panel carries a collapsible "What am I looking at?" explainer
  for visitors.

## Architecture notes

- Browsers cannot speak ZMQ → the bridge is mandatory; SSE instead of
  WebSocket keeps it on the Python stdlib. The bridge re-reads the page per
  request, so page edits deploy on browser refresh.
- Live tier crosses the network-namespace boundary without opening holes:
  broker control/telemetry bind `ipc://` sockets on the shared filesystem;
  srsUE metrics CSV, the in-netns ping log, and a status file are tailed by
  `demo/native/live_tailer.py`. Only the web port faces the LAN.
- Demo fixtures are COPIES with a trailing `path_loss` step per model
  (`demo/topology.demo-mimo-2x2.cuda.yaml`,
  `demo/native/topology.live-rank1-{2x1,4x1}.cuda.yaml`); the audited gate
  fixtures and their pins are untouched.

## Findings worth keeping (hit while building)

1. A `scalar path_loss_db` update is silently inert unless the model chain
   declares a `path_loss` step — it reaches telemetry either way. On
   `fixed_mimo` links the scalar IS accepted (only `tap0_*` is rejected).
2. A correlated model must lead with its fading tdl step, so the path_loss
   step goes after it.
3. Telemetry carries scalar link params only — no per-lane |H|. Measured
   heatmaps need pilot alternation (or a future telemetry extension).
4. srsUE CSV metrics need `metrics_csv_flush_period_sec > 0` or nothing is
   written until shutdown; srsUE emits `nan` for dl_snr between DL grants,
   which must not reach JSON (browsers reject bare NaN).
5. Teardown of the namespaced stack must TERM the *inner* runner, never the
   `unshare` wrapper: `--kill-child` SIGKILLs the inner before its trap can
   stop the setsid'd process groups, orphaning gNB/srsUE/core.
6. The loader rejects flow-style YAML lists, and the validator requires
   every device to be both the source and the destination of some link.
7. `/usr/bin/python3` on this box no longer has pymongo; the live runner
   picks whichever interpreter can import `bson` for the subscriber insert.

## Not done / decisions pending

- `fixed_mimo_swap` runtime message: drafted, not implemented (hot-path C++;
  needs Charles's sign-off). Until then SIMO re-steer = broker restart.
- S6 full rehearsal; Hyunsoo's final page design pass (wireframe agreement),
  and his choice of SSE vs WebSocket for the production bridge.
