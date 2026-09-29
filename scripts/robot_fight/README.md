# robot_fight — sumo arena, brains and fight runner (R2)

Two differential-drive push bots in a circular ring. Each bot's brain is a
separate process that talks to the arena over UDP, so in R4 the brain sits
behind the gNB (N6) and the arena's per-robot socket behind a UE's TUN
interface: the whole control loop then crosses the channel emulator. The arena
also publishes robot positions for the Sionna bridge (R3).

Everything runs on the wall clock and nobody waits for anybody (the
"아무도 기다리지 않는다" invariant of `ROBOT_FIGHT_MILESTONES.md`): a late or
lost command is a physical event, not a stall.

```
brain0 ──UDP CMD──▶ arena:6000 (robot ue0) ──UDP STATE──▶ brain0
brain1 ──UDP CMD──▶ arena:6001 (robot ue1) ──UDP STATE──▶ brain1
arena ──ZMQ PUB tcp://127.0.0.1:5570──▶ Sionna bridge  (positions, 20 Hz)
```

## Files

| File | Role |
|---|---|
| `protocol.py` | Wire formats: UDP header + STATE/CMD structs, position JSON. Shared with the bridge (`parse_positions_message`). |
| `arena.py` | MuJoCo world + referee + per-robot UDP server + position PUB. One process = one fight. |
| `brain.py` | One controller per robot, own loop at `--rate-hz`, `pusher` policy, `--policy module:callable` hook. |
| `fight.py` | Runs N fights (arena + 2 brains on loopback), optional `--handicap` delay/loss proxy, summary JSON/MD. |
| `../../tests/test_robot_fight_protocol.py` | pack/unpack round trips, RTT from echo, position JSON validation. |
| `../../tests/test_robot_fight_smoke.py` | one 5 s headless fight, checks RTF ≈ 1 and the streams. |

Interpreter: `~/ocudu-work/venvs/robot/bin/python` (mujoco, numpy, pyzmq, pytest).

## Wire formats

### UDP control plane (brain ⇄ robot)

Little-endian. 32-byte header on every datagram:

| field | type | meaning |
|---|---|---|
| magic | `2s` | `RF` |
| version | u8 | 1 |
| kind | u8 | 1 = STATE (robot → brain), 2 = CMD (brain → robot) |
| robot_id | u8 | 0 or 1 |
| seq | u32 | sender's counter per direction, +1 per datagram |
| t_send_us | u64 | sender's unix time in µs at send |
| echo_seq | u32 | seq of the newest datagram received from the peer |
| t_echo_us | u64 | that datagram's `t_send_us` |

`RTT = now − t_echo_us` on either end, no clock agreement needed (the arena
echoes the newest CMD in every STATE; the STATE stream is 100 Hz, so the RTT
sample includes up to one STATE period of quantisation). One-way latency
(`now − t_send_us`) is valid when both ends share a clock (same host, or
the Spark with brains and arena in different network namespaces).

STATE payload: `sim_time_s f64; x y yaw f32; vx vy wz f32; opp_x opp_y opp_yaw f32;
opp_vx opp_vy f32; ring_radius_m dist_to_edge_m opp_dist_to_edge_m f32; flags u32`
(flags: 1 running, 2 over, 4 this robot won, 8 this robot lost). 92 bytes.

CMD payload: `wheel_left wheel_right f32 (rad/s); ttl_ms u16; pad`. 44 bytes.

### ZMQ position plane (arena → Sionna bridge)

PUB, JSON, default `tcp://127.0.0.1:5570`, `--pub-hz` 20:

```json
{"event":"positions","t_unix_ms":1790685008187,"frame":"arena",
 "nodes":{"ue0":{"position_m":[x,y,z],"velocity_mps":[vx,vy,vz]},
          "ue1":{"position_m":[x,y,z],"velocity_mps":[vx,vy,vz]}}}
```

`frame` is always `arena`: ring centre at the origin, z up, metres; `z` is the
antenna height (`--antenna-height`, 0.3 m). Node ids come from `--node-ids`
(robot order). The bridge maps arena → scene coordinates.

## Arena

