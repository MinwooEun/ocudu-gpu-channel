#!/usr/bin/env python3
"""S5 follow-up -- which PUSCH SINR report drives the UL grant for the next 528-bit TB.

    s5-la-trace.py ARM=RUN_DIR[,RUN_DIR...] ...

The scheduler logs its UL decision (k2 slots ahead) before the PUSCH it
schedules. For every new transmission (newtx=true) of tbs=528 this pairs the
chosen width (fewer PRBs = higher MCS) with the latest PUSCH SINR the PHY had
reported when the decision line was written, and with the CRC of the resulting
PUSCH. Also printed: reported SINR per allocation width, the link adaptation's input.
"""
import re, statistics, sys
from collections import defaultdict
from pathlib import Path

PUSCH = re.compile(r'\[\s*(\d+\.\d+)\] PUSCH: rnti=\S+ harq_id=(\d+) prb=\[(\d+), (\d+)\) .*?crc=(OK|KO) .*?sinr=([-0-9.]+)dB')
SCHED = re.compile(r'\[\s*(\d+\.\d+)\] Slot decisions .*?UL: (.*)$')
GRANT = re.compile(r'h_id=(\d+) ss_id=\d+ rb=\[(\d+)\.\.(\d+)\) newtx=(true|false) rv=\d+ tbs=(\d+)')

for arm, dirs in (a.split('=', 1) for a in sys.argv[1:]):
    chosen = defaultdict(lambda: [[], 0, 0, 0])   # width -> [latest SINRs, latest-was-1PRB, n, ko]
    by_width = defaultdict(list)
    for d in dirs.split(','):
        latest = None
        pending = {}
        for line in open(Path(d) / 'logs/gnb-internal.log', errors='ignore'):
            m = SCHED.search(line)
            if m:
                for h, r0, r1, newtx, tbs in GRANT.findall(m.group(2)):
                    if newtx == 'true' and tbs == '528' and latest:
                        pending[(m.group(1), h)] = (int(r1) - int(r0), latest)
                continue
            m = PUSCH.search(line)
            if m:
                slot, h, p0, p1, crc, sinr = m.groups()
                w = int(p1) - int(p0)
                by_width[w].append(float(sinr))
                hit = pending.pop((slot, h), None)
                if hit:
                    cw, (ls, lw) = hit
                    c = chosen[cw]; c[0].append(ls); c[1] += lw == 1; c[2] += 1; c[3] += crc == 'KO'
                latest = (float(sinr), w)
    print(f'=== {arm}')
    print('  new 528-bit TB: chosen width <- latest reported SINR at decision time')
    for w in sorted(chosen):
        s, one, n, ko = chosen[w]
        print(f'    {w:2d} PRB n={n:4d} KO={ko:3d}  latest SINR mean={statistics.fmean(s):5.2f} '
              f'min={min(s):4.1f} max={max(s):4.1f}  from a 1-PRB PUSCH: {one}')
    print('  reported SINR by allocation width (all PUSCH, n >= 30): mean / sd / max')
    for w in sorted(by_width):
        v = by_width[w]
        if len(v) >= 30:
            print(f'    {w:3d} PRB n={len(v):5d} mean={statistics.fmean(v):5.2f} sd={statistics.pstdev(v):4.2f} max={max(v):5.1f}')
