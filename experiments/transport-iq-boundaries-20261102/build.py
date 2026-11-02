"""Rebuild the measurement harnesses against retained live-tested backend archives."""
import pathlib,subprocess as sp,sys,shutil,hashlib,json
S=pathlib.Path(__file__).resolve().parent;W=pathlib.Path(sys.argv[1]);W.mkdir(parents=True,exist_ok=True);spark=str(W).startswith('/workspace');C=pathlib.Path('/workspace/gpuch/profile-20261028/src' if spark else '/home/minwoo/ocudu-work/rtx-scaling-20261102/channel-src');B=pathlib.Path('/workspace/gpuch/profile-20261028/build' if spark else '/home/minwoo/ocudu-work/rtx-scaling-20261102/channel-build');original=pathlib.Path('/workspace/gpuch/one-ue-realtime-20261030/room-build/libocudu_gpu_channel_lib.a') if spark else B/'libocudu_gpu_channel_lib.a';broker_source=pathlib.Path('/workspace/gpuch/one-ue-realtime-20261030/broker-room.cpp') if spark else C/'src/broker.cpp';cuda=pathlib.Path('/usr/local/cuda');commands=[]
def run(cmd):commands.append(list(map(str,cmd)));sp.run(list(map(str,cmd)),check=True)
for helper in S.glob('*.py'):
 if helper.resolve()!=(W/helper.name).resolve():shutil.copy2(helper,W/helper.name)
run(['c++','-std=c++20','-O3','-pthread',S/'radio_peer.cpp','-lzmq','-o',W/'radio-peer'])
run(['c++','-std=c++20','-O3','-pthread','-I'+str(C/'include'),S/'iq_capacity.cpp',original,'-L'+str(cuda/'lib64'),'-Wl,-rpath,'+str(cuda/'lib64'),'-lcudart','-lzmq','-ldl','-o',W/'iq-capacity-ready'])
run(['c++','-std=c++20','-O3','-pthread','-I'+str(C/'include'),S/'iq_capacity.initial-window.cpp',original,'-L'+str(cuda/'lib64'),'-Wl,-rpath,'+str(cuda/'lib64'),'-lcudart','-lzmq','-ldl','-o',W/'iq-capacity'])
run([sys.executable,S/'add_probe.py',broker_source,W/'broker-probe.cpp'])
run(['c++','-O3','-DNDEBUG','-std=c++20','-DOCUDU_GPU_CHANNEL_HAS_CUDA=1','-DOCUDU_GPU_CHANNEL_KERNEL_SM='+('121' if spark else '120'),'-I'+str(cuda/'include'),'-I'+str(C/'include'),'-I'+str(C/'src'),'-c',W/'broker-probe.cpp','-o',W/'broker.cpp.o'])
shutil.copy2(original,W/'libocudu_gpu_channel_lib.a');run(['ar','r',W/'libocudu_gpu_channel_lib.a',W/'broker.cpp.o']);run(['c++',B/'CMakeFiles/ocudu-gpu-channel.dir/apps/ocudu_gpu_channel.cpp.o',W/'libocudu_gpu_channel_lib.a','-L'+str(cuda/'lib64'),'-Wl,-rpath,'+str(cuda/'lib64'),'-lcudart','-lzmq','-ldl','-pthread','-o',W/'ocudu-gpu-channel'])
(W/'build.json').write_text(json.dumps(dict(commands=commands,backend_archive_sha256=hashlib.sha256(original.read_bytes()).hexdigest()),indent=2))
