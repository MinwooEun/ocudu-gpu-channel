#!/usr/bin/env python3
"""Validate extended attach evidence and summarize 60 scheduler reports.

This is a measurement gate, not a CPU/CUDA parity verdict. BLER follows the
producer's per-report NOK/(OK+NOK) definition; missing SINR is not zero.
"""
import argparse
import importlib.util
import json
import math
from pathlib import Path
import statistics
import time


def summarize(records):
    if len(records) != 60:
        raise ValueError(f'expected 60 reports, found {len(records)}')
    times = [r['monotonic_seconds'] for r in records]
    if not all(0.5 <= b - a <= 1.5 for a, b in zip(times, times[1:])):
        raise ValueError('scheduler reports are not consecutive at one-second cadence')
    values = {k: [] for k in ('ul_bler_percent', 'dl_bler_percent', 'pusch_snr_db', 'ul_mcs', 'dl_mcs')}
    identity = None
    for record in records:
        if len(record['rows']) != 1:
            raise ValueError('expected exactly one UE in every scheduler report')
        row = record['rows'][0]
        current = (row.get('rnti'), row.get('pci'))
        if identity is None:
            identity = current
        if current != identity:
            raise ValueError('UE identity changed during the measured window')
        for direction in ('ul', 'dl'):
            ok, nok = row[direction + '_nof_ok'], row[direction + '_nof_nok']
            if any(type(v) is not int or v < 0 for v in (ok, nok)) or ok + nok == 0:
                raise ValueError('missing traffic or invalid scheduler counts')
            values[direction + '_bler_percent'].append(100 * nok / (ok + nok))
        for key in ('pusch_snr_db', 'ul_mcs', 'dl_mcs'):
            value = row.get(key)
            if type(value) not in (int, float) or not math.isfinite(value) or (key == 'pusch_snr_db' and value <= -99.9):
                raise ValueError('missing or invalid ' + key)
            values[key].append(value)
    return dict(reports=60, window_seconds=times[-1]-times[0],
                mean={key: statistics.mean(items) for key, items in values.items()})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results-root', type=Path, required=True)
    parser.add_argument('--summary', type=Path, required=True)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('legacy_verifier', Path(__file__).with_name('verify-legacy-1x1-artifacts.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    counters = module.validate_artifacts(args.results_root, args.summary, time.time(), qualification=True)
    records = [json.loads(line) for line in (args.summary.parent / 'gnb-kpis.jsonl').read_text().splitlines()]
    result = summarize(records)
    result['broker_counters'] = counters
    (args.summary.parent / 'kpi-summary.json').write_text(json.dumps(result, indent=2) + '\n')
    print('event=cuda_kpi_measurement result=pass summary=' + str(args.summary))


if __name__ == '__main__':
    main()
