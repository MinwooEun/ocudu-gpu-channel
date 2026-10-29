from pathlib import Path
P=Path('/workspace/gpuch/profile-20261028')
for rel,end in [('br15/scripts/native/run-ocudu-oai-2x2.sh','export OAI2X2_BROKER_BIN='),('ranb/use_cases/ran_benchmark/run-ocudu-scheduler-benchmark.sh','if [[ "${skip_ctest}"'),('ranb/scripts/native/run-ocudu-oai-multi-ue.sh','if [[ "${OCUDU_NATIVE_MUE_SKIP_CTEST')]:
 p=P/rel;s=p.read_text(); start=s.index('cmake -S '); stop=s.index(end,start)
 s=s[:start]+'if [[ "${OCG_PROFILE_PREBUILT:-0}" != 1 ]]; then\n'+s[start:stop]+'fi\n'+s[stop:]
 if 'scheduler-benchmark.sh' in rel:
  s=s.replace('gnb_binary="${native_root}/builds/ocudu-zmq-release/apps/gnb/gnb"','gnb_binary="${OCUDU_NATIVE_GNB_BINARY:-${native_root}/builds/ocudu-zmq-release/apps/gnb/gnb}"')
 p.write_text(s)
# Existing runner is copied, only paths/default output destination change.
src=Path('/workspace/gpuch/ranb-run.sh').read_text().replace('cd /workspace/gpuch/ranb','cd '+str(P/'ranb'))
(P/'ranb-run.sh').write_text(src)
