"""Align native PDSCH logs with replay windows, retaining boundary exclusions."""
import pathlib,json,re,datetime,bisect,collections,numpy as np
base=pathlib.Path('/workspace/gpuch/receiver-quality-20261030');prediction=json.loads((base/'noiseless-estimator-prediction.json').read_text());pred={r['k']:r['noise_free_snr_db'] for r in prediction['rows']};results={}
pattern=re.compile(r'PDSCH:.*?prb=\((\d+),(\d+)\).*?mod=(\S+) tbs=(\d+) R=([\d.]+) rv=(\d+) CRC=(\S+) iter=([\d.]+) evm=([\d.]+) t_us=(\d+).*?snr=([+-]?[\d.]+)')
for tag in ['original-iq-r1','control-noise-r1','zero-noise-r1','zero-noise-r2','control-noise-r2']:
 p=base/'u1'/tag;points=[]
 for line in (p/'runtime/logs/replay-applied.jsonl').open():
  r=json.loads(line)
  if r.get('record')=='applied' and r.get('link_id')=='gnb0>ue0:sionna_rt':points.append((r['observed_unix_ns'],r['k']))
 points.sort();times=[x[0] for x in points];rows=[];byk=collections.defaultdict(list)
 for line in (p/'runtime/logs/srsue-ue0-internal.log').open():
  if 'c-rnti=' not in line:continue
  m=pattern.search(line)
  if not m:continue
  t=int(datetime.datetime.fromisoformat(line[:26]).replace(tzinfo=datetime.timezone.utc).timestamp()*1e9);i=bisect.bisect_right(times,t)-1
  if i<0 or i+1>=len(points):continue
  if min(t-times[i],times[i+1]-t)<10000000:continue
  k=points[i][1]
  if k<100:continue
  start,n,mod,tbs,R,rv,crc,it,evm,dur,snr=m.groups();r=dict(k=k,start_prb=int(start),prbs=int(n),mod=mod,tbs=int(tbs),rate=float(R),rv=int(rv),crc=crc,iterations=float(it),evm=float(evm),native_pdsch_us=int(dur),snr_db=float(snr));rows.append(r)
  if int(start)==0 and int(n)==95:byk[k].append(r)
 def stats(a):
  return dict(count=len(a),crc_fail=sum(r['crc']=='KO' for r in a),avg_iterations=float(np.mean([r['iterations'] for r in a])),iterations_ge8=sum(r['iterations']>=8 for r in a),pdsch_us_percentiles=dict(zip(['p50','p95','p99','max'],np.percentile([r['native_pdsch_us'] for r in a],[50,95,99,100]).tolist())),evm_median=float(np.median([r['evm'] for r in a]))) if a else None
 grouped={str(k):dict(snr_median=float(np.median([r['snr_db'] for r in v])),predicted_noiseless_snr=pred[k],stats=stats(v)) for k,v in byk.items()};paired=[(x['snr_median'],x['predicted_noiseless_snr']) for x in grouped.values()];corr=np.corrcoef(np.array(paired).T)[0,1]
 res=dict(result=json.loads((p/'result.json').read_text()),all=stats(rows),negative_reported_snr=stats([r for r in rows if r['snr_db']<0]),by_k_95prb=grouped,noiseless_prediction_vs_live_correlation=float(corr),per_pdsch=rows)
 (p/'native-analysis.json').write_text(json.dumps(res,indent=2)+'\n');results[tag]={k:v for k,v in res.items() if k!='per_pdsch'}
 print(tag,'ALL',res['all'],'NEG',res['negative_reported_snr'],'CORR',corr)
 for k in [293,296,297,398]:print('k',k,grouped.get(str(k)))
(base/'native-comparison.json').write_text(json.dumps(dict(method='Post-warmup native c-rnti PDSCH logs assigned to preceding DL applied update timestamp, excluding 10 ms around either boundary. Timing alone is not a sample-exact PHY slot association.',runs=results),indent=2)+'\n')
