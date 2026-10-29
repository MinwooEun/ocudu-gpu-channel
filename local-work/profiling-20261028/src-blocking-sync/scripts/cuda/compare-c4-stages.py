#!/usr/bin/env python3
"""Apply C4's numeric gate to a staged run set: BLER within 1 pp, SINR within 0.5 dB.

Compares every acceleration rung against the CPU baseline captured in the same
sweep, on the KPIs the gNB already logs.

The BLER comparison is reported as INCONCLUSIVE rather than PASS whenever the
run is too small to express a 1 pp difference. A 15 s attach gate carries only
the attach exchange and one acceptance ping -- fewer than thirty PUSCH
transmissions -- so a single CRC failure moves BLER by more than 3 pp. Calling
that "within 1 pp" would be reading a verdict out of a measurement that cannot
produce one; the sweep says so instead, and the fix is a traffic-bearing run,
not a looser threshold.
"""
from __future__ import annotations
import json, sys
from pathlib import Path

BLER_TOLERANCE_PP = 1.0
SINR_TOLERANCE_DB = 0.5
BASELINE = 'cpu-baseline'


def channel(entry: dict | None, name: str) -> dict | None:
    if not entry or not entry.get('kpis'):
        return None
    return entry['kpis'].get('channels', {}).get(name)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit('usage: compare-c4-stages.py <stages.json>')
    data = json.loads(Path(sys.argv[1]).read_text())
    base = data.get(BASELINE)
    if not base:
        raise SystemExit(f'no {BASELINE} in the sweep; nothing to compare against')
    base_pusch = channel(base, 'PUSCH')
    if not base_pusch:
        raise SystemExit('baseline has no PUSCH KPIs')

    base_bler = base_pusch.get('bler_pct')
    base_res = base_pusch.get('bler_resolution_pp', float('inf'))
    base_sinr = (base_pusch.get('sinr') or {}).get('mean_db')

    print(f'baseline {BASELINE}: PUSCH tx={base_pusch.get("transmissions")} '
          f'bler={base_bler}% (+-{base_res}pp) sinr_mean={base_sinr}dB')
    print(f'{"stage":<12} {"backend":>9} {"tx":>4} {"bler%":>7} {"d_bler_pp":>10} '
          f'{"sinr_mean":>10} {"d_sinr_db":>10}  verdict')

    worst = 0
    for stage, entry in data.items():
        if stage == BASELINE:
            continue
        pusch = channel(entry, 'PUSCH')
        backends = entry.get('backends') or {}
        backend_verdict = backends.get('verdict', '?')
        if entry.get('verdict') != 'passed' or not pusch:
            print(f'{stage:<12} {backend_verdict:>9} {"-":>4} {"-":>7} {"-":>10} {"-":>10} '
                  f'{"-":>10}  GATE FAIL (verdict={entry.get("verdict")})')
            worst = max(worst, 2)
            continue
        bler = pusch.get('bler_pct')
        res = pusch.get('bler_resolution_pp', float('inf'))
        sinr = (pusch.get('sinr') or {}).get('mean_db')
        d_bler = None if bler is None or base_bler is None else round(bler - base_bler, 4)
        d_sinr = None if sinr is None or base_sinr is None else round(sinr - base_sinr, 4)

        notes = []
        # A rung that ran a requested path on the host still attaches and pings.
        # Scoring survival alone is what C4 exists to not do.
        if backend_verdict == 'FAIL':
            detail = backends.get('host_fallback') or backends.get('missing') or backends.get('unavailable')
            notes.append(f'BACKEND FAIL ({"; ".join(map(str, detail))})')
            worst = max(worst, 2)
        elif backend_verdict == 'DEGRADED':
            notes.append(f'BACKEND DEGRADED ({",".join(backends.get("degraded", []))})')
            worst = max(worst, 1)

        # SINR is a mean over per-transmission measurements; a handful of them
        # still gives a usable mean, unlike a ratio of rare events.
        if d_sinr is None:
            notes.append('SINR MISSING'); worst = max(worst, 2)
        elif abs(d_sinr) <= SINR_TOLERANCE_DB:
            notes.append(f'SINR PASS (<={SINR_TOLERANCE_DB}dB)')
        else:
            notes.append(f'SINR FAIL (>{SINR_TOLERANCE_DB}dB)'); worst = max(worst, 2)

        if d_bler is None:
            notes.append('BLER MISSING'); worst = max(worst, 2)
        elif max(res, base_res) > BLER_TOLERANCE_PP:
            notes.append(f'BLER INCONCLUSIVE (resolution {max(res, base_res)}pp > {BLER_TOLERANCE_PP}pp)')
            worst = max(worst, 1)
        elif abs(d_bler) <= BLER_TOLERANCE_PP:
            notes.append(f'BLER PASS (<={BLER_TOLERANCE_PP}pp)')
        else:
            notes.append(f'BLER FAIL (>{BLER_TOLERANCE_PP}pp)'); worst = max(worst, 2)

        print(f'{stage:<12} {backend_verdict:>9} {pusch.get("transmissions"):>4} {bler:>7} '
              f'{"" if d_bler is None else d_bler:>10} {"" if sinr is None else sinr:>10} '
              f'{"" if d_sinr is None else d_sinr:>10}  {"; ".join(notes)}')

    print()
    if worst == 0:
        print('C4 gate: PASS on every rung')
    elif worst == 1:
        print('C4 gate: NOT ESTABLISHED — no rung failed, but at least one result is '
              'not a pass. See BLER resolution and any DEGRADED backend above.')
    else:
        print('C4 gate: FAIL — see the rungs above')
    raise SystemExit(worst)


if __name__ == '__main__':
    main()
