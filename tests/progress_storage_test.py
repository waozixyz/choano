#!/usr/bin/env python3
"""Production Choano earned saves in an isolated native namespace."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
subprocess.run(['git', 'check-ignore', 'work/progress-storage'], check=True)
(ROOT / 'work').mkdir(exist_ok=True)
env = dict(os.environ, ZIRAN_PAR_THREADS='1')
subprocess.run(['ziran', 'build', '--project', '--locked', '--target=c', '--exe',
                '--entry', 'progress_storage_test:main', '-o', 'build/progress-storage-test',
                'tests/progress_storage_test.zi'], check=True, env=env)
with tempfile.TemporaryDirectory(prefix='progress-storage-', dir=ROOT / 'work') as data:
    env['CHOANO_DATA'] = data
    subprocess.run(['./build/progress-storage-test/progress_storage_test'], check=True, env=env)
    documents = list(Path(data).glob('choano.earned.*.v1'))
    assert len(documents) == 2
    import json
    for document in documents:
        saved = json.loads(document.read_text())
        assert saved['pending'] is False
        assert set(saved['earned']) == {'game', 'unlocked', 'completed', 'updated_at'}
