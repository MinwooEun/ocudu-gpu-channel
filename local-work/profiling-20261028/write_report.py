from pathlib import Path
import json,statistics,csv
P=Path(__file__).parent
def read(name,default=None):
 f=P/name
 return json.loads(f.read_text()) if f.exists() else default
live=read('live-summary.json',[]);oai=read('oai-summary.json',[]);audit=read('audit-5090.json')
out=[]
def say(s=''):out.append(s)
say('Spark CUDA gNB / GPU channel timing investigation — 2026-10-28')
say('Evidence and scripts: this directory. Source base: RAN_benchmark 364391bccd3abd5fb73946e50c3a4c95ce649551; opt-in instrumentation.patch.')
say()
say('RTX 5090 historical audit')
say(f"All {len(audit['checksums'])} saved-file SHA256 checks match. The 2026-10-13 N64 result is a synthetic, sequential, channel-only benchmark: no real gNB/UE processes and no ZMQ.")
r=audit['results'][-1]
for key in ['model_mix_latency','gpu_process_us','node:gnb0:call_us','node:gnb0:host_prep_us','node:gnb0:h2d_us','node:gnb0:kernel_us']:
 say(f"{key}: median run-level p50 = {statistics.median(x[key]['p50_us'] for x in r['runs']):.3f} us; median run-level p99 = {statistics.median(x[key]['p99_us'] for x in r['runs']):.3f} us.")
say('One block represents 1 ms. Each receiver completed about 1,278–1,282 calls in the requested 10 s sequential benchmark, approximately 128 blocks/s. This describes that benchmark, not the concurrent broker capacity.')
say('The aggregate median is dominated by 64 light UE-destination calls. The gNB destination combines 64 incoming streams. gpu_process_us excludes CPU preparation. A claim that these records prove 64 live UEs at real time is unsupported; the records themselves are internally consistent.')
say('At 64 inputs, one block contains 64 * 23,040 * 8 = 11,796,480 input bytes. Host preparation largely packs these IQ buffers; it is channel-emulator work, not the gNB MAC scheduler.')
say()
say('Timing definitions and normalization')
say('Channel wall intervals are entry/packing, model/control, receiver preparation, CUDA submission, stream-completion wait, and output/recording. Their sum is the channel call. The broker process interval additionally includes the profiling callback and CSV recording overhead.')
say('CUDA H2D/kernel/D2H event intervals overlap host submission and completion waiting. Do not add them to host wall intervals. The kernel event interval spans multiple kernels and their gaps/competition; it is not a single pure arithmetic kernel.')
say('Every reported mean normalized to one radio millisecond is sum(elapsed_us) / (sum(samples) / sample_rate_hz * 1000). Receiver calls can process fragments; a function call is not necessarily a radio slot.')
say('CPU thread time can include active CUDA completion waiting and polling. It is not equal to useful preparation time. room_us is output headroom waiting; data_us waits for common input IQ. Those waits can arise from radio compute, transport, or broker-thread scheduling.')
say()
say('Live 20 MHz UE sweep')
for r in sorted(live,key=lambda r:r['label']):
 say(r['label'])
 for run in r['runs']:
  say(f"  {run['run']}: radio/wall ratio={run['runtime']['real_time_ratio']}; valid radio segments={run.get('segments_valid')}; scheduler decision={run.get('decision_latency')}; runtime={run['runtime']['broker']}")
 for kind in ['broker','channel']:
  rows=[q for q in r['receivers'] if q.get('node')=='gnb0' and q.get('kind')==kind and q.get('window_complete')]
  if not rows:continue
  radio_ms=sum(q['radio_samples'] for q in rows)/23040000*1000
  say(f"  gNB receiver {kind}: calls/radio_ms={sum(q['calls'] for q in rows)/radio_ms:.4f}")
  for k in rows[0]['metrics']:
   val=sum(q['calls']*q['metrics'][k]['mean'] for q in rows)/radio_ms
   say(f"    {k}: {val:.3f} us per radio ms")
say('The many-recorder perf run at 16 UEs timed out in replay and is retained as failed diagnostic evidence. The trace-only repeat completes both windows. The tracing-off reference isolates measurement overhead; fairness/traffic/health verdicts remain separate from sample progress.')
say()
say('Live bandwidth and antenna ports: one OAI UE, 1 Mb/s DL')
for r in sorted(oai,key=lambda r:r['label']):
 say(f"{r['label']}: ratio={r['rank'].get('realtime_factor')}; health={r['rank'].get('health')}")
 for q in r['receivers']:
  if q['kind']!='broker':continue
  factor=q.get('calls_per_radio_ms')
  if factor is None:continue
  say(f"  {q['node']}: calls/radio_ms={factor:.4f}; "+', '.join(f"{k}={v['mean']*factor:.2f} us/radio_ms" for k,v in q['metrics'].items()))
say('Ports are antenna ports, not the number of spatial layers: the OAI gate is capped at DL rank 2. The 100 MHz four-UE-antenna case fails its PUSCH health bound.')
say()
say('Broker boundary and diagnostic controls')
groups=['boundary','matched-boundary','diagnostic-io4','diagnostic-live-budget','diagnostic-live-budget-blocking','multi-broker']
flat=[]
for group in groups:
 for f in sorted((P/group).glob('*/result.json')):
  r=json.loads(f.read_text());ratios=[x for x in r['ratios'] if x is not None]
  label=group+'/'+f.parent.name
  say(f"{label}: minimum/mean/maximum received sample-rate ratio={min(ratios):.6f}/{statistics.mean(ratios):.6f}/{max(ratios):.6f}; broker return code={r.get('broker_rc')}")
  flat.append(dict(group=group,label=f.parent.name,ratio_min=min(ratios),ratio_mean=statistics.mean(ratios),ratio_max=max(ratios),trace=r.get('trace'),ues=r.get('ues_per_cell'),cells=r.get('cells'),bandwidth_mhz=r.get('bandwidth_mhz'),gnb_antennas=r.get('gnb_antennas'),ue_antennas=r.get('ue_antennas'),broker_rc=r.get('broker_rc')))
