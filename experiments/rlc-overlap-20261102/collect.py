import pathlib,re,json,hashlib,shutil
b=pathlib.Path('/workspace/gpuch/rlc-overlap-20261102');root=pathlib.Path('/workspace/gpuch/multi-ue-affinity-20261102/u16/original-multi-u16-on-r1');source=pathlib.Path('/workspace/ocudu-spark-ranb/src/srsRAN_4G-local/lib/src/rlc/rlc_am_nr.cc');lines=(root/'runtime/logs/srsue-ue12-internal.log').read_text().splitlines();packets=[]
for i,line in enumerate(lines):
 m=re.search(r'Rx data PDU SN=617 \((\d+) B\)',line)
 if not m:continue
 h=bytes.fromhex(lines[i+1].split(': ',1)[1]);si=(h[0]>>4)&3;so=int.from_bytes(h[3:5],'big') if si in [2,3] else 0;length=int(m[1])-(5 if si in [2,3] else 3)
 packets.append(dict(time=line[:26],sn=617,so=so,length=length,end_inclusive=so+length-1,si=si,header_hex=h[:5 if si in [2,3] else 3].hex()))
results=json.loads((b/'results.json').read_text());assert results[0]['returncode']==0 and results[1]['returncode']==-6;assert 'SO_start=765 > SO_end=683. NACK_SN=617' in results[1]['output']
small=next(x for x in packets if x['so']==684 and x['length']==12);large=next(x for x in packets if x['so']==656 and x['length']==109);assert small['time']<large['time']
src=source.read_text().splitlines();e=b/'evidence';e.mkdir(exist_ok=True)
for name in ['results.json','build.json','inner-first.txt','outer-first.txt']:shutil.copy2(b/name,e/name)
(e/'live-packet-order.json').write_text(json.dumps(dict(packets=packets,trigger=[small,large],payload_note='Only captured headers and lengths are required for this range-management reproduction. Replay payloads are zero-filled, not bit-exact IQ replay.'),indent=2)+'\n')
(e/'source.json').write_text(json.dumps(dict(file=str(source),sha256=hashlib.sha256(source.read_bytes()).hexdigest(),excerpts=[dict(line=lo,text='\n'.join(src[lo-1:hi])) for lo,hi in [(1474,1497),(1748,1783),(1928,1968)]]),indent=2)+'\n')
(e/'live-final-segments.txt').write_text('\n'.join(x for x in lines if '2026-11-02T07:09:25.1620' in x and ('Segment:' in x or 'SO_start=' in x))+'\n')
