#!/usr/bin/env python3
"""C2 -- bridge/web server for the MIMO live demo (prototype).

Single file, stdlib + pyzmq + numpy-free. Browsers cannot speak ZMQ, so this
process is the mandatory middle layer:

  (a) SUBs the broker telemetry PUB (default :5560, v3.0 single-part frames,
      topic prefix = link_id),
  (b) PULLs power-meter frames from C1 (default bind :5561),
  (c) exposes broker REQ control actions as POST /api/control for the UI
      buttons (default broker REP :5559),
  (d) serves the static page and pushes merged state to the browser at
      ~10 Hz over Server-Sent Events (GET /events) -- SSE instead of
      WebSocket so the whole thing runs on the stdlib.

Only the HTTP port (default 8080) needs to be reachable from the demo laptop;
5559/5560/5561 stay on the workstation.

Data contract pushed to the page (plan Appendix B, filled from the S0
capture -- see contract/telemetry-sample.json):

  { "t": <epoch>,
    "channel": { "<link_id>": { "slot": 0, "seqno": 0,
        "live": { "path_loss_db": 0, "awgn_snr_db": 60, "cfo_hz": 0,
                  "tap0_delay_samples": 0, "tap0_gain_db": -13.4,
                  "tap0_phase_rad": 0, "los_k_db": 0 },
        "profile_active": false, "warmup_until_slot": 0, "age_s": 0.1 } },
    "power": { "<port>": { "avg_power": 6.9, "cumulative_power": 6.9,
                            "window_s": 0.5, "age_s": 0.05 } },
    "correlation": { "state": "iid"|"correlated", "tx_re": 0.4 },
    "expected": { "correlated": 9.71, "iid": 6.94 },
    "gpu": { "kernel_us": 97, "slot_budget_us": 500 },
    "telemetry_hz": 19.8 }
"""

import argparse
import json
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import zmq

STATE_LOCK = threading.Lock()
STATE = {
    "channel": {},          # link_id -> last telemetry frame (+ rx time)
    "power": {},            # port -> last meter frame (+ rx time)
    # |H| on the page is DECLARED state (L1): telemetry carries scalar link
    # params only, so the correlation shown is what the last accepted control
    # action set, not a measurement.
    "correlation": {"state": "iid", "tx_re": 0.0},
    "expected": {"correlated": 9.71, "iid": 6.94},
    "gpu": {"kernel_us": 97, "slot_budget_us": 500},
    "events": deque(maxlen=40),   # {t, action, label} for sparkline markers
}
TELEMETRY_TIMES = deque(maxlen=100)   # for the measured telemetry-Hz card

ARGS = None
ZCTX = zmq.Context.instance()


def telemetry_thread() -> None:
    sub = ZCTX.socket(zmq.SUB)
    sub.setsockopt(zmq.RCVTIMEO, 200)
    sub.setsockopt(zmq.LINGER, 0)
    sub.connect(ARGS.telemetry)
    sub.setsockopt_string(zmq.SUBSCRIBE, "")
    while True:
        try:
            part = sub.recv()
        except zmq.Again:
            continue
        brace = part.find(b"{")
        if brace < 0:
            continue
        try:
            frame = json.loads(part[brace:].decode())
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        link = frame.get("link_id") or part[:brace].decode(errors="replace").strip()
        frame["_rx_t"] = time.time()
        with STATE_LOCK:
            STATE["channel"][link] = frame
            TELEMETRY_TIMES.append(frame["_rx_t"])


def meter_thread() -> None:
    pull = ZCTX.socket(zmq.PULL)
    pull.setsockopt(zmq.RCVTIMEO, 200)
    pull.setsockopt(zmq.LINGER, 0)
    pull.bind(ARGS.meter_bind)
    while True:
        try:
            frame = json.loads(pull.recv_string())
        except zmq.Again:
            continue
        except json.JSONDecodeError:
            continue
        frame["_rx_t"] = time.time()
        with STATE_LOCK:
            STATE["power"][frame.get("port", "?")] = frame


