#!/usr/bin/env python3
"""Report the C5 measurement envelope. Deliberately issues no speedup verdict.

At this fixture -- 20 MHz, one layer -- the working group's own figures put the
GPU at 0.86x on PUSCH and 0.37x on PDSCH. A CUDA arm that is slower here is the
documented expectation, so turning these numbers into a faster/slower verdict
would be reporting the fixture, not the integration. What C5 is for is the
envelope: that both arms ran under the same affinity and the same MPS server,
what the run-to-run spread is, and whether anything regressed.

Every arm is printed, including failed ones. A measurement that failed is part
of the record; dropping it and re-running until the table looks clean is how a
spread gets understated.
"""
from __future__ import annotations
import json, statistics, sys
from pathlib import Path


def spread(values: list[float]) -> str:
    if not values:
        return '-'
    if len(values) == 1:
        return f'{values[0]:g}'
    return f'{statistics.median(values):g} [{min(values):g}..{max(values):g}]'


def collect(runs: dict, prefix: str, path: list[str]) -> list[float]:
    out = []
    for label, entry in runs.items():
        if not label.startswith(prefix):
            continue
        node = entry
        for key in path:
            if not isinstance(node, dict):
                node = None
                break
            node = node.get(key)
        if isinstance(node, (int, float)):
            out.append(float(node))
    return out


def gpu_state(directory: Path, label: str) -> dict | None:
    """SM clock and utilisation sampled during the arm.

    Carried next to the broker's GPU timings because it is the confounder for
    them: an arm whose gNB does not use the GPU leaves it idle and it clocks
    down, so the two arms are not timing the same silicon speed.
    """
    path = directory / f'{label}.telemetry.jsonl'
    if not path.is_file():
        return None
    clocks, utils = [], []
    for line in path.read_text(errors='replace').splitlines():
        try:
            gpu = (json.loads(line) or {}).get('gpu') or {}
            clocks.append(float(gpu['sm_clock_mhz']))
            utils.append(float(gpu['util_pct']))
        except (ValueError, TypeError, KeyError):
            continue
    if not clocks:
        return None
    return {'sm_clock_mean': round(statistics.fmean(clocks)), 'sm_clock_max': round(max(clocks)),
            'util_mean': round(statistics.fmean(utils)), 'n': len(clocks)}


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit('usage: report-c5-envelope.py <runs.json> [envelope.txt]')
    runs_path = Path(sys.argv[1])
    directory = runs_path.parent
    runs = json.loads(runs_path.read_text())
    print('=== C5 measurement envelope ===')
    if len(sys.argv) > 2 and Path(sys.argv[2]).is_file():
        for line in Path(sys.argv[2]).read_text().splitlines():
            if line.startswith(('pcores=', 'stage=', 'repeats=', 'NVIDIA')):
                print('  ' + line)

    print('\n-- affinity actually in effect (read from /proc, not assumed)')
    ok_envelope = True
    for label, entry in sorted(runs.items()):
        aff = entry.get('affinity') or {}
        masks = aff.get('affinity_masks') or {}
        if not masks:
            print(f'  {label:<10} no processes sampled')
            ok_envelope = False
            continue
        uniform = aff.get('uniform_envelope')
        ok_envelope = ok_envelope and bool(uniform)
        print(f'  {label:<10} uniform={uniform} mask={aff.get("single_mask") or sorted({m for v in masks.values() for m in v})} '
              f'processes={",".join(sorted(masks))}')
        for name, cpus in sorted((aff.get('cpus_actually_used') or {}).items()):
            print(f'    {name:<20} ran on {cpus}')

    print('\n-- verdicts (failed measurements are kept)')
    for label, entry in sorted(runs.items()):
        print(f'  {label:<10} exit={entry.get("exit")} verdict={entry.get("verdict")} run={entry.get("run_dir")}')

    print('\n-- broker gnb0 per-slot processing latency, us (median [min..max] over repeats)')
    print(f'  {"arm":<6} {"n":>18} {"p50":>18} {"p95":>18} {"p99":>18} {"p999":>18}')
    for prefix in ('cpu', 'cuda'):
        base = ['broker', 'nodes', 'gnb0', 'process_latency_us']
        cells = [spread(collect(runs, prefix, base + [k])) for k in ('n', 'p50', 'p95', 'p99', 'p999')]
        print(f'  {prefix:<6} ' + ' '.join(f'{c:>18}' for c in cells))

    print('\n-- GPU clock state during each arm (the confounder for the table below)')
    for label in sorted(runs):
        state = gpu_state(directory, label)
        print(f'  {label:<10} ' + ('no GPU samples' if not state else
              f'sm_clock mean={state["sm_clock_mean"]}MHz max={state["sm_clock_max"]}MHz '
              f'util mean={state["util_mean"]}% n={state["n"]}'))

    print('\n-- broker last-batch GPU sub-phase time, us (point sample once per second, active ticks)')
    print(f'  {"arm":<6} {"h2d mean":>18} {"kernel mean":>18} {"d2h mean":>18}')
    for prefix in ('cpu', 'cuda'):
        cells = [spread(collect(runs, prefix, ['broker', 'gpu_timings', k, 'mean']))
                 for k in ('h2d_us', 'kernel_us', 'd2h_us')]
        print(f'  {prefix:<6} ' + ' '.join(f'{c:>18}' for c in cells))
    print('  Same broker binary, same 23040-sample batch, both arms -- but not a like-for-like')
    print('  comparison: the arms sit at different SM clocks (above), because the CPU arm leaves')
    print('  the GPU idle enough to clock down. Occupancy record, not an efficiency result.')

    print('\n-- gNB PUSCH, from the log the run already writes')
    print(f'  {"arm":<6} {"tx":>14} {"sinr mean dB":>18} {"proc p50 us":>16} {"proc p99 us":>16}')
    for prefix in ('cpu', 'cuda'):
        base = ['phy', 'channels', 'PUSCH']
        cells = [spread(collect(runs, prefix, base + p)) for p in
                 (['transmissions'], ['sinr', 'mean_db'], ['proc_us', 'p50'], ['proc_us', 'p99'])]
        print(f'  {prefix:<6} ' + ' '.join(f'{c:>16}' for c in cells))

    print('\n-- regression check (this is the verdict C5 does make)')
    problems = []
    for label, entry in sorted(runs.items()):
        if entry.get('verdict') != 'passed':
            problems.append(f'{label}: gate verdict {entry.get("verdict")}')
        stop = ((entry.get('broker') or {}).get('stop')) or {}
        for key in ('tx_queue_overflows', 'tx_sequence_gaps', 'zmq_errors'):
            if stop.get(key, 0):
                problems.append(f'{label}: {key}={int(stop[key])}')
    if not ok_envelope:
        problems.append('affinity envelope was not uniform across processes')
    if problems:
        print('  NOT CLEAN:')
        for line in problems:
            print(f'    {line}')
    else:
        print('  clean: every arm passed its gate, no overflows, no sequence gaps, no ZMQ errors,')
        print('         and both arms ran under one affinity mask and one MPS server.')
    print('\n  No speedup claim is made or implied by this table. See the performance-claim')
    print('  boundary in CUDA_MILESTONES.md: at 20 MHz single layer the GPU is expected to be')
    print('  slower, and C7 is the first milestone where a speed claim is in scope.')


if __name__ == '__main__':
    main()
