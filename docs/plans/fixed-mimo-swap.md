# `fixed_mimo_swap` — runtime steering update for fixed-matrix links (proposal)

Status: **draft for review** (Charles / Prof. Park). Written 2026-08-24 while
building the MIMO live demo; the demo currently works around the gap with a
broker restart (`demo/simo_supervisor.py`, ~0.3 s), so this is not urgent for
the visit — it is the *right* mechanism afterwards, and the "agentic
closed-loop control" story is stronger when the steering swap goes through the
same control plane as everything else.

## 1. Gap

A `fixed_mimo` link folds its coefficients into per-lane tap weights at load
time (`expand_fixed_mimo_models`, config.cpp): each surviving lane gets a
model clone whose tdl taps carry `gain_db += 20·log10|c|`,
`phase_rad += arg(c)`. At runtime the control plane addresses LINKS (M4.2),
and both mutation paths are deliberately rejected on such links:

- `scalar` — a link-scope tap write would smear one value over every lane and
  erase the matrix (`runtime_control.h`, `fixed_mimo_declared`).
- `profile_swap` — replacing the tap layout would delete the folded weights
  (control_server.cpp, handle_profile_swap).

So there is no way to re-steer a 1×4 / 4×1 rank-1 link live, which is exactly
what the demo plan's S4 headline ("live steering swap visibly reorders the
bars") and any closed-loop beam-adaptation experiment need.

## 2. Proposed message

```jsonc
{ "type": "fixed_mimo_swap",
  "link_id": "ue>gnb:ul_simo_1x4",
  "coefficients": [                    // same shape as the YAML block
    { "tap": 0, "rx": 0, "tx": 0, "real": 0.2,  "imag": 0.0 },
    { "tap": 0, "rx": 1, "tx": 0, "real": 0.35, "imag": 0.0 },
    { "tap": 0, "rx": 2, "tx": 0, "real": 0.55, "imag": 0.0 },
    { "tap": 0, "rx": 3, "tx": 0, "real": 0.9,  "imag": 0.0 } ],
  "take_effect_at_slot": 0 }           // 0 = next slot boundary (v1 semantics)
// reply: {"ok":true,"seqno":N}  (same shape as correlation_swap)
```

Validation (control thread, mirroring the loader):
- link must have `fixed_mimo_declared` (the mirror image of today's
  rejection: this message is *only* for fixed-matrix links);
- every `(tap, rx, tx)` within `[0, n_taps) × [0, nr_hint) × [0, nt_hint)`;
- **v1 restriction: the surviving-lane set must not change** — a coefficient
  may change value but a lane that was zero (dropped at load, no model clone,
  no device dispatch) cannot be born at runtime, and a live lane cannot go to
  exactly zero. Reject otherwise. This keeps the change entirely inside
  "update tap weights of existing lanes" and away from lane
  creation/destruction, which is prepare()-time machinery.

## 3. Mechanism (follows the correlation_swap pattern)

1. **Prepare-time bookkeeping**: when a link's base model declares
   `fixed_mimo`, store on `BrokerLinkControl`:
   - the UNFOLDED base tap list (delay/gain/phase before folding), and
   - the current coefficient per lane.
   Cost: a few hundred bytes per link, prepare-time only.
2. **Control thread (REQ validation)**: fold the new coefficients into
   per-lane tap arrays using the same arithmetic as
   `expand_fixed_mimo_models` — factorisation-style work on the control
   thread, never on the serve path (the M3 promise). Stage into a new
   `FixedMimoShadow { int lanes; ProfileShadowLite per_lane[kMaxCorrelatedLanes]; }`,
   set `fixed_mimo_pending`, bump seqno with release semantics.
3. **Snap path** (one snap per link per slot, M4.2): on pending + slot gate,
   copy each lane's staged taps over that lane's live tap state and run the
   existing tap-refresh H2D path that profile_swap already uses — including
   the delay-line zero-fill and the `warmup_until_slot` contract when tap
   delays changed. When delays are untouched (the steering case: only
   gain/phase move), no warmup is needed — same rule the scalar tap-0 path
   already applies.
4. **Telemetry**: bump `seqno` in the frames as today; optionally add
   `live.fixed_mimo_seq` so a UI can show which steering is active.

## 4. Gates (repo rule: no step ships without one)

- Unit (test_control_server): accept/reject matrix — non-fixed_mimo link,
  out-of-range indices, lane-set change, happy path staging.
- Parity (test_runtime_update_parity): CPU vs CUDA output after a swap.
- Broker-level (gpu-test-sequence step): 1×4 deterministic topology (single
  0 dB tap, no fading — `demo/simo_supervisor.py` renders exactly this), RX
  powers = |a_r|² before, swap A→B mid-run, powers must equal reversed
  pattern after, counters clean. Expected values are exact, so the tolerance
  can be tight (±0.01).

## 5. Why not alternatives

- **Correlation swap cannot express it**: a correlation matrix has unit
  diagonal, so per-port *magnitude* patterns (|a_r|² ≠ const) are outside its
  reach; only phase-only steering could be faked that way.
- **Broker restart** (current workaround): works and is fast (~0.3 s) but
  drops in-flight state, resets counters/slot clock, and is not "runtime
  control" — fine for a demo button, wrong for closed-loop experiments.
