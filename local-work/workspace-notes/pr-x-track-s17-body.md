# PR 초안: UE-to-UE interference done physically, OAI TDD multi-UE/two-cell gates, and a threaded lower PHY over ZMQ (stacked on #3)

- base: `zhouyou-gu/ocudu-gpu-channel` main (리뷰는 #3 이후 커밋 4개만 보면 됨)
- head: `MinwooEun:x-track-s17` (`c0e7779`), #3 `gb10-integration` (`5973316`) 위에 스택
- 생성됨: https://github.com/zhouyou-gu/ocudu-gpu-channel/pull/4 (2026-10-08)
- 생성 명령 (사용함):

```bash
gh pr create -R zhouyou-gu/ocudu-gpu-channel --base main --head MinwooEun:x-track-s17 \
  --title "UE-to-UE interference done physically, OAI TDD multi-UE and two-cell gates, threaded lower PHY over ZMQ (stacked on #3)" \
  --body-file ~/ocudu-work/pr-x-track-s17-body.md
```

(아래 본문은 `---` 다음부터 그대로 PR 설명으로 사용)

---

Stacked on #3 (`gb10-integration`); the five commits after `5973316` are this PR.

## Why

The broker is carrier-agnostic: a port is one carrier's baseband and the broker sums whatever the graph declares. The FDD example topologies declared `ue0->ue1` / `ue1->ue0` "crosstalk" edges that have no physical counterpart on a band-3 cell (a UE's uplink carrier is never seen by another UE's downlink receiver), so they injected one UE's uplink baseband straight into the other UE's downlink. This PR makes the interference physical: carrier labels reject such edges, the transmit levels of every radio are put on one scale, and the gates where a UE<->UE path really exists (TDD n78, one cell with two OAI nrUEs; two cells with different TDD patterns) show the other UE's uplink landing in the victim's downlink slots and the stack reacting (CQI collapse, DL NACKs, RTT spikes).

Along the way the broker had a CFO bug (a `phase` step applied the link's CFO a second time, so every phase+cfo chain delivered 2x), the OCUDU gNB wedged under two-UE uplink load (its main worker pool starved itself on five pinned cores), and the lock-step loop over ZMQ turned out to be capped by OCUDU forcing a sequential lower PHY whenever the radio is ZMQ. The last one is addressed with local patches to the pinned gNB, built next to the pinned build (the policy already used for the OAI and srsUE local patches).

## Commits

1. **broker** (`63bb4e4`): port carrier labels with edge rejection, per-device `tx_scale_db`, the phase/CFO fix with a regression test, a relay wedge detector (`OCG_BROKER_WEDGE_TIMEOUT_MS`), per-second health deltas in the heartbeat, `runtime.cuda_stream_priority` (MPS clients), FDD examples without UE<->UE edges.
2. **native gates** (`ba362e0`): strict attach verdict, four-UE option, Sionna multi-UE gate with a live position feed and an absolute receiver noise floor, OAI nrUE TDD multi-UE gate (X3/X4) and two-cell two-pattern gate (X5), OAI transmit scale from wire captures and DL-only FO compensation (X7), gNB `main_pool` / lower-PHY profile render knobs (X6), the `robot_ring` Sionna scene these gates use.
3. **S17 local gNB patches** (`1fd3439`): `build-ocudu-gnb-local.sh` + lock; `OCUDU_ZMQ_LOWER_PHY_PROFILE` keeps a threaded lower PHY with ZMQ, the radio worker and libzmq I/O thread get real-time priority, two busy polls and a double copy are removed; an optional NEON conversion patch for the OAI ZMQ module.
4. **docs** (`4d08f34`): `CROSSTALK_MILESTONES.md`, `docs/plans/x3|x5|x6|x7`, `SPARK_MILESTONES.md` S16-S17, README sections.
5. **docs/platforms.md** (`c0e7779`): one page for the RTX 5090, DGX Spark GB10 and Jetson AGX Orin: what differs per host (host-memory mode, CPU placement, CUDA gNB lock/patch lineage, local stack patches), measured envelopes, and how each host is set up.

## Measured (DGX Spark GB10)

| What | Result |
|---|---|
| Two-cell TDD, different patterns, 10 links (X5) | victim UE: other UE's UL in its DL slots at -24.3 dB vs own DL -36.4 dB; CQI 0 x27; 3 DL NACK; RTT max 87 ms. Same pattern or no UE<->UE edge: clean |
| TDD multi-UE, both UEs LOS (X3/X4) | pass, UE<->UE tap median +4.1 dB over serving |
| phase+cfo chain | 125 Hz configured was 250 Hz on the wire; now 125 Hz (regression test) |
| 100 MHz 2x2 OAI, idle, real-time factor | 0.65-0.67 stock -> 0.82-0.85 with the S17 patches |
| 100 MHz 2x2 under load | 0.25 -> 0.32 (remaining bound: per-message REQ/REP round trip, OAI UE decode time) |
| 20 MHz 2x2 under load | 0.89 -> 0.98 |
| ctest / Python tests on this tree | 12/12, 125 passed |

## Not in this PR

- The robot-fight demo track that produced some of these mechanisms (its scene and the multi-UE gate stay because the X-track gates use them).
- Upstream reports for the OCUDU `main_pool` starvation and the forced sequential lower PHY (drafts exist; the local patches carry the fix for now).
- Open: whether the OAI gates should default `--cont-fo-comp` to 3; gNB<->gNB links, the 2D7U pattern and UL traffic under CLI were not run.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
