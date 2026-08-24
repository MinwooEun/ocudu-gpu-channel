#!/usr/bin/env python3
"""C1 -- per-port power meter for the MIMO live demo.

Drains broker RX endpoints exactly the way ocudu-zmq-sink does (REQ dummy
byte -> REP cf32 IQ batch, one request outstanding) but instead of a single
end-of-run avg_power it emits sliding-window per-port averages as JSON over
ZMQ PUSH, for the bridge (C2) to merge into the page feed.

Frame shape (one per port per emit tick):
  { "port": "ue_rx0", "t": 1724480000.0, "avg_power": 6.91,
    "cumulative_power": 6.93, "window_s": 0.5, "batches": 5012 }

avg_power is the mean |x|^2 over the trailing window; cumulative_power is the
run-long mean, which is what the S1 gate compares against the analytic
expectations (9.71 correlated / 6.94 iid, mean over the four RX ports).
"""

import argparse
import json
import threading
import time
from collections import deque

import numpy as np
import zmq


class PhaseWindow:
    """Sliding sum/count of (t, power_sum, sample_count) batch entries."""

    def __init__(self, span_s: float):
        self.span = span_s
        self.entries = deque()
        self.psum = 0.0
        self.count = 0

    def add(self, t: float, p: float, n: int) -> None:
        self.entries.append((t, p, n))
        self.psum += p
        self.count += n

    def prune(self, now: float) -> None:
        while self.entries and self.entries[0][0] < now - self.span:
            _, p, n = self.entries.popleft()
            self.psum -= p
            self.count -= n

    def mean(self):
        return (self.psum / self.count) if self.count else None


class PilotClock:
    """Recovers the pilot cycle position from the received power itself.

    The pilot source ends each cycle with a silence gap; the sinks see exact
    zeros there (a Rayleigh fade never is), so a run of zero batches followed
    by an active one marks cycle position 0. Everything between is classified
    by elapsed time, with a guard band around each boundary to absorb queue
    jitter and the delay-line tail.
    """

    def __init__(self, both_ms: int, tx0_ms: int, tx1_ms: int, gap_ms: int,
                 guard_ms: float = 50.0):
        self.bounds = (both_ms / 1e3, (both_ms + tx0_ms) / 1e3,
                       (both_ms + tx0_ms + tx1_ms) / 1e3)
        self.cycle = (both_ms + tx0_ms + tx1_ms + gap_ms) / 1e3
        self.min_gap = (gap_ms / 1e3) * 0.5
        self.guard = guard_ms / 1e3
        self.anchor = None
        self.zero_since = None

    def classify(self, t: float, mean_power: float):
        """Returns 'both' | 'tx0' | 'tx1' | 'gap' | None (guard/unsynced)."""
        zero = mean_power < 1e-9
        if zero:
            if self.zero_since is None:
                self.zero_since = t
        else:
            if self.zero_since is not None and t - self.zero_since >= self.min_gap:
                self.anchor = t  # silence just ended: cycle position 0
            self.zero_since = None
        if self.anchor is None:
            return None
        pos = (t - self.anchor) % self.cycle
        if zero:
            return "gap"
        b0, b1, b2 = self.bounds
        for lo, hi, phase in ((0.0, b0, "both"), (b0, b1, "tx0"), (b1, b2, "tx1")):
            if lo + self.guard <= pos < hi - self.guard:
                return phase
        return None  # inside a guard band


