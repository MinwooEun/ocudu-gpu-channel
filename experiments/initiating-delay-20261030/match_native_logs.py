"""Corroborate probe stages against native UE PDSCH timing/iteration logs."""
import pathlib,json,datetime,bisect,re
base=pathlib.Path('/workspace/gpuch/realtime-rate-20261030/u1')
for tag in ['original-input-root2-r2','original-input-root3-r1']:
 p=base/tag;a=json.loads((p/'causal-operation-matches.json').read_text());ref=json.loads((p/'launch.json').read_text())['clock_reference'];offset=ref['unix_ns']-ref['monotonic_ns'];logs=[]
 for l in (p/'runtime/logs/srsue-ue0-internal.log').open():
  if 'PDSCH: cc' not in l:continue
  t=int(datetime.datetime.fromisoformat(l[:26]).replace(tzinfo=datetime.timezone.utc).timestamp()*1e9);logs.append((t,l.strip()))
 ts=[t for t,l in logs];out=[]
 for row in a['events']:
  if row['event']['first_late_stage']!='UE IQ preparation / pre-send entry':continue
  t=row['event']['times']['ue_rf_tx_enter']+offset;i=bisect.bisect_right(ts,t)-1
  if i<0:continue
  log_t,line=logs[i];gap=(t-log_t)/1000
  if not 0<=gap<100:continue
  row['native_log']=dict(line=line,rf_entry_minus_log_us=gap);out.append(row)
 out.sort(key=lambda x:x['event']['shift_us'],reverse=True)
 (p/'native-log-matches.json').write_text(json.dumps(dict(note='Nearest preceding PDSCH log within 100 us of RF TX entry using launch wall/monotonic anchor; retain gap for audit. Probed diagnostic runs include observer overhead.',matched_events=len(out),events=out),indent=2)+'\n')
 print(tag)
 for row in out[:3]:print(row['event']['sample'],row['event']['shift_us'],row['native_log'])
