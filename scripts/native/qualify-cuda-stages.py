#!/usr/bin/env python3
"""Run sequential native gates and preserve latency/integrity evidence."""
import argparse
import datetime
import json
import os
from pathlib import Path
import re
import subprocess


def compare_latency(cpu, cuda):
    delta = {node: 100 * (cuda[node] / value - 1) for node, value in cpu.items()
             if value > 0 and node in cuda}
    # Integer cross multiplication keeps an exact 80 -> 84 us boundary
    # inside 5%, without a floating-point 5.000000000000004 rejection.
    passed = set(delta) == {'gnb0', 'ue0'} and all(
        95 * cpu[node] <= 100 * cuda[node] <= 105 * cpu[node] for node in delta)
    return delta, passed


def extract(root, stamp, family='ocudu-interop'):
    report = root / 'results/reports' / family / stamp
    logs = root / 'results/logs' / family / stamp
    summary = json.loads((report / 'attach-summary.json').read_text())
    provenance = json.loads((report / 'source-evidence.json').read_text())
    broker = (logs / 'broker.log').read_text()
    phy = (logs / 'gnb-internal.log').read_text()
    latency = {m[0]: int(m[1]) for m in re.findall(r'event=process_latency_summary node=(\S+).*? p99_us=(\d+)', broker)}
    crc = re.findall(r'PUSCH:.*?crc=(OK|KO)', phy)
    result = dict(timestamp=stamp, summary=summary, provenance=provenance, p99_us=latency,
                pusch_crc_ok=crc.count('OK'), pusch_crc_ko=crc.count('KO'),
                acceleration_manifests=[s for s in phy.splitlines() if 'acceleration manifest:' in s or 'GPU path selected:' in s],
                timing_warnings=[s for s in phy.splitlines() if re.search(r'\b(?:late|dropped)\b|Real-time failure', s, re.I)])
    if (report / 'kpi-summary.json').exists():
        result['kpi'] = json.loads((report / 'kpi-summary.json').read_text())
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', choices=('c2', 'c3'), required=True)
    parser.add_argument('--metrics', action='store_true', help='separate 90-second traffic/KPI qualification')
    parser.add_argument('--acceleration', choices=('low-phy-rx', 'low-phy-tx', 'pusch', 'pdsch', 'prach', 'all'),
                        help='recheck one C3 stage; does not certify the entire stage campaign')
    args = parser.parse_args()
    if args.acceleration and args.stage != 'c3':
        parser.error('--acceleration requires --stage c3')
    repo = Path(__file__).resolve().parents[2]
    root = Path(os.environ['OCUDU_NATIVE_ROOT'])
    out = root / 'results/cuda-qualification' / (args.stage + '-' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    out.mkdir(parents=True)
    schedule = [('cpu', 'auto'), ('cuda', 'disabled')] * 3 if args.stage == 'c2' else [('cuda', x) for x in ('low-phy-rx', 'low-phy-tx', 'pusch', 'pdsch', 'prach', 'all')]
    if args.acceleration:
        schedule = [('cuda', args.acceleration)]
    if args.metrics and args.stage == 'c3':
        schedule.insert(0, ('cpu', 'auto'))
    family = 'ocudu-cuda-kpi' if args.metrics else 'ocudu-interop'
    records = []
    for number, (profile, acceleration) in enumerate(schedule):
        env = dict(os.environ, OCUDU_NATIVE_GNB_PROFILE=profile, OCUDU_NATIVE_GNB_ACCELERATION=acceleration,
                   OCUDU_NATIVE_CHANNEL_MODE='legacy', OCUDU_NATIVE_CONFIG_RENDERER=str(repo / 'scripts/native/render-legacy-1x1-configs.py'))
        env.pop('OCUDU_TIME_INTERP', None)
        env['OCUDU_NATIVE_CUDA_QUALIFICATION'] = '1' if args.metrics else '0'
        output = out / f'{number:02d}-{profile}-{acceleration}.log'
        with output.open('w') as stream:
            result = subprocess.run(['bash', str(repo / 'scripts/native/run-ocudu-legacy-1x1.sh')], env=env, stdout=stream, stderr=subprocess.STDOUT)
        text = output.read_text()
        stamps = re.findall(r'/reports/' + family + r'/(\d{8}T\d{6}Z)/attach-summary.json', text)
        record = dict(profile=profile, acceleration=acceleration, exit_code=result.returncode, launcher_log=str(output))
        if stamps:
            try:
                record.update(extract(root, stamps[-1], family))
            except (OSError, ValueError) as error:
                record.update(timestamp=stamps[-1], evidence_error=str(error))
        records.append(record)
        (out / 'runs.json').write_text(json.dumps(records, indent=2) + '\n')
        print(json.dumps({k: record[k] for k in ('profile', 'acceleration', 'exit_code', 'timestamp', 'p99_us') if k in record}), flush=True)
        if args.metrics and number == 0 and 'kpi' not in record:
            print('stopping: reference KPI capture failed', flush=True)
            break
    if args.stage == 'c2':
        pairs = []
        for cpu, cuda in zip(records[::2], records[1::2]):
            delta, latency_pass = compare_latency(cpu.get('p99_us', {}), cuda.get('p99_us', {}))
            pairs.append(dict(cpu=cpu.get('timestamp'), cuda=cuda.get('timestamp'), delta_percent=delta,
                              latency_pass=latency_pass))
        (out / 'c2-comparison.json').write_text(json.dumps(pairs, indent=2) + '\n')
        print(json.dumps(pairs), flush=True)
    print('qualification_evidence=' + str(out), flush=True)
    functional = len(records) == len(schedule) and all(r['exit_code'] == 0 and 'summary' in r and r['summary']['status'] == 'passed' for r in records)
    verdict = dict(functional_pass=functional, full_c3_kpi_qualified=False)
    if args.metrics and args.stage == 'c3':
        comparison = []
        baseline = records[0].get('kpi', {}).get('mean', {})
        for record in records[1:]:
            measured = record.get('kpi', {}).get('mean', {})
            delta = {key: measured[key] - baseline[key] for key in baseline if key in measured}
            passed = (record['exit_code'] == 0 and len(delta) == 5
                      and abs(delta['ul_bler_percent']) <= 1 and abs(delta['dl_bler_percent']) <= 1
                      and abs(delta['pusch_snr_db']) <= 0.5 and not record.get('timing_warnings'))
            latency, latency_pass = compare_latency(records[0].get('p99_us', {}), record.get('p99_us', {}))
            stages = ('low-phy-rx', 'low-phy-tx', 'pusch', 'pdsch', 'prach', 'all')
            expected = ('Lower-PHY RX GPU path selected:', 'Lower-PHY TX GPU path selected:',
                        'PUSCH acceleration manifest: requested=enabled backend=CUDA',
                        'PDSCH acceleration manifest: requested=enabled backend=CUDA',
                        'PRACH acceleration manifest: requested=enabled backend=CUDA',
                        'SRS acceleration manifest: requested=enabled resolved=enabled backend=CUDA')
            manifests = '\n'.join(record.get('acceleration_manifests', []))
            backend_pass = all(token in manifests for token in expected[:stages.index(record['acceleration'])+1])
            comparison.append(dict(stage=record['acceleration'], delta=delta, kpi_pass=passed,
                                   latency_delta_percent=latency, latency_pass=latency_pass, backend_pass=backend_pass))
        (out / 'kpi-comparison.json').write_text(json.dumps(comparison, indent=2) + '\n')
        verdict['kpi_pass'] = functional and all(r['kpi_pass'] for r in comparison)
        verdict['selected_stages_qualified'] = verdict['kpi_pass'] and all(r['latency_pass'] and r['backend_pass'] for r in comparison)
        verdict['full_c3_kpi_qualified'] = verdict['selected_stages_qualified'] and len(comparison) == 6
    if args.stage == 'c2':
        verdict['latency_pass'] = all(p['latency_pass'] for p in pairs)
    (out / 'verdict.json').write_text(json.dumps(verdict, indent=2) + '\n')
    passed = functional and verdict.get('latency_pass', True) and verdict.get('kpi_pass', True)
    if args.metrics and args.stage == 'c3':
        passed = passed and verdict['selected_stages_qualified']
    raise SystemExit(0 if passed else 1)


if __name__ == '__main__':
    main()
