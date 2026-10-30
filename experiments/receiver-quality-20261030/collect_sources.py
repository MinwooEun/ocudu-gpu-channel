import pathlib,json,hashlib,subprocess as sp
b=pathlib.Path('/workspace/gpuch/receiver-quality-20261030');s=pathlib.Path('/workspace/ocudu-spark-ranb/src/srsRAN_4G-local');out={}
for name,lo,hi in [('lib/src/phy/ch_estimation/dmrs_sch.c',815,882),('lib/src/phy/phch/pdsch_nr.c',530,546),('lib/src/phy/mimo/precoding.c',284,305),('srsue/src/phy/nr/sf_worker.cc',85,130),('lib/src/phy/fec/ldpc/ldpc_decoder.c',65,104)]:
 f=s/name;lines=f.read_text().splitlines();out[name]=dict(sha256=hashlib.sha256(f.read_bytes()).hexdigest(),lines=[dict(line=i,text=lines[i-1]) for i in range(lo,hi+1)])
(b/'source-evidence.json').write_text(json.dumps(out,indent=2)+'\n')
predict=json.loads((b/'noiseless-estimator-prediction.json').read_text())['rows'];import csv
actual=list(csv.DictReader((b/'original-vector-results.csv').open()));assert len(actual)==len(predict)==400
r=dict(linked_original_archive='/workspace/ocudu-spark-ranb/builds/srsran4g-zmq-local/lib/src/phy/libsrsran_phy.a',rows=len(actual),maximum_difference_from_float64_db=max(abs(float(x['snr_db'])-y['noise_free_snr_db']) for x,y in zip(actual,predict)),input_noise_power=0,artifacts={str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in [b/'vector-probe',b/'vector_probe.c',b/'noiseless-responses.cf32',pathlib.Path('/workspace/ocudu-spark-ranb/builds/srsran4g-zmq-local/lib/src/phy/libsrsran_phy.a')]})
(b/'original-vector-validation.json').write_text(json.dumps(r,indent=2)+'\n')
