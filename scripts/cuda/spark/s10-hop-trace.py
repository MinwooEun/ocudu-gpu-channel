#!/usr/bin/env python3
"""Split the broker's lock-step cycle into hops from hop-trace.csv (S10).

Per device d (gnb0, ue0), steady state (drops the first `skip` seconds):
  pull_rtt   puller request sent -> device TX message received (device-side wait + transfer in)
  ring       message received -> in the TX ring
  wake_prod  source message in ring -> destination producer starts (only when it was waiting)
  produce    producer start -> row pushed (read + channel + push)
  wake_rep   row pushed -> REP pops it (only when the device request was already waiting)
  req_early  device RX request received -> row available (device asked before the row existed)
  send       REP pops -> zmq_send returned
  rx_turn    reply sent -> next RX request from the device (transfer out + device work)
Plus msg/s per device over the steady window.
Also, per device, the lock-step lead (TX samples pulled minus RX samples served,
in 61,440-sample messages) and the broker relay latency per direction.
Input is the broker's OCG_HOP_TRACE_DIR output (SPARK_MILESTONES.md S10).
usage: s10-hop-trace.py <hop-trace.csv> [skip_s]"""
import bisect, collections, sys

path = sys.argv[1]
skip = float(sys.argv[2]) if len(sys.argv) > 2 else 10.0
ev = collections.defaultdict(list)  # (role,id,event) -> [(t, samples)]
for line in open(path):
    if line.startswith("role"):
        continue
    role, dev, e, t, n = line.strip().split(",")
    ev[(role, dev, int(e))].append((int(t), int(n)))
t0 = min(v[0][0] for v in ev.values() if v)
lo = t0 + skip * 1e9
t_end = max(v[-1][0] for v in ev.values() if v)

def times(role, dev, e):
    return [t for t, _ in ev.get((role, dev, e), []) if t >= lo]

def pct(xs):
    if not xs:
        return "n=0"
    xs = sorted(xs)
    q = lambda f: xs[int(f * (len(xs) - 1))]
    return f"n={len(xs)} mean={sum(xs)/len(xs):.0f} p50={q(.5):.0f} p90={q(.9):.0f} p99={q(.99):.0f}"

def pairs(a, b):
    """For each a, the first b at or after it (us)."""
    out = []
    for t in a:
        i = bisect.bisect_left(b, t)
        if i < len(b):
            out.append((b[i] - t) / 1e3)
    return out

src_of = {"gnb0": "ue0", "ue0": "gnb0"}  # producer of node n reads the other device's TX
span = (t_end - lo) / 1e9
for d in ("gnb0", "ue0"):
    req = times("puller", d, 0); rcv = times("puller", d, 1); ring = times("puller", d, 2)
    rq = times("rep", d, 20); pop = times("rep", d, 21); sent = times("rep", d, 22)
    ready = times("producer", d, 10); pushed = times("producer", d, 11)
    print(f"== {d}: tx msgs/s={len(rcv)/span:.0f} rx replies/s={len(sent)/span:.0f} producer slots/s={len(ready)/span:.0f}")
    print("  pull_rtt   ", pct(pairs(req, rcv)))
    print("  ring       ", pct(pairs(rcv, ring)))
    # producer wake: for each producer start, the latest source ring push before it, if the
    # producer finished its previous slot before that push (i.e. it was waiting on data).
    src_ring = times("puller", src_of[d], 2)
    wake = []; prod = []
    for i, t in enumerate(ready):
        j = bisect.bisect_right(src_ring, t) - 1
        if j < 0:
            continue
        prev_done = pushed[bisect.bisect_right(pushed, t) - 1] if bisect.bisect_right(pushed, t) > 0 else 0
        if src_ring[j] > prev_done:
            wake.append((t - src_ring[j]) / 1e3)
    print("  wake_prod  ", pct(wake))
    print("  produce    ", pct(pairs(ready, pushed)))
    wr = []; early = []
    for t in pop:
        j = bisect.bisect_right(pushed, t) - 1
        k = bisect.bisect_right(rq, t) - 1
        if j < 0 or k < 0:
            continue
        if rq[k] < pushed[j]:  # request waited for the row
            wr.append((t - pushed[j]) / 1e3)
            early.append((pushed[j] - rq[k]) / 1e3)
    print("  wake_rep   ", pct(wr), f"(requests that waited: {len(wr)}/{len(pop)})")
    print("  req_early  ", pct(early))
    print("  send       ", pct(pairs(pop, sent)))
    rt = []
    for t in sent:
        i = bisect.bisect_right(rq, t)
        if i < len(rq):
            rt.append((rq[i] - t) / 1e3)
    print("  rx_turn    ", pct(rt))


def cum(lst):
    out = []; c = 0
    for t, n in lst:
        c += n; out.append((t, c))
    return out

def pct_lead(xs):
    if not xs:
        return "n=0"
    xs = sorted(xs); q = lambda f: xs[int(f * (len(xs) - 1))]
    return f"n={len(xs)} p10={q(.1):.0f} p50={q(.5):.0f} p90={q(.9):.0f}"

for d in ("gnb0", "ue0"):
    tx = cum(ev[("puller", d, 1)]); rx = cum(ev[("rep", d, 22)])
    leads = []; j = 0
    for t, c in rx:
        while j + 1 < len(tx) and tx[j + 1][0] <= t:
            j += 1
        if t >= lo and tx and tx[j][0] <= t:
            leads.append((tx[j][1] - c) / 61440.0)
    print(f"{d}: lead (TX pulled - RX served, messages)", pct_lead(leads))
for src, dst, name in (("gnb0", "ue0", "DL"), ("ue0", "gnb0", "UL")):
    tx = cum(ev[("puller", src, 1)]); rx = cum(ev[("rep", dst, 22)])
    lat = []; j = 0
    for t, c in rx:
        while j < len(tx) and tx[j][1] < c:
            j += 1
        if j < len(tx) and t >= lo:
            lat.append((t - tx[j][0]) / 1e3)
    print(f"{name} relay ({src} TX in -> {dst} RX out, us)", pct_lead(lat))
