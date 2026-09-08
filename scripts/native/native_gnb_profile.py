#!/usr/bin/env python3
"""Resolve and audit the selected native gNB without changing CPU defaults."""
from __future__ import annotations
import argparse
import ctypes
import hashlib
import json
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LOCK = REPO / 'scripts/native/native-workspace.lock.json'


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args])


def verify_source(root, repo, source, apply_patch=False):
    path = root / source['path']
    if git(path, 'rev-parse', 'HEAD').decode().strip() != source['commit']:
        raise ValueError('gNB source revision mismatch')
    patch = source.get('patch')
    if not patch:
        if git(path, 'status', '--porcelain'):
            raise ValueError(f"Git checkout is dirty: {source['name']}")
        return
    patch_path = repo / patch['path']
    expected = patch_path.read_bytes()
    if hashlib.sha256(expected).hexdigest() != patch['sha256']:
        raise ValueError('locked source patch checksum mismatch')
    if git(path, 'ls-files', '--others', '--exclude-standard'):
        raise ValueError('gNB source contains untracked files')
    actual = git(path, 'diff', '--binary', 'HEAD')
    if not actual and apply_patch:
        subprocess.run(['git', '-C', str(path), 'apply', '--check', str(patch_path)], check=True)
        subprocess.run(['git', '-C', str(path), 'apply', str(patch_path)], check=True)
        actual = git(path, 'diff', '--binary', 'HEAD')
    if actual != expected:
        raise ValueError('gNB source differs from the locked patch')


def resolve_profile(root, profile, hardware=False, check_build=True, apply_patch=False):
    lock = json.loads(LOCK.read_text())
    if profile not in lock['gnb_profiles']:
        raise ValueError('OCUDU_NATIVE_GNB_PROFILE must be cpu or cuda')
    selected = lock['gnb_profiles'][profile]
    source = next(s for s in lock['git_sources'] if s['name'] == selected['source'])
    build = lock['build_profiles'][selected['build']]
    verify_source(root, REPO, source, apply_patch)
    build_path = root / build['build_dir']
    binary = build_path / 'apps/gnb/gnb'
    data = dict(profile=profile, source=str(root / source['path']), commit=source['commit'],
                build=str(build_path), binary=str(binary), patch=source.get('patch'))
    if check_build:
        cache = {}
        for line in (build_path / 'CMakeCache.txt').read_text().splitlines():
            if '=' in line and ':' in line and not line.startswith(('//', '#')):
                key, value = line.split('=', 1)
                cache[key.split(':', 1)[0]] = value
        if cache.get('ENABLE_ZEROMQ') != 'ON':
            raise ValueError('selected gNB lacks ZMQ')
        if Path(cache.get('CMAKE_HOME_DIRECTORY', '')).resolve() != (root / source['path']).resolve():
            raise ValueError('gNB build/source path mismatch')
        version_text = subprocess.check_output([str(binary), '--version'], text=True)
        if not re.search(r'OCUDU 5G gNB version .*\(' + source['commit'][:7] + r'\)', version_text):
            raise ValueError('gNB binary revision mismatch')
        data['binary_sha256'] = hashlib.sha256(binary.read_bytes()).hexdigest()
        if profile == 'cuda':
            if cache.get('ENABLE_CUDA') != 'ON' or cache.get('CMAKE_CUDA_ARCHITECTURES') != '120':
                raise ValueError('gNB CUDA build does not match locked architecture 120')
            help_text = subprocess.check_output([str(binary), '--help'], text=True)
            if 'GPU acceleration:' not in help_text:
                raise ValueError('selected gNB binary lacks CUDA support')
            data['cuda_architectures'] = cache['CMAKE_CUDA_ARCHITECTURES']
            if hardware:
                data['cuda_compiler_version'] = subprocess.check_output([cache['CMAKE_CUDA_COMPILER'], '--version'], text=True).strip()
                data['gpu_driver_inventory'] = subprocess.check_output(['nvidia-smi', '--query-gpu=index,uuid,name,driver_version', '--format=csv,noheader'], text=True).strip()
                runtime = ctypes.CDLL('libcudart.so.12')
                version = ctypes.c_int()
                if runtime.cudaRuntimeGetVersion(ctypes.byref(version)) != 0:
                    raise ValueError('CUDA runtime version query failed')
                data['cuda_runtime_version'] = version.value
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--profile', choices=('cpu', 'cuda'), default='cpu')
    parser.add_argument('--fields', action='store_true')
    parser.add_argument('--hardware', action='store_true')
    parser.add_argument('--prepare-source', action='store_true')
    args = parser.parse_args()
    data = resolve_profile(args.root, args.profile, args.hardware, not args.prepare_source, args.prepare_source)
    print('\t'.join(data[k] for k in ('binary', 'source', 'build', 'commit')) if args.fields else json.dumps(data, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        raise SystemExit(f'gNB profile validation failed: {error}')