def steering_request(message: dict, timeout_ms: int = 15000) -> dict:
    """REQ to the SIMO supervisor; long timeout, a swap spans a broker restart."""
    req = ZCTX.socket(zmq.REQ)
    req.setsockopt(zmq.RCVTIMEO, timeout_ms)
    req.setsockopt(zmq.SNDTIMEO, 2000)
    req.setsockopt(zmq.LINGER, 0)
    try:
        req.connect(ARGS.steering_rep)
        req.send_string(json.dumps(message))
        return json.loads(req.recv_string())
    except zmq.Again:
        return {"ok": False, "error": "steering supervisor timed out"}
    except json.JSONDecodeError:
        return {"ok": False, "error": "unparseable supervisor reply"}
    finally:
        req.close()


def control_request(message: dict, timeout_ms: int = 1500) -> dict:
    """One fresh REQ per action: thread-safe and immune to stuck REQ state."""
    req = ZCTX.socket(zmq.REQ)
    req.setsockopt(zmq.RCVTIMEO, timeout_ms)
    req.setsockopt(zmq.SNDTIMEO, timeout_ms)
    req.setsockopt(zmq.LINGER, 0)
    try:
        req.connect(ARGS.control)
        req.send_string(json.dumps(message))
        return json.loads(req.recv_string())
    except zmq.Again:
        return {"ok": False, "error": "broker control endpoint timed out"}
    except json.JSONDecodeError:
        return {"ok": False, "error": "unparseable broker reply"}
    finally:
        req.close()


def apply_action(body: dict) -> dict:
    action = body.get("action")
    links = body.get("links") or ARGS.links
    replies = []
    if action == "correlate":
        tx_re = float(body.get("tx_re", 0.4))
        for link in links:
            replies.append(control_request({
                "type": "correlation_swap", "link_id": link, "kind": "kronecker",
                "tx": [{"i": 0, "j": 1, "re": tx_re, "im": 0.0}]}))
        if all(r.get("ok") for r in replies):
            with STATE_LOCK:
                STATE["correlation"] = {"state": "correlated", "tx_re": tx_re}
    elif action == "iid":
        for link in links:
            replies.append(control_request({
                "type": "correlation_swap", "link_id": link, "kind": "iid"}))
        if all(r.get("ok") for r in replies):
            with STATE_LOCK:
                STATE["correlation"] = {"state": "iid", "tx_re": 0.0}
    elif action == "path_loss":
        value = float(body.get("value", 0.0))
        for link in links:
            replies.append(control_request({
                "type": "scalar", "link_id": link,
                "param": "path_loss_db", "value": value}))
    elif action == "steering":
        # SIMO mode: forwarded to the supervisor, which re-renders the 1x4
        # fixed_mimo topology and restarts the broker (no runtime swap yet).
        if not ARGS.steering_rep:
            return {"ok": False, "error": "bridge started without --steering-rep"}
        reply = steering_request({"cmd": "steering",
                                  "pattern": body.get("pattern", "")})
        if reply.get("ok"):
            with STATE_LOCK:
                STATE["steering"] = {"pattern": reply["pattern"],
                                     "expected": reply["expected"],
                                     "swapped_t": time.time(),
                                     "restart_s": reply.get("restart_s", 0)}
                STATE["events"].append({"t": time.time(), "action": "steering",
                                        "label": f"steer {reply['pattern']}"})
        return {"ok": reply.get("ok", False), "replies": [reply]}
    else:
        return {"ok": False, "error": f"unknown action: {action}"}
    ok = all(r.get("ok") for r in replies)
    if ok:
        label = {"correlate": "corr", "iid": "iid",
                 "path_loss": f"PL {body.get('value', 0):g} dB"}.get(action, action)
        with STATE_LOCK:
            STATE["events"].append({"t": time.time(), "action": action, "label": label})
    return {"ok": ok, "replies": replies}


