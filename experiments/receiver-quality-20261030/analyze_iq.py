"""Compare captured GPU-channel output to independently reconstructed frozen FIR."""
import pathlib,json,numpy as np
from scipy.signal import lfilter
p=pathlib.Path('/workspace/gpuch/receiver-quality-20261030/u1/original-iq-r1')
manifest=json.loads((p/'iq/wire-capture.json').read_text());skip=manifest['skip_samples'];count=manifest['samples_per_port']
x=np.memmap(p/'iq/gnb0_p0.tx_in.cf32',dtype=np.complex64,mode='r');y=np.memmap(p/'iq/ue0_p0.rx_out.cf32',dtype=np.complex64,mode='r');assert len(x)==count and len(y)==count
report=json.loads((p/'runtime/report/run-report.json').read_text());s0=report['epoch']['s0'];fs=23040000
trace=pathlib.Path('/workspace/ocudu-spark-ranb/results/single-cell-scheduler-benchmark/tagged-profile1028-u1-20261028T075717Z-g160/bundle/channel/channel-trace.jsonl');out=[]
for line in trace.open():
 row=json.loads(line);k=row.get('k')
 if k is None:continue
 start=s0+k*2304000
 if start<skip+100 or start+2304000>=skip+count:continue
 taps=json.loads(next(m for m in row['messages'] if json.loads(m)['link_id']=='gnb0>ue0:sionna_rt'))['lanes'][0]['taps'];h=np.zeros(int(np.ceil(max(t['delay_samples'] for t in taps)))+8,dtype=np.complex128)
 for t in taps:
  delay=int(np.floor(t['delay_samples']));frac=t['delay_samples']-delay;idx=np.arange(8);c=np.sinc(idx-3-frac)*(.54-.46*np.cos(2*np.pi*idx/7));c=c.astype(np.float32);c*=np.float32(1/sum(np.sinc(idx-3-frac)*(.54-.46*np.cos(2*np.pi*idx/7))))
  a=10**(t['gain_db']/20)*np.exp(1j*t['phase_rad'])
  for i,v in enumerate(c):
   d=delay-3+i
   if d>=0:h[d]+=a*v
   else:assert abs(v)<1e-10,(k,t,d,v)
 for offset in [23040*2,23040*30,23040*55,23040*90]:
  n=start+offset-skip;size=23040*3;src=np.asarray(x[n-len(h):n+size],dtype=np.complex128);pred=lfilter(h,[1.0],src)[len(h):];actual=np.asarray(y[n:n+size],dtype=np.complex128)
  # Fit optional constant gain/phase to distinguish alignment/model mismatch.
  fit=np.vdot(pred,actual)/np.vdot(pred,pred);err=actual-pred;fitted=actual-fit*pred
  sp=float(np.mean(abs(pred)**2));npow=float(np.mean(abs(err)**2));fpow=float(np.mean(abs(fitted)**2));txp=float(np.mean(abs(src[len(h):])**2))
  out.append(dict(k=k,offset_ms=offset/fs*1000,absolute_sample=start+offset,tx_power=txp,predicted_signal_power=sp,output_power=float(np.mean(abs(actual)**2)),raw_residual_power=npow,fitted_residual_power=fpow,nominal_noise_power=1.12e-6,reconstructed_snr_db=float(10*np.log10(sp/npow)),fit_re=float(fit.real),fit_im=float(fit.imag)))
r=dict(manifest=manifest,epoch_s0=s0,method='Independent float64 FIR from frozen tap phases/gains and normalized 8-tap Hamming sinc. Excludes update boundary and uses preceding input history.',windows=out)
(p/'iq-analysis.json').write_text(json.dumps(r,indent=2)+'\n')
for k in [230,250,270,290,293,297,300,310,320]:
 a=[z for z in out if z['k']==k];print(k,a)
print('windows',len(out),'median error/noise',np.median([z['raw_residual_power']/1.12e-6 for z in out]))
