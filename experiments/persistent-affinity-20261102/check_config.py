"""Validate rendered native affinity and unchanged radio/PHY settings."""
import copy,importlib.util,pathlib,yaml
base=pathlib.Path('/workspace/gpuch/persistent-affinity-20261102');spec=importlib.util.spec_from_file_location('affinity',str(base/'configure_gnb_affinity.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
original=yaml.safe_load(pathlib.Path('/workspace/gpuch/one-ue-realtime-20261030/u1/original-gnb-root-1031-separate-r5/runtime/configs/gnb0.yaml').read_text());config=copy.deepcopy(original);r=m.configure(config,'5-12');assert r['radio_cpus']==[6] and r['main_cpus']==[5,7,8,9,10,11,12]
assert config['expert_execution']['threads']['main_pool']['nof_threads']==5
recovered=copy.deepcopy(config);recovered.pop('expert_execution');assert recovered==original
for radio,main in [('6','5-12'),('13','5,7-12'),('6,7','5,8-12'),('6','')]:
 try:m.configure(copy.deepcopy(original),'6',radio,main)
 except ValueError:pass
 else:raise AssertionError((radio,main))
try:m.configure(copy.deepcopy(original),'5-12','6','5-12')
except ValueError:pass
else:raise AssertionError('overlap accepted')
print('native config and out-of-budget/overlap checks passed')
