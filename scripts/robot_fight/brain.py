#!/usr/bin/env python3
"""One brain per robot: reads STATE, decides, sends CMD over UDP.

The brain runs on its own clock at --rate-hz and never blocks on the arena: a
tick with no fresh state reuses the last one (and counts it). It logs the RTT
carried by STATE echoes, gaps in the STATE sequence (loss), and its own
deadline misses. It exits when a STATE arrives with FLAG_OVER or after
--max-seconds.

Policies are plain functions ``policy(state, params, rng) -> (left, right)``
returning wheel angular-velocity targets in rad/s. The built-in one is
``pusher``. ``--policy module:callable`` plugs another one in (an LLM policy
would go there); it is imported from the venv's sys.path.
"""

from __future__ import annotations

import argparse
import importlib
import json
import math
import pathlib
import random
import socket
import sys
import threading
import time

import numpy as np

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    import protocol  # type: ignore
else:
    from . import protocol

WHEEL_RADIUS = 0.06
WHEEL_BASE = 0.28


def wrap_angle(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


def diff_drive(v: float, w: float) -> tuple[float, float]:
    """Body speed v (m/s) and yaw rate w (rad/s) -> wheel rad/s (left, right)."""
    left = (v - w * WHEEL_BASE / 2) / WHEEL_RADIUS
    right = (v + w * WHEEL_BASE / 2) / WHEEL_RADIUS
    return left, right


DEFAULT_PARAMS = {
    "v_max": 1.6,          # m/s (wheel limit 1.8)
    "k_heading": 5.0,      # rad/s per rad of heading error
    "w_max": 7.0,          # rad/s
    "flank_m": 0.7,        # waypoint this far beside the opponent (perpendicular to its heading)
    "charge_deg": 55.0,    # once the opponent is seen this far off its own heading, charge into it
    "edge_margin_m": 0.45, # slow down when this close to the edge and heading outward
    "noise_rad": 0.02,     # per-tick heading noise (std) when seeded
    "stall_s": 1.5,        # in contact this long -> back off and switch flank
    "backoff_s": 0.6,
}


def pusher(state: protocol.State, params: dict, rng: random.Random) -> tuple[float, float]:
    """Flank, then push. Head-on pushes between equal bots stall, so the bot
    goes to a waypoint beside the opponent (perpendicular to the opponent's
    heading) and charges into its side, which its wheels cannot resist. A
    stalled push backs off and switches flank. Near the edge the bot refuses to
    drive outward at full speed, so it does not push itself out."""
    mem = params.setdefault("_mem", {"stall_since": None, "backoff_until": None, "backoff_turn": 1.0, "side": None})
    ox, oy = state.opp_x, state.opp_y
    rx, ry = ox - state.x, oy - state.y           # me -> opponent
    dist_opp = math.hypot(rx, ry)
    speed = math.hypot(state.vx, state.vy)
    t = state.sim_time_s
    hx, hy = math.cos(state.opp_yaw), math.sin(state.opp_yaw)   # opponent heading
    nx, ny = -hy, hx                                            # opponent's left side
    if mem["side"] is None:
        mem["side"] = 1.0 if (nx * -rx + ny * -ry) >= 0 else -1.0   # the side I am already on
    # Stalemate escape: in contact but not moving -> reverse while turning, then switch flank.
    if mem["backoff_until"] is not None:
        if t < mem["backoff_until"]:
            return diff_drive(-0.6 * params["v_max"], mem["backoff_turn"] * 0.5 * params["w_max"])
        mem["backoff_until"] = None
        mem["stall_since"] = None
        mem["side"] = -mem["side"]
    if dist_opp < 0.5:   # in contact: give a push this long, then disengage
        if mem["stall_since"] is None:
            mem["stall_since"] = t
        elif t - mem["stall_since"] > params["stall_s"]:
            mem["backoff_until"] = t + params["backoff_s"]
            mem["backoff_turn"] = rng.choice((-1.0, 1.0)) if params["noise_rad"] > 0 else 1.0
            mem["stall_since"] = None
    else:
        mem["stall_since"] = None
    # Where am I relative to the opponent's heading? 0 = dead ahead of it, 180 = behind it.
    if dist_opp > 1e-3:
        cos_off = (hx * -rx + hy * -ry) / dist_opp
        off_deg = math.degrees(math.acos(max(-1.0, min(1.0, cos_off))))
    else:
        off_deg = 0.0
    if off_deg >= params["charge_deg"]:
        tx, ty = ox, oy                                   # charge into the opponent's side
    else:
        tx = ox + mem["side"] * nx * params["flank_m"]    # go around to its flank
        ty = oy + mem["side"] * ny * params["flank_m"]
    dx, dy = tx - state.x, ty - state.y
    heading_err = wrap_angle(math.atan2(dy, dx) - state.yaw)
    if params["noise_rad"] > 0:
        heading_err += rng.gauss(0.0, params["noise_rad"])
    w = max(-params["w_max"], min(params["w_max"], params["k_heading"] * heading_err))
    v = params["v_max"] * max(0.0, math.cos(heading_err))
    # Edge guard: heading outward while near the edge -> creep only.
    my_rad = math.hypot(state.x, state.y)
    if my_rad > 1e-3 and state.dist_to_edge_m < params["edge_margin_m"]:
        outward = (math.cos(state.yaw) * state.x + math.sin(state.yaw) * state.y) / my_rad
        if outward > 0.3 and dist_opp > 0.5:
            v *= 0.25
    return diff_drive(v, w)


def load_policy(spec: str):
    if spec == "pusher":
        return pusher
    module_name, _, attr = spec.partition(":")
    if not attr:
        raise SystemExit("--policy must be 'pusher' or module:callable")
    return getattr(importlib.import_module(module_name), attr)


class Brain:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.robot_id = args.robot_id
        self.rng = random.Random(args.seed)
        self.params = dict(DEFAULT_PARAMS)
        if args.params:
            self.params.update(json.loads(args.params))
        if args.seed is not None and args.param_jitter > 0:
            for key in ("v_max", "k_heading", "flank_m"):
                self.params[key] *= 1.0 + self.rng.uniform(-args.param_jitter, args.param_jitter)
        self.policy = load_policy(args.policy)
        host, _, port = args.robot.rpartition(":")
        self.robot_addr = (host, int(port))
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        if args.bind:
            bhost, _, bport = args.bind.rpartition(":")
            self.sock.bind((bhost, int(bport)))
        self.log_path = pathlib.Path(args.log)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log = self.log_path.open("w", encoding="utf-8")
        self.cmd_seq = 0
        self.last_state: protocol.State | None = None
        self.last_state_header: protocol.Header | None = None
        self.last_state_recv_us = 0
        self.states_received = 0
        self.state_gaps = 0
        self.rtt_us: list[int] = []
        self.last_echoed_seq = 0
        self.state_one_way_us: list[int] = []
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.fresh = False
        self.thread = threading.Thread(target=self.receiver, name="brain-rx", daemon=True)
        self.ticks = 0
        self.ticks_without_fresh_state = 0
        self.deadline_misses = 0
        self.over_flags = 0

    def emit(self, record: dict) -> None:
        record.setdefault("t_unix_us", protocol.now_us())
        self.log.write(json.dumps(record, separators=(",", ":")) + "\n")

    def receiver(self) -> None:
        """Blocking receive loop on its own thread so arrival timestamps are
        the real arrival times, not the brain's next tick."""
        self.sock.settimeout(0.05)
        while not self.stop.is_set():
            try:
                data, _ = self.sock.recvfrom(2048)
            except (socket.timeout, BlockingIOError, ConnectionRefusedError):
                continue
            except OSError:
                break
            now = protocol.now_us()
            try:
                header, body = protocol.unpack(data)
            except protocol.ProtocolError as exc:
                with self.lock:
                    self.emit({"event": "bad_datagram", "error": str(exc)})
                continue
            if header.kind != protocol.KIND_STATE or header.robot_id != self.robot_id or not isinstance(body, protocol.State):
                continue
            with self.lock:
                self.states_received += 1
                if self.last_state_header is not None:
                    if header.seq <= self.last_state_header.seq:
                        continue
                    if header.seq > self.last_state_header.seq + 1:
                        self.state_gaps += header.seq - self.last_state_header.seq - 1
                rtt = protocol.rtt_us(header, now)
                if rtt is not None and header.echo_seq != self.last_echoed_seq:
                    # First STATE that echoes a given command: RTT = link round trip
                    # + up to one STATE period. Later echoes of the same command
                    # would only add the brain's own tick period.
                    self.last_echoed_seq = header.echo_seq
                    self.rtt_us.append(rtt)
                self.state_one_way_us.append(now - header.t_send_us)  # valid when clocks are shared
                self.last_state, self.last_state_header, self.last_state_recv_us = body, header, now
                self.fresh = True
                if self.args.log_states:
                    self.emit({"event": "state", "seq": header.seq, "rtt_us": rtt, "one_way_us": now - header.t_send_us,
                               "echo_seq": header.echo_seq, "sim_time_s": round(body.sim_time_s, 4), "flags": body.flags})
                if body.flags & protocol.FLAG_OVER:
                    self.over_flags = body.flags

    def take_state(self) -> tuple[protocol.State | None, bool]:
        with self.lock:
            fresh, self.fresh = self.fresh, False
            return self.last_state, fresh

    def send_command(self, left: float, right: float) -> None:
        self.cmd_seq += 1
        echo_seq = self.last_state_header.seq if self.last_state_header else 0
        echo_t = self.last_state_header.t_send_us if self.last_state_header else 0
        header = protocol.Header(protocol.KIND_CMD, self.robot_id, self.cmd_seq, protocol.now_us(), echo_seq, echo_t)
        try:
            self.sock.sendto(protocol.pack_command(header, protocol.Command(left, right, self.args.ttl_ms)), self.robot_addr)
        except OSError as exc:
            self.emit({"event": "send_error", "error": str(exc)})

    def run(self) -> dict:
        period = 1.0 / self.args.rate_hz
        t0 = time.perf_counter()
        next_tick = t0
        deadline = t0 + self.args.max_seconds
        self.thread.start()
        # Kick: send a zero command so the arena learns our address and starts sending STATE.
        self.send_command(0.0, 0.0)
        while time.perf_counter() < deadline:
            now = time.perf_counter()
            if now < next_tick:
                time.sleep(min(next_tick - now, period))
                continue
            if now - next_tick > period:
                self.deadline_misses += 1
                next_tick = now  # resync rather than burst
            next_tick += period
            self.ticks += 1
            state, fresh = self.take_state()
            if self.over_flags:
                break
            if state is None:
                self.send_command(0.0, 0.0)
                continue
            if not fresh:
                self.ticks_without_fresh_state += 1
            left, right = self.policy(state, self.params, self.rng)
            with self.lock:
                self.send_command(left, right)
        self.stop.set()
        self.thread.join(timeout=0.5)
        return self.summary()

    def summary(self) -> dict:
        rtt = np.array(self.rtt_us, dtype=np.int64) if self.rtt_us else np.array([0])
        ow = np.array(self.state_one_way_us, dtype=np.int64) if self.state_one_way_us else np.array([0])
        outcome = "unknown"
        if self.over_flags & protocol.FLAG_WON:
            outcome = "won"
        elif self.over_flags & protocol.FLAG_LOST:
            outcome = "lost"
        elif self.over_flags & protocol.FLAG_OVER:
            outcome = "draw"
        result = {
            "robot_id": self.robot_id, "policy": self.args.policy, "seed": self.args.seed,
            "params": {k: v for k, v in self.params.items() if not k.startswith("_")},
            "rate_hz": self.args.rate_hz, "ttl_ms": self.args.ttl_ms, "outcome": outcome,
            "ticks": self.ticks, "deadline_misses": self.deadline_misses,
            "ticks_without_fresh_state": self.ticks_without_fresh_state, "cmds_sent": self.cmd_seq,
            "states_received": self.states_received, "state_seq_gaps": self.state_gaps,
            "rtt_us": {"p50": int(np.percentile(rtt, 50)), "p90": int(np.percentile(rtt, 90)),
                       "p99": int(np.percentile(rtt, 99)), "max": int(rtt.max()), "n": len(self.rtt_us)},
            "state_one_way_us": {"p50": int(np.percentile(ow, 50)), "p99": int(np.percentile(ow, 99)),
                                 "max": int(ow.max()), "n": len(self.state_one_way_us)},
        }
        self.emit({"event": "summary", **result})
        return result

    def close(self) -> None:
        self.log.close()
        self.sock.close()


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--robot-id", type=int, required=True, choices=(0, 1))
    p.add_argument("--robot", required=True, help="arena UDP address for this robot, host:port")
    p.add_argument("--bind", default=None, help="local host:port to bind (default: ephemeral)")
    p.add_argument("--rate-hz", type=float, default=50.0)
    p.add_argument("--ttl-ms", type=int, default=100, help="how long the robot may keep applying a command")
    p.add_argument("--policy", default="pusher", help="'pusher' or module:callable")
    p.add_argument("--params", default=None, help="JSON overrides for policy params")
    p.add_argument("--param-jitter", type=float, default=0.1, help="seeded +-fraction applied to v_max/k_heading/flank_m")
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--max-seconds", type=float, default=120.0)
    p.add_argument("--log-states", action="store_true", help="log every STATE (large)")
    p.add_argument("--log", default="brain.jsonl")
    p.add_argument("--result", default=None)
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    brain = Brain(args)
    try:
        result = brain.run()
    finally:
        brain.close()
    if args.result:
        pathlib.Path(args.result).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("robot_id", "outcome", "cmds_sent", "states_received", "rtt_us")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
