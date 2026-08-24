#!/usr/bin/env python3
"""SIMO steering supervisor -- the 1x4 rank-1 demo backend.

The broker has no runtime swap for `fixed_mimo` links (scalar and
profile_swap are rejected by design, and no fixed_mimo_swap message exists
yet -- see docs/plans/fixed-mimo-swap.md for the proposed one). Until that
lands, a steering swap is a broker RESTART with a re-rendered topology:
this process owns the broker subprocess, renders the 1x4 fixed_mimo YAML
from a named steering vector, and restarts the broker on request (~1-2 s
gap, which the page shows as a "re-steering" badge -- the same drill the
rehearsal plan wants for broker-restart-mid-demo anyway).

Control surface (ZMQ REP, default tcp://127.0.0.1:5565):
  {"cmd": "steering", "pattern": "A"|"B"}  -> restart broker on new vector
  {"cmd": "status"}                        -> current pattern + expected powers

The channel is deterministic (single 0 dB tap, no fading), so each RX port's
power is exactly |a_r|^2 and the bars sit on their analytic markers.
"""

import argparse
import json
import signal
import subprocess
import sys
import time
from pathlib import Path

import zmq

# |a_r| per gnb RX port; power bars show |a_r|^2. B is A reversed, so the
# swap visibly REORDERS the bars (the plan's S4 observable).
STEERINGS = {
    "A": [0.90, 0.55, 0.35, 0.20],
    "B": [0.20, 0.35, 0.55, 0.90],
}

TOPOLOGY = """\
# RENDERED by simo_supervisor.py -- do not edit; pattern {pattern}
runtime:
  backend: cuda
  gpu_device: 0
  batch_samples: 23040
  queue_samples: 2457600
devices:
  - id: ue_p0
    role: ue
    sample_rate_hz: 23040000
    tx_endpoint: tcp://127.0.0.1:16300
    rx_endpoint: tcp://*:16301
{gnb_devices}radio_nodes:
  - id: ue
    tx_ports:
      - ue_p0
    rx_ports:
      - ue_p0
  - id: gnb
    tx_ports:
      - gnb_p0
      - gnb_p1
      - gnb_p2
      - gnb_p3
    rx_ports:
      - gnb_p0
      - gnb_p1
      - gnb_p2
      - gnb_p3
links:
  - from: ue
    to: gnb
    model: ul_simo_1x4
  # Return direction only exists to satisfy the validator (every device must
  # source and sink a link); nothing on the page reads the UE RX port.
  - from: gnb
    to: ue
    model: dl_ref
models:
  dl_ref:
    chain:
      - type: tdl
        taps:
          - delay_samples: 0.0
            gain_db: 0.0
  ul_simo_1x4:
    fixed_mimo:
      coefficients:
{coefficients}    chain:
      - type: tdl
        taps:
          - delay_samples: 0.0
            gain_db: 0.0
"""


def render(pattern: str) -> str:
    gnb = ""
    for r in range(4):
        gnb += (f"  - id: gnb_p{r}\n    role: gnb\n    sample_rate_hz: 23040000\n"
                f"    tx_endpoint: tcp://127.0.0.1:{16302 + 2 * r}\n"
                f"    rx_endpoint: tcp://*:{16303 + 2 * r}\n")
    coeff = ""
    for r, a in enumerate(STEERINGS[pattern]):
        coeff += (f"        - tap: 0\n          rx: {r}\n          tx: 0\n"
                  f"          real: {a}\n          imag: 0.0\n")
    return TOPOLOGY.format(pattern=pattern, gnb_devices=gnb, coefficients=coeff)


def expected(pattern: str) -> dict:
    return {f"gnb_rx{r}": round(a * a, 4) for r, a in enumerate(STEERINGS[pattern])}


