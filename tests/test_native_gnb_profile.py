"""Negative provenance tests use real Git trees and executable stand-ins."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('gnb_profile', REPO / 'scripts/native/native_gnb_profile.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'src/cpu'
        self.source.mkdir(parents=True)
        self.git('init', '-q')
        self.git('config', 'user.email', 'test@example.invalid')
        self.git('config', 'user.name', 'Test')
        (self.source / 'file').write_text('before\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'fixture')
        commit = self.git('rev-parse', 'HEAD').decode().strip()
        self.entry = dict(name='cpu', path='src/cpu', commit=commit)
        self.build = self.root / 'build/cpu'
        self.binary = self.build / 'apps/gnb/gnb'
        self.binary.parent.mkdir(parents=True)
        self.binary.write_text(f'#!/bin/sh\necho "OCUDU 5G gNB version test ({commit[:7]})"\n')
        self.binary.chmod(0o755)
        self.cache = self.build / 'CMakeCache.txt'
        self.cache.write_text(f'ENABLE_ZEROMQ:BOOL=ON\nCMAKE_HOME_DIRECTORY:INTERNAL={self.source}\n')
        self.lock = self.root / 'lock.json'
        self.lock.write_text(json.dumps(dict(gnb_profiles={'cpu':dict(source='cpu',build='cpu')}, git_sources=[self.entry,dict(name='missing-cuda',path='does-not-exist')], build_profiles={'cpu':dict(build_dir='build/cpu')})))
        self.patch_lock = patch.object(m, 'LOCK', self.lock)
        self.patch_lock.start()
        self.addCleanup(self.patch_lock.stop)

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.source), *args])

    def test_cpu_does_not_require_cuda(self):
        self.assertEqual(m.resolve_profile(self.root, 'cpu')['binary'], str(self.binary))

    def test_unknown_profile(self):
        with self.assertRaisesRegex(ValueError, 'cpu or cuda'):
            m.resolve_profile(self.root, 'typo')

    def test_wrong_binary_revision(self):
        self.binary.write_text('#!/bin/sh\necho "OCUDU 5G gNB version test (0000000)"\n')
        with self.assertRaisesRegex(ValueError, 'binary revision'):
            m.resolve_profile(self.root, 'cpu')

    def test_wrong_build_source(self):
        self.cache.write_text('ENABLE_ZEROMQ:BOOL=ON\nCMAKE_HOME_DIRECTORY:INTERNAL=/wrong\n')
        with self.assertRaisesRegex(ValueError, 'build/source'):
            m.resolve_profile(self.root, 'cpu')

    def test_patch_apply_reuse_and_tamper(self):
        target = self.source / 'file'
        target.write_text('after\n')
        diff = self.git('diff', '--binary', 'HEAD')
        patch_file = self.root / 'compat.patch'
        patch_file.write_bytes(diff)
        self.entry['patch'] = dict(path='compat.patch',sha256=hashlib.sha256(diff).hexdigest())
        target.write_text('before\n')
        with self.assertRaisesRegex(ValueError, 'locked patch'):
            m.verify_source(self.root, self.root, self.entry)
        m.verify_source(self.root, self.root, self.entry, apply_patch=True)
        m.verify_source(self.root, self.root, self.entry, apply_patch=True)
        target.write_text('unreviewed\n')
        with self.assertRaisesRegex(ValueError, 'locked patch'):
            m.verify_source(self.root, self.root, self.entry, apply_patch=True)
        patch_file.write_bytes(diff + b'\n')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            m.verify_source(self.root, self.root, self.entry)

    def test_dirty_cpu_rejected(self):
        (self.source / 'untracked').touch()
        with self.assertRaisesRegex(ValueError, 'dirty'):
            m.resolve_profile(self.root, 'cpu')


if __name__ == '__main__':
    unittest.main()
