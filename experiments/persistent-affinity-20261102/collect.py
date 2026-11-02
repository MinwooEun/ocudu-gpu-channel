import pathlib,json,shutil,hashlib
b=pathlib.Path('/workspace/gpuch/persistent-affinity-20261102');root=pathlib.Path('/workspace/gpuch/one-ue-realtime-20261030/u1');e=b/'evidence';e.mkdir(exist_ok=True)
for p in sorted(root.glob('original-persistent-1102-*')):
 d=e/p.name;d.mkdir(exist_ok=True)
 for name in ['launch.json','result.json','rate-analysis.json','rf-analysis.json','affinity-audit.json','affinity-observer.log']:
  f=p/name
  if f.exists():shutil.copy2(f,d/(name[:-4]+'.txt' if name.endswith('.log') else name))
 for name in ['logs/gnb-affinity.json','logs/gnb0-dryrun.log','configs/gnb0.yaml']:
  f=p/'runtime'/name
  if f.exists():shutil.copy2(f,d/(f.name[:-4]+'.txt' if f.name.endswith('.log') else f.name))
 (d/'raw-index.json').write_text(json.dumps(dict(remote_case=str(p),files=[dict(file=str(f.relative_to(p)),size=f.stat().st_size) for f in (p/'raw').rglob('*') if f.is_file()]),indent=2)+'\n')
launcher=pathlib.Path('/workspace/gpuch/profile-20261028/ranb/use_cases/ran_benchmark/run-single-cell-policy.sh');helper=launcher.with_name('configure_gnb_affinity.py')
(e/'deployment.json').write_text(json.dumps(dict(launcher=str(launcher),launcher_sha256=hashlib.sha256(launcher.read_bytes()).hexdigest(),original_sha256=hashlib.sha256((b/'launcher.original.sh').read_bytes()).hexdigest(),helper=str(helper),helper_sha256=hashlib.sha256(helper.read_bytes()).hexdigest(),default_enabled='Spark CUDA benchmark, SINGLE_CELL_GNB_SEPARATE_RADIO defaults to 1',control_override='SINGLE_CELL_GNB_SEPARATE_RADIO=0',original_binary_unchanged=True),indent=2)+'\n')
