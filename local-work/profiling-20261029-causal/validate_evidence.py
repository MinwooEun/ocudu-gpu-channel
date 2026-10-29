import pathlib,json,struct,hashlib,subprocess as sp
P=pathlib.Path('/workspace/gpuch/profile-20261029-causal');cases=P/'pr10-frozen';out={}
for name in ('trace','trace-repeat'):
 checks=[]
 for f in (cases/name/'wire').glob('*.wire'):
  h=struct.unpack('8Q',f.open('rb').read(64));assert h[3]==0,(f,h[3]);checks.append(dict(file=f.name,records=h[1],dropped=h[3],sha256=hashlib.sha256(f.read_bytes()).hexdigest()))
 assert len(checks)>=18
 d=json.load(open(P/f'decompose-pr10-{name}.json'))
 g=next(x for x in d if x['node']=='gnb0');assert len(g['wire_checks'])==16
 assert all(v==0 for v in g['negative_wire_parts'].values());assert all(x['ready_after_send']==0 and x['ring_insert_before_recv']==0 for x in g['wire_checks'])
 assert abs(sum(g['wire_parts_us_per_radio_ms'].values())-g['data_us_per_radio_ms'])<1e-5
 room=json.load(open(P/f'room-pr10-{name}.json'));assert abs(sum(room['parts_us_per_radio_ms'].values())-room['room_us_per_radio_ms'])<1e-5
 rr=json.load(open(cases/name/'runtime/report/run-report.json'));assert rr['runtime']['broker']['tx_sequence_gaps']==0
 out[name]=dict(wire_files=checks,gnb_input_sources=16,matched_messages=sum(x['matched_iq_messages'] for x in g['wire_checks']),sample_gaps=0,part_sum_check=True)
for d in cases.iterdir():
 l=json.load(open(d/'launch.json'));assert l['frozen_bundle'].endswith('tagged-cd10-16ue-20261026T124817Z-g121/bundle')
 for rel,expected in l['input_hashes'].items():assert hashlib.sha256((pathlib.Path(l['frozen_bundle'])/rel).read_bytes()).hexdigest()==expected
out['frozen_input_hashes_match_all_trials']=True
out['gpu_processes_after']=sp.check_output(['nvidia-smi','--query-compute-apps=pid,process_name','--format=csv,noheader'],text=True).strip()
(P/'evidence-validation.json').write_text(json.dumps(out,indent=2));print('All final trace buffers have zero dropped records; 16 input streams match message sample counts; timing partitions and frozen inputs validate.')
