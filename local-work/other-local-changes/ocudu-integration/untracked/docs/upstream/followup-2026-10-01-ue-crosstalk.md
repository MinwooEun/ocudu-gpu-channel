# Draft (NOT posted): UE-to-UE "crosstalk" edges in the FDD example topologies

Target: zhouyou-gu/ocudu-gpu-channel (upstream main 3bae52c, PR #2 a07b8a9, PR #3 5973316),
and the Sionna contributor's two-cell scenes. Status: draft for minwoo to review before posting.

## Summary

`examples/topology.graph.cuda.yaml` (05-18), `examples/topology.sionna-2gnb-2ue.cuda.yaml` and
`examples/topology.sionna-multi-gnb.cuda.yaml` (08-21 / 09-11), and the scenarios
`examples/sionna/multi-gnb-sutd.json`, `sionna_SUTD_test.json` declare edges `ue0->ue1` and
`ue1->ue0` ("crosstalk"). On the FDD band-3 fixtures these edges have no physical counterpart:
a UE's uplink carrier (1747.5 MHz) is never seen by another UE's downlink receiver (1842.5 MHz).
The broker is carrier-agnostic (a port is one carrier's baseband) and sums whatever the graph
declares, so the edge injects the other UE's uplink baseband straight into the victim's
downlink baseband.

Two measured facts make that injection catastrophic rather than merely wrong:

1. srsUE's ZMQ driver multiplies `[rf] tx_gain = 50` numerically (`rf_zmq_send_timed_multi`):
   srsUE uplink on the wire = +44 dB mean active |x|^2 (peak amplitude 313) versus the OCUDU
   gNB downlink at -19.8 dB (peak 0.39): a 64 dB gap that is invisible as long as every receiver
   hears only one class of transmitter.
2. With the Sionna adapter's +60 dB gain offset and +20 dB clamp, a 2-4 m UE-to-UE path becomes a
   +18 dB tap while the serving downlink is -2.4 dB.

Result at the victim UE: the other UE's bursts arrive ~80 dB above its own downlink. In a live
run (DGX Spark GB10, srsUE x2, 2026-10-01) both UEs attached, then released on the same TTI
(`Scheduling request failed`) and their PRACH retries erased each other's RARs. The multi-UE
gate still reported `passed` because its verdict only required one successful ping.

The intermittent UE1 failures recorded for the 09-14 SUTD run (`docs/sionna-integration.md`,
"UE recovery validation": UE1 0/10 at the end) are consistent with this mechanism (that run
used the 10-link topology), though coverage holes were also present.

## What we changed on our side (branch integration-0928, commits e9534aa, e561468, ad8427c)

- Broker: optional per-port carrier labels (`tx_carrier`/`rx_carrier`, `carrier` for TDD);
  an edge whose TX-port carrier differs from its RX-port carrier is rejected at load with
  the reason. Optional per-device `tx_scale_db` folded as a constant gain behind the leading
  tdl so profile swaps keep it. Link keys keep the declared model id.
- Examples: UE<->UE edges removed from the four FDD files above; `graph.yaml` kept as an
  explicitly single-carrier example (`carrier: shared`); the bridge's default layout and
  `check_feed.py` list eight links.
- Gates: strict attach verdict (no SR failure, no post-attach PRACH, every ping answered).
- Renderers: UE ports get `tx_scale_db` = (23 dBm - 30 dBm) - 10 log10(UL_wire / DL_wire)
  (~ -71 dB for srsUE), gNB noise floor from the scaled uplink.

Validation: Sionna multi-UE (ring scene) and two-cell Sionna (street canyon) pass the strict
verdict; a scenario with the UE<->UE edge is refused at broker start.

## Suggested upstream changes

1. Drop the `ue0<->ue1` edges from the FDD examples/scenes, or label the example as a
   shared-carrier (TDD) case where they are physical.
2. Note in the README's topology section that an edge is only physical between a TX port and
   an RX port on the same carrier, and that the ZMQ radios' wire levels are software scales
   that must be normalised (per-device `tx_scale_db`) before transmitter classes are mixed.
3. Re-check the SUTD two-cell result with the eight-link topology.

We can open a PR with 1-2 if wanted.
