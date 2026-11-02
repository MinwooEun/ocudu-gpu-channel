import pathlib,subprocess as sp,json,sys
b=pathlib.Path('/workspace/gpuch/multi-ue-affinity-20261102');cases=[(1,'on','multi-u1-on-r2'),(4,'on','multi-u4-on-r1'),(8,'off','multi-u8-off-r1'),(8,'on','multi-u8-on-r1'),(16,'off','multi-u16-off-r1'),(16,'on','multi-u16-on-r1')];rows=[]
if sys.argv[1:]==['retry16']:
 cases=[(16,'on','multi-u16-on-r2')];rows=json.loads((b/'batch-results.json').read_text())
for n,mode,tag in cases:
 p=b/f'u{n}'/('original-'+tag)
 print('BEGIN',n,mode,tag,flush=True)
 if (p/'verification.json').exists():raise RuntimeError('refusing to overwrite '+str(p))
 r=sp.run(['python3',str(b/'run.py'),str(n),mode,tag]);row=dict(ues=n,patch=mode,case=str(p),controller_returncode=r.returncode)
 for name in ['result','verification']:
  f=p/(name+'.json')
  if f.exists():row[name]=json.loads(f.read_text())
 if (p/'result.json').exists() and row['result'].get('returncode')==0:
  with (p/'rate-analysis.log').open('w') as log:a=sp.run(['python3','/workspace/gpuch/one-ue-realtime-20261030/analyze_rate.py',str(p)],stdout=log,stderr=sp.STDOUT)
  if a.returncode==0:row['rate']=json.loads((p/'rate-analysis.json').read_text())
 rows.append(row);(b/'batch-results.json').write_text(json.dumps(rows,indent=2)+'\n')
 print('RESULT',n,mode,json.dumps(dict(runtime=row.get('result',{}).get('metrics'),valid=row.get('result',{}).get('valid_segments'),verified=row.get('verification'),post=row.get('rate',{}).get('post_warmup',{}).get('ratio'))),flush=True)
