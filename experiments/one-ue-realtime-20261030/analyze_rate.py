"""Keep unrounded sample-clock rates and deadline-loss accounting together."""
import csv,json,pathlib,re,sys
p=pathlib.Path(sys.argv[1]); ram=p/'raw' if (p/'raw').exists() else pathlib.Path('/dev/shm/ocudu-one-ue-rt-20261030')
tags=[]
for line in (p/'runtime/logs/broker.log').read_text().splitlines():
 if 'event=control_sample_applied link_id=ue0>gnb0:sionna_rt tag=k=' not in line: continue
 vals=dict(re.findall(r'(\w+)=([^ ]+)',line)); tags.append((int(vals['sample']),int(vals['unix_ns'])))
assert len(tags)==400,len(tags)
rows=list(csv.DictReader((ram/'pacing/gnb0.csv').open()));out={}
for label,start in [('including_warmup',0),('post_warmup',100)]:
 a,b=tags[start],tags[-1]; radio=(b[0]-a[0])/23040000;wall=(b[1]-a[1])/1e9
 events=[e for e in rows if a[0]<=int(e['sample'])<b[0]]
 out[label]=dict(radio_s=radio,wall_s=wall,ratio=radio/wall,loss_us=(wall-radio)*1e6,rebase_count=len(events),rebase_sum_us=sum(int(e['shift_ns']) for e in events)/1000,largest_rebases=sorted(events,key=lambda e:int(e['shift_ns']),reverse=True)[:10])
out['qualification']=json.loads((p/'result.json').read_text())
(p/'rate-analysis.json').write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps({k:{a:b for a,b in v.items() if a!='largest_rebases'} for k,v in out.items() if k!='qualification'},indent=2))