def drain_port(name: str, endpoint: str, push_endpoint: str,
               window_s: float, emit_hz: float, stop: threading.Event,
               pilot: "PilotClock | None" = None,
               pilot_window_s: float = 2.0) -> None:
    ctx = zmq.Context.instance()

    def fresh_req():
        s = ctx.socket(zmq.REQ)
        s.setsockopt(zmq.RCVTIMEO, 100)
        s.setsockopt(zmq.SNDTIMEO, 100)
        s.setsockopt(zmq.LINGER, 0)
        s.connect(endpoint)
        return s

    req = fresh_req()

    push = ctx.socket(zmq.PUSH)
    push.setsockopt(zmq.LINGER, 0)
    push.setsockopt(zmq.SNDHWM, 100)
    push.connect(push_endpoint)

    # 'both' keeps the original avg_power semantics (the 6.94/9.71
    # observable); tx0/tx1 windows are longer because each collects only a
    # quarter of the duty cycle.
    win_both = PhaseWindow(window_s if pilot is None else max(window_s, 1.0))
    win_h = {"tx0": PhaseWindow(pilot_window_s), "tx1": PhaseWindow(pilot_window_s)}
    total_sum = 0.0
    total_count = 0
    batches = 0
    awaiting_reply = False
    await_since = 0.0
    next_emit = time.monotonic()

    while not stop.is_set():
        # Same discipline as the C++ sink: exactly one request outstanding --
        # but if the broker died mid-request (demo failure drill / SIMO
        # steering restart), the reply never comes and a REQ socket wedges.
        # Recreate it so the meter rides through broker restarts.
        if awaiting_reply and time.monotonic() - await_since > 1.0:
            req.close()
            req = fresh_req()
            awaiting_reply = False
        if not awaiting_reply:
            try:
                req.send(b"\x00")
                awaiting_reply = True
                await_since = time.monotonic()
            except zmq.Again:
                time.sleep(0.05)
        if awaiting_reply:
            try:
                msg = req.recv()
                awaiting_reply = False
                if len(msg) >= 8 and len(msg) % 8 == 0:
                    iq = np.frombuffer(msg, dtype=np.complex64)
                    p = float(np.sum(iq.real.astype(np.float64) ** 2
                                     + iq.imag.astype(np.float64) ** 2))
                    now = time.monotonic()
                    batches += 1
                    if pilot is None:
                        win_both.add(now, p, iq.size)
                        total_sum += p
                        total_count += iq.size
                    else:
                        phase = pilot.classify(now, p / iq.size)
                        if phase == "both":
                            win_both.add(now, p, iq.size)
                            total_sum += p
                            total_count += iq.size
                        elif phase in win_h:
                            win_h[phase].add(now, p, iq.size)
            except zmq.Again:
                pass  # reply not ready; keep waiting on the same request

        now = time.monotonic()
        win_both.prune(now)
        for w in win_h.values():
            w.prune(now)

        if now >= next_emit:
            next_emit = now + 1.0 / emit_hz
            frame = {
                "port": name,
                "t": time.time(),
                "avg_power": win_both.mean() or 0.0,
                "cumulative_power": (total_sum / total_count) if total_count else 0.0,
                "window_s": win_both.span,
                "batches": batches,
            }
            if pilot is not None:
                frame["mode"] = "pilot" if pilot.anchor is not None else "sync"
                h0 = win_h["tx0"].mean()
                h1 = win_h["tx1"].mean()
                if h0 is not None:
                    frame["h0_power"] = h0
                if h1 is not None:
                    frame["h1_power"] = h1
            try:
                push.send_string(json.dumps(frame), zmq.DONTWAIT)
            except zmq.Again:
                pass  # bridge not draining; drop rather than stall the meter

    req.close()
    push.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", action="append", required=True, metavar="NAME=ENDPOINT",
                    help="e.g. --port ue_rx0=tcp://127.0.0.1:16205 (repeatable)")
    ap.add_argument("--push", default="tcp://127.0.0.1:5561",
                    help="bridge PULL endpoint for meter frames")
    ap.add_argument("--window", type=float, default=0.5, help="sliding window seconds")
    ap.add_argument("--emit-hz", type=float, default=10.0, help="frames per second per port")
    ap.add_argument("--duration", type=float, default=0.0,
                    help="seconds to run; 0 = until interrupted")
    ap.add_argument("--pilot", metavar="BOTH,TX0,TX1,GAP", default=None,
                    help="pilot-alternation phase lengths in ms (match "
                         "pilot_source.py, e.g. 250,250,250,150); enables "
                         "per-column h0/h1 measurement")
    ap.add_argument("--pilot-window", type=float, default=2.0,
                    help="sliding window seconds for the h0/h1 phases")
    args = ap.parse_args()

    pilot_ms = None
    if args.pilot:
        pilot_ms = tuple(int(x) for x in args.pilot.split(","))
        if len(pilot_ms) != 4:
            ap.error("--pilot needs four comma-separated ms values")

    stop = threading.Event()
    threads = []
    for spec in args.port:
        name, _, endpoint = spec.partition("=")
        if not endpoint:
            ap.error(f"bad --port spec: {spec}")
        pilot = PilotClock(*pilot_ms) if pilot_ms else None
        t = threading.Thread(target=drain_port, name=f"meter-{name}",
                             args=(name, endpoint, args.push, args.window,
                                   args.emit_hz, stop, pilot,
                                   args.pilot_window), daemon=True)
        t.start()
        threads.append(t)
    print(f"event=start ports={len(threads)} push={args.push} "
          f"window_s={args.window} emit_hz={args.emit_hz} "
          f"pilot={args.pilot or 'off'}", flush=True)

    try:
        if args.duration > 0:
            time.sleep(args.duration)
        else:
            while True:
                time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        for t in threads:
            t.join(timeout=2)
        print("event=stop", flush=True)


if __name__ == "__main__":
    main()
