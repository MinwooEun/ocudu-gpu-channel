"""Apply the original UE pilot-residual SNR formula to noise-free frozen H(f)."""
import json,pathlib,numpy as np
f=pathlib.Path('/workspace/ocudu-spark-ranb/results/single-cell-scheduler-benchmark/tagged-profile1028-u1-20261028T075717Z-g160/bundle/channel/channel-trace.jsonl')
rows=[];responses=[]
for line in f.open():
 r=json.loads(line);k=r.get('k')
 if k is None:continue
 taps=json.loads(next(m for m in r['messages'] if json.loads(m)['link_id']=='gnb0>ue0:sionna_rt'))['lanes'][0]['taps'];idx=np.arange(8);freq=np.arange(-636,-636+95*12,2)/1536;H=np.zeros(len(freq),dtype=complex)
 for t in taps:
  tau=t['delay_samples'];n=int(np.floor(tau));frac=tau-n;c=np.sinc(idx-3-frac)*(.54-.46*np.cos(2*np.pi*idx/7));c/=sum(c)
  H+=(10**(t['gain_db']/20)*np.exp(1j*t['phase_rad']))*(np.exp(-2j*np.pi*freq[:,None]*(n-3+idx)[None,:])@c)
 responses.append(H.astype(np.complex64));sync=-np.angle(np.vdot(H[:-1],H[1:]))/(2*np.pi);comp=H*np.exp(2j*np.pi*sync*np.arange(len(H)));rsrp=abs(np.mean(comp))**2;epre=np.mean(abs(comp)**2);snr=10*np.log10(rsrp/(epre-rsrp));rows.append(dict(k=k,noise_free_snr_db=float(snr),estimated_delay_samples=float(sync*1536/2),noise_fraction=float((epre-rsrp)/epre)))
for r in rows:
 if r['k'] in [0,100,200,230,270,290,291,292,293,294,295,296,297,298,299,300,310,320]:print(r)
pathlib.Path('/workspace/gpuch/receiver-quality-20261030/noiseless-estimator-prediction.json').write_text(json.dumps(dict(method='Original pilot residual formula applied to exact frozen FIR frequency response, 95 PRBs starting PRB0, DMRS type1, FFT1536. No injected noise. Omits UE preprocessing and real pilot extraction.',rows=rows),indent=2))

np.asarray(responses,dtype=np.complex64).tofile("/workspace/gpuch/receiver-quality-20261030/noiseless-responses.cf32")
