#!/usr/bin/env python3
"""Native link order through the shared artifact and renderer consumers."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('choano_build', ROOT / 'scripts/build.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)
real_output = subprocess.check_output

class RendererTest(unittest.TestCase):
    def setUp(self):
        scratch = ROOT / 'work/build-test'
        subprocess.run(['git', 'check-ignore', str(scratch)], check=True, stdout=subprocess.DEVNULL)
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'include').mkdir()
        self.meta = dict(schema=1, artifact='renderer-raylib', platform='linux-x86_64-gnu',
            archives=['second.a', 'first.a'], link_flags=['-lm', '-pthread'], compile_flags=[], defines=[],
            include_directories=['include'], resources=dict(font='font.ttf', font_license='font.txt'))
        for name in [*self.meta['archives'], 'font.ttf', 'font.txt']:
            (self.root / name).write_bytes(name.encode())
        self.descriptor = self.root / 'artifact.tsv'
        self.save()
        # Only the provider request is simulated; the helpers are the locked packages' own.
        def output(args, **options):
            if 'artifact' in args:
                return str(self.descriptor)
            return real_output(args, **options)
        patcher = patch.object(subprocess, 'check_output', side_effect=output)
        patcher.start()
        self.addCleanup(patcher.stop)

    def save(self):
        (self.root / 'renderer.json').write_text(json.dumps(self.meta))
        rows = dict(schema='1', package='kryon', artifact='renderer-raylib', platform='linux-x86_64-gnu', key='a' * 64)
        for name in ['renderer.json', *self.meta['archives'], 'font.ttf', 'font.txt']:
            rows[name] = hashlib.sha256((self.root / name).read_bytes()).hexdigest()
        self.descriptor.write_text(''.join(f'{k}\t{v}\n' for k, v in rows.items()))

    def test_order_and_existing_libraries(self):
        resolved = self.root.resolve()
        with patch.object(build, 'run') as run, patch.dict(os.environ, LDLIBS="'-Lwith spaces' -lcustom"):
            build.native()
        self.assertEqual(shlex.split(run.call_args.kwargs['env']['LDLIBS']),
            [str(resolved / 'second.a'), str(resolved / 'first.a'), '-lm', '-pthread', '-Lwith spaces', '-lcustom'])

    def test_corrupt_archive(self):
        (self.root / 'first.a').write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError, 'digest mismatch'):
            build.renderer_links()

    def test_wrong_platform(self):
        self.meta['platform'] = 'windows-x86_64-mingw'
        self.save()
        with self.assertRaisesRegex(ValueError, 'does not match'):
            build.renderer_links()

    def test_corrupt_metadata(self):
        (self.root / 'renderer.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'digest mismatch'):
            build.renderer_links()

if __name__ == '__main__': unittest.main()
