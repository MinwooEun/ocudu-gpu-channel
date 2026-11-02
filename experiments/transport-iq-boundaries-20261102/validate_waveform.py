import pathlib,subprocess as sp,time,json,sys
import zmq
W=pathlib.Path(sys.argv[1]);ctx=zmq.Context();out=[]
for batch in [23040,61440]:
 peers=[];sockets=[];files=[]
 try:
  for name,cmd in [('old',[W/'legacy-source','--endpoint','tcp://127.0.0.1:50000','--batch-samples',str(batch)]),('new',[W/'radio-peer','check','50002','1',str(batch),W/'never-epoch',W/'validate-ready','5'])]:
   f=(W/('validate-'+name+'.log')).open('wb');files.append(f);peers.append(sp.Popen(list(map(str,cmd)),stdout=f,stderr=f))
  for port in [50000,50002]:
   s=ctx.socket(zmq.REQ);s.setsockopt(zmq.RCVTIMEO,5000);s.setsockopt(zmq.LINGER,0);s.connect('tcp://127.0.0.1:'+str(port));sockets.append(s)
  time.sleep(.1);compared=0
  for _ in range(24):
   data=[]
   for s in sockets:s.send(b'\0');data.append(s.recv())
   assert data[0]==data[1],('wire mismatch',batch,compared)
   assert len(data[0])==batch*8;compared+=len(data[0])
  out.append(dict(batch_samples=batch,messages=24,compared_bytes=compared,wire_bytes_identical=True))
 finally:
  for s in sockets:s.close()
  for p in peers:
   p.terminate();p.wait(timeout=5)
  for f in files:f.close()
ctx.term();print(json.dumps(out,indent=2));(W/'waveform-validation.json').write_text(json.dumps(out,indent=2))
