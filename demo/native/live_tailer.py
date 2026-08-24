#!/usr/bin/env python3
"""Host-side tailer for the live-radio demo tier.

The RAN stack runs inside rootless namespaces; everything it can tell the
page comes out through the shared filesystem. This process tails those files
and pushes JSON frames to the bridge's meter PULL socket:

  ue_metrics    srsUE metrics CSV (rsrp, pathloss, dl_snr, brates, ...)
  ping          the continuous in-netns ping (RTT per reply, loss counter)
  stack         bring-up phase from live-status.json + attach flags parsed
                out of srsue.log
"""

import argparse
import json
import math
import os
import re
import time

import zmq

INTERESTING = ("rsrp", "pl", "cfo", "dl_mcs", "dl_snr", "dl_brate", "dl_bler",
               "ul_mcs", "ul_brate", "ul_bler", "is_attached")
PING_RE = re.compile(r"icmp_seq=(\d+) ttl=\d+ time=([\d.]+) ms")


class Tail:
    """Follow a file that may not exist yet; yields complete new lines."""

    def __init__(self, path: str):
        self.path = path
        self.pos = 0
        self.buf = ""

    def lines(self):
        try:
            size = os.path.getsize(self.path)
        except OSError:
            return
        if size < self.pos:      # rotated/truncated
            self.pos = 0
        if size == self.pos:
            return
        with open(self.path, "r", errors="replace") as f:
            f.seek(self.pos)
            chunk = f.read()
            self.pos = f.tell()
        self.buf += chunk
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            yield line


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--metrics-csv", required=True)
    ap.add_argument("--ping-log", required=True)
    ap.add_argument("--srsue-log", required=True)
    ap.add_argument("--status-json", required=True)
    ap.add_argument("--push", default="tcp://127.0.0.1:5566")
    args = ap.parse_args()

    ctx = zmq.Context.instance()
    push = ctx.socket(zmq.PUSH)
    push.setsockopt(zmq.LINGER, 0)
    push.setsockopt(zmq.SNDHWM, 100)
    push.connect(args.push)

    def emit(frame: dict) -> None:
        frame["t"] = time.time()
        try:
            push.send_string(json.dumps(frame), zmq.DONTWAIT)
        except zmq.Again:
            pass

    csv_tail = Tail(args.metrics_csv)
    ping_tail = Tail(args.ping_log)
    header = None
    rrc = pdu = False
    last_seq = None
    lost = 0
    next_stack = 0.0

    print("event=start", flush=True)
    while True:
        for line in csv_tail.lines():
            cells = line.strip().split(";")
            if header is None and cells and cells[0] == "time":
                header = cells
                continue
            if header is None or len(cells) < len(INTERESTING) or cells[0] == "time":
                continue
            row = dict(zip(header, cells))
            frame = {"port": "ue_metrics"}
            for key in INTERESTING:
                value = row.get(key, "")
                try:
                    number = float(value)
                except ValueError:
                    continue
                # srsUE reports 'nan' for e.g. dl_snr with no recent grants;
                # json would serialize it as a bare NaN token, which the
                # browser's JSON.parse rejects -- drop the field instead.
                if math.isfinite(number):
                    frame[key] = number
            if len(frame) > 1:
                emit(frame)

        for line in ping_tail.lines():
            m = PING_RE.search(line)
            if not m:
                continue
            seq, rtt = int(m.group(1)), float(m.group(2))
            if last_seq is not None and seq > last_seq + 1:
                lost += seq - last_seq - 1
            last_seq = seq
            emit({"port": "ping", "rtt_ms": rtt, "seq": seq, "lost": lost})

        now = time.monotonic()
        if now >= next_stack:
            next_stack = now + 1.0
            phase = "unknown"
            try:
                with open(args.status_json) as f:
                    phase = json.load(f).get("phase", "unknown")
            except (OSError, json.JSONDecodeError):
                pass
            if not (rrc and pdu):
                try:
                    with open(args.srsue_log, errors="replace") as f:
                        text = f.read()
                    rrc = rrc or ("RRC Connected" in text)
                    pdu = pdu or ("PDU Session Establishment successful" in text)
                except OSError:
                    pass
            emit({"port": "stack", "phase": phase,
                  "rrc": int(rrc), "pdu": int(pdu)})
        time.sleep(0.2)


if __name__ == "__main__":
    main()
