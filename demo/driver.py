#!/usr/bin/env python3
"""C4 -- demo driver: scenario scripts behind (or instead of) the UI buttons.

Talks to the bridge's /api/control endpoint, so the page badge and |H|
heatmap stay in sync with what the driver does (going straight to the broker
REQ would leave the page's declared-state view behind).

  driver.py correlate [--tx-re 0.4]   turn the TX-side correlation on
  driver.py iid                       back to independent lanes
  driver.py path-loss 12              set path_loss_db on both links
  driver.py sweep [--period 20] [--cycles 0]
      the closed-loop "agentic" scenario: alternate correlated <-> iid every
      period/2 seconds while ramping path loss up and back down, so every
      panel on the page visibly reacts without anyone touching a button.
      cycles=0 loops until interrupted.
"""

import argparse
import json
import sys
import time
import urllib.request


def post(bridge: str, body: dict) -> dict:
    req = urllib.request.Request(
        f"{bridge}/api/control", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--bridge", default="http://127.0.0.1:8080")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("correlate")
    p.add_argument("--tx-re", type=float, default=0.4)
    sub.add_parser("iid")
    p = sub.add_parser("path-loss")
    p.add_argument("value", type=float)
    p = sub.add_parser("sweep")
    p.add_argument("--period", type=float, default=20.0,
                   help="seconds per correlated<->iid cycle")
    p.add_argument("--cycles", type=int, default=0, help="0 = until interrupted")
    args = ap.parse_args()

    if args.cmd == "correlate":
        out = post(args.bridge, {"action": "correlate", "tx_re": args.tx_re})
    elif args.cmd == "iid":
        out = post(args.bridge, {"action": "iid"})
    elif args.cmd == "path-loss":
        out = post(args.bridge, {"action": "path_loss", "value": args.value})
    else:  # sweep
        cycle = 0
        try:
            while args.cycles == 0 or cycle < args.cycles:
                cycle += 1
                for state, action in (("correlated", {"action": "correlate"}),
                                      ("iid", {"action": "iid"})):
                    r = post(args.bridge, action)
                    print(f"cycle={cycle} -> {state} ok={r['ok']}", flush=True)
                    # ramp path loss 0 -> 6 -> 0 dB inside the half-period so
                    # the fading sparkline and bars move together
                    half = args.period / 2
                    for frac, db in ((0.25, 3.0), (0.5, 6.0), (0.75, 3.0), (1.0, 0.0)):
                        time.sleep(half * 0.25)
                        post(args.bridge, {"action": "path_loss", "value": db})
        except KeyboardInterrupt:
            post(args.bridge, {"action": "iid"})
            post(args.bridge, {"action": "path_loss", "value": 0.0})
            print("\nsweep stopped; broker returned to iid / 0 dB", flush=True)
            return
        out = {"ok": True}

    print(json.dumps(out, indent=2))
    sys.exit(0 if out.get("ok") else 1)


if __name__ == "__main__":
    main()
