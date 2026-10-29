#!/usr/bin/env python3
"""Open only our Choano process on a fresh private Xvfb display."""
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
env = {k: v for k, v in os.environ.items() if k not in
       ('DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY', 'DBUS_SESSION_BUS_ADDRESS', 'SESSION_MANAGER')}
env.update(YUE_DESKTOP_RECOVERY='0', SDL_AUDIODRIVER='dummy', CHOANO_DATA=str(ROOT / 'work/native-profile'))
read_fd, write_fd = os.pipe()
server = subprocess.Popen(['Xvfb', '-displayfd', str(write_fd), '-screen', '0', '1280x1024x24', '-nolisten', 'tcp'],
                          pass_fds=(write_fd,), env=env, stdout=subprocess.DEVNULL)
os.close(write_fd)
app = None
try:
    with os.fdopen(read_fd) as display:
        number = display.readline().strip()
    assert number, 'Private Xvfb did not start'
    env['DISPLAY'] = ':' + number
    app = subprocess.Popen([str(ROOT / 'build/Choano-native')], cwd=ROOT, env=env)
    window = ''
    for _ in range(100):
        assert app.poll() is None, 'Native game exited before opening'
        found = subprocess.run(['xdotool', 'search', '--onlyvisible', '--pid', str(app.pid), '--name', 'Choano'],
                               env=env, text=True, capture_output=True)
        if found.returncode == 0:
            window = found.stdout.splitlines()[0]
            break
        time.sleep(.1)
    assert window, 'Native Choano window missing'
    geometry = subprocess.check_output(['xdotool', 'getwindowgeometry', '--shell', window], env=env, text=True)
    assert 'WIDTH=900' in geometry and 'HEIGHT=680' in geometry, geometry
    subprocess.run(['xdotool', 'windowfocus', window, 'key', 'Return'], check=True, env=env)
    time.sleep(.2)
    subprocess.run(['xdotool', 'key', '1'], check=True, env=env)
    time.sleep(.2)
    subprocess.run(['xdotool', 'keydown', 'Right'], check=True, env=env)
    time.sleep(.4)
    subprocess.run(['xdotool', 'keyup', 'Right', 'key', 'r'], check=True, env=env)
    time.sleep(.3)
    assert app.poll() is None, 'Native game failed during swimming/restart'
    print('Choano local native window/input test passed on private Xvfb.')
finally:
    if app is not None and app.poll() is None:
        app.terminate()
        try:
            app.wait(timeout=10)
        except subprocess.TimeoutExpired:
            app.kill(); app.wait()
    server.terminate()
    server.wait(timeout=10)
