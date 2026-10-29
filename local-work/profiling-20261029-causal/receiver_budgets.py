import pathlib,csv,json,sys,collections
P=pathlib.Path(sys.argv[1]);r=json.load(open(P/'runtime/report/run-report.json'));lo=r['epoch']['s0']+r['warmup_seconds']*23040000;hi=lo+r['measure_seconds']*23040000;out=[]
for f in (P/'trace').glob('broker-*.csv'):
 seq=0;total=0;calls=0;sums=collections.defaultdict(float);node=None
 for row in csv.DictReader(f.open()):
  if None in row or any(v is None for v in row.values()):continue
  n=int(row['samples']);node=row['node']
  if lo<=seq<hi:
   calls+=1;total+=n
   for k,v in row.items():
    if k.endswith('_us'):sums[k]+=float(v)
  seq+=n
 if not total:continue
 ms=total/23040;out.append(dict(node=node,calls=calls,radio_ms=ms,us_per_radio_ms={k:v/ms for k,v in sums.items()}))
assert out
print(json.dumps(out,indent=2))
