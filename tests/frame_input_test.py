#!/usr/bin/env python3
"""Actual Choano Frame + published Apps host, isolated from desktop/accounts."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
ENV = dict(os.environ)
for key in ('DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY', 'DBUS_SESSION_BUS_ADDRESS',
            'SESSION_MANAGER', 'DESKTOP_SESSION', 'XDG_SESSION_ID', 'XDG_SESSION_TYPE',
            'KRYON_TEST_DRIVER', 'KRYON_CAPTURE_PATH'):
    ENV.pop(key, None)
ENV.update(YUE_DESKTOP_RECOVERY='0', SDL_AUDIODRIVER='dummy', ZIRAN_PAR_THREADS='1')
ZIRAN = ENV.get('ZIRAN', 'ziran')
LOCKED = [] if Path('ziran.local.toml').exists() else ['--locked']
WORK = ROOT / 'work/frame-input-adoption'

def run(*args, env=None):
    subprocess.run(list(map(str, args)), check=True, env=env or ENV)

def main():
    run('git', 'check-ignore', str(WORK))
    WORK.mkdir(parents=True, exist_ok=True)
    import fcntl
    with (WORK / 'test.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        ENV['CHOANO_DATA'] = str(WORK / 'native-data')
        libs = subprocess.check_output(['pkg-config', '--libs', 'sdl2', 'cairo',
            'freetype2', 'fontconfig', 'pangocairo'], text=True).strip()
        native_env = dict(ENV, LDLIBS=libs)
        run(ZIRAN, 'build', '--project', *LOCKED, '--target=c', '--exe',
            '--entry', 'frame_input_test:main', '-o', 'build/frame-input-test',
            'tests/frame_input_test.zi', env=native_env)
        run('xvfb-run', '-a', './build/frame-input-test/frame_input_test')
        # Apps validates the node catalog and assets, as a current host does.
        # A test-only package uses the actual portable entry and unchanged art.
        assets = WORK / 'assets'
        if assets.exists(): shutil.rmtree(assets)
        shutil.copytree('assets/choano', assets)
        shutil.copytree('src/locales', assets / 'locales')
        catalog = json.loads(Path('catalog.json').read_text())
        catalog.pop('build_defines', None)
        (assets / 'catalog.json').write_text(json.dumps(catalog))
        guest = WORK / 'guest.zx'
        run(ZIRAN, 'bundle', '--project', *LOCKED, '--define', 'CHOANO_PORTABLE',
            '--define', 'KRYON_HOSTED_UI', '--entry', 'portable:Main',
            '--asset-dir', 'assets/choano=' + str(assets), '-o', guest, 'src/portable.zi')
        with guest.open('rb') as source:
            digest = hashlib.file_digest(source, 'sha256').hexdigest()
        (WORK / 'portable.sha256').write_text(digest)
        compiler_root = Path(ENV.get('ZIRAN_ROOT', Path(shutil.which(ZIRAN)).resolve().parents[2]))
        archive = Path(ENV.get('ZIRAN_LIB', compiler_root / 'build/libziran.a'))
        if not archive.is_file():
            raise RuntimeError('Set ZIRAN_LIB to the existing toolchain libziran.a; this test never rebuilds it')
        portable_env = dict(ENV, LDLIBS=f'{archive} {libs} -lm -lz -ldl -pthread')
        run(ZIRAN, 'build', '--project', *LOCKED, '--target=c', '--exe',
            '--entry', 'portable_input_test:main', '-o', 'build/portable-input-test',
            'tests/portable_input_test.zi', env=portable_env)
        run('xvfb-run', '-a', './build/portable-input-test/portable_input_test')

if __name__ == '__main__': main()
