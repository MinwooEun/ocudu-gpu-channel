#!/usr/bin/env python3
"""S5 -- compare live PUSCH between arms on matched allocations.

    s5-compare-arms.py ARM=RUN_DIR[,RUN_DIR...] ARM=... [--ref ARM] [--min-n 30] [--json OUT]

Each RUN_DIR is a direct-ZMQ run (…/direct-zmq-*/logs/gnb-internal.log). Pooled
BLER is confounded by the allocation mix (issue 6, SPARK_MILESTONES.md), so the
verdict uses first transmissions of allocations -- (mod, prb range, tbs) --
present at least --min-n times in both the reference and the other arm.
Retransmissions in this configuration also go out with rv=0, so a first
transmission is recognised from the scheduler's own decision line for the same
slot and HARQ process (newtx=true), not from rv:
  BLER   |Δ| <= 1 %p   (weighted by the smaller arm's count)
  SINR   |Δ| <= 0.5 dB (same weighting)
Per-allocation rows and the PHY-reported processing time t= are printed as well.
"""
from __future__ import annotations
import argparse, json, re, statistics, sys
from collections import defaultdict
from pathlib import Path

SCHED = re.compile(r'\[\s*(\d+\.\d+)\] Slot decisions .*?UL: (.*)$')
GRANT = re.compile(r'h_id=(\d+) .*?newtx=(true|false)')
SLOT = re.compile(r'\[\s*(\d+\.\d+)\] PUSCH: rnti=\S+ harq_id=(\d+) ')
LINE = re.compile(r'PUSCH: rnti=\S+ harq_id=\d+ prb=\[(\d+), (\d+)\) symb=\S+ \S+ mod=(\S+) rv=(\d+) '
                  r'tbs=(\d+) crc=(OK|KO) .*?sinr=([-0-9.]+)dB t=([0-9.]+)us')


def load(dirs: list[str]) -> list[tuple]:
    """Rows of (alloc, newtx, ko, sinr, t). newtx is None when no decision line matched."""
    rows = []
    for d in dirs:
        newtx = {}
        for line in open(Path(d) / 'logs/gnb-internal.log', errors='ignore'):
            m = SCHED.search(line)
            if m:
                for h, n in GRANT.findall(m.group(2)):
                    newtx[(m.group(1), h)] = n == 'true'
                continue
            m = LINE.search(line)
            if m:
                p0, p1, mod, rv, tbs, crc, sinr, t = m.groups()
                k = SLOT.search(line)
                first = newtx.pop((k.group(1), k.group(2)), None) if k else None
                rows.append(((mod, f'[{p0},{p1})', int(tbs)), first, crc == 'KO', float(sinr), float(t)))
    return rows


def per_alloc(rows):
    acc = defaultdict(lambda: [0, 0, []])
    for alloc, first, ko, sinr, _ in rows:
        if first:
            a = acc[alloc]; a[0] += 1; a[1] += ko; a[2].append(sinr)
    return acc


def pct(v, q):
    v = sorted(v); return v[min(len(v) - 1, int(q * len(v)))] if v else float('nan')


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('arms', nargs='+')
    ap.add_argument('--ref', default=None)
    ap.add_argument('--min-n', type=int, default=30)
    ap.add_argument('--json')
    a = ap.parse_args()
    arms = {k: v.split(',') for k, v in (s.split('=', 1) for s in a.arms)}
    ref = a.ref or next(iter(arms))
    data = {k: load(v) for k, v in arms.items()}
    report = {'ref': ref, 'min_n': a.min_n, 'arms': {}}

    for k, rows in data.items():
        t = [r[4] for r in rows]
        n = len(rows); ko = sum(r[2] for r in rows)
        report['arms'][k] = dict(runs=len(arms[k]), transmissions=n, crc_ko=ko,
                                 pooled_bler_pct=round(100 * ko / n, 3) if n else None,
                                 sinr_mean_db=round(statistics.fmean(r[3] for r in rows), 3) if n else None,
                                 t_us=dict(p50=pct(t, .5), p99=pct(t, .99), max=max(t, default=None)))
        s = report['arms'][k]
        s['unmatched_decisions'] = sum(r[1] is None for r in rows)
        s['first_tx'] = sum(bool(r[1]) for r in rows)
        print(f'{k:9s} runs={s["runs"]} tx={n} first_tx={s["first_tx"]} unmatched={s["unmatched_decisions"]} crc_ko={ko} pooled_bler={s["pooled_bler_pct"]}% '
              f'sinr_mean={s["sinr_mean_db"]} t_us p50/p99/max={s["t_us"]["p50"]}/{s["t_us"]["p99"]}/{s["t_us"]["max"]}')

    ref_alloc = per_alloc(data[ref])
    verdict_ok = True
    for k in data:
        if k == ref:
            continue
        other = per_alloc(data[k])
        print(f'\n--- {k} vs {ref} (first transmissions, matched allocations, n >= {a.min_n} in both)')
        print(f'{"alloc":28s} {"n_ref":>6s} {"bler_ref":>9s} {"n":>6s} {"bler":>7s} {"dBLER":>7s} {"sinr_ref":>8s} {"sinr":>6s} {"dSINR":>6s}')
        wsum = wb = ws = 0.0; rows = []
        for alloc in sorted(set(ref_alloc) & set(other), key=lambda x: -min(ref_alloc[x][0], other[x][0])):
            r, o = ref_alloc[alloc], other[alloc]
            if min(r[0], o[0]) < a.min_n:
                continue
            br, bo = 100 * r[1] / r[0], 100 * o[1] / o[0]
            sr, so = statistics.fmean(r[2]), statistics.fmean(o[2])
            w = min(r[0], o[0]); wsum += w; wb += w * (bo - br); ws += w * (so - sr)
            name = f'{alloc[0]} {alloc[1]} tbs={alloc[2]}'
            rows.append(dict(alloc=name, n_ref=r[0], bler_ref=round(br, 2), n=o[0], bler=round(bo, 2),
                             sinr_ref=round(sr, 2), sinr=round(so, 2)))
            print(f'{name:28s} {r[0]:6d} {br:8.2f}% {o[0]:6d} {bo:6.2f}% {bo - br:+6.2f} {sr:8.2f} {so:6.2f} {so - sr:+6.2f}')
        if not wsum:
            print('no matched allocation reaches --min-n: no verdict'); verdict_ok = False
            report['arms'][k]['vs_ref'] = dict(verdict='insufficient', rows=rows); continue
        db, ds = wb / wsum, ws / wsum
        ok = abs(db) <= 1.0 and abs(ds) <= 0.5
        verdict_ok &= ok
        print(f'weighted dBLER={db:+.2f}%p dSINR={ds:+.2f} dB over {int(wsum)} matched tx -> {"PASS" if ok else "FAIL"}')
        report['arms'][k]['vs_ref'] = dict(weighted_dbler_pp=round(db, 3), weighted_dsinr_db=round(ds, 3),
                                           matched_tx=int(wsum), verdict='pass' if ok else 'fail', rows=rows)
    if a.json:
        Path(a.json).write_text(json.dumps(report, indent=2) + '\n')
    sys.exit(0 if verdict_ok else 1)


if __name__ == '__main__':
    main()
