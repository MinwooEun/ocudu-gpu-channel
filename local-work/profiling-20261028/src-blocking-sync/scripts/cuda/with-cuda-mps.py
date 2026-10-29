#!/usr/bin/env python3
"""Run a command with an isolated CUDA MPS server on the qualified GPU 0.

The server, clients, and cleanup are recorded under the native results root.
Existing MPS servers and GPU compute modes are not changed.

Why a measurement needs this: without MPS the broker, the Sionna bridge and the
CUDA gNB each get their own GPU context and time-slice against each other, and
the run-to-run spread swamps the difference being measured. The P-core pinning
that goes with it matters for the same reason -- on this 285K the P/E core mix
moves the CPU baseline by 6-7% on its own, which is larger than anything a
paired comparison is trying to see.

Adapted from the earlier tree's scripts/native/with-cuda-mps.py; the evidence
root is the rebuild tree's, and the exit path no longer dereferences a process
that was never started.
"""
import argparse
import datetime
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile
import time


def stop_process_group(process):
    if process is None or process.poll() is not None:
        return
    os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=45)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command:
        parser.error('supply a command after --')
    if os.environ.get('CUDA_MPS_PIPE_DIRECTORY'):
        parser.error('an MPS pipe is already selected; run the command directly or leave that environment first')
    if os.environ.get('OCUDU_NATIVE_GPU_DEVICE', '0') != '0':
        parser.error('this qualified MPS wrapper supports physical GPU 0')
    control = shutil.which('nvidia-cuda-mps-control')
    if control is None:
        parser.error('nvidia-cuda-mps-control is unavailable')
    root = Path(os.environ['OCUDU_NATIVE_ROOT']).resolve(strict=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    out = root / 'results/cuda-rebuild' / ('mps-' + stamp)
    out.mkdir(parents=True)
    pipe = Path(tempfile.mkdtemp(prefix='ocudu-mps-'))
    env = dict(os.environ, CUDA_VISIBLE_DEVICES='0', CUDA_MPS_PIPE_DIRECTORY=str(pipe),
               CUDA_MPS_LOG_DIRECTORY=str(out), OCUDU_NATIVE_MPS_EVIDENCE=str(out))
    metadata = dict(command=command, physical_gpu=0, pipe=str(pipe), evidence=str(out),
                    control_binary=control, started_unix_seconds=time.time())
    (out / 'launch.json').write_text(json.dumps(metadata, indent=2) + '\n')
    process = None
    daemon_started = False

    def query(text):
        result = subprocess.run([control], input=text + '\n', text=True, env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=10)
        if result.returncode:
            raise RuntimeError('MPS control failed: ' + result.stdout.strip())
        return result.stdout

    def interrupted(signum, _frame):
        raise KeyboardInterrupt('signal ' + str(signum))

    previous = {s: signal.signal(s, interrupted) for s in (signal.SIGTERM, signal.SIGHUP)}
    try:
        subprocess.run([control, '-d'], env=env, check=True, timeout=10)
        daemon_started = True
        time.sleep(0.5)
        (out / 'startup.txt').write_text(query('start_server -uid ' + str(os.getuid())))
        for _ in range(20):
            servers = query('get_server_list')
            if re.search(r'\b[1-9][0-9]*\b', servers):
                break
            time.sleep(0.5)
        else:
            raise RuntimeError('MPS server did not start; inspect ' + str(out))
        (out / 'servers.txt').write_text(servers)
        print('cuda_mps_evidence=' + str(out), flush=True)
        process = subprocess.Popen(command, env=env, start_new_session=True)
        with (out / 'clients.jsonl').open('x') as stream:
            while process.poll() is None:
                stream.write(json.dumps(dict(unix_seconds=time.time(), clients=query('ps'))) + '\n')
                stream.flush()
                time.sleep(2)
        metadata['command_exit_code'] = process.returncode
    finally:
        stop_process_group(process)
        if daemon_started:
            (out / 'shutdown.txt').write_text(query('quit'))
            metadata['daemon_quit'] = True
        metadata['finished_unix_seconds'] = time.time()
        (out / 'result.json').write_text(json.dumps(metadata, indent=2) + '\n')
        shutil.rmtree(pipe, ignore_errors=True)
        for signum, handler in previous.items():
            signal.signal(signum, handler)
    # A failure before the command launched must surface as that failure, not
    # as an AttributeError on a process that was never created.
    return 0 if process is None else process.returncode


if __name__ == '__main__':
    raise SystemExit(main())