- Ring radius 2.0 m (`--ring-radius`), bots spawn at ±0.5·R on x facing each other with a seeded few-cm jitter.
- Bot: 30×24×8 cm chassis, 4 kg (2 kg of it a low ballast plate), two 6 cm-radius drive wheels
  on the centre axle (velocity actuators, ±30 rad/s → 1.8 m/s), two casters floating 4 mm off
  the floor so the wheels carry the weight, a 3 cm-tall low-friction push plate in front.
- Referee: body centre outside the ring → ring-out; tilt > ~70° → fall; `--time-limit` (60 s) → draw.
- **Wall clock:** physics (1 ms steps) is advanced to `sim0 + wall_elapsed` each 1 ms loop; the
  result records `rtf`, `late_loops` (loop found itself > 2 ms behind) and `max_lag_ms`.
  `--lockstep` exists for debugging only and is recorded in the result as `lockstep: true`.
- Commands: newest CMD wins (older seq dropped). A command is fresh for `ttl_ms` after arrival;
  otherwise the robot follows `--stale-policy`: **`coast`** (default, motor driver off — the wheels
  free-wheel and the bot is pushable), `zero` (brake), `hold` (keep the last command).
  Stale intervals are counted from the first fresh command onward.
- Per-fight JSONL (`--log`): `spawn`, `brain_learned`, `first_command`, `cmd` (seq, one-way µs,
  brain turnaround µs), `stale_begin/end`, `pose` (20 Hz, both robots), `result`, `rtf`.
  Result JSON (`--result`): winner, reason, rtf, per-robot command/stale/latency stats.

## Brain

`pusher`: flank-then-push. Head-on pushes between equal bots stall, so the bot
drives to a waypoint beside the opponent (perpendicular to the opponent's
heading, `flank_m` 0.7) and charges into its side once it sees the opponent
≥ `charge_deg` off the opponent's own heading. A push that has lasted
`stall_s` backs off for `backoff_s` and switches flank. Near the edge the bot
will not drive outward at full speed. `--seed` gives ±10 % parameter jitter
(`--param-jitter`) and small heading noise so fights differ.

`--policy module:callable` loads `callable(state, params, rng) -> (left, right)`;
`params["_mem"]` is a per-brain scratch dict. An LLM policy goes there.

Brain result: outcome, ticks, deadline misses, ticks without a fresh STATE,
STATE seq gaps (loss), RTT p50/p90/p99, STATE one-way p50/p99.

## Runner

```
~/ocudu-work/venvs/robot/bin/python scripts/robot_fight/fight.py \
    --fights 30 --parallel 6 --time-limit 60 --seed 1000 --out results/robot-fight/noise-floor
~/ocudu-work/venvs/robot/bin/python scripts/robot_fight/fight.py \
    --fights 12 --parallel 6 --handicap robot=1,delay_ms=100,loss=0 --out results/robot-fight/h-d100
```

`--handicap robot=1,delay_ms=D,loss=P` puts a UDP proxy on robot 1's path in
both directions (one-way delay D each way, drop probability P). It is a local
smoke test of link sensitivity, not a radio measurement. Each fight uses a
port block `--port-base + 10·slot` (arena 0/1, PUB 2, proxy 3).

## Running the pieces by hand (what R4 does across namespaces)

```
# arena (UE side): one UDP socket per robot, positions PUB for the bridge
python arena.py --robot-bind ue0=10.45.0.2:6000,ue1=10.45.0.3:6001 \
                --positions-endpoint tcp://127.0.0.1:5570 --time-limit 60 --seed 1 \
                --log arena.jsonl --result arena.json
# brains (gNB / N6 side), one per robot
python brain.py --robot-id 0 --robot 10.45.0.2:6000 --rate-hz 50 --ttl-ms 100 --seed 1 --result b0.json
python brain.py --robot-id 1 --robot 10.45.0.3:6001 --rate-hz 50 --ttl-ms 100 --seed 2 --result b1.json
```

The arena learns each brain's address from the first CMD (`--state-dest` fixes
it instead). A brain exits when a STATE carries the over flag or after
`--max-seconds`.
