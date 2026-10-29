"""Collect live remedy trials without treating connectivity as real-time qualification."""
import collections
import json
from pathlib import Path

P = Path('/workspace/gpuch/profile-20261028')
out = []
for d in sorted((P / 'fixes').iterdir()):
    if not (d / 'result.json').exists():
        continue
    result = json.loads((d / 'result.json').read_text())
    entry = dict(result)
    entry['trial_directory'] = d.name
    entry['launch'] = json.loads((d / 'launch.json').read_text())
    report = d / 'runtime/report/run-report.json'
    if report.exists():
        r = json.loads(report.read_text())
        entry['segments_complete'] = r['segments_complete']
        entry['epoch'] = r['epoch']
        entry['radio_seconds_total'] = r['radio_seconds_total']
        entry['warmup_seconds'] = r['warmup_seconds']
        entry['measure_seconds'] = r['measure_seconds']
        segments = [s for s in r['segments'] if s['k'] >= r['warmup_seconds']]
        entry['invalid_segment_reasons'] = dict(collections.Counter(
            reason for s in segments for reason in s.get('reasons', [])))
        entry['kpi_valid_segments_only'] = r['metrics']
        entry['all_measurement_segment_means'] = {
            key: sum(s[key] for s in segments if s.get(key) is not None)
            / sum(s.get(key) is not None for s in segments)
            for key in ('dl_mbps', 'ul_mbps', 'decision_us_mean')
            if any(s.get(key) is not None for s in segments)
        }
        fault = r['runtime']['broker']
        entry['strict_zero_faults'] = all(fault.get(key) == 0 for key in (
            'rx_starvations', 'tx_queue_overflows', 'tx_sequence_gaps', 'zmq_errors'))
        # Applied updates provide an independent cumulative IQ progress check.
        links = collections.defaultdict(list)
        for line in (d / 'runtime/logs/replay-applied.jsonl').open():
            x = json.loads(line)
            if x.get('record') == 'applied':
                links[x['link_id']].append(x)
        rates = {}
        rate = r['epoch']['sample_rate_hz']
        for link, rows in links.items():
            rows.sort(key=lambda x: x['observed_sample'])
            if len(rows) > 1:
                a, b = rows[0], rows[-1]
                rates[link] = dict(
                    updates=len(rows),
                    radio_seconds=(b['observed_sample'] - a['observed_sample']) / rate,
                    wall_seconds=(b['observed_unix_ns'] - a['observed_unix_ns']) / 1e9,
                    ratio=(b['observed_sample'] - a['observed_sample']) / rate
                    / ((b['observed_unix_ns'] - a['observed_unix_ns']) / 1e9),
                )
        entry['independent_iq_progress'] = rates
    out.append(entry)
(P / 'live-fixes-summary.json').write_text(json.dumps(out, indent=2))
for r in out:
    print(r['trial_directory'], (r.get('metrics') or {}).get('real_time_ratio'),
          'valid', r.get('valid_segments'), 'strict', r.get('strict_zero_faults'))
