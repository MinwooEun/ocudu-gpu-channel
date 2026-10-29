#!/usr/bin/env python3
"""Producer hop-trace: per node, process time (DataReady->Pushed) and wait (Pushed->next DataReady)."""
import sys, csv, collections
f = sys.argv[1]; ev = collections.defaultdict(list)
for row in csv.reader(open(f)):
    if row and row[0] == "producer": ev[row[1]].append((int(row[3]), int(row[2])))
proc_all = []; share = []
for node, recs in ev.items():
    recs.sort(); proc = []; wait = []; last_push = None
    for t, e in recs:
        if e == 10:
            ready = t
            if last_push is not None: wait.append(t - last_push)
        elif e == 11 and 'ready' in dir():
            proc.append(t - ready); last_push = t
    if proc:
        proc_all += proc; share.append(sum(proc) / (sum(proc) + sum(wait)) if wait else 1.0)
def pct(v, q): v = sorted(v); return v[min(len(v) - 1, int(len(v) * q))] / 1000.0
if proc_all:
    print(f"nodes={len(ev)} slots={len(proc_all)} proc_us_p50={pct(proc_all,0.5):.1f} proc_us_p90={pct(proc_all,0.9):.1f} proc_us_p99={pct(proc_all,0.99):.1f} busy_share_mean={sum(share)/len(share):.3f} busy_share_max={max(share):.3f}")
else: print("nodes=0")
