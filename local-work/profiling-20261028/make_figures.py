from pathlib import Path
import json,statistics,math
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
P=Path(__file__).parent
def read(name,default=None):
 p=P/name
 return json.loads(p.read_text()) if p.exists() else default
live=read('live-summary.json',[]);oai=read('oai-summary.json',[])
def receiver(label,kind,node='gnb0'):
 r=next(x for x in live if x['label']==label)
 return [q for q in r['receivers'] if q.get('kind')==kind and q.get('node')==node and q.get('window_complete')]
def norm(q,k):return q['metrics'][k]['mean']*q['calls']/(q['radio_samples']/23040000*1000)
fig,axs=plt.subplots(1,3,figsize=(15,4.8))
ns=[1,4,8,16];labels=[f'cuda-u{n}-c1-bw20-a1x1'+('-trace-only' if n==16 else '') for n in ns]
stages=[('room_us','Output space wait','#ed9d35'),('data_us','Input IQ wait','#c94141'),('process_us','Whole channel call','#2878b5'),('commit_pace_us','Commit and pacing','#b6bac2'),('read_us','Read','#68bda4'),('push_us','Publish','#8b62ac')]
bottom=[0.]*len(ns)
for key,title,color in stages:
 values=[statistics.mean(norm(q,key) for q in receiver(label,'broker'))/1000 for label in labels]
 axs[0].bar(range(len(ns)),values,bottom=bottom,label=title,color=color);bottom=[x+y for x,y in zip(bottom,values)]
axs[0].axhline(1,color='black',ls='--',lw=1);axs[0].set(xticks=range(len(ns)),xticklabels=ns,xlabel='UEs',ylabel='Wall ms per 1 ms of radio samples',title='Live broker: where one receiver waits');axs[0].legend(fontsize=7)
bottom=[0.]*len(ns)
for key,title,color in [('entry_pack_us','Entry and input packing','#70b7a4'),('model_control_us','Model and control','#b291c6'),('rx_prep_us','Receiver parameters','#e1b052'),('submit_us','CUDA submission','#518ac1'),('sync_wait_us','Stream completion wait','#dc7d6e'),('output_record_us','Output and recording','#acafb4')]:
 values=[statistics.mean(norm(q,key) for q in receiver(label,'channel')) for label in labels]
 axs[1].bar(range(len(ns)),values,bottom=bottom,label=title,color=color);bottom=[x+y for x,y in zip(bottom,values)]
axs[1].set(xticks=range(len(ns)),xticklabels=ns,xlabel='UEs',ylabel='Host wall microseconds per radio ms',title='Inside the channel call');axs[1].legend(fontsize=7)
for ant,marker in [('2x2','o'),('4x4','s')]:
 pts=sorted((int(r['label'].split('-bw')[1].split('-')[0]),r['rank']['realtime_factor']) for r in oai if r['label'].endswith('a'+ant))
 axs[2].plot([p[0] for p in pts],[p[1] for p in pts],marker=marker,label=ant)
axs[2].axhline(1,color='black',ls='--',lw=1);axs[2].set(xlabel='Bandwidth MHz',ylabel='Radio-time / wall-time',title='Live CUDA gNB + one OAI UE',ylim=(0,1.08),xticks=[20,50,100]);axs[2].legend()
fig.text(.02,.015,'Means use the 30-radio-second post-warmup window. 16 UEs: trace only. 1/4/8 UEs: diagnostic perf sampling also enabled.\nGPU-event durations overlap host intervals and are deliberately not added. OAI 100 MHz 4x4 fails the PUSCH health bound.',fontsize=8)
fig.tight_layout(rect=[0,.08,1,1]);fig.savefig(P/'live-time-breakdown.png',dpi=180);fig.savefig(P/'live-time-breakdown.pdf')

boundary=[]
for f in (P/'boundary').glob('*/result.json'):
 r=json.loads(f.read_text());r['ratio_min']=min(r['ratios']);boundary.append(r)
if boundary:
 fig,axs=plt.subplots(1,2,figsize=(11,4.4))
 for traced,ls in [(False,'-'),(True,'--')]:
  rows=sorted([r for r in boundary if r['bandwidth_mhz']==20 and r['cells']==1 and r['gnb_antennas']==r['ue_antennas']==1 and r['trace']==traced],key=lambda r:r['ues_per_cell'])
  axs[0].plot([r['ues_per_cell'] for r in rows],[r['ratio_min'] for r in rows],marker='o',ls=ls,label='Detailed trace' if traced else 'Tracing off')
 axs[0].axhline(1,color='black',ls=':',lw=1);axs[0].set(xlabel='UEs in one cell',ylabel='Minimum received sample-rate ratio',title='Spark broker, synthetic radios, 20 MHz');axs[0].legend()
 for ant,marker in [(1,'o'),(2,'s'),(4,'^')]:
  rows=sorted([r for r in boundary if r['ues_per_cell']==1 and r['cells']==1 and r['gnb_antennas']==r['ue_antennas']==ant and not r['trace']],key=lambda r:r['bandwidth_mhz'])
  axs[1].plot([r['bandwidth_mhz'] for r in rows],[r['ratio_min'] for r in rows],marker=marker,label=f'{ant}x{ant}')
 axs[1].axhline(1,color='black',ls=':',lw=1);axs[1].set(xlabel='Bandwidth MHz',ylabel='Minimum received sample-rate ratio',title='One synthetic UE: antenna and bandwidth cost',xticks=[20,50,100]);axs[1].legend()
 fig.text(.02,.01,'8-tap channel; 12 wall seconds per point. Broker: two ZMQ I/O threads, cores 5-14. Radios: cores 15-19.\nThese curves characterize the complete broker/transport path; they are distinct from real-radio live-stack qualification.',fontsize=8)
 fig.tight_layout(rect=[0,.09,1,1]);fig.savefig(P/'spark-boundary.png',dpi=180);fig.savefig(P/'spark-boundary.pdf')
