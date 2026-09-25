#!/usr/bin/env python3
"""Summarise the PHY KPIs a gNB run leaves in its internal log.

Reads the per-transmission PHY lines the gNB already writes -- no new
instrumentation and no change to any gate -- and reports uplink BLER and SINR,
which is what C4 compares between the CPU and CUDA builds.

Uplink only for BLER: the gNB logs `crc=` on PUSCH because it is the receiver.
Downlink CRC happens at the UE and is not in this log, so a PDSCH BLER is not
derivable here and is deliberately absent rather than guessed at.

Also reports the sample count, and `bler_resolution_pp` -- the smallest BLER
difference a run of this size can express (100/n percentage points). A C4
verdict of "within 1 pp" is meaningless when one CRC failure moves the figure
by more than that, so the resolution travels with the number.
"""
from __future__ import annotations
import argparse, json, math, re, statistics, sys
from pathlib import Path

# 2026-09-11T03:55:42.831623 [PHY  ] [I] [ 245.6] PUSCH: rnti=0x4601 ... crc=OK ... sinr=2.0dB t=96.9us
LINE = re.compile(r'\[PHY\s*\]\s*\[I\]\s*\[\s*[\d.]+\]\s+(?P<channel>PUSCH|PUCCH|PDSCH|PRACH):\s*(?P<body>.*)')
CRC = re.compile(r'\bcrc=(OK|KO)\b')
SINR = re.compile(r'\bsinr=(-?[\d.]+|-?inf|-?nan)dB')
TIME = re.compile(r'\bt=([\d.]+)us')


def stats(values: list[float]) -> dict | None:
    if not values:
        return None
    ordered = sorted(values)
    return {
        'n': len(ordered),
        'mean_db': round(statistics.fmean(ordered), 3),
        'p50_db': round(statistics.median(ordered), 3),
        'min_db': round(ordered[0], 3),
        'max_db': round(ordered[-1], 3),
    }


def summarize(path: Path) -> dict:
    channels: dict[str, dict] = {}
    for raw in path.read_text(errors='replace').splitlines():
        match = LINE.search(raw)
        if not match:
            continue
        channel = match.group('channel')
        body = match.group('body')
        bucket = channels.setdefault(channel, {'lines': 0, 'crc_ok': 0, 'crc_ko': 0,
                                               'sinr_db': [], 'sinr_non_finite': 0,
                                               'proc_us': []})
        bucket['lines'] += 1
        crc = CRC.search(body)
        if crc:
            bucket['crc_ok' if crc.group(1) == 'OK' else 'crc_ko'] += 1
        sinr = SINR.search(body)
        if sinr:
            try:
                value = float(sinr.group(1))
            except ValueError:
                value = math.nan
            # -inf is what an idle PUCCH occasion reports; it is not a measurement.
            if math.isfinite(value):
                bucket['sinr_db'].append(value)
            else:
                bucket['sinr_non_finite'] += 1
        proc = TIME.search(body)
        if proc:
            bucket['proc_us'].append(float(proc.group(1)))

    out: dict = {'log': str(path), 'channels': {}}
    for channel, bucket in sorted(channels.items()):
        entry: dict = {'lines': bucket['lines']}
        decoded = bucket['crc_ok'] + bucket['crc_ko']
        if decoded:
            entry['crc_ok'] = bucket['crc_ok']
            entry['crc_ko'] = bucket['crc_ko']
            entry['transmissions'] = decoded
            entry['bler_pct'] = round(100.0 * bucket['crc_ko'] / decoded, 4)
            entry['bler_resolution_pp'] = round(100.0 / decoded, 4)
        sinr = stats(bucket['sinr_db'])
        if sinr:
            entry['sinr'] = sinr
        if bucket['sinr_non_finite']:
            entry['sinr_non_finite'] = bucket['sinr_non_finite']
        if bucket['proc_us']:
            ordered = sorted(bucket['proc_us'])
            entry['proc_us'] = {
                'n': len(ordered),
                'p50': round(statistics.median(ordered), 1),
                'p99': round(ordered[min(len(ordered) - 1, int(0.99 * len(ordered)))], 1),
                'max': round(ordered[-1], 1),
            }
        out['channels'][channel] = entry
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('log', type=Path, help='gnb-internal.log from a run')
    parser.add_argument('--json', action='store_true', help='emit JSON instead of a table')
    args = parser.parse_args()
    if not args.log.is_file():
        raise SystemExit(f'no such log: {args.log}')
    data = summarize(args.log)
    if args.json:
        print(json.dumps(data, indent=2))
        return
    for channel, entry in data['channels'].items():
        bits = [f'{channel:<6} lines={entry["lines"]}']
        if 'bler_pct' in entry:
            bits.append(f'tx={entry["transmissions"]} crc_ko={entry["crc_ko"]} '
                        f'bler={entry["bler_pct"]}% (+-{entry["bler_resolution_pp"]}pp)')
        if 'sinr' in entry:
            s = entry['sinr']
            bits.append(f'sinr n={s["n"]} mean={s["mean_db"]}dB p50={s["p50_db"]}dB')
        if 'proc_us' in entry:
            p = entry['proc_us']
            bits.append(f't p50={p["p50"]}us p99={p["p99"]}us')
        print('  '.join(bits))


if __name__ == '__main__':
    main()
