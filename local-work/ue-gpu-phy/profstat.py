#!/usr/bin/env python3
"""Per-stage statistics from srsUE slot-trace CSVs (SRSUE_SLOT_TRACE_DIR): <pid>-<tag>.csv, columns t_ns,ev,tti,a,b,c.

usage: profstat.py <trace dir> [<trace dir> ...]
Prints, per UE process: slot pipeline (sync wait for a worker, DL/UL work time, deadline misses), per-stage
cost, and the decode section broken down per code block count, for the CPU and the GPU LDPC path.
"""
import collections
import glob
import os
import sys


def pct(v, p):
    if not v:
        return 0
    v = sorted(v)
    return v[min(len(v) - 1, int(len(v) * p))]


def line(name, v, unit="us", extra=""):
    if not v:
        return
    print(f"  {name:28s} n={len(v):7d} p50={pct(v, .5):7.0f} p90={pct(v, .9):7.0f} p99={pct(v, .99):7.0f} max={max(v):8.0f} {unit}{extra}")


def load(d):
    pids = collections.defaultdict(lambda: collections.defaultdict(list))
    for f in glob.glob(os.path.join(d, "*.csv")):
        pid, tag = os.path.basename(f)[:-4].split("-", 1)
        with open(f) as fh:
            next(fh, None)
            for ln in fh:
                p = ln.rstrip("\n").split(",")
                if len(p) < 6:
                    continue
                try:
                    pids[pid][(tag, p[1])].append((int(p[0]), int(p[2]), int(p[3]), int(p[4]), int(p[5])))
                except ValueError:
                    continue
    return pids


