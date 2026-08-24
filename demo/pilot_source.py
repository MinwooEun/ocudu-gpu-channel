#!/usr/bin/env python3
"""L2 pilot source -- TX alternation so the page's |H| heatmap is MEASURED.

Serves the broker's four TX pull endpoints (REP, same wire protocol as
ocudu-zmq-source: dummy-byte request -> cf32 batch reply, unit-power tone
with a 4096-sample period) but gates each port on a shared schedule:

  cycle = [ both ports 250 ms | port0 only 250 ms | port1 only 250 ms
            | silence 150 ms ]                                  (900 ms)

During "both" the RX rows see |h_r0(+)h_r1|^2 -- the original 6.94/9.71
observable. During a single-TX phase a row sees |h_rc|^2 alone, which is the
per-column measurement that fills the 2x2 heatmap (plan L2). The silence gap
produces exact zeros at the sinks, which is what the meter anchors its phase
clock on -- no side channel needed, the alignment marker travels through the
channel itself.

The schedule is driven by the per-port SAMPLE COUNTER, not wall time: the
broker pulls all ports on the same slot cadence, so counting samples keeps
the four ports phase-locked to each other by construction. Phase durations
are whole batches (250/150 ms at 1 ms per batch), so no batch straddles a
boundary.
"""

import argparse
import threading
import time

import numpy as np
import zmq

TONE_PERIOD = 4096          # samples, matches ocudu-zmq-source
BATCH = 23040               # samples per reply = 1 ms at 23.04 Msps


def build_batches():
    """8 tone batches covering lcm(4096, 23040) samples, then it repeats."""
    n = np.arange(BATCH * 8, dtype=np.float64)
    phase = (n % TONE_PERIOD) / TONE_PERIOD * 2.0 * np.pi
    tone = np.empty(BATCH * 8 * 2, dtype=np.float32)
    tone[0::2] = np.cos(phase)
    tone[1::2] = np.sin(phase)
    raw = tone.tobytes()
    per = BATCH * 8  # bytes per batch (2 floats * 4 bytes / 2 samples... = 8*BATCH)
    return [raw[i * per:(i + 1) * per] for i in range(8)]


def serve_port(endpoint: str, role: int, phases_ms, stop: threading.Event) -> None:
    """role 0 = p0 (on in both+tx0), role 1 = p1 (on in both+tx1)."""
    tone_batches = build_batches()
    silence = b"\x00" * len(tone_batches[0])
    both_ms, tx0_ms, tx1_ms, gap_ms = phases_ms
    cycle_ms = both_ms + tx0_ms + tx1_ms + gap_ms

    ctx = zmq.Context.instance()
    rep = ctx.socket(zmq.REP)
    rep.setsockopt(zmq.RCVTIMEO, 100)
    rep.setsockopt(zmq.SNDTIMEO, 100)
    rep.setsockopt(zmq.LINGER, 0)
    rep.bind(endpoint)

    batches = 0  # one batch == one ms of samples
    while not stop.is_set():
        try:
            rep.recv()
        except zmq.Again:
            continue
        pos = batches % cycle_ms
        if pos < both_ms:
            on = True
        elif pos < both_ms + tx0_ms:
            on = role == 0
        elif pos < both_ms + tx0_ms + tx1_ms:
            on = role == 1
        else:
            on = False
        payload = tone_batches[batches % 8] if on else silence
        while not stop.is_set():
            try:
                rep.send(payload)
                break
            except zmq.Again:
                continue
        batches += 1
    rep.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", action="append", required=True, metavar="ROLE=ENDPOINT",
                    help="e.g. --port 0=tcp://*:16200 --port 1=tcp://*:16202 "
                         "(role 0/1 = which single-TX phase this port owns)")
    ap.add_argument("--both-ms", type=int, default=250)
    ap.add_argument("--tx0-ms", type=int, default=250)
    ap.add_argument("--tx1-ms", type=int, default=250)
    ap.add_argument("--gap-ms", type=int, default=150)
    ap.add_argument("--duration", type=float, default=0.0)
    args = ap.parse_args()

    phases = (args.both_ms, args.tx0_ms, args.tx1_ms, args.gap_ms)
    stop = threading.Event()
    threads = []
    for spec in args.port:
        role, _, endpoint = spec.partition("=")
        t = threading.Thread(target=serve_port, name=f"src-{endpoint}",
                             args=(endpoint, int(role), phases, stop), daemon=True)
        t.start()
        threads.append(t)
    print(f"event=start ports={len(threads)} cycle_ms={sum(phases)} "
          f"phases=both:{phases[0]},tx0:{phases[1]},tx1:{phases[2]},gap:{phases[3]}",
          flush=True)
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