def snapshot() -> dict:
    now = time.time()
    with STATE_LOCK:
        channel = {}
        for link, f in STATE["channel"].items():
            g = {k: v for k, v in f.items() if k not in ("_rx_t", "event")}
            g["age_s"] = round(now - f["_rx_t"], 3)
            channel[link] = g
        power = {}
        for port, f in STATE["power"].items():
            g = {k: v for k, v in f.items() if k not in ("_rx_t", "port", "t")}
            g["age_s"] = round(now - f["_rx_t"], 3)
            power[port] = g
        recent = [t for t in TELEMETRY_TIMES if t > now - 5]
        hz = round(len(recent) / 5.0, 1)
        return {"t": now, "channel": channel, "power": power,
                "correlation": dict(STATE["correlation"]),
                "expected": dict(STATE["expected"]),
                "gpu": dict(STATE["gpu"]),
                "events": [e for e in STATE["events"] if e["t"] > now - 60],
                "steering": STATE.get("steering"),
                "telemetry_hz": hz}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # quiet access log
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            page = Path(ARGS.static_dir, ARGS.page)
            if page.is_file():
                self._send(200, page.read_bytes(), "text/html; charset=utf-8")
            else:
                self._send(500, b"static/index.html missing", "text/plain")
        elif self.path == "/api/state":
            self._send(200, json.dumps(snapshot()).encode(), "application/json")
        elif self.path == "/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                while True:
                    payload = json.dumps(snapshot())
                    self.wfile.write(f"data: {payload}\n\n".encode())
                    self.wfile.flush()
                    time.sleep(1.0 / ARGS.push_hz)
            except (BrokenPipeError, ConnectionResetError):
                pass
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self):
        if self.path != "/api/control":
            self._send(404, b"not found", "text/plain")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode() or "{}")
        except (ValueError, json.JSONDecodeError):
            self._send(400, b'{"ok":false,"error":"bad json"}', "application/json")
            return
        result = apply_action(body)
        print(f"event=control action={body.get('action')} ok={result['ok']}", flush=True)
        self._send(200, json.dumps(result).encode(), "application/json")


def main() -> None:
    global ARGS
    ap = argparse.ArgumentParser(description="MIMO live demo bridge (C2)")
    ap.add_argument("--http-port", type=int, default=8080)
    ap.add_argument("--http-host", default="0.0.0.0")
    ap.add_argument("--telemetry", default="tcp://127.0.0.1:5560")
    ap.add_argument("--meter-bind", default="tcp://127.0.0.1:5561")
    ap.add_argument("--control", default="tcp://127.0.0.1:5559")
    ap.add_argument("--push-hz", type=float, default=10.0)
    ap.add_argument("--links", nargs="+",
                    default=["gnb>ue:tdl_a_corr", "ue>gnb:tdl_a_corr"],
                    help="link_ids the buttons act on")
    ap.add_argument("--static-dir", default=str(Path(__file__).parent / "static"))
    ap.add_argument("--page", default="index.html",
                    help="page served at / (simo.html for the 1x4 demo)")
    ap.add_argument("--steering-rep", default=None,
                    help="SIMO supervisor REP endpoint (enables the steering action)")
    ARGS = ap.parse_args()

    if ARGS.steering_rep:
        status = steering_request({"cmd": "status"}, timeout_ms=3000)
        if status.get("ok"):
            STATE["steering"] = {"pattern": status["pattern"],
                                 "expected": status["expected"],
                                 "swapped_t": 0, "restart_s": 0}

    threading.Thread(target=telemetry_thread, daemon=True).start()
    threading.Thread(target=meter_thread, daemon=True).start()
    server = ThreadingHTTPServer((ARGS.http_host, ARGS.http_port), Handler)
    print(f"event=start http={ARGS.http_host}:{ARGS.http_port} "
          f"telemetry={ARGS.telemetry} meter={ARGS.meter_bind} "
          f"control={ARGS.control}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("event=stop", flush=True)


if __name__ == "__main__":
    main()