def report(d):
    print(f"=== {d}")
    pids = load(d)
    for pid in sorted(pids):
        ev = pids[pid]
        get = lambda tag, name, col: [r[col] for r in ev.get((tag, name), [])]
        if not ev.get(("worker", "DL")) and not ev.get(("schnr", "TB")):
            continue
        tb = ev.get(("schnr", "TB"), [])
        backend = "mixed"
        if tb:
            cuda = sum(1 for r in tb if r[4])
            backend = "cuda" if cuda == len(tb) else "cpu" if cuda == 0 else f"mixed({cuda}/{len(tb)})"
        print(f"--- pid {pid} backend={backend}")
        # slot pipeline
        print(" slot pipeline (sync thread / worker)")
        ww = get("sync", "WW", 2)
        line("sync: wait for free worker", ww, extra=f"  >200us: {sum(1 for x in ww if x > 200)}  >1000us: {sum(1 for x in ww if x > 1000)}")
        line("sync: rx slot", get("sync", "RX", 2))
        dl = get("worker", "DL", 2)
        line("worker: DL work", dl, extra=f"  >1000us: {sum(1 for x in dl if x > 1000)}  >2000us: {sum(1 for x in dl if x > 2000)}  >3000us: {sum(1 for x in dl if x > 3000)}")
        line("worker: wait DL->UL order", get("worker", "DU", 2))
        line("worker: UL work", get("worker", "UL", 2))
        line("worker: worker_end (tx)", get("worker", "WE", 2))
        line("sync: tx semaphore wait", get("sync", "SEM", 2))
        line("sync: radio tx", get("sync", "TX", 2))
        line("zmq: tx request wait", get("zmqtx", "ZREQ", 2))
        # per-stage
        print(" DL stages per slot")
        for tag, name, label in [("ccw", "FFT", "FFT"), ("ccw", "CSI", "CSI measure"), ("ccw", "PDCCH", "PDCCH decode"),
                                 ("uedl", "CHEST", "PDSCH channel estimate"), ("pdsch", "EQ", "PDSCH get+equalize"),
                                 ("pdsch", "DEMOD", "PDSCH demodulate"), ("pdsch", "SCH", "DL-SCH decode (RM+LDPC+CRC)"),
                                 ("uedl", "PDEC", "PDSCH decode total")]:
            line(label, get(tag, name, 2))
        ok = ev.get(("ccw", "PDok"), [])
        nok = ev.get(("ccw", "PDnok"), [])
        line("PDSCH ok (cc_worker)", [r[4] for r in ok], extra=f"  prb_p50={pct([r[3] // 100 for r in ok], .5)} mcs_p50={pct([r[3] % 100 for r in ok], .5)} tbs_p50={pct([r[2] for r in ok], .5)}")
        line("PDSCH crc fail (cc_worker)", [r[4] for r in nok], extra=f"  prb_p50={pct([r[3] // 100 for r in nok], .5)} mcs_p50={pct([r[3] % 100 for r in nok], .5)}")
        line("PUSCH encode", [r[4] for r in ev.get(("ccw", "PU"), [])])
        # Local S2: GPU DL front end
        gf = ev.get(("uedl", "GFFT"), [])
        if gf:
            line("GPU FFT (launch+wait)", [r[2] for r in gf], extra=f"  fallback_to_cpu={sum(1 for r in gf if r[3] == 0)}")
        gp = ev.get(("uedl", "GPDSCH"), [])
        if gp:
            line("GPU PDSCH total (host)", [r[2] for r in gp], extra=f"  crc_ok={sum(1 for r in gp if r[4])}/{len(gp)}")
            line("  e2e launch", get("uedl", "GPT", 2))
            line("  rm+ldpc launch", get("uedl", "GPT", 3))
            line("  wait", get("uedl", "GPT", 4))
            line("  gpu span (events)", get("uedl", "GPG", 2))
            line("  unpack+crc", get("uedl", "GPG", 3))
        if ev.get(("uedl", "CHEST")):
            line("CPU PDSCH chest+decode", [a[2] + b[2] for a, b in zip(ev.get(("uedl", "CHEST"), []), ev.get(("uedl", "PDEC"), []))])
        # decode section by C
        print(" decode section per TB, by code blocks (C)")
        byc = collections.defaultdict(list)
        for r in tb:
            byc[r[3]].append(r[2])
        for c in sorted(byc):
            line(f"TB total C={c}", byc[c])
        line("RM per CB", get("schnr", "RM", 2))
        ld = ev.get(("schnr", "LDPC"), [])
        if ld:
            it = [r[4] for r in ld]
            line("LDPC per CB (cpu)", [r[2] for r in ld], extra=f"  iter: ok_p50={pct([x for x in it if x > 0], .5)} fail={sum(1 for x in it if x < 0)}")
            byi = collections.defaultdict(list)
            for r in ld:
                byi[r[4]].append(r[2])
            for i in sorted(byi):
                line(f"  LDPC per CB iter={i}", byi[i])
        gd = ev.get(("schnr", "GDEC"), [])
        if gd:
            byn = collections.defaultdict(list)
            for r in gd:
                byn[r[3]].append(r[2])
            for n in sorted(byn):
                line(f"GPU decode call n={n} (host)", byn[n])
            line("GPU avg iterations x10", [r[4] for r in gd], unit="")
        line("GPU: handle lookup/config", get("gldpc", "GCFG", 2))
        line("GPU: int8->fp16 fill", get("gldpc", "GFILL", 2))
        line("GPU: launch (host return)", get("gldpc", "GLNCH", 2))
        line("GPU: wait for completion", get("gldpc", "GWAIT", 2))
        gg = ev.get(("gldpc", "GGPU"), [])
        if gg:
            line("GPU: kernel span (events)", [r[2] for r in gg])
            line("GPU: launch+wait host", [r[4] for r in gg])
            line("GPU: host - kernel (overhead)", [r[4] - r[2] for r in gg])
            byn = collections.defaultdict(list)
            for r in gg:
                byn[r[3]].append(r[2])
            for n in sorted(byn):
                line(f"  kernel span n={n}", byn[n])
        line("GPU: unpack bits", get("gldpc", "GUNPK", 2))
        line("GPU: CRC check + pack", get("schnr", "GCRC", 2))


for d in sys.argv[1:]:
    report(d)