say('Main boundary: fixed 8-tap channel, two ZMQ I/O threads, blocking broker waits, broker cores 5–14 and synthetic radios on big cores 15–19. Each point has one tracing-off reference and one detailed-trace run of 12 wall seconds; these are paired observations, not statistical confidence intervals.')
say('Bandwidth maps to the existing radio rates (20/50/100 MHz -> 23.04/61.44/122.88 MS/s); sample rate is not an independent sweep axis. Batch durations are 1/1/0.5 ms in the main synthetic grid.')
say('Matched-topology controls preserve the live OAI model, configured batch and queues, changing only endpoint addresses. Synthetic source/request chunking is not the full real-radio execution pattern. These controls preserve a configured 1 ms batch at 100 MHz; do not silently compare them with the 0.5 ms generic grid as if only the model changed.')
say('The live-budget diagnostic uses broker cores 15–16 and radio placement corresponding to the live recipe; gNB proxy uses 5–12 and UE proxies use 13,14,17–19. Report minimum as well as mean progress because independent synthetic sources/sinks do not share the real stack feedback loop.')
say('The UE allocation is three big cores (17–19) plus two little cores (13–14), not five big cores. The gNB allocation 5–12 also spans CPU classes. The main synthetic grid instead gives endpoint proxies five big cores (15–19).')
say('Multi-broker controls have independent CUDA contexts and two I/O threads per process. A single broker with multiple cells and multiple brokers also differ in total I/O workers; their difference does not isolate CUDA context switching alone.')
say()
say('CPU and GPU profiles')
for filename in ['thread-runtime-steady-summary.json','two-cell-summary.json','two-cell-control-summary.json']:
 val=read(filename)
 if val:say(filename+': '+json.dumps(val))
nsys=read('nsys-summary.json',[])
if nsys:
 for r in nsys:
  say(f"Nsight {r['report']}: kernels={r.get('kernel_count')}; kernel union fraction over activity span={r.get('kernel_union_fraction')}; matched runtime correlations={r.get('kernel_runtime_correlation_matched')}; post-API kernel-start delay={r.get('post_api_return_to_kernel_start_us')}")
  apis=r.get('runtime_apis',{});say('  Highest summed CUDA API times: '+str(sorted(((k,v) for k,v in apis.items()),key=lambda x:x[1]['sum'],reverse=True)[:8]))
  say('  Copy activities by CUPTI kind: '+str(r.get('memcpy_by_kind')))
else:say('No usable exported Nsight timeline has been included yet. Per-call local-stream event timings and CPU profiles remain separate evidence; they do not by themselves resolve every GPU queue interval.')
say('Nsight activity fractions are time with at least one captured kernel running, not SM occupancy. Post-API start delay includes ordered dependencies on earlier kernels in the same stream; it is not exclusively inter-process GPU contention. The successful captures are synthetic broker controls, not the complete MPS live stack.')
say('Full live-stack launch under Nsight failed at unshare with Invalid argument before measurement. Live channel timings instead use receiver-local CUDA events and host timers. No complete live-stack GPU scheduling timeline is claimed.')
say('The steady-window software cpu-clock event was unsupported on this kernel. A single hardware-cycle collector captured the second policy after applied update k >= 120 (past the 10-radio-second warmup), pinned to auxiliary cores 0–4. Its PMUs are separate for CPU classes; 59 lost samples and unresolved kernel symbols limit exact CPU percentage attribution.')
say()
say('Validation and practical limits')
say('Release CUDA processing, runtime-update parity, matrix history and broker tests: 4/4 pass. The full initial suite also exposes a CPU parallel-reference parity failure reproduced in the pre-existing Spark binary. Production source and system tuning were not changed.')
say('The Sionna channel trace is computed before measurement and replayed at 10 Hz; the ray-tracing solver is not an active GPU tenant during the timed RAN window. Thus these tests do not measure concurrent online ray-tracing load.')
say('Real-time speed, deadline misses, connectivity and traffic validity are distinct. Preserve all failures; a near-1 sample ratio does not establish strict every-slot real-time qualification.')
say('Historical PR10 two-cell CUDA 0.53 is not reproduced: the instrumented run advances at about 0.868/0.890 by IQ sample progress, and the tracing-off repeat reports about 0.867/0.877 by the gate scheduler-slot metric. Do not treat the old two-cell slowdown as a universal GPU-sharing result.')
say('The direct measured result at 16 UEs is that most elapsed time is waiting around IQ exchange. The two-core broker allocation is itself a limit in its synthetic control; scheduler decision time alone is far smaller than the full cycle. A statement that MAC is the confirmed primary bottleneck would overstate these measurements.')
(P/'report.txt').write_text('\n'.join(out)+'\n')
if flat:
 with (P/'boundary-results.csv').open('w') as f:
  w=csv.DictWriter(f,fieldnames=list(flat[0]));w.writeheader();w.writerows(flat)
print('Wrote report.txt and boundary-results.csv')
