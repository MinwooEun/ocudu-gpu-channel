"""Build an offline, single-file visual explanation from preserved measurements."""
import csv
import hashlib
import json
import re
import statistics as st
from pathlib import Path

HERE = Path(__file__).resolve().parent
LAB = HERE.parent
load = lambda name: json.loads((LAB / name).read_text())
live = load('live-summary.json')
by_label = {x['label']: x for x in live}
cases = []
for n in (1, 4, 8, 16):
    base = f'cuda-u{n}-c1-bw20-a1x1'
    trace = by_label[base + ('-trace-only' if n == 16 else '')]
    ref = by_label.get(base + '-control', trace)
    entries = [x for x in trace['receivers'] if x.get('node') == 'gnb0'
               and x.get('window_complete') and 'metrics' in x]
    rec = {}
    for kind in ('broker', 'channel'):
        group = [x for x in entries if x['kind'] == kind]
        assert group, (n, kind)
        normalized = []
        for x in group:
            run = next(r for r in trace['runs'] if r['run'] == x['run'])
            radio_ms = x['radio_samples'] / run['rate'] * 1000
            normalized.append({key: value['mean'] * x['calls'] / radio_ms
                               for key, value in x['metrics'].items()})
        rec[kind] = {key: st.mean(x[key] for x in normalized) for key in normalized[0]}
        if kind == 'broker':
            rec['calls_per_radio_ms'] = st.mean(
                x['calls'] / (x['radio_samples'] / trace['runs'][0]['rate'] * 1000)
                for x in group)
            rec['timing_runs'] = [x['run'] for x in group]
    cases.append(dict(ues=n, trace_ratios=[r['runtime']['real_time_ratio'] for r in trace['runs']],
                      reference_ratios=[r['runtime']['real_time_ratio'] for r in ref['runs']],
                      reference_valid=[r['segments_valid'] for r in ref['runs']],
                      method='receiver CSV only' if n == 16 else 'diagnostic capture including CPU sampling',
                      trace_label=trace['label'], reference_label=ref['label'], **rec))

fix_labels = {
    'baseline': '원래 설정', 'baseline-repeat': '원래 설정 · 반복',
    'sleep': '내부 대기를 sleep으로', 'poll10': 'sleep 간격 10 µs',
    'broker4': 'broker 4코어 + I/O 4개 · sleep',
    'broker4-spin': 'broker 4코어 + I/O 4개 · spin',
    'ue5big-shared': 'UE big core 5개 · 공유 + sleep',
    'ue5big-spin': 'UE big core 5개 · 개별 고정',
    'ue5big-spin-repeat': 'UE big core 5개 · 개별 고정 · 반복',
    'cuda-blocking-sleep': 'GPU 완료 대기도 CPU를 재움 · sleep',
}
fixes = []
for x in load('live-fixes-summary.json'):
    if not x.get('metrics'):
        continue
    name = x['trial_directory']
    fixes.append(dict(id=name, label=fix_labels[name], ratio=x['metrics']['real_time_ratio'],
                      valid=x['valid_segments'], complete=x['segments_complete'],
                      faults=x['metrics']['broker'], attached=x['gate']['all_ues_attached'],
                      gate=x['gate']['status'], strict=x['strict_zero_faults'],
                      exclusions=x['invalid_segment_reasons'], changes=x['launch']['changes'],
                      iq_min=min(v['ratio'] for v in x['independent_iq_progress'].values()),
                      iq_max=max(v['ratio'] for v in x['independent_iq_progress'].values()),
                      report=f'fixes/{name}/runtime/report/run-report.json'))
fixes.sort(key=lambda x: list(fix_labels).index(x['id']))

oai = []
for x in load('oai-summary.json'):
    m = re.search(r'bw(\d+)-a(\d+)x(\d+)', x['label'])
    oai.append(dict(bw=int(m[1]), g=int(m[2]), u=int(m[3]),
                    ratio=x['rank']['realtime_factor'], health=x['rank']['health'],
                    label=x['label']))
boundary = list(csv.DictReader((LAB / 'boundary-results.csv').open()))
synthetic = [dict(ues=int(x['ues']), ratio=float(x['ratio_min']), label=x['label'])
             for x in boundary if x['group'] == 'boundary' and x['trace'] == 'False'
             and x['bandwidth_mhz'] == '20' and x['gnb_antennas'] == '1'
             and x['ue_antennas'] == '1']
