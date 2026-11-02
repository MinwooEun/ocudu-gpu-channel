import os,pathlib,json
os.environ['BOUND_IQ_BINARY']='iq-capacity-ready'
import run_case as engine
W=engine.W;results=[]
for mode in ['iq','radio']:
 engine.PROFILE='ready-start-iq' if mode=='iq' else 'matched-five-fast-cores'
 for bw in [50,100]:
  for rep in [2,3]:
   results.append(engine.run_case(mode,n=4,bw=bw,rep=rep));(W/'confirmation-results.json').write_text(json.dumps(results,indent=2))
engine.PROFILE='matched-five-fast-cores'
for rep in [2,3]:results.append(engine.run_case('radio',n=4,rep=rep))
if engine.HOST=='rtx':
 for rep in [2,3]:results.append(engine.run_case('radio',n=8,rep=rep))
else:
 engine.PROFILE='ready-start-iq'
 for rep in [2,3]:results.append(engine.run_case('iq',n=48,rep=rep))
(W/'confirmation-results.json').write_text(json.dumps(results,indent=2));print('CONFIRMATIONS COMPLETE',engine.HOST,flush=True)
