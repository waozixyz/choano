#!/usr/bin/env python3
"""Exercise KSS and the actual shared Profile host color protocol."""
import os
from pathlib import Path
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
env = {key: value for key, value in os.environ.items() if key not in
       ('DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY', 'DBUS_SESSION_BUS_ADDRESS', 'SESSION_MANAGER')}
env.update(YUE_DESKTOP_RECOVERY='0', ZIRAN_PAR_THREADS='1')
ziran = env.get('ZIRAN', 'ziran')
locked = [] if (ROOT / 'ziran.local.toml').exists() else ['--locked']
toolchain = Path(subprocess.check_output([ziran, 'pkg', 'path', 'ziran', *locked], text=True, env=env).strip())
archive = Path(env.get('ZIRAN_LIB', toolchain / 'build/libziran.a'))
assert archive.is_file(), 'Use the existing locked runtime archive for the Profile protocol test'
libraries = subprocess.check_output(['pkg-config', '--libs', 'sdl2', 'cairo', 'freetype2',
                                      'fontconfig', 'pangocairo'], text=True, env=env).strip()
env['LDLIBS'] = shlex.join([str(archive)]) + ' ' + libraries + ' -lm -lz -ldl -pthread'
subprocess.run([ziran, 'build', '--project', *locked, '--target=c', '--exe',
                '--entry', 'theme_test:main', '-o', 'build/theme-test', 'tests/theme_test.zi'], check=True, env=env)
subprocess.run(['build/theme-test/theme_test'], check=True, env=env)
