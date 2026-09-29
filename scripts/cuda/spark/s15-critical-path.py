#!/usr/bin/env python3
"""Critical-path accounting of the lock-step broker cycle from hop-trace.csv (S15).

Works for multi-port nodes (ids `<node>_p<k>`). Every stage is matched by the
cumulative sample count it has handled, so a sample boundary `s` has one time
per stage. For each message boundary (end of a device TX message) it reports,
per direction (DL = gnb0 TX -> ue0 RX, UL = ue0 TX -> gnb0 RX):

  in_ring     TX message received by the puller -> in the TX ring (last port)
  wake_prod   last port in ring -> destination producer has the window
  produce     producer has the window -> row pushed (read + channel + push)
  wait_req    row pushed -> device RX request arrives   (device-owned, 0 if early)
  wake_rep    max(row pushed, request) -> REP popped the row (broker wake)
  send        popped -> zmq_send returned (last port)
  broker      TX message received -> reply sent, minus wait_req

and per device the turnaround: RX reply sent (last port) -> that device's next
TX message received by the puller (first port). The cycle is the time between
successive TX messages of one device.
usage: s15-critical-path.py <csv> [skip_s] [until_s]  (window in s after the first event)
"""
import bisect
import collections
import sys

path = sys.argv[1]
skip = float(sys.argv[2]) if len(sys.argv) > 2 else 10.0
until = float(sys.argv[3]) if len(sys.argv) > 3 else 1e9  # window end, s after the first event
ev = collections.defaultdict(list)
for line in open(path):
    if line.startswith("role"):
        continue
    role, dev, e, t, n = line.rstrip().split(",")
    ev[(role, dev, int(e))].append((int(t), int(n)))

ports = collections.defaultdict(set)
for role, dev, _ in ev:
    if role in ("puller", "rep"):
        ports[dev.split("_p")[0]].add(dev)
t0 = min(v[0][0] for v in ev.values() if v)
lo = t0 + skip * 1e9
hi = t0 + until * 1e9


def cum(role, dev, e):
    """(cumulative samples after event, time) for events carrying samples."""
    out, c = [], 0
    for t, n in ev.get((role, dev, e), []):
        c += n
        out.append((c, t))
    return out


def at(series, s):
    """Time the stage first covered sample count s (None if never)."""
    i = bisect.bisect_left(series, (s, -1))
    return series[i][1] if i < len(series) else None


tcache = {}


def times(role, dev, e):
    k = (role, dev, e)
    if k not in tcache:
        tcache[k] = [t for t, _ in ev.get(k, [])]
    return tcache[k]


def pct(xs):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return "n=0"
    q = lambda f: xs[int(f * (len(xs) - 1))]
    return f"n={len(xs)} mean={sum(xs)/len(xs):.1f} p50={q(.5):.1f} p90={q(.9):.1f} p99={q(.99):.1f}"


cache = {}


def times(role, dev, e):
    k = (role, dev, e)
    if k not in tcache:
        tcache[k] = [t for t, _ in ev.get(k, [])]
    return tcache[k]


def pct(xs):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return "n=0"
    q = lambda f: xs[int(f * (len(xs) - 1))]
    return f"n={len(xs)} mean={sum(xs)/len(xs):.1f} p50={q(.5):.1f} p90={q(.9):.1f} p99={q(.99):.1f}"


def last_port(role, node, e, s):
    ts = [at(cum(role, p, e), s) for p in sorted(ports[node])]
    return None if any(t is None for t in ts) else max(ts)


cache = {}


def c(role, dev, e):
    k = (role, dev, e)
    if k not in cache:
        cache[k] = cum(role, dev, e)
    return cache[k]


def last(role, node, e, s):
    ts = [at(c(role, p, e), s) for p in sorted(ports[node])]
    return None if any(t is None for t in ts) else max(ts)


def req_for(node, s):
    """RX request that the reply covering s answered: the k-th request on the
    last port, where k is the index of the popped event covering s."""
    out = []
    for p in sorted(ports[node]):
        pops = c("rep", p, 21)
        i = bisect.bisect_left(pops, (s, -1))
        reqs = times("rep", p, 20)
        if i >= len(pops) or i >= len(reqs):
            return None
        out.append(reqs[i])
    return max(out)


span_end = min(hi, max(v[-1][0] for v in ev.values() if v))
span = (span_end - lo) / 1e9
summary = {}
for src, dst, name in (("gnb0", "ue0", "DL"), ("ue0", "gnb0", "UL")):
    rx0 = sorted(ports[src])[0]
    bounds = [s for s, t in c("puller", rx0, 1) if lo <= t < hi]
    seg = collections.defaultdict(list)
    for s in bounds:
        t_in = last("puller", src, 1, s)
        t_ring = last("puller", src, 2, s)
        t_ready = at(c("producer", dst, 10), s)
        t_push = at(c("producer", dst, 11), s)
        t_req = req_for(dst, s)
        t_pop = last("rep", dst, 21, s)
        t_sent = last("rep", dst, 22, s)
        if None in (t_in, t_ring, t_ready, t_push, t_req, t_pop, t_sent):
            continue
        us = lambda a, b: (b - a) / 1e3
        wait_req = max(0.0, us(t_push, t_req))
        seg["in_ring"].append(us(t_in, t_ring))
        seg["wake_prod"].append(max(0.0, us(t_ring, t_ready)))
        seg["produce"].append(us(max(t_ready, t_ring), t_push))
        seg["wait_req"].append(wait_req)
        seg["wake_rep"].append(us(max(t_push, t_req), t_pop))
        seg["send"].append(us(t_pop, t_sent))
        seg["broker"].append(us(t_in, t_sent) - wait_req)
        seg["relay"].append(us(t_in, t_sent))
    print(f"== {name} ({src} TX -> {dst} RX), messages={len(seg['relay'])}")
    for k in ("in_ring", "wake_prod", "produce", "wait_req", "wake_rep", "send", "broker", "relay"):
        print(f"  {k:10s} {pct(seg[k])}")
    summary[name] = seg

for d in ("gnb0", "ue0"):
    tx0 = sorted(ports[d])[0]
    tx = [t for t in times("puller", tx0, 1) if lo <= t < hi]
    sent_last = [t for t in (last("rep", d, 22, s) for s, _ in c("rep", sorted(ports[d])[0], 22)) if t and lo <= t < hi]
    turn = []
    for t in sent_last:
        i = bisect.bisect_right(tx, t)
        if i < len(tx):
            turn.append((tx[i] - t) / 1e3)
    cyc = [(b - a) / 1e3 for a, b in zip(tx, tx[1:])]
    print(f"== {d}: tx msgs/s={len(tx)/span:.0f}")
    print(f"  turnaround {pct(turn)}")
    print(f"  cycle      {pct(cyc)}")
