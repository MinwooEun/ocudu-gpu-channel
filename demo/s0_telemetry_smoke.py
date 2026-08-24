#!/usr/bin/env python3
"""S0 -- telemetry smoke test.

Subscribes to the broker telemetry PUB, captures frames for a few seconds,
and reports the exact frame shape (topics, multipart layout, live{} keys).
The captured keys define the bridge data contract (plan Appendix B); this run
closes the documented "telemetry never exercised against a live subscriber"
caveat.

Usage: run a broker with --telemetry-endpoint tcp://*:5560 first, then
  python3 s0_telemetry_smoke.py [--endpoint tcp://localhost:5560] [--seconds 5]
"""

import argparse
import json
import time

import zmq


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", default="tcp://localhost:5560")
    ap.add_argument("--seconds", type=float, default=5.0)
    ap.add_argument("--out", default=None,
                    help="write a sample of decoded frames to this JSON file")
    args = ap.parse_args()

    ctx = zmq.Context.instance()
    sub = ctx.socket(zmq.SUB)
    sub.setsockopt(zmq.RCVTIMEO, 200)
    sub.setsockopt(zmq.LINGER, 0)
    sub.connect(args.endpoint)
    sub.setsockopt_string(zmq.SUBSCRIBE, "")

    frames = []
    topics = {}
    deadline = time.monotonic() + args.seconds
    while time.monotonic() < deadline:
        try:
            parts = sub.recv_multipart()
        except zmq.Again:
            continue
        # v3.0 layout: ONE part, "<link_id topic prefix>{json...}" -- the topic
        # is a plain prefix of the payload byte-string (classic ZMQ prefix
        # subscription), not a separate multipart frame.
        decoded = None
        topic = "(none)"
        for part in reversed(parts):
            brace = part.find(b"{")
            if brace < 0:
                continue
            try:
                decoded = json.loads(part[brace:].decode())
                topic = part[:brace].decode(errors="replace") or "(empty-prefix)"
                break
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
        if len(parts) > 1:
            topic = parts[0].decode(errors="replace")
        topics[topic] = topics.get(topic, 0) + 1
        if decoded is not None:
            frames.append({"topic": topic, "parts": len(parts), "frame": decoded})

    print(f"captured={len(frames)} frames in {args.seconds}s "
          f"({len(frames)/args.seconds:.1f} Hz) endpoint={args.endpoint}")
    print(f"topics: {topics}")
    if frames:
        sample = frames[-1]
        print(f"multipart layout: {sample['parts']} part(s), topic prefix = link_id")
        print("top-level keys:", sorted(sample["frame"].keys()))
        live = sample["frame"].get("live")
        if isinstance(live, dict):
            print("live{} keys:", sorted(live.keys()))
        print("sample frame:")
        print(json.dumps(sample["frame"], indent=2))
        if args.out:
            with open(args.out, "w") as f:
                json.dump({"endpoint": args.endpoint,
                           "captured": len(frames),
                           "seconds": args.seconds,
                           "topics": topics,
                           "samples": frames[-4:]}, f, indent=2)
            print(f"wrote {args.out}")
    else:
        raise SystemExit("GATE FAILED: no telemetry frames received")


if __name__ == "__main__":
    main()