synthetic.sort(key=lambda x: x['ues'])
audit = load('audit-5090.json')
a64 = next(x for x in audit['results'] if x['ues'] == 64)
audit64 = {key: {percentile: st.median(r[key][percentile] for r in a64['runs'])
                 for percentile in ('p50_us', 'p99_us')}
           for key in a64['runs'][0]}
source_names = ['live-summary.json', 'live-fixes-summary.json', 'live-fixes-results.csv',
                'oai-summary.json', 'boundary-results.csv', 'audit-5090.json',
                'nsys-summary.json', 'thread-runtime-steady-summary.json',
                'live-fixes-channel-cpu.json', 'two-cell-control-summary.json',
                'report.txt', 'live-fixes.ko.txt', 'instrumentation.patch', 'blocking-sync.patch']
fanin_dir = LAB.parent / 'ocudu-upstream-main/docs/reports/performance/2026-10-13-fanin'
prep_runs = []
for n in (1, 2, 3):
    f = fanin_dir / f'N8.{n}.csv'
    records = list(csv.reader(f.open()))
    columns = next(row for row in records if row[0] == 'metric')
    row = next(row for row in records if row[0] == 'node:gnb0:host_prep_us')
    assert next(row for row in records if row[0] == 'cuda_zero_copy')[1] == '0'
    prep_runs.append(dict(repeat=n, p99_us=float(row[columns.index('p99_us')]),
                          source=str(f.relative_to(LAB.parent))))
    source_names.append('../' + str(f.relative_to(LAB.parent)))
source_names += ['../ocudu-upstream-main/docs/reports/performance/2026-10-13-fanin/README.md',
                 '../ocudu-upstream-main/docs/history/milestones/ZERO_COPY_MILESTONES.md',
                 '../perf-platform/compare-zc-z8.md',
                 'explainer/spark-direct-input-observation.json']
sources = [dict(name=name, sha256=hashlib.sha256((LAB / name).read_bytes()).hexdigest())
           for name in source_names]
code = {}
for name, lo, hi in [('broker.cpp', 1153, 1193), ('broker.cpp', 1212, 1283),
                     ('cuda_backend.cu', 1499, 1520)]:
    lines = (LAB / 'src/src' / name).read_text().splitlines()
    code[f'{name}:{lo}'] = '\n'.join(f'{i + 1:4d}  {lines[i]}' for i in range(lo - 1, hi))
data = dict(date='2026-10-28', cases=cases, fixes=fixes, oai=oai,
            synthetic=synthetic, audit64=audit64, audit_checksums=len(audit['checksums']),
            audit_verified=audit['all_checksums_match'],
            cpu=load('thread-runtime-steady-summary.json'),
            channel_cpu=load('live-fixes-channel-cpu.json'),
            cells=load('two-cell-control-summary.json'),
            nsys=[dict(label=Path(x['report']).parent.name,
                       kernel_count=x['kernel_count'],
                       window_s=x['kernel_activity_window_s'],
                       kernel_union_fraction=x['kernel_union_fraction'],
                       memcpy=x['memcpy_by_kind']) for x in load('nsys-summary.json')],
            sources=sources, code=code,
            preparation_origin=dict(date='2026-10-13', hardware='RTX 5090',
                                    incoming_tx_ports=8, batch_samples=23040,
                                    rate_hz=23040000, mode='copy', real_radios=False,
                                    metric='node:gnb0:host_prep_us', runs=prep_runs,
                                    median_p99_us=st.median(r['p99_us'] for r in prep_runs)),
            spark_direct=json.loads((HERE / 'spark-direct-input-observation.json').read_text()),
            provenance=dict(broker='364391bccd3abd5fb73946e50c3a4c95ce649551',
                            pr10='9a33e0c2de17d5e8030ea570f57ba0fc08075fce',
                            sample_rate_hz=23040000, bandwidth_mhz=20,
                            host='DGX Spark GB10', tracing='receiver-local host clocks and CUDA events'))
template = (HERE / 'explainer.template.html').read_text()
payload = json.dumps(data, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c')
assert template.count('__MEASURED_DATA__') == 1
html = template.replace('__MEASURED_DATA__', payload)
out = LAB / 'profiling-explained.ko.html'
out.write_text(html)
(HERE / 'embedded-data.json').write_text(json.dumps(data, ensure_ascii=False, indent=2))
print(f'Built {out} ({out.stat().st_size:,} bytes)')
