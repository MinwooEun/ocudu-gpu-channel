#!/usr/bin/env python3
"""Summarise tagged benchmark sessions: real-time ratio per test run and ue0 KPIs.
usage: sessions.py <tag> [<tag> ...]   (run on the Spark; reads the results tree)
"""
import csv
import glob
import json
import os
import sys

ROOT = "/workspace/ocudu-spark-ranb/results/single-cell-scheduler-benchmark"
print(f"{'tag':24s} {'session':6s} {'rt test1':9s} {'rt test2':9s} {'ue0 dl Mb/s':14s} {'mcs':9s} {'bler':13s} {'harq tx/tb':11s}")
for tag in sys.argv[1:]:
    ds = sorted(glob.glob(f"{ROOT}/tagged-{tag}-*"))
    if not ds:
        print(f"{tag:24s} (no session)")
        continue
    d = ds[-1]
    sess = d.rsplit("-", 1)[-1]
    rts = []
    for run in sorted(glob.glob(f"{d}/policy_runs/*/report/run-report.json")):
        try:
            r = json.load(open(run))
            v = (r.get("runtime") or {}).get("real_time_ratio", r.get("real_time_ratio"))
            rts.append("-" if v is None else f"{v:.3f}")
        except Exception:
            rts.append("err")
    while len(rts) < 2:
        rts.append("-")
    dl, mcs, bler, htx = [], [], [], []
    p = f"{d}/reports/per-ue-kpis.csv"
    if os.path.exists(p):
        for row in csv.DictReader(open(p)):
            if row.get("ue") == "ue0":
                dl.append(f"{float(row['dl_mbps']):.1f}")
                mcs.append(f"{float(row['dl_mcs']):.1f}")
                bler.append(f"{float(row['dl_bler']):.3f}")
                htx.append(f"{float(row['dl_harq_tx_per_tb']):.2f}" if row.get("dl_harq_tx_per_tb") else "-")
    print(f"{tag:24s} {sess:6s} {rts[0]:9s} {rts[1]:9s} {'/'.join(dl):14s} {'/'.join(mcs):9s} {'/'.join(bler):13s} {'/'.join(htx):11s}")
