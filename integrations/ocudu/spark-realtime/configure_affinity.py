"""Configure disjoint native gNB radio/main masks before thread creation."""
import argparse,json,pathlib,yaml

def cpus(text):
 result=set()
 for item in text.split(','):
  bounds=item.strip().split('-');lo=int(bounds[0]);hi=int(bounds[-1])
  if len(bounds)>2 or lo<0 or hi<lo:raise ValueError('invalid CPU range: '+item)
  result.update(range(lo,hi+1))
 return result

def configure(config,allowed,radio_override='',main_override=''):
 allocation=cpus(allowed)
 if len(allocation)<2:raise ValueError('radio separation requires at least two allocated gNB CPUs')
 radio=cpus(radio_override) if radio_override else {sorted(allocation)[1]}
 main=cpus(main_override) if main_override else allocation-radio
 if len(radio)!=1 or not main or radio&main or not (radio|main)<=allocation:
  raise ValueError('radio/main masks must be nonempty, disjoint and within the gNB allocation; radio needs one CPU')
 expert=config.setdefault('expert_execution',{})
 # Preserve the pre-separation auto-sized pool; narrowing its mask must not
 # silently reduce the original number of workers (five for eight CPUs).
 expert.setdefault('threads',{}).setdefault('main_pool',{}).setdefault('nof_threads',min(5,len(allocation)-3))
 affinities=expert.setdefault('affinities',{});affinities.update(main_pool_cpus=','.join(map(str,sorted(main))),main_pool_pinning='mask')
 cells=expert.setdefault('cell_affinities',[{}])
 if len(cells)!=1:raise ValueError('this single-cell launcher requires exactly one RU affinity entry')
 cells[0].update(ru_cpus=','.join(map(str,sorted(radio))),ru_pinning='mask')
 return dict(allowed_cpus=sorted(allocation),radio_cpus=sorted(radio),main_cpus=sorted(main),applied='native configuration before worker creation')

if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('--config',type=pathlib.Path,required=True);ap.add_argument('--allowed',required=True);ap.add_argument('--radio',default='');ap.add_argument('--main',default='');ap.add_argument('--report',type=pathlib.Path,required=True);a=ap.parse_args()
 config=yaml.safe_load(a.config.read_text());report=configure(config,a.allowed,a.radio,a.main)
 a.config.write_text(yaml.safe_dump(config,sort_keys=False));a.report.write_text(json.dumps(report,indent=2)+'\n')
