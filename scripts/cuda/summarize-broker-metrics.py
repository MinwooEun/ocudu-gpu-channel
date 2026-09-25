#!/usr/bin/env python3
"""Summarise a broker run log into the numbers C5 compares.

Everything here is already in broker.log; this only parses it, so a measurement
never depends on instrumentation that the measured run did not have.

`gpu_timings` is a once-per-second point sample of `processor_->last_timings()`
-- the h2d/kernel/d2h of the single most recently completed batch -- not a sum
or an average over the tick. So it is aggregated over *active* ticks only, and
the active and total counts are reported: a run whose gNB spends 20 s starting
up contributes idle ticks whose last-batch timing is still zero, and averaging
those in makes the arm with the slower startup look like it does less GPU work.
On the first paired sweep the CPU arm had 1 idle tick of 14 and the CUDA arm 20
of 44.

Because it is per batch, and both arms use the same 23040-sample batch, the
figure is comparable between arms in principle. In practice it is not a clean
comparison, for a reason outside this file: an arm whose gNB does not use the
GPU leaves it mostly idle and it clocks down. Measured on the paired sweep, the
CPU arm sat at 1923-2080 MHz against the CUDA arm's 2363 MHz. Read these as an
occupancy record, not as an efficiency comparison, and read the SM clock beside
them.
"""
from __future__ import annotations
import argparse, json, re, statistics, sys
from pathlib import Path

LATENCY = re.compile(r'event=process_latency_summary node=(?P<node>\S+) n=(?P<n>\d+) '
                     r'p50_us=(?P<p50>[\d.]+) p95_us=(?P<p95>[\d.]+) p99_us=(?P<p99>[\d.]+) '
                     r'p999_us=(?P<p999>[\d.]+) max_us=(?P<max>[\d.]+)')
STOP = re.compile(r'event=stop (?P<body>.*)')
KV = re.compile(r'(\w+)=([\d.]+)')
STAGE = re.compile(r'event=cpu_stage_timings t=(?P<t>\d+) node=(?P<node>\S+) (?P<body>.*)')
GPU = re.compile(r'event=gpu_timings t=(?P<t>\d+) (?P<body>.*)')
STALL = re.compile(r'event=node_stall node=(?P<node>\S+) phase=(?P<phase>\S+) waited_ms=(?P<ms>\d+)')


def pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(q * len(ordered)))], 3)


def summarize(path: Path) -> dict:
    out: dict = {'log': str(path), 'nodes': {}, 'stop': {}, 'gpu_timings': {}, 'stalls': []}
    stages: dict[str, dict[str, list[float]]] = {}
    gpu_ticks: list[dict[str, float]] = []
    for line in path.read_text(errors='replace').splitlines():
        match = LATENCY.search(line)
        if match:
            d = match.groupdict()
            out['nodes'].setdefault(d['node'], {})['process_latency_us'] = {
                'n': int(d['n']), 'p50': float(d['p50']), 'p95': float(d['p95']),
                'p99': float(d['p99']), 'p999': float(d['p999']), 'max': float(d['max'])}
            continue
        match = STOP.search(line)
        if match:
            out['stop'] = {k: float(v) for k, v in KV.findall(match.group('body'))}
            continue
        match = STAGE.search(line)
        if match:
            node = stages.setdefault(match.group('node'), {})
            for key, value in KV.findall(match.group('body')):
                node.setdefault(key, []).append(float(value))
            continue
        match = GPU.search(line)
        if match:
            entry = {k: float(v) for k, v in KV.findall(match.group('body'))}
            entry['t'] = float(match.group('t'))  # the regex pulls t out of body
            gpu_ticks.append(entry)
            continue
        match = STALL.search(line)
        if match:
            out['stalls'].append(match.groupdict())

    for node, series in sorted(stages.items()):
        entry = out['nodes'].setdefault(node, {})
        entry['cpu_stage_us'] = {
            key: {'n': len(v), 'mean': round(statistics.fmean(v), 3),
                  'p50': pct(v, 0.50), 'p99': pct(v, 0.99), 'max': round(max(v), 3)}
            for key, v in sorted(series.items()) if key != 't'}
    # A tick counts as active if the broker did any GPU work in it. Idle ticks
    # are excluded from the statistics and counted separately, so a window that
    # contains more startup does not masquerade as lighter GPU use.
    def is_active(tick: dict[str, float]) -> bool:
        return any(v > 0.0 for k, v in tick.items() if k != 't')

    active = [tick for tick in gpu_ticks if is_active(tick)]
    out['gpu_tick_counts'] = {'total': len(gpu_ticks), 'active': len(active),
                              'idle': len(gpu_ticks) - len(active)}
    keys = sorted({k for tick in gpu_ticks for k in tick} - {'t'})
    for key in keys:
        values = [tick.get(key, 0.0) for tick in active]
        out['gpu_timings'][key] = {
            'n_active': len(values),
            'mean': round(statistics.fmean(values), 3) if values else 0.0,
            'p99': pct(values, 0.99), 'max': round(max(values), 3) if values else 0.0,
            'all_zero': not values or all(v == 0.0 for v in values)}

    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('log', type=Path)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    if not args.log.is_file():
        raise SystemExit(f'no such log: {args.log}')
    data = summarize(args.log)
    if args.json:
        print(json.dumps(data, indent=2))
        return
    for node, entry in data['nodes'].items():
        lat = entry.get('process_latency_us')
        if lat:
            print(f'{node:<6} slots={lat["n"]:<7} p50={lat["p50"]}us p95={lat["p95"]}us '
                  f'p99={lat["p99"]}us p999={lat["p999"]}us max={lat["max"]}us')
    if data['stop']:
        print('stop   ' + ' '.join(f'{k}={int(v)}' for k, v in data['stop'].items()))
    if data['gpu_timings']:
        counts = data.get('gpu_tick_counts', {})
        zeros = [k for k, v in data['gpu_timings'].items() if v['all_zero']]
        head = f'gpu    ticks active={counts.get("active")}/{counts.get("total")} '
        print(head + ('all zero — no channel model on this run'
                      if len(zeros) == len(data['gpu_timings'])
                      else ' '.join(f'{k}: mean={v["mean"]}us p99={v["p99"]}us'
                                    for k, v in data['gpu_timings'].items())))
    if data['stalls']:
        print(f'stalls {len(data["stalls"])} (max waited_ms='
              f'{max(int(s["ms"]) for s in data["stalls"])})')


if __name__ == '__main__':
    main()