class Supervisor:
    def __init__(self, broker_bin: str, yaml_path: Path, duration_s: int,
                 control: str, telemetry: str):
        self.broker_bin = broker_bin
        self.yaml_path = yaml_path
        self.duration_s = duration_s
        self.control = control
        self.telemetry = telemetry
        self.pattern = "A"
        self.proc = None
        self.deadline = time.monotonic() + duration_s

    def start_broker(self) -> None:
        remaining = max(5, int(self.deadline - time.monotonic()))
        self.yaml_path.write_text(render(self.pattern))
        self.proc = subprocess.Popen(
            [self.broker_bin, "--config", str(self.yaml_path),
             "--duration", f"{remaining}s",
             "--control-endpoint", self.control,
             "--telemetry-endpoint", self.telemetry, "--telemetry-rate-hz", "10"],
            stdout=open(self.yaml_path.with_suffix(".broker.log"), "ab"),
            stderr=subprocess.STDOUT)
        print(f"event=broker_start pattern={self.pattern} pid={self.proc.pid}",
              flush=True)

    def stop_broker(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        self.proc = None

    def swap(self, pattern: str) -> dict:
        if pattern not in STEERINGS:
            return {"ok": False, "error": f"unknown pattern: {pattern}"}
        t0 = time.time()
        self.pattern = pattern
        self.stop_broker()
        self.start_broker()
        return {"ok": True, "pattern": pattern, "expected": expected(pattern),
                "restart_s": round(time.time() - t0, 2),
                "note": "broker restarted (no fixed_mimo runtime swap yet)"}

    def status(self) -> dict:
        alive = self.proc is not None and self.proc.poll() is None
        return {"ok": True, "pattern": self.pattern,
                "expected": expected(self.pattern), "broker_alive": alive,
                "patterns": {k: [round(a * a, 4) for a in v]
                             for k, v in STEERINGS.items()}}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--broker", required=True, help="path to ocudu-gpu-channel")
    ap.add_argument("--rep", default="tcp://127.0.0.1:5565")
    ap.add_argument("--control", default="tcp://*:5562")
    ap.add_argument("--telemetry", default="tcp://*:5563")
    ap.add_argument("--yaml", default=None, help="where to render the topology")
    ap.add_argument("--duration", type=int, default=7200)
    args = ap.parse_args()

    yaml_path = Path(args.yaml or Path(__file__).parent / "run-logs"
                     / "topology.simo-rendered.cuda.yaml")
    yaml_path.parent.mkdir(parents=True, exist_ok=True)

    sup = Supervisor(args.broker, yaml_path, args.duration,
                     args.control, args.telemetry)
    # The run script stops this process with SIGTERM; without a handler the
    # broker child would be orphaned and keep its ports.
    def on_sigterm(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, on_sigterm)
    sup.start_broker()

    ctx = zmq.Context.instance()
    rep = ctx.socket(zmq.REP)
    rep.setsockopt(zmq.RCVTIMEO, 500)
    rep.setsockopt(zmq.LINGER, 0)
    rep.bind(args.rep)
    print(f"event=start rep={args.rep}", flush=True)

    try:
        while time.monotonic() < sup.deadline:
            if sup.proc is not None and sup.proc.poll() is not None \
               and time.monotonic() < sup.deadline - 5:
                print("event=broker_died restarting", flush=True)
                sup.start_broker()
            try:
                msg = json.loads(rep.recv_string())
            except zmq.Again:
                continue
            except json.JSONDecodeError:
                rep.send_string(json.dumps({"ok": False, "error": "bad json"}))
                continue
            cmd = msg.get("cmd")
            if cmd == "steering":
                out = sup.swap(msg.get("pattern", ""))
            elif cmd == "status":
                out = sup.status()
            else:
                out = {"ok": False, "error": f"unknown cmd: {cmd}"}
            rep.send_string(json.dumps(out))
            print(f"event=cmd cmd={cmd} ok={out['ok']}", flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        sup.stop_broker()
        rep.close()
        print("event=stop", flush=True)
        sys.exit(0)


if __name__ == "__main__":
    main()
